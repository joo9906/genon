"""SFR-018 FAQ 오류 코드 중앙 관리.

가이드 3.9절
- 3.9.2절: 공통 코드는 00020001(통신 실패) / 00020002(실행 실패) / 00020003(그 외)
  세 개만 조합한다. 원인 구분은 error_type / user_msg 로 한다.
- 이 패키지는 두 영역에 걸친다 (SFR-006 과 같은 구성):
  * `run_chat.py` (워크플로우 Python 단계) → 영역코드 02, `data["error"]` 객체로 반환
  * `main.py` (코드 서빙)                 → 영역코드 03, HTTP 오류 응답으로 반환
- 3.8절: user_msg 에 내부 예외 원문·문서 내용을 절대 담지 않는다.
"""

from dataclasses import dataclass

_WORKFLOW = "02"
_SERVING = "03"


@dataclass(frozen=True)
class ErrorCode:
    code: str
    error_type: str
    retryable: bool
    user_msg: str
    http_status: int = 500


# ── 워크플로우(02) — run_chat.py ─────────────────────────────

ERR_CHAT_NO_INPUT = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_NO_INPUT",
    retryable=False,
    user_msg="업로드된 문서를 찾을 수 없습니다. 문서를 첨부한 뒤 다시 시도해 주세요.",
)

ERR_CHAT_DOC_INVALID = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_DOCUMENT_INVALID",
    retryable=False,
    user_msg="문서를 해석하지 못했습니다. hwpx·pdf·docx 파일인지 확인해 주세요.",
)

ERR_CHAT_COUNT_ZERO = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_COUNT_ZERO",
    retryable=False,
    user_msg="생성할 FAQ 개수가 0으로 지정되어 있습니다. 1개 이상으로 골라 주세요.",
)

ERR_CHAT_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"{_WORKFLOW}-00020001",
    error_type="FAQ_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
)

ERR_CHAT_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_WORKFLOW}-00020002",
    error_type="FAQ_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="FAQ 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
)

# 스키마·근거 검증을 통과한 항목이 하나도 없는 경우. 통신은 됐지만 쓸 결과가 없다.
# 빈 목록을 성공으로 내려보내면 "FAQ 가 0개인 문서"처럼 보인다 (실패 침묵 처리 금지).
ERR_CHAT_NO_GROUNDED_ITEMS = ErrorCode(
    code=f"{_WORKFLOW}-00020002",
    error_type="FAQ_NO_GROUNDED_ITEMS",
    retryable=True,
    user_msg="문서에서 근거를 확인할 수 있는 FAQ 를 만들지 못했습니다. 다시 시도해 주세요.",
)

ERR_CHAT_INTERNAL = ErrorCode(
    code=f"{_WORKFLOW}-00020003",
    error_type="FAQ_INTERNAL_UNCLASSIFIED",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
)


# ── 코드 서빙(03) — main.py ──────────────────────────────────

ERR_API_INPUT = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_INPUT",
    retryable=False,
    user_msg="요청 형식이 올바르지 않습니다.",
    http_status=400,
)

ERR_API_SESSION_NOT_FOUND = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_SESSION_NOT_FOUND",
    retryable=False,
    user_msg="FAQ 정보를 찾을 수 없습니다. FAQ 를 먼저 생성해 주세요.",
    http_status=404,
)

ERR_API_UPSTREAM_TIMEOUT = ErrorCode(
    code=f"{_SERVING}-00020001",
    error_type="FAQ_API_UPSTREAM_TIMEOUT",
    retryable=True,
    user_msg="외부 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    http_status=504,
)

ERR_API_UPSTREAM_EXECUTION = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="FAQ_API_UPSTREAM_EXECUTION_FAILED",
    retryable=True,
    user_msg="FAQ 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=502,
)

# 통신·실행은 됐는데 **근거를 확인할 수 있는 항목이 하나도 없는** 경우
# (`generator.FAILURE_NO_GROUNDED`). 2026-08-13 추가.
#
# 그전에는 이 사건이 `ERR_API_UPSTREAM_EXECUTION`(502)에 합쳐져 있었다. 그래서
# 워크플로우 스텝은 "FAQ 생성에 실패했습니다"만 받았고, 워크플로우 오류표의
# `NO_GROUNDED` 항목(`ERR_CHAT_NO_GROUNDED_ITEMS` 와 짝)은 **닿을 수 없는 코드**였다 —
# 스텝이 그 분기를 `upstream_status == 422` 로 걸어 뒀는데 서빙이 422 를 낸 적이 없다.
#
# 두 사건은 사용자가 할 일이 다르다: 실행 실패는 "잠시 후 다시", 근거 미확보는 "이 문서로는
# 근거 있는 FAQ 가 안 나온다"(문서를 바꾸거나 개수를 줄이는 쪽이 맞다). 502 로 뭉뚱그리면
# 그 구분이 사라지고 기각 사유를 아무리 세어도 화면까지 오지 않는다.
ERR_API_NO_GROUNDED = ErrorCode(
    code=f"{_SERVING}-00020002",
    error_type="FAQ_API_NO_GROUNDED_ITEMS",
    retryable=True,
    user_msg="문서에서 근거를 확인할 수 있는 FAQ 를 만들지 못했습니다. 다시 시도해 주세요.",
    # 422 — 요청 형식은 맞지만 그 내용으로는 처리할 수 없다. 워크플로우 스텝이 이미 이
    # 상태코드를 근거 미확보로 읽고 있어(그쪽이 먼저였다) 코드를 거기 맞춘다.
    http_status=422,
)

# 프롬프트 템플릿을 못 찾았다 (`generator.FAILURE_PROMPT`). 2026-08-13 추가.
#
# **재시도로 풀리지 않는다.** 이미지에 `onprem/prompt/SFR-018_faq/` 를 안 넣은 배포 실수라
# 몇 번을 불러도 같은 자리에서 실패한다. 그전에는 이것도 502(retryable=True)로 나가서
# 캔버스가 재시도를 걸 수 있었고, 로그에도 LLM 실패와 같은 error_type 이 남아
# **배포 구성 문제라는 사실이 어디에도 드러나지 않았다.**
ERR_API_PROMPT_UNAVAILABLE = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_PROMPT_UNAVAILABLE",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 관리자에게 문의해 주세요.",
    http_status=500,
)

# Gateway 설정(`GENOS_URL`/`LLM_SERVING_ID`) 부재 (`generator.FAILURE_CONFIG`).
#
# 프롬프트 부재와 **같은 성격**이다 — 환경을 안 채운 배포 실수라 재시도가 무의미하다.
# 그전에는 `LlmResult.is_transport_error` 가 False 라는 이유로 실행 실패에 뭉쳐
# `ERR_API_UPSTREAM_EXECUTION`(502, retryable=True)로 나갔다.
ERR_API_CONFIG_UNAVAILABLE = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_CONFIG_UNAVAILABLE",
    retryable=False,
    user_msg="서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
    http_status=500,
)

ERR_API_INTERNAL = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_INTERNAL",
    retryable=False,
    user_msg="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    http_status=500,
)

ERR_API_ADMIN_FORBIDDEN = ErrorCode(
    code=f"{_SERVING}-00020003",
    error_type="FAQ_API_ADMIN_FORBIDDEN",
    retryable=False,
    user_msg="권한이 없습니다.",
    http_status=403,
)

# ── 걷어낸 코드 (2026-08-12) ─────────────────────────────────
#
# `ERR_API_EXPORT_UNAVAILABLE`(501, 수단 없음)과 `ERR_API_EXPORT_FAILED`(500, 변환 실패)가
# 있었다. 내려받기가 hwpx/pdf/xlsx 였을 때는 형식마다 **가용 조건**(관리자 템플릿·
# weasyprint·openpyxl)이 달라 그 둘을 갈라야 했다 — "다른 형식을 골라라" 와 "다시 시도해라"
# 는 사용자가 할 일이 다르다.
#
# txt 로 통일된 뒤에는 **둘 다 성립하지 않는다.** 문자열 조립과 utf-8 인코딩은 환경에
# 좌우되지 않으므로 "이 환경에서는 못 만든다" 가 없고, 실패하면 그것은 우리 버그이지
# 재시도로 풀리는 일이 아니다 — `ERR_API_INTERNAL` 로 올린다.
# 되살릴 일이 생기면 `git show archive/sfr018-doc-export:onprem/codeserving/SFR-018_faq/faq/error_codes.py`.
