"""번역 서비스 환경설정.

GenOS 엔지니어 개발가이드 v1.02 반영
- 3.7절 / 6.7절: 시크릿은 환경변수로만 관리하고 코드에 직접 입력하지 않는다.
  기본값에 실제 유효한 키 형태를 넣지 않는다 (없으면 명시적으로 실패시킨다).
- 10.2절: GenOS 관리 대상 모델은 Gateway OpenAI 호환 경로만 사용한다.
  외부 SDK/키로 우회 호출하는 경로를 두지 않는다.
"""

import os


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {key}")
    return value


class Config:
    # GenOS Gateway 경로 (10.2절 표준 경로만 사용)
    GENOS_URL = os.environ.get("GENOS_URL", "").rstrip("/")
    LLM_SERVING_ID = os.environ.get("LLM_SERVING_ID", "")
    LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "")

    # 시크릿 - 기본값 없음. 실제 호출 시점에만 검증하여, import 단계에서
    # 테스트/목업 모드(translator_mode=mock|noop) 실행까지 막지 않는다.
    @staticmethod
    def genos_token() -> str:
        return _require_env("GENOS_TOKEN")

    RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "90"))
    LLM_RETRY_COUNT = int(os.environ.get("LLM_RETRY_COUNT", "2"))
    MODEL_TEMP = float(os.environ.get("MODEL_TEMP", "0.3"))
    MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "16384"))

    LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "15"))
    MAX_CHARS_PER_BATCH = int(os.environ.get("MAX_CHARS_PER_BATCH", "4000"))
    MAX_ITEMS_PER_BATCH = int(os.environ.get("MAX_ITEMS_PER_BATCH", "10"))
