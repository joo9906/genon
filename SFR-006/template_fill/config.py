"""SFR-006 템플릿 채우기 환경설정.

GenOS 엔지니어 개발가이드 v1.02 반영
- 3.7절/6.7절: 시크릿은 환경변수로만 관리. 코드에 기본값으로 유효한 키를 넣지 않는다.
  토큰은 호출 시점에 검증해서 mock 모드가 import 단계에서 막히지 않게 한다.
- 10.2절: LLM은 GenOS Gateway OpenAI 호환 경로만 사용.
"""

import os


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {key}")
    return value


class Config:
    # ── GenOS Gateway (10.2절 표준 경로) ──
    GENOS_URL = os.environ.get("GENOS_URL", "").rstrip("/")
    LLM_SERVING_ID = os.environ.get("LLM_SERVING_ID", "")
    LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "")

    @staticmethod
    def genos_token() -> str:
        return _require_env("GENOS_TOKEN")

    RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "60"))
    LLM_RETRY_COUNT = int(os.environ.get("LLM_RETRY_COUNT", "2"))
    MODEL_TEMP = float(os.environ.get("MODEL_TEMP", "0.1"))  # 필드 추출은 결정적으로

    # ── 동작 모드: llm | mock ──
    # mock: LLM 없이 "필드명: 값" 줄 파싱으로 파이프라인 구조 검증 (폐쇄망 테스트용)
    LLM_MODE = os.environ.get("TEMPLATE_FILL_LLM_MODE", "llm").strip().lower()

    # ── 저장소 경로 (워크플로우 pod ↔ 코드 서빙 pod 가 공유하는 볼륨 경로로 설정) ──
    TEMPLATE_DIR = os.environ.get("TEMPLATE_FILL_TEMPLATE_DIR", "./templates")
    SESSION_DIR = os.environ.get("TEMPLATE_FILL_SESSION_DIR", "./template_fill_sessions")
    SESSION_TTL_HOURS = float(os.environ.get("TEMPLATE_FILL_SESSION_TTL_HOURS", "24"))

    # ── 입력 상한 (LLM 예산/메모리 보호 — 번역 서비스 main.py와 동일한 취지) ──
    MAX_FIELDS = int(os.environ.get("TEMPLATE_FILL_MAX_FIELDS", "200"))
    MAX_VALUE_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_VALUE_CHARS", "2000"))
    MAX_MESSAGE_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_MESSAGE_CHARS", "20000"))
