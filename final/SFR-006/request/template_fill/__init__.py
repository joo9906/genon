"""SFR-006 HWPX 템플릿 채우기 패키지.

hwpx 템플릿의 채울 자리(슬롯 `{'항목명', …}`, 누름틀)를 스캔하고, 멀티턴 대화와
업로드 문서로 수집한 값을 채워 초안 문서를 생성한다.

- main.py        : GenOS 코드 서빙 (area 03) — 템플릿 관리·화면 편집·다운로드 API
- chat_api.py    : 대화 경로(`/chat/*`). 워크플로우 스텝(area 02,
                   `final/workflow/sfr006_0*.py`)이 부른다
- hwpx_fields.py : lxml 기반 파서/필러 — hwpx 판정의 정본
"""
