"""공용 로깅 유틸.

3.10절 공통 금지사항: stdout에 일반 로그 출력(print) 금지.
표준 logger로 통일하고, 문서 원문/LLM 응답 전문 등은 여기서도 그대로 통과시키지
않도록 호출부에서 메타정보만 넘기게 한다.
"""

import logging

_log = logging.getLogger("translation_pipeline")


def log_info(message: str) -> None:
    _log.info(message)


def log_warning(message: str) -> None:
    _log.warning(message)
