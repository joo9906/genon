# onprem/workflow — GenOS 워크플로우 Python 단계 (area 02)

**파일 1개 = 캔버스 파이썬 스텝 1개.** 각 파일은 자기완결이며, 내용을 통째로 캔버스에
붙여 넣는다.

---

## 스텝 목록

| 순서 | 파일 | 시그니처 | 게이트웨이로 부르는 것 |
|---|---|---|---|
| 006-1 | `sfr006_01_context.py` | `async def run(data) -> dict` | 서빙 `POST /chat/context` |
| 006-2 | `sfr006_02_extract.py` | `async def run(data) -> dict` | 서빙 `POST /chat/extract` |
| 006-3 | `sfr006_03_commit.py` | async generator | 서빙 `POST /chat/commit` |
| 다듬-1 | `sfr018_polish_01_policy.py` | `async def run(data) -> dict` | MCP `lang_policy.resolve_tone` |
| 다듬-2 | `sfr018_polish_02_polish.py` | async generator | 서빙 `POST /polish` + MCP `text_guard` ×3 |
| FAQ-1 | `sfr018_faq_01_source.py` | `async def run(data) -> dict` | MCP `hwpx_text` + 서빙 `GET /config` |
| FAQ-2 | `sfr018_faq_02_generate.py` | async generator | 서빙 `POST /generate` |
| 번역-1 | `sfr018_translate_01_detect.py` | `async def run(data) -> dict` | MCP `hwpx_text` + MCP `lang_policy.validate_direction` |
| 번역-2 | `sfr018_translate_02_translate.py` | async generator | 서빙 `POST /translate/markdown` + MCP `text_guard` |

---

## 이 디렉토리의 규율 넷

### 1. 파일을 세부 기능별로 쪼개지 않는다

캔버스 파이썬 스텝은 **코드 한 덩어리**로 등록된다. 그래서 로깅 유틸·오류표·게이트웨이
클라이언트가 파일마다 반복된다. **이 중복은 의도한 것이다** — 공용 모듈로 빼면 스텝이
자기완결이 아니게 되어 캔버스에 붙일 수 없다.

같은 이유로 **파일 간 import 이 하나도 없다.** 어떤 파일이든 단독으로 복사해 쓸 수 있다.

### 2. 쓰는 패키지는 `httpx` 하나다

워크플로우 이미지에 포함된 것만 쓸 수 있다 (GENOS_RULES §D.3):
`asyncio, httpx, json, datetime, re, opentelemetry.*, GenOS Logger`.

**`lxml`·`redis`·`jinja2` 는 여기 없다.** 예전 `run_chat.py` 들이 그 셋을 로컬 import
하고 있었고 그게 기본 이미지 변경 요청(11.5.6)에 묶여 있던 원인이다. 지금은 전부
코드서빙/MCP 쪽에 있다.

### 3. 중간 스텝은 generator 가 아니다

- **중간 스텝**: `async def run(data) -> dict`. `{**data, ...}` 로 돌려준다.
- **마지막 스텝**: async generator. 토큰 스트리밍 후 **`event: result` 를 1회** yield.

네 시그니처를 섞으면 안 된다 (§D.1). `return` 과 `yield` 를 한 함수에 섞으면 SyntaxError 다.

### 4. 오류는 `data["error"]` 로 흐른다

각 스텝은 첫머리에서 앞 스텝의 `error` 를 확인하고 **있으면 그대로 통과**시킨다 (§A.4).
캔버스에서 `data.error` 로 분기를 걸 수 있다.

> ⚠️ **마지막 스텝이 오류를 사용자에게 말해 준다.** 중간 스텝은 스트리밍을 하지 않으므로,
> 마지막 스텝이 `error` 를 받아 문구를 스트리밍하고 `result` 를 내지 않으면 **화면이 빈 채로
> 끝난다.** 세 마지막 스텝 전부 그 경로를 갖고 있다 (`finish_with_error`).

---

## 스트리밍 규약 (가이드 5.2 / §D.4)

```python
await sio_server.emit(event_name, payload, room=sid)
await asyncio.sleep(0)          # ← 없으면 UI 가 마지막에 한꺼번에 받는다
```

전송 단위는 글자가 아니라 **청크(32자)**. `_STREAM_CHUNK_CHARS` 로 각 파일에 있다.

> **실시간 토큰 스트리밍이 아니다** — 이전 구현도 그랬다. LLM 응답을 **전부 받은 뒤**
> 청크로 잘라 emit 한다. 그래서 LLM 호출을 코드서빙으로 내려도 UI 동작이 달라지지 않는다.
> 진짜 토큰 스트리밍이 필요해지면 코드서빙이 SSE 를 내고 이 스텝이 중계해야 하는데,
> 게이트웨이가 스트리밍 응답을 통과시키는지 **확인되지 않았다.**

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
| `HWPX_TEXT_MCP_ID` | FAQ-1, **번역-1** |
| `LANG_POLICY_MCP_ID` | 다듬-1, 번역-1 |

**번역-1 이 이 표에 늦게 들어왔다** (2026-08-14). `POST /translate/hwpx` 는 처음부터
있었는데 이 스텝이 `genosUploaded`(전처리기 산출물)만 읽어서, 캔버스로 hwpx 를 올리면
**표 안 수치가 깨지는 경로**로 번역되고 있었다. 지금은 `translate_hwpx_path` 가 있으면
FAQ-1 과 **같은 도구·같은 폴백**을 탄다 — 없거나 실패하면 전처리기 산출물로 떨어지고
그 사실을 로그에 남긴다(예전에는 그게 기본값이라 흔적조차 없었다).

**시크릿 기본값은 없다.** 누락되면 각 스텝이 `CONFIG_MISSING`(`02-00020003`)으로
사용자에게 "서비스 설정이 완료되지 않았습니다" 를 내고 끝낸다 — 값을 로그·응답에
남기지 않는다 (§C).

`GENOS_URL` 이 이미 `/api/gateway` 로 끝나도 되고 아니어도 된다. 각 파일의
`_gateway_base()` 가 흡수한다 — f-string 으로 직접 조립하면 prefix 를 빠뜨린다
(018 두 단위가 실제로 그래서 게이트웨이를 지나지 않고 있었다).

---

## 아직 확인하지 못한 것

- **MCP 호출 형식.** `{GENOS_URL}/api/gateway/mcp/<id>/mcp` 에 JSON-RPC `tools/call` 을
  보내고 `result.content[].text` 를 JSON 으로 파싱한다 (§H + MCP 표준). 게이트웨이가
  JSON-RPC 를 그대로 통과시키는지는 **실물로 확인해야 한다.** 형식이 다르면 각 파일의
  `_mcp_call` 한 곳만 고치면 된다.
- **워크플로우 스텝 간 `data` 크기 한도.** 문서 본문(`polish_source_text`,
  `translate_source_text`, `faq_source_text`)을 스텝 사이로 넘긴다. 큰 문서에서
  캔버스가 이를 어떻게 다루는지 미확인이다. 한도에 걸리면 본문 대신 **핸들**(세션 키)만
  넘기고 코드서빙이 다시 읽는 형태로 바꿔야 한다.
- **번역 02 스텝 2개는 신규다.** 캔버스에 등록된 적이 없다.
