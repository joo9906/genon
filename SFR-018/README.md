# SFR-018 — 글다듬이 / 번역 / FAQ

| 기능 | 폴더 | 실행 영역 | 상태 |
|---|---|---|---|
| 글다듬이 | `text_polish/` | 워크플로우 Python 단계 (02) | 동작 — LlmResult 패턴 정렬 완료 |
| 번역 | `translation_refactored/` | 코드 서빙 (03) | 동작 — 패키지 조립 완료 (폴더 README 참고) |
| 번역(용어집 실험) | `genos-glossary/` | 코드 서빙 (03) | 용어집(glossary) 강제 적용 실험 브랜치 |
| FAQ | (별도 구현 존재) | — | 이 폴더 범위 밖 |

## 입력 경로 공통 사항 — 전처리기 산출물 (마크다운 + HTML 표)

docx/pdf/hwpx 는 회사 전처리기를 거쳐 들어오며, 표 형식이 유형별로 다르다
(`genos_files/` 전처리기 소스 확인 결과):

- **첨부용(attach_processor)**: 마크다운 표(`| a | b |`) + `<!-- PB -->` 페이지 마커
- **지능형(intelligence_processor)**: `table_format` 설정에 따라 마크다운 표 또는
  **한 줄 HTML 표**(`<table><tbody>…`, 셀 텍스트 html.escape, colspan 보존,
  같은 줄에 제목 접두 텍스트 가능) + `[표 설명]` 요약 병기

표 등 구조는 건드리지 않고 내용만 바꾸는 원칙의 구현 방식이 기능별로 다르다:

- **번역**: `/translate/markdown` — 분해 시점에 표 파이프·HTML 태그·제목·목록·
  코드펜스를 코드가 스켈레톤으로 분리하고 **텍스트 내용만 LLM 에 보낸다**.
  재조립 결과의 구조는 LLM 출력과 무관하게 항상 원본과 동일 (구조적 보장).
- **글다듬이**: 문장 문맥이 필요해 문서를 통째로 보내되, 다듬기 전/후 구조
  지문(마크다운 표 행·열, HTML 표 행·셀, 제목, 코드펜스)을 `markdown_guard.py`
  로 대조해 훼손 시 경고를 노출한다 (감지 방식 — 재작성 특성상 스켈레톤 분리가 부적합).

## 글다듬이 (text_polish)

- 진입점: `main.py`의 `run(data)` — 업로드 문서(genosUploaded 마크다운) 우선,
  없으면 채팅 텍스트를 다듬는다.
- 문서유형 8종 × 톤 3종 정책은 `tone_presets.py`의 선언적 딕셔너리 하나로 관리
  (톤 고정군은 사용자가 다른 톤을 요청해도 강제 톤으로 대체 + 안내 문구).
- 변경 내역은 LLM에게 묻지 않고 `diff_report.py`의 difflib으로 결정적으로 계산.
- `llm.py`는 translation_refactored와 동일한 `LlmResult` 패턴 —
  전역 오류 상태 없음, 통신/실행 실패를 예외 타입으로 분류.

## 번역 (translation_refactored)

`translation_refactored/README.md` 참고. 핵심 리팩토링 3가지:
전역 오류 레이스 제거(LlmResult), 동일 원문 dict 키 충돌 계약 명시,
배치 실패 시 단건 fallback 병렬화 + 실패 유닛 명시 추적.
