"""글다듬이 환경설정 (2026-08-13 신규 — 번역·FAQ 단위와 같은 모양으로 맞췄다).

- 3.7절 / 6.7절: 시크릿은 환경변수로만 관리하고 코드에 직접 입력하지 않는다.
  기본값에 유효한 키 형태를 넣지 않고, 없으면 **호출 시점에** 명시적으로 실패시킨다.
- 10.2절: GenOS 관리 대상 모델은 Gateway OpenAI 호환 경로만 사용한다.

## 왜 만들었나 — 값이 import 시점에 얼어붙어 있었다

그전에는 `llm.py` 가 모듈 최상위에서 `GENOS_URL = os.environ.get(...)` 로 읽었다.
그 값은 **import 되는 순간 확정**되므로, 프로세스가 뜬 뒤 환경이 채워지는 경로
(점검 스크립트가 env 를 세팅한 뒤 단위를 싣는 경우가 정확히 이것이다)에서는 빈 값이
그대로 남아 "설정을 넣었는데 안 읽는다" 가 된다. 번역·FAQ 두 단위는 이미 `Config`
클래스로 이 문제를 피하고 있었고, 이 단위만 옛 모양이었다.

시크릿(`GENOS_TOKEN`)은 클래스 속성이 아니라 `genos_token()` 으로 둔다 — 클래스 속성으로
두면 import 단계에서 검증이 돌아 **토큰이 없는 환경에서는 모듈을 열 수조차 없다.**

## `RES_TIMEOUT` 기본값을 90 으로 올렸다

옛 값은 60 이었고 번역·FAQ 는 90 이었다. 글다듬이는 **문서 전체를 한 번에** LLM 에
보내는 단위라 셋 중 가장 오래 걸리는 쪽인데 제한이 가장 짧았다 — 긴 문서에서 timeout 이
먼저 나고, 그 실패는 재시도 가능(00020001)으로 분류돼 같은 자리에서 또 걸린다.
"""

import os


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {key}")
    return value


# ── 톤별 프롬프트 (2026-09-03) ──────────────────────────────────────────────
#
# 톤마다 **다른 프롬프트**를 GenOS 프롬프트 라이브러리에서 받는다. 그전에는 `system.j2`
# 하나에 `tone_instruction` 을 끼워 넣었고, 그 방식은 폴백으로 남는다.
#
# **여기가 코드 하드매칭 자리다.** 프롬프트는 온프레미스에서 직접 만들어야 하므로 ID 를
# 미리 알 수 없다 — 만든 뒤 아래 표에 적거나, 등록 화면의 `POLISH_PROMPT_IDS` 에
# `system_polite=51` 꼴로 넣는다(그쪽이 이긴다). **비어 있으면 지금과 동작이 같다.**
#
#     TONE_PROMPT_IDS = {"polite": "51", "friendly": "52", "clear": "53", "objective": "54"}
#
# 톤을 **관리자가 추가하면 여기 없다** — 그 톤은 `system.j2` + `tone_instruction` 으로
# 떨어진다. 코드 없이 붙이는 방법은 `onprem/docs/WIP_prompt_dynamic.md`.
TONE_PROMPT_IDS: dict = {}

# 톤 코드 → 프롬프트 이름. 이름은 **파일 이름에서 확장자를 뗀 것**과 같은 규약이라
# `.j2` 파일을 두면 그대로 폴백이 된다(지금은 두지 않는다 — 톤 지시문은 정책에서 온다).
TONE_PROMPT_NAME_FORMAT = "system_{tone}"


class Config:
    # ── GenOS Gateway (10.2절 표준 경로) ──
    # 경로 조립은 `llm._base_url()` 한 곳에서만 한다. f-string 으로 직접 이어붙이면
    # `/api/gateway` prefix 를 빠뜨린다 (018 두 단위가 실제로 그랬다 — 2026-08-05 수정).
    @staticmethod
    def genos_url() -> str:
        return os.environ.get("GENOS_URL", "").strip().rstrip("/")

    @staticmethod
    def llm_serving_id() -> str:
        return os.environ.get("LLM_SERVING_ID", "").strip()

    @staticmethod
    def llm_model_id() -> str:
        return os.environ.get("LLM_MODEL_ID", "").strip()

    # 시크릿 — 기본값 없음. import 단계가 아니라 실제 LLM 호출 시점에만 검증한다.
    @staticmethod
    def genos_token() -> str:
        return _require_env("GENOS_TOKEN")

    # ── 호출 파라미터 ──
    # 문서 전체를 한 번에 보내는 단위라 번역·FAQ 와 같은 90초를 쓴다 (머리말 참고).
    RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "90"))
    LLM_RETRY_COUNT = int(os.environ.get("LLM_RETRY_COUNT", "2"))
    MODEL_TEMP = float(os.environ.get("MODEL_TEMP", "0.3"))

    # ── 입력 상한 ──
    # 없으면 한 번의 요청이 LLM 예산과 응답 시간을 통째로 쓴다. 상한 초과는 **자르지 않고
    # 거절한다** — 잘린 문서를 다듬어 돌려주면 뒷부분이 통째로 사라진 결과가 정상 응답처럼
    # 나간다 (FAQ 는 앞부분만 쓰고 `source_truncated` 로 알리는데, 그쪽은 "문서에서 뽑기"
    # 라 부분 입력에도 결과가 성립하기 때문이다. 되쓰기는 그렇지 않다).
    MAX_INPUT_CHARS = int(os.environ.get("POLISH_MAX_INPUT_CHARS", "200000"))

    # ── 조각 분할 (2026-08-29) ──
    #
    # **상한 안쪽 문서가 실제로는 안 됐다.** 문서 전체를 한 번에 보내던 탓에 20만 자에
    # 닿기 한참 전에 `RES_TIMEOUT`(90초)이 먼저 났고, 그 실패는 재시도 가능으로 분류돼
    # 같은 자리에서 또 걸렸다 — 사용자에게는 "긴 문서는 그냥 안 되는 기능" 이었다.
    # 지금은 `chunking.split_for_polish` 로 나눠 함께 돌린다.
    #
    # 나눠도 되는 근거: 이 기능은 내용을 다시 쓰는 것이 아니라 **문체에 맞게 낱말·어미를
    # 손질**한다. 판단 단위가 문장이라 조각 경계 너머의 문맥이 필요하지 않다.
    MAX_CHUNK_CHARS = int(os.environ.get("POLISH_MAX_CHUNK_CHARS", "6000"))
    # 동시에 도는 조각 수. 순차로 돌리면 조각 수만큼 시간이 곱해져 나누는 의미가 없다.
    LLM_CONCURRENCY = int(os.environ.get("POLISH_LLM_CONCURRENCY", "4"))

    # 프롬프트 디렉토리는 prompt_loader.prompt_dir() 가 정한다
    # (POLISH_PROMPT_DIR 로 덮어쓸 수 있다).


    # ── 프롬프트 라이브러리 — 프롬프트 **본문** (2026-09-03) ──
    #
    # 아래 `genos_admin_api_url()` 을 함께 쓴다 — 톤·문서유형 정책(`policy_store`)과
    # **같은 admin-api** 이고, 이쪽은 그 값을 끼우는 **틀**(`system.j2`)을 받는다.
    #
    # `{템플릿 이름: 프롬프트 ID}`. `NAME=ID` 목록 또는 JSON. **ID 를 코드에 적지 않는다**
    # (§10.5). 안 적힌 이름은 이미지에 든 `.j2` 파일을 쓴다 — 미설정은 정상 경로다.
    @staticmethod
    def prompt_ids_raw() -> str:
        # 코드 맵을 **앞에** 둔다 — `prompt_ids()` 가 순서대로 덮으므로 환경변수가 이긴다.
        # 그래야 고객사마다 ID 가 달라도 재배포 없이 등록 화면에서 바꿀 수 있다.
        env = os.environ.get("POLISH_PROMPT_IDS", "").strip()
        code = ",".join(
            f"{TONE_PROMPT_NAME_FORMAT.format(tone=tone)}={prompt_id}"
            for tone, prompt_id in TONE_PROMPT_IDS.items()
            if str(prompt_id).strip()
        )
        if env.lstrip().startswith("{"):
            # JSON 표기는 합치지 않는다 — 두 표기를 섞어 파싱하면 규칙이 두 벌이 된다.
            return env
        return ",".join(part for part in (code, env) if part)

    # 요청 경로에 걸리는 호출이라 짧게 둔다 — 실패해도 파일로 진행한다.
    PROMPT_FETCH_TIMEOUT = float(os.environ.get("POLISH_PROMPT_TIMEOUT", "5"))

    # ── 관리자 정책 (GenOS 프롬프트 라이브러리, 가이드 §10.5) ──
    #
    # **Gateway 가 아니라 admin-api 다.** `/api/gateway/prompt/...` 경로는 없다 —
    # 클러스터 내부는 `http://llmops-admin-api-service:8080`, 외부는
    # `https://<host>/api/admin` 이다.
    #
    # **프롬프트 ID 를 코드에 직접 적지 않는다** (§10.5 금지). 둘 중 하나라도 비면
    # 내장 기본값(`tone_presets.py`)으로 돌고, 그 사실이 `GET /policies` 의
    # `source`/`reason` 으로 드러난다.
    @staticmethod
    def genos_admin_api_url() -> str:
        return os.environ.get("GENOS_ADMIN_API_URL", "").strip().rstrip("/")

    @staticmethod
    def policy_prompt_id() -> str:
        return os.environ.get("POLISH_POLICY_PROMPT_ID", "").strip()

    # 화면 진입 경로에 걸리는 호출이라 짧게 둔다 — 실패해도 내장 기본값으로 진행한다.
    POLICY_FETCH_TIMEOUT = float(os.environ.get("POLISH_POLICY_TIMEOUT", "5"))
