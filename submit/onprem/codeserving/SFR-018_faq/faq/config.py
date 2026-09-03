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
    #
    # **사용자가 고르는 개수는 문서 하나에서 만들 총 개수다** (2026-09-03 요구 확정).
    # 조각 배분은 우리가 한다 — 사용자는 "몇 개를 받을지" 만 정하고, 그 개수를 어느
    # 구간에서 몇 개씩 뽑을지는 `chunking.plan_quota` 가 정한다.
    #
    # 2026-08-31~09-02 에는 이 값이 **구간당** 개수였고 총량은 `FAQ_MAX_TOTAL_COUNT`
    # 가 잡았다. 그러면 사용자가 고른 숫자와 받는 개수가 달라진다(구간이 여섯이면
    # 5를 골라도 30개가 나온다) — 요구가 "총 개수를 사용자가 정한다" 로 확정되며
    # 그 상한 변수는 없어졌다. 대신 **호출 수 상한**(`FAQ_MAX_CHUNK_CALLS`)이 LLM
    # 예산을 잡는다: 개수와 비용을 같은 손잡이로 묶으면 둘 중 하나를 못 지킨다.
    #
    # 관리자가 상한을 정하고, 사용자는 0~상한 안에서 고른다. 사용자가 상한을 넘겨
    # 요청하면 상한으로 깎고 그 사실을 응답에 노출한다 (조용히 바꾸지 않는다).
    # 기본값 30 은 옛 총량 상한과 같다 — 실제로 만들 수 있던 최대치를 유지한다.
    MAX_FAQ_COUNT = int(os.environ.get("FAQ_MAX_COUNT", "30"))
    DEFAULT_FAQ_COUNT = int(os.environ.get("FAQ_DEFAULT_COUNT", "5"))
    # LLM 호출 수 상한 — **개수가 아니라 비용의 손잡이다.** 총 개수를 조각들이 나눠
    # 가지므로, 이 값이 없으면 30개를 30조각에 1개씩 배정해 호출이 30번이 된다.
    # 기본값 6 은 옛 규약(구간당 5개 × 여섯 구간 = 총량 30)의 호출 수와 같다.
    #
    # 상한에 걸려 몫을 받지 못한 구간은 **문서 앞뒤로 치우치지 않게 고르게 건너뛰고**
    # (`chunking.plan_quota`), 그 사실을 `coverage_capped` 로 낸다 — 조용히 건너뛰면
    # 사용자는 문서 전체에서 뽑은 결과로 읽는다.
    MAX_CHUNK_CALLS = int(os.environ.get("FAQ_MAX_CHUNK_CALLS", "6"))

    # ── 입력 상한 ──
    #
    # **이 값은 문서 상한이 아니라 LLM 호출 한 번의 예산이다** (2026-08-29 의미 변경).
    # 그전에는 문서를 이 길이로 **자르고** 한 번만 불렀다 — 넘는 문서에서는 언제나
    # 앞부분만 FAQ 후보였고, 뒷부분은 기각 건수에도 안 잡힌 채 사라졌다.
    # 지금은 문서를 이 크기의 조각으로 나눠(`chunking.split_for_context`) 각 조각이
    # 자기 몫을 만든다. 실질 문서 상한은 아래 업로드 용량이다.
    MAX_CONTEXT_CHARS = int(os.environ.get("FAQ_MAX_CONTEXT_CHARS", "24000"))
    MAX_UPLOAD_BYTES = int(os.environ.get("FAQ_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    # 조각 수 상한 — 문서 길이가 곧 LLM 비용이 되지 않게 막는 최후 방어선이다.
    # 기본값(40 × 24,000자 ≈ 96만 자)은 사내 규정집 실물을 덮고도 남는다. 여기에
    # 걸린 문서만 뒤가 잘리고, 그때만 `source_truncated` 가 참이 된다.
    #
    # **호출 수는 이 값이 아니라 `MAX_CHUNK_CALLS` 가 정한다** — 조각이 40개여도
    # 호출 상한이 6이면 LLM 은 6번 부르고 총 개수를 그 여섯이 나눈다
    # (`chunking.plan_quota`).
    MAX_CONTEXT_CHUNKS = int(os.environ.get("FAQ_MAX_CONTEXT_CHUNKS", "40"))

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
