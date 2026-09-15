"""SFR-006 HWPX 템플릿 채우기 패키지.

hwpx 템플릿의 누름틀(CLICK_HERE 필드)을 스캔하고, 멀티턴 대화로 수집한
값을 채워 초안 문서를 생성한다.

- run_chat.py : GenOS 워크플로우 Python 단계 (area 02) — 대화로 필드 값 수집
- main.py     : GenOS 코드 서빙 (area 03) — 다운로드 버튼이 호출하는 파일 생성 API
- hwpx_fields.py : 두 영역이 공유하는 lxml 기반 누름틀 파서/필러
"""
