"""SFR-018 내보내기 환경설정.

GenOS 엔지니어 개발가이드 v1.02 반영
- 3.7절: 시크릿은 환경변수로만 관리한다. 이 단위는 LLM·임베딩을 호출하지 않으므로
  (다듬기·번역은 이미 끝난 결과를 받는다) 현재 필요한 시크릿이 없다.
- 6.7절: 상한값은 환경변수로 조정 가능하게 두고 코드에 기본값을 명시한다.
"""

import os


class Config:
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # ── 세션 저장소 (GenOS 제공 Redis) ──
    # 다운로드는 대화 턴의 연장이 아니라 별개 HTTP 요청이고, GenOS 는 이전 대화를
    # 자동으로 주입하지 않는다(CLAUDE.md §4.2). 그래서 대화에서 만든 문단 결과를
    # 여기 보관해 두고 내보내기 요청이 꺼내 쓴다 — 화면에 보인 문장과 파일 속 문장이
    # 같아야 하므로 LLM 을 다시 부르지 않는다.
    # SFR-006 과 같은 Redis 를 쓰되 키 접두어로 분리한다.
    REDIS_URL = os.environ.get("REDIS_URL", "redis://llmops-redis-service:6379/0").strip()
    REDIS_KEY_PREFIX = os.environ.get("EXPORT_REDIS_PREFIX", "sfr018_export:session")
    # 대화~다운로드 사이에만 유지하면 되므로 짧게 잡는다. 버려진 세션 자동 회수용.
    SESSION_TTL_HOURS = float(os.environ.get("EXPORT_SESSION_TTL_HOURS", "6"))

    # ── 입력 상한 ──
    # 업로드 원본은 전량을 메모리에서 XML 파싱하므로 상한이 필요하다
    # (SFR-006 /generate/upload 와 같은 이유·같은 기본값).
    MAX_UPLOAD_BYTES = int(os.environ.get("EXPORT_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    # 문단 수·본문 길이 상한 — Redis 값 크기와 응답 크기를 묶어서 막는다
    MAX_PARAGRAPHS = int(os.environ.get("EXPORT_MAX_PARAGRAPHS", "5000"))
    MAX_TOTAL_CHARS = int(os.environ.get("EXPORT_MAX_TOTAL_CHARS", "500000"))
    # FAQ 엑셀 행 수 상한
    MAX_FAQ_ITEMS = int(os.environ.get("EXPORT_MAX_FAQ_ITEMS", "2000"))
