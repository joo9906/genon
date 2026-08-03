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

    # ------------------------------------------------------------------
    # 용어사전 RAG (Weaviate) 설정
    #
    # 조회 자체가 실패해도 번역은 계속 진행되어야 하므로(fail-open),
    # 여기 값들이 비어 있어도 import/부팅 단계에서 죽지 않는다.
    # 실제 실패 처리는 glossary.py 쪽에서 담당한다.
    # ------------------------------------------------------------------
    WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "")
    WEAVIATE_HTTP_PORT = int(os.environ.get("WEAVIATE_HTTP_PORT", "8080"))
    WEAVIATE_GRPC_PORT = int(os.environ.get("WEAVIATE_GRPC_PORT", "50051"))
    GLOSSARY_COLLECTION = os.environ.get("GLOSSARY_COLLECTION", "GlossaryTerm")
    EMBEDDING_SERVING_ID = os.environ.get("EMBEDDING_SERVING_ID", "")

    GLOSSARY_TOPK = int(os.environ.get("GLOSSARY_TOPK", "3"))  # 후보 하나당 검색 결과 수
    GLOSSARY_ALPHA = float(os.environ.get("GLOSSARY_ALPHA", "0.5"))
    GLOSSARY_CONCURRENCY = int(os.environ.get("GLOSSARY_CONCURRENCY", "5"))
    GLOSSARY_MAX_CANDIDATES = int(os.environ.get("GLOSSARY_MAX_CANDIDATES", "15"))
    GLOSSARY_MIN_SCORE = float(os.environ.get("GLOSSARY_MIN_SCORE", "0.75"))

    GLOSSARY_CONNECT_TIMEOUT = float(os.environ.get("GLOSSARY_CONNECT_TIMEOUT", "3"))
    GLOSSARY_READ_TIMEOUT = float(os.environ.get("GLOSSARY_READ_TIMEOUT", "10"))
    GLOSSARY_RETRY_COUNT = int(os.environ.get("GLOSSARY_RETRY_COUNT", "2"))

    # 1단계(정확 매칭) 캐시 상한. 초과하면 1단계를 끄고 2단계(벡터 검색)만 사용한다.
    # 실측 기준 50만 건 약 150MB이므로 Pod 메모리 limit에 맞춰 조정한다.
    # OOMKill로 서빙이 죽는 것보다 1단계를 포기하는 쪽이 안전하다.
    GLOSSARY_MAX_CACHED_TERMS = int(os.environ.get("GLOSSARY_MAX_CACHED_TERMS", "300000"))

    # 용어사전 전체 캐시 갱신 주기(초). main.py 시작 시 1회 + 주기적 갱신에 사용.
    GLOSSARY_REFRESH_INTERVAL_SEC = int(os.environ.get("GLOSSARY_REFRESH_INTERVAL_SEC", "1800"))
    GLOSSARY_TARGET_LANGS = [
        lang.strip() for lang in os.environ.get("GLOSSARY_TARGET_LANGS", "en,ja,zh").split(",")
        if lang.strip()
    ]

    @staticmethod
    def weaviate_api_key() -> str:
        return _require_env("WEAVIATE_API_KEY")
