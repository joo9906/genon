"""업로드한 문서에서 템플릿 항목 값을 자동으로 채운다.

## 무엇을 하나

템플릿 채우기는 기본적으로 "템플릿을 고르고 **대화로** 채운다" 이지만, **문서를 올리면
그 내용으로 알아서 채운다.** 사용자가 이미 가진 문서(사업계획서·회의록)를 사내 양식에
옮겨 적는 일이 실제 업무이기 때문이다.

**문서는 대화 도중 언제든, 여러 번 올릴 수 있다.** 호출하는 쪽의 게이트(`chat_api`)와
표식 보관 방식(세션에 해시 **목록**)이 이를 다룬다. 여기서 기억할 것 하나: **`existing`
에는 그때까지 대화로 모인 값이 들어온다** — 비어 있을 수도, 차 있을 수도 있고, 그 값들은
절대 안 밀린다.

## 문서를 "첫 발화" 자리에 넣지 않는 이유 셋

처음 떠올리는 방법은 파싱한 문서를 `question` 으로 넘겨 기존 추출 경로를 그대로 태우는
것이다. 그러면 세 자리에서 깨진다:

1. **`Config.MAX_MESSAGE_CHARS`(기본 20,000)에서 조용히 잘린다.** `chat_api` 가
   `question[:상한]` 으로 자르고 그 사실을 아무 데도 남기지 않는다 — 사업계획서·협상서는
   그 길이를 넘고, 잘린 뒷부분의 값은 **없는 것이 된다.**
2. **프롬프트의 성격이 다르다.** `extract_system.j2` 는 "이번 턴 사용자가 말한 것" 만
   담으라고 못박은 지시문이라, 문서를 발화로 주면 지움 지시·본문 추가 의도를 문서
   문장에서 찾아내려 든다. 그래서 프롬프트를 따로 뒀다(`document_system.j2`).
3. **덮어쓰기 방향이 반대다.** 대화 추출은 "사용자가 방금 말한 값이 이긴다" 가 맞지만,
   문서 자동 채움은 **사용자가 이미 넣은 값을 절대 덮어선 안 된다**(요구 확정). 덮으면
   사용자는 자기가 넣은 값이 사라진 것을 화면에서 우연히 발견한다.

## 규약 넷

- **빈 항목만 채운다.** 이미 값이 있는 항목은 프롬프트에서 아예 빼고(토큰), 그래도 온
  값은 버리고 건수만 센다(`conflicts`). 두 층으로 막는 이유는 프롬프트 지시를 보장으로
  보지 않는다는 저장소 규약이다(CLAUDE.md §5).
  **예외는 하나 — 사용자가 "문서 내용으로 바꿔줘" 라고 명시한 턴**(`overwrite=True`)이다.
  그때는 `existing` 을 보호하지 않고 찬 항목도 묻는다. 판정(추출 LLM 의 `use_document`)은
  `field_judge` 가, 덮을지 말지는 이 인자 하나가 정한다.
- **조각마다 남은 항목만 묻는다.** 앞 조각이 채운 항목은 뒤 조각의 프롬프트에서 빠지므로
  **앞 조각이 이긴다.** 문서 앞쪽이 대개 표지·개요라 항목 값이 정면으로 적혀 있고, 뒤쪽
  본문의 스쳐 지나가는 언급보다 정확하다.
- **다 채우면 남은 조각을 부르지 않는다.** 조각 수가 곧 비용이 되지 않게 하는 유일한
  장치다 — 40조각 문서에서 항목 5개가 첫 조각에 다 있으면 호출은 1회다.
- **반복 묶음이 있으면 새 묶음 하나를 더 묻는다** (`repeat`). 문서·파일이 여럿이면 주제마다
  묶음이 늘어나야 하는데, 지금 있는 묶음만 물으면 다 찬 순간 "채울 자리가 없다" 며 멈춘다.
  그래서 조각마다 **지금까지 모인 값**으로 목록을 다시 펴고(`field_specs(extra_copy=True)`)
  다음 번호를 프롬프트에 적는다 — 앞 조각이 2번까지 채웠으면 뒤 조각은 3번부터 쓴다.
  번호를 안 알려 주면 모델이 조각마다 1번부터 다시 세고, 그 값은 덮어쓰기 금지에 걸려
  **두 번째 주제가 조용히 버려진다.** 대가로 반복 템플릿은 묶음 상한까지 조각을 끝까지 읽는다.
- **항목명은 화이트리스트가 거른다** (`field_judge.parse_updates`). 값의 진위는 코드가
  판정하지 않는다(요구 확정) — 채운 값을 답변에 전부 나열해 사용자가 그 자리에서 고친다.

## 실패는 대화를 막지 않는다

문서 자동 채움이 실패해도 예외를 올리지 않는다. 사용자는 원래 하려던 일(대화로 채우기)을
계속할 수 있어야 하고, 문서를 올린 턴에 오류 화면을 받으면 **템플릿 채우기 자체가 안 되는
것으로 보인다.** 다만 실패 사실은 `error_type` 으로 돌려주고 호출부가 답변에 한 줄 싣는다
— 조용히 넘기면 "문서를 올렸는데 아무 일도 안 일어났다" 가 된다.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field as dataclass_field

from .config import Config
from .field_judge import parse_updates
from .hwpx_fields import missing_field_names
from .llm import CONFIG_MISSING, STREAM_UNSUPPORTED, llm_call_async, llm_stream_async
from .logging_utils import log_info, log_warning
from .prompt_loader import PromptRenderError
from .prompts import build_document_prompts, build_group_prompts, build_topic_prompts
from .template_index import field_specs


# 조각 경계 판정용. 전처리기·hwpx 파서 산출물이 모두 `#` 표기를 쓴다.
def _is_heading(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#") and stripped.lstrip("#").startswith((" ", "\t"))


# 예산의 이 비율을 넘긴 뒤 제목을 만나면 거기서 끊는다. 조각이 절 단위로 떨어져야
# 그 안의 값이 무엇에 관한 것인지 모델이 읽을 수 있다.
_HEADING_BREAK_RATIO = 0.6


@dataclass
class PrefillOutcome:
    """자동 채움 결과 + 무엇을 얼마나 버렸는지."""

    values: dict = dataclass_field(default_factory=dict)
    chunk_count: int = 0        # 문서를 나눈 조각 수
    chunks_called: int = 0      # 그중 실제로 LLM 을 부른 수 (다 채우면 멈춘다)
    chunks_failed: int = 0      # 호출이 실패한 수
    rejected: int = 0           # 템플릿에 없는 항목명 (환각률 지표의 원천)
    conflicts: int = 0          # 이미 값이 있는 항목에 다시 온 값 (버렸다)
    error_type: str = ""        # 전량 실패일 때만 의미가 있다
    is_transport_error: bool = False
    topic_count: int = 0        # 반복 묶음 템플릿에서 뽑은 주제 수 (0 이면 주제 경로를 안 탔다)
    groups_failed: int = 0      # 그중 채우지 못한 묶음 수
    fallback: bool = False      # 주제를 못 뽑아 비상 경로(묶음 자리를 상한까지 펼침)로 채웠다

    @property
    def ok(self) -> bool:
        """한 조각이라도 응답을 받았는가. 값이 0개인 것은 실패가 아니다.

        문서에 항목 값이 없으면 `{"updates": {}}` 가 정상 답이다 — 그것을 실패로 보면
        사용자에게 "문서를 못 읽었다" 고 잘못 말한다.
        """
        return self.chunks_called > self.chunks_failed

    @property
    def config_missing(self) -> bool:
        return self.error_type == CONFIG_MISSING


def split_document(text: str, budget: int) -> list:
    """문서를 `budget` 자 이하 조각으로 나눈다. **버리는 글자는 없다.**

    자르는 자리는 줄 경계이고, 예산의 60% 를 넘긴 뒤 제목을 만나면 그 앞에서 끊는다.

    FAQ 단위의 `chunking.split_for_context` 와 같은 규칙이다. **배포 단위 간 import 가
    금지돼 있어 강제된 사본이고**, 이쪽은 조각별 몫(quota) 배분이 없어 더 짧다 — 006 은
    개수를 뽑는 것이 아니라 **정해진 항목을 채우는** 일이라 나눌 몫이 없다.
    """
    if not text or budget <= 0:
        return []

    chunks: list = []
    current: list = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
        current, size = [], 0

    for line in text.split("\n"):
        if len(line) > budget:
            # 줄 하나가 예산을 넘는다 (한 줄 HTML 표가 대표적). 여기서 나누지 않으면 이
            # 조각이 통째로 상한을 넘겨 LLM 이 뒤를 잘라 버린다 — 그 절단은 안 보인다.
            flush()
            chunks.extend(
                line[start: start + budget]
                for start in range(0, len(line), budget)
                if line[start: start + budget].strip()
            )
            continue

        if current and size + len(line) + 1 > budget:
            flush()
        elif current and size >= budget * _HEADING_BREAK_RATIO and _is_heading(line):
            flush()

        current.append(line)
        size += len(line) + 1

    flush()
    return chunks


def _pending_specs(specs: list, taken: dict, existing: dict) -> list:
    """아직 값이 없는 항목만. 템플릿에 원래 적혀 있던 항목(`spec.filled`)도 뺀다.

    **"무엇이 부족한가" 는 `missing_field_names` 가 정본이다** — 같은 조건을 여기 다시
    적으면 `/chat/prefill` 의 `no_pending_fields` 게이트와 이 함수가 갈릴 수 있고, 그
    상태는 "채울 자리가 없다며 건너뛰는데 정작 빈 항목이 남아 있는" 것으로 나타난다.
    여기서 더하는 것은 `taken`(이번 문서의 앞 조각이 이미 채운 것)뿐이다.
    """
    pending = set(missing_field_names(specs, existing))
    return [spec for spec in specs if spec.name in pending and spec.name not in taken]


_UPDATES_OPEN_RE = re.compile(r'"updates"\s*:\s*\{')
_DECODER = json.JSONDecoder()


class _UpdatesScanner:
    """스트리밍 응답에서 `"updates"` 객체의 **닫힌** `키: 값` 쌍만 꺼낸다.

    값 뒤에 `,` 나 `}` 가 와야 닫힌 것으로 본다 — 숫자 `12` 는 다음 델타에서 `123` 이
    될 수 있다. 모양이 어긋나면 더 꺼내지 않고 멈춘다. 최종 채택은 어차피 응답 전체를
    다시 판정하므로(`prefill_from_document`), 여기서 놓친 쌍은 진행 줄만 늦게 나온다.
    """

    def __init__(self) -> None:
        self._text = ""
        self._pos = None
        self._stopped = False

    def _skip(self, index: int) -> int:
        while index < len(self._text) and self._text[index].isspace():
            index += 1
        return index

    def feed(self, piece: str) -> list:
        self._text += piece
        pairs: list = []
        if self._stopped:
            return pairs
        if self._pos is None:
            match = _UPDATES_OPEN_RE.search(self._text)
            if match is None:
                return pairs
            self._pos = match.end()
        while True:
            start = self._skip(self._pos)
            if start >= len(self._text):
                break
            if self._text[start] == ",":
                self._pos = start + 1
                continue
            if self._text[start] == "}":
                self._stopped = True
                break
            try:
                key, colon = _DECODER.raw_decode(self._text, start)
            except ValueError:
                break  # 키가 아직 안 닫혔다
            colon = self._skip(colon)
            if colon >= len(self._text):
                break
            if self._text[colon] != ":" or not isinstance(key, str):
                self._stopped = True
                break
            value_start = self._skip(colon + 1)
            if value_start >= len(self._text):
                break
            try:
                value, end = _DECODER.raw_decode(self._text, value_start)
            except ValueError:
                break  # 값이 아직 안 닫혔다
            if self._skip(end) >= len(self._text):
                break  # 뒤를 봐야 닫혔는지 안다
            self._pos = end
            pairs.append((key, value))
        return pairs


async def _stream_chunk(system_prompt: str, user_prompt: str, *, allowed_names, blocked,
                        on_progress, index: int, total: int, announced: dict):
    """조각 하나를 스트리밍으로 부르고, 닫힌 쌍마다 `field` 진행 이벤트를 낸다.

    판정은 최종 채택과 **같은 판정기 · 같은 조건**이다 — 쌍 하나를 `{"updates": {…}}` 로
    감싸 `parse_updates` 에 태우고, `blocked`(사용자 값 · 앞 조각 값)는 흘리지 않는다.
    조건이 갈리면 흘린 줄과 실제로 채운 값이 어긋나고 그 어긋남은 오류로 드러나지 않는다.
    흘린 것은 `announced` 에 `{항목명: 값}` 으로 남긴다.
    """
    scanner = _UpdatesScanner()

    async def _on_delta(piece: str) -> None:
        for key, value in scanner.feed(piece):
            wrapped = json.dumps({"updates": {key: value}}, ensure_ascii=False)
            for name, text in parse_updates(wrapped, allowed_names).updates.items():
                if name in blocked or name in announced:
                    continue
                announced[name] = text
                await on_progress({
                    "status": "field", "index": index, "total": total,
                    "name": name, "value": text,
                })

    return await llm_stream_async(system_prompt, user_prompt, _on_delta)


# ─────────────────────────────────────────────────────────────
# 반복 묶음 — 주제를 먼저 뽑고 묶음마다 따로 채운다
# ─────────────────────────────────────────────────────────────
# 한 호출에 "주제를 세면서 내용도 쓰라" 고 맡기면, 추론을 끈 모델은 [필드 목록] 에 보이는
# 묶음 자리(지금 묶음 + 1)만 채우고 멈춘다 — 본문 8개 분량 문서에서 1~2개만 나왔다.
#
# 1. **주제 뽑기** (`topic_*.md`) — 조각마다 제목과 시작 줄만 받는다. 개수를 코드가 쥔다.
# 2. **묶음 밖 항목** — 지금까지의 조각 경로(`_fill_by_chunks`)로 채운다.
# 3. **묶음 k** (`group_*.md`) — 그 주제의 문서 구간만 보여 주고 묶음 하나씩 채운다.
#    묶음끼리 항목 이름이 겹치지 않으므로 함께 돌린다(`DOC_GROUP_CONCURRENCY`).
#
# 주제를 하나도 못 뽑으면(호출 실패 · 이상한 응답 · 0개) **비상 경로**다 — 조각 경로로
# 돌아가되 묶음 자리를 상한까지 펼쳐 보여 준다(`repeat_document.md` 가 "남는 번호는 뺀다" 를
# 못박는다). 지금 묶음 + 1 로 돌아가면 다시 1~2개만 채운다.
_TOPIC_TITLE_CHARS = 200


@dataclass(frozen=True)
class Topic:
    title: str
    anchor: str
    chunk_index: int   # 이 주제를 뽑은 조각 (1부터) — 위치를 못 찾으면 이 조각을 보여 준다


def _loads_object(raw: str):
    """응답에서 JSON 객체 하나를 관대하게 꺼낸다 (`field_judge` 와 같은 규칙). 실패 시 None."""
    text = raw or ""
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1]):
        try:
            result = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        return result if isinstance(result, dict) else None
    return None


def parse_topics(raw: str):
    """주제 응답 → `[(title, anchor)]`. 모양이 틀리면 None, 빈 목록은 `[]`."""
    parsed = _loads_object(raw)
    if parsed is None or not isinstance(parsed.get("topics"), list):
        return None
    topics: list = []
    for item in parsed["topics"]:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())[:_TOPIC_TITLE_CHARS]
        anchor = str(item.get("anchor") or "").strip()
        if title:
            topics.append((title, anchor))
    return topics


def _topic_key(title: str) -> str:
    return re.sub(r"\s+", "", title)


async def _plan_topics(chunks: list, repeat, protected: dict, template_id: str,
                       on_progress) -> list:
    """조각마다 주제를 묻고 문서 순서대로 모은다. **실패하면 빈 목록**(비상 경로로 간다).

    상한은 남은 묶음 자리다 — 이미 값이 든 묶음 뒤에 이어 쓰므로.
    """
    used = repeat.used_count(protected, Config.MAX_REPEAT, Config.MAX_REPEAT_ITEMS)
    room = Config.MAX_REPEAT - used
    if room <= 0:
        return []
    topics: list = []
    seen: set = set()
    started = time.monotonic()
    for index, chunk in enumerate(chunks, start=1):
        if len(topics) >= room:
            break
        try:
            system_prompt, user_prompt = build_topic_prompts(
                repeat, chunk, chunk_index=index, chunk_total=len(chunks),
                max_topics=room - len(topics), template_id=template_id,
            )
        except PromptRenderError as exc:
            log_warning(
                "주제 뽑기 프롬프트 생성 실패 — 비상 경로로 채운다",
                event="prefill_topics_failed",
                error_type=type(exc).__name__,
                status="prompt_render_failed",
            )
            return []
        result = await llm_call_async(system_prompt, user_prompt)
        parsed = parse_topics(result.content) if result.ok else None
        if parsed is None:
            log_warning(
                "주제를 뽑지 못해 비상 경로로 채운다",
                event="prefill_topics_failed",
                error_type=result.error_type or "InvalidTopics",
                status=f"chunk={index}/{len(chunks)}",
            )
            return []
        for title, anchor in parsed:
            key = _topic_key(title)
            if key in seen:
                continue  # 조각 경계에 걸린 주제가 두 번 나온다
            seen.add(key)
            topics.append(Topic(title=title, anchor=anchor, chunk_index=index))
            if len(topics) >= room:
                break
    log_info(
        "문서 주제 뽑기 완료",
        event="prefill_topics_planned",
        item_count=len(topics),
        duration_ms=int((time.monotonic() - started) * 1000),
        status=f"chunks={len(chunks)} room={room}",
    )
    if topics and on_progress is not None:
        await on_progress({"status": "planned", "topics": [topic.title for topic in topics]})
    return topics


def _anchor_text(anchor: str) -> str:
    """시작 줄에서 찾을 글자 — 마크다운 제목 기호와 앞뒤 공백을 뗀다."""
    return anchor.strip().lstrip("#").strip()


def _topic_sections(text: str, chunks: list, topics: list) -> list:
    """주제마다 보여 줄 문서 구간. 시작 줄을 문서 순서대로 찾아 다음 주제 앞까지 자른다.

    시작 줄도 제목도 못 찾은 주제는 **그 주제를 뽑은 조각 전체**를 보여 준다 — 구간이 넓어질
    뿐 값이 사라지지는 않는다. 구간은 `DOC_GROUP_SECTION_CHARS` 에서 자르고 로그를 남긴다.
    """
    starts: list = []
    cursor = 0
    for topic in topics:
        found = -1
        for needle in (_anchor_text(topic.anchor), topic.title):
            if needle:
                found = text.find(needle, cursor)
                if found != -1:
                    break
        if found == -1:
            starts.append(None)
            continue
        starts.append(text.rfind("\n", 0, found) + 1)
        cursor = found + 1

    sections: list = []
    located = 0
    for index, topic in enumerate(topics):
        start = starts[index]
        if start is None:
            section = chunks[topic.chunk_index - 1]
        else:
            located += 1
            end = next((s for s in starts[index + 1:] if s is not None and s > start), len(text))
            section = text[start:end].strip()
        if len(section) > Config.DOC_GROUP_SECTION_CHARS:
            log_warning(
                "주제 구간이 길어 앞부분만 보여 준다",
                event="prefill_group_section_truncated",
                item_count=len(section) - Config.DOC_GROUP_SECTION_CHARS,
                status=f"group={index + 1}/{len(topics)}",
            )
            section = section[: Config.DOC_GROUP_SECTION_CHARS]
        sections.append(section)
    if located < len(topics):
        log_info(
            "시작 줄을 못 찾은 주제는 그 조각 전체를 보여 준다",
            event="prefill_topic_unlocated",
            item_count=len(topics) - located,
        )
    return sections


async def _fill_groups(outcome: PrefillOutcome, text: str, chunks: list, topics: list,
                       specs: list, repeat, allowed_names, protected: dict, template_id: str,
                       on_progress) -> None:
    """묶음 k 마다 그 주제의 구간으로 채운다. 묶음 하나가 실패해도 나머지는 채운다."""
    used = repeat.used_count(protected, Config.MAX_REPEAT, Config.MAX_REPEAT_ITEMS)
    sections = _topic_sections(text, chunks, topics)
    semaphore = asyncio.Semaphore(Config.DOC_GROUP_CONCURRENCY)
    # 채택과 진행 이벤트는 한 번에 하나씩 — 호출부는 콜백이 직렬로 불린다고 전제한다.
    lock = asyncio.Lock()
    total = len(topics)

    async def _emit(event: dict) -> None:
        if on_progress is not None:
            await on_progress(event)

    async def _one(position: int, topic: Topic, section: str) -> None:
        k = used + position + 1
        label = topic.title
        group_fields = repeat.group_specs(specs, k, 1)
        allowed_k = {name for name in allowed_names if repeat.index_of(name) == k}
        error_type = ""
        result = None
        async with semaphore:
            async with lock:
                await _emit({"status": "start", "index": position + 1, "total": total,
                             "label": label, "filled": []})
            started = time.monotonic()
            try:
                system_prompt, user_prompt = build_group_prompts(
                    group_fields, repeat, k, topic.title, section, template_id=template_id,
                )
                result = await llm_call_async(system_prompt, user_prompt)
                error_type = result.error_type
            except Exception as exc:  # noqa: BLE001 - 프롬프트 부재 · 클라이언트 초기화 실패
                error_type = type(exc).__name__
        async with lock:
            outcome.chunks_called += 1
            log_info(
                "묶음 채우기",
                event="prefill_group_done",
                duration_ms=int((time.monotonic() - started) * 1000),
                status=f"group={k} ok={int(bool(result is not None and result.ok))}",
            )
            if result is None or not result.ok:
                outcome.chunks_failed += 1
                outcome.groups_failed += 1
                outcome.error_type = error_type
                if result is not None:
                    outcome.is_transport_error = result.is_transport_error
                await _emit({"status": "failed", "index": position + 1, "total": total,
                             "label": label, "filled": []})
                return
            intent = parse_updates(result.content, allowed_k)
            outcome.rejected += len(intent.rejected)
            newly_filled: list = []
            for name, value in intent.updates.items():
                if name in protected or name in outcome.values:
                    outcome.conflicts += 1
                    continue
                outcome.values[name] = value
                newly_filled.append(name)
            await _emit({
                "status": "done", "index": position + 1, "total": total, "label": label,
                "filled": newly_filled,
                "values": {name: outcome.values[name] for name in newly_filled},
                "announced": [],
            })

    await asyncio.gather(*(
        _one(position, topic, section)
        for position, (topic, section) in enumerate(zip(topics, sections))
    ))


async def prefill_from_document(
    specs: list,
    allowed_names,
    document: str,
    existing: dict,
    template_id: str = "",
    on_progress=None,
    overwrite: bool = False,
    repeat=None,
):
    """문서에서 **빈 항목만** 채운다. 예외를 올리지 않는다.

    Args:
        specs: 템플릿의 `FieldSpec` 목록.
        allowed_names: 화이트리스트 (`TurnContext.allowed_names`).
        document: 업로드 문서 본문 (전처리기 마크다운 또는 hwpx 파싱 결과).
        existing: 이미 수집된 {항목명: 값}. **이 항목은 건드리지 않는다**(`overwrite` 제외).
        on_progress: 조각을 처리할 때마다 부르는 선택적 async 콜백. dict 하나를 받는다 —
            `status` 는 `start` · `field`(응답을 받는 도중 항목 하나가 닫혔다: `name`·
            `value`) · `done`(`filled`·`values`·`announced` — 이미 `field` 로 흘린
            항목) · `failed`(`discarded` — 흘렸지만 반영하지 않은 항목).
            **콜백이 있으면 LLM 을 스트리밍으로 부른다** — 배포가 스트리밍을 안 받으면
            (`STREAM_UNSUPPORTED`) 비스트리밍으로 돌아가고 `field` 없이 `done` 만 간다.
            **문구를 만들지 않는다** — 사람이 읽을 문장은 호출부(`/chat/prefill/stream`)가
            짓는다. 이 함수는 도메인 계층이라 텍스트 조립을 모른다(006 의 계층 규약,
            `chat_reply.py` 가 문구를 짓는 것과 같은 경계). 콜백이 없으면
            (`/chat/prefill` 비스트리밍 경로) 아무 일도 하지 않는다.
        overwrite: 사용자가 문서 내용으로 **바꾸라고 명시한** 턴. `existing` 을 보호하지
            않는다 — 찬 항목도 프롬프트에 넣고, 온 값을 `conflicts` 로 버리지 않는다.
            앞 조각 우선은 그대로다.
        repeat: 템플릿의 반복 묶음(`RepeatGroup`). 주면 `specs` 는 **1번만 든 템플릿 목록**
            이고, 조각마다 모인 값으로 펴서 새 묶음 하나까지 묻는다(모듈 docstring).

    Returns:
        PrefillOutcome.
    """
    outcome = PrefillOutcome()
    # 보호할 값. 덮어쓰기 턴이면 비운다 — 아래 세 판정(묻을 항목 · 흘릴 항목 · 버릴 값)이
    # 이 하나를 본다. 셋 중 하나만 `existing` 을 보면 흘린 줄과 채운 값이 갈린다.
    protected = {} if overwrite else dict(existing or {})
    text = (document or "").strip()
    if not text or not specs:
        return outcome

    chunks = split_document(text, Config.DOC_CHUNK_CHARS)
    if len(chunks) > Config.DOC_MAX_CHUNKS:
        # 여기 걸린 문서만 뒤를 안 본다. 조용히 자르지 않고 로그로 낸다 — 조각 수 상한은
        # 문서 길이가 곧 LLM 비용이 되지 않게 막는 최후 방어선이다.
        log_warning(
            "문서가 매우 길어 뒷부분은 자동 채움에서 제외했다",
            event="prefill_document_truncated",
            item_count=len(chunks) - Config.DOC_MAX_CHUNKS,
        )
        chunks = chunks[: Config.DOC_MAX_CHUNKS]
    outcome.chunk_count = len(chunks)
    if repeat is not None:
        topics = await _plan_topics(chunks, repeat, protected, template_id, on_progress)
        if topics:
            outcome.topic_count = len(topics)
            # 묶음 밖 항목(제목 · 기간 · 담당자 …)은 지금까지와 같은 경로로 채운다. 묶음 이름은
            # 받지 않는다 — 여기서 `본문 1` 이 오면 아래 묶음 1 의 값이 덮어쓰기 금지에 걸린다.
            plain = [spec for spec in specs if spec.name not in repeat.template_names]
            group_names = repeat.allowed_names(Config.MAX_REPEAT, Config.MAX_REPEAT_ITEMS)
            if plain:
                await _fill_by_chunks(
                    outcome, chunks, plain, set(allowed_names) - group_names, protected,
                    template_id, on_progress, repeat=None,
                )
            await _fill_groups(
                outcome, text, chunks, topics, specs, repeat, allowed_names, protected,
                template_id, on_progress,
            )
            _log_done(outcome)
            return outcome
        # 비상 경로 — 주제를 못 뽑았다. 묶음 자리를 상한까지 펼쳐 한 번에 채운다.
        outcome.fallback = True

    await _fill_by_chunks(
        outcome, chunks, specs, allowed_names, protected, template_id, on_progress,
        repeat=repeat, min_groups=Config.MAX_REPEAT if repeat is not None else 0,
    )
    _log_done(outcome)
    return outcome


def _log_done(outcome: PrefillOutcome) -> None:
    log_info(
        "문서 자동 채움 완료",
        event="prefill_done",
        item_count=len(outcome.values),
        status=(
            f"chunks={outcome.chunks_called}/{outcome.chunk_count}"
            f" failed={outcome.chunks_failed}"
            f" rejected={outcome.rejected}"
            f" conflicts={outcome.conflicts}"
            f" topics={outcome.topic_count} groups_failed={outcome.groups_failed}"
            f" fallback={int(outcome.fallback)}"
        ),
    )


async def _fill_by_chunks(outcome: PrefillOutcome, chunks: list, specs: list, allowed_names,
                          protected: dict, template_id: str, on_progress, *, repeat=None,
                          min_groups: int = 0) -> None:
    """조각마다 **아직 빈 항목만** 묻고 `outcome` 에 채운다 — 반복 묶음이 없거나(그대로),
    주제를 못 뽑은 비상 경로(`min_groups` = 상한)이거나, 묶음 밖 항목(`repeat=None`)일 때.
    """
    # 진행을 보는 호출부(`/chat/prefill/stream`)가 있을 때만 스트리밍으로 부른다.
    streaming = on_progress is not None

    for index, chunk in enumerate(chunks, start=1):
        merged = {**protected, **outcome.values}
        candidates = (
            field_specs(specs, repeat, merged, extra_copy=True, min_groups=min_groups)
            if repeat is not None else specs
        )
        pending = _pending_specs(candidates, outcome.values, protected)
        if not pending:
            # 다 채웠다. 남은 조각을 부를 이유가 없다 (조각 수 = 비용 방지).
            break

        if on_progress is not None:
            await on_progress({
                "status": "start", "index": index, "total": len(chunks), "filled": [],
            })

        try:
            system_prompt, user_prompt = build_document_prompts(
                pending,
                chunk,
                chunk_index=index,
                chunk_total=len(chunks),
                template_id=template_id,
                repeat=repeat,
                values=merged,
            )
        except PromptRenderError as exc:
            # 이미지에 프롬프트 디렉토리를 안 넣은 배포 실수다. 조각 수만큼 두드릴 이유가
            # 없고, LLM 실패와 따로 남겨야 운영에서 손을 쓸 수 있다.
            log_warning(
                "자동 채움 프롬프트 생성 실패",
                event="prompt_render_failed",
                error_type=type(exc).__name__,
            )
            outcome.error_type = type(exc).__name__
            outcome.chunks_failed += 1
            outcome.chunks_called += 1
            if on_progress is not None:
                await on_progress({
                    "status": "failed", "index": index, "total": len(chunks), "filled": [],
                })
            break

        outcome.chunks_called += 1
        announced: dict = {}
        chunk_started = time.monotonic()
        try:
            if on_progress is not None and streaming:
                result = await _stream_chunk(
                    system_prompt,
                    user_prompt,
                    allowed_names=allowed_names,
                    blocked=set(protected) | set(outcome.values),
                    on_progress=on_progress,
                    index=index,
                    total=len(chunks),
                    announced=announced,
                )
                if result.error_type == STREAM_UNSUPPORTED:
                    # 이 배포는 스트리밍을 안 받는다. 남은 조각도 같으므로 다시 묻지 않는다.
                    streaming = False
                    result = await llm_call_async(system_prompt, user_prompt)
            else:
                result = await llm_call_async(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001 - 클라이언트 초기화 실패 등
            outcome.chunks_failed += 1
            outcome.error_type = type(exc).__name__
            if on_progress is not None:
                await on_progress({
                    "status": "failed", "index": index, "total": len(chunks), "filled": [],
                    "discarded": list(announced),
                })
            break
        # 어느 조각이 느린지(입력이 긴가 · 출력이 긴가)를 가르려면 조각별 시간이 있어야 한다.
        log_info(
            "문서 조각 확인",
            event="prefill_chunk_done",
            item_count=len(announced),
            duration_ms=int((time.monotonic() - chunk_started) * 1000),
            status=f"chunk={index}/{len(chunks)} ok={int(result.ok)} stream={int(streaming)}",
        )

        if not result.ok:
            outcome.chunks_failed += 1
            outcome.error_type = result.error_type
            outcome.is_transport_error = result.is_transport_error
            if on_progress is not None:
                # 흘린 뒤 끊겼으면 화면에 이미 나간 값이 있다 — 반영하지 않았다고 말해야 한다.
                await on_progress({
                    "status": "failed", "index": index, "total": len(chunks), "filled": [],
                    "discarded": list(announced),
                })
            if result.error_type == CONFIG_MISSING:
                # 재시도로 풀리지 않는 배포 문제다 — 조각 수만큼 부르지 않는다
                # (긴 문서 커버 작업에서 글다듬이가 밟은 것과 같은 규약).
                break
            continue

        # 대화 경로와 **같은 판정기**를 태운다. 템플릿에 없는 항목명은 여기서 잘린다.
        intent = parse_updates(result.content, allowed_names)
        outcome.rejected += len(intent.rejected)
        newly_filled: list = []
        for name, value in intent.updates.items():
            if name in protected or name in outcome.values:
                # 프롬프트에서 뺀 항목인데도 왔다. 지시를 보장으로 보지 않으므로 여기서
                # 버린다 — 채택하면 사용자 값·앞 조각 값이 문서 뒤쪽 언급에 밀린다.
                outcome.conflicts += 1
                continue
            outcome.values[name] = value
            newly_filled.append(name)

        if on_progress is not None:
            await on_progress({
                "status": "done", "index": index, "total": len(chunks), "filled": newly_filled,
                "values": {name: outcome.values[name] for name in newly_filled},
                # 흘린 값과 최종값이 같은 항목 — 호출부가 두 번 말하지 않게.
                "announced": [
                    name for name in newly_filled if announced.get(name) == outcome.values[name]
                ],
            })
