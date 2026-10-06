# 기능 명세 — 지금 무엇이 구현돼 있고, 무엇이 계약인가

> **엔드포인트별 요청·응답 필드의 정본은 [`API.md`](API.md)** 다(코드 기준). 이 문서는
> 기능 단위로 무엇이 있고 무엇을 보장하는지를 말한다. 어긋나면 코드가 이긴다.
>
> 계약 문장·판정 규칙·수치 기준은 기계로 대조되지 않는다. 각 절이 가리키는 정본:
> `txt_output.py` 머리말(md 규약) · [`DESIGN_NOTES.md`](DESIGN_NOTES.md)(설계 결정) ·
> `../README.md`(프론트 하이라이트 계약) · `../preprocessor/README.md`.

## 이 문서의 자리

| 문서 | 답하는 질문 |
|---|---|
| **이 문서** | **무엇이 구현돼 있나. 어느 경로로 부르나. 무엇을 보장하나** |
| `README.md` | 어떻게 배포하나 (환경변수·로깅 규약·이관 순서) |
| `ONPREM.md` | **이관 문서 하나** — 등록 10번·핵심 파일·환경변수·검증 상태·남은 미검증 |
| `SFR-006_architecture.md` | 006 내부 설계 심화 |
| `DESIGN_NOTES.md` | 설계 결정과 그 이유 |

기능이 늘거나 계약이 바뀌면 여기를 고친다. **"왜 그렇게 했나" 는 여기 적지 않는다** —
그건 `DESIGN_NOTES.md` 와 각 모듈 docstring 의 몫이고, 두 벌로 적으면 갈린다.

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
| 쓰는 외부 패키지 | **`httpx` 뿐** | fastapi·httpx·lxml·redis | **stdlib 만** |
| 진입점 | `run(data)` | FastAPI 앱 + `$PORT` | `@mcp.tool()` — 앱도 포트도 없다 |
| LLM | 부르지 않는다 | 부른다 | **부르지 않는다** |

**등록은 10번**(코드서빙 4 + MCP 4 + **전처리기 2**), **저장소는 1개**다.
근거는 `../ONPREM.md` §5, 칸마다 적을 값은 `SERVING_REGISTRY.md`.

**area 05 전처리기는 이 표에 없다** — hwpx 를 RAG 로 적재하는 경로라 위 네 기능 어디에도
배선돼 있지 않고 워크플로우가 부르지도 않는다. 등록 형태는 MCP 와 같은 파일 단위이고,
명세는 `../preprocessor/README.md` 가 정본이다.

**MCP 는 서빙이 아니라 파일이다.** GenOS 는 소스 파일 한 개를 받아 실행하고 `mcp` 객체를
런타임이 전역으로 주입한다. FastAPI 앱·`/health`·`$PORT`·`requirements.txt` 가 전부 없다.
상세는 `../mcp/README.md`.

### 기능 × 영역

| 기능 | 워크플로우 스텝 | 코드서빙 | MCP |
|---|---|---|---|
| SFR-006 템플릿 채우기 | 3 | `SFR-006_template_fill` | — |
| SFR-018 글다듬이 | 2 | `SFR-018_text_polish` | `lang_policy`, `text_guard` |
| SFR-018 번역 | 2 | `SFR-018_translation` | `lang_policy`, `text_guard`, `glossary` |
| SFR-018 FAQ | 2 | `SFR-018_faq` | **없다** (첨부는 전처리기가 읽는다) |

---

## 1. SFR-006 — HWPX 템플릿 채우기

hwpx 템플릿의 **채울 자리**를 찾아 대화로 값을 모으고, 다운로드 버튼을 누르면
초안 **hwpx** 를 만들어 준다 (산출 형식은 hwpx 하나다 — 1-7).

### 1-1. 채울 자리를 어떻게 아는가 — 인식 방식 3종

우선순위대로 **슬롯 → 누름틀 → `{{token}}`** 이다.

| 방식 | 생김새 | 상태 |
|---|---|---|
| **슬롯** | `제 목 : {'제목', 16pt, 맑은 고딕, 볼드}` | **기본**. 현장 템플릿이 이 모양이다 |
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

끄는 스위치: `TEMPLATE_FILL_SLOT_FIELDS=0` (별칭 `TEMPLATE_FILL_LABEL_FIELDS` 도 같은 스위치로 읽는다).

### 1-2. 코드서빙 엔드포인트

| 경로 | 하는 일 |
|---|---|
| `GET /health`, `GET /`, `GET ""` | 헬스체크·루트 |
| `GET /prompts` · `POST /prompts/reload` | 프롬프트를 라이브러리·파일 중 어디서 받았는지 / 캐시 비우기 (**관리자**) |
| `GET /templates` | 등록된 템플릿 목록 (+ 색인 상태) |
| `POST /templates` | **관리자** 등록 (업로드 + 즉시 색인). **파싱을 먼저, 파일 쓰기를 나중에** |
| `DELETE /templates/{id}` | **관리자** 삭제 (+ 색인 폐기) |
| `GET /fields` | 항목 스키마 + 본문 블록 서식 목록 |
| `GET /status` | 세션 채움 현황 (다운로드 버튼 활성화 판단용) |
| `GET /preview` | 채운 결과를 마크다운으로 (표시 전용) |
| `PATCH /values` · `DELETE /values` | 화면에서 고친 항목 값 반영·비우기 |
| `PUT /blocks` | 본문 추가 내용 **배열 통째 교체** |
| `POST /generate` | 등록 템플릿으로 초안 생성 + 다운로드 (**hwpx 만**) |
| `POST /generate/upload` | **업로드한 hwpx** 로 즉석 생성 (multipart) |
| `POST /chat/context` · `/chat/extract` · `/chat/commit` | 대화 3단계 — 워크플로우 스텝이 부른다 |
| `POST /chat/prefill` · `/chat/prefill/stream` | 업로드 문서로 빈 항목 자동 채움. 스트림은 **항목이 닫히는 대로** `✔ 항목: 값` 을 SSE 로 흘린다(스텝 3 이 부른다). `overwrite` 면 **찬 항목도** 문서 값으로 바꾼다 — 사용자가 "문서 내용으로 바꿔줘" 라고 명시한 턴(`/chat/extract` 의 `use_document`)에만 |

`PUT /blocks` 가 배열 통째 교체인 이유: 인덱스가 어긋나 **엉뚱한 문단을 지우는** 것을
막기 위해서다.

### 1-3. 워크플로우 스텝 3개

| 스텝 | 부르는 곳 | 캔버스 변수 | 내는 것 |
|---|---|---|---|
| `sfr006_01_context` | `POST /chat/context` | `template_fill_template_id` | `field_names`·`field_values`·`fields_missing`·**`ready_for_download`**·`template_markdown` |
| `sfr006_02_extract` | `POST /chat/extract` | — | 채택/기각 항목 |
| `sfr006_03_commit` | `POST /chat/prefill/stream`(문서가 있을 때) · `POST /chat/commit` | — | 답변 스트리밍(`token`) 후 `result` **1회** |

`ready_for_download` 가 **캔버스 분기의 근거**다 — "다 채웠으면 다운로드 안내 노드로,
아니면 추출 스텝으로" 를 스텝 1 뒤에 건다.

**사용자가 톤을 고르지 않는다** — 배포 템플릿은 관리자가 정한 고정 톤으로 채우면 되는
성격이라 톤 관련 캔버스 변수가 없다. 대신 `/chat/commit` 이 **본문 블록만** 글다듬이
서빙(`/polish`)에 보내 템플릿별 톤(`TEMPLATE_FILL_POLISH_MAP`, 기본 `objective`)으로
다듬는다(`polish_client.py`). 항목 값은 다듬지 않고, 실패하면 원문을 넣으며(fail-open),
숫자·날짜가 바뀐 블록은 원문으로 되돌린다(`value_guard.fact_diff`). 끄는 스위치는
`TEMPLATE_FILL_POLISH_BLOCKS=0`.

### 1-4. 문서 조립 — 순서가 계약이다

```
서식 적용  →  채우기  →  본문 블록
```

`document.build` **한 곳에만** 있다. 서식이 채우기보다 먼저인 이유: 채우면 `{…}` 가
사라져 어디에 무슨 서식을 걸지 알 수 없다.

- **서식은 LLM 없이 코드가 적용한다**: `charPr` 을 복제해 크기(1pt=100)·폰트·굵게만 바꾸고
  그 id 를 **슬롯 run** 에 건다 (`STYLE_SCOPE` 기본 `slot`). 문단 전체에 걸면 라벨까지
  커지고, 한 문단에 슬롯이 둘이면 뒤엣것이 앞엣것을 덮는다.
- **본문 블록은 템플릿 문단을 통째로 `deepcopy` 한다.** 명세를 파싱해 조립하면 charPr 만
  재현되고 **paraPr(여백·줄간격·정렬)은 재현되지 않는다.** 복제하면 둘 다 따라오고
  **새 서식 정의가 0개**라 `header.xml` 을 건드리지 않는다.
- 복제 시 **`hp:t` 만 남기는 화이트리스트**로 secPr·ctrl·tbl·그림을 버린다.

### 1-5. 응답 헤더로 알리는 것 (침묵 처리 금지)

`X-Missing-Fields` · `X-Written-Fields` · `X-Styled-Fields` · `X-Body-Blocks` ·
`X-Document-Format`

개봉 안전 검사·표 셀 넘침 측정은 하지 않는다 — 실제 배포 템플릿이 전부 표 없는
1~2쪽짜리라 두 검사가 아무 판정도 하지 않는다.

### 1-6. 상태·캐시

- **세션은 Redis** (`session_store.py`). GenOS 는 이전 대화를 자동 주입하지 않는다.
  **저장은 덮어쓰기**라 값만 저장하면 블록이 지워진다 → 항상 함께 넘긴다.
- **템플릿 파싱은 `template_index.py` 캐시 경유** (등록 시 1회). 무효화는 값 대조로
  한다 — 내용 해시·`SCHEMA_VERSION`·`SLOT_FIELDS`. Redis 장애 시 직접 파싱으로 degrade.
- **슬롯 인식 규칙이나 `FieldSpec` 을 고치면 `SCHEMA_VERSION` 을 올린다.**

### 1-7. 산출 형식은 hwpx 하나다

`format` 은 받지만 **hwpx 외의 값은 400** 이다 — 조용히 hwpx 를 내려주면 화면은 PDF 를
받았다고 믿는데 파일은 hwpx 인 상태가 되고, 그 어긋남은 아무 기록도 남기지 않는다.
`GET /templates` 의 `formats` 는 환경과 무관하게 항상 `["hwpx"]` 다.

---

## 2. SFR-018 글다듬이

문서를 받아 문체·톤을 다듬고, **무엇이 어떻게 바뀌었는지**와 **구조가 훼손되지
않았는지**를 함께 낸다.

### 2-1. 한 기능이 네 곳에 나뉘어 있다

| 하는 일 | 위치 |
|---|---|
| 정책 확정 (문서유형 → 톤) | 스텝 `sfr018_polish_01_policy` → MCP `lang_policy` |
| LLM 다듬기 | 스텝 `sfr018_polish_02_polish` → 코드서빙 `POST /polish/stream`(SSE). 흘리기 전에 실패하면 `POST /polish`(한 번에) |
| 구조 훼손 감지 | 스텝 2 → MCP `text_guard` (`markdown_structure_issues`·`fact_issues`) |
| 지원 정책 목록 | 코드서빙 `GET /policies` (**표가 유일한 출처다**) |
| 프롬프트 출처·캐시 | 코드서빙 `GET /prompts` · `POST /prompts/reload` · `POST /policies/reload`(캐시를 비우고 `GET /policies` 와 같은 응답) |
| md 내려받기 | 결과를 만들 때 코드서빙이 **MinIO 에 굳혀 올리고** `download_url` 을 낸다. `POST /download`(본문 왕복)는 폴백이다 |
| 헬스체크·루트 | `GET /health` · `GET /` · `GET ""` |

**관리자가 톤·문서유형을 추가하는 경로는 없다** — 코드서빙 안에서 JSON 정책을 해석하지
않는다. **목록·라벨·강제 톤의 출처는 표 하나**(`tone_presets.py` ↔ MCP `genon_lang_policy.py`)이고, 관리자가 바꿀
수 있는 것은 **톤별 지시문 문장**뿐이다(`POLISH_PROMPT_IDS` 의 `system_<tone>`·
`doc_type_<code>` 이름=ID 매칭). 톤을 늘리는 것은 개발자 일이고 두 표 + eval
`TONE_RULES` 를 함께 고친다. 근거는 `DESIGN_NOTES.md`.

**긴 문서는 조각으로 나눠 다듬는다.** 문서 전체를 한 번에 보내면 입력 상한(20만 자)에
닿기 한참 전에 `RES_TIMEOUT`(90초)이 먼저 난다. 조각 경계는 빈
줄이고 **코드펜스·여러 줄 HTML 표 안에서는 끊지 않는다.** 실패한 조각 자리에는
**원문이 그대로** 남고(전량 실패만 오류다), 응답의 `chunk_count`·`failed_chunk_count`
가 몇 조각이 돌았는지를 말한다. 환경변수는 `POLISH_MAX_CHUNK_CHARS`(기본 6000)·
`POLISH_LLM_CONCURRENCY`(기본 4).

**글다듬이는 문서(hwpx/pdf)를 출력하지 않는다** — 채팅 응답 + **마크다운(.md) 파일**로 끝난다.
파일은 **결과를 만들 때 서빙이 굳혀 MinIO 에 올리고**(`file_store.upload_bytes`)
payload 에는 `download_url` 만 싣는다 — 화면이 파일 본문을 들고 있을 이유가 없다.

**업로드 실패는 결과를 버리지 않는다**(fail-open). 그때 코드서빙 `/polish`·
`/polish/stream`(`done`) 의 `download_url` 은 **빈 문자열 `""`** 이고(FAQ·006 서빙은
`None`), 스텝 2 가 `""` 를 `None` 으로 바꿔 `result` 에 싣는다. **폐쇄망에서 CDN 업로드가
실제로 되는지는 미검증**이라 `POST /download` 라우트를 폴백으로 남겨 뒀다.

**변경 낱말 하이라이트는 내지 않는다.** 스텝 2 는 `diff_changes` 를 부르지 않는다 —
다듬기가 문장을 크게 다시 쓰는 일이 흔해 낱말 단위 diff 가 문서 전체를 뒤덮어 오히려
"무엇이 바뀌었나" 를 가린다. 원문과 다듬은 글을 `<mark>` 없이 좌우에 그대로 낸다.
도구 자체는 MCP `genon_text_guard` 에 남아 있다.

스텝 2 의 `result` 가 내는 값:

| 필드 | 쓰는 곳 |
|---|---|
| `original_text` | **좌측** — 원문 그대로 |
| `polished_text` | **우측** — 다듬은 글 그대로 (흘린 토큰을 이어붙인 것과 같다) |
| `download_url` | 미리 굳혀 올린 md 링크. 못 올렸으면 `None` |
| `notice` | **결과는 냈지만 알아야 하는 것.** 고정 한국어 문장 목록이고 **있을 때만** 실린다 |
| `error` | **오류일 때만** 실린다. 정상 응답에는 없다 |

**payload 는 사용자가 눈으로 보는 값만 담는다**. 프론트에 실어 보내면
화면이 그 값을 어떻게 쓸지 각자 정하게 되고, 쓰지 않는 값은 아무도 안 읽는 채로 계약에
남는다. 그래서 뺀 것: 정본(파일이 됐다) · `changes`(사본을 만드는 **입력**이다) ·
`structure_warnings`/`fact_warnings`/`tone_overridden`/`tone_notice`(**disclaimer 로
나간다** — 판정만 하고 문구를 조립하지 않으며, 전송은 MCP 확정 후) · `text`(본문은
`token` 이벤트로 흘리고 `result` 의 `polished_text` 가 최종값이다).

**사본 이름에 `_highlighted` 를 붙이지 않는다.** 정본은 파일이 돼 payload 에 없으므로
구분할 상대가 없고, 접미어를 붙이면 `original_text` 와 이름 짝이 어긋난다.

번역도 같은 모양이다 — `original_text` / `translated_text` / `download_url`.
(진단·지표 `glossary`·`translate_stats`·`translate_source_kind`·`numeric_warnings` 는
`event=translate_done` 로그가 전부 싣는다. FAQ 는 `faq_stats` 를 `event=faq_done` 이 갖는다.)

**한국어 조사를 정규화한다.** `가맹점을` 이 한 토큰이라 그대로는 사전과 매칭되지 않고,
그 실패가 방향마다 다르다 — **ko→en 은 용어가 프롬프트에 안 실리고**(준수율 1.0),
**en→ko 는 제대로 옮긴 번역이 준수율 0.0** 을 받는다. 조회 시점에 조사를 떼는 폴백
하나가 매칭·준수율·하이라이트에 함께 걸린다. 번역 쪽 하이라이트는 **변경이 아니라 용어사전 용어**이고, 양쪽이 같은
기준이다: **실제로 참고한 것만**, 그리고 **사전에 걸린 낱말만**. `I love ccrs` 에서
`ccrs` 만 사전에 있으면 `I love` 는 그대로 남는다. 요구사항 §2 가 요구하는 것이 "어떤
단어가 용어사전의 어떤 단어를 참고하였는지" 이므로 참고하지 않은 자리는 칠할 관계가
없다 — 미준수는 `glossary.term_map_unapplied` 와 준수율이 맡는 **검수용** 값이다.

### 2-2. 정책

**문서유형 5종 × 톤 4종.**

| | |
|---|---|
| 톤 4종 | `polite` 격식·정중 · `friendly` 친절·안내 · `clear` 명확·간결 · `objective` 사실·객관 |
| 자유 선택군 | 메일 · 게시글 · **고객발송문구** |
| 톤 고정군 | 채무 및 연체발생 사유 · 심사역 의견 — **사실·객관 고정** |

넷은 **전부 존댓말**이다 — "명확·간결" 은 문장을 줄이는 톤이지 종결어미(개조식
`~함/~임`)를 바꾸는 톤이 아니다. 캔버스가 보내는 별칭 `report` 는
`LEGACY_TONE_ALIASES`(`report` → `clear`)가 받는다. 없으면 그 선택이 **조용히 기본 톤으로**
바뀐다. 목록에 없는 문서유형은 기본 문서유형(메일)으로 떨어진다.

**문서유형이 톤을 강제하는 경우**가 있고, 그때는
`tone_overridden=true` 와 사용자 안내문을 함께 낸다 (사용자가 고른 톤이 조용히
무시되면 안 된다). 판정은 MCP `resolve_tone` 이 한다 — **판정하는 쪽이 원본을 갖는다.**

톤 프리셋 사본이 **3벌**(MCP 원본 · 글다듬이 · eval)이고, 한 사본에서 지시문 한 문장만
빠져도 오류 없이 문체만 달라진다. `Test/check/check_tone_policy.py` 가 대조한다.

### 2-3. 구조 보존 — 감지 방식이다

번역과 달리 **문서를 통째로 LLM 에 보낸다** (문장 문맥이 필요하다). 대신 다듬기
전/후의 **구조 지문**을 대조한다:

| 도구 | 보는 것 |
|---|---|
| `markdown_structure_issues` | 표 행·열 수, 제목 단계, 코드펜스 |
| `fact_issues` | 숫자·날짜가 사라지거나 바뀌었는지 (다중집합 대조, 날짜는 표기 달라도 같은 날이면 같다) |
| `diff_changes` | **낱말 단위** 변경 내역 + **양쪽 좌표**(`source_span`·`target_span`) + `<mark>` 표시용 사본 **둘** — **LLM 에 되묻지 않고 difflib 으로** |

되돌리지 않고 **경고만 낸다.**

### 2-4. 스트리밍

**LLM 증분을 그대로 흘린다.** 코드서빙 `POST /polish/stream` 이 다듬어지는 대로 SSE
`delta` 프레임을 내고, 스텝 2 가 그것을 캔버스 `token` 이벤트로 중계한다. 흘리는 것은
**정본**이라 이어붙이면 `result.polished_text` 와 같다(갈아 끼울 사본이 없다).

- **흘리기 전에 실패하면** 스텝이 `POST /polish` 로 한 번에 받아 잘라 흘린다. 조각은
  기본 32자(`_STREAM_CHUNK_CHARS`)이고 총 emit 수 상한(`_STREAM_MAX_EMITS` 400)에 맞춰
  긴 문서에서는 키운다.
- 게이트웨이가 스트리밍을 받지 않으면 서빙이 비스트리밍으로 다시 다듬어 한 덩어리로
  보내고 `done` 에 `stream_fallback=true` 를 싣는다. 흘린 뒤 끊긴 조각이 있으면
  `stream_diverged=true` 이고 스텝이 안내문(`notice`)을 단다.
- `sio_server.emit` 뒤에 **`await asyncio.sleep(0)`** 이 필수다.

---

## 3. SFR-018 번역

### 3-1. 지원 범위 — 거부도 기능이다

**6개 언어**(한국어·영어·중국어·태국어·베트남어·러시아어)이고 **원본이나 대상 중
하나는 반드시 한국어**여야 한다. `en→ru` 는 400 이다.

방향 검증은 **거부 판정**이라 LLM 에 맡기지 않는다 — MCP `lang_policy`(와 코드서빙
`languages.py` 사본)가 문자 체계로 결정적으로 감지한다. **감지 불가(숫자·기호뿐)이고
원문 언어도 선택하지 않았으면, 대상이 한국어일 때만 통과한다.** 대상이 한국어가 아니면
한국어 축을 증명할 수 없으므로 "원문 언어를 선택해 주세요. 문서에서 언어를 알아내지
못했고, 한국어가 아닌 언어로 번역하려면 원문이 한국어인지 확인되어야 합니다." 로 거부한다.

### 3-1-1. 유닛에 절 제목을 문맥으로 단다

LLM 에는 셀·문장 텍스트만 들어가므로(구조는 코드가 쥔다) 표 셀 하나짜리 유닛은 그것이
무엇에 관한 값인지 알 방법이 없다. 배치 항목에 `c`(그 유닛이 속한 절의 제목 원문)를
함께 싣는다 — **번역 대상이 아니고 출력 스키마는 `{id, t}` 그대로**이며, 문맥이 없는
유닛에는 키 자체를 넣지 않는다. 단건 폴백에도 같은 값이 실린다.

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
| `GET /health`, `GET /`, `GET ""` | 헬스체크·루트 |
| `GET /prompts` · `POST /prompts/reload` | 프롬프트 출처 / 캐시 비우기 (**관리자**) |
| `GET /languages` | 지원 언어·문체 목록 (UI 선택지) |
| `GET /glossary` · `POST /glossary/reload` | 용어사전 상태 / **관리자** 재적재 |
| `POST /translate` | 노드 목록 번역 |
| `POST /translate/markdown` | 전처리기 마크다운/HTML 번역 |
| `POST /translate/hwpx` | **hwpx 직접 파싱** 후 번역 (전처리기를 거치지 않는다) |
| `POST /translate/stream` | 번역문을 만들어지는 대로 SSE(`delta`·`done`·`error`)로 흘린다. 마크다운째 번역하고(스켈레톤 분해 없음) 구조 대조는 finalize 가 한다 |
| `POST /translate/finalize` | 스트리밍이 끝난 뒤 용어사전 하이라이트 사본·구조 대조·`download_url` 을 낸다. LLM 을 부르지 않는다 |
| `POST /download` | 번역문을 **마크다운(.md) 파일**로 (상태 없음 — 본문을 요청으로 받는다. `download_url` 폴백) |

hwpx 를 직접 파는 이유는 전처리기를 태우면 **표 안 수치가 깨지기** 때문이다.
산출 마크다운은 `/translate/markdown` 과 **같은** 스켈레톤 분해를 탄다.

**문서 출력(hwpx/pdf)은 하지 않는다.** 원본을 `source_markdown` 으로 함께 낸다.
나가는 파일은 **마크다운(.md) 하나**이고, 본문은 받은 그대로 담는다 — 표를 평문으로
풀면 "구조는 입력과 동일" 계약을 마지막 단계에서 우리가 깨는 셈이다.

### 3-4. 용어사전 — 1단계만 있다

완전 일치 + 영어 활용형 정규화(`glossary_exact.py`)만 병합돼 있다. 2단계(Weaviate +
임베딩)는 폐쇄망 벡터DB 가용성 미확인으로 보류다.

**2단계 폴백이 없다는 것이 중요하다.** 사전이 없거나 상한을 넘으면 그 언어는 용어사전
없이 번역되고, 그 사실을 응답 `glossary.source` 로 노출한다. MCP `glossary_lookup` 도
그 상태를 `enabled=false` + `reason` 으로 낸다 — 상한 초과뿐 아니라 **사전 미적재도
`false`** 다. 그렇지 않으면 미적재가 `enabled=true` 로 빠져나간다.

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

### 4-1-1. 문서 전체가 후보다

문서를 `FAQ_MAX_CONTEXT_CHARS`(기본 12,000) 크기의 조각으로 나눠 **조각마다 자기 몫**을
만든다. 앞에서 잘라 한 번만 보내면 잘린 뒷부분이 FAQ 후보에서 통째로 빠지고 **기각
건수에도 잡히지 않는다** — LLM 이 본 적이 없으니 `ungrounded` 도 `duplicate` 도 아니다.
실질 상한은 업로드 용량(`FAQ_MAX_UPLOAD_BYTES`)이다.

- **사용자는 총 개수만 고른다.** 고른 숫자가 곧 받는 개수이고 **어느 구간에서 몇 개씩
  뽑을지는 코드가 배분한다**(`chunking.plan_quota`). 상한은 `FAQ_MAX_COUNT`(기본 30)
  하나다. 선택을 구간당 개수로 읽으면 구간이 여섯일 때 5를 골라도 30개가 나온다.
- **호출 수는 `FAQ_MAX_CHUNK_CALLS`(기본 6)가 정한다 — 개수가 아니라 비용의 손잡이다.**
  조각이 40개여도 여섯 조각이 총 개수를 나눠 갖고, 태울 조각은 **고르게 표집한다**
  (앞에서부터 채우면 문서를 앞에서 자른 것과 결과가 같아진다). 이 상한이 조각당 몫이 0 이
  되는 것도 함께 막는다.
- **상한에 걸려 못 태운 구간은 `coverage_capped`** 로 낸다. `source_truncated` 와
  다른 사건이다 — 그쪽은 문서 뒤를 안 봤고, 이쪽은 전체를 나눴지만 일부만 태웠다.
  둘 다 안내문으로 나간다(조용히 넘기면 문서 전체에서 뽑은 결과로 읽힌다).
- **근거 대조·중복 판정은 문서 전체 기준**이다. 조각별로 하면 경계 문장이 오탐
  기각되고, 여러 절에 나오는 같은 질문이 전부 통과한다.
- `FAQ_MAX_CONTEXT_CHUNKS`(기본 80 ≈ 96만 자)에 **걸린 문서만** `source_truncated` 다.
- **조각들은 병렬로 부른다** (동시 수 `FAQ_LLM_CONCURRENCY` 기본 6). 조각 사이에 순서
  의존이 없으므로 순차로 돌면 **대기시간이 조각 수에 비례**한다 — 기본 상한(6조각)에서
  한 번 호출 시간의 여섯 배다. **채택만은 조각 순서대로** 한다: 중복 판정·기각 건수·
  조각별 채택 상한이 누적 상태라, 도착 순서대로 채택하면 같은 문서가 실행마다 다른
  분포를 낸다(오류로는 드러나지 않는다). 조각 크기 기본값(12,000)이 작은 것도 같은
  이유다 — 조각이 짧을수록 겹쳐 도는 효과가 크다.
- 응답에 `source_chunks`·`chunks_planned`·`chunks_used` 를 낸다. 뒤의 둘이 다르면
  조각 몇 개가 실패한 채로 결과가 나갔다는 뜻이고, 스텝이 그 차이로 안내문을 낸다.

### 4-2. 개수 상한은 두 층이다

배포 상한(`FAQ_MAX_COUNT`) **안에서만** 캔버스 변수(`faq_max_count`)로 낮출 수 있다.
캔버스가 상한을 넘길 수 있으면 LLM 예산 상한이 설정 하나로 무력해진다.

**개수 상한과 비용 상한은 다른 손잡이다.** 위 둘은 사용자가 받을 **총 개수**를 잡고,
LLM 호출 수는 `FAQ_MAX_CHUNK_CALLS` 가 잡는다. 하나로 묶으면 둘 중 하나를 못 지킨다 —
개수를 지키려다 사용자가 고른 숫자를 구간당으로 바꿔 읽게 된다.

### 4-3. 엔드포인트

| 경로 | 하는 일 |
|---|---|
| `GET /health`, `GET /`, `GET ""` | 헬스체크·루트 |
| `GET /prompts` · `POST /prompts/reload` | 프롬프트 출처 / 캐시 비우기 (**관리자**) |
| `GET /config` | 상한·기본 개수·내려받을 수 있는 형식 (**항상 `["md"]`**) |
| `POST /generate` | 마크다운 본문으로 생성 |
| `POST /generate/stream` | `/generate` 와 같은 생성을 **항목마다** SSE 로 흘린다(`item_open`·`delta`·`item_close`·`done`). 검증을 통과한 항목만 프레임이 되고 한 번에 한 항목만 열린다 |
| `POST /generate/upload` | **hwpx 업로드 직접 파싱** 후 생성 |
| `GET /faqs` | 세션에 저장된 FAQ 조회 |
| `POST /download` | **md** (`format` 생략 가능. 다른 이름 txt/hwpx/pdf/xlsx 는 400) |

### 4-4. 내려받기 — 마크다운(.md) 하나다

- **저장된 것을 내려준다. 다시 생성하지 않는다** — LLM 을 다시 부르면 화면에서 본
  FAQ 와 파일이 달라진다. **다운로드가 세션을 지우지 않는다**(같은 FAQ 를 다시 받는
  흐름이 정상이라 006 과 다르다).
- **파일은 화면과 같은 마크다운이다.** `**Q1.**`·`> 근거:` 형식을 `formatting._render`
  하나가 정하고, 파일은 그 앞에 `# 제목` 한 줄을 붙인다(`rows_to_markdown`).
- **UTF-8 BOM + CRLF.** 마크다운 뷰어가 없는 PC 에서 메모장으로 열어도 한글이 깨지거나
  한 줄로 붙지 않게 한다. 환경변수 스위치를 두지 않는다.
- **형식 가용성 판별이 없다.** md 는 볼륨·외부 변환기·시스템 라이브러리를 요구하지
  않으므로 "이 환경에서는 못 만든다"(501)가 성립하지 않는다.
- 세 018 단위의 md 응답 바이트는 `check_unit_endpoints.py` 가 대조한다 — `txt_output.py`
  가 단위마다 사본이라(단위 간 import 금지) 갈릴 수 있고, 갈리면 "그 기능에서 받은
  파일만 깨진다" 가 된다.

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
| | `diff_changes` | 낱말 단위 변경 내역 + `source`·`revised` 양쪽 좌표 + `<mark>` 사본 둘 (difflib) |
| `genon_glossary.py` | `glossary_lookup` | 문장에 걸린 사내 용어 → `{원문: 번역}` |
| | `glossary_status` | 적재 상태 (미적재를 숨기지 않는다) |
| | `glossary_reload` | 볼륨 파일 재적재 (**경로는 인자로 못 받는다** — 임의 경로 읽기가 된다) |
| `genon_pii_audit.py` | `pii_audit`·`pii_scan_text`·`pii_detectors` | 산출 텍스트의 미마스킹 개인정보 건수 집계. **기능이 부르지 않고 사람이 주기적으로 직접 부른다** |

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
| `sfr006_01_context` | 중간 | `TEMPLATE_FILL_SERVING_ID` `/chat/context` | — | `template_fill_template_id`, **`genosUploaded`** |
| `sfr006_02_extract` | 중간 | `/chat/extract` | — | — |
| `sfr006_03_commit` | **마지막** | `/chat/prefill/stream`(문서가 있을 때) + `/chat/commit` | — | — |
| `sfr018_polish_01_policy` | 중간 | — | `LANG_POLICY_MCP_ID` `resolve_tone` | `polish_doc_type`, `polish_tone`, **`genosUploaded`** |
| `sfr018_polish_02_polish` | **마지막** | `TEXT_POLISH_SERVING_ID` `/polish/stream` (폴백 `/polish`) | `TEXT_GUARD_MCP_ID` ×2 (`markdown_structure_issues`·`fact_issues`) | — |
| `sfr018_translate_01_detect` | 중간 | — | `LANG_POLICY_MCP_ID` `validate_direction` | `translate_target_lang`, `translate_source_lang`, `translate_register`, **`genosUploaded`** |
| `sfr018_translate_02_translate` | **마지막** | `TRANSLATION_SERVING_ID` `/translate/stream` + `/translate/finalize` (폴백 `/translate/markdown`) | `TEXT_GUARD_MCP_ID` `numeric_issues` | — |
| `sfr018_faq_01_source` | 중간 | `FAQ_SERVING_ID` `/config` | — | `faq_count`, `faq_max_count`, `faq_title`, **`genosUploaded`** |
| `sfr018_faq_02_generate` | **마지막** | `/generate/stream` (폴백 `/generate`) | — | — |

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

**프롬프트 라이브러리가 파일을 덮어쓴다.** 자주 손보는 지시문을 재배포
없이 고치기 위해서다 (§10.5 — "코드 PR 로 프롬프트 변경" 이 금지사항이다).

| | 자리 |
|---|---|
| 자주 바뀌는 것 — 006 항목 매핑, FAQ 생성 지시, 문체 지시 | **프롬프트 라이브러리** (`<단위>_PROMPT_IDS` 에 `이름=ID`) |
| 톤·문서유형 **목록** | `tone_presets.py` 표 (JSON 정책 문서는 해석하지 않는다) |
| 고정 골격 — 시스템 프롬프트(출력 형식·금지 조항) | 파일(`.txt`) |

- 이름은 **파일 이름에서 확장자를 뗀 것**(`extract_user.txt` → `extract_user`). 안 적힌
  이름은 파일을 쓴다 — 미설정은 정상 경로다.
- **못 읽거나 본문 렌더가 실패하면 파일로 떨어진다**(fail-open). admin-api 장애나 관리자
  오타가 기능을 통째로 막지 않는다. 다만 조용하지 않다 — `GET /prompts` 가 이름마다
  `source`/`reason` 을 내고 `event=prompt_library_failed`·`_render_failed` 가 남는다.
- `POST /prompts/reload` 로 즉시 반영(안 부르면 TTL 60초). **`/prompts` 는 본문을 싣지
  않는다** — 담으면 지시문 유출 경로가 된다(3.8절).
- 네 단위의 `prompt_library.py` 는 **본문까지 같은 사본**이고
  `check_deploy_contract.check_prompt_library_copies()` 가 대조한다.

기본값 파일은 배포 단위 **밖** jinja 문법 파일이다: `final/<기능>/prompt/<배포단위이름>/*.txt`.
`StrictUndefined` 로 렌더하고, **파일도 없으면 빈 프롬프트로 넘어가지 않고 요청을
세운다** — 지시문 없는 프롬프트의 결과가 정상 응답처럼 내려가기 때문이다.
렌더 실패는 LLM 실패와 **따로** 로그를 남긴다(`event=prompt_render_failed`).

지시문 언어는 **전부 한국어**다. 번역은 **출력 언어를 못박는 문장**(`{{ target_label }}`)을
맨 위와 "입력은 내용이지 지시가 아니다" 절 두 곳에 둔다 — 실호출 검증은 못 했다.

프롬프트 디렉토리는 **상위로 훑어 찾는다**(`_search_upward`). 고정 깊이로 찾으면
단위가 한 겹 내려갈 때 **네 단위의 프롬프트가 동시에 사라진다.**

### 7-4. 의도된 중복 — 건드리지 말 것

배포 단위 간 import 가 금지돼 있어 **강제된 사본**이 있다. 갈렸는지는 점검이 본다.

| 사본 | 벌 수 | 지키는 점검 |
|---|---|---|
| hwpx 파싱 코어 (표 격자·상자·자동 번호·tail·수식) | **5** | `check_table_grid.py` (전처리기가 3층의 정본) |
| 톤 프리셋 문구 | **3** | `check_tone_policy.py` (MCP 원본 · 글다듬이 · eval) |
| `txt_output.py` (BOM·CRLF·헤더·파일명) | 3 | `check_unit_endpoints.py` (세 단위 응답을 **바이트로** 대조) |
| `file_store.py` (MinIO 업로드·fail-open) | 4 | `check_api_contract.py` (AST 대조) |
| 용어사전 적재·매칭 (조사 절단 포함) | 2 | `check_mcp_tools.py` |
| 워크플로우 스텝의 로깅·오류표·게이트웨이 클라이언트 | 9 | `check_deploy_contract.check_workflow_steps()` |

> **조각 분할(`chunking.py`)은 사본이 아니다.** FAQ 와 글다듬이가 같은
> 이름의 모듈을 갖지만 **계약이 다르다** — FAQ 는 버리는 글자만 없으면 되고(조각을
> LLM 입력으로만 쓴다), 글다듬이는 **이어붙이면 원문과 문자 단위로 같아야** 한다
> (실패한 조각 자리에 원문을 되꽂는다). 맞추려고 어느 쪽을 따라가지 말 것.

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
python Test/run_all.py          # 점검 16개 + unittest 2벌. 요약·FAIL 만 출력
```

점검별 내용은 각 `Test/check/check_*.py` 머리말, 목록은 `../ONPREM.md` §8. **기준 건수의
정본은 `Test/run_all.py` 의 `EXPECTED` 다** — 건수가 줄면 FAIL 로 친다(실물 경로가
어긋나면 FAIL 없이 건수만 조용히 준다).

`check_unit_endpoints` 는 `SSL_CERT_FILE` 이 없는 경로를 가리키면 2건 실패한다(코드
결함이 아니다 — 그 변수를 비우고 다시 돌린다).

### 아직 확인되지 않은 것 — 실물이 있어야 한다

이 문서가 "구현돼 있다" 고 적은 것 중 **LLM·게이트웨이·한/글을 지나야 확인되는 것**은
아직 실물로 본 적이 없다. 상세는 `../ONPREM.md` §9.

| 미확인 | 왜 |
|---|---|
| LLM 실호출 경로 전체 | 게이트웨이가 없다. 한국어 지시문이 출력 언어를 지키는지도 여기서 처음 드러난다 |
| 게이트웨이가 JSON-RPC 를 그대로 통과시키는지 | 안 되면 스텝 9개의 `_mcp_call` 을 각각 고쳐야 한다(자기완결 규율상 공용 모듈로 못 뺀다) |
| **MCP 파일 등록이 실제로 되는지** | 파일 4개를 올려 도구 16개가 다 뜨는지. 우리 쪽 규약(`@mcp.tool()`·JSON 문자열·`mcp` 주입)은 운영 참고 코드에 맞췄지만 등록 화면을 본 적은 없다 |
| 생성한 hwpx 를 **한/글에서 열어보기** | 확인할 한/글이 없다. 개봉 안전 검사도 하지 않는다(1-5) |
| 실제 사내 용어사전 | `_MAX_TERM_WORDS=6`·적재 상한 2만 건(`_MAX_TERMS`)이 실물에 맞는지 미검증 |
| 빌드·시작 커맨드가 셸을 거치는지 | `cd A && B` 가 안 먹으면 `uvicorn --app-dir` 로 바꾼다 |
| 워크플로우 스텝 간 `data` 크기 한도 | 걸리면 본문 대신 **핸들(세션 키)** 만 넘기는 형태로 바꿔야 한다 |
| 번역 02 스텝 2개 | 코드는 있고 실행도 되지만 **캔버스에 등록된 적이 없다** |
