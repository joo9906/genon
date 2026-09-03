"""평가 MCP 입력 오류 메시지 + 오류 전달 경로.

이 패키지는 GenOS 워크플로우/코드서빙이 아니라 **평가지표·MCP 도구** 영역이라
가이드 3.9절의 영역코드 체계(02/03)를 쓰지 않는다. 대신 그 영역의 오류 전달 규칙을
따른다 (CLAUDE.md §1, GENOS_RULES A.4):

> 전처리기·평가지표는 오류 객체를 반환하지 않는다. **로그에 코드를 남기고 예외를 던진다.**

그래서 `raise EvalInputError(...)` 를 직접 쓰지 않고 `fail()` 을 쓴다 — 로그 없이
예외만 던지면 폐쇄망에서 무엇이 왜 실패했는지 추적할 근거가 남지 않는다.
오류 문자열은 여기 상수만 참조한다(하드코딩 금지).
"""

from typing import NoReturn

from .logging_utils import log_warning


class EvalInputError(ValueError):
    """평가 입력이 계약에 맞지 않음.

    계약: 메시지는 이 파일의 상수만 담는다 (내부 예외 원문 금지).
    """


def fail(message: str, *, event: str, from_exc: BaseException | None = None, **fields) -> NoReturn:
    """로그를 남긴 뒤 예외를 던진다 (평가지표 영역의 오류 전달 방식).

    Args:
        message: 이 파일의 상수 중 하나.
        event: 로그 이벤트 이름 (허용 필드).
        from_exc: 원인 예외. **클래스명만** error_type 으로 로그에 남기고(3.8절 —
            예외 원문 금지) 예외 체인은 유지해 내부 트레이스백을 잃지 않는다.
        fields: logging_utils 화이트리스트(item_count, status 등)만 통과한다.
    """
    if from_exc is not None:
        fields.setdefault("error_type", type(from_exc).__name__)
    log_warning(message, event=event, **fields)
    raise EvalInputError(message) from from_exc


ERR_EMPTY_TEXT = "평가할 텍스트가 비어 있습니다."
ERR_EMPTY_ITEMS = "평가할 항목이 하나도 없습니다."
ERR_UNKNOWN_MATCH_MODE = "지원하지 않는 매칭 방식입니다. exact/contains/regex 중 하나를 지정해 주세요."
ERR_BAD_REGEX = "정규식 형식이 올바르지 않습니다."
ERR_UNKNOWN_OPERATOR = "지원하지 않는 비교 연산자입니다. lt/gt/eq/between 중 하나를 지정해 주세요."
ERR_BETWEEN_BOUNDS = "between 비교에는 최소값과 최대값이 모두 필요합니다."
ERR_MISSING_THRESHOLD = "비교할 임계값이 없습니다."
ERR_NO_NUMBER_FOUND = "텍스트에서 수치를 찾지 못했습니다."
ERR_GOLD_REQUIRED = "정답(참조) 데이터가 없으면 이 지표는 측정할 수 없습니다."
ERR_NOT_A_MAPPING = "필드 추출 결과는 {필드명: 값} 형태의 객체여야 합니다."
ERR_PAIR_NOT_A_MAPPING = "평가 항목은 {source/original, target/result} 형태의 객체여야 합니다."
ERR_PAIR_SOURCE_MISSING = (
    "평가 항목에 원문이 없습니다. source 또는 original 키에 원문을 넣어 주세요 "
    "(원문 없이는 어떤 대조도 성립하지 않습니다)."
)
ERR_FILE_NOT_FOUND = "지정한 파일을 찾을 수 없습니다."
ERR_HWPX_INVALID = "hwpx 파일을 해석하지 못했습니다. hwpx(ZIP+XML) 형식인지 확인해 주세요."
ERR_BAD_SAMPLE_RATE = "샘플링 비율은 0 이상 1 이하여야 합니다."
ERR_JUDGE_NOT_ENABLED = (
    "LLM Judge 는 게이트드 도구입니다. 온프레미스 서빙 가용성 확인 후 "
    "opt_in 을 명시해야 호출됩니다."
)
ERR_NGRAM_SIZE = "n-gram 크기는 1 이상이어야 합니다."
ERR_UNKNOWN_FEATURE = (
    "지원하지 않는 기능입니다. template_fill / text_polish / translation / faq "
    "중 하나를 지정해 주세요."
)
