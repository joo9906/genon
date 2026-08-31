"""업로드한 문서에서 템플릿 항목 값을 자동으로 채운다 (2026-08-31 신규).

## 무엇이 달라졌나

템플릿 채우기는 "템플릿을 고르고 **대화로** 채운다" 였다. 요구가 하나 붙었다 —
**채팅 시작 시 문서를 올리면 그 내용으로 알아서 채운다.** 사용자가 이미 가진 문서
(사업계획서·회의록)를 사내 양식에 옮겨 적는 일이 실제 업무이기 때문이다.

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
- **조각마다 남은 항목만 묻는다.** 앞 조각이 채운 항목은 뒤 조각의 프롬프트에서 빠지므로
  **앞 조각이 이긴다.** 문서 앞쪽이 대개 표지·개요라 항목 값이 정면으로 적혀 있고, 뒤쪽
  본문의 스쳐 지나가는 언급보다 정확하다.
- **다 채우면 남은 조각을 부르지 않는다.** 조각 수가 곧 비용이 되지 않게 하는 유일한
  장치다 — 40조각 문서에서 항목 5개가 첫 조각에 다 있으면 호출은 1회다.
- **항목명은 화이트리스트가 거른다** (`field_judge.parse_updates`). 값의 진위는 코드가
  판정하지 않는다(요구 확정) — 채운 값을 답변에 전부 나열해 사용자가 그 자리에서 고친다.

## 실패는 대화를 막지 않는다

문서 자동 채움이 실패해도 예외를 올리지 않는다. 사용자는 원래 하려던 일(대화로 채우기)을
계속할 수 있어야 하고, 문서를 올린 턴에 오류 화면을 받으면 **템플릿 채우기 자체가 안 되는
것으로 보인다.** 다만 실패 사실은 `error_type` 으로 돌려주고 호출부가 답변에 한 줄 싣는다
— 조용히 넘기면 "문서를 올렸는데 아무 일도 안 일어났다" 가 된다.
"""

from dataclasses import dataclass, field as dataclass_field

from .config import Config
from .field_judge import parse_updates
from .llm import CONFIG_MISSING, llm_call_async
from .logging_utils import log_info, log_warning
from .prompt_loader import PromptRenderError
from .prompts import build_document_prompts


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
    """아직 값이 없는 항목만. 템플릿에 원래 적혀 있던 항목(`spec.filled`)도 뺀다."""
    return [
        spec
        for spec in specs
        if spec.name not in taken and spec.name not in existing and not spec.filled
    ]


async def prefill_from_document(specs: list, allowed_names, document: str, existing: dict):
    """문서에서 **빈 항목만** 채운다. 예외를 올리지 않는다.

    Args:
        specs: 템플릿의 `FieldSpec` 목록.
        allowed_names: 화이트리스트 (`TurnContext.allowed_names`).
        document: 업로드 문서 본문 (전처리기 마크다운 또는 hwpx 파싱 결과).
        existing: 이미 수집된 {항목명: 값}. **이 항목은 건드리지 않는다.**

    Returns:
        PrefillOutcome.
    """
    outcome = PrefillOutcome()
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

    for index, chunk in enumerate(chunks, start=1):
        pending = _pending_specs(specs, outcome.values, existing)
        if not pending:
            # 다 채웠다. 남은 조각을 부를 이유가 없다 (조각 수 = 비용 방지).
            break

        try:
            system_prompt, user_prompt = build_document_prompts(
                pending, chunk, chunk_index=index, chunk_total=len(chunks)
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
            break

        outcome.chunks_called += 1
        try:
            result = await llm_call_async(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001 - 클라이언트 초기화 실패 등
            outcome.chunks_failed += 1
            outcome.error_type = type(exc).__name__
            break

        if not result.ok:
            outcome.chunks_failed += 1
            outcome.error_type = result.error_type
            outcome.is_transport_error = result.is_transport_error
            if result.error_type == CONFIG_MISSING:
                # 재시도로 풀리지 않는 배포 문제다 — 조각 수만큼 부르지 않는다
                # (긴 문서 커버 작업에서 글다듬이가 밟은 것과 같은 규약).
                break
            continue

        # 대화 경로와 **같은 판정기**를 태운다. 템플릿에 없는 항목명은 여기서 잘린다.
        intent = parse_updates(result.content, allowed_names)
        outcome.rejected += len(intent.rejected)
        for name, value in intent.updates.items():
            if name in existing or name in outcome.values:
                # 프롬프트에서 뺀 항목인데도 왔다. 지시를 보장으로 보지 않으므로 여기서
                # 버린다 — 채택하면 사용자 값·앞 조각 값이 문서 뒤쪽 언급에 밀린다.
                outcome.conflicts += 1
                continue
            outcome.values[name] = value

    log_info(
        "문서 자동 채움 완료",
        event="prefill_done",
        item_count=len(outcome.values),
        status=(
            f"chunks={outcome.chunks_called}/{outcome.chunk_count}"
            f" failed={outcome.chunks_failed}"
            f" rejected={outcome.rejected}"
            f" conflicts={outcome.conflicts}"
        ),
    )
    return outcome
