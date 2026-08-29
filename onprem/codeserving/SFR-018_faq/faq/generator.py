"""FAQ 생성 — LLM 호출 → 스키마 검증 → 근거 대조 → 중복 제거 → 부족분 재요청.

## 코드가 판정하고 LLM 은 만들기만 한다

이 저장소의 다른 기능과 같은 분업이다 (006 은 채워짐 판정을, 번역은 구조 보존을
코드가 한다). FAQ 에서 코드가 쥐는 것은 셋이다:

1. **개수** — 관리자 상한 안으로 깎고, 실제로 몇 개가 나왔는지 센다.
   프롬프트로 "{{count}}개 만들어라"라고 하지만 그건 요청이지 보장이 아니다.
2. **근거** — `evidence.py` 가 문서 원문과 대조한다. 통과 못한 항목은 기각한다.
3. **중복** — 같은 질문을 정규화해서 거른다. 부족분 재요청 때 특히 잘 겹친다.

기각한 건수는 전부 `FaqResult` 에 담아 응답·로그로 노출한다. 조용히 버리면
"왜 5개 요청했는데 3개만 나왔는지" 알 수 없다 (실패 침묵 처리 금지).

## 문서 전체가 후보다 (2026-08-29)

문서를 LLM 예산 크기의 조각으로 나눠(`chunking.py`) 조각마다 자기 몫을 만든다.
그전에는 상한을 넘는 문서를 **앞에서 잘라** 한 번만 불렀고, 잘린 뒤쪽은 기각 건수에도
잡히지 않은 채 사라졌다 — 사내 규정집은 대부분 그 상한을 넘으므로 **뒷부분에서는
FAQ 가 나올 수 없는 상태**였다.

- 근거 대조(`EvidenceChecker`)는 **조각이 아니라 문서 전체**로 만든다. 조각 경계가
  문장 가운데를 지날 때 그 문장을 든 항목이 오탐 기각되는 것을 막는다.
- 중복 판정(`seen_questions`)도 조각을 가로질러 공유한다. 같은 주제가 여러 절에
  나오면 조각마다 같은 질문이 나오는데, 조각별로 따로 세면 그게 다 통과한다.

## 부족분 재요청

조각이 자기 몫을 못 채우면(스키마·근거·중복 기각) 그 조각에 이미 채택된 질문 목록을
주고 다시 부른다(`retry_shortfall.j2`). **호출 수 상한이 있다** — 계속 부르면 근거가
얕은 항목만 늘어나고, 조각이 많은 문서에서 비용이 조각 수에 비례해 버린다.
"""

import json
import re
from dataclasses import dataclass, field

from . import chunking
from .config import Config
from .evidence import EvidenceChecker, normalize
from .llm import CONFIG_MISSING, LlmResult, llm_call_async
from .logging_utils import log_info, log_warning
from .prompt_loader import PromptRenderError, render

# 부족분 재요청에 쓸 수 있는 **추가 호출 총량**. 조각마다 상한을 두면 조각이 많은
# 문서에서 호출이 곱셈으로 늘어난다 — 그래서 조각 수와 무관한 총량으로 둔다.
_MAX_SHORTFALL_CALLS = 2

# 난이도 지시문 (요구사항 §5). 프롬프트 변수로 넘겨 문구를 템플릿에서 다시 쓰지 않게 한다.
_DIFFICULTY_NOTE = (
    "이 문서를 처음 보는 사람이 실제로 궁금해할 만한 것을 묻는다. "
    "문서를 이미 아는 사람만 떠올릴 수 있는 세부 조항·예외 규정·내부 약어 문제는 만들지 않는다. "
    "용어가 나오면 답변 안에서 풀어 설명한다."
)

# 실패 분류 — 영역(02/03)마다 오류 코드가 달라 여기서는 분류만 하고 매핑은 호출부가 한다
FAILURE_NONE = ""
FAILURE_TRANSPORT = "transport"
FAILURE_EXECUTION = "execution"
FAILURE_NO_GROUNDED = "no_grounded"
FAILURE_PROMPT = "prompt"
# Gateway 설정 부재. **실행 실패와 갈라 둔다** — 프롬프트 부재를 2026-08-13 에 뗀 것과
# 같은 판단이다. 둘 다 환경을 안 채운 배포 실수라 몇 번을 불러도 같은 자리에서 실패하는데,
# 실행 실패로 뭉치면 502(retryable)로 나가 캔버스가 재시도를 걸고 로그의 error_type 도
# LLM 실패와 같아 **원인이 어디에도 드러나지 않는다.**
FAILURE_CONFIG = "config"

_QUESTION_NORMALIZE_RE = re.compile(r"[^0-9a-z가-힣]+")


@dataclass(frozen=True)
class FaqItem:
    question: str
    answer: str
    evidence: str        # 문서에서 그대로 옮긴 근거 (검증 통과분)
    evidence_ratio: float  # 1.0 = 완전 포함, 그 미만 = 부분 일치로 통과


@dataclass
class FaqResult:
    """생성 결과 + 무엇을 얼마나 버렸는지."""

    items: list = field(default_factory=list)
    requested_count: int = 0
    max_count: int = 0
    count_clamped: bool = False      # 사용자가 상한을 넘겨 요청해 깎았다
    rejected_schema: int = 0         # 질문·답변·근거가 비었거나 형식이 틀림
    rejected_ungrounded: int = 0     # 근거를 문서에서 확인하지 못함
    rejected_duplicate: int = 0      # 같은 질문
    # **조각 수 상한**(`FAQ_MAX_CONTEXT_CHUNKS`)에 걸려 뒤를 버린 경우에만 참이다.
    # 예전에는 문서가 조금만 길어도 늘 참이었다 — 그때는 이 값이 "앞부분만 봤다" 였고
    # 지금은 "이 문서는 상한을 넘길 만큼 길다" 다.
    source_truncated: bool = False
    source_chunks: int = 0           # 문서를 나눈 조각 수 (문서 전체 기준)
    chunks_planned: int = 0          # 그중 몫(quota)을 배정받은 조각 수
    chunks_used: int = 0             # 그중 실제로 LLM 호출이 성공한 조각 수
    #   planned > used → 조각 몇 개가 실패한 채로 결과가 나갔다는 뜻이다. 전량 실패는
    #   `failure` 로 가고, 부분 실패는 이 두 값의 차이로만 드러난다 (번역의 부분 폴백과
    #   같은 자리다). 스텝이 이 차이를 보고 안내문을 낸다.
    failure: str = FAILURE_NONE
    failure_type: str = ""           # 예외 클래스명 등 내부 분류 (사용자 노출 안 함)

    @property
    def ok(self) -> bool:
        return self.failure == FAILURE_NONE and bool(self.items)

    def as_payload(self) -> dict:
        return {
            "items": [
                {
                    "question": item.question,
                    "answer": item.answer,
                    "evidence": item.evidence,
                    "evidence_ratio": item.evidence_ratio,
                }
                for item in self.items
            ],
            "count": len(self.items),
            "requested_count": self.requested_count,
            "max_count": self.max_count,
            "count_clamped": self.count_clamped,
            "rejected": {
                "schema": self.rejected_schema,
                "ungrounded": self.rejected_ungrounded,
                "duplicate": self.rejected_duplicate,
            },
            "source_truncated": self.source_truncated,
            # 조각 수는 **왜 이 개수가 나왔나** 를 답하는 값이다 (기각 건수와 같은 몫).
            # 캔버스 payload 로는 나가지 않고 스텝이 `event=faq_done` 에 싣는다.
            "source_chunks": self.source_chunks,
            "chunks_planned": self.chunks_planned,
            "chunks_used": self.chunks_used,
        }


def resolve_max_count(admin_max=None) -> int:
    """관리자 상한. 배포 상한(`FAQ_MAX_COUNT`) **안에서만** 낮출 수 있다.

    캔버스 워크플로우 변수(`faq_max_count`)로 관리자가 재배포 없이 조정하게 하되,
    캔버스 값이 배포 상한을 **넘기지는 못하게** 한다. 넘길 수 있으면 LLM 예산 상한이
    캔버스 설정 하나로 무력해진다.
    """
    ceiling = max(0, Config.MAX_FAQ_COUNT)
    if admin_max is None or str(admin_max).strip() == "":
        return ceiling
    try:
        requested_max = int(admin_max)
    except (TypeError, ValueError):
        return ceiling
    return max(0, min(ceiling, requested_max))


def resolve_count(requested, admin_max=None) -> tuple:
    """(적용 개수, 상한, 깎였는지). 요구사항 §4 — 사용자는 0~관리자 상한 안에서 고른다.

    값이 없으면 기본값을 쓰고, 상한을 넘으면 상한으로 깎되 그 사실을 돌려준다
    (조용히 바꾸면 사용자는 요청한 개수가 나온 줄 안다).
    """
    maximum = resolve_max_count(admin_max)
    try:
        value = int(requested)
    except (TypeError, ValueError):
        value = Config.DEFAULT_FAQ_COUNT
    value = max(0, value)
    if value > maximum:
        return maximum, maximum, True
    return value, maximum, False


def _normalize_question(question: str) -> str:
    """중복 판정용 키 — 문장부호·공백·조사 앞뒤 차이를 흡수한다."""
    return _QUESTION_NORMALIZE_RE.sub("", normalize(question))


def _parse_faq_payload(raw: str) -> list:
    """LLM 응답에서 faqs 배열을 꺼낸다. 실패 시 빈 목록.

    응답 전문을 로그에 남기지 않는다 (3.8절) — 파싱 실패는 호출부가 건수로만 센다.
    """
    text = (raw or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return []
        try:
            payload = json.loads(text[start: end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        items = payload.get("faqs")
    elif isinstance(payload, list):
        items = payload  # 스키마를 어기고 배열만 준 경우까지 받아준다
    else:
        return []
    return items if isinstance(items, list) else []


def _adopt(
    raw_items: list,
    result: FaqResult,
    checker: EvidenceChecker,
    seen_questions: set,
    limit: int,
) -> None:
    """검증을 통과한 항목만 result.items 에 넣는다 (limit 까지)."""
    for entry in raw_items:
        if len(result.items) >= limit:
            return
        if not isinstance(entry, dict):
            result.rejected_schema += 1
            continue
        question = str(entry.get("question", "") or "").strip()
        answer = str(entry.get("answer", "") or "").strip()
        evidence = str(entry.get("evidence", "") or "").strip()
        if not question or not answer or not evidence:
            # 근거 없는 항목은 스키마 위반으로 본다 — 근거 표시가 요구사항이다
            result.rejected_schema += 1
            continue

        key = _normalize_question(question)
        if not key or key in seen_questions:
            result.rejected_duplicate += 1
            continue

        verdict = checker.check(evidence, Config.EVIDENCE_MIN_RATIO)
        if not verdict.grounded and Config.EVIDENCE_REJECT:
            result.rejected_ungrounded += 1
            continue

        seen_questions.add(key)
        result.items.append(
            FaqItem(
                question=question,
                answer=answer,
                evidence=evidence,
                evidence_ratio=verdict.ratio,
            )
        )


def _record_failure(result: FaqResult, llm_result: LlmResult) -> None:
    if llm_result.error_type == CONFIG_MISSING:
        # `is_transport_error` 는 False 라 예전에는 여기서 실행 실패로 떨어졌다
        # (`FAILURE_CONFIG` 머리말 참고).
        result.failure = FAILURE_CONFIG
    elif llm_result.is_transport_error:
        result.failure = FAILURE_TRANSPORT
    else:
        result.failure = FAILURE_EXECUTION
    result.failure_type = llm_result.error_type



async def _generate_from_chunk(
    chunk: str,
    quota: int,
    result: FaqResult,
    checker: EvidenceChecker,
    seen_questions: set,
    total_limit: int,
) -> bool:
    """조각 하나에서 `quota` 개를 만들어 채택한다. LLM 호출이 실패하면 False.

    채택 상한을 **`현재 + quota`** 로 잡는다(전체 상한이 아니라). LLM 이 요청 개수를
    넘겨 주는 일이 흔한데 전체 상한으로 열어 두면 **앞 조각이 뒤 조각들의 몫까지
    먹어 치워** 문서를 잘라 쓰던 시절의 앞부분 편중이 그대로 되살아난다.
    """
    try:
        system_prompt = render("system.j2", count=quota, difficulty_note=_DIFFICULTY_NOTE)
        user_prompt = render("user.j2", document=chunk, count=quota)
    except PromptRenderError as exc:
        result.failure = FAILURE_PROMPT
        result.failure_type = type(exc).__name__
        return False

    llm_result = await llm_call_async(system_prompt, user_prompt)
    if not llm_result.ok:
        _record_failure(result, llm_result)
        return False

    limit = min(total_limit, len(result.items) + quota)
    _adopt(_parse_faq_payload(llm_result.content), result, checker, seen_questions, limit)
    return True


async def _fill_shortfall(
    chunks: list,
    produced: list,
    quota: list,
    result: FaqResult,
    checker: EvidenceChecker,
    seen_questions: set,
    total_limit: int,
) -> None:
    """모자란 만큼 다시 요청한다 — **못 채운 조각부터**.

    호출 예산은 조각 수와 무관한 총량(`_MAX_SHORTFALL_CALLS`)이다. 조각마다 상한을
    두면 40조각짜리 문서에서 추가 호출이 40배가 된다.

    부족분 실패는 전체 실패가 아니다 — 1차에서 건진 항목은 그대로 내보낸다.
    """
    order = sorted(
        range(len(chunks)),
        key=lambda index: (quota[index] - produced[index], quota[index]),
        reverse=True,
    )
    calls = 0
    for index in order:
        missing = total_limit - len(result.items)
        if missing <= 0 or calls >= _MAX_SHORTFALL_CALLS:
            return
        if quota[index] <= 0:
            continue  # 애초에 몫이 없던 조각이다 (요청 개수 < 조각 수)

        log_info(
            "FAQ 개수 부족 — 추가 생성 요청",
            event="faq_shortfall_retry",
            item_count=missing,
            status=f"adopted={len(result.items)},chunk={index + 1}/{len(chunks)}",
        )
        try:
            system_prompt = render(
                "system.j2", count=missing, difficulty_note=_DIFFICULTY_NOTE
            )
            retry_prompt = render(
                "retry_shortfall.j2",
                document=chunks[index],
                missing=missing,
                existing_questions=[item.question for item in result.items],
            )
        except PromptRenderError:
            return  # 1차 결과는 유효하므로 그대로 쓴다 (여기서 요청을 세우지 않는다)

        calls += 1
        retry_result = await llm_call_async(system_prompt, retry_prompt)
        if not retry_result.ok:
            log_warning(
                "FAQ 부족분 재요청 실패 — 확보된 항목만 사용",
                event="faq_shortfall_failed",
                error_type=retry_result.error_type,
                item_count=len(result.items),
            )
            return
        _adopt(
            _parse_faq_payload(retry_result.content),
            result,
            checker,
            seen_questions,
            total_limit,
        )


async def generate_faqs(document: str, requested_count, admin_max=None) -> FaqResult:
    """문서에서 FAQ 를 만든다.

    Args:
        document: 전처리기 마크다운 또는 hwpx 직접 파싱 결과.
        requested_count: 사용자가 고른 개수 (관리자 상한 안으로 깎인다).
        admin_max: 캔버스 워크플로우 변수로 온 관리자 상한 (배포 상한 안에서만 적용).

    Returns:
        FaqResult. 예외를 던지지 않는다 — 실패는 `failure` 분류로 담아 돌려준다
        (워크플로우·코드서빙이 각자 영역 코드로 매핑한다).

    **문서 전체가 후보다** (2026-08-29). 조각으로 나눠 조각마다 자기 몫을 만든다 —
    그전에는 앞부분만 잘라 한 번 불렀고 뒷부분은 흔적 없이 빠졌다.
    """
    count, maximum, clamped = resolve_count(requested_count, admin_max)
    result = FaqResult(requested_count=count, max_count=maximum, count_clamped=clamped)
    if count <= 0:
        return result

    chunks = chunking.split_for_context(document or "", Config.MAX_CONTEXT_CHARS)
    if len(chunks) > Config.MAX_CONTEXT_CHUNKS:
        # 여기 걸린 문서만 뒤가 잘린다. 그 사실을 응답·로그로 낸다 —
        # 조용히 자르면 "왜 뒤쪽 내용이 하나도 안 나왔나" 에 답할 수 없다.
        chunks = chunks[: Config.MAX_CONTEXT_CHUNKS]
        result.source_truncated = True
    if not chunks:
        # 글자가 없는 문서다. LLM 을 부를 이유가 없고, 빈 목록을 성공으로 내보내면
        # "FAQ 가 0개인 문서" 처럼 보인다.
        result.failure = FAILURE_NO_GROUNDED
        return result

    result.source_chunks = len(chunks)
    quota = chunking.plan_quota(len(chunks), count)
    result.chunks_planned = sum(1 for value in quota if value > 0)

    # **근거 대조는 문서 전체로 한다** — 조각 경계가 문장 가운데를 지날 때 그 문장을
    # 근거로 든 항목이 오탐 기각되는 것을 막는다. 상한에 걸려 버린 뒤쪽은 LLM 이 본
    # 적이 없으므로 채택한 조각들만 이어 붙인 것이 곧 "문서" 다.
    checker = EvidenceChecker("\n".join(chunks))
    # **중복 판정은 조각을 가로질러 공유한다.** 같은 주제가 여러 절에 나오면 조각마다
    # 같은 질문이 나오는데, 조각별로 따로 세면 그게 전부 통과한다.
    seen_questions: set = set()
    produced = [0] * len(chunks)

    for index, chunk_quota in enumerate(quota):
        if chunk_quota <= 0:
            continue
        before = len(result.items)
        ok = await _generate_from_chunk(
            chunks[index], chunk_quota, result, checker, seen_questions, count
        )
        produced[index] = len(result.items) - before
        if ok:
            result.chunks_used += 1
        else:
            # 첫 실패에서 멈춘다 — 설정·프롬프트 부재는 다음 조각에서도 같은 자리에서
            # 죽고, 통신 실패도 조각 수만큼 두드릴 이유가 없다.
            break

    if result.items:
        # 조각 몇 개가 실패했어도 **건진 항목은 내보낸다** (번역의 부분 실패 규약과
        # 같다). 실패 분류를 지워야 `ok` 가 참이 된다 — 대신 몇 조각이 돌았는지가
        # `chunks_used` 로 남고, `chunks_planned` 보다 적으면 스텝이 안내문을 낸다.
        result.failure = FAILURE_NONE
        result.failure_type = ""
        await _fill_shortfall(
            chunks, produced, quota, result, checker, seen_questions, count
        )
    elif result.failure == FAILURE_NONE:
        # 통신은 됐는데 쓸 항목이 없다. 빈 목록을 성공으로 내려보내면
        # "FAQ 가 0개인 문서"처럼 보인다.
        result.failure = FAILURE_NO_GROUNDED

    log_info(
        "FAQ 생성 완료",
        event="faq_generated",
        item_count=len(result.items),
        status=(
            f"requested={count},"
            f"chunks={result.chunks_used}/{result.chunks_planned}"
            f"of{result.source_chunks},"
            f"truncated={int(result.source_truncated)},"
            f"schema={result.rejected_schema},"
            f"ungrounded={result.rejected_ungrounded},"
            f"duplicate={result.rejected_duplicate}"
        ),
    )
    return result
