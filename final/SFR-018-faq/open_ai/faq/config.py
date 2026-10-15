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
    # 채우므로 지금 동작에는 지장이 없지만, 네 단위가 모두 같은 지연 읽기 방식을 쓴다.
    @staticmethod
    def genos_url() -> str:
        return os.environ.get("GENOS_URL", "").strip().rstrip("/")

    @staticmethod
    def llm_serving_id() -> str:
        return os.environ.get("LLM_SERVING_ID", "").strip()

    # **`llm_model_id()` 는 이 판본에만 있다.** 정본(`onprem/`)은 게이트웨이의 서빙
    # 경로(`/rep/serving/{LLM_SERVING_ID}/v1/chat/completions`)가 이미 모델을 결정하므로
    # `model` 을 요청 본문에 싣지 않는다. 이 판본에서 되살린 이유는 **`openai` SDK 가
    # `model` 없이 요청을 만들지 않기** 때문이다(클라이언트 쪽 필수 인자다). 기본값을
    # `"default"` 로 둔다: 게이트웨이가 무시하면 그만이고, OpenAI 규격대로 검증하는
    # 배포에서는 `LLM_MODEL_ID` 로 채운다. **정본과 갈리는 유일한 설정이고**, 지울 때는
    # `llm.py` 의 `_request_kwargs` 도 함께 본다.
    @staticmethod
    def llm_model_id() -> str:
        return os.environ.get("LLM_MODEL_ID", "").strip() or "default"

    @staticmethod
    def genos_token() -> str:
        return _require_env("GENOS_TOKEN")

    RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "90"))
    LLM_RETRY_COUNT = int(os.environ.get("LLM_RETRY_COUNT", "2"))
    # FAQ 는 문서에서 뽑는 작업이라 창작 여지를 낮게 둔다 (근거 검증 기각률과 직결)
    MODEL_TEMP = float(os.environ.get("MODEL_TEMP", "0.2"))
    # 추론 모델의 생각 단계를 끈다(`none`). 켜 두면 응답 첫 글자까지 수십 초가 걸린다.
    # 비우면 요청 본문에 싣지 않는다(추론 단계가 없는 모델 · 그 필드를 거절하는 게이트웨이).
    REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "none").strip()

    # ── 생성 개수 (요구사항 §4) ──
    #
    # **사용자가 고르는 개수는 문서 하나에서 만들 총 개수다.**
    # 조각 배분은 우리가 한다 — 사용자는 "몇 개를 받을지" 만 정하고, 그 개수를 어느
    # 구간에서 몇 개씩 뽑을지는 `chunking.plan_quota` 가 정한다. 조각이 고른 개수보다
    # 많으면 조각마다 후보를 하나씩 만들고 그중 고른 개수만 남긴다 — 받는 개수는 늘지 않는다.
    #
    # 관리자가 상한을 정하고, 사용자는 0~상한 안에서 고른다. 사용자가 상한을 넘겨
    # 요청하면 상한으로 깎고 그 사실을 응답에 노출한다 (조용히 바꾸지 않는다).
    MAX_FAQ_COUNT = int(os.environ.get("FAQ_MAX_COUNT", "30"))
    DEFAULT_FAQ_COUNT = int(os.environ.get("FAQ_DEFAULT_COUNT", "5"))

    # ── 입력 ──
    #
    # **조각 크기는 문서마다 정한다** (`chunking.chunk_budget`). `총 글자 ÷ 요청 개수` 를
    # 아래 두 값 사이로 맞춰 조각 하나가 FAQ 하나를 맡게 나누고, **모든 조각을 한 번씩
    # 부른다** — 문서 어느 구간도 LLM 이 보지 못한 채 남지 않는다.
    #
    # - 하한 `FAQ_MAX_CONTEXT_CHARS` — 짧은 문서를 잘게 쪼개지 않는다. 이보다 짧으면 한
    #   번에 요청 개수를 다 만든다.
    # - 상한 `FAQ_MAX_CHUNK_CHARS` — LLM 한 번에 실을 수 있는 길이다. 넘기면 모델·게이트웨이가
    #   뒤를 잘라 버리고, 그 절단은 우리에게 보이지 않는다.
    #
    # 상한에 걸려 조각이 요청 개수보다 많으면 조각마다 후보 1개씩을 만든 뒤 **요청 개수만
    # 고른다**(`chunking.select_spread`).
    MAX_CONTEXT_CHARS = int(os.environ.get("FAQ_MAX_CONTEXT_CHARS", "12000"))
    MAX_CHUNK_CHARS = int(os.environ.get("FAQ_MAX_CHUNK_CHARS", "40000"))
    MAX_UPLOAD_BYTES = int(os.environ.get("FAQ_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

    # 조각을 **동시에 몇 개까지 부르나.** 번역(`LLM_CONCURRENCY` 15)·
    # 글다듬이(`POLISH_LLM_CONCURRENCY` 4)와 같은 손잡이다.
    #
    # 호출 수는 조각 수가 정한다. 이 값은 "그중 몇 개가 동시에 도나"(대기시간)라
    # 게이트웨이에 실리는 부하를 잡는다.
    LLM_CONCURRENCY = int(os.environ.get("FAQ_LLM_CONCURRENCY", "6"))

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
    # 설정이 없다. 산출 형식이 md 하나라 볼륨도 외부 변환기도 요구하지 않는다.

    # ── 관리자 API 보호 ──
    ADMIN_TOKEN = os.environ.get("FAQ_ADMIN_TOKEN", "").strip()


    # ── 프롬프트 라이브러리 (GenOS 프롬프트 라이브러리, 가이드 §10.5) ──
    #
    # **Gateway 가 아니라 admin-api 다.** `/api/gateway/prompt/...` 경로는 없다 —
    # 클러스터 내부는 `http://llmops-admin-api-service:8080`, 외부는 `https://<host>/api/admin`.
    # **네 단위가 같은 환경변수 이름**(`GENOS_ADMIN_API_URL`)을 쓴다 — 단위마다 다른
    # 이름을 두면 배포가 같은 주소를 네 번 넣게 되고 한쪽만 고쳐진다.
    @staticmethod
    def genos_admin_api_url() -> str:
        return os.environ.get("GENOS_ADMIN_API_URL", "").strip().rstrip("/")

    # `{템플릿 이름: 프롬프트 ID}`. `NAME=ID` 목록 또는 JSON. **ID 를 코드에 적지 않는다**
    # (§10.5). 안 적힌 이름은 이미지에 든 `.j2` 파일을 쓴다 — 미설정은 정상 경로다.
    @staticmethod
    def prompt_ids_raw() -> str:
        return os.environ.get("FAQ_PROMPT_IDS", "").strip()

    # 요청 경로에 걸리는 호출이라 짧게 둔다 — 실패해도 파일로 진행한다.
    PROMPT_FETCH_TIMEOUT = float(os.environ.get("FAQ_PROMPT_TIMEOUT", "5"))

    # 프롬프트 디렉토리는 prompt_loader.prompt_dir() 가 정한다 (FAQ_PROMPT_DIR 로 덮어쓰기).
