# 서비스 아키텍처

네 기능(FAQ 생성 · 글다듬이 · 번역 · 템플릿 채우기)이 **어디서 돌고, 요청이 어떤 길로 지나가며,
단계마다 어떤 규칙으로 판정하는지**를 코드 기준으로 적는다.

- 프론트와 주고받는 값의 정본은 [`FRONT.md`](FRONT.md), 안내 문구 등록표는 [`disclaimer.md`](disclaimer.md),
  환경변수 전체 목록은 [`env.md`](env.md) 다. 단계별 설정값 · MCP 그림은 [`architect.html`](architect.html).
- 설계 근거(왜 그렇게 했나)는 [`DESIGN_NOTES.md`](DESIGN_NOTES.md) 가 갖는다. 여기서는 **무엇을 어떻게**만 쓴다.
- 파일 경로는 `final/` 기준이다. `파일:함수` 로 적는다.

**단계 표시**

| 표시 | 뜻 |
|---|---|
| `●` | 우리 코드가 한다 |
| `◎` | GenOS 플랫폼이 한다 (우리 코드 밖) |
| `◐` | 일부만 한다 — 오른쪽에 무엇이 빠졌는지 적었다 |
| `○` | 자리만 있다 — 이 단계 없이 다음으로 넘어간다 |

---

## 0. 공통 구조

### 0.1 배치

```
 사용자 ─ 젠포탈 화면
            │  발화 · 캔버스 변수(언어·톤·개수·양식) · 첨부
            ▼
 ◎ 첨부 처리 ── 첨부용 전처리기 preprocessor/high_preprocessor.py
            │     → 캔버스 변수 genosUploaded = <doc file_name=…>마크다운</doc>
            ▼
 ● 캔버스 워크플로우 (workflow/*.py — 파일 1개 = 파이썬 스텝 1개)
     스텝 1: 원문 확보 · OCR · 입력 판정 · 정책
     스텝 2(·3): 본 기능 호출 · 검증 · 안내문 · 업로드 · 화면 스트리밍
            │  {GENOS_URL}/api/gateway/code_serving/{*_SERVING_ID}/<경로>    (HTTP / SSE)
            │  {GENOS_URL}/api/gateway/mcp/{*_MCP_ID}/mcp                   (JSON-RPC tools/call)
            ▼
 ● 코드서빙 4개 (FastAPI, <기능>/request/main.py)          ● MCP (mcp/*.py, 파일 1개 = 등록 단위)
     ├─ ◎ LLM 게이트웨이 /rep/serving/{LLM_SERVING_ID}/v1/chat/completions
     ├─ ◎ 프롬프트 라이브러리 GET {GENOS_ADMIN_API_URL}/prompt/template/{id}
     ├─ ◎ 용어사전 API (번역만) /data/glossaries/{id}/attributes · /terms
     ├─ ◎ MinIO CDN 업로드 GENOS_CDN_UPLOAD_URL → presigned_url
     └─ ◎ Redis (FAQ · 템플릿 채우기만)
```

운영은 언제나 **캔버스 스텝 → 코드서빙** 이다.

### 0.2 스텝 `run` 계약

아홉 스텝이 모두 같은 모양이다.

- `async def run(data)` — async generator. `{"event": "token"|"result"|"pythonStepResult", "data": …}` 를 yield 한다.
  중간 스텝은 마지막에 `result` 를 **한 번** 내 다음 스텝에 `data` 를 넘기고, 마지막 스텝은
  `pythonStepResult` 를 **한 번** 내 캔버스에 최종 결과를 준다.
- 입력이 문자열이면 JSON 으로 읽고, 안 되면 `{"question": data}` 로 감싼다.
- **앞 스텝 오류는 그대로 넘긴다.** `data.error` 가 있으면 스텝 1 은 통과시키고, 마지막 스텝은
  `{error}` 만 낸다(`finish_with_error`).
- **발화**는 `question → text → message → query` 순으로, 최상위에 없으면 `request_payload` 안에서 찾는다.
- **캔버스 변수**(`_canvas_vars`)는 `최상위 키 > overrideConfig.vars > 기본값 환경변수` 순이다. 빈 값은 없는 것으로 본다.
  스텝은 값을 **검증하지 않는다** — 검증은 MCP 와 코드서빙이 한다.
- **첨부**(`_extract_uploaded_markdown`): `<doc[^>]*>(.*?)</doc>` 본문들을 `\n\n` 으로 잇는다. 태그가 없으면 통째로 쓴다.
  글다듬이 · 번역은 **이번 턴 `file_ids` 가 있을 때만** `genosUploaded` 를 읽는다(`_turn_upload`) — 앞 턴 첨부가
  세션에 남아 있어도 무시한다(`event=upload_ignored`).
- **세션 id**: `socketIOClientId → sessionId → session_id`, 최상위를 먼저 보고 `genos_state` 를 본다.
- 마지막 스텝의 `pythonStepResult` 는 `{**data}` 를 싣지 않고 화면 값만 싣는다(`genos_state` 도 없다).

### 0.3 화면 스트리밍

```
 코드서빙  ──SSE──▶  마지막 스텝  ──socket.io "token"──▶  화면
  data: {"type":"delta","text":…}        sio_server.emit(room=sid) → await asyncio.sleep(0)
  data: {"type":"done", …응답 본문}       → result 1회
  data: {"type":"error","error_code","msg"}
```

- 스텝(`_stream_serving`)은 `text` 를 든 프레임이면 종류와 상관없이 그대로 `token` 으로 흘린다
  (FAQ 의 `item_open` · `item_close` · `progress` 도 같다). `done` 이 결과, `error` 는 실패다.
- **한 글자도 흘리기 전에 실패하면** 같은 payload 로 비스트리밍 라우트를 다시 부른다. 비스트리밍 결과는
  `_stream_chunks` 로 잘라 흘린다(조각 = `max(32, ⌈글자수/400⌉)` — emit 최대 400번).
- **흘린 뒤의 실패는 그대로 오류다.** 이미 흘린 글은 화면에 남는다.
- 서빙 안에서도 한 번 더 폴백한다: 게이트웨이가 LLM 스트리밍을 400/415/422/501 로 거절하면
  (`STREAM_UNSUPPORTED`) 서빙이 비스트리밍으로 돌려 결과를 델타 하나로 보낸다(`done.stream_fallback=true`).
- 흘리기 전 오류(입력 검증 등)는 SSE 가 아니라 평범한 JSON 오류 응답이다.
- 스캔 OCR 진행 같은 과정 안내는 `<think>…</think>` 안에 흘린다. 닫는 태그는 실패해도 낸다.

### 0.4 스텝 → 서빙 / MCP 호출 규칙

- 주소: `GENOS_URL` 끝 `/` 를 떼고, `/api/gateway` 로 끝나지 않을 때만 붙인다. 인증 `Authorization: Bearer {GENOS_TOKEN}`.
- 재시도(`_post_json`): connect 3초, **2회 시도**, 502·503·504 와 전송 오류만 재시도(0.3초 × n 대기).
- 실패 분류: `config`(설정 부재) · `transport`(시간 초과·연결) · `upstream_final`(본문 `error_code` 가
  `00020003` 으로 끝남 = 재시도 불가) · `execution`(그 밖).
- MCP 는 `Accept: application/json, text/event-stream` 을 붙인다. SSE 로 오면 `result`/`error` 프레임을 고르고,
  `result.content[].text` 를 이어 JSON 으로 읽는다.

### 0.5 오류 코드

형식은 `ERR-<영역>-<공통코드>` — 영역 `02` 스텝 · `03` 코드서빙, 공통코드 `00020001` 통신 · `00020002` 실행 ·
`00020003` 그 외(재시도 불가). 스텝은 `{error_code, msg, retryable}` 를 `result.error` 로 내고, 서빙은
`{error_code, msg}` 본문과 HTTP 상태를 낸다. 사용자 문구는 각 `error_codes.py` 의 고정 한국어다.

### 0.6 스캔 문서 OCR (스텝 1 넷 공통)

첨부용 전처리기는 텍스트 레이어가 없는 쪽을 PNG 로 CDN 에 올리고 그 자리에
`[[GENON_SCAN doc=… page=N image=<presigned>]]` 표식만 남긴다. 스텝 1 이 이것을 읽는다.

1. 표식이 하나라도 있으면 `scan_ocr=true`(→ 안내문 1번).
2. 같은 `doc` 의 연속한 쪽을 **최대 16쪽**씩 묶고(`_OCR_BATCH_PAGES`) 같은 이미지는 한 번만 넣는다.
3. 묶음마다 MCP `ocr_scan_pages({image_urls})` — read 제한 `20초 × 쪽수 + 30초`, 8초마다 경과 시간을 흘린다.
   쪽마다 `N쪽: 문단 n개 · k단`, 지운 머리말·꼬리말 수, 버린 낮은 점수 상자 수를 보여 준다.
4. 성공하면 표식을 인식된 글로 바꾼다. **한 묶음이라도 실패하면 턴을 세운다**
   (`IMAGE_NOT_FOUND`→`SCAN_SOURCE_MISSING`, `URL_NOT_ALLOWED`→`CONFIG_MISSING`,
   `IMAGE_FETCH_FAILED`·쪽 누락→`SCAN_OCR_FAILED`, `OCR_TRANSPORT_FAILED`→`SCAN_OCR_TIMEOUT`).

MCP 쪽(`genon_ocr.py`)은 `OCR_IMAGE_HOSTS`(기본 `GENOS_CDN_HOSTNAME` 호스트)에서만 이미지를 받고,
Paddle OCR(`OCR_ENDPOINT`) 결과를 줄 → 단 → 문단으로 복원하며 반복 머리말을 지운다(`min_score` 기본 0.3).

### 0.7 쪽 표식 `[[GENON_PAGE n]]`

첨부용 전처리기는 청크 머리에 `[[GENON_PAGE n]]` 한 줄을 붙이고 쪽 경계에서 청크를 끊는다(`page_marks`).
첨부 봉투에는 레코드의 쪽 필드가 실리지 않아서 본문에 넣는다.

- **FAQ** 만 이 표식을 쓴다 — 서빙이 걷어 내며 쪽 구간을 만들고 근거의 쪽을 정한다(§1.4).
- 글다듬이 · 번역 · 템플릿 채우기는 스텝 1 이 `_strip_page_marks` 로 걷어 버린다. 남기면 결과 글에 실린다.

### 0.8 입력 판단 `/input/check` (글다듬이 · 번역)

뜻 없는 입력(무작위 타자, 쪽 번호만 있는 문서 등)을 LLM 으로 거른다.

- 스텝 1 이 원문 앞 2,000자를 보낸다(read 30초). 서빙은 `input_check_system.md` 로 LLM 을 한 번 부르고
  (`INPUT_CHECK_LLM_SERVING_ID`, 없으면 `LLM_SERVING_ID`) 응답의 첫 `{…}` 만 읽는다.
- 받는 조합은 셋뿐이다: `usable:true/ok` · `usable:false/gibberish` · `usable:false/no_content`.
  그 밖(LLM 실패 · 형식 밖 응답 · 프롬프트 실패)은 `usable:true, reason:not_judged` — **판단하지 못하면 통과시킨다.**
- 스텝도 호출 자체가 실패하면 통과시킨다(fail-open).
- `usable:false` 는 **오류가 아니다.** 스텝 1 이 `*_input_unusable=true` + 빈 원문을 넘기고, 스텝 2 는 서빙을 부르지 않고
  빈 결과 + 안내문 3번(스캔이었으면 1번도)만 낸다.

### 0.9 LLM 호출 (서빙 `llm.py`, 단위마다 사본)

- URL: `_chat_url()` 이 `{GENOS_URL}[/api/gateway]/rep/serving/{LLM_SERVING_ID}/v1/chat/completions` 를 만든다.
- 본문: system + user 메시지, `temperature=MODEL_TEMP`, `reasoning_effort=LLM_REASONING_EFFORT`(기본 `none`, 비우면 생략).
  `model` 은 싣지 않는다.
- 타임아웃 connect 3초 / read `RES_TIMEOUT`, `LLM_RETRY_COUNT`(기본 2)회 시도, 4xx 는 재시도하지 않는다.
  스트리밍은 첫 델타가 나간 뒤에는 재시도하지 않는다.
- 결과는 **`LlmResult(content, error_type, is_transport_error)`** 로 돌려준다 — 예외를 밖으로 던지지 않는다.
  설정 부재는 `error_type="CONFIG_MISSING"`(재시도 불가), 전송 예외는 `is_transport_error=true`.

### 0.10 프롬프트

`prompt_library.py` → `prompt_loader.py` 순으로 찾는다(단위마다 사본).

1. `<단위>_PROMPT_IDS`(`이름=ID,…` 또는 JSON)에 이름이 있으면 프롬프트 라이브러리 본문을 쓴다
   (`GET {GENOS_ADMIN_API_URL}/prompt/template/{id}`, TTL 60초, 본문 상한 20,000자, timeout 5초).
2. 못 받거나 렌더에 실패하면 `final/<기능>/prompt/<배포단위이름>/<이름>.md` 파일.
3. 파일도 없으면 **요청을 세운다**(`PromptRenderError`, `event=prompt_render_failed`) — 빈 지시문으로 넘어가지 않는다.

렌더러는 `{{ 이름 }}` 치환과 `{# #}` 주석 제거만 한다. `{%` 가 있거나 변수가 빠지면 오류다.
`GET /prompts` 가 어느 쪽을 썼는지와 사유를, `POST /prompts/reload` 가 캐시 비우기를 맡는다.

### 0.11 산출 파일 · 업로드

- **018 세 기능은 `.md` 하나**를 낸다(`md_output.py`, 세 단위 사본). 파일 = UTF-8 BOM + 열람 안내(`GUIDE` + `---`)
  + 안내문 인용 블록(`> 줄`, 줄 사이 `>`) + 본문, 줄바꿈은 CRLF. 파일명은 `safe_stem(title)`(금지 문자 제거, 80자) + `.md`.
- **템플릿 채우기는 hwpx** 를 낸다(§4.6).
- 업로드(`file_store.upload_bytes`): `GENOS_CDN_UPLOAD_URL` 로 multipart(`file`, `hostname=GENOS_CDN_HOSTNAME`)를 보내고
  응답의 `data.presigned_url` 이 `download_url` 이다. connect 3초 / read 20초. **실패해도 결과는 정상으로 나가고**
  `download_url=null` + 안내문 2번이 붙는다.

### 0.12 안내문(`disclaimer`)

문장은 플랫폼 Disclaimer MCP 의 `widget_disclaimer({agent_id, disclaimer_id})` 에서만 받는다
(`DISCLAIMER_MCP_ID`, read 15초, 안내마다 동시에). 숫자는 코드가 상세 줄로 붙이고, 용어 · 본문은 싣지 않는다.

| 번호 | 키 | 기능 | 붙는 곳 | 상세 줄 |
|---|---|---|---|---|
| 1 | `scan_ocr` | 네 기능 | 화면 + 파일 | — |
| 2 | `download_failed` | 네 기능 | **화면만**(맨 뒤) | — |
| 3 | `input_unusable` | 글다듬이 · 번역 | 화면(파일 없음) | — |
| 4 | `fact_mismatch` | 글다듬이 · 번역 | 화면 + 파일 | `원문과 다른 곳: N곳` |
| 5 | `structure_changed` | 글다듬이 · 번역 | 화면 + 파일 | `구조가 달라진 곳: N곳` |
| 11 | `translate_failed_units` | 번역 | 화면 + 파일 | `번역하지 못한 문장: N개` |
| 31 | `faq_shortfall` | FAQ | 화면 + 파일 | `N개를 생성하지 못하였습니다.` |

- 화면에는 `result.disclaimer` 한 키(여럿이면 줄바꿈)로, 있을 때만 싣는다.
- 문구를 하나라도 못 받으면 맨 앞에 `disclaimer를 확인하지 못하였습니다. 결과에 유의해 주세요.` 를 한 번 붙인다.
- 상세 줄의 N 은 검증 MCP 가 돌려준 **문구 줄 수**다(숫자 · 날짜는 최대 2, 구조는 최대 4).
- 파일에 언제 넣는지는 기능마다 다르다 — 글다듬이 · 번역은 스텝이 판정 뒤 `/upload` 로, FAQ 는 서빙이 생성 요청 안에서,
  템플릿 채우기는 서빙이 hwpx 맨 끝에 넣는다.

### 0.13 로깅

서빙 · 스텝 · MCP 모두 화이트리스트 필드(`event`, `trace_id`, `request_id`, `resource_id`, `status`, `duration_ms`,
`item_count`, `upstream_status`, `error_code`, `error_type`)만 싣는다. 목록 밖 필드는 값을 버리고 이름만 남긴다.
본문 · 용어 · 값은 로그에 싣지 않는다. `GENON_DEBUG=1` 일 때만 stderr 로 값을 300자까지 낸다.

---

## 1. FAQ 생성

### 1.1 한눈에

```
  ┌──────────────────────────────────────┐
  │  입력   FAQ 개수 + 파일 업로드          │  faq_count · faq_max_count · faq_title · genosUploaded
  └───────────────────┬──────────────────┘
                      ▼
● 전처리기             high_preprocessor — hwpx·hwp·docx·pdf → 마크다운 + 쪽 표식 (스캔 쪽은 OCR MCP)
                      ▼
○ PII 마스킹           첨부용 전처리기에는 GenOS 가드레일(#315)이 연결돼 있지 않다
                      ▼
○ 입력 가드레일         빈 원문만 막는다 (NO_INPUT)
                      ▼
● 개수 결정            배포 상한 · 캔버스 상한 · 요청 개수 (스텝 1, 서빙 /config)
                      ▼
● 문서 분할            총 글자 ÷ 개수를 12,000~40,000자로 맞춘 조각
                      ▼
● FAQ 생성             조각마다 LLM, 6개씩 동시에 (항목마다 근거 → 질문 → 답변)
                      ▼
● 채택                 조각 순서대로 — 형식 · 중복 · 근거 대조(문서 전체) · 조각 몫
                      ▼
● 고르기 · 보충         후보가 많으면 고르게 고르고, 모자라면 최대 2번 더 요청 (비스트리밍 경로)
                      ▼
◐ 답변 품질            개수 미달만 안내 31번으로 알린다 (막지 않는다)
                      ▼
  ┌──────────────────────────────────────┐
  │  출력   md 파일 + 화면 텍스트           │  token(문답 항목 단위) · result{faq_items, download_url}
  └──────────────────────────────────────┘
```

| 자리 | 파일 |
|---|---|
| 스텝 1 (원문 · 개수) | `workflow/sfr018_faq_01_source.py` |
| 스텝 2 (생성 · 스트리밍) | `workflow/sfr018_faq_02_generate.py` |
| 코드서빙 | `SFR-018-faq/request/main.py`, `faq/` |
| 프롬프트 | `SFR-018-faq/prompt/SFR-018_faq/` — `md_system` · `md_user` · `md_retry_shortfall` |

### 1.2 스텝 1 — 원문과 개수

1. 캔버스 변수 `faq_count` · `faq_max_count` · `faq_title` · `genosUploaded` 를 읽는다(기본값 환경변수 없음).
2. `genosUploaded` 에서 본문을 꺼낸다. **쪽 표식은 그대로 둔다** — 서빙이 쓴다.
3. 스캔 표식이 있으면 OCR(§0.6).
4. 원문이 비면 `NO_INPUT` 오류(`FAQ 를 만들 문서를 첨부해 주세요.`). FAQ 는 입력 판단(`/input/check`)을 하지 않는다.
5. 개수: 서빙 `GET /config` 에서 배포 상한 `max_count`(서빙 `FAQ_MAX_COUNT`, 기본 30)와 기본값 `default_count`(5)를 받는다.
   - `상한 = min(배포 상한, faq_max_count 또는 배포 상한)` — 캔버스는 상한을 **낮출 수만** 있다.
   - `개수 = clamp(faq_count 또는 기본값, 0, 상한)`, 0 이면 `COUNT_ZERO` 오류.
6. 넘기는 값: `faq_source_text`, `faq_count`, `faq_title`, `faq_session_id`, `scan_ocr`.

### 1.3 스텝 2 — 생성 호출

1. 안내 문구 1번 · 31번을 **생성 전에** Disclaimer MCP 에서 받아 둔다(파일은 서빙이 생성 요청 안에서 굳히기 때문).
2. `POST /generate/stream`(read 120초) 에 `{markdown, count, session_id, title, scan_ocr, disclaimer_texts, disclaimer_unavailable}`.
3. 흘리기 전 실패면 `POST /generate` 로 다시 생성한다(§0.3).
4. 오류 분기: 422 → `NO_GROUNDED`(근거가 확인된 항목이 하나도 없음, 재시도 가능) · `config` → `CONFIG_MISSING` ·
   `transport` → `UPSTREAM_TIMEOUT` · `upstream_final` → `UPSTREAM_FINAL` · 그 밖 → `UPSTREAM_EXECUTION`.
5. 안내문은 **서빙이 판정한 `result.disclaimer` 를 그대로** 쓰고, `download_url` 이 비었을 때만 2번을 맨 뒤에 붙인다.
6. `result = {faq_items[{question, answer, evidence, evidence_ratio, page}], download_url, disclaimer?}`.
   기각 건수 · 조각 수는 `event=faq_done` 로그에만 남는다.

### 1.4 코드서빙 — 생성 파이프라인 (`faq/generator.py`)

**① 쪽 구간** — `pages.split_pages` 가 `[[GENON_PAGE (\d+)]]` 를 걷어 내며 `(쪽, 시작, 끝)` 구간을 만든다.
LLM 에는 표식 없는 원문만 간다.

**② 조각 분할** (`chunking.py`)

- 조각 크기 `chunk_budget = clamp(⌈총 글자 / 개수⌉, 하한 FAQ_MAX_CONTEXT_CHARS 12,000, 상한 FAQ_MAX_CHUNK_CHARS 40,000)`.
  짧은 문서는 12,000자 조각 하나, 긴 문서는 조각이 커지다가 40,000자에서 멈추고 조각 수가 늘어난다.
- `split_for_context`: 줄 단위로 쌓다가 예산을 넘으면 끊는다. 예산의 60% 를 넘긴 뒤 `#` 제목을 만나면 그 앞에서 끊는다.
  예산보다 긴 한 줄은 고정 길이로 자른다. 겹침은 없고 버리는 글자도 없다.
- 조각별 몫 `plan_quota`: `max(개수, 조각 수)` 를 조각 수로 나누고 나머지를 앞 조각부터 1개씩 더한다. 모든 조각이 최소 1개를 받는다.

**③ 조각별 LLM** — `asyncio.Semaphore(FAQ_LLM_CONCURRENCY=6)` + `gather`. 조각 사이에 순서 의존이 없으므로 호출만 겹친다.

- system `md_system.md(count=몫)`, user `md_user.md(document=조각, count=몫)`.
- 응답 형식(구분자 마크다운):

  ```
  <<<FAQ
  근거: (문서에서 그대로 옮긴 문장)
  질문: …
  답변: …
  >>>
  ```

  `markdown_items.ItemStream` 이 묶음 밖 글을 버리고, `>>>` 없이 다음 `<<<FAQ` 가 오면 앞 항목을 끊는다.
  **근거를 먼저 쓰게 하는 것**은 답변을 문서에 묶어 두기 위해서다.
- LLM 설정 · 프롬프트 부재가 나오면 `aborted` 를 세워 남은 조각을 부르지 않는다.

**④ 채택** (`_adopt` → `_adopt_one`) — 결과를 **조각 순서대로 한 곳에서** 처리한다. 중복 판정 · 기각 건수 · 몫이 누적 상태라
도착 순서대로 채택하면 같은 문서가 실행마다 다른 결과를 낸다.

1. 조각 몫이 찼으면 그 조각의 나머지를 버린다(`limit = min(목표, 현재 개수 + 몫)`).
2. 형식 — 질문 · 답변 · 근거 중 하나라도 비면 `rejected_schema`.
3. 중복 — 질문을 정규화하고 `[^0-9a-z가-힣]` 를 지운 키가 이미 있으면 `rejected_duplicate`. 키 집합은 조각을 가로질러 공유한다.
4. 근거 대조 — 통과하지 못하면 `rejected_ungrounded`.

**⑤ 근거 대조** (`evidence.EvidenceChecker`) — 조각이 아니라 **문서 전체**로 한 번 만든다(경계 문장을 근거로 든 항목이 오탐 기각되지 않게).

- 정규화(문서 · 근거 같은 함수): HTML 태그 → 공백, `* _ \` ~ # > | \\` → 공백, 공백 접기, `casefold`.
- 정규화한 근거가 문서에 **부분 문자열로 들어 있으면** 통과, `ratio=1.0`.
- 아니면 문자 3-gram 포함률 `|근거 ∩ 문서| / |근거|` 가 `FAQ_EVIDENCE_MIN_RATIO`(0.8) 이상이면 통과.
- `FAQ_EVIDENCE_REJECT=0` 이면 기각하지 않고 표시만 한다(기본 1 = 기각).
- **쪽**(`_page_of`): 정규화한 근거를 통째로 담은 첫 쪽, 없으면 3-gram 이 가장 많이 겹치는 쪽. 쪽은 LLM 이 아니라 이 대조가 정한다.

**⑥ 고르기** (`select_spread`, 비스트리밍) — 후보가 개수보다 많으면 근거 일치율(소수 3자리) 높은 순으로 남기고,
경계 점수의 동점 묶음에서는 문서 전체에 **고르게** 뽑는다. 결과는 문서 순서로 정렬한다. 최종 개수는 요청 개수를 넘지 않는다.

**⑦ 보충** (`_fill_shortfall`, 비스트리밍) — 항목이 1개 이상인데 모자라면 **최대 2번** 더 요청한다.
몫 대비 덜 나온 조각부터, `md_retry_shortfall.md` 에 이미 채택한 질문 목록을 넣어 겹치지 않게 한다. 실패하면 1차 결과를 유지한다.

**⑧ 실패 판정** — 항목이 1개 이상이면 일부 조각이 실패해도 성공이다. 0개면 첫 실패 분류(`transport`/`config`/`prompt`/`execution`)를
HTTP 오류로, 통신은 됐는데 채택이 0개면 `NO_GROUNDED`(422)다.

### 1.5 코드서빙 — 스트리밍 (`/generate/stream`)

두 갈래다.

- **조각 수 > 개수** (긴 문서, 후보 모드): 비스트리밍 파이프라인(①~⑧)을 그대로 돌리며 `<think>` 안에
  `k/N 구간 완료` 를 흘리고, 다 고른 뒤 고른 항목만 한꺼번에 흘린다. 도착 순서대로 흘리면 앞 조각이 자리를 다 차지한다.
- **조각 수 ≤ 개수** (항목 단위 실시간): 조각마다 LLM 스트림을 읽으며 이벤트별로 판정한다.
  1. `근거:` 가 닫히면 근거 대조 — 실패하면 그 항목은 화면에 열지 않는다.
  2. `질문:` 이 닫히면 중복 · 몫 · 전체 개수 확인.
  3. 첫 답변 델타에서 자리를 잡고(`open_slot`) `item_open`(`**Q{n}. 질문**`) → 답변 `delta` 를 흘린다.
  4. 항목이 끝나면 `item_close`(`> 근거 (3쪽): …`).

  조각이 겹쳐 돌기 때문에 **화면에는 한 번에 한 항목만 연다**(`_StreamCtx.stream_frame`). 다른 항목의 프레임은 버퍼에 쌓았다가
  화면을 쥔 항목이 닫히면 자리를 잡은 순서대로 흘린다 — 최종 `faq_items` 순서와 흘린 순서가 같다. 이 경로에는 ⑥ 고르기 · ⑦ 보충이 없다.

### 1.6 결과 · 파일 · 세션 (`main._store_and_payload`)

- 화면 마크다운과 md 파일은 **같은 조립기**(`formatting._render` · `evidence_line`)를 지난다:
  `**Q1. 질문**` / 답변 / `> 근거 (3쪽): …`. 쪽을 모르면 `> 근거: …`.
- 안내문(`_build_disclaimer`): `scan_ocr` 이면 1번, `요청 개수 − 생성 개수 > 0` 이면 31번 + `N개를 생성하지 못하였습니다.`.
  같은 안내가 화면 `disclaimer` 와 md 맨 위 인용 블록에 들어간다.
- md 를 만들어 MinIO 에 올리고(`download_url`), `session_id` 가 있으면 Redis `faq:session:{id}` 에 항목 · 안내문을 24시간 저장한다.
- `POST /download` 는 **저장된 것을 내려준다. 다시 생성하지 않는다.** 내려받아도 세션을 지우지 않는다. `format` 은 `md` 만 받는다.

### 1.7 주요 설정

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `FAQ_MAX_COUNT` / `FAQ_DEFAULT_COUNT` | 30 / 5 | 배포 상한 / 기본 개수 |
| `FAQ_MAX_CONTEXT_CHARS` / `FAQ_MAX_CHUNK_CHARS` | 12,000 / 40,000 | 조각 하한 / 상한 |
| `FAQ_LLM_CONCURRENCY` | 6 | 동시 LLM 호출 |
| `FAQ_EVIDENCE_MIN_RATIO` / `FAQ_EVIDENCE_REJECT` | 0.8 / 1 | 근거 통과 기준 / 미통과 기각 |
| `MODEL_TEMP` · `RES_TIMEOUT` | 0.2 · 90 | |
| `FAQ_SESSION_TTL_HOURS` | 24 | 다운로드용 세션 |

---

## 2. 글다듬이

### 2.1 한눈에

```
  ┌──────────────────────────────────────┐
  │  입력   문서유형 · 톤 + 글/파일         │  polish_doc_type · polish_tone · genosUploaded
  └───────────────────┬──────────────────┘
                      ▼
● 전처리기             첨부가 있을 때만 (스캔 쪽은 OCR MCP)
                      ▼
○ PII 마스킹           첨부용 전처리기 · 채팅 글 모두 거치지 않는다
                      ▼
◐ 입력 가드레일         뜻 없는 입력만 막는다 (/input/check). 인젝션 · 금칙 표현은 안 본다
                      ▼
● 톤 정책              MCP resolve_tone — 문서유형이 톤을 강제하면 바꾼다 (서빙이 같은 표로 다시 판정)
                      ▼
● 문서 분할            6,000자 조각 (빈 줄 경계, 표 · 코드 · HTML 표는 통째로)
                      ▼
● 문장 다듬기           조각마다 LLM, 4개씩 동시에 · 문서 순서대로 화면에 흘림
                      ▼
● 합침                 조각 + 꼬리 공백을 순서대로 이어 붙임 (실패 조각은 원문)
                      ▼
● 검증 MCP             text_guard — 표 · 제목 · 코드블록 구조, 숫자 · 날짜가 원문과 같은지
                      ▼
◐ 답변 품질            구조 · 숫자 어긋남을 안내 4 · 5번으로 알린다 (막지 않는다). 일부 조각 실패는 로그만
                      ▼
  ┌──────────────────────────────────────┐
  │  출력   md 파일 + 화면 텍스트           │  token(다듬은 글) · result{original_text, polished_text, download_url}
  └──────────────────────────────────────┘
```

| 자리 | 파일 |
|---|---|
| 스텝 1 (원문 · 정책) | `workflow/sfr018_polish_01_policy.py` |
| 스텝 2 (다듬기 · 검증) | `workflow/sfr018_polish_02_polish.py` |
| 코드서빙 | `SFR-018-polish/request/main.py`, `text_polish/` |
| 프롬프트 | `SFR-018-polish/prompt/SFR-018_text_polish/` — `system` · `sentence_rule` · `input_check_system` |
| MCP | `genon_lang_policy.resolve_tone`, `genon_text_guard.markdown_structure_issues` · `fact_issues` |

### 2.2 스텝 1 — 원문 · 입력 판단 · 톤

1. 원문 = **첨부 본문(쪽 표식 제거 · OCR 처리) → 없으면 발화**. 둘 다 비면 `INPUT_EMPTY`.
2. 입력 판단(§0.8). 막히면 빈 결과 + 안내 3번으로 끝.
3. MCP `resolve_tone({doc_type, tone})`(read 15초):

   | 문서유형 | 라벨 | 톤 |
   |---|---|---|
   | `email` | 메일 | 자유 선택 |
   | `post` | 게시글 | 자유 선택 |
   | `customer_notice` | 고객발송문구 | 자유 선택 |
   | `debt_reason` | 채무 및 연체발생 사유 | **`objective` 강제** |
   | `reviewer_opinion` | 심사역 의견 | **`objective` 강제** |

   톤은 `polite`(격식 · 정중, 기본) · `friendly`(친절 · 안내) · `clear`(명확 · 간결) · `objective`(사실 · 객관).
   모르는 문서유형은 `email`, 모르는 톤은 `polite`. MCP 호출이 실패하면 **기본 톤으로 진행하지 않고** 오류로 세운다.
4. 넘기는 값: `polish_source_text`, `polish_doc_type`, `polish_tone`, `tone_overridden`, `tone_notice`, `scan_ocr`.
   `tone_*` 는 캔버스 분기용이고 화면 · 안내문에는 쓰지 않는다.

### 2.3 스텝 2 — 다듬기 · 검증 · 파일

1. `POST /polish/stream`(read 90초) 에 `{text, doc_type, tone, title, upload:false}`. 흘리기 전 실패면 `POST /polish`.
   다듬은 글이 비면 `UPSTREAM_EXECUTION`.
2. 검증 MCP 두 도구를 동시에 부른다(`{source: 원문, revised: 다듬은 글}`, read 15초):
   - `markdown_structure_issues` — 지문 비교: HTML 표마다 `<tr>` 수 · `<td|th>` 수, 코드펜스 줄 수,
     `#`~`######` 제목 레벨의 순서, 마크다운 표의 구분행 수와 행별 칸 수. 다른 종류마다 한 줄(최대 4줄).
   - `fact_issues` — 날짜 4형식(`YYYY-MM-DD`류 · `YYYY년 M월 D일` · `YYYY년 M월` · `M월 D일`)을 표준형으로 바꾸고,
     날짜 밖 숫자는 콤마를 떼고 뽑아 **다중집합**으로 비교한다. 사라진 값 · 새로 생긴 값 각 한 줄(최대 2줄).
   - 호출이 실패하면 경고 없이 진행한다(`event=text_guard_call_failed`).
3. 안내문: 파일 안 = 1(스캔) · 4(숫자 · 날짜) · 5(구조) 순.
4. `POST /upload {text: 다듬은 글, title, disclaimer: 파일 안 안내}` → `download_url`. 실패면 2번을 화면 맨 뒤에.
5. `result = {original_text, polished_text, download_url, disclaimer?}`. 두 글은 태그 없이 원본 그대로 나간다.

### 2.4 코드서빙 — 다듬기 (`text_polish/polisher.py`)

**① 앞단** (`_prepare_polish`): 빈 글 400, `POLISH_MAX_INPUT_CHARS`(200,000) 초과 422 — **자르지 않는다**.
`tone_presets.resolve_policy` 로 톤을 MCP 와 같은 표로 다시 판정한다.

**② 시스템 프롬프트** (`system.md`): 한국어 교정 · 윤문 전문가 역할, 다듬은 글만 · 한국어만 · 번역 금지 ·
마크다운/HTML 구조 보존(문장만 다시 쓴다) · 사실 지어내기 금지 · 뜻 없는 입력은 그대로 반환. 이어서

- `[교정]` — 오탈자 · 띄어쓰기 · 비문
- `[문서유형: 라벨]` — 라이브러리 `doc_type_<코드>` 또는 표의 지시문
  (메일: 인사-본문-맺음말 흐름 유지 / 고객발송문구: 법적 고지 · 필수 항목 삭제 · 완화 금지 / 채무사유: 사실관계 중심 /
  심사역 의견: 판단 근거의 논리 순서 유지 …)
- `sentence_rule.md` — "문장을 합치거나 나누거나 새로 만들지 않고 순서도 바꾸지 않는다". **`clear` 톤만 빠진다**(문장을 짧게 끊어야 하므로).
- `[톤: 라벨]` — 라이브러리 `system_<톤>` 또는 프리셋 지시문
  (polite: `~습니다/~합니다` 완곡 / friendly: 부드러운 존댓말 · 쉬운 말 / clear: 한 문장에 한 가지 · 군더더기 삭제 /
  objective: 사실 중심 · 주관 · 추측 · 과장 삭제). 모든 톤이 수치 · 날짜 · 고유명사를 보존한다.

user 메시지는 조각 원문 그 자체다.

**③ 조각 분할** (`chunking.split_for_polish`, `POLISH_MAX_CHUNK_CHARS` 6,000)

- 빈 줄을 경계로 덩어리를 나눈다. 코드펜스 안 · 여러 줄 HTML 표 · `|` 로 시작하는 연속 줄(마크다운 표)은 덩어리 하나로 둔다.
- 덩어리를 6,000자까지 이어 붙인다. 6,000자를 넘는 덩어리 하나는 자르지 않는다.
- 조각 = `(본문 = rstrip, 꼬리 공백)`. LLM 에는 본문만 보내고 **꼬리 공백은 코드가 되꽂는다** — LLM 은 응답 끝 공백을 지우므로
  그대로 두면 문단 경계가 사라진다. 계약: `join(본문 + 꼬리) == 원문`.

**④ 병렬 · 실패** — `Semaphore(POLISH_LLM_CONCURRENCY=4)` + `gather`.

- 실패한 조각 자리에는 **원문을 되꽂는다.** 한 조각 실패로 문서 전체를 버리지 않는다.
- **전량 실패만 오류**다(`CONFIG_MISSING` → 500 재시도 불가, 전송 → 504, 그 밖 → 502). 일부 실패는 성공 응답 + `failed_chunk_count`.
- `CONFIG_MISSING` 이 한 번 나오면 남은 조각은 부르지 않는다.

**⑤ 스트리밍 순서** (`polish_document_stream`) — 맨 앞 조각은 델타를 받는 대로 흘리고, 뒤 조각은 자기 버퍼에 모았다가 차례가 오면
통째로 흘린다. 각 조각 뒤에 꼬리 공백을 흘린다. 한 글자도 못 흘린 실패 조각에서 멈췄다가 전체가 끝나고 성공이면 그 자리 원문을 흘린다.
전량 실패면 아무것도 흘리지 않고 `error` 프레임만 나간다.

### 2.5 주요 설정

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `POLISH_MAX_INPUT_CHARS` | 200,000 | 입력 상한 (넘으면 422) |
| `POLISH_MAX_CHUNK_CHARS` | 6,000 | 조각 크기 |
| `POLISH_LLM_CONCURRENCY` | 4 | 동시 LLM 호출 |
| `MODEL_TEMP` · `RES_TIMEOUT` | 0.3 · 90 | |
| `POLISH_DEFAULT_DOC_TYPE` / `POLISH_DEFAULT_TONE` | — | 스텝 기본값 (없으면 MCP 가 email / polite) |

---

## 3. 번역

### 3.1 한눈에

```
  ┌──────────────────────────────────────┐
  │  입력   언어 · 문체 + 글/파일           │  translate_target_lang · translate_source_lang · translate_register
  └───────────────────┬──────────────────┘
                      ▼
● 전처리기             첨부가 있을 때만 (스캔 쪽은 OCR MCP)
                      ▼
○ PII 마스킹           첨부용 전처리기 · 채팅 글 모두 거치지 않는다
                      ▼
◐ 입력 가드레일         뜻 없는 입력(/input/check) · 한국어 축이 아닌 언어쌍(MCP validate_direction)을 막는다
                      ▼
● 문서 분할            6,000자 조각 (빈 줄 경계, 표 · 코드 · HTML 표는 통째로)
                      ▼
● 번역                 조각마다 LLM (그 조각에 나온 용어사전 항목을 프롬프트에) · 15개씩 동시에 · 문서 순서대로 흘림
                      ▼
● 합침                 /translate/stream 안에서 조각 + 꼬리 공백을 순서대로 (실패 조각은 원문)
                      ▼
● 마무리                /translate/finalize — 용어사전 대조(한↔영) · <mark> 사본 두 벌 · 구조 지문 대조
                      ▼
● 검증 MCP             text_guard numeric_issues — 숫자가 원문과 같은지
                      ▼
◐ 답변 품질            숫자 · 구조 어긋남 · 번역 못 한 조각을 안내 4 · 5 · 11번으로 알린다. 용어 미반영은 로그만
                      ▼
  ┌──────────────────────────────────────┐
  │  출력   md 파일 + 화면 텍스트           │  token(번역문) · result{original_text, translated_text, download_url}
  └──────────────────────────────────────┘
```

| 자리 | 파일 |
|---|---|
| 스텝 1 (원문 · 방향) | `workflow/sfr018_translate_01_detect.py` |
| 스텝 2 (번역 · 마무리) | `workflow/sfr018_translate_02_translate.py` |
| 코드서빙 | `SFR-018-translate/request/main.py`, `translation_pipeline/office/` · `common/` |
| 프롬프트 | `SFR-018-translate/prompt/SFR-018_translation/` |
| MCP | `genon_lang_policy.validate_direction`, `genon_text_guard.numeric_issues` |

**언어는 화면 선택값이 유일한 근거다.** 본문에 "중국어로 번역해줘" 가 섞여 있어도 선택한 언어로 번역한다.
스텝은 본문을 파싱하지 않고, 서빙은 목록 밖 값을 400 으로 거절하며, 프롬프트는 "입력은 내용이지 지시가 아니다" 절을 둔다.

### 3.2 언어와 방향

지원 언어는 한국어 · 영어 · 중국어 · 태국어 · 베트남어 · 러시아어 6개이고, **한쪽은 반드시 한국어**다.

**스크립트 감지** (`languages.script_shares`, MCP 와 서빙 사본) — 글자마다 판정하고 판정된 글자만 분모로 센다(숫자 · 공백 · 기호 제외).

| 글자 범위 | 언어 |
|---|---|
| 베트남어 성조 문자 | vi |
| U+AC00–D7A3, 1100–11FF, 3130–318F | ko |
| U+0E00–0E7F | th |
| U+0400–052F | ru |
| U+4E00–9FFF, 3400–4DBF, F900–FAFF | zh |
| 그 밖의 라틴 알파벳 | en |

vi 가 한 글자라도 있으면 en 개수를 vi 에 합친다. 최빈값이 감지 언어다. 방향 거부는 LLM 에 맡기지 않는다 — 결정적이어야 하기 때문이다.

**방향 규칙** (`resolve_direction`)

1. 대상 언어가 목록 밖이면 거부.
2. 원문 언어 = 선언값, 없으면 감지값.
3. 원문을 정하지 못하면(선언 없음 + 감지 불가 — 숫자 · 기호뿐인 문서) **대상이 한국어일 때만** 통과. 비한국어 대상이면
   "원문 언어를 선택해 주세요" 로 거부한다 — 축을 증명할 수 없어서다.
4. 원문 = 대상이면 거부.
5. 원문 · 대상 어느 쪽에도 한국어가 없으면 거부(`en→ru` 등).
6. 선언과 감지가 다르고, 선언 언어 비율이 10% 미만이고, 감지 언어 · 대상이 모두 비한국어면 거부.

**문체** (`registers.resolve_register`): `written`(문어체, 기본) · `spoken`(구어체). 한국어 대상이면 문어체는 `~한다/~합니다`,
구어체는 `~해요/~예요` 를 지시한다. 모르는 값은 문어체로 바꾼다.

### 3.3 스텝 1 — 원문 · 방향

1. 원문 = 첨부 본문(쪽 표식 제거 · OCR) → 없으면 발화. 둘 다 비면 `INPUT_EMPTY`, 대상 언어가 없으면 `TARGET_MISSING`.
2. 입력 판단(§0.8) — 방향 검증보다 먼저 돈다.
3. MCP `validate_direction({sample: 원문[:2000], target_lang, source_lang})` — `allowed=false` 면 `UNSUPPORTED_PAIR`.
   감지 불가 · 선언과 감지 불일치는 로그만 남기고 진행한다.
4. 넘기는 값: `translate_source_text`, `translate_source_lang`(판정값), `translate_target_lang`, `translate_register`,
   `translate_glossary_applies`, `scan_ocr` 등.

### 3.4 스텝 2 — 번역 · 마무리 · 파일

1. `POST /translate/stream`(read 180초) 에 `{markdown, target_lang, source_lang, register, title, upload:false}`.
   델타를 받는 즉시 흘린다.
2. `done` 이 오면 `POST /translate/finalize`(30초)에 원문 · 번역문 · 옵션을 보내 하이라이트 사본 · 용어 보고 · 구조 대조를 받는다.
   실패해도 진행한다(사본 자리에 정본).
3. 흘리기 전 실패면 `POST /translate/markdown`(스켈레톤 경로, §3.6)으로 다시 번역한다.
4. **전량 실패 판정**: `translation_error` 가 있고 실패 조각 수 ≥ 전체 조각 수면 오류(`ALL_FALLBACK`, 설정 부재면 `CONFIG_MISSING`).
   번역 실패 자리에 원문이 남으므로 응답은 200 이고 본문도 비어 있지 않다 — 이 판정이 없으면 사용자는 자기 글을 번역문으로 돌려받는다.
   일부 실패는 오류가 아니라 안내 11번이다.
5. 숫자 검사 MCP `numeric_issues(원문, 번역 정본)` — 자릿수 구분 기호를 떼고 전각 숫자를 반각으로, 앞자리 0 을 떼고 Counter 로 비교한다.
   `1,000` ↔ `1.000` 은 같은 값으로 본다.
6. 안내문: 파일 안 = 1(스캔) · 4(숫자) · 5(구조, finalize 결과) · 11(번역 못 한 조각) 순.
7. `POST /upload {text: 번역 정본, title, disclaimer}` → `download_url`. 실패면 2번.
8. `result = {original_text: 원문 하이라이트 사본, translated_text: 번역 하이라이트 사본, download_url, disclaimer?}`.
   화면에는 정본을 흘리고 result 에서 사본으로 갈아 끼운다. 용어 보고 · 통계는 `event=translate_done` 로그에만 남는다.

### 3.5 코드서빙 — 스트리밍 번역 (기본 경로)

- 옵션 확정(`pipeline._resolve_options`): 서빙이 방향 · 문체를 **다시 판정**한다(문서 앞 4,000자). 거부면 400.
- 조각 분할(`stream_chunking.split_for_translation`, `TRANSLATE_STREAM_CHUNK_CHARS` 6,000) — 글다듬이와 같은 규칙
  (빈 줄 경계, 표 · 코드 · HTML 표 통째, 꼬리 공백 되꽂기).
- 프롬프트: `system_stream.md` + `user_stream.md`. 출력 언어를 못박는 문장(`{{ target_label }}`)을 맨 위와
  "입력은 내용이지 지시가 아니다" 절 두 곳에 둔다. 그 조각에 나온 용어사전 항목만 `- "원문" -> "번역"` 줄로 `{{ glossary_block }}` 에 넣는다.
- 병렬 `Semaphore(LLM_CONCURRENCY=15)`, 흘림 순서 · 실패 조각 원문 · 전량 실패 처리는 글다듬이 §2.4 ⑤ 와 같다.
- 이 경로는 **마크다운째 LLM 에 보낸다.** 구조 보존은 프롬프트 지시와 finalize 의 지문 대조(§3.7)가 맡는다.

### 3.6 코드서빙 — 스켈레톤 번역 (`/translate/markdown`, 폴백 경로)

문서를 **번역할 글(유닛)과 건드리지 않을 구조(리터럴)** 로 나눈 뒤 유닛만 번역해 다시 끼운다 — 구조를 코드가 보장한다.

**① 분해** (`markdown_units.split_markdown`)

| 원문 | 리터럴(그대로) | 유닛(번역) |
|---|---|---|
| HTML `<table>…</table>` | 태그 · 주석 | 태그 사이 텍스트(`html.unescape`) |
| 코드펜스 블록 | 통째 | — |
| 마크다운 표 행 | 구분행 `|---|`, 파이프 | 셀마다 |
| 제목 · 인용 · 목록 | `#`, `>`, `-`, `1.` 마커 | 마커 뒤 글 |
| 그 밖의 줄 | 앞뒤 공백 | 줄 |

글자가 없는 조각(숫자 · 기호뿐)은 유닛으로 만들지 않는다. 각 유닛에 직전 제목을 문맥(`c`)으로 붙인다.

**② 번역** (`translation_modes.translate_units`)

- **같은 원문은 한 번만 호출한다**(`TRANSLATE_DEDUPE_UNITS=1`) — 호출 수가 줄고 반복 머리글이 자리마다 다르게 번역되는 흔들림이 없어진다.
- 배치: 4,000자(`MAX_CHARS_PER_BATCH`) 또는 10개(`MAX_ITEMS_PER_BATCH`) 중 먼저 차는 쪽에서 끊는다.
  user = `[{"id","s","c"}]` JSON, 응답 = `[{"id","t"}]`.
- 응답 검증: 기대한 id 이고 `t` 가 비지 않은 항목만 채택, 기각 사유별로 센다. 배치가 실패하면 2번 재시도, 그래도 실패하거나
  빠진 항목은 **단건 번역**으로 다시, 단건도 실패하면 원문을 유지하고 `failed_unit_ids` 에 넣는다.
- 숫자 보존(`numeric_guard`, 유닛 단위): 기본 `warn`(경고만), `revert` 면 그 유닛을 원문으로 되돌린다.

**③ 재조립** (`rebuild_markdown`) — 번역문 개행은 공백으로, HTML 표 텍스트는 다시 escape, 표 셀의 `|` 는 `\|` 로 이스케이프한다
(번역문에 파이프가 섞이면 그 행부터 열이 밀린다). 같은 재조립기로 정본 · 번역 사본 · 원문 사본 세 벌을 만든다.

응답 `stats` 에 `unit_count` · `failed_unit_count` · `deduped_unit_count` · `fallback_rate`(실패 ÷ 전체)를 싣는다.

### 3.7 마무리 (`/translate/finalize`) — LLM 없음, 상태 없음

1. 방향 · 문체 재판정.
2. **용어사전 대조**(`build_document_glossary`) — 문서 전체를 유닛 하나로 본다.
   - 원문에서 사전 용어 위치(`spans`)를 찾고, 번역문이 그 용어의 대역어를 썼는지(`applied`)와 위치(`target_spans`)를 본다.
   - 한 원문에 후보가 여럿이면 **하나라도 쓰면 적용**이다(`glossary_report.judge_term` — 비스트리밍과 같은 함수).
   - `term_map` = **실제로 참고한 것만** `{"원문":"쓴 후보"}`, `term_map_unapplied` = 원문에는 나왔는데 번역문이 안 쓴 것(후보를 ` / ` 로 이음).
   - `compliance` = 적용 ÷ 매칭(매칭 0건이면 1.0).
3. **하이라이트 사본 두 벌** — 참고한 용어 낱말만 `<mark>…</mark>` 로 감싼다(원문 사본은 `spans`, 번역 사본은 `target_spans`).
   겹치는 구간은 병합해 한 번만 감싼다. **정본은 손대지 않는다** — 파일은 정본으로 만든다.
4. **구조 지문 대조**(`structure_diff`) — 원문과 번역문에서 마크다운 표 행 · 코드펜스 · HTML 표/행/셀 · 제목 · 목록 항목 개수를 세어
   다른 종류를 `issues` 로 낸다(→ 안내 5번).

### 3.8 용어사전

**적재** (`common/glossary_store.py`) — GenOS `데이터 > 용어사전` API. 기동 때 한 번, `POST /glossary/reload` 로 다시.

1. `GET {API}/data/glossaries/{id}/attributes` 로 속성 이름 → 키를 찾는다. 이름 `ko`(없으면 대표어)가 한국어, `en` 이 영어다.
   키를 하드코딩하지 않는 이유는 사전마다 키가 달라서다. 못 찾으면 `attribute_not_found`.
2. `GET …/terms?pg=N&pgSize=200` 을 끝까지 받는다(최대 500쪽).
3. 값은 `text[]` 전부 · `;` 로 나눈 전부가 후보다. 빈 값 · 같은 (한국어, 영어) 쌍을 거르고 사유별로 센다(값은 로그에 남기지 않는다).
4. **양방향 색인** — `ko→en` 은 각 한국어 표기가 영어 전부를, `en→ko` 는 영어 각각이 첫 한국어(대표어)를 후보로 갖는다.

**색인 · 조회** (`common/glossary_exact.py`)

- 표제어는 원문과 같은 토큰 정규식(`_TOKEN_RE`)으로 자른다(하이픈 · 아포스트로피 표기가 걸린다). 숫자도 독립 토큰이라 `1차` 는 `1차` 에만 걸린다. 문장부호도 토큰이라 문서의 부호를 넘어 용어가 이어지지 않고, 표제어의 부호는 있어도 없어도 된다(`401(k)` ↔ `401k`). 문서 쪽 영어 동사 활용(`refinanced`)은 어간 후보로 기본형 표제어(`Refinance`)에 건다(`_en_stems`). 한국어 `-하다/-되다` 활용형(`연체되었습니다`)도 어미 목록으로 떼어 본다(`_strip_ko_predicate`). 대소문자만 다른 원문은 한 묶음이다.
- 키 = 정규화한 첫 단어, 버킷 안은 단어 수 내림차순(최장 일치 우선). 같은 표기의 후보가 여럿이면 **전부** 같은 구간으로 낸다. 6단어 초과 용어는 제외, 300,000건을 넘으면 그 언어를 끈다.
- 영어 정규화: 소문자 + 복수형 접미사(`ies→y`, `ves→f`, `xes/ches/shes`, `s`) 제거.
- **한국어 조사는 조회할 때 뗀다**(`strip_ko_particle`) — 정확 일치가 먼저이고, 못 찾을 때만 긴 조사부터 떼어 본다(떼고 2자 이상일 때만).
  색인 키를 깎으면 `신용도` 가 `신용` 으로 굳어 표제어가 사라지므로 색인은 그대로 둔다.
  `match_occurrences` · `contains_phrase` · `phrase_positions` 셋이 같은 규칙을 쓴다.

**적용 범위** — 용어사전은 **한국어 ↔ 영어 쌍에만** 있다. 대상이 ko/en 이고 원문이 ko/en(또는 감지 불가)일 때만 적용한다.
나머지 언어는 LLM 만으로 번역한다. 못 받아도 번역은 계속하고, 이유를 `glossary.source.reason` 으로 남긴다
(`not_applicable` · `not_configured` · `fetch_failed_{상태}` · `invalid_response` · `attribute_not_found` · `language_missing` · `disabled_over_limit` · `ok`).

### 3.9 주요 설정

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `TRANSLATE_STREAM_CHUNK_CHARS` | 6,000 | 스트리밍 조각 |
| `LLM_CONCURRENCY` | 15 | 동시 LLM 호출 |
| `MAX_CHARS_PER_BATCH` / `MAX_ITEMS_PER_BATCH` | 4,000 / 10 | 스켈레톤 배치 |
| `TRANSLATE_MAX_TOTAL_CHARS` | 500,000 | 입력 상한 (넘으면 400) |
| `TRANSLATE_DEDUPE_UNITS` · `TRANSLATE_NUMERIC_GUARD` | 1 · warn | |
| `TRANSLATE_GLOSSARY_API_URL` · `_ID` · `_TOKEN` · `_KO_ATTR` · `_EN_ATTR` | — · — · `GENOS_TOKEN` · ko · en | 용어사전 |
| `MODEL_TEMP` · `RES_TIMEOUT` · `MAX_TOKENS` | 0.3 · 90 · 16,384 | |

---

## 4. 템플릿 채우기 (여러 턴)

### 4.1 한눈에

```
  ┌──────────────────────────────────────┐
  │  입력   양식 선택 + 채팅 (+ 참고 문서)   │  template_fill_template_id · 발화 · genosUploaded(선택)
  └───────────────────┬──────────────────┘
                      ▼
● 세션 불러오기         양식 항목 목록 · 지금까지 채운 값 · 본문 블록 (Redis)
                      ▼
● 첨부 원문            genosUploaded (문서 캐시 · 스캔 쪽은 OCR MCP)
                      ▼
○ PII 마스킹 · 입력 가드레일
                      ▼
● 발화 해석            LLM — 채울 값 · 지울 값 · 본문 추가/삭제 · "문서 내용으로 바꿔줘"
                      ▼
● 문서 자동 채움        아직 안 읽은 문서일 때 — 12,000자 조각, 빈 항목만
                      │   일반 양식: 조각 순서대로, 다 차면 멈춤
                      │   반복 묶음 양식: 1차 LLM 주제 목록 → 주제별 구간 → 2차 LLM 묶음마다 (4개씩 동시에)
                      ▼
● 검증                 항목 화이트리스트 — 양식에 없는 항목 · 형식이 틀린 값은 버림 (LLM 호출마다)
                      ▼
● 병합 · 저장           문서 값 → 발화 값 순 (사용자가 넣은 값은 문서가 덮지 않음) → 세션 저장
                      ▼
◐ 답변 품질            채운 값을 전부 나열 · 자동 채움 전량 실패는 답변에 한 줄 · 파일 생성 실패는 안내 2번
                      ▼
  ┌──────────────────────────────────────┐
  │  출력   hwpx 파일 + 화면 텍스트         │  token(진행 → 답변 → 미리보기) · result{text, download_url, session_id}
  └──────────────────────────────────────┘
```

| 자리 | 파일 |
|---|---|
| 스텝 1 (세션 · 첨부) | `workflow/sfr006_01_context.py` |
| 스텝 2 (발화 해석) | `workflow/sfr006_02_extract.py` |
| 스텝 3 (자동 채움 · 커밋 · 답변) | `workflow/sfr006_03_commit.py` |
| 코드서빙 | `SFR-006/request/main.py`, `template_fill/` |
| 프롬프트 | `SFR-006/prompt/SFR-006_template_fill/` |
| MCP (사람이 직접) | `mcp/genon_template_draft.py` — `template_fill_draft` |

### 4.2 양식 등록 · 색인

**등록** (`POST /templates`, 관리자 `X-Admin-Token`) — `.hwpx` 만, 20MB 이하. **먼저 파싱해 보고** 성공하면 볼륨
(`TEMPLATE_FILL_TEMPLATE_DIR`, `{id}.hwpx`, 임시 파일 → 원자적 교체)에 쓰고 색인을 Redis 에 저장한다.
응답에 인식한 항목 · 본문 서식 · 반복 묶음 · 경고 · 따옴표 없는 `{…}` 표본을 싣는다.

**채울 자리 인식** (`hwpx_fields.py`) — 본문 `Contents/section{N}.xml` 을 섹션 번호 순으로 읽는다.

| 방식 | 표기 | 항목 이름 / 안내문 | 채워짐 판정 |
|---|---|---|---|
| **슬롯**(기본) | `{'항목명', 16pt, 굵게}` — 따옴표 `' ‘ " “` 로 연다 | 따옴표 안 문자열이 이름이자 안내문. 뒤는 서식 인자 | 항상 미입력(문서에 `{…}` 가 남아 있으면 안 채운 것) |
| 누름틀 | 한글 CLICK_HERE 필드 | `name` 속성 → 안내문 → `field_{n}` | 현재 글이 비어 있지 않고 안내문과 다름 |
| 토큰 | `{{token}}` | 토큰 이름 | — |

- 따옴표 없는 `{소속}`, `{YYYY.MM.DD.}` 는 채울 자리가 아니다 — 문서에 그대로 남기고 등록 응답에 경고로만 싣는다.
- 같은 이름은 한 항목으로 합치고 값은 모든 자리에 같이 들어간다. 순서는 문서 등장 순서. 최대 200개(`MAX_FIELDS`).
- 슬롯 위치는 문단이 **직접 소유한** 글자(`para_text`) 기준 offset 이다 — 표 안 하위 문단은 빠진다.

**반복 묶음** (`hwpx_repeat.py`) — `본문 1`, `내용 1-1` 처럼 1 로 끝나는 이름을 묶음으로 본다. 묶음 항목을 가진 첫 문단부터
마지막 문단까지가 복제 구간이다. 개수는 저장하지 않고 **값이 든 가장 큰 번호**로 센다(상한 묶음 10 · 세부 10).
번호 2 이상이 이미 적혀 있거나 여러 섹션에 걸치면 반복을 끄고 경고한다.

**색인 캐시** (`template_index.py`) — Redis `template_fill:index:{id}`, TTL 720시간. 스키마 버전 · 설정 · 내용 해시가 다르면 다시 파싱한다.
Redis 가 죽어 있으면 직접 파싱한다.

### 4.3 턴 하나 — 스텝 1 · 2 · 3

**스텝 1 — 세션 · 첨부** (`/chat/context`, 20초)

1. 발화를 4,000자에서 자른다. 양식 = 캔버스 `template_fill_template_id` → 세션의 양식 → `TEMPLATE_FILL_DEFAULT_TEMPLATE_ID`.
2. 서빙이 세션을 읽고 양식 색인을 불러, 세션 값을 화이트리스트로 다시 거른다(`chat_state.restore_state`).
   돌려주는 것: 항목 이름 · 본문 서식 · 현재 값 · 블록 · 빈 항목 · 양식 원본 마크다운.
3. 첨부: 본문을 꺼내고 쪽 표식을 걷는다. 문서 캐시(`/chat/doc/get`, 세션별 최근 5개)에 있으면 OCR 을 건너뛰고,
   없으면 OCR(§0.6) 뒤 `/chat/doc/put` 으로 저장한다. **자동 채움은 여기서 하지 않는다.**

**스텝 2 — 발화 해석** (`/chat/extract`, 60초) — 발화가 비면 부르지 않는다.

- 프롬프트: `extract_system.md`(+ 양식 전용 `extract_system__<양식>.md` 가 있으면 그것, + 문체 `style__<양식>.md`) /
  `extract_user.md` 에 항목 목록(`- 이름 (채워짐|미입력) — 안내문: …`), 현재 값 JSON, 반복 묶음 현황(코드가 계산한 다음 번호),
  본문 블록 목록, 발화를 넣는다.
- 응답: `{"updates":{항목:값}, "clears":[항목], "blocks":[{"style_ref","text"}], "block_clears":[번호], "use_document":true}`.

  | 의도 | 키 |
  |---|---|
  | 값 채우기 · 고치기 | `updates` |
  | 값 지우기 | `clears` |
  | 양식 밖 본문 추가 | `blocks` |
  | 본문 삭제 | `block_clears`(1부터) |
  | "문서 내용으로 바꿔줘" | `use_document` |

- **검증** (`field_judge.parse_updates`) — 화이트리스트 밖 이름 · 빈 문자열 · 리스트/객체는 기각, 값은 2,000자에서 자른다.
  같은 항목이 `updates` 와 `clears` 에 다 있으면 고치기를 채택한다. 블록은 100개 · 4,000자 상한, 서식 이름이 목록 밖이면 기본 서식.
  `use_document` 는 JSON `true` 만 참이다. **이 스텝은 저장하지 않는다.**

**스텝 3 — 자동 채움 · 커밋 · 답변**

1. 문서가 있으면 `POST /chat/prefill/stream`(180초)으로 자동 채움(§4.4). 진행 상황을 `<think>` 안에 흘린다.
   흘리기 전 실패면 `/chat/prefill`. 실패해도 **턴을 막지 않는다**(`prefill_failed=true`).
   `use_document` 인데 문서가 없으면 부르지 않고 "문서 없음" 을 답변에 낸다.
2. 스캔 문서였으면 안내 1번 문구를 받아 `file_disclaimer` 로 넘긴다.
3. `POST /chat/commit`(30초) — 순서가 계약이다.
   1. 세션을 다시 읽고 이전 값을 보관한다.
   2. **문서 값을 먼저** 병합 — 화이트리스트에 있고, 아직 값이 없는 항목만(`use_document` 면 덮어쓰기).
   3. **발화 값을 나중에** 병합 — 같은 턴의 발화가 문서 값을 이긴다.
   4. 빈 반복 묶음 번호를 당긴다(`compact`).
   5. 블록은 **삭제를 먼저, 추가를 나중에**(삭제 번호가 추가 이전 목록 기준이라서). 상한을 넘는 새 블록은 받지 않고 기각에 적는다.
   6. 세션 저장 — 실패하면 오류로 세운다(다음 턴에 값이 사라지므로).
   7. 미리보기를 만들고 답변을 짓는다. 빈 항목이 없으면 hwpx 를 만들어 올린다.
4. 답변(`chat_reply.compose_status_reply`): 자동 채움으로 채운 값 전부(덮어쓰기면 `이전 → 새`) → 이번 턴 반영 · 고침 · 비움 · 기각 →
   블록 추가 · 삭제 건수 → 작성 현황표 → 다음에 채울 항목(최대 3개). **값의 진위는 코드가 판정하지 않으므로 채운 값을 전부 보여 준다.**
5. 화면 = 답변 + `---` + `**미리보기**` + 채운 문서 마크다운.
   `result = {session_id, template_id, text, download_url | null, disclaimer?}`.

### 4.4 문서 자동 채움 (`doc_prefill.py`)

**게이트** (`chat_api._prefill_gate`, 순서대로): 기능이 꺼짐 → 문서 없음 → (덮어쓰기면 여기서 통과) → **이미 읽은 문서**
(sha256 앞 16자가 세션 `source_doc_hashes` 에 있음) → 채울 빈 항목 없음. 한 세션이 기억하는 문서는 20개이고 오래된 것부터 잊는다.

**보호 집합** — 덮어쓰기가 아니면 이미 값이 든 항목을 묻지 않고, 흘리지 않고, 와도 버린다.

**조각 분할** (`split_document`) — 줄 경계, 12,000자(`DOC_CHUNK_CHARS`), 예산 60% 이후 `#` 제목 앞에서 끊기. 20조각(`DOC_MAX_CHUNKS`)을 넘으면 뒤를 버린다.

**일반 양식** (`_fill_by_chunks`) — 조각을 **순서대로** 돈다.

- 조각마다 아직 빈 항목만 묻는다(`document_system.md` · `document_user.md`, 응답 `{"updates":{…}}`). 앞 조각이 채운 값을 뒤 조각이 덮지 않는다.
- 빈 항목이 다 차면 **그 자리에서 멈춘다** — 조각 수가 그대로 비용이 되지 않게.
- 스트리밍이면 `"updates"` 안의 닫힌 `키:값` 쌍을 나오는 대로 꺼내 같은 검증을 거쳐 `✔ 항목: 값` 으로 흘린다.

**반복 묶음 양식** — 두 단계다.

1. **주제 뽑기** (`_plan_topics`) — 조각마다 `topic_system/user` 로 `{"topics":[{"title","anchor"}]}` 를 받는다. 남은 자리
   (`10 − 이미 쓴 묶음`)보다 많으면 `merge_system/user` 로 고른다(실패하면 앞에서부터).
2. 묶음 밖 항목은 일반 방식으로 채운다.
3. **묶음 채우기** (`_fill_groups`) — 주제마다 `anchor` → `title` 로 문서에서 위치를 찾아 다음 주제 앞까지 구간을 자른다(최대 12,000자,
   못 찾으면 그 주제를 뽑은 조각 전체). **묶음 번호는 코드가 정하고**, 그 번호의 항목만 화이트리스트로 `group_system/user` 를 부른다.
   `Semaphore(DOC_GROUP_CONCURRENCY=4)` 로 동시에 돌리고 채택은 락으로 하나씩 한다.
4. 주제가 0개면 묶음 자리를 상한까지 펼쳐 일반 방식으로 묻는다.

**결과** — 호출한 조각 수 > 실패한 조각 수면 성공이다(값 0개는 실패가 아니다). 실제로 돌면 문서 해시를 세션에 기록한다.

### 4.5 세션

- Redis `template_fill:session:{id}` 키 **하나**에 JSON 스냅샷을 저장하고 **매 턴 통째로 덮어쓴다.** 대화 이력은 저장하지 않는다 —
  발화 해석 LLM 은 매 턴 "이번 발화 + 지금까지의 값" 만 본다.

  ```
  {version: 3, template_id, values: {항목: 값}, blocks: [{text, style_ref}],
   source_doc_hashes: [최대 20], file_disclaimer, updated_at}
  ```

- 덮어쓰기라서 커밋 · 화면 편집(`PATCH /values`, `PUT /blocks`) 모두 블록 · 해시 · 안내문을 매번 다시 싣는다.
- 크기 상한: 값 200항목 × 2,000자, 블록 100개 × 4,000자, 문서 해시 20개. 문서 캐시(`{세션키}:doc`)는 최근 5개, 한 문서 500,000자 이하.
- 수명: TTL 24시간(저장할 때마다 다시 걸린다). `/generate` 가 성공하면 세션 키와 문서 캐시를 즉시 지운다.
- 읽기 실패 · 손상은 빈 세션으로 진행, 저장 실패는 오류다.

### 4.6 hwpx 만들기 (`document.build`)

순서는 **반복 복제 → 서식 → 채우기 → 본문 블록 → 안내문** 이고 이 함수 한 곳이 쥔다.

1. **반복 복제** (`hwpx_repeat.expand_repeats`) — 묶음 개수만큼 구간 문단을 복제하고 슬롯 이름의 번호를 바꾼다. 복제본에서 쪽 단위 제어
   (구역 설정 · 머리말 · 꼬리말 · 쪽 번호)를 떼고 표 · 그림 id 를 새로 준다. 구간 안 표는 표째 복제된다.
2. **서식** (`hwpx_style.apply_styles`) — 슬롯 인자를 생김새로 읽는다: `16pt`/`16포인트` → 크기, 굵게 · 기울임 · 밑줄(부정 표현 먼저),
   남은 첫 토큰 → 글꼴. 원래 글자 모양을 복제해 바꾸고, 같은 모양이 이미 있으면 그 id 를 쓴다. **서식 실패는 삼키고** 서식 없이 계속한다.
3. **채우기** (`hwpx_fields.fill_template`)
   - 슬롯: offset 기준으로 `{…}` 구간만 값으로 바꾸고 바깥 글자는 노드 경계까지 그대로 둔다. **값이 없는 슬롯은 `{…}` 를 지운다**(작성 지시문이므로).
     값 앞에 `항목명:` 이 붙어 오면 뗀다.
   - 누름틀: 첫 글자 노드에 값, 나머지는 비운다. 값이 없으면 안내문 상태로 둔다.
   - 줄바꿈은 `hp:lineBreak`, 글자를 바꾼 문단은 줄 배치 캐시(`linesegarray`)를 지운다.
4. **본문 블록** (`hwpx_blocks.append_blocks`) — 서식 이름에 해당하는 문단을 복제해 글만 바꿔 넣는다. 블록 안 줄바꿈은 문단 분리다.
   위치는 `TEMPLATE_FILL_BLOCK_ANCHOR` 항목 문단 뒤, 없으면 문서 끝.
5. **안내문** — `file_disclaimer` 가 있으면 문서 맨 끝(본문 블록 아래)에 줄마다 문단으로 붙인다.

**`download_url`** 은 빈 항목이 없는 커밋 턴에만 온다 — `{template_id}_초안.hwpx` 를 만들어 MinIO 에 올린다.
그 전에도 화면이 `POST /generate` 로 받을 수 있다(세션 값 + 요청 값으로 조립, 성공하면 세션 종료).
미리보기(`hwpx_markdown.render_filled`)는 같은 파이프라인을 서식 · 안내문 없이 돌려 마크다운으로 바꾼 것이다.

### 4.7 라우트

| 구분 | 라우트 |
|---|---|
| 양식 | `GET/POST /templates`, `DELETE /templates/{id}`, `GET /fields` |
| 대화(캔버스) | `POST /chat/context` · `/chat/doc/get` · `/chat/doc/put` · `/chat/extract` · `/chat/prefill` · `/chat/prefill/stream` · `/chat/commit` |
| 화면 편집 | `GET /status`, `GET /preview`, `PATCH /values`, `DELETE /values`, `PUT /blocks` |
| 생성 | `POST /generate`(세션 종료), `POST /draft`(세션 유지), `POST /generate/upload`(즉석 양식) |
| 기타 | `GET /health`, `GET /prompts`, `POST /prompts/reload` |

### 4.8 주요 설정

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `TEMPLATE_FILL_DOC_CHUNK_CHARS` / `_DOC_MAX_CHUNKS` | 12,000 / 20 | 자동 채움 조각 |
| `TEMPLATE_FILL_DOC_GROUP_CONCURRENCY` / `_DOC_GROUP_SECTION_CHARS` | 4 / 12,000 | 묶음 채우기 |
| `TEMPLATE_FILL_MAX_FIELDS` / `_MAX_VALUE_CHARS` | 200 / 2,000 | 항목 · 값 상한 |
| `TEMPLATE_FILL_MAX_BLOCKS` / `_MAX_BLOCK_CHARS` | 100 / 4,000 | 본문 블록 상한 |
| `TEMPLATE_FILL_MAX_REPEAT` / `_MAX_REPEAT_ITEMS` | 10 / 10 | 반복 묶음 상한 |
| `TEMPLATE_FILL_SESSION_TTL_HOURS` / `_INDEX_TTL_HOURS` | 24 / 720 | 세션 / 색인 수명 |
| `MODEL_TEMP` · `RES_TIMEOUT` | 0.1 · 60 | |

---

## 5. 전처리기 · MCP

### 5.1 전처리기

| | 첨부용 `high_preprocessor.py` | 적재용 `final_preprocessor.py` |
|---|---|---|
| 쓰는 곳 | 네 기능의 첨부(`genosUploaded`) | RAG 적재 |
| 형식 | hwpx · hwp · docx · pdf | 모든 형식(hwpx 는 자체 파서, 나머지는 벤더) |
| hwpx · docx | zip + XML 자체 파서 | hwpx 자체 파서 / docx 벤더 |
| hwp | GenosHwp 리더, 표는 셀 span 으로 HTML | 벤더 |
| pdf | PyMuPDF 표 찾기 + 줄 좌표로 단 · 문단 복원, 스캔 쪽은 OCR | 벤더 평문 |
| 표 | HTML + 첫 행 `<th>` | 같음 |
| 쪽 | `[[GENON_PAGE n]]` 머리 + 쪽 경계에서 청크 끊기. hwpx · docx 는 뷰어 PDF 로 변환해 블록 대조 — 절반 넘게 대조가 안 되면 표식 없이 | 레코드 쪽 필드 |
| 스캔 | 쪽 PNG 를 CDN 에 올리고 `[[GENON_SCAN …]]` 표식(스텝 1 이 OCR) | 벤더 |
| 청킹 | 조/항/호 위계(`제N조` 2개 이상), 이어붙이면 원문 | 같음 |
| PII | 없음 | GenOS 가드레일(#315) |

hwpx 파싱 코어(표 격자 · 1칸 표 문단화 · 자동 번호 · 수식)는 전처리기와 006 · 번역 · FAQ 서빙에 사본으로 있다.

### 5.2 MCP

| 파일 | 도구 | 하는 일 | 부르는 곳 |
|---|---|---|---|
| `genon_ocr.py` | `ocr_scan_pages` | 스캔 쪽 이미지 → Paddle OCR → 문단 | 스텝 1 넷 |
| `genon_lang_policy.py` | `validate_direction`, `resolve_tone` (+ `detect_language` · `list_languages` · `list_registers` · `resolve_register`) | 번역 방향 판정, 문서유형별 톤 강제 | 번역 스텝 1, 글다듬이 스텝 1 |
| `genon_text_guard.py` | `markdown_structure_issues`, `fact_issues`, `numeric_issues` (+ `diff_changes`) | 원문 ↔ 결과 구조 · 숫자 · 날짜 결정적 비교 | 글다듬이 스텝 2, 번역 스텝 2 |
| `genon_glossary.py` | `glossary_lookup` · `glossary_status` · `glossary_reload` | 용어사전 API 적재 · 완전 일치 조회 (서빙 `glossary_store.py` 와 같은 규칙) | 캔버스 노드용 — 네 기능 흐름은 부르지 않는다 |
| `genon_pii_audit.py` | `pii_audit` · `pii_scan_text` · `pii_detectors` | 마스킹 안 된 PII 건수 감사 | 사람이 직접 |
| `genon_template_draft.py` | `template_fill_draft` | 006 `POST /generate` → hwpx 업로드 → `download_url` | 사람이 직접 |

MCP 는 파일 하나가 등록 단위이고 표준 라이브러리만 쓰며 LLM 을 부르지 않는다. 입력 오류는 예외가 아니라 `{"ok": false, …}` 결과로 돌려준다.
안내 문구(`widget_disclaimer`)는 이 저장소 밖 플랫폼 MCP 다.

---

## 6. 배포 단위

| 단위 | 루트 | 시작 | 패키지 |
|---|---|---|---|
| FAQ | `SFR-018-faq/request/` | `uvicorn main:app` | `faq/` |
| 글다듬이 | `SFR-018-polish/request/` | 〃 | `text_polish/` |
| 번역 | `SFR-018-translate/request/` | 〃 | `translation_pipeline/` (+ 루트 `config.py` · `api_contract.py`) |
| 템플릿 채우기 | `SFR-006/request/` | 〃 | `template_fill/` |

- `main.py` 는 단위 루트에 두고 맨 끝이 `if __name__ == "__main__": uvicorn.run(…, port=PORT)` 다. `PORT`(기본 8080)는 GenOS 가 주입한다.
- 프롬프트 `final/<기능>/prompt/<배포단위이름>/` 은 단위 밖에 있고 로더가 상위로 올라가며 찾는다.
- 워크플로우 스텝은 캔버스에 내용을 붙여 넣고, MCP 는 파일마다 등록한다.
