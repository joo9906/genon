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

## 부족분 재요청

1차 응답이 요청 개수에 못 미치면 이미 채택된 질문 목록을 주고 한 번 더 부른다
(`retry_shortfall.j2`). 상한 있는 재시도다 — 계속 부르면 근거가 얕은 항목이
늘어나기만 한다.
"""

import json
import re
from dataclasses import dataclass, field

from .config import Config
from .evidence import EvidenceChecker, normalize
from .llm import CONFIG_MISSING, LlmResult, llm_call_async
from .logging_utils import log_info, log_warning
from .prompt_loader import PromptRenderError, render

# 부족분 재요청 횟수 상한. 늘려도 근거가 얕은 항목만 늘어난다.
_MAX_SHORTFALL_RETRY = 1

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
    source_truncated: bool = False   # 문서가 상한을 넘어 앞부분만 사용
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


async def generate_faqs(document: str, requested_count, admin_max=None) -> FaqResult:
    """문서에서 FAQ 를 만든다.

    Args:
        document: 전처리기 마크다운 또는 hwpx 직접 파싱 결과.
        requested_count: 사용자가 고른 개수 (관리자 상한 안으로 깎인다).
        admin_max: 캔버스 워크플로우 변수로 온 관리자 상한 (배포 상한 안에서만 적용).

    Returns:
        FaqResult. 예외를 던지지 않는다 — 실패는 `failure` 분류로 담아 돌려준다
        (워크플로우·코드서빙이 각자 영역 코드로 매핑한다).
    """
    count, maximum, clamped = resolve_count(requested_count, admin_max)
    result = FaqResult(requested_count=count, max_count=maximum, count_clamped=clamped)
    if count <= 0:
        return result

    source = document or ""
    if len(source) > Config.MAX_CONTEXT_CHARS:
        source = source[: Config.MAX_CONTEXT_CHARS]
        result.source_truncated = True

    checker = EvidenceChecker(source)
    seen_questions: set = set()

    try:
        system_prompt = render("system.j2", count=count, difficulty_note=_DIFFICULTY_NOTE)
        user_prompt = render("user.j2", document=source, count=count)
    except PromptRenderError as exc:
        result.failure = FAILURE_PROMPT
        result.failure_type = type(exc).__name__
        return result

    llm_result = await llm_call_async(system_prompt, user_prompt)
    if not llm_result.ok:
        _record_failure(result, llm_result)
        return result

    _adopt(_parse_faq_payload(llm_result.content), result, checker, seen_questions, count)

    # 부족분 재요청 — 이미 채택된 질문을 알려줘 중복 생성을 막는다
    for _ in range(_MAX_SHORTFALL_RETRY):
        missing = count - len(result.items)
        if missing <= 0:
            break
        log_info(
            "FAQ 개수 부족 — 추가 생성 요청",
            event="faq_shortfall_retry",
            item_count=missing,
            status=f"adopted={len(result.items)}",
        )
        try:
            retry_prompt = render(
                "retry_shortfall.j2",
                document=source,
                missing=missing,
                existing_questions=[item.question for item in result.items],
            )
        except PromptRenderError:
            break  # 1차 결과는 유효하므로 그대로 쓴다 (여기서 요청을 세우지 않는다)
        retry_result = await llm_call_async(system_prompt, retry_prompt)
        if not retry_result.ok:
            # 부족분 실패는 전체 실패가 아니다 — 1차에서 건진 항목은 그대로 내보낸다
            log_warning(
                "FAQ 부족분 재요청 실패 — 확보된 항목만 사용",
                event="faq_shortfall_failed",
                error_type=retry_result.error_type,
                item_count=len(result.items),
            )
            break
        _adopt(_parse_faq_payload(retry_result.content), result, checker, seen_questions, count)

    if not result.items:
        # 통신은 됐는데 쓸 항목이 없다. 빈 목록을 성공으로 내려보내면
        # "FAQ 가 0개인 문서"처럼 보인다.
        result.failure = FAILURE_NO_GROUNDED

    log_info(
        "FAQ 생성 완료",
        event="faq_generated",
        item_count=len(result.items),
        status=(
            f"requested={count},"
            f"schema={result.rejected_schema},"
            f"ungrounded={result.rejected_ungrounded},"
            f"duplicate={result.rejected_duplicate}"
        ),
    )
    return result
