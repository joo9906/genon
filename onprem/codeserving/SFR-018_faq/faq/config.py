"""SFR-018 FAQ 환경설정.

- 3.7절/6.7절: 시크릿은 환경변수로만. 코드에 유효한 기본값을 넣지 않고 호출 시점에 검증.
- 10.2절: LLM 은 GenOS Gateway OpenAI 호환 경로만 사용.
"""

import os


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {key}")
    return value


def _flag(key: str, default: str) -> bool:
    return os.environ.get(key, default) not in ("0", "false", "False")


class Config:
    # ── GenOS Gateway (10.2절 표준 경로) ──
    #
    # **호출 시점에 읽는다.** 클래스 속성으로 두면 **import 되는 순간 값이 굳어**, 프로세스가
    # 뜬 뒤 환경이 채워지는 경로에서는 빈 값이 그대로 남는다. GenOS 는 pod 기동 전에 환경을
    # 채우므로 지금 동작에는 지장이 없지만, 네 단위 중 글다듬이만 지연 읽기라 모양이
    # 갈려 있었다 — 2026-08-14 에 넷을 맞췄다(시크릿은 원래부터 지연 읽기였다).
    @staticmethod
    def genos_url() -> str:
        return os.environ.get("GENOS_URL", "").strip().rstrip("/")

    @staticmethod
    def llm_serving_id() -> str:
        return os.environ.get("LLM_SERVING_ID", "").strip()

    @staticmethod
    def llm_model_id() -> str:
        return os.environ.get("LLM_MODEL_ID", "").strip()

    @staticmethod
    def genos_token() -> str:
        return _require_env("GENOS_TOKEN")

    RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "90"))
    LLM_RETRY_COUNT = int(os.environ.get("LLM_RETRY_COUNT", "2"))
    # FAQ 는 문서에서 뽑는 작업이라 창작 여지를 낮게 둔다 (근거 검증 기각률과 직결)
    MODEL_TEMP = float(os.environ.get("MODEL_TEMP", "0.2"))

    # ── 생성 개수 (요구사항 §4) ──
    # 관리자가 상한을 정하고, 사용자는 0~상한 안에서 고른다. 사용자가 상한을 넘겨
    # 요청하면 상한으로 깎고 그 사실을 응답에 노출한다 (조용히 바꾸지 않는다).
    MAX_FAQ_COUNT = int(os.environ.get("FAQ_MAX_COUNT", "10"))
    DEFAULT_FAQ_COUNT = int(os.environ.get("FAQ_DEFAULT_COUNT", "5"))

    # ── 입력 상한 ──
    # LLM 컨텍스트 보호. 넘으면 앞부분만 쓰고 truncated 로 알린다 —
    # 조용히 자르면 뒷부분에서 FAQ 가 안 나온 이유를 알 수 없다.
    MAX_CONTEXT_CHARS = int(os.environ.get("FAQ_MAX_CONTEXT_CHARS", "24000"))
    MAX_UPLOAD_BYTES = int(os.environ.get("FAQ_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

    # ── 근거 검증 (요구사항 §2 — 어떤 내용에서 추출됐는지 명시) ──
    # LLM 이 evidence 로 준 문장이 실제 문서에 있는지 코드가 대조한다.
    # 임계값은 정규화 후 문자 단위 포함률. 1.0 이면 완전 일치만 인정한다.
    EVIDENCE_MIN_RATIO = float(os.environ.get("FAQ_EVIDENCE_MIN_RATIO", "0.8"))
    # 근거 검증에 실패한 항목을 버릴지(기본) 경고만 달고 남길지.
    # 버리는 쪽이 기본인 이유: 근거 없는 FAQ 는 "문서에서 뽑았다"는 계약을 깨뜨린다.
    EVIDENCE_REJECT = _flag("FAQ_EVIDENCE_REJECT", "1")

    # ── 세션 저장소 (GenOS 제공 Redis) ──
    # 워크플로우 pod(생성)와 코드 서빙 pod(다운로드)가 같은 Redis 를 본다.
    REDIS_URL = os.environ.get("REDIS_URL", "redis://llmops-redis-service:6379/0").strip()
    REDIS_KEY_PREFIX = os.environ.get("FAQ_REDIS_PREFIX", "faq:session")
    SESSION_TTL_HOURS = float(os.environ.get("FAQ_SESSION_TTL_HOURS", "24"))

    # ── 다운로드 ──
    # **설정이 없다** (2026-08-12). 산출 형식이 txt 하나가 되면서 `FAQ_HWPX_TEMPLATE_PATH`
    # 가 없어졌다 — 관리자 hwpx 템플릿의 반복 블록을 복제해 문서를 만들던 경로가
    # 통째로 사라졌기 때문이다. txt 는 볼륨도 외부 변환기도 요구하지 않는다.
    # 폐쇄망 배포에서 이 환경변수를 이미 넣어 뒀다면 **지워도 되고 남겨도 된다** —
    # 코드가 더는 읽지 않는다.

    # ── 관리자 API 보호 ──
    ADMIN_TOKEN = os.environ.get("FAQ_ADMIN_TOKEN", "").strip()

    # 프롬프트 디렉토리는 prompt_loader.prompt_dir() 가 정한다 (FAQ_PROMPT_DIR 로 덮어쓰기).
