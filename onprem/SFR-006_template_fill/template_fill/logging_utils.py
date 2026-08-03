"""공용 로깅 유틸.

3.10절: stdout에 일반 로그를 print로 출력하지 않는다.
3.8절: 문서 원문/LLM 응답 전문/사용자 입력값을 로그에 남기지 않고
       길이·개수·필드명 등 메타정보만 남긴다.
"""

import logging

_log = logging.getLogger("template_fill")


def log_info(message: str) -> None:
    _log.info(message)


def log_warning(message: str) -> None:
    _log.warning(message)
