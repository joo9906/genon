"""SFR-006 템플릿 채우기 환경설정.

GenOS 엔지니어 개발가이드 v1.02 반영
- 3.7절/6.7절: 시크릿은 환경변수로만 관리. 코드에 기본값으로 유효한 키를 넣지 않는다.
  토큰은 호출 시점에 검증한다.
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

    # ── 템플릿 저장소 경로 (워크플로우 pod ↔ 코드 서빙 pod 가 공유하는 볼륨) ──
    TEMPLATE_DIR = os.environ.get("TEMPLATE_FILL_TEMPLATE_DIR", "./templates")

    # ── 세션 저장소 (GenOS 제공 Redis) ──
    # 멀티턴 상태를 파일 볼륨 대신 GenOS Redis 로 공유한다. 워크플로우 pod 와
    # 코드 서빙 pod 가 같은 Redis 를 바라보므로 공유 볼륨 마운트가 필요 없다.
    # 기본값은 사내 GenOS Redis 서비스 DNS (deep_search 계열 노드와 동일 규약).
    # 접속 규약이 다른 배포는 REDIS_URL 로 주입 (redis://:pass@host:6379/0).
    REDIS_URL = os.environ.get("REDIS_URL", "redis://llmops-redis-service:6379/0").strip()
    REDIS_KEY_PREFIX = os.environ.get("TEMPLATE_FILL_REDIS_PREFIX", "template_fill:session")
    # 세션 진행 중 값을 유지하는 시간. 문서 생성 완료 시 즉시 삭제하며, 이 TTL 은
    # 완료 없이 버려진(abandoned) 세션을 자동 회수하는 안전망 역할만 한다.
    SESSION_TTL_HOURS = float(os.environ.get("TEMPLATE_FILL_SESSION_TTL_HOURS", "24"))

    # ── 템플릿 색인 캐시 (등록 시점 1회 파싱 결과) ──
    # 같은 Redis 를 쓰지만 세션과 다른 접두어를 둔다 — 수명(템플릿은 장기, 세션은 24h)과
    # 삭제 시점이 달라 한 접두어에 섞으면 세션 정리가 색인을 지운다.
    REDIS_INDEX_PREFIX = os.environ.get("TEMPLATE_FILL_REDIS_INDEX_PREFIX", "template_fill:index")
    # 템플릿은 오래 살지만, 삭제된 템플릿의 색인이 영구히 남지 않게 만료를 둔다.
    # 색인이 만료돼도 다음 요청이 다시 파싱하므로 기능에는 영향이 없다(성능만).
    INDEX_TTL_HOURS = float(os.environ.get("TEMPLATE_FILL_INDEX_TTL_HOURS", "720"))

    # ── 채울 자리 인식 방식 ──
    # 슬롯: 본문에 텍스트로 적힌 "제 목 : {'제목', 16pt, 고딕, 볼드}" 를 항목으로 인식한다.
    # 중괄호 **안**만 채울 자리이고 밖은 원문 그대로 남는다. 기본 켜짐.
    # 누름틀(CLICK_HERE)과 `{{token}}` 은 항상 함께 지원한다.
    # 옛 이름(TEMPLATE_FILL_LABEL_FIELDS)도 읽는다 — 라벨 방식을 쓰던 배포가 이 스위치를
    # 꺼 두었다면, 이름이 바뀌었다는 이유로 조용히 켜져서는 안 된다.
    SLOT_FIELDS = os.environ.get(
        "TEMPLATE_FILL_SLOT_FIELDS",
        os.environ.get("TEMPLATE_FILL_LABEL_FIELDS", "1"),
    ) not in ("0", "false", "False")

    # ── 서식 적용 (슬롯 인자 "{'제목', 16pt, 함초롬, 볼드}" 반영) ──
    # 기본 켜짐: 서식 인자가 없는 템플릿에서는 아무 일도 일어나지 않는다.
    APPLY_STYLE_SPEC = os.environ.get("TEMPLATE_FILL_APPLY_STYLE_SPEC", "1") not in ("0", "false", "False")
    # slot: 중괄호 자리에만 (기본 — 중괄호 밖 라벨은 원래 서식 유지)
    # paragraph: 슬롯이 놓인 문단 전체 (라벨까지 같이 커진다)
    # run: 누름틀도 값 run 에만
    STYLE_SCOPE = os.environ.get("TEMPLATE_FILL_STYLE_SCOPE", "slot")

    # ── 본문 블록 (템플릿 항목을 다 채운 뒤 내용을 더 이어 쓰는 경로) ──
    # 템플릿 항목은 개수가 고정이라, 다 채우면 더 쓸 자리가 없다. 블록은 그 자리를
    # 만든다 — 서식은 템플릿 문단을 복제해 물려받으므로 새 서식 정의가 생기지 않는다.
    BODY_BLOCKS = os.environ.get("TEMPLATE_FILL_BODY_BLOCKS", "1") not in ("0", "false", "False")
    # 삽입 기준 항목명. 비우면 문서 맨 끝에 붙인다. 서명란처럼 마지막에 고정돼야 하는
    # 문단이 있는 템플릿만 지정한다 (그 항목 문단 **바로 뒤**에 들어간다).
    BLOCK_ANCHOR = os.environ.get("TEMPLATE_FILL_BLOCK_ANCHOR", "").strip()
    MAX_BLOCKS = int(os.environ.get("TEMPLATE_FILL_MAX_BLOCKS", "100"))
    MAX_BLOCK_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_BLOCK_CHARS", "4000"))

    # ── 입력 상한 (LLM 예산/메모리 보호) ──
    MAX_FIELDS = int(os.environ.get("TEMPLATE_FILL_MAX_FIELDS", "200"))
    MAX_VALUE_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_VALUE_CHARS", "2000"))
    MAX_MESSAGE_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_MESSAGE_CHARS", "20000"))
    # 업로드 템플릿 크기 상한 — 전량을 메모리에서 XML 파싱하므로 상한이 필요하다
    MAX_UPLOAD_BYTES = int(os.environ.get("TEMPLATE_FILL_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    # 마크다운 미리보기 길이 상한. 넘으면 잘라 내려주고 truncated 로 알린다.
    MAX_PREVIEW_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_PREVIEW_CHARS", "20000"))
    # 대화 응답에 채운 문서 미리보기를 함께 실을지. 턴마다 채우기를 1회 수행하므로
    # 아주 큰 템플릿에서 부담되면 0 으로 끈다 (UI 는 GET /preview 로 대체 가능).
    CHAT_PREVIEW = os.environ.get("TEMPLATE_FILL_CHAT_PREVIEW", "1") not in ("0", "false", "False")

    # ── 산출물 검증 ──
    # 내보내기 직전에 개봉 안전 검사를 돌리고, 통과하지 못하면 문서를 내보내지 않는다.
    # 기본 켜짐 — 이 검사가 한/글 없이 "산출물이 열리는가" 를 판정하는 유일한 수단이다.
    # 검사기는 벤더 사본(`template_fill/_vendor/`)이라 **모든 환경에 항상 있다.**
    # 예전에는 pip 의존이라 wheel 이 없는 환경에서 스위치와 무관하게 꺼졌는데, 그러면
    # 배포 환경에 따라 산출물이 검증 없이 나갔다 (2026-08-10 에 사본으로 바꾼 이유).
    # 끄는 경우는 하나뿐이다: 검사기가 정상 문서를 오판해 운영이 막힐 때의 탈출구.
    VERIFY_OUTPUT = os.environ.get("TEMPLATE_FILL_VERIFY_OUTPUT", "1") not in ("0", "false", "False")
    # 표 셀 슬롯에 값이 넘치는지 추정해 경고한다 (문서 생성은 막지 않는다).
    CHECK_OVERFLOW = os.environ.get("TEMPLATE_FILL_CHECK_OVERFLOW", "1") not in ("0", "false", "False")

    # PDF 다운로드에는 설정이 없다 — 전처리기 변환기
    # (genon.preprocessor.converters.hwp_to_pdf)를 그대로 호출하고, 가용 여부는
    # 그 패키지·백엔드 존재로 판단한다 (pdf_convert.available()).

    # ── 관리자 API 보호 (POST /templates, DELETE /templates/{id}) ──
    # 값이 있으면 X-Admin-Token 헤더가 일치해야 등록/삭제를 허용한다. 비워 두면
    # 검사하지 않으므로(사내 폐쇄망 기본), 그 사실을 기동 시 경고로 남긴다 —
    # 인증 부재를 조용히 넘기면 배포자가 보호되고 있다고 착각한다.
    ADMIN_TOKEN = os.environ.get("TEMPLATE_FILL_ADMIN_TOKEN", "").strip()
