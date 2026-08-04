# CLAUDE.md — genon 저장소 (SFR 기능별 작업 공간)

> 이 저장소에서 코드를 쓰거나 고칠 때의 진입 문서.
> **개발 규칙의 원본은 `genos-project/CLAUDE.md` 와 `genos-project/docs/GENOS_RULES.md` 다** —
> 영역(area)별 시그니처, 오류 코드 체계, HWP/HWPX 도메인 지식, GenOS 런타임 데이터 위치가
> 전부 거기 있다. 먼저 읽고 이 파일로 돌아올 것.
> `genos-project/` 는 CHECKSUMS.txt 로 봉인된 참조 번들이므로 **수정하지 않는다.**

---

## 저장소 구성 (2026-08-05 기준)

```
onprem/                   # ⭐ 현행 코드 — 온프레미스 환경으로 옮겨 실행하는 파일들
  SFR-006_template_fill/  # HWPX 템플릿 채우기 (02 + 03)
  SFR-018_text_polish/    # 글다듬이 (02)
  SFR-018_translation/    # 번역 (03)
  SFR-018_export/         # 산출물 내보내기 hwpx·PDF·XLSX (03)
  eval/                   # 평가지표 MCP 서버 (배포 단위 아님)

SFR-006/                  # 테스트를 들고 있는 사본 (onprem 보다 앞선 버전 아님)
  template_fill/          # tests/ 포함 — 회귀 테스트가 여기 있다
  hwpx.py                 # 레거시 {{token}} 로컬 검증 CLI
SFR-018/                  # 같은 성격의 사본 — text_polish / translation_refactored / export

genos-project/            # 📖 읽기 전용 규칙/참조 번들 (개발가이드 PDF, 원본 소스 스냅샷)
genos_files/              # 개발가이드 PDF + hwpx_report.py PoC 사본
archive/                  # zip 백업 (건드리지 않음)
```

**같은 이름의 파일이 여러 곳에 있다. 어느 쪽이 현행인지 헷갈리지 말 것:**

| 위치 | 성격 |
|---|---|
| `onprem/` | **현행 코드.** 실제 온프레미스 환경에 옮겨 실행하는 파일. 기능을 더하거나 고칠 때 여기부터 고친다 |
| `SFR-006/`, `SFR-018/` | 테스트(`tests/`)를 들고 있는 사본. `onprem/` 은 tests 를 두지 않으므로 회귀 테스트는 여기서 돌린다 |
| `genos-project/source/` | 과거 스냅샷. 참조용이며 수정하지 않는다 |

두 트리는 이미 여러 곳이 어긋나 있다 (예: `logging_utils.py` 는 `onprem/` 이 화이트리스트
방식이고 `SFR-*/` 는 단일 인자, `hwpx_fields.TOKEN_RE` 는 `onprem/` 만 한글 토큰을 잡는다).
**순수 로직 모듈을 고치면 양쪽을 함께 고친다.** import 경로 규약이 다르니 주의:
`onprem/` 배포 단위는 절대 import(`from config import Config`), `SFR-*/` 는 상대 import 다.

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

# SFR-018 내보내기 (hwpx 되쓰기 — 합성 픽스처)
cd SFR-018 && python -m unittest discover -s export/tests -t .
```

`onprem/` 에는 `tests/` 를 두지 않는다 (배포용). 순수 로직은 위 명령으로 검증하고,
`onprem/` 쪽 사본은 스모크로 확인한다.

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

## SFR-018 내보내기 설계 결정 (요약 — 상세는 onprem/README.md)

- **출력 형식은 입력 형식을 따른다.** hwpx 로 들어온 것만 hwpx 로 되쓴다. docx·pdf 원본은
  되쓸 hwpx 가 없고 docx→hwpx 변환 능력은 전처리기에도 없으므로 PDF 만 제공한다 —
  빈 템플릿으로 가짜 서식을 만들어 주지 않는다.
- **문단 index 는 `POST /prepare` 응답이 유일한 기준이다.** 전처리기 마크다운을 쓰지
  않는다: 표를 한 덩어리로 직렬화하고 페이지 마커·표 설명을 끼워 넣어 원본 hwpx 문단과
  1:1 이 아니므로, 그 index 로 되쓰면 엉뚱한 문단이 바뀐다.
- **LLM 에 hwpx XML 을 넣지 않는다.** 코드가 문단 평문을 뽑아 넘기고 코드가 되쓴다.
  토큰 낭비보다 `charPrIDRef`·`itemCnt` 훼손(한 글자 틀리면 문서가 안 열림)이 위험하다.
- **되쓰기는 첫 `hp:t` 에 값, 나머지 run 은 빈 텍스트** (SFR-006 `_write_occurrence` 와 같은
  전략, 범위만 문단 전체). 문단 안 부분 강조는 첫 run 서식으로 통일되고 그 손실을
  `X-Style-Simplified-Paragraphs` 로 보고한다. 값이 원문과 같으면 건드리지 않는다.
- **원본 지문(sha256) 을 대조한다.** 원본이 바뀌면 index 가 밀려 조용히 엉뚱한 문단이
  바뀌므로 쓰기 전에 막는다. 원본 바이트는 세션에 넣지 않고(20MB 상한) 요청에 다시 받는다.
- **PDF 렌더러를 만들지 않는다.** 전처리기 변환기에 위임하고, 없으면 503 으로 알린다.

## 남은 일

- SFR-006: 실제 한/글 제작 누름틀 템플릿으로 파서 검증 (stringParam name 속성 편차 확인)
- SFR-018 내보내기: 글다듬이(02)·번역(03) 이 `/prepare` → `/results` 를 호출하도록 연결.
  지금은 내보내기 쪽 계약만 서 있고 호출부가 없다.
- SFR-018 내보내기: 실제 온프레미스에서 PDF 변환기 가용성 확인 (`document_converter_available`)
- SFR-006: `hwpx_repeat.fill_with_repeat` 를 `fill_template` 에 연결 (입력 계약 `contents` 확정 후)
- 두 트리(`onprem/` ↔ `SFR-*/`) 드리프트 전수 점검 — `logging_utils.py` 계약 통일 여부 결정
- genos-glossary: 현행 translation 구조와의 병합 여부 결정 필요
