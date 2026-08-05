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
    # 라벨 항목: 본문에 텍스트로 적힌 "제목: {볼드체, 고딕, 16pt}" 를 항목으로 인식한다.
    # 현장 템플릿의 실제 방식이라 기본 켜짐. 누름틀(CLICK_HERE)은 항상 함께 지원한다.
    LABEL_FIELDS = os.environ.get("TEMPLATE_FILL_LABEL_FIELDS", "1") not in ("0", "false", "False")

    # ── 서식 명세 적용 (템플릿에 적힌 "제목: {함초롬, 16pt, bold}" 반영) ──
    # 기본 켜짐: 명세가 없는 템플릿에서는 아무 일도 일어나지 않는다.
    APPLY_STYLE_SPEC = os.environ.get("TEMPLATE_FILL_APPLY_STYLE_SPEC", "1") not in ("0", "false", "False")
    # paragraph: 명세가 붙은 필드가 놓인 문단 전체 / run: 누름틀 값만
    STYLE_SCOPE = os.environ.get("TEMPLATE_FILL_STYLE_SCOPE", "paragraph")

    # ── 입력 상한 (LLM 예산/메모리 보호) ──
    MAX_FIELDS = int(os.environ.get("TEMPLATE_FILL_MAX_FIELDS", "200"))
    MAX_VALUE_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_VALUE_CHARS", "2000"))
    MAX_MESSAGE_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_MESSAGE_CHARS", "20000"))
    # 업로드 템플릿 크기 상한 — 전량을 메모리에서 XML 파싱하므로 상한이 필요하다
    MAX_UPLOAD_BYTES = int(os.environ.get("TEMPLATE_FILL_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    # 마크다운 미리보기 길이 상한. 넘으면 잘라 내려주고 truncated 로 알린다.
    MAX_PREVIEW_CHARS = int(os.environ.get("TEMPLATE_FILL_MAX_PREVIEW_CHARS", "20000"))

    # ── PDF 다운로드 ──
    # auto: 전처리기 변환기(genon.preprocessor.converters.hwp_to_pdf)를 호출한다.
    # mock: 변환 없이 최소 PDF 를 돌려준다 — 폐쇄망에서 변환기 없이 경로만 확인할 때.
    #       실물 문서가 아니므로 호출마다 경고 로그를 남긴다.
    # off : PDF 를 아예 지원하지 않는다고 응답한다.
    PDF_MODE = os.environ.get("TEMPLATE_FILL_PDF_MODE", "auto").strip().lower()

    # ── 관리자 API 보호 (POST /templates, DELETE /templates/{id}) ──
    # 값이 있으면 X-Admin-Token 헤더가 일치해야 등록/삭제를 허용한다. 비워 두면
    # 검사하지 않으므로(사내 폐쇄망 기본), 그 사실을 기동 시 경고로 남긴다 —
    # 인증 부재를 조용히 넘기면 배포자가 보호되고 있다고 착각한다.
    ADMIN_TOKEN = os.environ.get("TEMPLATE_FILL_ADMIN_TOKEN", "").strip()
