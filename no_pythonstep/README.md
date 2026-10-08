# no_pythonstep — 젠포탈이 코드서빙을 **직접** 부르는 경로 (네 단위 전부)

> 세션이 끊겨도 이어서 작업할 수 있게 남기는 작업 기록이다. **할 일은 맨 아래 "지금 할 일"**.
> 마지막 갱신: 2026-10-08 (번역 시범 확인 → 글다듬이·FAQ·006 에도 `/chat` 적용 → 네 단위 모두 `main.py` 를 단위 루트로)

## 단위 한눈에

| 폴더 | 시작 커맨드 | `complete` 값 | 비고 |
|---|---|---|---|
| `SFR-018-translate/` | `uvicorn main:app --host 0.0.0.0 --port $PORT` | `original_text`·`translated_text`·`download_url`·`notice?` | 시범. 아래 본문 |
| `SFR-018-polish/` | `uvicorn main:app --host 0.0.0.0 --port $PORT` | `original_text`·`polished_text`·`download_url`·`doc_type`·`tone`·`tone_overridden`·`notice?` | **`TEXT_GUARD_MCP_ID` 새로 필요** |
| `SFR-018-faq/` | `uvicorn main:app --host 0.0.0.0 --port $PORT` (또는 루트 `main.py`) | `faq_items`·`download_url`·`notice?`·`disclaimer?` | 세션 없으면 Redis 저장만 건너뜀 |
| `SFR-006/` | `uvicorn main:app --host 0.0.0.0 --port $PORT` (또는 루트 `main.py`) | `template_id`·`session_id?`·`download_url` | **여러 턴 — 세션 id 가 관건** |

공통: 프레임 `{"event","data"}`(heartbeat/token/complete/end), 채팅에 보일 글은 token 으로만,
`complete` 에 `text` 없음, 스트리밍 오류도 200 SSE, `stream:false` 는 `text` 를 실은 JSON,
`CHAT_*` 환경변수, `[입력된 문서]` 표식, 우선순위 최상위 키 > `question` 머리말 > 환경변수 기본값,
스캔 표식 `[[GENON_SCAN` 은 OCR 미지원(번역·글다듬이·FAQ 는 거절, 006 은 자동 채움만 건너뜀).
각 단위 상세는 아래 단위별 절.

**`main.py` 는 네 단위 모두 단위 루트에 있다** — GenOS 는 저장소 루트의 `main.py` 를 먼저 실행한다(개발가이드 6.2).
번역은 `config.py` 까지 루트에 있는 특별한 경우이고, 글다듬이·FAQ·006 은 `config.py` 가 패키지(`text_polish/`·`faq/`·`template_fill/`)
안에 있고 `main.py` 는 **그보다 한 단계 위**다. 루트 `main.py` 는 패키지를 `faq.…`·`template_fill.…` 절대 경로로 import 하고,
파일 끝에 `if __name__ == "__main__"` uvicorn 블록이 있다. `final/` 도 같은 배치로 맞췄다(`check_deploy_contract` 가 루트 `main.py` 부재·기동 블록 위치를 FAIL 로 본다).
네 단위 모두 `python main.py` 로 띄워 `/health`·`/chat` 등록을 확인했다(2026-10-08).

## 왜 만들었나

워크플로우 경로(캔버스 파이썬 스텝 → 코드서빙)에서는 **token 은 채팅에 보이는데 그 뒤로 아무것도
안 나왔다.** 코드에서 확인한 원인은 둘이다.

1. 번역 마지막 스텝(`final/workflow/sfr018_translate_02_translate.py`)의 `event: result`
   데이터에 **`text` 가 없다.** 기본 채팅은 `text` 만 그리는데, 우리 result 는 전용 UI 용
   `original_text`·`translated_text` 만 싣는다. 오류 경로(`finish_with_error`)도 `text` 없이
   `error` 만 실어서 오류가 나도 빈 화면으로 끝난다(006 은 `text` 를 실어서 괜찮다).
2. 코드서빙의 SSE 프레임 모양이 젠포탈과 다르다. 기존 `/translate/stream` 은
   `data: {"type": "delta", "text": …}` — 워크플로우 스텝만 읽는 내부 형식이다. 직접 호출 방식으로
   **동작이 확인된 다른 단위**는 `data: {"event": "complete", "data": {…}}` 처럼 **`event`·`data`
   두 키를 가진 JSON 한 줄**을 보낸다.

그래서 워크플로우 스텝을 빼고 젠포탈 → 코드서빙 `POST /chat` 직접 호출로 바꾼다.
번역을 먼저 옮겨서 시범으로 써 보고 동작을 확인한 뒤(2026-10-08) 글다듬이·FAQ·006 에도 같은 방식을 적용했다.

## 들어 있는 것

`SFR-018-translate/` — 번역 코드서빙 **전체 사본**(`final/SFR-018-translate/request` + `prompt/`)에
아래 두 파일과 `main.py` 수정을 더한 것. 이 폴더 하나를 그대로 등록하면 된다.

| 파일 | 내용 |
|---|---|
| `chat_input.py` | `{question, stream}` 해석. `question` 안의 옵션 파싱 |
| `chat_api.py` | `POST /chat` 라우트. 스트리밍은 SSE, 아니면 JSON |
| `main.py` | `app.include_router(chat_router)` 추가. **`if __name__ == "__main__"` 블록을 파일 끝으로 옮겼다** |

> ⚠ `final/SFR-018-translate/request/main.py` 에는 그 `__main__` 블록이 **파일 중간**에 있다.
> `python main.py` 로 띄우면 그 아래의 `/prompts`·`/translate/stream`·`/translate/finalize` 가
> 등록되기 전에 서버가 뜬다. 시작 커맨드가 `uvicorn main:app` 이면 영향이 없다. final 쪽도 파일 끝으로 옮겼다(2026-10-08).

## 요청 계약

```json
{ "question": "target_lang: en\nregister: 문어체\ntitle: 보도자료\n\n번역할 본문…", "stream": true }
```

`question` 안 옵션 — 두 모양을 받는다.

- **머리말 줄**(권장): 맨 앞의 `키: 값`(또는 `키=값`) 줄들. 아는 키가 아닌 줄을 만나면 그 줄부터
  본문이다(본문 첫 줄이 `날짜: …` 여도 먹히지 않는다). 머리말 뒤의 빈 줄이나 `---` 하나는 버린다.
- **JSON 문자열**: `{"target_lang": "en", "text": "본문"}` — 본문 키는 `text`→`markdown`→`body`→`question` 순서로 찾는다.

| 옵션 | 받는 키 | 값 |
|---|---|---|
| 대상 언어 (필수) | `target_lang` `target` `to` `translate_target_lang` `대상언어` | `ko` `en` `zh` `th` `vi` `ru` (한국어 이름도 받는다) |
| 원문 언어 | `source_lang` `source` `from` `translate_source_lang` `원문언어` | 비우면 감지 |
| 문체 | `register` `translate_register` `문체` | `문어체`/`written`, `구어체`/`spoken` |
| 파일명 | `title` `translate_title` | 내려받기 md 이름 |

우선순위: **payload 최상위 키 > question 머리말 > `TRANSLATE_DEFAULT_*` 환경변수.**

**젠포탈이 직접 부르면 값은 전부 `question` 안에 온다**(사용자 확인 2026-10-08). 첨부(`genosUploaded`)는
`question` 안 `[입력된 문서]` 표식 뒤에 붙는다. 표식이 있으면 **그 뒤가 원문**이고, 앞쪽에서는 머리말(옵션)만 읽는다.
표식 뒤에 `<doc>` 태그가 있으면 태그 안만 원문이다. 표식 뒤의 정확한 모양(태그 유무, 문서가 여럿일 때 구분)은 **실물 확인 전**이다.
`stream` 은 `true`/`"true"`/`1` 을 모두 받는다.

## 응답 계약

### `stream: true` → SSE (오류도 HTTP 200 SSE)

```
data: {"event": "heartbeat", "data": {"elapsed_seconds": 0}}  ← 시작 1회 + 조용한 동안 5초마다
data: {"event": "token",    "data": "번역문 조각"}            ← 채팅에 보인다
data: {"event": "token",    "data": "\n\n---\n\n> ⚠ 안내…\n\n[번역 결과 내려받기 (.md)](url)"}
data: {"event": "complete", "data": {"original_text", "translated_text", "download_url", "notice"?}}
data: {"event": "end",      "data": ""}
```

- **채팅에 보이는 글은 token 으로만 나간다**(번역문 + 안내문 + 링크, 오류 문구도 token).
  `complete` 에는 **`text` 를 넣지 않았다** → 값은 전달되지만 채팅에는 다시 그려지지 않는다.
- `original_text`·`translated_text` 는 용어사전 `<mark>` 가 입혀진 사본이다(전용 UI 용).
- 오류: `token`(문구) → `complete` `{"error": {"error_code", "msg"}}` → `end`.
- **heartbeat**: 화면이 진행 표시를 돌린다(사용자가 다른 단위에서 관찰한 동작). **개발가이드에는 없다** —
  PDF 전체와 `archive/genos_files` 참고 코드를 찾아봤지만 `heartbeat`·`elapsed_seconds` 가 없다. 가이드 6.10.4 는
  오히려 "임의로 추가한 이벤트를 화면이 자동으로 처리한다고 가정하지 말라"고 한다. 그래서 끌 수 있게 했다:
  `CHAT_HEARTBEAT_SECONDS`(기본 5, `0` 이면 끈다) · `CHAT_HEARTBEAT_EVENT`(기본 `heartbeat`).
- 이벤트 이름은 젠포탈이 가리지 않는다(사용자 확인). 그래도 환경변수로 바꿀 수 있다: `CHAT_TOKEN_EVENT`(token) · `CHAT_RESULT_EVENT`(complete) ·
  `CHAT_END_EVENT`(end, 빈 값이면 end 프레임을 보내지 않는다).

### `stream: false` → JSON

`{"text", "original_text", "translated_text", "download_url", "notice"?}` — 흘릴 데가 없으므로 `text` 를 싣는다.
오류는 상태코드(400/500/502/504)와 함께 `{"text": 문구, "error": {...}}`.

### 번역 경로

- 스트리밍: `stream_pipeline`(조각 단위 LLM 스트리밍). 구조 보존이 프롬프트에 달려 있어서,
  끝난 뒤 `structure_diff` 로 대조하고 어긋나면 안내문을 붙인다.
  게이트웨이가 스트리밍을 안 받으면 비스트리밍으로 되돌아간다.
- 비스트리밍: `run_markdown_translation_job`(스켈레톤 분해 — 구조를 코드가 보장하는 정본 경로).

## 확인한 것 (2026-10-08, 로컬, LLM·업로드를 가짜로 바꿔 끼움)

스트리밍 정상 / JSON 정상 / JSON 문자열 question / 대상 언어 누락 / 한국어 축 위반(en→ru) /
본문 첫 줄이 `날짜: …` / 전량 실패(스트리밍·비스트리밍) — **8건 모두 기대대로 나왔다.**
추가 확인: heartbeat(시작 1회·대기 중 반복·흐르는 동안 없음·`0` 이면 끔), `[입력된 문서]` 표식(태그 有/無, 사용자 글이 앞/뒤) — 기대대로.
테스트 스크립트는 저장소에 넣지 않았다(세션 scratchpad). `Test/` 그물에는 아직 포함되지 않았다.

## 지금 할 일

- [x] 이벤트 이름 — 젠포탈은 이름을 가리지 않는다(사용자 확인 2026-10-08).
- [x] heartbeat 추가(2026-10-08). **실제 화면에서 진행 표시가 도는지, `{"elapsed_seconds": …}` 가 글자로
      찍히지 않는지 확인 필요.** 찍히면 `CHAT_HEARTBEAT_SECONDS=0`.
- [ ] **실호출 500 (2026-10-08)** — 게이트웨이 로그 `code_serving/767/6071/chat` → 500, 게이트웨이 인가는 ALLOW.
      우리 코드에서 500 은 **`stream` 이 참이 아닐 때만** 난다(스트리밍은 오류도 200 SSE). 후보: ① 젠포탈이 `stream`
      을 안 보냄 ② 새 서빙에 `GENOS_URL`·`GENOS_TOKEN`·`LLM_SERVING_ID` 미설정(`event=llm_config_missing`,
      로컬에서 같은 500 재현) ③ 내부 예외(`event=chat_translate_internal_error`). **코드서빙 컨테이너 로그로 가른다.**
      → **판명**: 실제 요청은 `{"question": "안녕?", "stream": true}` 였고(로컬은 200 SSE), 게이트웨이 로그에
      `ClientConnectorDNSError(host='code-serving-767-6071')` — **리비전 6071 의 서비스가 클러스터에 없다**(미배포·빌드/기동 실패).
      코드 문제가 아니다. `no_pythonstep/` 은 아직 Git 미커밋이라 저장소 배포라면 코드도 없다.
- [ ] **실호출 `ERR-03-00020002` "번역에 실패했습니다" (2026-10-08, 세션 215d87ea…)** — 서빙은 이제 뜬다(200 SSE).
      heartbeat 가 0초 한 번뿐이라 5초 안에 **모든 조각이 비통신·비설정 사유로** 실패했다(`chat_api.py` `_translate_streaming`).
      설정 부재(GENOS_URL·LLM_SERVING_ID)·통신 실패는 다른 문구라 제외. 후보: ① 게이트웨이 4xx — GENOS_TOKEN 틀림(401/403),
      LLM_SERVING_ID 틀림(404), 400 이면 비스트리밍 폴백도 400 ② 5xx 재시도 소진 ③ 200 인데 내용이 빔(`EMPTY_LLM_RESPONSE`,
      추론형 모델이 `delta.content` 대신 다른 키로 보낼 때) ④ `PromptRenderError`. **컨테이너 로그 `chat_translate_failed` 의
      `error_type` 과 `llm_stream_*` 의 `upstream_status` 로 가른다.** 응답 본문까지 보려면 `GENON_DEBUG=1`.
      → **판명**: 로그 `error_type=PromptRenderError`, LLM 은 부르지도 않았다. `prompt_file_missing`·`prompt_variable_missing`
      로그가 **없으므로** 파일 하나가 빠진 게 아니라 **프롬프트 디렉토리 자체를 못 찾았다**(`prompt_loader._read_template` 의
      `isdir` 분기는 로그 없이 세운다). 후보: 기존 번역 서빙 환경변수를 옮기며 `TRANSLATION_PROMPT_DIR` 이 따라와 없는 경로를
      가리킴, 또는 올린 코드에 `prompt/SFR-018_translation/` 이 빠짐. 확인: `GET /prompts`, 컨테이너에서 해당 경로 `ls`.
- [ ] **`complete` 를 채팅에 안 그리는지 실제 화면에서 확인.** 만약 그린다면 이벤트 이름을 바꾸거나 데이터를 줄인다.
- [ ] **등록**: 코드서빙 1개(`no_pythonstep/SFR-018-translate`). 시작 커맨드는 `uvicorn main:app --host 0.0.0.0 --port $PORT`
      (또는 루트 `main.py`). 환경변수는 기존 번역 서빙과 같다(`GENOS_URL`·`GENOS_TOKEN`·`LLM_SERVING_ID`·
      용어사전 `TRANSLATE_GLOSSARY_*` 등) + 필요하면 `TRANSLATE_DEFAULT_*`·`CHAT_*_EVENT`.
- [ ] **젠포탈 → `/chat` 직접 호출 설정** — 컨테이너 서비스 "워크플로우로 사용" 연계를 쓰면 기본 경로가
      `POST /chat` 이다(개발가이드 §6.5, 41쪽). 요청·응답 항목 등록 화면이 실제로 어떻게 생겼는지는 아직 모른다.
- [x] 첨부는 `question` 안 `[입력된 문서]` 뒤로 온다 → 반영(2026-10-08).
- [ ] **첨부가 실린 `question` 실물 한 건 받기** — 표식 뒤에 `<doc>` 태그가 붙는지, 문서가 여럿일 때 어떻게
      이어지는지, 사용자 글이 표식 앞에 오는지 뒤에 오는지. 지금 코드는 앞/뒤 모두 받는다.
- [ ] **대상 언어를 어떻게 받을지** — 값이 전부 question 에 오므로 사용자가 `target_lang: en` 줄을 직접 쳐야 한다.
      화면이 이 줄을 붙여 주지 않으면 `TRANSLATE_DEFAULT_TARGET_LANG` 만 남는다(자연어 "영어로" 는 읽지 않는다 —
      "선택값이 유일한 근거" 결정, `final/CLAUDE.md`).
- [ ] **스캔 쪽 OCR 미지원** — 원문에 `[[GENON_SCAN` 표식이 있으면 지금은 입력 오류로 거절한다
      (워크플로우 경로는 MCP `genon_ocr` 를 불렀다). 필요하면 MCP 호출을 이 서빙에 붙인다.
- [ ] 동작하면: `final/` 에 반영할지 결정(이 폴더는 사본이라 `final/` 과 함께 고쳐야 할 파일이 생긴다),
      `Test/` 에 `/chat` 점검 추가. (글다듬이·FAQ·006 적용은 완료 — 아래 단위별 절)
- [ ] (워크플로우 경로를 계속 쓴다면) `sfr018_translate_02_translate.py` 의 result·`finish_with_error` 에
      `text` 추가 + `Test/check/check_workflow_run.py` `_ALLOWED_KEYS` + `final/docs/FRONT.md` 계약 갱신.

---

## SFR-018-polish (글다듬이) — `SFR-018-polish/`

글다듬이 코드서빙 전체 사본 + `chat_input.py`·`chat_api.py`·`text_polish/guard_client.py`.
워크플로우 스텝 1(원본·톤 정책)·2(다듬기·점검·결과)가 하던 일을 `POST /chat` 하나가 한다.

- 요청: `{"question": "doc_type: 메일\ntone: 격식·정중\ntitle: 안내\n\n본문…", "stream": true}`
  - 옵션 키: `doc_type`/`polish_doc_type`/`문서유형`/`문서종류`, `tone`/`polish_tone`/`톤`/`어조`, `title`/`polish_title`
    (`제목` 은 받지 않는다 — 다듬을 글의 첫 줄 `제목: …` 을 먹는다). 값은 코드·화면 라벨 둘 다.
    기본값 `POLISH_DEFAULT_DOC_TYPE`·`POLISH_DEFAULT_TONE`. 목록 밖 값은 `resolve_policy` 가 기본값으로 대체.
  - `[입력된 문서]` 뒤가 원문(첨부)이고, 사용자가 친 글은 다듬지 않는다.
- 응답: `complete` = `{original_text, polished_text, download_url, doc_type, tone, tone_overridden, notice?}`
  (하이라이트 없음). 링크 문구 `[다듬은 결과 내려받기 (.md)]`. JSON 오류는 400/422/500/502/504 + `{text, error}`.
- 톤 정책은 내장 `resolve_policy`(= `/polish` 와 같은 판정)이고 MCP `genon_lang_policy` 는 부르지 않는다. 톤이 강제되면 안내문 1줄.
- 구조·사실 점검은 MCP `genon_text_guard` 를 직접 부른다(`TEXT_GUARD_MCP_ID`). 실패·미설정이면 점검 없이 결과를 낸다
  (`text_guard_call_failed`/`text_guard_unconfigured` 로그).
- `main.py`: `_prepare_polish` → `_prepare_core`(ErrorCode 반환, 기존 래퍼 유지), `__main__` 블록을 파일 끝으로.
  `error_codes.py` 에 `ERR_INPUT_INVALID`(400)·`ERR_INPUT_SCANNED`(422) 추가.
- 로컬 확인(가짜 LLM·업로드·MCP): 스트리밍/JSON/빈 입력/잘못된 본문/톤 강제/구조 경고/`[입력된 문서]` 태그 유무/
  JSON question/본문 첫 줄 `제목:`/전량 실패/스캔 거절/스트리밍 미지원 폴백/heartbeat 반복·끄기/guard SSE·500·미설정, 기존 `/polish` — 기대대로.

### 지금 할 일 (글다듬이)
- [ ] **등록**: 환경변수 = 기존 글다듬이 서빙 + **`TEXT_GUARD_MCP_ID`** + 필요하면 `POLISH_DEFAULT_*`·`CHAT_*`.
- [ ] 실호출 한 건 — token 흐름, `complete` 를 다시 그리지 않는지, heartbeat 가 글자로 안 찍히는지.
- [ ] 문서유형·톤을 화면이 머리말 줄로 붙여 주는지. 아니면 `POLISH_DEFAULT_*` 만 남는다.
- [ ] 스캔 OCR 미지원 — 필요하면 MCP `genon_ocr` 호출(워크플로우 스텝 1 `_ocr_scanned_pages` 참고).

---

## SFR-018-faq — `SFR-018-faq/`

FAQ 코드서빙 전체 사본에 `faq/chat_input.py`·`faq/chat_api.py` 를 더하고, `faq/main.py` 를 **단위 루트 `main.py`** 로 올린 것.
생성·저장·실패 분류는 기존 라우트와 같은 함수(`generate_faqs_stream`·`_store_and_payload`·`_FAILURE_ERRORS`·
`_display_text`)를 지난다 — `/chat` 과 `/generate` 가 같은 파일을 내려준다. 루트 `main.py` 가 끝에서
`chat_api.install(app, sys.modules[__name__])` 로 자기 모듈을 넘긴다(`chat_api` 가 `main` 을 import 하면 `python main.py` 때 두 번 실린다).

- 요청: `{"question": "faq_count: 5\ntitle: 휴가 FAQ\n\n[입력된 문서]\n<doc>…</doc>", "stream": true}`

| 옵션 | 받는 키 | 값 |
|---|---|---|
| 개수 | `faq_count` `count` `개수` | 비우면 `FAQ_DEFAULT_COUNT`, `FAQ_MAX_COUNT` 로 깎임, 0 이면 오류 |
| 상한 낮추기 | `faq_max_count` `max_count` | 배포 상한 안에서만 |
| 파일명 | `faq_title` `title` `제목` | 내려받기 md 이름 |

- 원문: 최상위 `genosUploaded` > `[입력된 문서]` 뒤(`<doc>` 있으면 태그 안) > 표식 없을 때 본문.
- 세션: 최상위 `socketIOClientId`→`sessionId`→`session_id`(`genos_state` 안 포함). 없으면 Redis 저장만 건너뛴다.
- 응답: token(문답 조각 → 안내문·`[FAQ 내려받기 (.md)](url)`) → `complete {faq_items, download_url, notice?, disclaimer?}`.
  JSON 오류 400/422(근거 미확보)/500/502/504. 오류 코드는 `ERR-03-…`(워크플로우의 `ERR-02-…` 아님).
- 로컬 확인: 스트리밍/JSON, 빈 입력, 개수 0, 개수 미달 안내, 최상위 키 우선, 전량 실패, 스트리밍 미지원 폴백(목록 1회),
  스캔 거절, heartbeat 반복·끔, 잘못된 본문 — 기대대로.

### 지금 할 일 (FAQ)
- [ ] 등록: 루트 `main.py` 자동 실행(또는 `uvicorn main:app --host 0.0.0.0 --port $PORT`). 환경변수 = 기존 FAQ 서빙 + 필요하면 `CHAT_*`.
- [ ] 세션 id 가 오는지 — 안 오면 `POST /download` 옛 경로를 못 쓴다(`download_url` 은 정상).
- [ ] 개수 — 화면이 `faq_count: N` 줄을 붙이지 않으면 늘 기본값.
- [ ] 스캔 OCR 미지원.
- [ ] `complete` 의 `faq_items` 를 채팅이 다시 그리지 않는지 확인.

---

## SFR-006 (템플릿 채우기) — `SFR-006/`

`final/SFR-006/request`(반복 묶음 미커밋분 포함) + `prompt/` 전체 사본에 `POST /chat` 을 더했다.
워크플로우 스텝 셋(context → extract → prefill·commit)을 한 요청 안에서 HTTP 없이 부른다.

| 파일 | 내용 |
|---|---|
| `template_fill/chat_input.py` | `{question, stream}` 해석 — 머리말 옵션·`[입력된 문서]`·세션 id |
| `template_fill/chat_direct.py` | `POST /chat`. 스트리밍은 SSE, 아니면 JSON |
| `template_fill/chat_api.py` | 라우트 몸통을 모듈 함수(`prefill_turn`·`extract_turn`·`commit_turn`)로 꺼냄. 기존 `/chat/*` 동작 동일(`check_chat_turn` 60/60) |
| `main.py`(루트) | 앱 본체 — `template_fill/main.py` 를 한 단계 올렸다. `template_fill.…` 절대 import, `__main__` 블록은 파일 끝 |

- 요청: `{"question": "template_id: abc\nsession_id: …\n\n제목은 A 로 해줘\n[입력된 문서]\n<doc>…</doc>", "stream": true}`
  - 세션: 최상위 `socketIOClientId`→`sessionId`→`session_id`→`chatId`→`chat_id`→`conversationId`→`conversation_id`(+`genos_state`) > 머리말 `session_id`/`sessionId`/`socketIOClientId`/`세션`.
  - 템플릿: 최상위 `template_id`/`template_fill_template_id` > 머리말 `template_id`/`template`/`템플릿` > 세션에 저장된 것 > `TEMPLATE_FILL_DEFAULT_TEMPLATE_ID` > `abc`.
  - `[입력된 문서]` 앞 = 발화(**버리지 않는다** — "이 문서로 채우고 제목은 A" 가 한 턴에 온다), 뒤 = 자동 채움 문서. 발화 값이 문서 값을 이긴다.
- 응답(stream): heartbeat → token(자동 채움 진행 `✔ 항목: 값`) → token(답변+미리보기) →
  `complete {template_id, session_id?, download_url}`(`download_url` 은 다 채웠을 때만) → end.
  JSON: `{text, template_id, session_id?, download_url}`, 오류는 `ApiError` 상태코드 + `{text, error}`.
- **세션이 없으면** 요청을 세우지 않고 이번 턴만 처리한 뒤 "대화 정보를 받지 못해 …" 안내를 붙인다(`event=session_id_missing`).
- 스캔 표식이 있으면 자동 채움만 건너뛰고 안내문을 붙인다(대화는 계속).
- 로컬 확인(가짜 LLM/Redis/업로드) 22/22: 스트리밍 턴·JSON 다음 턴(세션 이어짐·download_url)·세션 없음·머리말 세션·
  템플릿 없음(SSE/JSON)·문서 자동 채움·스캔 표식·heartbeat·본문 오류·기존 `/chat/context`. 워크플로우 스텝 3개 체인도 그대로 돈다.

### 지금 할 일 (006)
- [ ] **세션 id 가 실제로 오는가 (최우선)** — 지금까지 본 직접 호출은 `{question, stream}` 뿐이다. 없으면 매 턴 새 대화가 된다.
      실호출 payload 를 받아 대화 id 키 확인 → 필요하면 `chat_input._SESSION_KEYS` 에 추가. 끝내 안 오면 화면이
      `session_id:` 머리말을 붙이게 하거나 006 은 워크플로우 경로를 유지.
- [ ] 템플릿 선택 — 지금은 머리말/세션/기본값(`abc`)뿐.
- [ ] 다운로드 버튼 — `POST /generate` 를 부르던 배선이 직접 호출 화면에도 있는지. 없으면 `download_url` 만 남는다.
- [ ] 답변+미리보기(마크다운 표·인용)가 token 으로 흐를 때 화면 렌더 확인.
- [ ] 스캔 OCR 미지원.
- [ ] `final/` 반영 시: `chat_api` 모듈 함수 분리 + `chat_direct`·`chat_input` 이관, `Test/` 에 `/chat` 점검 추가.
