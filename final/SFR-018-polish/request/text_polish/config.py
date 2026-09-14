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
# `system_polite=91` 꼴로 넣는다(**그쪽이 이긴다**). 비어 있으면 `system.j2` 로 떨어진다.
#
# **최종적으로는 환경변수로 뺀다** (§10.5 — ID 를 코드에 두지 않는다). 아래 값은
# 2026-09-07 프로토타입 시연용으로 적어 둔 것이고, 등록 화면에 같은 이름을 넣는 순간
# 그쪽이 이기므로 **지우지 않아도 이관을 막지 않는다.**
#
# 값이 **빈 문자열이면 그 줄은 통째로 무시된다**(`prompt_ids_raw` 가 거른다) — 그래서
# 아직 안 만든 프롬프트를 미리 적어 둬도 안전하다.
TONE_PROMPT_IDS: dict = {
    # 온프레미스 프롬프트 라이브러리에서 받은 번호 (2026-09-07)
    "objective": "100",   # 사실·객관
    "clear": "97",        # 명확·간결
    "friendly": "94",     # 친절·안내
    "polite": "91",       # 격식·정중

    # ── 관리자가 추가할 자리 셋 ──────────────────────────────────────────
    #
    # **여기만 채우면 안 된다.** 톤 목록의 출처는 `tone_presets.TONE_PRESETS` 이고,
    # 표에 없는 코드는 화면 드롭다운에도 안 뜨고 `resolve_policy` 도 안 받는다 —
    # **프롬프트만 등록되고 아무 데서도 안 쓰이는** 상태가 된다(오류는 안 난다).
    #
    # 톤 하나를 늘릴 때 고칠 자리는 **넷**이다:
    #   1) 아래 줄의 키를 실제 톤 코드로 바꾸고 ID 를 적는다
    #   2) `tone_presets.TONE_PRESETS` 에 `TonePreset(label=…, instruction=…)` 추가
    #   3) MCP `onprem/mcp/genon_lang_policy.py` 의 `LPTONE_PRESETS` 에 **같은 값**
    #      (강제 톤 판정이 그쪽이다 — 갈리면 고른 톤이 조용히 무시된다)
    #   4) eval `onprem/eval/eval_mcp/tone_metrics.py` 의 `TONE_RULES`
    #      (안 넣으면 그 톤은 채점에서 `skipped` 로 빠진다)
    #
    # 2·3 이 갈리는지는 `python onprem/test/check_tone_policy.py` 가 잡는다.
    "custom_tone_1": "",
    "custom_tone_2": "",
    "custom_tone_3": "",
}

# 톤 코드 → 프롬프트 이름. 이름은 **파일 이름에서 확장자를 뗀 것**과 같은 규약이라
# `.j2` 파일을 두면 그대로 폴백이 된다(지금은 두지 않는다 — 톤 지시문은 내장 표에서 온다).
TONE_PROMPT_NAME_FORMAT = "system_{tone}"

# ── 문서유형별 추가 지시문 (2026-09-07) ─────────────────────────────────────
#
# 톤과 **같은 규약**이다: 문서유형마다 프롬프트 한 건을 라이브러리에 만들고 이름으로
# 매칭한다. 본문은 `system.j2` 의 `{{ doc_type_instruction }}` 자리에 그대로 들어간다.
#
# 이 경로가 2026-09-07 에 **JSON 정책 문서를 대체했다.** 그전에는 관리자가 프롬프트
# 하나에 `{"doc_types": [{"code","label","extra_instruction"}]}` 를 담고 코드서빙이
# `json.loads` 로 읽었다 — 요구가 "프롬프트는 전부 라이브러리에서 당기고 코드서빙 안에서
# JSON 을 해석하지 않는다" 로 바뀌어 걷어냈다.
#
# **라벨·강제 톤은 여기로 오지 않는다** — 프롬프트 본문은 문장 하나라 그런 값을 담을 수
# 없다. 그 둘은 `tone_presets.DOC_TYPE_POLICIES` 가 계속 들고 있고, 지시문만 덮인다.
# 물려받지 않으면 지시문을 고친 순간 **강제 톤이 사라진다**(오류 없이 문체만 달라진다).
#
# 값이 **빈 문자열이면 그 줄은 통째로 무시된다** — 아직 안 만든 프롬프트를 미리 적어
# 둬도 안전하고, 그동안은 내장 표의 `extra_instruction` 이 그대로 쓰인다.
DOC_TYPE_PROMPT_IDS: dict = {
    # 내장 문서유형 5종. 프롬프트를 만들면 번호만 채운다.
    "email": "",              # 메일???
    "post": "",               # 게시글
    "customer_notice": "",    # 고객발송문구
    "debt_reason": "",        # 채무 및 연체발생 사유 (톤 고정: 사실·객관)
    "reviewer_opinion": "",   # 심사역 의견        (톤 고정: 사실·객관)

    # ── 관리자가 추가할 자리 셋 ──────────────────────────────────────────
    #
    # 톤과 같다 — **여기만 채우면 안 된다.** 문서유형 목록의 출처는
    # `tone_presets.DOC_TYPE_POLICIES` 이고, 표에 없는 코드는 화면에도 안 뜨고
    # `normalize_doc_type` 이 기본 문서유형(메일)으로 떨어뜨린다.
    #
    # 고칠 자리는 **셋**이다 (eval 은 톤만 채점하므로 여기엔 없다):
    #   1) 아래 줄의 키를 실제 문서유형 코드로 바꾸고 ID 를 적는다
    #   2) `tone_presets.DOC_TYPE_POLICIES` 에 `DocTypePolicy(label=…, forced_tone=…)` 추가
    #   3) MCP `genon_lang_policy.py` 의 `LPDOC_TYPE_POLICIES` 에 **같은 값**
    #
    # **강제 톤을 걸려면 2·3 에 `forced_tone` 을 적어야 한다** — 프롬프트 본문에는
    # 담을 수 없다(문장 하나다).
    "custom_doc_type_1": "",
    "custom_doc_type_2": "",
    "custom_doc_type_3": "",
}

DOC_TYPE_PROMPT_NAME_FORMAT = "doc_type_{doc_type}"


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

    # **`llm_model_id()` 를 2026-09-07 에 없앴다.** 게이트웨이의 서빙 경로
    # (`/rep/serving/{LLM_SERVING_ID}/v1/chat/completions`)가 이미 모델을 결정하므로
    # `LLM_SERVING_ID` 가 모델 지정 역할을 함께 한다 — 요청 본문의 `model` 은 그 위에
    # 얹히는 중복이었고 실환경에서 필요하지 않다(요구 확정).
    #
    # **되살릴 자리는 둘이다**: 여기(정적 메서드)와 `llm.py` 의 요청 본문. 게이트웨이가
    # OpenAI 규격대로 `model` 을 필수로 검증하는 배포를 만나면 400/422 로 드러난다.

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
    # 아래 `genos_admin_api_url()` 을 함께 쓴다. 시스템 프롬프트 골격(`system`), 톤 전용
    # 프롬프트(`system_<tone>`), 문서유형 지시문(`doc_type_<code>`)이 **한 매핑**에 담긴다.
    #
    # `{템플릿 이름: 프롬프트 ID}`. `NAME=ID` 목록 또는 JSON. **ID 를 코드에 적지 않는다**
    # (§10.5). 안 적힌 이름은 이미지에 든 `.j2` 파일을 쓴다 — 미설정은 정상 경로다.
    @staticmethod
    def prompt_ids_raw() -> str:
        # 코드 맵을 **앞에** 둔다 — `prompt_ids()` 가 순서대로 덮으므로 환경변수가 이긴다.
        # 그래야 고객사마다 ID 가 달라도 재배포 없이 등록 화면에서 바꿀 수 있다.
        env = os.environ.get("POLISH_PROMPT_IDS", "").strip()
        pairs = [
            (TONE_PROMPT_NAME_FORMAT.format(tone=key), prompt_id)
            for key, prompt_id in TONE_PROMPT_IDS.items()
        ] + [
            (DOC_TYPE_PROMPT_NAME_FORMAT.format(doc_type=key), prompt_id)
            for key, prompt_id in DOC_TYPE_PROMPT_IDS.items()
        ]
        code = ",".join(
            f"{name}={prompt_id}" for name, prompt_id in pairs if str(prompt_id).strip()
        )
        if env.lstrip().startswith("{"):
            # JSON 표기는 합치지 않는다 — 두 표기를 섞어 파싱하면 규칙이 두 벌이 된다.
            return env
        return ",".join(part for part in (code, env) if part)

    # 요청 경로에 걸리는 호출이라 짧게 둔다 — 실패해도 파일로 진행한다.
    PROMPT_FETCH_TIMEOUT = float(os.environ.get("POLISH_PROMPT_TIMEOUT", "5"))

    # ── admin-api 주소 (가이드 §10.5) ──
    #
    # **Gateway 가 아니라 admin-api 다.** `/api/gateway/prompt/...` 경로는 없다 —
    # 클러스터 내부는 `http://llmops-admin-api-service:8080`, 외부는
    # `https://<host>/api/admin` 이다.
    #
    # 비어 있으면 프롬프트를 전부 이미지에 든 `.j2` 파일로 쓰고, 그 사실이
    # `GET /prompts` 의 `source`/`reason` 으로 드러난다. **미설정은 정상 경로다.**
    @staticmethod
    def genos_admin_api_url() -> str:
        return os.environ.get("GENOS_ADMIN_API_URL", "").strip().rstrip("/")

