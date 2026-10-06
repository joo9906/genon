# final/workflow — GenOS 워크플로우 Python 단계 (area 02)

**파일 1개 = 캔버스 파이썬 스텝 1개.** 각 파일은 자기완결이며, 내용을 통째로 캔버스에
붙여 넣는다.

---

## 스텝 목록

| 순서 | 파일 | 시그니처 | 게이트웨이로 부르는 것 |
|---|---|---|---|
| 006-1 | `sfr006_01_context.py` | `async def run(data) -> dict` | 서빙 `POST /chat/context` |
| 006-2 | `sfr006_02_extract.py` | `async def run(data) -> dict` | 서빙 `POST /chat/extract` |
| 006-3 | `sfr006_03_commit.py` | async generator | 서빙 `POST /chat/prefill/stream`(폴백 `/chat/prefill`) + `POST /chat/commit` |
| 다듬-1 | `sfr018_polish_01_policy.py` | `async def run(data) -> dict` | MCP `lang_policy.resolve_tone` |
| 다듬-2 | `sfr018_polish_02_polish.py` | async generator | 서빙 `POST /polish/stream`(폴백 `/polish`) + MCP `text_guard` ×2 |
| FAQ-1 | `sfr018_faq_01_source.py` | `async def run(data) -> dict` | 서빙 `GET /config` |
| FAQ-2 | `sfr018_faq_02_generate.py` | async generator | 서빙 `POST /generate/stream`(폴백 `/generate`) |
| 번역-1 | `sfr018_translate_01_detect.py` | `async def run(data) -> dict` | MCP `lang_policy.validate_direction` |
| 번역-2 | `sfr018_translate_02_translate.py` | async generator | 서빙 `POST /translate/stream` + `/translate/finalize`(폴백 `/translate/markdown`) + MCP `text_guard` |

---

## 이 디렉토리의 규율 넷

### 1. 파일을 세부 기능별로 쪼개지 않는다

캔버스 파이썬 스텝은 **코드 한 덩어리**로 등록된다. 그래서 로깅 유틸·오류표·게이트웨이
클라이언트가 파일마다 반복된다. **이 중복은 의도한 것이다** — 공용 모듈로 빼면 스텝이
자기완결이 아니게 되어 캔버스에 붙일 수 없다.

같은 이유로 **파일 간 import 이 하나도 없다.** 어떤 파일이든 단독으로 복사해 쓸 수 있다.
대신 같은 이름의 헬퍼는 **같은 코드**여야 한다 — `check_deploy_contract` 의 "사본 일치"
가 스텝마다 본문을 대조한다(독스트링·주석은 보지 않는다).

### 2. 쓰는 패키지는 `httpx` 하나다

워크플로우 이미지에 포함된 것만 쓸 수 있다 (GENOS_RULES §D.3):
`asyncio, httpx, json, datetime, re, opentelemetry.*, GenOS Logger`.

**`lxml`·`redis`·`jinja2` 는 여기 없다.** 셋 다 기본 이미지 변경 요청(11.5.6)에 묶이므로
전부 코드서빙/MCP 쪽에 둔다.

### 3. 중간 스텝은 generator 가 아니다

- **중간 스텝**: `async def run(data) -> dict`. `{**data, ...}` 로 돌려준다.
- **마지막 스텝**: async generator. 토큰 스트리밍 후 **`event: result` 를 1회** yield.

네 시그니처를 섞으면 안 된다 (§D.1). `return` 과 `yield` 를 한 함수에 섞으면 SyntaxError 다.

### 4. 오류는 `data["error"]` 로 흐른다

각 스텝은 첫머리에서 앞 스텝의 `error` 를 확인하고 **있으면 그대로 통과**시킨다 (§A.4).
캔버스에서 `data.error` 로 분기를 걸 수 있다.

> ⚠️ **마지막 스텝이 오류를 사용자에게 말해 준다.** 중간 스텝은 스트리밍을 하지 않으므로,
> 마지막 스텝이 `error` 를 받아 `result` 로 내지 않으면 **화면이 빈 채로 끝난다.**
> 네 마지막 스텝 전부 그 경로를 갖고 있다 (`finish_with_error`).

---

## 스트리밍 규약 (가이드 5.2 / §D.4)

```python
await sio_server.emit(event_name, payload, room=sid)
await asyncio.sleep(0)          # ← 없으면 UI 가 마지막에 한꺼번에 받는다
```

### 서빙이 SSE 로 흘리고 스텝이 중계한다

네 마지막 스텝은 서빙의 스트리밍 라우트를 `_stream_serving` 으로 읽으며 프레임의 `text`
를 그대로 `token` 으로 옮긴다 — 화면에 나갈 글을 스텝이 다시 조립하지 않는다(조립기가
두 벌이 되면 화면에 흐른 글과 내려받은 파일이 갈린다).

- **한 글자도 흘리기 전에 실패하면 비스트리밍 라우트로 되돌아간다.** 스트리밍 라우트가
  없는 서빙 리비전이거나 게이트웨이·프록시가 SSE 를 막는 경우다 — 기능이 통째로 죽으면
  안 된다. 그 경로에서는 결과를 받은 뒤 청크로 잘라 흘린다.
- **흘린 뒤의 실패는 그대로 오류다.** 같은 글을 두 번 뿌리면 사용자는 그것을 결과물로 읽는다.
- **오류가 날 결과는 흘리지 않는다.** 서빙이 보장한다 — 번역 전량 실패·FAQ 기각 항목은
  프레임으로 나가지 않는다. 비스트리밍 경로는 판정(번역 전량 폴백 등)을 끝낸 뒤 흘린다.
  그 앞에서 흘리면 화면에 글을 뿌려 놓고 오류로 갈아엎게 되어 **답이 나왔다가 사라진다.**
  `check_workflow_run` 이 오류 경로에서 토큰이 나오면 FAIL 한다.

비스트리밍 경로의 전송 단위는 글자가 아니라 **청크(32자)**. `_STREAM_CHUNK_CHARS` 로 각
파일에 있고, 긴 글에서는 `_STREAM_MAX_EMITS`(400)가 조각을 키워 **emit 수가 글 길이에
비례하지 않게** 한다. **사본이 4벌**(마지막 스텝 넷)이라 `check_deploy_contract` 가 갈리면
FAIL 한다.

결정적 점검(MCP `text_guard`)은 **먼저 띄워 두고 그 동안** 흘린다 — 순서대로 하면
스트리밍이 순수한 연출이 되고 전체 시간만 늘어난다.

### 무엇을 흘리나

| 스텝 | 흘리는 것 | `event: result` |
|---|---|---|
| `sfr006_03_commit` | 문서 자동 채움 진행 문구(서빙이 짓는다) + 답변·미리보기 | `text` + `download_url` — 전용 UI 가 없어 **채팅이 곧 화면**이다 |
| `sfr018_polish_02_polish` | 다듬은 글(정본) | 원문·다듬은 글 그대로(하이라이트 없음) + `notice` |
| `sfr018_translate_02_translate` | 번역문(정본) | 원문·번역문 `<mark>` 사본으로 **갈아 끼운다** + `notice` |
| `sfr018_faq_02_generate` | 근거 대조를 통과한 문답(서빙이 조립한 마크다운) | `faq_items` 목록 + `notice`·`disclaimer` |

번역은 **정본을 흘린다** — `<mark>` 사본이 아니다. 사본을 흘리면 하이라이트가 스트리밍
중에 이미 나타나 "스트리밍부터 하고 끝나면 한 번에 하이라이트" 라는 요구와 어긋나고,
태그가 조각 경계에서 갈려 부스러기가 남는다. **원시 마크다운이 보이는 것은 허용된
동작**이다.

---

## 환경 변수 (리비전 정보 > 환경 변수 — 11.5.4)

| 이름 | 필요한 스텝 |
|---|---|
| `GENOS_URL` `GENOS_TOKEN` | 전부 |
| `TEMPLATE_FILL_SERVING_ID` | 006-1·2·3 |
| `TEXT_POLISH_SERVING_ID` | 다듬-2 |
| `FAQ_SERVING_ID` | FAQ-1·2 |
| `TRANSLATION_SERVING_ID` | 번역-2 |
| `TEXT_GUARD_MCP_ID` | 다듬-2, 번역-2 |
| `LANG_POLICY_MCP_ID` | 다듬-1, 번역-1 |
| (선택) `POLISH_DEFAULT_DOC_TYPE` `POLISH_DEFAULT_TONE` | 다듬-1 — 화면이 안 준 값의 기본값 |
| (선택) `TRANSLATE_DEFAULT_TARGET_LANG` `TRANSLATE_DEFAULT_SOURCE_LANG` `TRANSLATE_DEFAULT_REGISTER` | 번역-1 — 화면이 안 준 값의 기본값 |

**첨부 원문은 전처리기 산출물 `genosUploaded` 하나다.** FAQ-1·번역-1 은 업로드 원본을
MCP 로 다시 파싱하지 않는다 — 같은 문서를 두 번 파싱하게 되고, 캔버스 변수가 업로드 원본
경로를 담아 준다는 보장도 없다. 첨부용 전처리기는 파싱만 하고 **청킹하지 않아야** 한다
(검색용 조문·표 머리말이 섞이면 번역이 원문에 없던 머리말을 번역해 결과물에 싣고, FAQ 는
그 머리말을 근거 대조에 쓴다).

**시크릿 기본값은 없다.** 누락되면 각 스텝이 `CONFIG_MISSING`(`ERR-02-00020003`)으로
사용자에게 "서비스 설정이 완료되지 않았습니다" 를 내고 끝낸다 — 값을 로그·응답에
남기지 않는다 (§C).

`GENOS_URL` 이 이미 `/api/gateway` 로 끝나도 되고 아니어도 된다. 각 파일의
`_gateway_base()` 가 흡수한다 — f-string 으로 직접 조립하면 prefix 를 빠뜨려 게이트웨이를
지나지 않는다.

---

## MCP 호출 형식

`{GENOS_URL}/api/gateway/mcp/<id>/mcp` 에 JSON-RPC `tools/call` 을 보내고
`result.content[].text` 를 JSON 으로 파싱한다 (§H + MCP 표준). 부르는 스텝마다 `_mcp_call`
이 그 일을 한다(다듬-1·2, 번역-1·2).

- **Accept 헤더에 `application/json`·`text/event-stream` 을 둘 다 싣는다**(`_MCP_HEADERS`).
  MCP 스트리머블 HTTP 서버는 POST 본문을 읽기 전에 Accept 헤더를 보고, 둘을 다 열거하지
  않으면 도구를 부르지도 않고 `406 Not Acceptable` 로 끊는다(httpx 기본값은 `Accept: */*`).
- 서버가 SSE 프레임으로 답하는 경우를 `_decode_body` 가 해석한다.
- `Test/check/check_workflow_run.py` 의 `_check_mcp_transport` 가 지킨다.

---

## 아직 확인하지 못한 것

- **MCP 상태 유지 모드.** 서버가 상태 유지 모드로 떠 있으면 `initialize` →
  `Mcp-Session-Id` 핸드셰이크가 필요하고 `400 Missing session ID` 로 실패한다. 지금은
  `tools/call` 한 번만 보낸다 — 상태 없는 모드를 전제한다. 고칠 자리는 `_mcp_call` 이다.
- **워크플로우 스텝 간 `data` 크기 한도.** 문서 본문(`polish_source_text`,
  `translate_source_text`, `faq_source_text`)을 스텝 사이로 넘긴다. 큰 문서에서
  캔버스가 이를 어떻게 다루는지 미확인이다. 한도에 걸리면 본문 대신 **핸들**(세션 키)만
  넘기고 코드서빙이 다시 읽는 형태로 바꿔야 한다.
- **번역 스텝 2개는 캔버스에 등록된 적이 없다.**
