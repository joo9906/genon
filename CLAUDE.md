# CLAUDE.md — genon 저장소 (SFR 기능별 작업 공간)

> 이 저장소에서 코드를 쓰거나 고칠 때의 진입 문서.
> **개발 규칙의 원본은 `genos-project/CLAUDE.md` 와 `genos-project/docs/GENOS_RULES.md` 다** —
> 영역(area)별 시그니처, 오류 코드 체계, HWP/HWPX 도메인 지식, GenOS 런타임 데이터 위치가
> 전부 거기 있다. 먼저 읽고 이 파일로 돌아올 것.
> `genos-project/` 는 CHECKSUMS.txt 로 봉인된 참조 번들이므로 **수정하지 않는다.**

---

## 저장소 구성 (2026-08-03 기준)

```
SFR-006/                  # HWPX 템플릿 채우기 (보고서·공문 초안 생성)
  template_fill/          # ⭐ 프로덕션 패키지 — SFR-006/README.md 참고
  hwpx.py                 # 레거시 {{token}} 로컬 검증 CLI (반복 블록 복제 포함)

SFR-018/                  # 글다듬이 / 번역 / FAQ — SFR-018/README.md 참고
  text_polish/            # 글다듬이 워크플로우 (area 02)
  translation_refactored/ # 번역 코드 서빙 (area 03) — 자립 실행 가능하게 조립됨
  genos-glossary/         # 용어집 강제 적용 실험

genos-project/            # 📖 읽기 전용 규칙/참조 번들 (개발가이드 PDF, 원본 소스 스냅샷)
genos_files/              # 개발가이드 PDF + hwpx_report.py PoC 사본
archive/                  # zip 백업 (건드리지 않음)
```

같은 이름의 파일이 여러 곳에 있다: `genos-project/source/` 는 **과거 스냅샷**,
SFR 폴더 안이 **현행 코드**다. 수정은 항상 SFR 폴더에서 한다.

---

## SFR-006 설계 결정 (요약 — 상세는 SFR-006/README.md)

- **누름틀(CLICK_HERE 필드) 기반**이 기본. 필드 식별은 `fieldBegin` 의 `name` 속성,
  안내문은 첫 `stringParam`. `{{token}}` 은 폴백으로만 지원.
- **채워짐 판정은 코드가 결정적으로** 한다: begin~end 사이 텍스트가 비어 있지 않고
  안내문과 다르면 채워진 것. LLM 의 역할은 사용자 발화 → `{필드명: 값}` 추출까지.
- begin/end 짝은 **문서 순서 스택 매칭** (문단/필드 id 는 신뢰 불가 — 규칙 문서 §3.2).
- 멀티턴 상태는 **파일 기반 세션 저장소** (`session_store.py`) — GenOS 는 이전 대화를
  자동 주입하지 않으므로 워크플로우 pod ↔ 코드 서빙 pod 가 볼륨을 공유해야 한다.
- 대화(area 02, `run_chat.py`)와 파일 생성(area 03, `main.py` `/generate`)은
  별개 영역이다. 다운로드 버튼은 코드 서빙을 호출한다.

## 공통 코딩 컨벤션 (규칙 문서 §5 + 이 저장소에서 정착된 것)

- LLM 호출 결과는 **`LlmResult`(content, error_type, is_transport_error) 값 객체**로
  반환한다. 전역 오류 상태 금지 (asyncio 레이스). 통신/실행 실패는 예외 타입으로 분류.
- LLM 응답은 화이트리스트/스키마 검증 후 정상 항목만 채택하고,
  기각 건수를 로그·응답으로 노출한다 (침묵 처리 금지).
- `mock`/`noop` 모드를 항상 유지 — 폐쇄망에서 LLM 없이 구조 검증.
- 오류 문자열 하드코딩 금지 → 각 패키지 `error_codes.py` 상수만.
- 사용자 노출 예외(TemplateError, TranslationRequestError 등)의 메시지는
  해당 파일 안에서 작성한 **고정 한국어 안내문만** 담는다.

## 검증 명령

```
# SFR-006 (샘플 hwpx 불필요 — 합성 픽스처)
cd SFR-006 && python -m unittest discover -s template_fill/tests -t .

# SFR-018 번역 (마크다운 구조 보존 계약 포함)
cd SFR-018/translation_refactored && python -m unittest discover -s tests -t .

# SFR-018 글다듬이 (구조 훼손 점검)
cd SFR-018 && python -m unittest discover -s text_polish/tests -t .
```

## 전처리기 입력 원칙 (SFR-018) — 매번 다시 알아내지 말 것

docx/pdf/hwpx 는 전처리기가 변환해 들어오며 **표 형식이 유형별로 다르다**
(`genos_files/attach_processor.py`, `intelligence_processor.py` 확인 결과):
- 첨부용: 마크다운 표 + `<!-- PB -->` 페이지 마커
- 지능형: 마크다운 표 또는 **한 줄 HTML 표**(`<table><tbody>…`, 셀 html.escape,
  colspan, 같은 줄 제목 접두 가능) + `[표 설명]` 요약

**표 등 구조는 건드리지 않고 내용만 바꾼다** — 번역은 `/translate/markdown` 의
스켈레톤 분리(마크다운+HTML 모두)로 구조를 코드가 보장하고, 글다듬이는
`markdown_guard.py` 지문 대조로 훼손을 감지한다.
프롬프트 지시("표를 유지하라")만으로 구조 보존을 처리하지 않는다.

## 남은 일

- SFR-006: 실제 한/글 제작 누름틀 템플릿으로 파서 검증 (stringParam name 속성 편차 확인)
- SFR-006: 반복 블록(contents 배열)이 필요해지면 `hwpx.py` → `hwpx_fields.py` 이식
- genos-glossary: 현행 translation_refactored 구조와의 병합 여부 결정 필요
