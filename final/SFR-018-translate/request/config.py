"""번역 서비스 환경설정.

GenOS 엔지니어 개발가이드 v1.02 반영
- 3.7절 / 6.7절: 시크릿은 환경변수로만 관리하고 코드에 직접 입력하지 않는다.
  기본값에 실제 유효한 키 형태를 넣지 않는다 (없으면 명시적으로 실패시킨다).
- 10.2절: GenOS 관리 대상 모델은 Gateway OpenAI 호환 경로만 사용한다.
  외부 SDK/키로 우회 호출하는 경로를 두지 않는다.
"""

import os

from translation_pipeline.office.numeric_guard import MODE_REVERT, MODE_WARN


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {key}")
    return value


def _flag(key: str, default: str) -> bool:
    return os.environ.get(key, default) not in ("0", "false", "False")


def _numeric_guard_mode() -> str:
    """알 수 없는 값은 기본값(warn)으로 떨어뜨린다 — 오타로 검사가 꺼지지 않게."""
    value = os.environ.get("TRANSLATE_NUMERIC_GUARD", MODE_WARN).strip().lower()
    return value if value in (MODE_WARN, MODE_REVERT) else MODE_WARN


class Config:
    # ── GenOS Gateway (10.2절 표준 경로) ──
    #
    # **호출 시점에 읽는다.** 클래스 속성으로 두면 **import 되는 순간 값이 굳어**, 프로세스가
    # 뜬 뒤 환경이 채워지는 경로에서는 빈 값이 그대로 남는다. GenOS 는 pod 기동 전에 환경을
    # 채우므로 지금 동작에는 지장이 없지만, 네 단위가 같은 모양이어야 한다(시크릿은
    # 원래부터 지연 읽기다).
    @staticmethod
    def genos_url() -> str:
        return os.environ.get("GENOS_URL", "").strip().rstrip("/")

    @staticmethod
    def llm_serving_id() -> str:
        return os.environ.get("LLM_SERVING_ID", "").strip()

    # `model` 은 요청 본문에 싣지 않는다 — 게이트웨이의 서빙 경로
    # (`/rep/serving/{LLM_SERVING_ID}/v1/chat/completions`)가 이미 모델을 결정하므로
    # `LLM_SERVING_ID` 가 모델 지정 역할을 함께 하고, 본문의 `model` 은 그 위에 얹히는
    # 중복이다. 게이트웨이가 OpenAI 규격대로 `model` 을 필수로 검증하는 배포를 만나면
    # 400/422 로 드러난다 — 그때 되살릴 자리는 여기(정적 메서드)와 `llm.py` 의 요청 본문.

    # 시크릿 - 기본값 없음. import 단계가 아니라 실제 LLM 호출 시점에만 검증한다.
    @staticmethod
    def genos_token() -> str:
        return _require_env("GENOS_TOKEN")

    RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "90"))
    LLM_RETRY_COUNT = int(os.environ.get("LLM_RETRY_COUNT", "2"))
    MODEL_TEMP = float(os.environ.get("MODEL_TEMP", "0.3"))
    MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "16384"))

    LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "15"))

    # ── 스트리밍 번역 조각 예산 ──
    #
    # **조각 하나 = LLM 호출 한 번 = 화면에 흐르기 시작하는 단위**다. 작을수록 첫 글자가
    # 빨리 나오고 조각들이 겹쳐 도는 효과가 커지지만, 조각 경계 너머 문맥이 끊긴다 —
    # 이 경로는 문단·표 단위로만 끊으므로(`stream_chunking`) 문장이 갈리지는 않는다.
    # 기본값 6,000 은 글다듬이(`POLISH_MAX_CHUNK_CHARS`)와 같다: 같은 성격의 손잡이를
    # 단위마다 다른 값으로 두면 "왜 이쪽만 느린가" 에 답할 수 없다.
    #
    # 동시 호출 수는 `LLM_CONCURRENCY`(위)를 그대로 쓴다 — 배치 경로와 같은 게이트웨이를
    # 때리므로 손잡이가 둘이면 한쪽만 내려도 부하가 안 준다.
    STREAM_CHUNK_CHARS = int(os.environ.get("TRANSLATE_STREAM_CHUNK_CHARS", "6000"))
    MAX_CHARS_PER_BATCH = int(os.environ.get("MAX_CHARS_PER_BATCH", "4000"))
    MAX_ITEMS_PER_BATCH = int(os.environ.get("MAX_ITEMS_PER_BATCH", "10"))

    # ── 입력 상한 (LLM 예산·메모리 보호) ──
    MAX_NODES = int(os.environ.get("TRANSLATE_MAX_NODES", "2000"))
    MAX_TOTAL_CHARS = int(os.environ.get("TRANSLATE_MAX_TOTAL_CHARS", "500000"))
    # hwpx 업로드는 전량을 메모리에서 XML 파싱하므로 별도 상한이 필요하다
    MAX_UPLOAD_BYTES = int(os.environ.get("TRANSLATE_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

    # ── 용어사전 (요구사항 §2 — 주어지는 용어사전을 기반으로 번역) ──
    #
    # **GenOS 용어사전(`데이터 > 용어사전`)에서 받는다** — 스펙과 응답 해석은
    # `translation_pipeline/common/glossary_store.py` 머리말이 정본이다.
    # URL·인증 키·영문명 속성 키 중 하나라도 비면 용어사전 없이 번역하고 그 사실을
    # `glossary.source` 로 노출한다.
    #
    # 값은 호출 시점에 읽는다 — 게이트웨이 설정과 같은 이유다(위 절 참고).
    @staticmethod
    def glossary_api_url() -> str:
        """용어 목록 URL 전체. `{glossary_id}` 를 넣으면 사전 ID 로 치환한다.

        스펙에 REST 경로가 적혀 있지 않아 경로를 코드가 만들지 않는다.
        예: `https://admin-api.genos.internal/<용어 목록 경로>/{glossary_id}/terms`
        """
        return os.environ.get("TRANSLATE_GLOSSARY_API_URL", "").strip()

    @staticmethod
    def glossary_id() -> str:
        """용어사전 ID (관리자 콘솔 용어사전 목록의 ID 컬럼)."""
        return os.environ.get("TRANSLATE_GLOSSARY_ID", "").strip()

    @staticmethod
    def glossary_token() -> str:
        """사전의 **읽기 전용 인증 키** (용어사전 상세 → 인증 키 탭).

        게이트웨이 토큰으로 대신하지 않는다 — 인증 키는 사전마다 발급되므로 다른 값으로
        채우면 401/403 이 나고, 그 사유가 `fetch_failed_401` 로 드러난다.
        """
        return os.environ.get("TRANSLATE_GLOSSARY_TOKEN", "").strip()

    @staticmethod
    def glossary_target_key() -> str:
        """영어 대응 용어를 담은 **속성 키** (용어사전 상세 → 속성 정의 탭의 속성 키)."""
        return os.environ.get("TRANSLATE_GLOSSARY_TARGET_KEY", "").strip()

    @staticmethod
    def glossary_synonym_key() -> str:
        """한국어 동의어·줄임말을 담은 속성 키 (선택). 비우면 대표어만 찾는다."""
        return os.environ.get("TRANSLATE_GLOSSARY_SYNONYM_KEY", "").strip()

    @staticmethod
    def glossary_workspace_id() -> str:
        """`x-genos-workspace-id` 헤더 값 (선택). 비우면 헤더를 싣지 않는다."""
        return os.environ.get("TRANSLATE_GLOSSARY_WORKSPACE_ID", "").strip()

    # ── 품질 장치 ──
    # 같은 원문을 한 번만 LLM 에 보낸다 (반복 머리글·표 라벨). 끄면 유닛 수만큼 호출한다.
    DEDUPE_UNITS = _flag("TRANSLATE_DEDUPE_UNITS", "1")
    # 숫자 보존 검사 정책: warn(기본, 경고만) | revert(이탈 유닛은 원문 유지)
    NUMERIC_GUARD = _numeric_guard_mode()

    # ── 관리자 API 보호 (POST /glossary/reload) ──
    # 값이 있으면 X-Admin-Token 헤더가 일치해야 재적재를 허용한다. 비워 두면 검사하지
    # 않으므로(사내 폐쇄망 기본) 그 사실을 기동 로그 경고로 남긴다 — 인증 부재를 조용히
    # 넘기면 배포자가 보호되고 있다고 착각한다 (SFR-006 과 같은 규약).
    ADMIN_TOKEN = os.environ.get("TRANSLATE_ADMIN_TOKEN", "").strip()

    # 프롬프트 디렉토리는 prompt_loader.prompt_dir() 가 정한다
    # (TRANSLATION_PROMPT_DIR 로 덮어쓸 수 있다).

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
    # (§10.5). 안 적힌 이름은 이미지에 든 `.txt` 파일을 쓴다 — 미설정은 정상 경로다.
    @staticmethod
    def prompt_ids_raw() -> str:
        return os.environ.get("TRANSLATE_PROMPT_IDS", "").strip()

    # 요청 경로에 걸리는 호출이라 짧게 둔다 — 실패해도 파일로 진행한다.
    PROMPT_FETCH_TIMEOUT = float(os.environ.get("TRANSLATE_PROMPT_TIMEOUT", "5"))
