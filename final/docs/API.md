# API.md — 코드서빙 네 단위의 HTTP 요청·응답

코드서빙(영역 03) 네 배포 단위의 **모든 HTTP 라우트**를 코드 기준으로 적는다. 프론트가 소켓으로
받는 값(워크플로우 `token`·`pythonstep_result`)은 `FRONT.md` 가 정본이고, 여기는 서버가
실제로 받고 내는 계약 전체다. 코드와 이 문서가 다르면 **코드가 맞다** — 고친 쪽을 함께 고친다.

| 단위 | 배포 단위 이름 | 코드 위치 |
|---|---|---|
| [글다듬이](#글다듬이-sfr-018-polish) | `SFR-018_text_polish` | `final/SFR-018-polish/request/` |
| [번역](#번역-sfr-018-translate) | `SFR-018_translation` | `final/SFR-018-translate/request/` |
| [FAQ](#faq-sfr-018-faq) | `SFR-018_faq` | `final/SFR-018-faq/request/` |
| [템플릿 채우기](#템플릿-채우기-sfr-006) | `SFR-006_template_fill` | `final/SFR-006/request/` |

**네 단위 공통**

- 오류 응답 바디는 `{"error_code": "ERR-03-<공통코드>", "msg": "<고정 한국어 안내문>"}` 이다
  (단위별 예외는 각 절 "공통"). 분류는 `error_code` 뒤 8자리로 한다.
- **요청 본문 검증 실패(Pydantic)는 위 모양이 아니다.** 네 단위 모두 `RequestValidationError`
  핸들러가 없어 FastAPI 기본 `422 {"detail": [...]}` 이 나간다.
- 관리자 라우트(`/prompts/reload`, `/glossary/reload` 등)는 `X-Admin-Token` 헤더를 본다.
  토큰 환경변수가 비어 있으면 검사하지 않는다(기동 로그에 경고).

---

## 글다듬이 (SFR-018-polish)

### 공통

| 항목 | 값 |
|---|---|
| 진입점 | `final/SFR-018-polish/request/main.py` (저장소 루트 `main.py` — 가이드 6.2 자동 실행 경로) |
| 앱 | `FastAPI(title="sfr018-text-polish", version="1.0.0")` |
| 기동 | `python main.py` → `uvicorn.run(app, host="0.0.0.0", port=$PORT)` (`PORT` 기본 `8080`) |
| 베이스 경로 | 접두어 없음. 라우트가 앱 루트에 바로 붙는다 |
| 상태 | 없음 (Redis 미사용). `/download` 는 화면이 보낸 본문을 인코딩만 한다 |
| 인증 | 없음. `/policies/reload`·`/prompts/reload` 도 토큰을 요구하지 않는다 |
| 라우트 수 | 10 (`GET /` 와 `GET ""` 를 따로 셈) |

**공통 오류 바디** (`_error_response`) — 상태코드는 `ErrorCode.http_status` 가 정한다. `detail` 은 싣지 않는다.

```json
{ "error_code": "ERR-03-00020003", "msg": "다듬을 문서나 텍스트를 입력해 주세요." }
```

응답 바디에는 `error_type`·`retryable` 이 없다(로그에만 남는다). 같은 `error_code` 를 여러 원인이 공유하므로 원인 구분은 HTTP 상태와 `msg` 로 한다.

**오류 코드 표** (`text_polish/error_codes.py`, 영역코드 `03`)

| 상수 | HTTP | `error_code` | `error_type` (로그) | retryable | `msg` |
|---|---|---|---|---|---|
| `ERR_UPSTREAM_TIMEOUT` | 504 | `ERR-03-00020001` | `POLISH_UPSTREAM_TIMEOUT` | true | 문장 다듬기 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_UPSTREAM_EXECUTION` | 502 | `ERR-03-00020002` | `POLISH_UPSTREAM_EXECUTION_FAILED` | true | 문장 다듬기 결과를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_INPUT_EMPTY` | 400 | `ERR-03-00020003` | `POLISH_INPUT_EMPTY` | false | 다듬을 문서나 텍스트를 입력해 주세요. |
| `ERR_INPUT_TOO_LONG` | 422 | `ERR-03-00020003` | `POLISH_INPUT_TOO_LONG` | false | 문서가 너무 깁니다. 나누어 요청해 주세요. |
| `ERR_INTERNAL` | 500 | `ERR-03-00020003` | `POLISH_INTERNAL_UNCLASSIFIED` | false | 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_CONFIG_MISSING` | 500 | `ERR-03-00020003` | `POLISH_CONFIG_MISSING` | false | 서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요. |

**바디 검증 실패** — 이 단위에는 `RequestValidationError` 핸들러가 없다. Pydantic 제약(`title` 200자, `extra_instruction` 2000자 초과, 필드 타입 불일치, JSON 아님)에 걸리면 FastAPI 기본 응답 `422 {"detail": [...]}` 가 나간다 — 위 `{error_code, msg}` 모양이 아니다.

**입력 상한** — `Config.MAX_INPUT_CHARS` = 환경변수 `POLISH_MAX_INPUT_CHARS` (기본 `200000`자). `/polish`·`/polish/stream`·`/download` 가 같은 값을 본다.

---

### GET /health

| 항목 | 값 |
|---|---|
| 용도 | 상태 확인 프로그램용 고정 응답 |
| 호출자 | GenOS 상태 확인 |
| 요청 | 없음 |
| 성공 | `200`, `application/json` — `{"status": "ok"}` |
| 오류 | 없음 |

### GET / , GET ""

| 항목 | 값 |
|---|---|
| 용도 | 서비스 이름과 엔드포인트 목록 (게이트웨이가 경로 없이 베이스를 칠 때 대비해 둘 다 등록) |
| 호출자 | 확인 안 됨 |
| 요청 | 없음 |
| 성공 | `200`, `application/json` |
| 오류 | 없음 |

```json
{ "service": "sfr018-text-polish",
  "endpoints": ["/polish", "/policies", "/policies/reload", "/prompts", "/prompts/reload", "/download"] }
```

`endpoints` 목록에 `/polish/stream`·`/health` 는 없다(코드 상수 그대로).

### GET /policies

| 항목 | 값 |
|---|---|
| 용도 | 문서유형·톤 선택지 (화면 드롭다운). 출처는 `tone_presets.py` 표 하나 |
| 호출자 | 프론트 |
| 요청 | 없음 |
| 성공 | `200`, `application/json` |
| 오류 | 없음 (라우트에 오류 분기가 없다) |

| 필드 | 타입 | 설명 |
|---|---|---|
| `doc_types[]` | array | 문서유형 목록 |
| `doc_types[].code` | string | `email` · `post` · `customer_notice` · `debt_reason` · `reviewer_opinion` |
| `doc_types[].label` | string | 화면 라벨 |
| `doc_types[].forced_tone` | bool | 강제 톤이 걸려 있고 그 톤이 표에 있으면 `true` |
| `doc_types[].allowed_tones` | string[] | 보내면 그대로 적용되는 톤. 비지 않는다 (`resolve_policy` 로 파생) |
| `tones[]` | array | `{code, label}` — `polite` 격식·정중 · `friendly` 친절·안내 · `clear` 명확·간결 · `objective` 사실·객관 |
| `default_doc_type` | string | `"email"` |
| `default_tone` | string | `"polite"` |

```json
{ "doc_types": [{"code": "debt_reason", "label": "채무 및 연체발생 사유", "forced_tone": true, "allowed_tones": ["objective"]}],
  "tones": [{"code": "polite", "label": "격식·정중"}],
  "default_doc_type": "email", "default_tone": "polite" }
```

### POST /policies/reload

| 항목 | 값 |
|---|---|
| 용도 | 프롬프트 라이브러리 캐시를 비운 뒤 `GET /policies` 와 **같은 응답**을 낸다 (`POST /prompts/reload` 의 별칭 성격) |
| 호출자 | 관리자 |
| 요청 | 바디 없음, 인증 없음 |
| 성공 | `200`, `application/json` — `GET /policies` 와 동일한 모양 |
| 오류 | 없음 |

### GET /prompts

| 항목 | 값 |
|---|---|
| 용도 | 프롬프트를 라이브러리와 파일 중 어디서 받았는지 이름별로. 본문은 싣지 않는다 |
| 호출자 | 관리자 |
| 요청 | 없음 |
| 성공 | `200`, `application/json` — `{"prompts": [...]}` |
| 오류 | 없음 |

| `prompts[]` 필드 | 타입 | 설명 |
|---|---|---|
| `name` | string | 프롬프트 이름 (`system_<tone>`, `doc_type_<code>`, `POLISH_PROMPT_IDS` 의 이름 등) |
| `configured` | bool | `POLISH_PROMPT_IDS` 에 ID 가 있는가 |
| `prompt_id` | string | 설정된 ID. 없으면 `""` |
| `source` | string | `prompt_library` (본문을 받음) / `file` |
| `reason` | string | `prompt_library` · `not_configured` · `fetch_failed` · `fetch_failed_<HTTP상태>` · `api_error` · `empty_body` |

```json
{ "prompts": [{"name": "system_polite", "configured": true, "prompt_id": "123",
               "source": "file", "reason": "fetch_failed_404"}] }
```

### POST /prompts/reload

| 항목 | 값 |
|---|---|
| 용도 | 프롬프트 캐시를 강제로 다시 읽고 `GET /prompts` 와 같은 모양을 돌려준다 |
| 호출자 | 관리자 |
| 요청 | 바디 없음, 인증 없음 |
| 성공 | `200`, `application/json` — `{"prompts": [...]}` |
| 오류 | 없음 |

### POST /polish

| 항목 | 값 |
|---|---|
| 용도 | 문서유형·톤 정책에 맞춰 본문을 다듬고(비스트리밍), 결과 md 를 CDN 에 올린 링크와 함께 돌려준다 |
| 호출자 | 워크플로우 스텝 `sfr018_polish_02_polish` (스트리밍 실패 시 폴백), SFR-006 `polish_client.py` |
| 요청 | `application/json` — `PolishRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `text` | string | 사실상 필수 | `""` | 앞뒤 공백 제거 후 비면 `ERR_INPUT_EMPTY`, `MAX_INPUT_CHARS` 초과면 `ERR_INPUT_TOO_LONG` (자르지 않는다) |
| `doc_type` | string | 아니오 | `""` | 표에 없거나 비면 `email` 로 대체 (오류 아님) |
| `tone` | string | 아니오 | `""` | 옛 `report` → `clear`. 비거나 허용 밖이면 허용 목록 첫 톤 또는 `polite`. 강제군이면 강제 톤 |
| `title` | string | 아니오 | `""` | `max_length=200`. 업로드 파일명 본체 (비면 `글다듬이결과`) |
| `extra_instruction` | string | 아니오 | `""` | `max_length=2000`. 시스템 프롬프트의 문서유형 지시문 **뒤**에 잇는다 |

**성공** — `200`, `application/json`

| 필드 | 타입 | 설명 |
|---|---|---|
| `polished_text` | string | 다듬은 본문 (정본, `<mark>` 없음). 실패한 조각 자리는 원문 그대로 |
| `download_url` | string | 결과 md presigned URL. 업로드 미설정·실패면 **빈 문자열 `""`** |
| `doc_type` | string | 실제 적용된 문서유형 코드 |
| `tone` | string | 실제 적용된 톤 코드 |
| `tone_overridden` | bool | 요청 톤이 정책으로 대체됐는가 |
| `chunk_count` | int | 다듬기에 쓴 조각 수 |
| `failed_chunk_count` | int | 실패해 원문으로 둔 조각 수 (스텝의 부분 실패 안내문 근거) |

```json
{ "polished_text": "…", "download_url": "https://…/글다듬이결과.md", "doc_type": "email",
  "tone": "polite", "tone_overridden": false, "chunk_count": 3, "failed_chunk_count": 0 }
```

업로드 파일: `<safe_stem(title)>.md`, `text/markdown; charset=utf-8`, UTF-8 BOM + CRLF.

**오류** — 부분 실패는 성공 응답이다. 전량 실패(다듬어진 조각이 하나도 없음)만 오류.

| HTTP | `error_code` | 원인 (`error_type`) |
|---|---|---|
| 400 | `ERR-03-00020003` | `POLISH_INPUT_EMPTY` — `text` 공백뿐 |
| 422 | `ERR-03-00020003` | `POLISH_INPUT_TOO_LONG` — 입력 상한 초과 |
| 422 | — | FastAPI 기본 `{"detail": [...]}` — `title`/`extra_instruction` 길이 초과 등 |
| 500 | `ERR-03-00020003` | `POLISH_INTERNAL_UNCLASSIFIED` — 정책 키 누락(`policy_key_missing`), 프롬프트 렌더 실패(`prompt_render_failed`), 예상 밖 예외 |
| 500 | `ERR-03-00020003` | `POLISH_CONFIG_MISSING` — `GENOS_URL`/`LLM_SERVING_ID` 부재로 전량 실패 |
| 504 | `ERR-03-00020001` | `POLISH_UPSTREAM_TIMEOUT` — 전량 실패, 통신 오류 |
| 502 | `ERR-03-00020002` | `POLISH_UPSTREAM_EXECUTION_FAILED` — 전량 실패, 그 밖 |

### POST /polish/stream

| 항목 | 값 |
|---|---|
| 용도 | `/polish` 와 같은 처리를 하되 다듬어지는 대로 SSE 로 흘리고, 마지막 프레임에 `/polish` 와 같은 본문을 준다 |
| 호출자 | 워크플로우 스텝 `sfr018_polish_02_polish` (`_POLISH_STREAM_PATH`) |
| 요청 | `/polish` 와 동일 (`PolishRequest`) |

**흘리기 전 실패** — 입력 검증·정책·프롬프트 렌더 단계 오류(`POLISH_INPUT_EMPTY` 400, `POLISH_INPUT_TOO_LONG` 422, `POLISH_INTERNAL_UNCLASSIFIED` 500)는 SSE 가 아니라 **`/polish` 와 같은 JSON 오류**로 나간다. 바디 검증 422 도 같다.

**성공 시작** — `200`, `Content-Type: text/event-stream`, 헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no`. 프레임은 `data: <JSON>\n\n` 한 줄씩 (`ensure_ascii=False`). `event:` 줄은 없다.

| 프레임 `type` | 필드 | 설명 |
|---|---|---|
| `delta` | `text` | 흘릴 글 조각. 이어붙이면 화면 본문 |
| `done` | `/polish` 성공 필드 전부 + `type`, `stream_diverged`(bool), `stream_fallback`(bool) | 종료 프레임 (성공). `polished_text` 가 정본 |
| `error` | `error_code`, `msg` | 종료 프레임 (실패) |

- `stream_diverged` — 흘린 뒤 끊긴 조각이 있어 화면에 나간 글과 정본(`polished_text`)이 다르다.
- `stream_fallback` — 게이트웨이가 스트리밍을 받지 않아(한 글자도 안 흘린 상태) 서빙이 비스트리밍으로 다시 다듬었다. 이때 결과는 `delta` 한 덩어리로 나간다.
- 스트림 시작 후의 실패는 HTTP 상태가 이미 200 이므로 **`error` 프레임**으로만 온다: 전량 실패 시 `ERR-03-00020001`/`ERR-03-00020002`/`ERR-03-00020003`(`POLISH_CONFIG_MISSING`) — 위 `/polish` 매핑과 같은 표(`_outcome_error_code`). 예상 밖 예외는 `ERR_INTERNAL`(`ERR-03-00020003`, 요청을 처리하지 못했습니다…).
- 프레임은 `done` 또는 `error` 하나로 끝나고 스트림이 닫힌다. 클라이언트가 끊으면 서버 작업을 취소한다.

```
data: {"type": "delta", "text": "안녕하십니까. "}

data: {"type": "done", "polished_text": "…", "download_url": "", "doc_type": "email", "tone": "polite", "tone_overridden": false, "chunk_count": 1, "failed_chunk_count": 0, "stream_diverged": false, "stream_fallback": false}
```

### POST /download

| 항목 | 값 |
|---|---|
| 용도 | 화면이 들고 있는 본문을 마크다운(.md) 파일로 내려준다. 본문은 손대지 않는다 (`download_url` 폴백) |
| 호출자 | 프론트 (`download_url` 이 비었을 때 폴백) |
| 요청 | `application/json` — `DownloadRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `text` | string | 둘 중 하나 | `""` | 내려받을 본문 |
| `polished_text` | string | 둘 중 하나 | `""` | `text` 의 별칭 (`/polish` 응답 필드 이름). `text` 가 비었을 때만 쓴다 |
| `title` | string | 아니오 | `""` | `max_length=200`. 파일명 본체 (비면 `글다듬이결과`) |

**성공** — `200`, 바이너리

| 항목 | 값 |
|---|---|
| `Content-Type` | `text/markdown; charset=utf-8` |
| `Content-Disposition` | `attachment; filename*=UTF-8''<퍼센트 인코딩된 stem>.md` (`filename=` 없음) |
| 본문 | UTF-8 BOM + CRLF 로 통일한 원문 |
| 파일명 규칙 | 윈도우 금지문자 `\/:*?"<>|`·제어문자 제거, 공백 접기, 80자, 앞뒤 `.`/공백 제거 |

**오류**

| HTTP | `error_code` | 원인 |
|---|---|---|
| 400 | `ERR-03-00020003` | `POLISH_INPUT_EMPTY` — 본문 공백뿐 |
| 422 | `ERR-03-00020003` | `POLISH_INPUT_TOO_LONG` — `MAX_INPUT_CHARS` 초과 |
| 422 | — | FastAPI 기본 `{"detail": [...]}` — `title` 200자 초과 등 |

---

## 번역 (SFR-018-translate)

코드 위치: `final/SFR-018-translate/request/` — 라우트는 `main.py`, 요청 모델·응답 조립은 `api_contract.py`, 용어사전 적재는 `translation_pipeline/common/glossary_store.py`.

### 공통

| 항목 | 값 |
|---|---|
| 앱 | FastAPI `title="office-translation-service"` |
| 베이스 경로 | 앱 안에는 접두 경로가 없다. GenOS 코드서빙 게이트웨이 아래 어느 경로에 붙는지는 코드로 확인 안 됨 |
| 기동 | 저장소 루트 `main.py` 의 `__main__` 블록이 `uvicorn.run(app, host="0.0.0.0", port=$PORT)` (기본 8080). 시작 커맨드로 등록할 때는 `uvicorn main:app --host 0.0.0.0 --port $PORT` (`final/docs/SERVING_REGISTRY.md`) |
| 상태 | 무상태. Redis·세션을 쓰지 않는다. 내려받기는 화면이 본문을 되돌려 보낸다 |
| 기동 시 하는 일 | lifespan 에서 용어사전을 한 번 적재한다(실패해도 기동은 계속). `TRANSLATE_ADMIN_TOKEN` 이 비어 있으면 `event=admin_token_missing` 경고를 남긴다 |

#### 공통 오류 바디

코드가 직접 내는 오류는 전부 같은 모양이다 (`api_contract.input_error_response` / `internal_error_response`).

```json
{ "error_code": "ERR-03-00020003", "msg": "입력값을 확인해 주세요." }
```

| 상수 (`error_codes.py`) | HTTP | `error_code` | `error_type` (로그 전용) | `msg` |
|---|---|---|---|---|
| `ERR_INPUT` | 400 | `ERR-03-00020003` | `TRANSLATION_INPUT_INVALID` | 라우트마다 고정 한국어 안내문 (아래 각 라우트) |
| `ERR_INTERNAL` | 500 | `ERR-03-00020003` | `INTERNAL_UNCLASSIFIED` (로그에는 예외 클래스명) | `요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.` |
| (관리자 거부) | 403 | `ERR-03-00020003` | — (상수 없음, 로그 없음) | 라우트별 고정 문구 |

- `error_type` 은 응답에 실리지 않는다. 로그에만 남는다.
- `ERR_UPSTREAM_TIMEOUT`(504, `ERR-03-00020001`)·`ERR_UPSTREAM_EXECUTION`(502, `ERR-03-00020002`)·`ERR_RESPONSE_PARSE`(500)는 `error_codes.py` 에 정의돼 있지만 **어느 라우트도 HTTP 응답으로 내지 않는다.** LLM 실패는 HTTP 오류가 아니라 200 응답의 `translation_error` 문자열로 나간다(아래 "번역 실패 표시").
- **Pydantic 검증 실패는 FastAPI 기본 422** 이고 바디는 `{"detail": [...]}` 이다. 이 단위에는 `RequestValidationError` 핸들러가 없어 `{error_code, msg}` 모양이 아니다(필수 필드 누락, `min_length`/`max_length` 위반, multipart 필수 필드 누락이 여기에 해당).

#### 인증

| 대상 | 방식 |
|---|---|
| 번역·내려받기·조회 라우트 | 호출자 인증 없음 |
| `POST /glossary/reload`, `POST /prompts/reload` | 헤더 `x-admin-token`. `TRANSLATE_ADMIN_TOKEN` 이 설정돼 있을 때만 일치를 검사하고, 비어 있으면 검사하지 않는다 |

#### 번역 실패 표시 (`translation_error`)

LLM 이 실패한 유닛은 **원문이 그대로 남고** 응답은 200 이다. 실패 여부는 `translation_error` 와 `stats.failed_unit_count` 로 가린다.

| 경로 | 값 |
|---|---|
| `/translate`·`/translate/markdown`·`/translate/hwpx` | `""`(전량 성공) 또는 마지막 실패의 `error_type` — `CONFIG_MISSING`(LLM 설정 부재), `EMPTY_INPUT`, 예외 클래스명(예: `ReadTimeout`), 사유가 없으면 `TRANSLATION_PARTIAL_FAILURE`. 부분 실패와 전량 실패를 이 값으로는 가르지 않는다 — `stats.failed_unit_count == stats.unit_count` 로 판정한다 |
| `/translate/stream` `done` 프레임 | 전량 실패일 때만 `config_missing` / `transport` / `execution`, 그 외 `""`. 부분 실패는 `failed_chunk_count` 로 본다 |

#### 공통 하위 객체

**`options`** — 실제로 적용된 언어·문체 (`pipeline._options_payload`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `target_lang` | str | 대상 언어 코드 (`ko`·`en`·`zh`·`th`·`vi`·`ru`) |
| `target_lang_label` | str | 대상 언어 한국어 이름 |
| `source_lang` | str | 원문 언어 코드. 감지 불가 + 대상이 한국어면 `""` |
| `source_lang_detected` | bool | 요청에 원문 언어가 없어 감지값을 썼으면 true |
| `source_lang_mismatch` | bool | 선언한 원문 언어와 문서 감지 언어가 다른데 통과한 경우 true |
| `detected_lang` | str | 문서에서 감지한 최빈 언어 (`""` = 판정 불가) |
| `register` | str | `written` / `spoken` |
| `register_fell_back` | bool | 알 수 없는 문체 값이 와서 `written` 으로 떨어뜨렸으면 true |

**`stats`** (`types.TranslationStats.as_payload`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `unit_count` | int | 전체 번역 유닛 수 |
| `failed_unit_count` | int | 원문으로 폴백된 유닛 수 |
| `llm_unit_count` | int | 실제로 LLM 에 보낸 유닛 수(중복 제거 후) |
| `deduped_unit_count` | int | 같은 원문이라 재사용한 유닛 수 |
| `numeric_warning_count` | int | 숫자 보존 검사에 걸린 유닛 수 |
| `numeric_reverted_count` | int | 그중 원문으로 되돌린 유닛 수 (`TRANSLATE_NUMERIC_GUARD=revert` 일 때만) |
| `fallback_rate` | float | `failed_unit_count / unit_count` (소수 4자리, 유닛 0 이면 0.0) |

**`pairs[]`** (`units.build_pairs`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str | 노드 id. `/translate` 는 요청 노드의 `id`(없으면 순번), 마크다운 경로는 `md:<unit_id>` |
| `unit_id` | int | 유닛 순번. `glossary.hits[].unit_id`·`numeric_warnings[].unit_id` 가 이 값을 가리킨다 |
| `original` | str | 원문 |
| `translated` | str | 번역문 (실패 시 원문) |
| `type` | str | 요소 종류 (`/translate` 는 노드 `type`) |

**`numeric_warnings[]`** — `{unit_id, node_id, missing, added, reverted}`. `missing`/`added` 는 원문에만/번역문에만 있는 수 목록.

**`glossary`** (유닛 경로: `pipeline._run`, 스트리밍 경로: `stream_pipeline.build_document_glossary`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `term_map` | object | `{원문 용어: 번역 용어}` — 번역문이 **실제로 쓴** 용어만 |
| `term_map_unapplied` | object | 사전에 있었지만 번역문이 안 쓴 용어 (검수용). `term_map` 과 겹칠 수 있다 |
| `hits[]` | array | (용어×유닛) 하나당 한 건: `term_source`, `term_target`, `unit_id`, `node_id`, `applied`, `spans`(유닛 원문 기준 `[start,end)` 목록), `target_spans`(유닛 번역문 기준, `applied=false` 면 `[]`). **`/translate/finalize` 에서는 문서 전체가 한 단위라 `unit_id`·`node_id` 가 없고 좌표는 문서 기준이다** |
| `matched_count` | int | 원문에서 사전 용어가 발견된 (용어×유닛) 건수 |
| `applied_count` | int | 그중 번역문이 지정 용어를 쓴 건수 |
| `compliance` | float | `applied_count / matched_count` (소수 4자리). 매칭 0 이면 1.0 |
| `applies` | bool | 이 번역 방향에 용어사전을 쓰는가 (원문·대상 모두 `ko`/`en` 일 때 true. 원문 미감지면 대상만 본다) |
| `source` | object | `{available, reason, term_count}` — 아래 사유 표 |

#### `glossary.source.reason` (번역 응답, 언어별)

`pipeline._glossary_source_status` → `glossary_store.language_status(target_lang)`. 판정 순서대로.

| `reason` | `available` | 뜻 |
|---|---|---|
| `not_applicable` | false | 이 방향은 용어사전 적용 대상이 아니다 (zh·th·vi·ru 가 낀 쌍). 설계대로다 |
| `disabled_over_limit` | false | 그 언어의 색인 용어 수가 캐시 상한(300,000, `glossary_exact._DEFAULT_MAX_CACHED_TERMS`)을 넘어 색인을 포기했다 |
| `language_missing` | false | 적재는 성공(`loaded=true`)했는데 그 언어 색인이 비어 있다 |
| (적재 실패 사유 그대로) | false | 적재 자체가 실패했으면 `GET /glossary` 의 `reason` 이 그대로 온다 — `not_configured` / `fetch_failed` / `fetch_failed_<HTTP 상태코드>` / `target_key_missing` / `empty` (기동 전이면 `not_loaded`) |
| `ok` | true | 적용됨. `term_count` 는 그 언어 색인 용어 수 |

#### 용어사전 환경변수 (`config.py`, 호출 시점에 읽는다)

`TRANSLATE_GLOSSARY_API_URL`·`TRANSLATE_GLOSSARY_TOKEN`·`TRANSLATE_GLOSSARY_TARGET_KEY` 중 하나라도 비어 있거나, URL 에 `{glossary_id}` 가 있는데 `TRANSLATE_GLOSSARY_ID` 가 비어 있으면 적재하지 않고 `not_configured` 다.

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `TRANSLATE_GLOSSARY_API_URL` | ✅ | `""` | 용어 목록 URL 전체. `{glossary_id}` 가 있으면 사전 ID 로 치환(URL 인코딩)한다. 경로를 코드가 만들지 않는다 |
| `TRANSLATE_GLOSSARY_ID` | 조건부 | `""` | 용어사전 ID. URL 에 `{glossary_id}` 가 있을 때만 필수 |
| `TRANSLATE_GLOSSARY_TOKEN` | ✅ | `""` | 사전의 읽기 전용 인증 키. `Authorization: Bearer <값>` 으로 싣는다. 게이트웨이 토큰으로 대신하지 않는다 |
| `TRANSLATE_GLOSSARY_TARGET_KEY` | ✅ | `""` | 영문명(영어 대응 용어) 속성 키 |
| `TRANSLATE_GLOSSARY_SYNONYM_KEY` | 선택 | `""` | 한국어 동의어·줄임말 속성 키. 비우면 대표어만 색인 |
| `TRANSLATE_GLOSSARY_WORKSPACE_ID` | 선택 | `""` | 값이 있으면 `x-genos-workspace-id` 헤더로 싣는다 |

적재 요청 고정값(`glossary_store.py`): `GET <URL>?pg=<page>&pgSize=200`, 타임아웃 20초, 최대 20,000 용어(`_MAX_TERMS`)에서 끊는다. 대표어 키는 `text` 고정, 값 하나 1,024자 상한.

#### 그 밖의 환경변수 (라우트 동작에 걸리는 것)

| 변수 | 기본값 | 쓰는 곳 |
|---|---|---|
| `TRANSLATE_MAX_NODES` | 2000 | `/translate` 노드 수 상한 |
| `TRANSLATE_MAX_TOTAL_CHARS` | 500000 | 모든 번역·내려받기·finalize 의 본문 길이 상한 |
| `TRANSLATE_MAX_UPLOAD_BYTES` | 20971520 (20MB) | `/translate/hwpx` 업로드 상한 |
| `TRANSLATE_ADMIN_TOKEN` | `""` | 두 reload 라우트의 `x-admin-token` 검사 |
| `TRANSLATE_PROMPT_IDS` | `""` | 프롬프트 라이브러리 `이름=ID` 목록 또는 JSON |
| `GENOS_ADMIN_API_URL` | `""` | 프롬프트 라이브러리 조회 주소 |
| `GENOS_CDN_UPLOAD_URL` / `GENOS_CDN_HOSTNAME` | `http://llmops-cdn-api-service:8080/minio/upload/temp` / `https://genos.genon.ai` | `download_url` 업로드 |

---

### GET /health

헬스체크 (가이드 필수). 누가 부르나: GenOS 플랫폼.

- 요청: 없음
- 응답 200 `application/json`: `{"status": "ok"}`
- 오류: 없음

### GET / (및 GET "")

게이트웨이가 서빙 베이스를 경로 없이 호출하는 배포에 대비한 루트. `""` 와 `"/"` 둘 다 등록돼 있다.

- 요청: 없음
- 응답 200: `{"service": "office-translation-service", "status": "ok"}`
- 오류: 없음

### GET /languages

지원 언어·문체 목록. 누가 부르나: 프론트(선택지 그리기 — FRONT.md §3.1).

- 요청: 없음
- 응답 200:

| 필드 | 타입 | 설명 |
|---|---|---|
| `languages[]` | array | `{code, label(한국어 이름), en_label, glossary_supported}` 6개: ko·en·zh·th·vi·ru. `glossary_supported` 는 ko·en 만 true |
| `registers[]` | array | `{code, label}` — `written`/문어체, `spoken`/구어체 |
| `korean_axis_required` | bool | 항상 `true` (원문·대상 중 하나는 한국어) |
| `glossary_languages` | array | `["ko", "en"]` |

- 오류: 없음

### GET /glossary

용어사전 적재 상태(마지막 적재 시도 결과). 누가 부르나: 관리자·운영 점검.

- 요청: 없음
- 응답 200 (`glossary_store.status()`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `loaded` | bool | 쓸 용어가 1건 이상 색인됐으면 true |
| `reason` | str | 아래 표 |
| `languages` | object | `{"en": <ko→en 색인 용어 수>, "ko": <en→ko 색인 용어 수>}`. 적재 실패·용어 0건이면 `{}` |
| `source` | str | 적재를 한 번이라도 시도했으면 `"api"`, 기동 전이면 `""` |

| `reason` | `loaded` | 뜻 |
|---|---|---|
| `not_loaded` | false | 아직 적재를 시도하지 않았다 (lifespan 전) |
| `not_configured` | false | URL·인증 키·영문명 속성 키(또는 `{glossary_id}` 가 있을 때 ID) 중 하나가 비어 있다 |
| `fetch_failed_<코드>` | false | 용어사전 API 가 HTTP 오류 상태를 돌려줬다 (예: `fetch_failed_401`, `fetch_failed_403`, `fetch_failed_500`) |
| `fetch_failed` | false | 연결 실패·타임아웃·JSON 파싱 실패 등 상태코드 없는 실패 |
| `target_key_missing` | false | 용어는 받았는데 어느 용어에도 영문명 속성 키가 없다 — 설정한 키 이름이 틀렸다 |
| `empty` | false | 받은 용어가 없거나, 검증(대표어·영문명 필수, 1,024자 상한, 중복)에서 전부 걸러졌다 |
| `ok` | true | 적재 성공 |

```json
{ "loaded": true, "reason": "ok", "languages": { "en": 1280, "ko": 1342 }, "source": "api" }
```

- 오류: 없음

### POST /glossary/reload

용어사전을 API 에서 다시 받아 색인한다(용어 등록·승인 후 재배포 없이 반영). 누가 부르나: 관리자.

- 요청: 바디 없음. 헤더 `x-admin-token` (선택, 기본 `""`)
- 응답 200: `GET /glossary` 와 같은 모양 (재적재 결과). 적재가 실패해도 200 이고 사유는 `reason` 에 담긴다
- 오류:

| HTTP | `error_code` | `msg` | 조건 |
|---|---|---|---|
| 403 | `ERR-03-00020003` | `용어사전 재적재 권한이 없습니다.` | `TRANSLATE_ADMIN_TOKEN` 이 설정돼 있고 헤더 값이 다름 |

### POST /translate

문서에서 추출한 노드 목록을 번역한다. 누가 부르나: 확인 안 됨 (캔버스 스텝은 `/translate/markdown` 을 부른다 — FEATURES.md §워크플로우 표).

- 요청 `application/json` (`TranslateRequest`):

| 필드 | 타입 | 필수 | 기본값 | 제약 |
|---|---|---|---|---|
| `nodes` | list[object] | ✅ | — | 노드마다 `id`(없으면 순번), `text`, `type`, `scope`(문맥 범위), `context` 를 읽는다. 개수 ≤ `TRANSLATE_MAX_NODES`, `text` 합계 ≤ `TRANSLATE_MAX_TOTAL_CHARS` |
| `target_lang` | str | ✅ | — | 1~32자. 코드 또는 별칭(`english`, `영어`, `en-us` 등) |
| `source_lang` | str | | `""` | ≤32자. 비우면 감지 |
| `register` | str | | `""` | ≤32자. `written`/`spoken` 또는 별칭(`문어체`·`구어체`·`formal`·`casual` 등). 비우면 `written` |

- 응답 200 (`api_contract.nodes_payload`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `pairs` | array | 공통 `pairs[]` |
| `text` | str | `pairs[].translated` 를 `\n` 으로 이은 전체 번역문 |
| `translation_error` | str | 공통 "번역 실패 표시" |
| `stats` · `glossary` · `numeric_warnings` · `options` | | 공통 하위 객체 |

- 오류 (400 은 전부 `ERR-03-00020003`):

| HTTP | `msg` | 조건 |
|---|---|---|
| 400 | `nodes 개수가 상한(<N>건)을 초과했습니다.` | 노드 수 초과 |
| 400 | `총 텍스트 길이가 상한(<N>자)을 초과했습니다.` | 글자 수 초과 |
| 400 | `nodes가 비어 있습니다.` | `nodes: []` |
| 400 | `target_lang이 비어 있습니다.` | 공백뿐인 `target_lang` |
| 400 | 언어 안내문 (아래 "언어 거부 문구") | 지원 밖 언어·같은 언어·한국어 축 위반·원문 언어 확인 불가 |
| 400 | `프롬프트 템플릿을 찾을 수 없습니다.` 등 `prompt_loader` 고정 문구 | 프롬프트 렌더 실패(배포 구성 오류) |
| 422 | FastAPI 기본 | 필드 누락·길이 위반·`nodes` 원소가 object 아님 |
| 500 | `ERR_INTERNAL` | 그 밖의 예외 |

**언어 거부 문구** (`languages.py`, 다섯 경로 공통):

- `지원하지 않는 언어입니다. 한국어·영어·중국어·태국어·베트남어·러시아어 중에서 골라 주세요.`
- `원문과 같은 언어로는 번역할 수 없습니다.`
- `한국어가 포함된 번역만 지원합니다. 원문 또는 번역 대상 중 하나는 한국어여야 합니다.`
- `원문 언어를 선택해 주세요. 문서에서 언어를 알아내지 못했고, 한국어가 아닌 언어로 번역하려면 원문이 한국어인지 확인되어야 합니다.` — 감지 불가(숫자·기호뿐) + 원문 미지정 + 대상이 한국어가 아님
- `선택하신 원문 언어와 문서의 언어가 다릅니다. 문서는 <언어>로 보이며, 한국어가 포함된 번역만 지원합니다. 원문 언어를 확인해 주세요.` — 선언한 언어가 문서 문자의 10% 미만이고 감지 언어·대상 모두 한국어가 아님

**프롬프트 렌더 실패 문구** (`prompt_loader.py`): `프롬프트 템플릿을 찾을 수 없습니다.` / `프롬프트 이름이 올바르지 않습니다.` / `프롬프트에 지원하지 않는 문법이 있습니다.` / `프롬프트를 생성하지 못했습니다.`

### POST /translate/markdown

전처리기 산출물(마크다운/HTML 표)을 구조 보존 방식(스켈레톤 분해)으로 번역하고, 결과 md 를 업로드해 링크를 함께 준다. 누가 부르나: 워크플로우 스텝 `sfr018_translate_02_translate`.

- 요청 `application/json` (`TranslateMarkdownRequest`):

| 필드 | 타입 | 필수 | 기본값 | 제약 |
|---|---|---|---|---|
| `markdown` | str | ✅ | — | 최소 1자, ≤ `TRANSLATE_MAX_TOTAL_CHARS` |
| `target_lang` | str | ✅ | — | 1~32자 |
| `source_lang` | str | | `""` | ≤32자 |
| `register` | str | | `""` | ≤32자 |
| `title` | str | | `""` | ≤200자. 업로드 파일명(`<title>.md`, 비면 `번역결과.md`) |

- 응답 200 (`api_contract.markdown_payload`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `markdown` | str | 번역 마크다운 **정본**. 구조는 입력과 동일 |
| `download_url` | str \| null | 정본을 md 로 올린 presigned 링크. 업로드 실패·미설정이면 `null` |
| `markdown_highlighted` | str | 표시용 사본 — 실제로 참고한 사전 용어를 `<mark>…</mark>` 로 감쌈 |
| `source_markdown` | str | 입력 원문 그대로 |
| `source_markdown_highlighted` | str | 원문 표시용 사본 (같은 기준으로 `<mark>`) |
| `pairs` · `translation_error` · `stats` · `glossary` · `numeric_warnings` · `options` | | 공통 |

번역할 텍스트가 없는 문서(숫자 표 등)는 LLM 을 부르지 않고 입력을 그대로 돌려준다(`pairs: []`, `stats` 0, `glossary: {}`).

```json
{
  "markdown": "| Item | Amount |\n|---|---|\n| merchant | 1,000 |",
  "download_url": "https://genos.genon.ai/…/번역결과.md",
  "markdown_highlighted": "| Item | Amount |\n|---|---|\n| <mark>merchant</mark> | 1,000 |",
  "source_markdown": "| 항목 | 금액 |\n|---|---|\n| 가맹점 | 1,000 |",
  "source_markdown_highlighted": "…<mark>가맹점</mark>…",
  "pairs": [{ "id": "md:2", "unit_id": 2, "original": "가맹점", "translated": "merchant", "type": "…" }],
  "translation_error": "",
  "stats": { "unit_count": 4, "failed_unit_count": 0, "llm_unit_count": 4, "deduped_unit_count": 0,
             "numeric_warning_count": 0, "numeric_reverted_count": 0, "fallback_rate": 0.0 },
  "glossary": { "term_map": { "가맹점": "merchant" }, "term_map_unapplied": {}, "hits": [ … ],
                "matched_count": 1, "applied_count": 1, "compliance": 1.0, "applies": true,
                "source": { "available": true, "reason": "ok", "term_count": 1280 } },
  "numeric_warnings": [],
  "options": { "target_lang": "en", "target_lang_label": "영어", "source_lang": "ko",
               "source_lang_detected": true, "source_lang_mismatch": false, "detected_lang": "ko",
               "register": "written", "register_fell_back": false }
}
```

- 오류:

| HTTP | `msg` | 조건 |
|---|---|---|
| 400 | `총 텍스트 길이가 상한(<N>자)을 초과했습니다.` | |
| 400 | `markdown이 비어 있습니다.` | 공백뿐인 본문 |
| 400 | `target_lang이 비어 있습니다.` | |
| 400 | 언어 거부 문구 · 프롬프트 렌더 실패 문구 | `/translate` 와 같다 |
| 422 | FastAPI 기본 | 필드 누락·길이 위반 |
| 500 | `ERR_INTERNAL` | |

### POST /translate/hwpx

업로드한 hwpx 를 전처리기 없이 직접 파싱(`hwpx_text.to_markdown`)한 뒤 `/translate/markdown` 과 같은 경로로 번역한다. 누가 부르나: 확인 안 됨 (캔버스 스텝은 전처리기 산출물을 `/translate/stream`·`/translate/markdown` 으로 보낸다).

- 요청 `multipart/form-data`:

| 필드 | 종류 | 필수 | 기본값 | 제약 |
|---|---|---|---|---|
| `document` | File | ✅ | — | hwpx. ≤ `TRANSLATE_MAX_UPLOAD_BYTES` (상한을 넘으면 읽기를 멈춘다) |
| `target_lang` | Form | ✅ | — | |
| `source_lang` | Form | | `""` | |
| `register` | Form | | `""` | |
| `title` | Form | | `""` | 업로드 파일명 |

- 응답 200: `/translate/markdown` 과 같은 필드 + `source`:

| 필드 | 타입 | 설명 |
|---|---|---|
| `source.paragraph_count` | int | 파싱한 문단 수 |
| `source.table_count` | int | 파싱한 표 수 |

- 오류:

| HTTP | `msg` | 조건 |
|---|---|---|
| 400 | `파일 크기가 상한(<N>MB)을 초과했습니다.` | |
| 400 | `업로드된 파일이 비어 있습니다.` | |
| 400 | `hwpx 파일이 아니거나 손상된 파일입니다.` | zip 아님 |
| 400 | `hwpx 본문 XML 을 해석하지 못했습니다.` | XML 파싱 실패 |
| 400 | `문서에서 번역할 텍스트를 찾지 못했습니다.` | 파싱 결과가 비어 있음 |
| 400 | `총 텍스트 길이가 상한(<N>자)을 초과했습니다.` | 파싱 결과가 길다 (자르지 않는다) |
| 400 | `target_lang이 비어 있습니다.` · 언어 거부 문구 · 프롬프트 렌더 실패 문구 | |
| 422 | FastAPI 기본 | `document`·`target_lang` 누락 |
| 500 | `ERR_INTERNAL` | 파싱 중 그 밖의 예외(`event=translate_hwpx_parse_error`) 또는 번역 중 예외 |

### POST /download

화면이 들고 있는 번역문을 그대로 md 파일로 내려준다(폴백 경로 — 기본은 `download_url`). 누가 부르나: 프론트.

- 요청 `application/json` (`DownloadRequest`):

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `text` | str | | `""` | 내려받을 번역문 (`/translate` 의 `text`) |
| `markdown` | str | | `""` | `text` 의 별칭 (마크다운 경로의 `markdown`). `text` 가 비었을 때만 쓴다 |
| `title` | str | | `""` | ≤200자. 파일명 |

- 응답 200:
  - `Content-Type: text/markdown; charset=utf-8`
  - `Content-Disposition: attachment; filename*=UTF-8''<URL 인코딩된 제목>.md` (`filename=` 없음). 제목에서 `\/:*?"<>|`·제어문자를 지우고 80자로 자른다. 비면 `번역결과`
  - 본문: UTF-8 BOM + CRLF. 내용은 받은 그대로 (표·`<mark>` 를 풀거나 지우지 않는다)
- 오류:

| HTTP | `msg` | 조건 |
|---|---|---|
| 400 | `내려받을 번역문이 없습니다.` | `text`·`markdown` 모두 비거나 공백 |
| 400 | `총 텍스트 길이가 상한(<N>자)을 초과했습니다.` | |
| 422 | FastAPI 기본 | `title` 200자 초과 |

### GET /prompts

프롬프트를 어디서 받았는지(라이브러리 ID / 이미지 안 파일). 본문은 싣지 않는다. 누가 부르나: 관리자.

- 요청: 없음
- 응답 200: `{"prompts": [ … ]}`. `TRANSLATE_PROMPT_IDS` 에 적힌 이름만 행이 된다 — 미설정이면 `[]`.

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | str | 템플릿 이름 = 파일 이름에서 확장자를 뗀 것 (`system_batch`, `user_batch`, `glossary_batch`, `system_single`, `user_single`, `glossary_single`, `system_stream`, `user_stream`, `glossary_stream`) |
| `configured` | bool | ID 가 설정됐는가 |
| `prompt_id` | str | 설정된 ID |
| `source` | str | `prompt_library` 또는 `file` |
| `reason` | str | `prompt_library`(성공) / `not_configured`(`GENOS_ADMIN_API_URL` 없음) / `fetch_failed_<코드>` / `fetch_failed` / `api_error`(`code != 0`) / `empty_body` |

결과는 60초 캐시된다.

- 오류: 없음

### POST /prompts/reload

캐시를 무시하고 프롬프트 라이브러리를 즉시 다시 읽는다. 누가 부르나: 관리자.

- 요청: 바디 없음. 헤더 `x-admin-token`
- 응답 200: `GET /prompts` 와 같은 모양
- 오류:

| HTTP | `error_code` | `msg` | 조건 |
|---|---|---|---|
| 403 | `ERR-03-00020003` | `프롬프트 재적재 권한이 없습니다.` | `TRANSLATE_ADMIN_TOKEN` 설정 + 헤더 불일치 |

### POST /translate/stream

번역문을 만들어지는 대로 SSE 로 흘린다(마크다운째 번역, 스켈레톤 분해 없음 — 구조 보존은 프롬프트에 맡기고 finalize 가 대조한다). 누가 부르나: 번역 워크플로우 스텝(`_TRANSLATE_STREAM_PATH`)이 먼저 부르고, 실패하면 `/translate/markdown` 으로 폴백한다. 끝나면 `/translate/finalize` 를 부른다.

- 요청 `application/json` (`TranslateStreamRequest`): `markdown`(✅, 최소 1자) · `target_lang`(✅, 1~32자) · `source_lang`(`""`) · `register`(`""`). `/translate/markdown` 에서 `title` 만 없다.
- 흘리기 전 실패는 SSE 가 아니라 일반 JSON 오류다:

| HTTP | `msg` | 조건 |
|---|---|---|
| 400 | `총 텍스트 길이가 상한(<N>자)을 초과했습니다.` | |
| 400 | 언어 거부 문구 | 옵션 확정(`resolve_options`) 실패 |
| 422 | FastAPI 기본 | 필드 누락·길이 위반 |
| 500 | `ERR_INTERNAL` | 옵션 확정 중 그 밖의 예외 |

- 성공 응답 200 `text/event-stream`, 헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no`. 프레임은 `data: <JSON>\n\n` (event 이름 없음, `ensure_ascii=False`).

| `type` | 필드 | 설명 |
|---|---|---|
| `delta` | `text` | 번역문 조각. 문서 순서대로 온다. 게이트웨이가 스트리밍을 받지 않으면 비스트리밍으로 번역해 한 덩어리로 한 번 보낸다 |
| `done` | 아래 표 | 정상 종료 프레임 (마지막) |
| `error` | `error_code`, `msg` | 번역 도중 예외. `error_code` 는 `ERR-03-00020003`, `msg` 는 `번역 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.` (마지막) |

`done` 프레임:

| 필드 | 타입 | 설명 |
|---|---|---|
| `translated_text` | str | 번역 정본. **finalize 에 이 값을 그대로 보낸다** (델타를 이어 붙인 값이 아니라) |
| `options` | object | 공통 `options` |
| `chunk_count` | int | LLM 을 부른 조각 수 (`TRANSLATE_STREAM_CHUNK_CHARS`, 기본 6000자 단위) |
| `failed_chunk_count` | int | 실패해 원문을 넣은 조각 수 |
| `translation_error` | str | 전량 실패일 때만 `config_missing`/`transport`/`execution`, 그 외 `""` |
| `stream_diverged` | bool | 화면에 흘린 글과 정본이 어긋났다 |
| `stream_fallback` | bool | 스트리밍을 못 써 비스트리밍으로 번역했다 |
| `finalize_endpoint` | str | `"/translate/finalize"` |

```
data: {"type": "delta", "text": "| Item | Amount |\n"}

data: {"type": "done", "translated_text": "…", "options": {…}, "chunk_count": 1, "failed_chunk_count": 0, "translation_error": "", "stream_diverged": false, "stream_fallback": false, "finalize_endpoint": "/translate/finalize"}
```

클라이언트가 연결을 끊으면 진행 중인 번역 작업을 취소한다.

### POST /translate/finalize

스트리밍이 끝난 뒤 용어사전 하이라이트·구조 대조·내려받기 링크를 받는다. LLM 을 부르지 않는 결정적 계산이라 재시도해도 같은 답이다. 누가 부르나: `/translate/stream` 을 쓴 쪽.

- 요청 `application/json` (`TranslateFinalizeRequest`):

| 필드 | 타입 | 필수 | 기본값 | 제약 |
|---|---|---|---|---|
| `original_text` | str | ✅ | — | 스트리밍에 보낸 원문. 최소 1자, ≤ `TRANSLATE_MAX_TOTAL_CHARS` |
| `translated_text` | str | ✅ | — | `done` 프레임의 `translated_text`. 최소 1자, ≤ 상한 |
| `target_lang` | str | ✅ | — | 1~32자 |
| `source_lang` | str | | `""` | ≤32자 |
| `register` | str | | `""` | ≤32자 |
| `title` | str | | `""` | ≤200자. 업로드 파일명 |

- 응답 200:

| 필드 | 타입 | 설명 |
|---|---|---|
| `original_text` | str | 받은 원문 그대로 |
| `translated_text` | str | 받은 번역문 그대로 |
| `markdown_highlighted` | str | 번역문 표시용 사본 (`<mark>`). `/translate/markdown` 과 같은 키 이름 |
| `source_markdown_highlighted` | str | 원문 표시용 사본 |
| `glossary` | object | 공통 `glossary` — 단 `hits[]` 에 `unit_id`·`node_id` 가 없고 좌표는 문서 전체 기준 |
| `structure` | object | `{ok: bool, issues: [{kind, source, translated}]}`. `kind` ∈ `md_table_row`·`code_fence`·`html_table`·`html_row`·`html_cell`·`heading`·`list_item`, `source`/`translated` 는 개수 |
| `download_url` | str | 번역문 md 링크. **업로드 실패 시 `""`** (`null` 이 아니다) |
| `options` | object | 공통 `options` |

- 오류:

| HTTP | `msg` | 조건 |
|---|---|---|
| 400 | `총 텍스트 길이가 상한(<N>자)을 초과했습니다.` | 원문 또는 번역문이 상한 초과 |
| 400 | 언어 거부 문구 | |
| 422 | FastAPI 기본 | 필드 누락·길이 위반 |
| 500 | `ERR_INTERNAL` | |

---

## FAQ (SFR-018-faq)

### 공통

| 항목 | 값 |
|---|---|
| 진입점 | `final/SFR-018-faq/request/faq/main.py` (패키지 안 — 시작(Run) 커맨드 등록 필요). 요청 스키마·오류 조립은 `faq/api_contract.py` |
| 앱 | `FastAPI(title="faq-service", lifespan=_lifespan)` — 기동 시 `FAQ_ADMIN_TOKEN` 이 없으면 `event=admin_token_missing` 경고 |
| 기동 | 이 파일에 `__main__` 블록 없음. 시작 커맨드 `uvicorn faq.main:app --host 0.0.0.0 --port $PORT` (`final/docs/README.md` 등록표 기준) |
| 베이스 경로 | 접두어 없음 |
| 상태 | Redis 세션 (`FAQ_REDIS_PREFIX` 기본 `faq:session`, TTL `FAQ_SESSION_TTL_HOURS` 기본 24h). 다운로드가 세션을 지우지 않는다 |
| 인증 | 헤더 `x-admin-token` — `POST /prompts/reload` 만 본다. 값은 `FAQ_ADMIN_TOKEN`. 미설정이면 검사 없음 |
| 라우트 수 | 11 (`GET /` 와 `GET ""` 를 따로 셈) |

**공통 오류 바디** (`api_contract.json_error`) — 상태코드는 `ErrorCode.http_status`. `msg` 는 라우트가 넘긴 고정 안내문이 있으면 그것, 없으면 `user_msg`.

```json
{ "error_code": "ERR-03-00020003", "msg": "session_id 가 필요합니다." }
```

응답 바디에 `error_type`·`retryable` 은 없다(로그 `event=api_error` 에만).

**오류 코드 표** (`faq/error_codes.py`, 영역코드 `03`)

| 상수 | HTTP | `error_code` | `error_type` (로그) | retryable | 기본 `msg` |
|---|---|---|---|---|---|
| `ERR_API_INPUT` | 400 | `ERR-03-00020003` | `FAQ_API_INPUT` | false | 요청 형식이 올바르지 않습니다. (라우트가 대개 다른 문구로 덮는다) |
| `ERR_API_SESSION_NOT_FOUND` | 404 | `ERR-03-00020003` | `FAQ_API_SESSION_NOT_FOUND` | false | FAQ 정보를 찾을 수 없습니다. FAQ 를 먼저 생성해 주세요. |
| `ERR_API_UPSTREAM_TIMEOUT` | 504 | `ERR-03-00020001` | `FAQ_API_UPSTREAM_TIMEOUT` | true | 외부 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_API_UPSTREAM_EXECUTION` | 502 | `ERR-03-00020002` | `FAQ_API_UPSTREAM_EXECUTION_FAILED` | true | FAQ 생성에 실패했습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_API_NO_GROUNDED` | 422 | `ERR-03-00020002` | `FAQ_API_NO_GROUNDED_ITEMS` | true | 문서에서 근거를 확인할 수 있는 FAQ 를 만들지 못했습니다. 다시 시도해 주세요. |
| `ERR_API_PROMPT_UNAVAILABLE` | 500 | `ERR-03-00020003` | `FAQ_API_PROMPT_UNAVAILABLE` | false | 요청을 처리하지 못했습니다. 관리자에게 문의해 주세요. |
| `ERR_API_CONFIG_UNAVAILABLE` | 500 | `ERR-03-00020003` | `FAQ_API_CONFIG_UNAVAILABLE` | false | 서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요. |
| `ERR_API_INTERNAL` | 500 | `ERR-03-00020003` | `FAQ_API_INTERNAL` | false | 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_API_ADMIN_FORBIDDEN` | 403 | `ERR-03-00020003` | `FAQ_API_ADMIN_FORBIDDEN` | false | 권한이 없습니다. |

**생성 실패 매핑** (`_FAILURE_ERRORS`, `/generate`·`/generate/stream`·`/generate/upload` 공통)

| `generator` 실패 분류 | 오류 |
|---|---|
| `transport` | `ERR_API_UPSTREAM_TIMEOUT` (504) |
| `no_grounded` — 근거 통과 항목 0건, 또는 본문에 글자가 없음 | `ERR_API_NO_GROUNDED` (422) |
| `prompt` — 프롬프트 템플릿 부재 | `ERR_API_PROMPT_UNAVAILABLE` (500) |
| `config` — `GENOS_URL`/`LLM_SERVING_ID` 부재 | `ERR_API_CONFIG_UNAVAILABLE` (500) |
| 그 밖 (`execution` 등, 실패 없이 항목 0건 포함) | `ERR_API_UPSTREAM_EXECUTION` (502) |

**바디 검증 실패** — `RequestValidationError` 핸들러가 없다. Pydantic/Form 제약 위반은 FastAPI 기본 `422 {"detail": [...]}` 로 나간다.

**입력 길이 상한** — `FAQ_MAX_CONTEXT_CHARS`(기본 12000) × `FAQ_MAX_CONTEXT_CHUNKS`(기본 80) = 기본 960,000자. 넘으면 `ERR_API_INPUT` 400 "문서가 너무 깁니다. 나누어 요청해 주세요."

---

### GET /health

| 항목 | 값 |
|---|---|
| 용도 | 헬스체크 |
| 호출자 | GenOS 상태 확인 |
| 성공 | `200` — `{"status": "ok"}` |
| 오류 | 없음 |

### GET / , GET ""

| 항목 | 값 |
|---|---|
| 용도 | 게이트웨이가 경로 없이 베이스를 칠 때의 응답 |
| 호출자 | 확인 안 됨 |
| 성공 | `200` — `{"service": "faq-service", "status": "ok"}` |
| 오류 | 없음 |

### GET /config

| 항목 | 값 |
|---|---|
| 용도 | 개수 상한·기본 개수·형식 (화면 선택지, 스텝의 상한 판정) |
| 호출자 | 워크플로우 스텝 `sfr018_faq_01_source`, 프론트 |
| 요청 | 없음 |
| 성공 | `200`, `application/json` |
| 오류 | 없음 |

| 필드 | 타입 | 설명 |
|---|---|---|
| `max_count` | int | 총 개수 배포 상한 `FAQ_MAX_COUNT` (기본 30) |
| `default_count` | int | `FAQ_DEFAULT_COUNT` (기본 5) |
| `formats` | string[] | 항상 `["md"]` |
| `evidence_required` | bool | `FAQ_EVIDENCE_REJECT` (기본 켜짐) — 근거 미확인 항목을 기각하는가 |

```json
{ "max_count": 30, "default_count": 5, "formats": ["md"], "evidence_required": true }
```

### POST /generate

| 항목 | 값 |
|---|---|
| 용도 | 마크다운 본문으로 FAQ 생성 (비스트리밍). 성공하면 md 를 CDN 에 올리고, `session_id` 가 있으면 세션에 저장 |
| 호출자 | 워크플로우 스텝 `sfr018_faq_02_generate` (스트리밍 폴백) |
| 요청 | `application/json` — `GenerateRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `markdown` | string | 예 | — | `min_length=1`. 전처리기 산출 본문. 길이 상한은 위 공통 |
| `count` | int | 아니오 | `0` | `0 ≤ count ≤ 1000`. 0 이면 `FAQ_DEFAULT_COUNT`. `max_count` 를 넘으면 깎이고 `count_clamped=true` |
| `session_id` | string | 아니오 | `""` | `max_length=128`. 비면 세션 저장 안 함 (`download_ready=false`) |
| `title` | string | 아니오 | `""` | `max_length=200`. 파일 맨 위 `# 제목`·파일명 (비면 `FAQ`) |

**성공** — `200`, `application/json`

| 필드 | 타입 | 설명 |
|---|---|---|
| `items[]` | array | `{question, answer, evidence, evidence_ratio}` — 근거 검증을 통과한 항목 |
| `count` | int | `items` 길이 |
| `requested_count` | int | 상한 안으로 깎인 목표 총 개수 |
| `max_count` | int | 총 개수 상한 |
| `call_cap` | int | LLM 호출 수 상한 `FAQ_MAX_CHUNK_CALLS` (기본 6) |
| `count_clamped` | bool | 요청 개수가 상한을 넘어 깎였는가 |
| `coverage_capped` | bool | 호출 수 상한 때문에 일부 구간만 태웠는가 |
| `rejected` | object | `{schema, ungrounded, duplicate}` 기각 건수 |
| `source_truncated` | bool | 조각 수 상한에 걸려 문서 뒤를 버렸는가 |
| `source_chunks` | int | 문서를 나눈 조각 수 |
| `chunks_planned` | int | 몫을 배정받은 조각 수 |
| `chunks_used` | int | LLM 호출이 성공한 조각 수 |
| `markdown` | string | 화면용 마크다운 (`**Q1. …**` / 답변 / `> 근거: …`) |
| `download_ready` | bool | 세션 저장 성공 여부 (`POST /download` 를 세션으로 부를 수 있는가) |
| `download_url` | string \| null | 결과 md presigned URL. 업로드 미설정·실패면 `null` |

```json
{ "items": [{"question": "위약금은?", "answer": "잔여 기간에 비례합니다.", "evidence": "위약금은 …", "evidence_ratio": 1.0}],
  "count": 1, "requested_count": 5, "max_count": 30, "call_cap": 6, "count_clamped": false,
  "coverage_capped": false, "rejected": {"schema": 0, "ungrounded": 2, "duplicate": 0},
  "source_truncated": false, "source_chunks": 1, "chunks_planned": 1, "chunks_used": 1,
  "markdown": "**Q1. 위약금은?**\n\n…", "download_ready": true, "download_url": null }
```

업로드 파일: `<safe_stem(title,"FAQ")>.md`, `text/markdown; charset=utf-8`, UTF-8 BOM + CRLF.

**오류**

| HTTP | `error_code` | 원인 |
|---|---|---|
| 400 | `ERR-03-00020003` | `FAQ_API_INPUT` — "문서가 너무 깁니다. 나누어 요청해 주세요." |
| 422 | — | FastAPI 기본 — `markdown` 누락/빈 문자열, `count` 범위 밖 등 |
| 422 | `ERR-03-00020002` | `FAQ_API_NO_GROUNDED_ITEMS` |
| 502 | `ERR-03-00020002` | `FAQ_API_UPSTREAM_EXECUTION_FAILED` |
| 504 | `ERR-03-00020001` | `FAQ_API_UPSTREAM_TIMEOUT` |
| 500 | `ERR-03-00020003` | `FAQ_API_PROMPT_UNAVAILABLE` / `FAQ_API_CONFIG_UNAVAILABLE` / `FAQ_API_INTERNAL`(예상 밖 예외) |

세션 저장 실패(`SessionStoreError`)는 오류가 아니다 — 결과를 내고 `download_ready=false`.

### POST /generate/stream

| 항목 | 값 |
|---|---|
| 용도 | `/generate` 와 같은 생성을 항목마다 SSE 로 흘린다. 근거·중복 검증을 통과한 항목만 프레임이 된다 |
| 호출자 | 워크플로우 스텝 `sfr018_faq_02_generate` (`_GENERATE_STREAM_PATH`) |
| 요청 | `/generate` 와 동일 (`GenerateRequest`) |

**흘리기 전 실패** — 길이 상한 초과(400)와 바디 검증(422)만 JSON 오류로 나간다. 생성 실패는 스트림이 시작된 뒤라 `error` 프레임이다.

**성공 시작** — `200`, `Content-Type: text/event-stream`, 헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no`. 프레임은 `data: <JSON>\n\n` (`event:` 줄 없음). 한 번에 한 항목만 열리며 `index` 는 0부터, 최종 `items` 순서와 같다.

| 프레임 `type` | 필드 | `text` (화면에 더할 글) |
|---|---|---|
| `item_open` | `index`, `question`, `text` | `**Q{index+1}. {question}**\n\n` (index>0 이면 앞에 `\n\n`) |
| `delta` | `index`, `text` | 답변 토큰 |
| `item_close` | `index`, `question`, `answer`, `evidence`, `text` | `\n\n> 근거: {evidence 한 줄로}` |
| `done` | `/generate` 성공 필드 전부 + `type`, `stream_fallback`(bool) | 종료 프레임 (성공) |
| `error` | `error_code`, `msg` | 종료 프레임 (실패) |

- 모든 `text` 를 이어붙이면 `done.markdown` 과 같다.
- `stream_fallback=true` — 게이트웨이가 스트리밍을 받지 않아 비스트리밍으로 다시 만들었다. 이때도 같은 `item_open`/`delta`/`item_close` 프레임으로 흘린다 (단 이 경로의 폴백 프레임에는 `text` 가 덧붙지 않는다 — `_on_frame` 을 거치지 않고 큐에 직접 넣는다).
- `error` 프레임의 코드는 위 "생성 실패 매핑" 표와 같다. 예상 밖 예외는 `ERR_API_INTERNAL`(`ERR-03-00020003`).
- 클라이언트가 끊으면 서버 작업을 취소한다.

```
data: {"type": "item_open", "index": 0, "question": "위약금은?", "text": "**Q1. 위약금은?**\n\n"}

data: {"type": "delta", "index": 0, "text": "잔여 기간에"}

data: {"type": "done", "items": [...], "count": 1, "markdown": "…", "download_ready": true, "download_url": null, "stream_fallback": false, ...}
```

### POST /generate/upload

| 항목 | 값 |
|---|---|
| 용도 | hwpx 를 직접 파싱(`hwpx_text.to_markdown`)해 FAQ 생성. 응답은 `/generate` 에 `source` 를 더한 것 |
| 호출자 | 확인 안 됨 (워크플로우 스텝은 이 경로를 부르지 않는다) |
| 요청 | `multipart/form-data` |

| 필드 | 종류 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `document` | File | 예 | — | hwpx. `FAQ_MAX_UPLOAD_BYTES`(기본 20MB) 초과 시 읽기를 멈추고 거절 |
| `count` | Form int | 아니오 | `0` | 0 이면 기본 개수. 범위 제약 없음 (음수는 생성기가 0 으로 깎음) |
| `session_id` | Form str | 아니오 | `""` | 길이 제약 없음 |
| `title` | Form str | 아니오 | `""` | 길이 제약 없음 |

**성공** — `200`, `/generate` 성공 필드 + `source: {paragraph_count, table_count}`.

**오류**

| HTTP | `error_code` | `msg` / 원인 |
|---|---|---|
| 400 | `ERR-03-00020003` | 파일 크기가 상한({N}MB)을 초과했습니다. |
| 400 | `ERR-03-00020003` | 업로드된 파일이 비어 있습니다. |
| 400 | `ERR-03-00020003` | hwpx 파일이 아니거나 손상된 파일입니다. / hwpx 본문 XML 을 해석하지 못했습니다. (`HwpxParseError`) |
| 400 | `ERR-03-00020003` | 문서에서 FAQ 를 만들 내용을 찾지 못했습니다. |
| 400 | `ERR-03-00020003` | 문서가 너무 깁니다. 나누어 요청해 주세요. |
| 422 | — | FastAPI 기본 — `document` 누락, `count` 정수 아님 |
| 422/502/504/500 | | 생성 실패 매핑 표와 같음 |
| 500 | `ERR-03-00020003` | `FAQ_API_INTERNAL` — 파싱 중 예상 밖 예외(`faq_upload_parse_error`), 생성 중 예외 |

### GET /faqs

| 항목 | 값 |
|---|---|
| 용도 | 세션에 저장된 FAQ 조회 (다운로드 버튼 활성화 판단용) |
| 호출자 | 확인 안 됨 |
| 쿼리 | `session_id` (string, 필수 — 비면 400) |
| 헤더 | 없음 — 사용자 라우트라 관리자 토큰을 보지 않는다. 조회 범위는 `session_id` |

**성공** — `200`. 세션이 없거나 만료·손상·Redis 장애여도 빈 목록으로 200 이다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `items[]` | array | 저장 형태 `{question, answer, sources}` (근거 키가 `sources` 다) |
| `count` | int | 항목 수 |
| `title` | string | 저장된 제목 |
| `ready_for_download` | bool | 항목이 하나라도 있는가 |
| `formats` | string[] | `["md"]` |

```json
{ "items": [{"question": "위약금은?", "answer": "…", "sources": "위약금은 …"}],
  "count": 1, "title": "약관", "ready_for_download": true, "formats": ["md"] }
```

**오류**

| HTTP | `error_code` | 원인 |
|---|---|---|
| 400 | `ERR-03-00020003` | `FAQ_API_INPUT` — session_id 가 필요합니다. |

### POST /download

| 항목 | 값 |
|---|---|
| 용도 | 저장된 FAQ(또는 화면이 보낸 항목)를 md 파일로 내려준다. 다시 생성하지 않는다. 세션을 지우지 않는다 |
| 호출자 | 프론트 (`download_url` 이 `null` 일 때 폴백) |
| 요청 | `application/json` — `DownloadRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `format` | string | 아니오 | `"md"` | `max_length=16`. 소문자·trim 후 `md` 가 아니면 400 |
| `session_id` | string | 조건부 | `""` | `max_length=128`. `items` 가 없을 때 필수 |
| `items` | object[] \| null | 조건부 | `null` | 화면이 들고 있는 항목. 키는 **`question`·`answer`** 와 근거 `sources`(없으면 `evidence`)를 읽는다 — `/generate` 의 `items` 를 그대로 되보내도 된다 (dict 가 아닌 원소는 버림) |
| `title` | string | 아니오 | `""` | `max_length=200`. 비고 세션으로 읽었으면 세션의 제목 |

**성공** — `200`, 바이너리

| 항목 | 값 |
|---|---|
| `Content-Type` | `text/markdown; charset=utf-8` |
| `Content-Disposition` | `attachment; filename*=UTF-8''<퍼센트 인코딩된 stem>.md` (stem 비면 `FAQ`) |
| `X-Faq-Count` | 항목 수 |
| 본문 | `# 제목`(있을 때) + 화면과 같은 FAQ 마크다운, UTF-8 BOM + CRLF |

**오류**

| HTTP | `error_code` | `msg` / 원인 |
|---|---|---|
| 400 | `ERR-03-00020003` | md 형식으로만 내려받을 수 있습니다. |
| 400 | `ERR-03-00020003` | session_id 또는 items 가 필요합니다. |
| 404 | `ERR-03-00020003` | `FAQ_API_SESSION_NOT_FOUND` — 세션이 비었거나 만료(Redis 장애 포함) |
| 422 | — | FastAPI 기본 — 필드 길이·타입 위반 |
| 500 | `ERR-03-00020003` | `FAQ_API_INTERNAL` — 본문 조립 실패 |

### GET /prompts

| 항목 | 값 |
|---|---|
| 용도 | 프롬프트를 라이브러리와 파일 중 어디서 받았는지 이름별로. 본문은 싣지 않는다 |
| 호출자 | 관리자 |
| 인증 | 없음 |
| 성공 | `200` — `{"prompts": [{name, configured, prompt_id, source, reason}]}` |
| 오류 | 없음 |

`source` 는 `prompt_library`/`file`, `reason` 은 `prompt_library` · `not_configured` · `fetch_failed` · `fetch_failed_<HTTP상태>` · `api_error` · `empty_body`. 프롬프트 ID 는 `FAQ_PROMPT_IDS` 로 설정.

### POST /prompts/reload

| 항목 | 값 |
|---|---|
| 용도 | 프롬프트 라이브러리를 즉시 다시 읽는다 (TTL 무시) |
| 호출자 | 관리자 |
| 헤더 | `x-admin-token` — `FAQ_ADMIN_TOKEN` 이 설정돼 있으면 **반드시 일치**해야 한다 (헤더 누락도 거절) |
| 성공 | `200` — `{"prompts": [...]}` (`GET /prompts` 와 같은 모양) |

**오류**

| HTTP | `error_code` | `msg` |
|---|---|---|
| 403 | `ERR-03-00020003` | 프롬프트 재적재 권한이 없습니다. (`ERR_API_INPUT` 의 코드를 403 으로 직접 조립 — `ERR_API_ADMIN_FORBIDDEN` 을 쓰지 않는다) |

---

## 템플릿 채우기 (SFR-006)

### 공통

| 항목 | 값 |
|---|---|
| 진입점 | `final/SFR-006/request/template_fill/main.py` (패키지 안 — 시작(Run) 커맨드 등록 필요). `/chat/*` 는 `chat_api.install(app)` 이 붙인다 |
| 앱 | `FastAPI(title="hwpx-template-fill-service")` |
| 기동 | `__main__` 블록 없음. 시작 커맨드 `uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT` (`final/docs/README.md` 등록표 기준) |
| 베이스 경로 | 접두어 없음 |
| 상태 | Redis 세션(`session_store.py`) + 템플릿 볼륨 `TEMPLATE_FILL_TEMPLATE_DIR`(기본 `/workspace/templates`) + Redis 색인 캐시 |
| 인증 | 헤더 `x-admin-token` = `TEMPLATE_FILL_ADMIN_TOKEN`. `POST /templates`·`DELETE /templates/{id}`·`POST /prompts/reload` 만 본다. 미설정이면 검사 없음(기동 시 `event=admin_token_missing` 경고) |
| 라우트 수 | 20 (`main.py` 15 — `GET /` 와 `GET ""` 를 따로 셈 — + `chat_api.py` 5) |

**공통 오류 바디** — 라우트는 `ApiError` 를 던지고 `api_errors.install` 이 건 핸들러가 바꾼다. 상태코드는 `ErrorCode.http_status`, `msg` 는 던진 쪽의 고정 안내문이 있으면 그것, 없으면 `user_msg`.

```json
{ "error_code": "ERR-03-00020003", "msg": "템플릿을 찾을 수 없습니다." }
```

응답에 `error_type`·`retryable` 은 없다(로그 `event=api_error` 에만, 5xx 는 ERROR·4xx 는 WARNING).

**오류 코드 표** (`template_fill/error_codes.py`)

코드서빙(03) — 화면·다운로드 경로(`main.py`)

| 상수 | HTTP | `error_code` | `error_type` (로그) | retryable | 기본 `msg` |
|---|---|---|---|---|---|
| `ERR_API_INPUT` | 400 | `ERR-03-00020003` | `TEMPLATE_FILL_API_INPUT` | false | 요청 형식이 올바르지 않습니다. (대개 라우트가 덮는다) |
| `ERR_API_TEMPLATE_NOT_FOUND` | 404 | `ERR-03-00020003` | `TEMPLATE_FILL_API_TEMPLATE_NOT_FOUND` | false | 템플릿을 찾을 수 없습니다. |
| `ERR_API_SESSION_NOT_FOUND` | 404 | `ERR-03-00020003` | `TEMPLATE_FILL_API_SESSION_NOT_FOUND` | false | 세션 정보를 찾을 수 없습니다. 대화를 먼저 진행해 주세요. |
| `ERR_API_INTERNAL` | 500 | `ERR-03-00020002` | `TEMPLATE_FILL_API_INTERNAL` | true | 문서 생성에 실패했습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_API_ADMIN_FORBIDDEN` | 403 | `ERR-03-00020003` | `TEMPLATE_FILL_API_ADMIN_FORBIDDEN` | false | 템플릿 등록·삭제 권한이 없습니다. |
| `ERR_API_TEMPLATE_EXISTS` | 409 | `ERR-03-00020003` | `TEMPLATE_FILL_API_TEMPLATE_EXISTS` | false | 같은 이름의 템플릿이 이미 있습니다. 덮어쓰려면 overwrite 를 지정해 주세요. |

워크플로우(02) — 대화 경로(`/chat/*`). **`http_status` 를 지정하지 않아 전부 HTTP 500 으로 나간다.**

| 상수 | HTTP | `error_code` | `error_type` (로그) | retryable | 기본 `msg` |
|---|---|---|---|---|---|
| `ERR_CHAT_UPSTREAM_TIMEOUT` | 500 | `ERR-02-00020001` | `TEMPLATE_FILL_UPSTREAM_TIMEOUT` | true | 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_CHAT_UPSTREAM_EXECUTION` | 500 | `ERR-02-00020002` | `TEMPLATE_FILL_UPSTREAM_EXECUTION_FAILED` | true | 입력 내용을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_CHAT_TEMPLATE_NOT_FOUND` | 500 | `ERR-02-00020003` | `TEMPLATE_FILL_TEMPLATE_NOT_FOUND` | false | 템플릿을 찾을 수 없습니다. 관리자에게 템플릿 등록 여부를 확인해 주세요. |
| `ERR_CHAT_TEMPLATE_INVALID` | 500 | `ERR-02-00020003` | `TEMPLATE_FILL_TEMPLATE_INVALID` | false | 템플릿 파일을 해석하지 못했습니다. hwpx 형식인지 확인해 주세요. |
| `ERR_CHAT_NO_FIELDS` | 500 | `ERR-02-00020003` | `TEMPLATE_FILL_NO_FIELDS` | false | 템플릿에서 채울 수 있는 항목(슬롯·누름틀)을 찾지 못했습니다. |
| `ERR_CHAT_INTERNAL` | 500 | `ERR-02-00020003` | `TEMPLATE_FILL_INTERNAL_UNCLASSIFIED` | false | 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `ERR_CHAT_CONFIG_MISSING` | 500 | `ERR-02-00020003` | `TEMPLATE_FILL_CONFIG_MISSING` | false | 서비스 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요. |

**공통으로 나가는 오류**

| 상황 | 응답 |
|---|---|
| Pydantic/Query/Form 검증 실패 (필수 누락·길이 초과·타입) | FastAPI 기본 `422 {"detail": [...]}` — `RequestValidationError` 핸들러 없음 |
| `ApiError` 가 아닌 예상 밖 예외 | FastAPI 기본 `500` (`Internal Server Error`, `{error_code,msg}` 아님) |
| `session_id` 가 공백뿐 (정규화 후 빈 키) | 400 `ERR-03-00020003` "session_id 가 올바르지 않습니다." (`/status`·`/preview`·`/values`·`/blocks`·`/generate*`) |
| 템플릿 id 가 비었거나 형식 불가, 또는 파일 없음 (조회 경로) | 404 `ERR-03-00020003` `TEMPLATE_FILL_API_TEMPLATE_NOT_FOUND` |
| 템플릿 hwpx 해석 실패 (`TemplateError`) | 400 `ERR-03-00020003`, `msg` = 도메인 고정 안내문 (예: "hwpx 파일이 아니거나 손상된 파일입니다.", "템플릿 본문 XML 을 해석하지 못했습니다.") |

**주요 상한** (`config.py`): `TEMPLATE_FILL_MAX_FIELDS` 200, `TEMPLATE_FILL_MAX_VALUE_CHARS` 2000, `TEMPLATE_FILL_MAX_MESSAGE_CHARS` 20000, `TEMPLATE_FILL_MAX_UPLOAD_BYTES` 20MB, `TEMPLATE_FILL_MAX_PREVIEW_CHARS` 20000, `TEMPLATE_FILL_MAX_BLOCKS` 100. 기능 스위치 `TEMPLATE_FILL_BODY_BLOCKS`(기본 켜짐), `TEMPLATE_FILL_DOC_PREFILL`(기본 켜짐).

**공용 응답 조각**

`field` (`session_view.field_payload`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | string | 항목명 |
| `guide` | string | 템플릿에 적힌 안내문 |
| `occurrences` | int | 템플릿 안 등장 횟수 |
| `filled` | bool | 템플릿 자체에 값이 이미 적혀 있는가 |
| `current_value` | string | 템플릿에 적힌 현재 값 |
| `source` | string | `field`(누름틀) / `slot`(본문 슬롯) |
| `value` | string | 편집 view 에서만 — 세션 값 (없으면 `""`) |

`block` = `{text: string, style_ref: string}`

**편집 view** (`session_view.compose_view`) — `/preview`·`PATCH /values`·`DELETE /values`·`PUT /blocks` 공통 본문

| 필드 | 타입 | 설명 |
|---|---|---|
| `template_id` | string | 확정된 템플릿 |
| `session_id` | string | 요청 값 (없으면 `""`) |
| `markdown` | string | 채운 결과 미리보기. `preview=false` 면 `""` |
| `truncated` | bool | 미리보기가 `MAX_PREVIEW_CHARS` 에서 잘렸는가 |
| `fields` | field[] | `value` 포함 |
| `values` | object | `{항목명: 값}` — 지금 템플릿에 있는 항목만 |
| `fields_missing` | string[] | 비어 있는 항목 |
| `ready_for_download` | bool | `fields_missing` 이 비었는가 |
| `formats` | string[] | 항상 `["hwpx"]` |
| `blocks` | block[] | 본문 추가 블록 |
| `block_styles` | string[] | 블록 서식 선택지 (`BODY_BLOCKS` 꺼지면 `[]`) |

---

### GET /health

| 항목 | 값 |
|---|---|
| 용도 | 헬스체크 |
| 호출자 | GenOS 상태 확인 |
| 성공 | `200` — `{"status": "ok"}` |
| 오류 | 없음 |

### GET / , GET ""

| 항목 | 값 |
|---|---|
| 용도 | 게이트웨이가 경로 없이 베이스를 칠 때의 응답 |
| 호출자 | 확인 안 됨 |
| 성공 | `200` — `{"service": "template-fill-service", "status": "ok"}` |
| 오류 | 없음 |

### GET /prompts

| 항목 | 값 |
|---|---|
| 용도 | 프롬프트를 라이브러리(`TEMPLATE_FILL_PROMPT_IDS`)와 파일 중 어디서 받았는지. 본문은 싣지 않는다 |
| 호출자 | 관리자 |
| 인증 | 없음 |
| 성공 | `200` — `{"prompts": [{name, configured, prompt_id, source, reason}]}` (글다듬이·FAQ 와 같은 모양) |
| 오류 | 없음 |

### POST /prompts/reload

| 항목 | 값 |
|---|---|
| 용도 | 프롬프트 라이브러리를 즉시 다시 읽는다 |
| 호출자 | 관리자 |
| 헤더 | `x-admin-token` (토큰 설정 시 필수·일치) |
| 성공 | `200` — `{"prompts": [...]}` |
| 오류 | 403 `ERR-03-00020003` 템플릿 등록·삭제 권한이 없습니다. (`ERR_API_ADMIN_FORBIDDEN`) |

### GET /templates

| 항목 | 값 |
|---|---|
| 용도 | 등록된 템플릿 목록 + 캐시에 있는 색인 정보 (목록 조회가 파싱을 일으키지 않는다) |
| 호출자 | 프론트 |
| 요청 | 없음 |
| 성공 | `200`, `application/json` |
| 오류 | 확인된 `ApiError` 분기 없음 |

| 필드 | 타입 | 설명 |
|---|---|---|
| `templates` | string[] | 템플릿 id 목록 |
| `items[].template_id` | string | |
| `items[].indexed` | bool | 색인 캐시가 있는가 (없으면 `/fields` 첫 호출이 만든다) |
| `items[].field_count` | int \| null | 색인 없으면 `null` |
| `items[].table_count` | int \| null | |
| `items[].indexed_at` | float \| null | **epoch 초** (`time.time()`) |
| `formats` | string[] | `["hwpx"]` |

```json
{ "templates": ["보도자료"],
  "items": [{"template_id": "보도자료", "indexed": true, "field_count": 5, "table_count": 2, "indexed_at": 1790000000.0}],
  "formats": ["hwpx"] }
```

### POST /templates

| 항목 | 값 |
|---|---|
| 용도 | 관리자 템플릿 등록 — 파싱·색인을 먼저 하고 성공하면 볼륨에 쓴다 |
| 호출자 | 관리자 |
| 요청 | `multipart/form-data`, 헤더 `x-admin-token` |

| 필드 | 종류 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `template` | File | 예 | — | 파일명이 `.hwpx` 로 끝나야 함, 비어 있지 않음, `MAX_UPLOAD_BYTES` 이하 |
| `template_id` | Form str | 아니오 | `null` | 생략 시 업로드 파일명. `.hwpx` 접미어 제거, `[\w\-. ()\[\]가-힣]+`, `.` 시작·`..`·경로 구분자 금지 |
| `overwrite` | Form bool | 아니오 | `false` | 같은 id 가 있을 때 덮어쓸지 |

**성공** — 새로 만들면 `201`, 덮어쓰면 `200`, `application/json`

| 필드 | 타입 | 설명 |
|---|---|---|
| `template_id` | string | 정규화된 id |
| `overwritten` | bool | 기존 파일을 덮었는가 |
| `content_hash` | string | 템플릿 내용 해시 |
| `fields` | field[] | `value` 없음 |
| `block_styles` | string[] | |
| `markdown` | string | 템플릿 원본 마크다운 |
| `markdown_truncated` | bool | |
| `bare_braces` | string[] | 채울 자리로 보지 않은 따옴표 없는 `{…}` |

**오류**

| HTTP | `error_code` | 원인 / `msg` |
|---|---|---|
| 403 | `ERR-03-00020003` | `TEMPLATE_FILL_API_ADMIN_FORBIDDEN` |
| 400 | `ERR-03-00020003` | hwpx 파일만 업로드할 수 있습니다. / 파일 크기가 상한({N}MB)을 초과했습니다. / 업로드한 파일이 비어 있습니다. |
| 400 | `ERR-03-00020003` | 템플릿 이름에 쓸 수 없는 문자가 있습니다. |
| 400 | `ERR-03-00020003` | 템플릿 해석 실패 (`TemplateError` 안내문) |
| 409 | `ERR-03-00020003` | `TEMPLATE_FILL_API_TEMPLATE_EXISTS` — 있고 `overwrite=false` |
| 500 | `ERR-03-00020002` | 템플릿을 저장하지 못했습니다. (`ERR_API_INTERNAL`) |
| 422 | — | FastAPI 기본 — `template` 누락 |

### DELETE /templates/{template_id}

| 항목 | 값 |
|---|---|
| 용도 | 관리자 템플릿 삭제 — 파일과 색인 캐시를 함께 없앤다 |
| 호출자 | 관리자 |
| 경로 | `template_id` (string) |
| 헤더 | `x-admin-token` |
| 성공 | `200` — `{"template_id": "<id>", "deleted": true}` |

**오류**

| HTTP | `error_code` | 원인 / `msg` |
|---|---|---|
| 403 | `ERR-03-00020003` | `TEMPLATE_FILL_API_ADMIN_FORBIDDEN` |
| 400 | `ERR-03-00020003` | 템플릿 이름에 쓸 수 없는 문자가 있습니다. |
| 404 | `ERR-03-00020003` | `TEMPLATE_FILL_API_TEMPLATE_NOT_FOUND` |
| 500 | `ERR-03-00020002` | 템플릿을 삭제하지 못했습니다. |

### GET /fields

| 항목 | 값 |
|---|---|
| 용도 | 템플릿 항목 스키마 + 본문 블록 서식 목록. 색인이 없으면 이때 만든다 |
| 호출자 | 프론트 |
| 쿼리 | `template_id` (string, 필수) |
| 성공 | `200` |

| 필드 | 타입 | 설명 |
|---|---|---|
| `template_id` | string | 요청 값 |
| `fields` | field[] | `value` 없음 |
| `block_styles` | string[] | `BODY_BLOCKS` 꺼지면 `[]` |
| `from_cache` | bool | 색인을 캐시에서 읽었는가 |

**오류**: 404 템플릿 없음, 400 해석 실패, 422 `template_id` 누락.

### GET /status

| 항목 | 값 |
|---|---|
| 용도 | 세션 채움 현황 (미리보기 없는 가벼운 경로, 다운로드 버튼 활성화 판단) |
| 호출자 | 프론트 (확인되는 호출부 없음) |
| 쿼리 | `session_id` (필수), `template_id` (선택 — 없으면 세션의 템플릿) |
| 성공 | `200` |

| 필드 | 타입 | 설명 |
|---|---|---|
| `template_id` | string | 확정된 템플릿 |
| `session_id` | string | |
| `values` | object | 지금 템플릿에 있는 항목 값 |
| `fields_missing` | string[] | |
| `block_count` | int | 본문 블록 수 (`ready` 에 관여하지 않음) |
| `ready_for_download` | bool | |
| `formats` | string[] | `["hwpx"]` |

**오류**: 400 session_id 형식, 404 템플릿 없음(세션에도 템플릿이 없으면 빈 id 로 404), 400 해석 실패, 422 `session_id` 누락.

### GET /preview

| 항목 | 값 |
|---|---|
| 용도 | 지금 값으로 채운 결과를 마크다운으로 (표시 전용, 세션 변경 없음). 세션 없이 템플릿 원본만도 가능 |
| 호출자 | 프론트 |
| 쿼리 | `session_id` (선택), `template_id` (선택) — 둘 다 없으면 템플릿 id 가 비어 404 |
| 성공 | `200` — **편집 view** (공통 절) |

**오류**: 400 session_id 형식·해석 실패, 404 템플릿 없음, 500 `ERR-03-00020002` "미리보기를 만들지 못했습니다."

### PATCH /values

| 항목 | 값 |
|---|---|
| 용도 | 화면에서 고친 항목 값을 세션에 반영. 템플릿에 없는 항목명은 기각, 빈 값은 지움 |
| 호출자 | 프론트 (선택 경로) |
| 요청 | `application/json` — `ValuePatchRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `session_id` | string | 예 | — | `max_length=256` |
| `template_id` | string \| null | 아니오 | `null` | `max_length=256`. 없으면 세션의 템플릿 |
| `values` | object<string,string> | 아니오 | `{}` | 건수 ≤ `MAX_FIELDS`. 값은 trim 후 `MAX_VALUE_CHARS` 로 자름. 빈 값 = 지움 |
| `preview` | bool | 아니오 | `true` | `false` 면 `markdown` 을 만들지 않음 |

**성공** — `200`, 편집 view + `updated_fields`(string[]), `cleared_fields`(string[]), `rejected_fields`(string[]) — 모두 정렬됨.

**오류**: 400 "values 개수가 상한({N}건)을 초과했습니다.", 400 session_id 형식·해석 실패, 404 템플릿 없음, 500 `ERR-03-00020002` 세션 저장 실패(`msg` = `session_store` 고정 안내문) / 미리보기 실패, 422 바디 검증.

### DELETE /values

| 항목 | 값 |
|---|---|
| 용도 | 세션의 항목 값을 여러 개 비운다 |
| 호출자 | 프론트 (선택 경로) |
| 요청 | `application/json` 바디 — `ValueDeleteRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약 |
|---|---|---|---|---|
| `session_id` | string | 예 | — | `max_length=256` |
| `template_id` | string \| null | 아니오 | `null` | `max_length=256` |
| `fields` | string[] | 아니오 | `[]` | 지울 항목명 |
| `preview` | bool | 아니오 | `true` | |

**성공** — `200`, 편집 view + `deleted_fields`(세션에서 실제로 지운 것), `rejected_fields`(템플릿에 없는 이름), `still_filled_in_template`(템플릿 자체에 값이 적혀 있어 지운 뒤에도 채워진 것으로 보이는 항목).

**오류**: `PATCH /values` 와 같음 (상한 검사 제외).

### PUT /blocks

| 항목 | 값 |
|---|---|
| 용도 | 본문 블록 목록을 세션에 **통째로 교체** (빈 배열 = 전부 삭제). 글다듬이를 거치지 않는다 |
| 호출자 | 프론트 (선택 경로) |
| 요청 | `application/json` — `BlockPutRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `session_id` | string | 예 | — | `max_length=256` |
| `template_id` | string \| null | 아니오 | `null` | `max_length=256` |
| `blocks` | array | 아니오 | `[]` | 원소는 `{text, style_ref}`(또는 `style`) 객체나 문자열. 서식 이름이 목록에 없으면 기본 서식으로 떨어뜨리고 `rejected_blocks` 에 적는다. `MAX_BLOCKS` 초과분은 기각 |
| `preview` | bool | 아니오 | `true` | |

**성공** — `200`, 편집 view + `rejected_blocks`(string[] — `<blocks: …>` 형태의 사유 문자열 포함).

**오류**: 400 "본문 추가 기능이 꺼져 있습니다."(`BODY_BLOCKS` 꺼짐), 그 밖은 `PATCH /values` 와 같음.

### POST /generate

| 항목 | 값 |
|---|---|
| 용도 | 등록 템플릿 + 세션 값(+요청 값)으로 hwpx 초안을 만들어 바이너리로 내려준다. 성공하면 세션을 종료한다 |
| 호출자 | 프론트 (`download_url` 이 `null` 일 때 폴백) |
| 요청 | `application/json` — `GenerateRequest` |

| 필드 | 타입 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `template_id` | string \| null | 조건부 | `null` | `max_length=256`. 없으면 세션의 템플릿 |
| `session_id` | string \| null | 조건부 | `null` | `max_length=256`. 있으면 세션 값·블록을 읽는다 |
| `values` | object<string,string> \| null | 아니오 | `null` | 세션 값 위에 덮어쓴다. 건수 ≤ `MAX_FIELDS`, 값은 `MAX_VALUE_CHARS` 로 자름 |
| `filename` | string \| null | 아니오 | `null` | `max_length=128`. 없으면 `{template_id}_초안` |
| `format` | string \| null | 아니오 | `null` | `max_length=8`. 소문자·trim 후 `hwpx` 만 허용 |
| `blocks` | array \| null | 아니오 | `null` | 생략 시 세션의 블록. `BODY_BLOCKS` 꺼지면 무시 |

**성공** — `200`, 바이너리. 값이 없는 슬롯은 표기만 지운 **부분 초안**도 성공이다.

| 헤더 | 값 |
|---|---|
| `Content-Type` | `application/octet-stream` |
| `Content-Disposition` | `attachment; filename*=UTF-8''<퍼센트 인코딩된 이름>.hwpx` (요청 이름의 `.hwpx` 접미어는 떼고 다시 붙인다) |
| `X-Missing-Fields` | 비어 있는 항목명, `,` 로 잇고 퍼센트 인코딩 |
| `X-Written-Fields` | 채운 항목명 (같은 인코딩) |
| `X-Styled-Fields` | 서식을 적용한 항목명 (같은 인코딩) |
| `X-Body-Blocks` | 덧붙인 본문 블록 수 |
| `X-Document-Format` | `hwpx` |

**오류**

| HTTP | `error_code` | 원인 / `msg` |
|---|---|---|
| 400 | `ERR-03-00020003` | 지금은 hwpx 로만 내려받을 수 있습니다. |
| 400 | `ERR-03-00020003` | session_id 가 올바르지 않습니다. |
| 400 | `ERR-03-00020003` | values 개수가 상한({N}건)을 초과했습니다. |
| 404 | `ERR-03-00020003` | `TEMPLATE_FILL_API_SESSION_NOT_FOUND` — `session_id` 를 줬는데 세션 값이 없고 `values` 도 없음 |
| 404 | `ERR-03-00020003` | `TEMPLATE_FILL_API_TEMPLATE_NOT_FOUND` — 템플릿 id 없음/파일 없음 |
| 400 | `ERR-03-00020003` | 조립·블록 서식 추출 중 `TemplateError` 안내문 |
| 500 | `ERR-03-00020002` | `TEMPLATE_FILL_API_INTERNAL` — 조립 중 예상 밖 예외 |
| 422 | — | FastAPI 기본 — 길이·타입 위반 |

### POST /generate/upload

| 항목 | 값 |
|---|---|
| 용도 | 등록 없이 업로드한 hwpx 를 채워 내려준다. 처리 규칙은 `/generate` 와 같다. `session_id` 가 있으면 성공 후 세션 종료 |
| 호출자 | 확인 안 됨 |
| 요청 | `multipart/form-data` |

| 필드 | 종류 | 필수 | 기본값 | 제약·동작 |
|---|---|---|---|---|
| `template` | File | 예 | — | `.hwpx` 파일명, 비어 있지 않음, `MAX_UPLOAD_BYTES` 이하 |
| `session_id` | Form str | 아니오 | `null` | 세션 값·블록을 읽는다 (세션이 비어도 404 를 내지 않는다) |
| `values` | Form str | 아니오 | `null` | **JSON 객체 문자열**. 건수 ≤ `MAX_FIELDS` |
| `blocks` | Form str | 아니오 | `null` | **JSON 배열 문자열**. 생략 시 세션 블록 |
| `filename` | Form str | 아니오 | `null` | 없으면 `{업로드 파일명 stem}_초안` |
| `format` | Form str | 아니오 | `null` | `hwpx` 만 |

**성공** — `/generate` 와 같은 바이너리·헤더.

**오류**: 400 hwpx 형식/크기/빈 파일, 400 "values 는 JSON 객체이어야 합니다." / "blocks 는 JSON 배열이어야 합니다.", 400 형식·session_id·상한·`TemplateError`, 500 `ERR-03-00020002` 조립 실패, 422 `template` 누락.

---

### POST /chat/context

| 항목 | 값 |
|---|---|
| 용도 | 스텝 1 — 세션·템플릿 확정, 항목 목록·현재 값 |
| 호출자 | 워크플로우 스텝 `sfr006_01_context` |
| 요청 | `application/json` — `ContextRequest` |

| 필드 | 타입 | 필수 | 기본값 | 동작 |
|---|---|---|---|---|
| `session_id` | string | 아니오 | `""` | 비면 빈 세션. Redis 장애·형식 오류도 빈 세션으로 진행 |
| `template_id` | string | 아니오 | `""` | 이번 턴 지정이 세션 값보다 우선 |

**성공** — `200`

| 필드 | 타입 | 설명 |
|---|---|---|
| `template_id` | string | |
| `field_names` | string[] | 항목명 (`MAX_FIELDS` 까지) |
| `block_styles` | string[] | |
| `field_values` | object | 세션의 현재 값 |
| `blocks` | block[] | |
| `fields_missing` | string[] | |
| `ready_for_download` | bool | |
| `template_markdown` | string | 템플릿 원본 마크다운 |
| `template_markdown_truncated` | bool | |
| `from_cache` | bool | 색인 캐시 사용 여부 |

**오류** (전부 HTTP 500): `ERR-02-00020003` `TEMPLATE_FILL_TEMPLATE_NOT_FOUND`(id 없음·불가·파일 없음) / `TEMPLATE_FILL_TEMPLATE_INVALID` / `TEMPLATE_FILL_NO_FIELDS`.

### POST /chat/prefill

| 항목 | 값 |
|---|---|
| 용도 | 업로드 문서로 빈 항목을 자동 채움 (비스트리밍). **저장하지 않는다** — 값만 돌려주고 `/chat/commit` 이 병합 |
| 호출자 | 워크플로우 스텝 `sfr006_03_commit` (스트리밍 폴백) |
| 요청 | `application/json` — `PrefillRequest` |

| 필드 | 타입 | 필수 | 기본값 | 동작 |
|---|---|---|---|---|
| `session_id` | string | 아니오 | `""` | |
| `template_id` | string | 아니오 | `""` | |
| `document` | string | 아니오 | `""` | 업로드 문서 본문 (trim) |
| `overwrite` | bool | 아니오 | `false` | 찬 항목도 문서 값으로 바꾼다. 켜면 `already_applied`·`no_pending_fields` 게이트를 건너뛴다 |

**건너뛰기 판정** (순서대로): `TEMPLATE_FILL_DOC_PREFILL` 꺼짐 → `disabled`, 문서 없음 → `no_document`, (`overwrite` 아니면) 세션에 같은 문서 해시 → `already_applied`, 빈 항목 없음 → `no_pending_fields`.

**성공** — `200` (자동 채움 실패도 200 — `prefill_failed=true`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `applied` | bool | 채운 값이 하나라도 있는가 (건너뛰면 `false`) |
| `skipped_reason` | string | `""` / `disabled` / `no_document` / `already_applied` / `no_pending_fields` |
| `template_id` | string | |
| `fields_prefilled` | object | `{항목명: 값}` |
| `source_doc_hash` | string | 문서 sha256 앞 16자. `disabled`·`no_document` 면 `""` |
| `prefill_failed` | bool | 자동 채움이 실패했는가 |
| `chunk_count` | int | 문서 조각 수 |
| `chunks_called` | int | 호출한 조각 수 |

```json
{ "applied": true, "skipped_reason": "", "template_id": "보도자료", "fields_prefilled": {"제목": "…"},
  "source_doc_hash": "a1b2c3d4e5f60718", "prefill_failed": false, "chunk_count": 2, "chunks_called": 2 }
```

**오류**: `/chat/context` 와 같은 템플릿 오류 (HTTP 500, `ERR-02-00020003`).

### POST /chat/prefill/stream

| 항목 | 값 |
|---|---|
| 용도 | `/chat/prefill` 과 같은 계산을 SSE 로 — 진행 상황(조각 시작, 항목이 닫히는 대로 `✔ 항목: 값`)을 먼저 흘리고 마지막에 같은 본문 |
| 호출자 | 워크플로우 스텝 `sfr006_03_commit` |
| 요청 | `/chat/prefill` 과 동일 (`PrefillRequest`) |

**흘리기 전 실패** — 템플릿 확정(`_load_turn`)은 스트림을 열기 전에 하므로 템플릿 오류는 **JSON 오류**(HTTP 500, `ERR-02-00020003`)로 나간다.

**성공** — `200`, `text/event-stream`, 헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no`. 프레임 `data: <JSON>\n\n` (`event:` 줄 없음).

| 프레임 `type` | 필드 | 설명 |
|---|---|---|
| `delta` | `text` | 진행 문구 한 줄 (끝에 `\n`). 예: `(1/3) 문서를 확인하고 있습니다…`, `✔ 제목: …`(값 60자에서 `…`), `(2/3) 이 구간은 확인하지 못해 건너뜁니다.`, `(2/3) 이 구간은 끝까지 읽지 못해 위 값은 반영하지 않았습니다.` (조각이 하나면 `(i/n)` 없음) |
| `done` | `/chat/prefill` 성공 필드 전부 + `type` | 종료 프레임 |

- 건너뛰는 경우는 `delta` 없이 `done` 한 번.
- `error` 프레임은 없다. 계산 중 예상 밖 예외가 나면 `done` 없이 스트림이 끝난다 (`prefill_from_document` 는 예외를 올리지 않는 계약).

```
data: {"type": "delta", "text": "✔ 제목: 2026년 상반기 실적\n"}

data: {"type": "done", "applied": true, "skipped_reason": "", "template_id": "보도자료", "fields_prefilled": {"제목": "2026년 상반기 실적"}, "source_doc_hash": "…", "prefill_failed": false, "chunk_count": 1, "chunks_called": 1}
```

### POST /chat/extract

| 항목 | 값 |
|---|---|
| 용도 | 스텝 2 — 발화에서 값·삭제·본문 블록을 LLM 으로 뽑고 코드로 화이트리스트 검증. **저장하지 않는다** |
| 호출자 | 워크플로우 스텝 `sfr006_02_extract` |
| 요청 | `application/json` — `ExtractRequest` |

| 필드 | 타입 | 필수 | 기본값 | 동작 |
|---|---|---|---|---|
| `session_id` | string | 아니오 | `""` | |
| `template_id` | string | 아니오 | `""` | |
| `question` | string | 사실상 필수 | `""` | trim 후 `MAX_MESSAGE_CHARS`(20000)로 자름. 비면 LLM 을 부르지 않고 빈 추출 결과(200) |

**성공** — `200`

| 필드 | 타입 | 설명 |
|---|---|---|
| `fields_updated` | object | 채택된 `{항목명: 값}` |
| `fields_cleared` | string[] | 지울 항목 |
| `fields_rejected` | string[] | 템플릿에 없어 기각한 항목명 |
| `blocks_added` | block[] | 추가할 본문 블록 |
| `block_clears` | int[] | 지울 블록 번호 (0부터, 오름차순, 범위 검사됨) |
| `use_document` | bool | "문서 내용으로 바꿔줘" 지시 — 스텝 3 이 prefill `overwrite` 로 넘긴다 |

**오류** (전부 HTTP 500)

| `error_code` | 원인 |
|---|---|
| `ERR-02-00020003` | `TEMPLATE_FILL_TEMPLATE_NOT_FOUND` / `_TEMPLATE_INVALID` / `_NO_FIELDS` |
| `ERR-02-00020003` | `TEMPLATE_FILL_INTERNAL_UNCLASSIFIED` — 프롬프트 렌더 실패, LLM 호출 준비 실패 |
| `ERR-02-00020003` | `TEMPLATE_FILL_CONFIG_MISSING` — `GENOS_URL`/`LLM_SERVING_ID` 부재 |
| `ERR-02-00020001` | `TEMPLATE_FILL_UPSTREAM_TIMEOUT` — 통신 실패 |
| `ERR-02-00020002` | `TEMPLATE_FILL_UPSTREAM_EXECUTION_FAILED` — 그 밖 LLM 실패 |

### POST /chat/commit

| 항목 | 값 |
|---|---|
| 용도 | 스텝 3 — 자동 채움분 → 발화분 순으로 병합, 새 본문 블록은 글다듬이로 다듬어 넣고, 세션 저장, 미리보기, 답변 문구. 다 채웠으면 hwpx 를 굳혀 업로드 |
| 호출자 | 워크플로우 스텝 `sfr006_03_commit` |
| 요청 | `application/json` — `CommitRequest` |

| 필드 | 타입 | 필수 | 기본값 | 동작 |
|---|---|---|---|---|
| `session_id` | string | 아니오 | `""` | 비면 저장하지 않음 |
| `template_id` | string | 아니오 | `""` | |
| `fields_updated` | object | 아니오 | `{}` | `/chat/extract` 결과 |
| `fields_prefilled` | object | 아니오 | `{}` | `/chat/prefill` 결과. 화이트리스트 밖·(덮어쓰기 아니면) 이미 값이 있는 항목은 버림 |
| `source_doc_hash` | string | 아니오 | `""` | 이번 턴 문서 해시. 세션 목록에 더한다 |
| `prefill_failed` | bool | 아니오 | `false` | 답변 문구용 |
| `prefill_skipped_reason` | string | 아니오 | `""` | 답변 문구용 (`no_pending_fields` 만 한 줄) |
| `prefill_overwrite` | bool | 아니오 | `false` | 찬 항목도 문서 값으로 병합 |
| `fields_cleared` | array | 아니오 | `[]` | |
| `fields_rejected` | array | 아니오 | `[]` | 답변 문구에 기각 항목으로 실린다 |
| `blocks_added` | array | 아니오 | `[]` | 서식 재검증 후 글다듬이(`POST /polish`)로 다듬어 추가. 실패해도 원문으로 넣는다 |
| `block_clears` | array | 아니오 | `[]` | |

**성공** — `200`

| 필드 | 타입 | 설명 |
|---|---|---|
| `text` | string | 채팅 답변 문구 (채운 값·`이전 → 새`·기각·남은 항목) |
| `field_values` | object | 병합 후 값 |
| `fields_filled` | string[] | |
| `fields_missing` | string[] | |
| `ready_for_download` | bool | |
| `download_url` | string \| null | 다 채웠을 때만 hwpx 를 올린 링크 (`{template_id}_초안.hwpx`). 덜 채웠거나 업로드 실패면 `null` |
| `blocks` | block[] | 병합 후 블록 |
| `blocks_removed` | int | 지운 블록 수 |
| `document_markdown` | string | 미리보기 (실패해도 `""` 로 진행) |
| `document_markdown_truncated` | bool | |

**오류** (전부 HTTP 500): 템플릿 오류 3종(`ERR-02-00020003`), 세션 저장 실패 `ERR-02-00020003` `TEMPLATE_FILL_INTERNAL_UNCLASSIFIED`.

---

