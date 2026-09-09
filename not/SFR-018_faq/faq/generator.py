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

## 조각은 병렬로 부르고, 채택은 순서대로 한다 (2026-09-09)

조각 사이에 순서 의존이 없다 — 앞 조각의 결과가 뒤 조각의 프롬프트에 들어가지 않는다.
그래서 호출은 `asyncio.gather` 로 겹쳐 돌린다(동시 수는 `FAQ_LLM_CONCURRENCY`).
순차로 돌던 시절에는 **대기시간이 조각 수에 그대로 비례했다** — 기본 상한(6조각)에서
한 번 호출 시간의 여섯 배다.

**채택(`_adopt`)만은 조각 순서대로, 한 곳에서만 한다.** 중복 판정·기각 건수·조각별
채택 상한이 전부 누적 상태라, 응답이 도착한 순서대로 채택하면 **같은 문서가 실행마다
다른 분포를 낸다** — 오류로는 드러나지 않고 "어느 구간에서 몇 개가 나왔나" 만 흔들린다.
그래서 `_request_chunk` 는 공유 상태를 건드리지 않는 순수 호출이고, 판정과 채택은
`generate_faqs` 가 gather 결과를 받아 순서대로 흘린다.

## 부족분 재요청

조각이 자기 몫을 못 채우면(스키마·근거·중복 기각) 그 조각에 이미 채택된 질문 목록을
주고 다시 부른다(`retry_shortfall.j2`). **호출 수 상한이 있다** — 계속 부르면 근거가
얕은 항목만 늘어나고, 조각이 많은 문서에서 비용이 조각 수에 비례해 버린다.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field

from . import chunking, markdown_items
from .config import Config
from .evidence import EvidenceChecker, normalize
from .llm import (
    CONFIG_MISSING,
    STREAM_UNSUPPORTED,
    LlmResult,
    faq_stream_async,
    llm_call_async,
)
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
# 게이트웨이가 스트리밍을 받지 않는다. **실패가 아니라 경로 문제**라 갈라 둔다 —
# 호출부가 비스트리밍(`generate_faqs`)으로 되돌아가면 결과는 정상으로 나온다.
FAILURE_STREAM_UNSUPPORTED = "stream_unsupported"

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
    # 이번 문서의 **총 목표** = 사용자가 고른 총 개수 (상한 안으로 깎인 값).
    # 조각들이 이 개수를 나눠 갖는다 (2026-09-03 요구 확정).
    requested_count: int = 0
    max_count: int = 0               # 총 개수 상한 (관리자·배포 상한)
    call_cap: int = 0                # LLM 호출 수 상한 (`FAQ_MAX_CHUNK_CALLS`)
    count_clamped: bool = False      # 사용자가 총 개수 상한을 넘겨 요청해 깎았다
    # 호출 수 상한 때문에 **몫을 받지 못한 구간이 있다.** `source_truncated` 와 다른
    # 사건이다 — 그쪽은 조각 수 상한에 걸려 문서 뒤를 아예 안 본 것이고, 이쪽은 문서
    # 전체를 나눴지만 그중 일부 구간만 태운 것이다. 둘 다 "그 구간 내용으로는 FAQ 가
    # 나오지 않았다" 로 이어지므로 각각 알린다.
    coverage_capped: bool = False
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
            "call_cap": self.call_cap,
            "count_clamped": self.count_clamped,
            "coverage_capped": self.coverage_capped,
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
    """**총 개수** 관리자 상한. 배포 상한(`FAQ_MAX_COUNT`) **안에서만** 낮출 수 있다.

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


def resolve_call_cap() -> int:
    """LLM 호출 수 상한 = 태울 조각 수의 상한.

    캔버스 변수로 열지 않는다 — 이것은 **개수가 아니라 비용의 손잡이**라 배포가 정할
    몫이고, 총 개수(`resolve_max_count`)는 관리자가 이미 조정할 수 있다.
    """
    return max(0, Config.MAX_CHUNK_CALLS)


def resolve_count(requested, admin_max=None) -> tuple:
    """(총 개수, 총 개수 상한, 깎였는지). 요구사항 §4 — 사용자는 0~상한에서 고른다.

    **이 값은 문서 하나에서 만들 총 개수다** (2026-09-03 요구 확정). 조각 배분은 우리가
    한다 — 2026-08-31~09-02 에는 이 값이 구간당 개수여서 **고른 숫자와 받는 개수가
    달랐다**(구간이 여섯이면 5를 골라도 30개).

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
    """LLM 응답에서 항목 목록을 꺼낸다 — **마크다운 구분자 형식** (`not/` 판본).

    정본은 JSON 을 받아 `json.loads` 로 읽는다. 이 판본이 형식을 바꾼 이유는 하나다:
    **JSON 은 미완성 상태를 파싱할 수 없어** 조각이 통째로 끝나야 화면에 무언가를 낼 수
    있고, 그게 30~60초다(요구는 첫 글자까지 10초). 구분자 형식은 필드가 닫히는 순간을
    알 수 있어 항목 하나씩 내보낼 수 있다.

    **스트리밍 경로와 같은 파서를 쓴다** (`markdown_items`). 경로마다 파서를 두면
    마크다운 파서가 스트리밍 요청에서만 돌아 거의 검증되지 않는 갈래가 된다.

    응답 전문을 로그에 남기지 않는다 (3.8절) — 파싱 실패는 호출부가 건수로만 센다.
    """
    return markdown_items.parse_all(raw or "")


def _adopt_one(
    entry,
    result: FaqResult,
    checker: EvidenceChecker,
    seen_questions: set,
) -> FaqItem:
    """항목 **하나**를 검증해 채택한다. 기각이면 `None` 을 돌려주고 건수를 센다.

    스트리밍 경로가 항목마다 이 판정을 부르고, 비스트리밍 경로(`_adopt`)는 목록을
    돌며 부른다 — **판정이 한 곳이라야** 두 경로가 같은 것을 기각한다. 갈리면 같은
    문서가 경로에 따라 다른 개수를 내고, 그 차이는 오류로 드러나지 않는다.

    `result.items` 에 넣지는 **않는다.** 스트리밍은 화면에 낸 순서대로 자리를 잡아야
    해서 넣는 시점이 다르다 — 넣는 일은 호출부가 한다.
    """
    if not isinstance(entry, dict):
        result.rejected_schema += 1
        return None
    question = str(entry.get("question", "") or "").strip()
    answer = str(entry.get("answer", "") or "").strip()
    evidence = str(entry.get("evidence", "") or "").strip()
    if not question or not answer or not evidence:
        # 근거 없는 항목은 스키마 위반으로 본다 — 근거 표시가 요구사항이다.
        # 마크다운 형식에서는 **라벨이 흔들린 항목**도 여기로 떨어진다(필드가 빈다).
        result.rejected_schema += 1
        return None

    key = _normalize_question(question)
    if not key or key in seen_questions:
        result.rejected_duplicate += 1
        return None

    verdict = checker.check(evidence, Config.EVIDENCE_MIN_RATIO)
    if not verdict.grounded and Config.EVIDENCE_REJECT:
        result.rejected_ungrounded += 1
        return None

    seen_questions.add(key)
    return FaqItem(
        question=question,
        answer=answer,
        evidence=evidence,
        evidence_ratio=verdict.ratio,
    )


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
        item = _adopt_one(entry, result, checker, seen_questions)
        if item is not None:
            result.items.append(item)


def _classify_failure(llm_result: LlmResult) -> tuple:
    """(실패 분류, 내부 분류명). 호출부가 `FaqResult` 에 옮겨 담는다."""
    if llm_result.error_type == CONFIG_MISSING:
        # `is_transport_error` 는 False 라 예전에는 여기서 실행 실패로 떨어졌다
        # (`FAILURE_CONFIG` 머리말 참고).
        failure = FAILURE_CONFIG
    elif llm_result.is_transport_error:
        failure = FAILURE_TRANSPORT
    else:
        failure = FAILURE_EXECUTION
    return failure, llm_result.error_type


@dataclass(frozen=True)
class _ChunkOutcome:
    """조각 하나의 LLM 호출 결과.

    **공유 상태를 건드리지 않는다** — 채택(`_adopt`)은 호출이 전부 끝난 뒤 호출부가
    **조각 순서대로** 한 곳에서만 한다. 그래야 병렬로 돌려도 결과가 순차 시절과 같다:
    중복 판정(`seen_questions`)·기각 건수·조각별 채택 상한이 전부 누적 상태라,
    응답이 도착한 순서대로 채택하면 **어느 조각이 몇 개를 가져가는지가 매번 달라진다**
    (오류로는 드러나지 않고 분포로만 흔들린다).
    """

    content: str = ""
    failure: str = FAILURE_NONE
    failure_type: str = ""

    @property
    def ok(self) -> bool:
        return self.failure == FAILURE_NONE


async def _request_chunk(chunk: str, quota: int, semaphore) -> _ChunkOutcome:
    """조각 하나에 `quota` 개를 요청한다. **판정도 채택도 하지 않는다.**

    동시 호출 수는 `semaphore`(`FAQ_LLM_CONCURRENCY`)가 잡는다 — 호출 수 상한
    (`FAQ_MAX_CHUNK_CALLS`)은 "몇 번 부르나"(비용)이고 이쪽은 "동시에 몇 개가
    도나"(대기시간)다.

    **프롬프트 렌더는 세마포어 밖에서 한다.** 실패하면 LLM 을 부르지 않고 끝나므로
    (템플릿 부재는 이미지에 디렉토리를 안 넣은 배포 실수다) 자리를 잡을 이유가 없다.
    """
    try:
        system_prompt = render("md_system.txt", count=quota, difficulty_note=_DIFFICULTY_NOTE)
        user_prompt = render("md_user.txt", document=chunk, count=quota)
    except PromptRenderError as exc:
        return _ChunkOutcome(failure=FAILURE_PROMPT, failure_type=type(exc).__name__)

    async with semaphore:
        llm_result = await llm_call_async(system_prompt, user_prompt)
    if not llm_result.ok:
        failure, failure_type = _classify_failure(llm_result)
        return _ChunkOutcome(failure=failure, failure_type=failure_type)
    return _ChunkOutcome(content=llm_result.content)


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
                "md_system.txt", count=missing, difficulty_note=_DIFFICULTY_NOTE
            )
            retry_prompt = render(
                "md_retry_shortfall.txt",
                document=chunks[index],
                missing=missing,
                # 줄 조립을 코드가 한다 — 로더에 `{% for %}` 가 없고, 리스트를 그대로
                # 넘기면 `['질문']` 이라는 파이썬 repr 이 프롬프트에 실린다.
                existing_block="\n".join(f"- {item.question}" for item in result.items),
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
        requested_count: 사용자가 고른 **총 개수** (총 개수 상한 안으로 깎인다).
        admin_max: 캔버스 워크플로우 변수로 온 관리자 상한 (배포 상한 안에서만 적용).

    Returns:
        FaqResult. 예외를 던지지 않는다 — 실패는 `failure` 분류로 담아 돌려준다
        (워크플로우·코드서빙이 각자 영역 코드로 매핑한다).

    **문서 전체가 후보다** (2026-08-29). 조각으로 나눠 조각마다 자기 몫을 만든다 —
    그전에는 앞부분만 잘라 한 번 불렀고 뒷부분은 흔적 없이 빠졌다.

    **총 개수를 조각들이 나눠 갖는다** (2026-09-03 요구 확정). 사용자는 총 개수만
    고르고 배분은 `chunking.plan_quota` 가 한다. 긴 문서에서 조각당 몫이 0 이 되는
    것은 **호출 수 상한**(`FAQ_MAX_CHUNK_CALLS`)이 막는다 — 태울 조각 수를 묶으므로
    조각이 40개여도 여섯 조각이 나눠 갖고 몫은 1 밑으로 내려가지 않는다.
    """
    count, maximum, clamped = resolve_count(requested_count, admin_max)
    call_cap = resolve_call_cap()
    result = FaqResult(
        requested_count=count,
        max_count=maximum,
        call_cap=call_cap,
        count_clamped=clamped,
    )
    if count <= 0 or call_cap <= 0:
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
    # 배분은 여기 한 곳에서만 한다. 합은 사용자가 고른 `count` 와 정확히 같다 —
    # 목표를 조각 수에 따라 다시 계산하면 "고른 숫자와 받는 개수가 다르다" 로 돌아간다.
    quota = chunking.plan_quota(len(chunks), count, call_cap)
    result.chunks_planned = sum(1 for value in quota if value > 0)
    # 호출 수 상한(또는 총 개수)에 걸려 태우지 못한 구간이 있는가.
    # `source_truncated`(조각 수 상한)와 갈라 둔다 — 사용자에게는 원인이 다르게 보여야 한다.
    result.coverage_capped = result.chunks_planned < len(chunks)

    # **근거 대조는 문서 전체로 한다** — 조각 경계가 문장 가운데를 지날 때 그 문장을
    # 근거로 든 항목이 오탐 기각되는 것을 막는다. 상한에 걸려 버린 뒤쪽은 LLM 이 본
    # 적이 없으므로 채택한 조각들만 이어 붙인 것이 곧 "문서" 다.
    checker = EvidenceChecker("\n".join(chunks))
    # **중복 판정은 조각을 가로질러 공유한다.** 같은 주제가 여러 절에 나오면 조각마다
    # 같은 질문이 나오는데, 조각별로 따로 세면 그게 전부 통과한다.
    seen_questions: set = set()
    produced = [0] * len(chunks)

    # **조각들을 동시에 부른다** (2026-09-09). 조각 사이에는 순서 의존이 없다 —
    # 앞 조각이 뒤 조각의 프롬프트에 들어가지도, 뒤 조각이 앞 조각의 결과를 보지도
    # 않는다. 순차로 돌면 대기시간이 조각 수에 그대로 비례했다(기본 상한 6조각이면
    # 한 번 호출 시간의 여섯 배).
    semaphore = asyncio.Semaphore(max(1, Config.LLM_CONCURRENCY))
    targets = [index for index, share in enumerate(quota) if share > 0]
    outcomes = await asyncio.gather(
        *(_request_chunk(chunks[index], quota[index], semaphore) for index in targets)
    )

    # **채택은 조각 순서대로, 여기 한 곳에서만.** 호출은 겹쳐 돌지만 채택은 순차
    # 시절과 같은 순서로 흐른다 — 중복 판정·기각 건수·조각별 채택 상한이 누적
    # 상태라, 도착 순서대로 채택하면 같은 문서가 실행마다 다른 분포를 낸다.
    for index, outcome in zip(targets, outcomes):
        if not outcome.ok:
            # **첫 실패를 남긴다** (조각 순서 기준). 순차 시절에는 여기서 멈췄지만
            # 병렬에서는 호출이 이미 전부 나갔으므로 멈출 것이 없다 — 성공한 조각의
            # 결과를 버리는 것은 손해다(부분 실패 규약: 건진 항목은 내보낸다).
            if result.failure == FAILURE_NONE:
                result.failure = outcome.failure
                result.failure_type = outcome.failure_type
            continue
        before = len(result.items)
        # 채택 상한을 **`현재 + 몫`** 으로 잡는다(전체 상한이 아니라). LLM 이 요청
        # 개수를 넘겨 주는 일이 흔한데 전체 상한으로 열어 두면 **앞 조각이 뒤 조각들의
        # 몫까지 먹어 치워** 문서를 잘라 쓰던 시절의 앞부분 편중이 되살아난다.
        limit = min(count, len(result.items) + quota[index])
        _adopt(_parse_faq_payload(outcome.content), result, checker, seen_questions, limit)
        produced[index] = len(result.items) - before
        result.chunks_used += 1

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
            f"clamped={int(clamped)},"
            f"call_cap={call_cap},"
            f"chunks={result.chunks_used}/{result.chunks_planned}"
            f"of{result.source_chunks},"
            f"coverage_capped={int(result.coverage_capped)},"
            f"truncated={int(result.source_truncated)},"
            f"schema={result.rejected_schema},"
            f"ungrounded={result.rejected_ungrounded},"
            f"duplicate={result.rejected_duplicate}"
        ),
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 항목 단위 스트리밍 — **화면 첫 글자까지 10초** (`not/` 판본)
# ═══════════════════════════════════════════════════════════════════════════
# ## 왜 토큰을 그대로 흘리지 않나
#
# FAQ 항목은 스키마·근거 대조·중복 기각을 지나야 화면에 나갈 자격이 생긴다. 토큰으로
# 흘리면 **기각될 항목이 이미 화면에 나타난 뒤**다 — 이 저장소가 계속 피해 온 "답이
# 나왔다가 사라진다" 가 그것이다.
#
# ## 그래서 필드 순서를 뒤집었다
#
# 프롬프트가 `근거 → 질문 → 답변` 순으로 쓰게 한다(`md_system.txt`). 그러면 검증이
# **접두어 연산**이 된다:
#
#   근거가 닫히면  → 근거 대조 (실패면 이 항목은 한 글자도 안 나간다)
#   질문이 닫히면  → 중복 판정 · 몫 확인
#   답변 첫 델타   → 여기서 항목을 **연다**(질문을 화면에 낸다) 그리고 이어서 흘린다
#
# 화면 첫 글자까지 = 근거 + 질문 ≈ 100~200토큰. 항목 전체(300~500토큰)를 기다리는
# 것과 비교해 절반 이하다.
#
# **항목을 여는 시점이 "질문이 닫힐 때" 가 아니라 "답변 첫 델타" 인 이유**: 질문만 내고
# 답변이 끝내 안 오면(형식 위반) 화면에 답 없는 질문이 남는다. 한 토큰 늦추면 그 경우가
# 사라진다 — 늦어지는 것은 30ms 남짓이다.
#
# ## 조각 순서를 강제하지 않는다
#
# 번역은 문서 순서가 곧 결과물이라 머리 조각 버퍼가 필수였지만, FAQ 는 **항목 목록**이라
# 도착 순서대로 흘려도 된다 — 제일 먼저 끝난 조각의 첫 항목이 화면에 뜨고 그게 첫 글자를
# 당긴다. 다만 **최종 `faq_items` 순서를 흘린 순서와 같게** 맞춘다(안 그러면 마지막에
# 항목이 재정렬되며 화면에서 튄다). 그래서 자리를 **열 때** 잡고 끝날 때 채운다.

# 스트리밍 프레임 종류 (SSE 로 나가는 `type`)
FRAME_ITEM_OPEN = "item_open"     # 검증을 통과했다 — 질문을 화면에 낸다
FRAME_DELTA = "delta"             # 그 항목의 답변 토큰
FRAME_ITEM_CLOSE = "item_close"   # 답변이 끝났다 (근거·최종 답변을 함께 준다)


class _StreamCtx:
    """조각들이 공유하는 스트리밍 상태.

    조각마다 값 객체를 두면 **자리 순서**를 정할 수 없다 — 그건 조각 하나의 상태가
    아니라 조각들 사이의 상태다.
    """

    def __init__(self, result: FaqResult, checker: EvidenceChecker, total: int, on_frame):
        self.result = result
        self.checker = checker
        self.total = total
        self.on_frame = on_frame
        self.seen_questions: set = set()
        # 화면에 낸 순서대로 자리를 잡는다. 끝나면 이 목록이 곧 `result.items` 다.
        self.slots: list = []
        # `on_frame` 직렬화 + 자리 배정. 조각들이 함께 도므로 이게 없으면 두 항목의
        # 프레임이 섞여 나간다.
        self.lock = asyncio.Lock()

    def open_slot(self) -> int:
        index = len(self.slots)
        self.slots.append(None)
        return index

    @property
    def filled(self) -> int:
        return sum(1 for slot in self.slots if slot is not None)


async def _stream_one_chunk(
    semaphore: asyncio.Semaphore,
    chunk: str,
    quota: int,
    ctx: _StreamCtx,
    aborted: asyncio.Event,
) -> _ChunkOutcome:
    """조각 하나를 스트리밍으로 태우고 **항목마다 검증해서** 프레임을 낸다."""
    if aborted.is_set():
        # 설정·프롬프트 부재가 이미 확인됐다. 남은 조각을 부르면 같은 실패만 쌓인다.
        return _ChunkOutcome(failure=FAILURE_CONFIG, failure_type=CONFIG_MISSING)

    try:
        system_prompt = render(
            "md_system.txt", count=quota, difficulty_note=_DIFFICULTY_NOTE
        )
        user_prompt = render("md_user.txt", document=chunk, count=quota)
    except PromptRenderError as exc:
        aborted.set()
        return _ChunkOutcome(failure=FAILURE_PROMPT, failure_type=type(exc).__name__)

    parser = markdown_items.ItemStream()
    # 이 조각의 "지금 만들고 있는 항목" 상태. 조각 하나의 스트림은 순차라 하나면 된다.
    live = {"index": None, "question": "", "evidence": "", "ratio": 0.0, "answer": []}
    adopted = 0

    def _reset_live() -> None:
        live.update({"index": None, "question": "", "evidence": "", "ratio": 0.0})
        live["answer"] = []

    async def _handle(event) -> None:
        nonlocal adopted
        if event.kind == markdown_items.EVIDENCE:
            # 새 항목이 시작됐다. **여기서 근거 대조를 한다** — 통과 못하면 이 항목은
            # 화면에 한 글자도 안 나간다.
            _reset_live()
            evidence = event.text.strip()
            verdict = ctx.checker.check(evidence, Config.EVIDENCE_MIN_RATIO)
            if not verdict.grounded and Config.EVIDENCE_REJECT:
                async with ctx.lock:
                    ctx.result.rejected_ungrounded += 1
                live["evidence"] = ""     # 이 항목은 죽었다
                return
            live["evidence"] = evidence
            live["ratio"] = verdict.ratio
            return

        if event.kind == markdown_items.QUESTION:
            if not live["evidence"]:
                return  # 근거에서 이미 기각됐다
            question = event.text.strip()
            key = _normalize_question(question)
            async with ctx.lock:
                if not key or key in ctx.seen_questions:
                    ctx.result.rejected_duplicate += 1
                    live["evidence"] = ""
                    return
                if adopted >= quota or len(ctx.slots) >= ctx.total:
                    # 몫을 다 썼다. **기각이 아니다** — 건수에 넣으면 "왜 5개인가" 를
                    # 설명하는 값이 상한 때문에 부풀어 진단을 흐린다.
                    live["evidence"] = ""
                    return
                ctx.seen_questions.add(key)
            live["question"] = question
            return

        if event.kind == markdown_items.ANSWER_DELTA:
            if not live["evidence"] or not live["question"]:
                return
            async with ctx.lock:
                if live["index"] is None:
                    # **첫 델타에서 항목을 연다** (위 머리말). 자리도 여기서 잡는다 —
                    # 화면 순서와 최종 목록 순서가 같아야 한다.
                    live["index"] = ctx.open_slot()
                    adopted += 1
                    await ctx.on_frame(
                        {
                            "type": FRAME_ITEM_OPEN,
                            "index": live["index"],
                            "question": live["question"],
                        }
                    )
                live["answer"].append(event.text)
                await ctx.on_frame(
                    {"type": FRAME_DELTA, "index": live["index"], "text": event.text}
                )
            return

        if event.kind == markdown_items.ITEM_END:
            index = live["index"]
            if index is None:
                # 화면에 열지 않은 항목이다. 근거·중복에서 이미 세었거나, 답변이 아예
                # 없어 스키마 미달이거나(라벨 흔들림), 몫을 다 쓴 뒤였다.
                entry = event.item
                if (
                    live["evidence"]
                    and live["question"]
                    and not str(entry.get("answer", "")).strip()
                ):
                    async with ctx.lock:
                        ctx.result.rejected_schema += 1
                elif not live["evidence"] and not markdown_items.is_complete(event.item):
                    async with ctx.lock:
                        ctx.result.rejected_schema += 1
                _reset_live()
                return
            answer = "".join(live["answer"]).strip()
            async with ctx.lock:
                ctx.slots[index] = FaqItem(
                    question=live["question"],
                    answer=answer,
                    evidence=live["evidence"],
                    evidence_ratio=live["ratio"],
                )
                await ctx.on_frame(
                    {
                        "type": FRAME_ITEM_CLOSE,
                        "index": index,
                        "question": live["question"],
                        "answer": answer,
                        "evidence": live["evidence"],
                    }
                )
            _reset_live()

    async def _on_delta(piece: str) -> None:
        for event in parser.feed(piece):
            await _handle(event)

    async with semaphore:
        llm_result = await faq_stream_async(system_prompt, user_prompt, _on_delta)

    # 닫히지 않은 마지막 묶음까지 정리한다 — 모델이 `>>>` 를 빠뜨리는 일이 흔하고,
    # 그것 때문에 멀쩡한 항목 하나를 버릴 이유가 없다.
    for event in parser.finish():
        await _handle(event)

    if not llm_result.ok:
        failure, failure_type = _classify_failure(llm_result)
        if failure_type == CONFIG_MISSING:
            aborted.set()
        return _ChunkOutcome(failure=failure, failure_type=failure_type)
    return _ChunkOutcome(content=llm_result.content)


async def generate_faqs_stream(
    document: str,
    requested_count,
    admin_max=None,
    on_frame=None,
) -> FaqResult:
    """문서에서 FAQ 를 만들며 **항목마다 흘린다.** 예외를 던지지 않는다.

    Args:
        on_frame: `async def (dict) -> None`. `item_open` · `delta` · `item_close`
            프레임이 온다. **호출은 직렬화된다** — 소비자가 SSE 에 쓰므로 겹치면
            프레임이 섞인다.

    Returns:
        `FaqResult`. `items` 는 **흘린 순서와 같다.**
        `failure == FAILURE_STREAM_UNSUPPORTED` 면 이 배포는 스트리밍을 받지 않으므로
        호출부가 `generate_faqs` 로 되돌아간다.

    조각 분할·몫 배분·근거 대조·중복 판정은 **비스트리밍과 같은 코드**를 쓴다
    (`chunking.plan_quota` · `_adopt_one` 의 판정부). 갈리면 같은 문서가 경로에 따라
    다른 개수를 낸다.
    """
    if on_frame is None:
        async def on_frame(_frame):  # noqa: ANN001 - 대역 없이 부를 때
            return None

    count, maximum, clamped = resolve_count(requested_count, admin_max)
    call_cap = resolve_call_cap()
    result = FaqResult(
        requested_count=count, max_count=maximum, call_cap=call_cap, count_clamped=clamped
    )
    if count <= 0 or call_cap <= 0:
        return result

    chunks = chunking.split_for_context(document or "", Config.MAX_CONTEXT_CHARS)
    if len(chunks) > Config.MAX_CONTEXT_CHUNKS:
        chunks = chunks[: Config.MAX_CONTEXT_CHUNKS]
        result.source_truncated = True
    if not chunks:
        result.failure = FAILURE_NO_GROUNDED
        return result

    result.source_chunks = len(chunks)
    quota = chunking.plan_quota(len(chunks), count, call_cap)
    result.chunks_planned = sum(1 for value in quota if value > 0)
    result.coverage_capped = result.chunks_planned < len(chunks)

    # 근거 대조는 **문서 전체**로 한다 — 조각 경계가 문장 가운데를 지나면 그 문장을
    # 근거로 든 항목이 오탐 기각된다.
    ctx = _StreamCtx(result, EvidenceChecker("\n".join(chunks)), count, on_frame)
    semaphore = asyncio.Semaphore(max(1, Config.LLM_CONCURRENCY))
    aborted = asyncio.Event()
    targets = [index for index, share in enumerate(quota) if share > 0]

    outcomes = await asyncio.gather(
        *(
            _stream_one_chunk(semaphore, chunks[index], quota[index], ctx, aborted)
            for index in targets
        )
    )
    for outcome in outcomes:
        if outcome.ok:
            result.chunks_used += 1
        elif result.failure == FAILURE_NONE:
            result.failure = outcome.failure
            result.failure_type = outcome.failure_type

    # **화면에 낸 순서 그대로** 최종 목록을 만든다. 열렸는데 안 닫힌 자리(스트림이
    # 도중에 끊긴 항목)는 버린다 — 답변이 잘린 항목을 결과물에 실을 수는 없다.
    result.items = [slot for slot in ctx.slots if slot is not None]
    dropped = len(ctx.slots) - len(result.items)
    if dropped:
        result.rejected_schema += dropped

    # **스트리밍을 안 받는 배포는 갈라서 알린다** — 호출부가 비스트리밍으로 되돌아간다.
    if not result.items and all(
        outcome.failure_type == STREAM_UNSUPPORTED for outcome in outcomes
    ):
        result.failure = FAILURE_STREAM_UNSUPPORTED
        result.failure_type = STREAM_UNSUPPORTED
        return result

    if result.items:
        result.failure = FAILURE_NONE
        result.failure_type = ""
    elif result.failure == FAILURE_NONE:
        result.failure = FAILURE_NO_GROUNDED

    log_info(
        "FAQ 스트리밍 생성 완료",
        event="faq_stream_generated",
        item_count=len(result.items),
        status=(
            f"requested={count},call_cap={call_cap},"
            f"chunks={result.chunks_used}/{result.chunks_planned}of{result.source_chunks},"
            f"schema={result.rejected_schema},"
            f"ungrounded={result.rejected_ungrounded},"
            f"duplicate={result.rejected_duplicate}"
        ),
    )
    return result
