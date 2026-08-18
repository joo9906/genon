# 기능 명세 — 지금 무엇이 구현돼 있고, 무엇이 계약인가

> **본문은 2026-08-11 에 코드에서 뽑아 적었고**(엔드포인트·환경변수·캔버스 변수·MCP 도구를
> 손으로 옮기지 않고 소스를 훑어 만들었다), 그 뒤 바뀐 것 중 **등록 단위 수(9)·번역 스텝 1의
> hwpx 입력 경로**만 2026-08-14 에 반영했다. **전면 재대조는 하지 않았다** — 2026-08-12~14
> 변경(018 산출물 txt 통일 · 006 톤 제거 · 설정 부재 분류 · 용어사전 하이라이트 필드 ·
> hwpx 전처리기 신설)의 세부는 각 절이 가리키는 정본 문서와 어긋날 수 있다. 그 다섯 건의
> 정본은 순서대로 `SFR-018_txt_output.md` · 루트 `CLAUDE.md` · `last_refactor.md` ·
> `../README.md`("프론트 하이라이트 계약") · `../preprocessor/README.md` 다.

## 이 문서의 자리

| 문서 | 답하는 질문 |
|---|---|
| **이 문서** | **무엇이 구현돼 있나. 어느 경로로 부르나. 무엇을 보장하나** |
| `README.md` | 어떻게 배포하나 (환경변수·로깅 규약·이관 순서) |
| `ARCHITECTURE_SPLIT.md` | 왜 이렇게 나눴나 (영역 재배치의 근거) |
| `HANDOFF.md` | 다음 사람이 어디서부터 이어서 하나 |
| `SFR-006_architecture.md` | 006 내부 설계 심화 |
| 루트 `CLAUDE.md` | 설계 결정과 그 이유 (변경 이력 포함) |

기능이 늘거나 계약이 바뀌면 여기를 고친다. **"왜 그렇게 했나" 는 여기 적지 않는다** —
그건 `CLAUDE.md` 와 각 모듈 docstring 의 몫이고, 두 벌로 적으면 갈린다.

---

## 0. 전체 지도

기능 4개가 **영역 3개**에 나뉘어 있다. 한 기능이 여러 영역에 걸치는 것이 정상이다.

```
 사용자 ── 캔버스(워크플로우, area 02) ── 게이트웨이 ─┬─ 코드서빙(area 03) ── LLM
                  스텝 9개                            │      단위 4개
             httpx 만 쓴다                            └─ MCP 도구(area 01)
                                                           파일 4개 · LLM 없음
```

| | area 02 워크플로우 | area 03 코드서빙 | area 01 MCP |
|---|---|---|---|
| 등록 단위 | **파일 1개 = 스텝 1개** (9개) | 디렉토리 = 서빙 (4개) | **파일 1개 = 도구 묶음 1개** (4개) |
| 쓰는 외부 패키지 | **`httpx` 뿐** | fastapi·lxml·redis·jinja2·openai 등 | stdlib (hwpx 만 `lxml`) |
| 진입점 | `run(data)` | FastAPI 앱 + `$PORT` | `@mcp.tool()` — 앱도 포트도 없다 |
| LLM | 부르지 않는다 | 부른다 | **부르지 않는다** |

**등록은 9번**(코드서빙 4 + MCP 4 + **hwpx 전처리기 1**), **저장소는 1개**다.
근거는 `HANDOFF.md` §5, 칸마다 적을 값은 `SERVING_REGISTRY.md`.

**area 05 전처리기는 이 표에 없다** — hwpx 를 RAG 로 적재하는 경로라 위 네 기능 어디에도
배선돼 있지 않고 워크플로우가 부르지도 않는다. 등록 형태는 MCP 와 같은 파일 단위이고,
명세는 `../preprocessor/README.md` 가 정본이다.

**MCP 는 서빙이 아니라 파일이다.** GenOS 는 소스 파일 한 개를 받아 실행하고 `mcp` 객체를
런타임이 전역으로 주입한다. FastAPI 앱·`/health`·`$PORT`·`requirements.txt` 가 전부 없다
(2026-08-11 정정 — 그전에는 코드서빙처럼 만들어 뒀다). 상세는 `../mcp/README.md`.

### 기능 × 영역

| 기능 | 워크플로우 스텝 | 코드서빙 | MCP |
|---|---|---|---|
| SFR-006 템플릿 채우기 | 3 | `SFR-006_template_fill` | — |
| SFR-018 글다듬이 | 2 | `SFR-018_text_polish` | `lang_policy`, `text_guard` |
| SFR-018 번역 | 2 | `SFR-018_translation` | `lang_policy`, `text_guard`, `glossary` |
| SFR-018 FAQ | 2 | `SFR-018_faq` | `hwpx_text` |

---

## 1. SFR-006 — HWPX 템플릿 채우기

hwpx 템플릿의 **채울 자리**를 찾아 대화로 값을 모으고, 다운로드 버튼을 누르면
초안 **hwpx** 를 만들어 준다 (PDF 출력은 2026-08-14 에 걷어냈다).

### 1-1. 채울 자리를 어떻게 아는가 — 인식 방식 3종

우선순위대로 **슬롯 → 누름틀 → `{{token}}`** 이다.

| 방식 | 생김새 | 상태 |
|---|---|---|
| **슬롯** | `제 목 : {'제목', 16pt, 맑은 고딕, 볼드}` | **기본** (2026-08-06~). 현장 템플릿이 이 모양이다 |
| 누름틀(CLICK_HERE) | 한/글에서 심은 필드 | 폴백 — 관리자가 필드를 심어 올려도 동작한다 |
| `{{token}}` | `부서: {{dept}}` | 프로토타입 호환용 |

슬롯 규칙(계약):

- **첫 인자는 따옴표 필수**이고, 그 문자열이 곧 항목명이자 LLM 안내문이다.
- 뒤 인자 0~3개는 크기·글꼴·굵게이며 **순서·개수가 자유롭다** (`16pt`=크기, `볼드`=굵게,
  남은 것이 글꼴). 지정하지 않은 인자는 **건드리지 않는다.**
- **중괄호 밖은 원문 그대로 남는다** — `제 목  : ` 의 줄맞춤 공백까지.
- 한 문단에 여러 개가 올 수 있다 (`담당자 : {'소속'} {'성명'}`).
- **굽은 따옴표(`‘제목’`)도 받는다.** 한/글 자동 고침이 바꿔 저장하고, 관리자는 그
  차이를 눈으로 구분할 수 없다. 한쪽만 바뀐 문서(`‘제목'`)도 연다.
- **따옴표 없는 `{…}` 는 채울 자리가 아니다** (`{YYYY.MM.DD. (요일)}` 는 값 안내다).
  원문 그대로 두고 등록 시 경고로만 알린다.
- **슬롯은 언제나 미입력이다** — 채우면 `{…}` 자체가 사라지므로, 남아 있다는 것이 곧
  아직 안 채웠다는 뜻이다.

끄는 스위치: `TEMPLATE_FILL_SLOT_FIELDS=0` (옛 이름 `..._LABEL_FIELDS` 도 읽는다).

### 1-2. 코드서빙 엔드포인트

| 경로 | 하는 일 |
|---|---|
| `GET /health`, `GET /`, `GET ""` | 헬스체크·루트 |
| `GET /templates` | 등록된 템플릿 목록 (+ 색인 상태) |
| `POST /templates` | **관리자** 등록 (업로드 + 즉시 색인). **파싱을 먼저, 파일 쓰기를 나중에** |
| `DELETE /templates/{id}` | **관리자** 삭제 (+ 색인 폐기) |
| `GET /fields` | 항목 스키마 + 본문 블록 서식 목록 |
| `GET /status` | 세션 채움 현황 (다운로드 버튼 활성화 판단용) |
| `GET /preview` | 채운 결과를 마크다운으로 (표시 전용) |
| `PATCH /values` · `DELETE /values` | 화면에서 고친 항목 값 반영·비우기 |
| `PUT /blocks` | 본문 추가 내용 **배열 통째 교체** |
| `POST /generate` | 등록 템플릿으로 초안 생성 + 다운로드 (**hwpx 만** — 2026-08-14) |
| `POST /generate/upload` | **업로드한 hwpx** 로 즉석 생성 (multipart) |
| `POST /chat/context` · `/chat/extract` · `/chat/commit` | 대화 3단계 — 워크플로우 스텝이 부른다 |

`PUT /blocks` 가 배열 통째 교체인 이유: 인덱스가 어긋나 **엉뚱한 문단을 지우는** 것을
막기 위해서다.

### 1-3. 워크플로우 스텝 3개

| 스텝 | 부르는 곳 | 캔버스 변수 | 내는 것 |
|---|---|---|---|
| `sfr006_01_context` | `POST /chat/context` | `template_fill_template_id` | `field_names`·`field_values`·`fields_missing`·**`ready_for_download`**·`template_markdown` |
| `sfr006_02_extract` | `POST /chat/extract` | — | 채택/기각 항목 |
| `sfr006_03_commit` | `POST /chat/commit` | — | 답변 스트리밍(`token`) 후 `result` **1회** |

`ready_for_download` 가 **캔버스 분기의 근거**다 — "다 채웠으면 다운로드 안내 노드로,
아니면 추출 스텝으로" 를 스텝 1 뒤에 건다.

**톤(글다듬이) 변환은 2026-08-12 에 뺐다** — 실제 배포 템플릿이 관리자가 정한 고정
톤으로 채우면 되는 성격이라 사용자 발화별 톤 선택이 불필요했다. `template_fill_tone`
변수, `tone_llm_error_fields`/`_blocks` 등 톤 관련 필드는 이제 없다. 코드는
`archive/sfr006-tone` 브랜치.

### 1-4. 문서 조립 — 순서가 계약이다

```
서식 적용  →  채우기  →  본문 블록
```

`document.build` **한 곳에만** 있다. 슬롯 방식이 되면서 앞의 둘이 뒤집혔다 — 채우면
`{…}` 가 사라져 어디에 무슨 서식을 걸지 알 수 없기 때문이다.

- **서식은 LLM 없이 코드가 적용한다**: `charPr` 을 복제해 크기(1pt=100)·폰트·굵게만 바꾸고
  그 id 를 **슬롯 run** 에 건다 (`STYLE_SCOPE` 기본 `slot`). 문단 전체에 걸면 라벨까지
  커지고, 한 문단에 슬롯이 둘이면 뒤엣것이 앞엣것을 덮는다.
- **본문 블록은 템플릿 문단을 통째로 `deepcopy` 한다.** 명세를 파싱해 조립하면 charPr 만
  재현되고 **paraPr(여백·줄간격·정렬)은 재현되지 않는다.** 복제하면 둘 다 따라오고
  **새 서식 정의가 0개**라 `header.xml` 을 건드리지 않는다.
- 복제 시 **`hp:t` 만 남기는 화이트리스트**로 secPr·ctrl·tbl·그림을 버린다.

### 1-5. 응답 헤더로 알리는 것 (침묵 처리 금지)

`X-Missing-Fields` · `X-Written-Fields` · `X-Styled-Fields` · `X-Body-Blocks` ·
`X-Overflow-Fields` · `X-Open-Safety-Checked` · `X-Document-Format`

`X-Open-Safety-Checked` 의 `0` 은 **통과가 아니라 미판정**이다. 검사 없이 나간 파일을
검사 통과처럼 보이게 하지 않는다.

### 1-6. 상태·캐시

- **세션은 Redis** (`session_store.py`). GenOS 는 이전 대화를 자동 주입하지 않는다.
  **저장은 덮어쓰기**라 값만 저장하면 블록이 지워진다 → 항상 함께 넘긴다.
- **템플릿 파싱은 `template_index.py` 캐시 경유** (등록 시 1회). 무효화는 값 대조로
  한다 — 내용 해시·`SCHEMA_VERSION`·`SLOT_FIELDS`. Redis 장애 시 직접 파싱으로 degrade.
- **슬롯 인식 규칙이나 `FieldSpec` 을 고치면 `SCHEMA_VERSION` 을 올린다.**

### 1-7. 산출 형식은 hwpx 하나다 (2026-08-14)

PDF 출력을 걷어냈다(요구 변경). `format` 은 계속 받지만 **hwpx 외의 값은 400** 이다 —
조용히 hwpx 를 내려주면 화면은 PDF 를 받았다고 믿는데 파일은 hwpx 인 상태가 되고, 그
어긋남은 아무 기록도 남기지 않는다. `GET /templates` 의 `formats` 도 환경과 무관하게
항상 `["hwpx"]` 다(예전에는 `genon.preprocessor` 유무로 갈렸다).
코드는 `archive/sfr006-pdf` 브랜치.

---

## 2. SFR-018 글다듬이

문서를 받아 문체·톤을 다듬고, **무엇이 어떻게 바뀌었는지**와 **구조가 훼손되지
않았는지**를 함께 낸다.

### 2-1. 한 기능이 네 곳에 나뉘어 있다

| 하는 일 | 위치 |
|---|---|
| 정책 확정 (문서유형 → 톤) | 스텝 `sfr018_polish_01_policy` → MCP `lang_policy` |
| LLM 다듬기 | 스텝 `sfr018_polish_02_polish` → 코드서빙 `POST /polish` |
| 구조 훼손 감지·변경 내역 | 스텝 2 → MCP `text_guard` |
| 지원 정책 목록 | 코드서빙 `GET /policies` (내장 + **관리자가 추가한 톤·문서유형**) |
| 관리자 정책 갱신 | 코드서빙 `POST /policies/reload` (2026-08-18) |
| txt 내려받기 | 코드서빙 `POST /download` (2026-08-12 신규) |

**톤·문서유형은 고객사 관리자가 추가할 수 있다** (2026-08-18). GenOS 프롬프트
라이브러리에 JSON 정책을 등록하고 프롬프트 ID 를 주입하면 **재배포 없이** 목록과
판정에 반영된다 (가이드 §10.5). 내장 톤 3종 위에 **병합**되고, 미설정·조회 실패는
내장값으로 떨어지되 `policy.source`/`reason` 으로 드러난다. 등록 절차는
`docs/SERVING_REGISTRY.md` §2-2, 근거는 루트 `CLAUDE.md`.

**글다듬이는 문서(hwpx/pdf)를 출력하지 않는다** — 채팅 응답 + **txt 파일**로 끝난다.
`POST /download` 는 상태 없이 본문(`text` 또는 `polished_text`)을 받아 UTF-8 BOM + CRLF 로
낸다. 되돌려 보낼 값은 `polished_text` 다 — 화면 표시용 `text` 에는 경고문과 변경내역이
붙어 있어 파일에 섞이면 사용자가 메모장에서 지워야 한다.

### 2-2. 정책

문서유형 8종 × 톤 3종. **문서유형이 톤을 강제하는 경우**가 있고, 그때는
`tone_overridden=true` 와 사용자 안내문을 함께 낸다 (사용자가 고른 톤이 조용히
무시되면 안 된다). 판정은 MCP `resolve_tone` 이 한다 — **판정하는 쪽이 원본을 갖는다.**

톤 프리셋 사본이 **4벌**이고 실제로 갈린 적이 있다(006 `friendly` 한 문장 누락).
`onprem/test/check_tone_policy.py` 가 대조한다.

### 2-3. 구조 보존 — 감지 방식이다

번역과 달리 **문서를 통째로 LLM 에 보낸다** (문장 문맥이 필요하다). 대신 다듬기
전/후의 **구조 지문**을 대조한다:

| 도구 | 보는 것 |
|---|---|
| `markdown_structure_issues` | 표 행·열 수, 제목 단계, 코드펜스 |
| `fact_issues` | 숫자·날짜가 사라지거나 바뀌었는지 (다중집합 대조, 날짜는 표기 달라도 같은 날이면 같다) |
| `diff_changes` | 문장 단위 변경 내역 — **LLM 에 되묻지 않고 difflib 으로** |

되돌리지 않고 **경고만 낸다.**

### 2-4. 스트리밍

실시간 토큰 스트리밍이 아니다. LLM 응답을 **다 받은 뒤 32자씩 잘라** emit 한다.
그래서 LLM 호출을 코드서빙으로 내려도 UI 동작이 같다.
`sio_server.emit` 뒤에 **`await asyncio.sleep(0)`** 이 필수다.

---

## 3. SFR-018 번역

### 3-1. 지원 범위 — 거부도 기능이다

**6개 언어**(한국어·영어·중국어·태국어·베트남어·러시아어)이고 **원본이나 대상 중
하나는 반드시 한국어**여야 한다. `en→ru` 는 400 이다.

방향 검증은 **거부 판정**이라 LLM 에 맡기지 않는다 — MCP `lang_policy` 가 문자 체계로
결정적으로 감지한다. **감지 불가(숫자·기호뿐)는 거부하지 않고** 방향 검증만 건너뛴다.

### 3-2. 구조 보존 — 스켈레톤 분리다

분해 시점에 표 파이프·HTML 태그·제목·목록·코드펜스를 **코드가 스켈레톤으로 분리**하고
LLM 에는 셀/문장 텍스트만 보낸다. 재조립 결과의 구조는 **LLM 출력과 무관하게** 원본과
동일하다.

계약 둘 (`SFR-018/tests/test_markdown_units.py` 가 지킨다):

1. **무손실** — 항등 번역이면 산출물이 입력과 **문자 단위로** 같다.
2. **구조 불변** — 번역 후에도 줄마다 파이프 수·마커가 원본과 같다.

부수 규칙:

- **표 셀 파이프 이스케이프** — 번역문에 `|` 가 섞이면 그 행부터 열이 밀린다.
  분해 때는 파이프가 곧 셀 경계라 보장이 있었지만 번역문에는 없다.
- **번역문 줄바꿈 정규화** — 줄바꿈 하나가 들어가면 표 행이 갈라진다.
- **같은 원문은 한 번만 호출한다.** 호출 수도 줄고, 반복 머리글이 자리마다 다르게
  번역되는 흔들림도 사라진다.
- **번역할 텍스트가 없는 문서(숫자 표)는 LLM 을 아예 부르지 않는다.**

### 3-3. 엔드포인트

| 경로 | 하는 일 |
|---|---|
| `GET /languages` | 지원 언어·문체 목록 (UI 선택지) |
| `GET /glossary` · `POST /glossary/reload` | 용어사전 상태 / **관리자** 재적재 |
| `POST /translate` | 노드 목록 번역 |
| `POST /translate/markdown` | 전처리기 마크다운/HTML 번역 |
| `POST /translate/hwpx` | **hwpx 직접 파싱** 후 번역 (전처리기를 거치지 않는다) |
| `POST /download` | 번역문을 **txt 파일**로 (상태 없음 — 본문을 요청으로 받는다) |

hwpx 를 직접 파는 이유는 전처리기를 태우면 **표 안 수치가 깨지기** 때문이다.
산출 마크다운은 `/translate/markdown` 과 **같은** 스켈레톤 분해를 탄다.

**문서 출력(hwpx/pdf)은 하지 않는다.** 원본을 `source_markdown` 으로 함께 낸다.
나가는 파일은 **txt 하나**이고(2026-08-12), 본문은 받은 그대로 담는다 — 표를 평문으로
풀면 "구조는 입력과 동일" 계약을 마지막 단계에서 우리가 깨는 셈이다.

### 3-4. 용어사전 — 1단계만 있다

완전 일치 + 영어 활용형 정규화(`glossary_exact.py`)만 병합돼 있다. 2단계(Weaviate +
임베딩)는 폐쇄망 벡터DB 가용성 미확인으로 보류다.

**2단계 폴백이 없다는 것이 중요하다.** 사전이 없거나 상한을 넘으면 그 언어는 용어사전
없이 번역되고, 그 사실을 응답 `glossary.source` 로 노출한다. MCP `glossary_lookup` 도
그 상태를 `enabled=false` + `reason` 으로 낸다 (2026-08-11 수정 — 그전에는 상한 초과만
`false` 여서 **사전 미적재가 `enabled=true` 로 빠져나갔다**).

**준수율을 코드가 다시 센다** — 프롬프트 지시로 끝내지 않는다.
`glossary_report.build_report` 가 번역 후 대조해 `compliance` 와 하이라이트 데이터를 낸다.

알려진 한계: 태국어·중국어는 띄어쓰기가 없어 토큰이 길게 잡히므로 **사실상 완전 일치만**
걸린다.

### 3-5. 숫자 보존

`numeric_guard` — 자릿수 구분 기호를 제거하고 비교하므로 `1,000` ↔ `1.000` 은 오탐이
아니다. 기본 `warn`, `revert` 도 있다 (`TRANSLATE_NUMERIC_GUARD`).

---

## 4. SFR-018 FAQ

문서에서 FAQ 를 뽑고, **근거가 실제로 문서에 있는지 검증**한 뒤 파일로 내려준다.

### 4-1. 근거 검증이 이 기능의 핵심 계약이다

LLM 이 준 `evidence` 가 실제로 문서에 있는지 `evidence.py` 가 결정적으로 대조하고,
통과 못하면 **기각한다.** 완전 포함이면 1.0, 아니면 3-gram 겹침 비율로 판정한다
(`FAQ_EVIDENCE_MIN_RATIO`).

검증 없이 표시만 하면 근거란이 장식이 되고, **지어낸 답변에 그럴듯한 출처가 붙어
더 위험하다.**

**기각 건수를 전부 노출한다** (schema / ungrounded / duplicate). 조용히 버리면 5개
요청에 3개만 나온 이유를 알 수 없다.

### 4-2. 개수 상한은 두 층이다

배포 상한(`FAQ_MAX_COUNT`) **안에서만** 캔버스 변수(`faq_max_count`)로 낮출 수 있다.
캔버스가 상한을 넘길 수 있으면 LLM 예산 상한이 설정 하나로 무력해진다.

### 4-3. 엔드포인트

| 경로 | 하는 일 |
|---|---|
| `GET /config` | 상한·기본 개수·내려받을 수 있는 형식 (**항상 `["txt"]`**) |
| `POST /generate` | 마크다운 본문으로 생성 |
| `POST /generate/upload` | **hwpx 업로드 직접 파싱** 후 생성 |
| `GET /faqs` | 세션에 저장된 FAQ 조회 |
| `POST /download` | **txt** (`format` 생략 가능. 옛 이름 hwpx/pdf/xlsx 는 400) |

### 4-4. 내려받기 — txt 하나다 (2026-08-12)

hwpx·pdf·xlsx 를 걷어냈다. 사용자가 결과를 메모장에서 이어 편집하기 때문이다.
코드는 `archive/sfr018-doc-export` 브랜치에 있다.

- **저장된 것을 내려준다. 다시 생성하지 않는다** — LLM 을 다시 부르면 화면에서 본
  FAQ 와 파일이 달라진다. **다운로드가 세션을 지우지 않는다**(같은 FAQ 를 다시 받는
  흐름이 정상이라 006 과 다르다).
- **화면은 마크다운, 파일은 평문.** `**Q1.**`·`> 근거:` 는 우리가 붙인 장식이라 메모장에서
  기호가 글자로 보인다. 파일에서는 `Q1.` / `[근거]` + 구분선으로 낸다. 두 형태는
  `formatting.py` 의 나란한 두 함수가 만들고 **항목 목록을 공유**한다.
- **UTF-8 BOM + CRLF.** 옛 메모장이 BOM 없는 UTF-8 을 cp949 로 읽고, LF 만 있는 파일을
  한 줄로 붙여 보여준다. 환경변수 스위치를 두지 않는다.
- **형식 가용성 판별이 없어졌다.** txt 는 볼륨·외부 변환기·시스템 라이브러리를 요구하지
  않으므로 "이 환경에서는 못 만든다"(501)가 성립하지 않는다.
- 세 018 단위의 txt 응답 바이트는 `check_unit_endpoints.py` 가 대조한다 — `txt_output.py`
  가 단위마다 사본이라(단위 간 import 금지) 갈릴 수 있고, 갈리면 "그 기능에서 받은
  파일만 메모장에서 깨진다" 가 된다.

---

## 5. MCP 도구 파일 4개 (area 01)

**LLM 을 부르지 않는 결정적 도구**다. 같은 입력에 항상 같은 결과가 나온다.
설계 규율(접두어·shim·`-> str`·빈 문자열 주입)은 `../mcp/README.md` 에 있다.

| 파일 | 도구 | 하는 일 |
|---|---|---|
| `genon_lang_policy.py` | `detect_language` | 문자 체계로 언어 감지. **감지 불가는 빈 문자열이지 오류가 아니다** |
| | `validate_direction` | 번역 방향 검증. **거부는 오류가 아니라 `allowed=false` 판정** |
| | `list_languages`·`list_registers`·`resolve_register` | 지원 목록·문체 정규화 (`fell_back` 으로 기본값 대체를 알린다) |
| | `resolve_tone` | 문서유형 → 톤 확정 (강제 시 `tone_overridden`+안내문) |
| `genon_text_guard.py` | `markdown_structure_issues` | 표 행·열, 제목 단계, 코드펜스 훼손 |
| | `fact_issues` | 숫자·날짜 소실/변조 (날짜는 표기가 달라도 같은 날이면 같다) |
| | `numeric_issues` | 번역문 숫자 보존 (자릿수 기호 차이는 오탐 아님) |
| | `diff_changes` | 문장 단위 변경 내역 (difflib) |
| `genon_hwpx_text.py` | `hwpx_to_markdown` | hwpx 직접 파싱. **병합·중첩 표는 HTML(`rowspan`/`colspan` 보존), 단순한 표는 마크다운** — 마크다운에는 병합 문법이 없어 빈 칸이 되고 수치가 무엇의 값인지 사라진다 |
| `genon_glossary.py` | `glossary_lookup` | 문장에 걸린 사내 용어 → `{원문: 번역}` |
| | `glossary_status` | 적재 상태 (미적재를 숨기지 않는다) |
| | `glossary_reload` | 볼륨 파일 재적재 (**경로는 인자로 못 받는다** — 임의 경로 읽기가 된다) |

### 호출 형식

워크플로우 스텝이 게이트웨이를 통해 부른다:

```
{GENOS_URL}/api/gateway/mcp/{serving_id}/mcp     JSON-RPC  {"method": "tools/call"}
```

도구는 **JSON 문자열**을 돌려주고, 런타임이 `{"content": [{"type": "text", "text": …}]}`
로 감싼다. 스텝의 `_mcp_call` 이 그 `text` 를 JSON 으로 되돌린다.

**게이트웨이가 JSON-RPC 를 그대로 통과시키는지는 아직 실물 확인 대상이다.**

### 준수율은 MCP 에 없다 — 의도한 것이다

준수율 계산은 번역 파이프라인의 `TranslationUnit` 객체를 받아 JSON 으로 넘길 수 없고,
MCP 용으로 다시 구현하면 **같은 준수율 규칙이 두 벌**이 된다. 번역 코드서빙 응답
(`glossary.compliance`)에 그대로 둔다.

---

## 6. 워크플로우 스텝 9개 (area 02)

파일 1개 = 스텝 1개. **자기완결이어야 한다** — 공용 모듈로 빼면 캔버스에 못 붙인다.
그래서 로깅·오류표·게이트웨이 클라이언트 중복은 **의도한 것**이고,
`check_deploy_contract.check_workflow_steps()` 가 이를 강제한다.

| 스텝 | 종류 | 부르는 코드서빙 | 부르는 MCP | 캔버스 변수 |
|---|---|---|---|---|
| `sfr006_01_context` | 중간 | `TEMPLATE_FILL_SERVING_ID` `/chat/context` | — | `template_fill_template_id` |
| `sfr006_02_extract` | 중간 | `/chat/extract` | — | — |
| `sfr006_03_commit` | **마지막** | `/chat/commit` | — | — |
| `sfr018_polish_01_policy` | 중간 | — | `LANG_POLICY_MCP_ID` `resolve_tone` | `polish_doc_type`, `polish_tone` |
| `sfr018_polish_02_polish` | **마지막** | `TEXT_POLISH_SERVING_ID` `/polish` | `TEXT_GUARD_MCP_ID` ×3 | — |
| `sfr018_translate_01_detect` | 중간 | — | `HWPX_TEXT_MCP_ID` `hwpx_to_markdown` + `LANG_POLICY_MCP_ID` `validate_direction` | `translate_target_lang`, `translate_source_lang`, `translate_register`, **`translate_hwpx_path`** |
| `sfr018_translate_02_translate` | **마지막** | `TRANSLATION_SERVING_ID` `/translate/markdown` | `TEXT_GUARD_MCP_ID` `numeric_issues` | — |
| `sfr018_faq_01_source` | 중간 | `FAQ_SERVING_ID` `/config` | `HWPX_TEXT_MCP_ID` `hwpx_to_markdown` | `faq_count`, `faq_max_count`, `faq_title`, `faq_hwpx_path` |
| `sfr018_faq_02_generate` | **마지막** | `/generate` | — | — |

### 반환 계약 (`check_workflow_run.py` 가 실행해서 확인한다)

| | 중간 스텝 5개 | 마지막 스텝 4개 |
|---|---|---|
| 반환형 | `dict` | async generator |
| 이벤트 | — | `token` … 후 **`result` 정확히 1회** |

`result` 가 0회면 화면이 비고, 2회 이상이면 답변이 겹쳐 찍힌다.

공통:

- **오류는 예외가 아니라 `data["error"]`** 다. 예외를 던지면 워크플로우가 통째로 죽어
  사용자에게 안내문이 못 간다. 앞 스텝이 실패했으면 아무것도 하지 않고 통과시킨다.
- 오류 객체는 `{error_code, retryable, msg}` 이고 **`error_type` 은 싣지 않는다** —
  내부 분류값이라 로그에만 남긴다.
- 영역코드는 **`02-`** 다. 코드서빙(`03-`)의 코드를 그대로 올리지 않는다.
- **`{**data, ...}` 로 돌려준다.** `data` 를 통째로 갈면 `genos_state`(trace_id)를 잃는다.

---

## 7. 공통 규약

### 7-1. 오류

| 영역 | 방식 |
|---|---|
| 워크플로우(02) | `data["error"]` 객체 반환 |
| 코드서빙(03) | `{error_code, msg}` JSON. 006 은 `ApiError` 예외 하나로 올려 핸들러가 변환 |
| MCP(01) | `{"content": [...], "isError": true}` |
| eval | **로그 남긴 뒤 예외** (`error_codes.fail()`), 로그는 stderr 전용 |

사용자 노출 문구는 **각 파일에서 쓴 고정 한국어 안내문만** 담는다. 예외 원문은
`error_type`(클래스 이름)으로 로그에만 남긴다.

### 7-2. LLM 호출

- 결과는 **`LlmResult`(content, error_type, is_transport_error) 값 객체**로 반환한다.
  전역 오류 상태는 asyncio 레이스를 만든다.
- 응답은 화이트리스트/스키마 검증 후 정상 항목만 채택하고 **기각 건수를 노출한다.**
- **URL 은 `llm.py` 의 `_base_url()` 한 곳에서만 만든다.** `/api/gateway` prefix 를 코드가
  붙이고, `GENOS_URL` 이 이미 그걸로 끝나면 중복시키지 않는다.

### 7-3. 프롬프트

배포 단위 **밖** jinja 파일이다: `onprem/prompt/<배포 단위 이름>/*.j2`.
`StrictUndefined` 로 렌더하고, 템플릿이 없으면 **빈 프롬프트로 넘어가지 않고 요청을
세운다** — 지시문 없는 프롬프트의 결과가 정상 응답처럼 내려가기 때문이다.
렌더 실패는 LLM 실패와 **따로** 로그를 남긴다(`event=prompt_render_failed`).

지시문 언어는 나눠 쓴다: **구조·형식·금지 조항은 영어**, **산출물의 언어·어투·표기
규칙은 한국어**. 번역 단위만 전부 영어다(대상 언어가 요청마다 바뀌어 지시문 언어가
섞이면 모델이 출력 언어를 헷갈린다).

프롬프트 디렉토리는 **상위로 훑어 찾는다**(`_search_upward`). 고정 깊이로 찾다가
단위가 한 겹 내려가자 **네 단위의 프롬프트가 동시에 사라진** 적이 있다.

### 7-4. 의도된 중복 — 건드리지 말 것

배포 단위 간 import 가 금지돼 있어 **강제된 사본**이 있다. 갈렸는지는 점검이 본다.

| 사본 | 벌 수 | 지키는 점검 |
|---|---|---|
| 표 격자 규칙 (`cellAddr` 좌표·병합 앵커) | 4 | `check_table_grid.py` |
| 톤 프리셋 문구 | 4 | `check_tone_policy.py` |
| 워크플로우 스텝의 로깅·오류표·게이트웨이 클라이언트 | 9 | `check_deploy_contract.check_workflow_steps()` |

**저장소를 하나로 두는 근거가 이것이다** — 갈렸는지는 한 커밋 안에서 동시에 읽어야
확인된다.

### 7-5. 전처리기 입력

docx/pdf/hwpx 는 전처리기가 변환해 들어오며 **표 형식이 유형별로 다르다**:

- 첨부용: 마크다운 표 + `<!-- PB -->` 페이지 마커
- 지능형: 마크다운 표 **또는 한 줄 HTML 표**(`<table><tbody>…`, 셀 html.escape,
  colspan, 같은 줄 제목 접두 가능) + `[표 설명]` 요약

**프롬프트 지시("표를 유지하라")만으로 구조 보존을 처리하지 않는다.**

---

## 8. 검증 — 무엇이 어디까지 확인됐나

```bash
export PYTHONIOENCODING=utf-8   # Windows 콘솔 필수 (cp949 가 '—' 에서 죽는다)

# 함수 단위 회귀 테스트 (onprem 을 직접 태운다)
cd SFR-006 && python -m unittest discover -s tests -t .   #  32건
cd SFR-018 && python -m unittest discover -s tests -t .   # 172건

# 배포 계약·기능·실행 점검
python onprem/test/check_deploy_contract.py   # FAIL 0 / WARN 3 / OK 63
python onprem/test/check_api_contract.py      # 45   006 엔드포인트
python onprem/test/check_unit_endpoints.py    # 66   018 세 단위 엔드포인트
python onprem/test/check_chat_turn.py         # 22   대화 한 턴 (02↔03)
python onprem/test/check_service_boot.py      # 16   코드서빙 4단위 기동
python onprem/test/check_workflow_run.py      # 74   워크플로우 스텝 9개 실행
python onprem/test/check_mcp_tools.py         # 68   MCP 도구 파일 4개 (공존·판정·빈값 주입·스키마 enum)
python onprem/test/check_body_blocks.py       # 17   문단 복제 안전장치
python onprem/test/check_tone_policy.py       # 22   톤 사본 3벌 + 관리자 정책 파서 2벌
python onprem/test/check_output_safety.py     #  5   파트 선언·누름틀 안내문
python onprem/test/check_table_grid.py        # 18   표 격자 4벌 (단순표 + 병합표 2층)
```

**개봉 게이트·넘침 측정·벤더 절연 점검은 2026-08-12 에 뺐다** — 실제 배포 템플릿 3개가
표 없는 소규모라 판정할 게 없었다. 근거는 `docs/hwpx_library_adoption.md` 상단 공지,
코드는 `archive/hwpx-genon-vendor` 브랜치.

**위 건수는 2026-08-18 에 전부 다시 돌려서 얻은 값이다** (unittest 204건 + 점검 416건,
전부 종료 코드 0). 그전까지 이 블록은 2026-08-11 수치(unittest 50건 + 점검 295건)를
들고 있었다 — **이 숫자가 곧 회귀 감지 기준**이라 낡으면 판정이 사라져도 알 수 없다.
정본은 `test/README.md` 표와 `HANDOFF.md` §3-1 이고, 점검을 고칠 때 세 곳을 같이 고친다.
`check_unit_endpoints` 는 `SSL_CERT_FILE` 이 없는 경로를 가리키면 2건 실패한다(코드
결함이 아니다 — 그 변수를 비우고 다시 돌린다).

### 아직 확인되지 않은 것 — 실물이 있어야 한다

이 문서가 "구현돼 있다" 고 적은 것 중 **LLM·게이트웨이·한/글을 지나야 확인되는 것**은
아직 실물로 본 적이 없다. 상세는 `HANDOFF.md` §4-A.

| 미확인 | 왜 |
|---|---|
| LLM 실호출 경로 전체 | 게이트웨이가 없다. 프롬프트 한/영 분리의 실제 효과도 여기서 처음 드러난다 |
| 게이트웨이가 JSON-RPC 를 그대로 통과시키는지 | 안 되면 스텝 9개의 `_mcp_call` 을 각각 고쳐야 한다(자기완결 규율상 공용 모듈로 못 뺀다) |
| **MCP 파일 등록이 실제로 되는지** | 파일 4개를 올려 도구 14개가 다 뜨는지. 우리 쪽 규약(`@mcp.tool()`·JSON 문자열·`mcp` 주입)은 운영 참고 코드에 맞췄지만 등록 화면을 본 적은 없다 |
| 생성한 hwpx 를 **한/글에서 열어보기** | 확인할 한/글이 없다. `reopen_checked=False` 로 **하지 않았다고 말한다** |
| FAQ hwpx 템플릿 실물 | 반복 블록 규약에 맞는 사내 서식 파일이 없다 |
| 실제 사내 용어사전 파일 | `_MAX_TERM_WORDS=6`·캐시 상한 30만 건이 실물에 맞는지 미검증 |
| 빌드·시작 커맨드가 셸을 거치는지 | `cd A && B` 가 안 먹으면 `uvicorn --app-dir` 로 바꾼다 |
| 워크플로우 스텝 간 `data` 크기 한도 | 걸리면 본문 대신 **핸들(세션 키)** 만 넘기는 형태로 바꿔야 한다 |
| 번역 02 스텝 2개 | 코드는 있고 실행도 되지만 **캔버스에 등록된 적이 없다** |
