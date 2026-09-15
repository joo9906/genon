# GENOS_RULES.md — 개발가이드 v1.02 강제 규칙 요약

> 출처: `260721_GenOS_엔지니어_개발가이드_v1.02.pdf`
> 이 파일은 **코드를 쓰기 전에 읽는 체크리스트**다. 조항 번호는 원문 절 번호.
>
> 이 요약본은 원문에서 뽑아 쓴 파생 문서이며 `CHECKSUMS.txt` 봉인 대상이 아니다
> (봉인 대상은 `source/` 원본 17개와 PDF). 원문을 더 읽으면 여기에 반영한다.
> **2026-08-06 갱신**: 6장(코드 서빙) 전체와 11.5.6·11.5.7 을 원문에서 다시 읽어 §E 를
> 재작성하고 §C 에 로거·trace 항목을 추가했다.

---

## A. 오류 처리 (3.9) — 가장 자주 틀리는 부분

### A.1 형식: `{영역코드}-{공통오류코드}`

**영역 코드 (3.9.1)**
| 코드 | 영역 |
|---|---|
| 01 | MCP |
| 02 | 워크플로우 Python 단계 |
| 03 | 코드 서빙 |
| 04 | Flowise Custom JS Function |
| 05 | 전처리기 |
| 06 | 평가지표 |

**공통 오류 코드 (3.9.2) — 이 3개가 전부다. 새로 만들지 마라.**
| 코드 | 조건 | 재시도 |
|---|---|---|
| `00020001` | 외부 API와 **통신 자체 실패** — 연결실패/DNS/timeout/HTTP 502·503·504 | O |
| `00020002` | 통신은 됐는데 **응답 본문이 실행 실패**를 나타냄 | 조건부 |
| `00020003` | 통신 오류가 아닌 **나머지 전부** — 입력검증, JSON파싱, 인증, 리소스없음, 내부오류 | X |

> 입력 오류·인증 오류·404에 별도 숫자코드를 만들지 않는다. 전부 `00020003`이고,
> 구분은 `error_type`(내부 로그용)과 `msg`(사용자용)로 한다.

**외부 API 결과 판정 순서**
1. 연결실패/timeout/비정상 HTTP → `00020001`
2. HTTP는 정상인데 body가 실패 → `00020002`
3. JSON 변환 실패, 내 코드 처리 실패 → `00020003`

### A.2 HTTP 상태 매핑 (3.9.3, 코드 서빙)
| 종류 | 공통코드 | HTTP |
|---|---|---|
| INPUT | 00020003 | 400 / 422 |
| AUTH | 00020003 | 401 / 403 |
| RESOURCE | 00020003 | 404 |
| STATE | 00020003 | 409 |
| LIMIT | 00020003 | 429 |
| INTERNAL | 00020003 | 500 |
| UPSTREAM 통신실패(재시도O) | 00020001 | 502/503/504 |
| UPSTREAM 4xx(재시도X) | 00020001 | 연계 API 기준 변환 |
| UPSTREAM 실행실패 | 00020002 | 502 |

### A.3 응답 형식 (3.9.4)
```json
{"error_code": "03-00020001", "msg": "외부 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.", "detail": "crm timeout"}
```
- `msg`: 사용자가 읽을 문장. 가능하면 **항상** 반환
- `detail`: 선택. **예외 원문 그대로 넣지 마라.** 사용자 입력 / LLM 출력 / 문서 원문 / SQL / 토큰 / 내부 URL / stack trace / 외부 응답 본문 **전부 제외**. 섞일 가능성 있으면 `detail`을 빼고 내부 로그에만 남긴다.

### A.4 영역별 전달 방법 (3.9.5) ⚠️ 영역마다 다르다
| 영역 | 방법 |
|---|---|
| 워크플로우 (일반) | `data["error"]`에 오류 객체 넣어 반환 → 다음 step이 `data.get("error")`로 분기 |
| 워크플로우 (스트리밍) | `yield {"event":"error","data":{...}}` 후 `return`. **단, error 이벤트는 다음 step의 data를 바꾸지 않는다.** 다음 step에 넘겨야 하면 `{"event":"result","data":{**data,"error":{...}}}` |
| 코드 서빙 | HTTP 상태 + body에 `error_code`/`msg`/`detail`. 채팅 연계 시 `msg`만 전달될 수 있으니 **내부 로그에도 같은 코드 기록** |
| Flowise | `{ "error": { ... } }` 객체 반환 |
| 전처리기 | 로그에 오류코드 기록 후 **예외 발생**. 반환값은 `list[dict]`여야 하므로 오류 객체 반환 금지 |
| 평가지표 | 로그 기록 후 **예외 발생**. 반환값은 숫자 점수여야 함 |

---

## B. 외부 호출 (3.6)

- **모든 외부 호출에 timeout 필수**
- 전체 처리시간 안에서 개별 호출 제한을 잡는다 (예: 전체 30s → 개별 10s → 최대 2회 시도)
- **재시도 대상**: timeout, HTTP 502/503/504
- **재시도 제외**: 입력 오류, 인증 실패, 일반 4xx (400/401/403/404/422)
- **횟수 제한 없는 재시도 루프 금지**

```python
timeout = httpx.Timeout(connect=3.0, read=20.0, write=5.0, pool=3.0)
async with httpx.AsyncClient(timeout=timeout) as client:
    response = await client.get(url)
```

- **K8s Service DNS 직접 호출 금지.** 반드시 `/api/gateway/...` 경로. 직접 호출하면 인증·실행기록이 빠진다.
- 사용자 입력으로 URL을 만들 때는 `https` scheme + 사전 정의 host allowlist만 허용

---

## C. 시크릿 · 로깅 (3.7 / 3.8)

**시크릿**
- API Key/토큰/비밀번호/접속정보 **하드코딩 금지** (코드·패키지·저장소 전부)
- 영역별 환경변수 주입 사용. 누락 시 **실제 값을 포함하지 않은 메시지로 즉시 실패**
- 환경변수 이름은 용도가 드러나게. `TOKEN`, `URL`, `KEY1` 금지

**시크릿 등록 위치 (11.5.4)**
| 영역 | 위치 |
|---|---|
| 워크플로우 Python 단계 | 리비전 정보 > 환경 변수 |
| 코드 서빙 | 리비전 상세 > 환경 설정 > 환경 변수 |
| 전처리기 | 생성·수정 화면의 환경 변수 |
| Flowise | 워크플로우의 `$vars` |
| MCP 도구 | 중요 정보 > 환경 변수 |

**로깅**
- Python: GenOS 로거. `print()` 금지 / JS stdio MCP: `console.log` 금지(stdout 오염), `console.error` 사용
- 로그가 안 보이면 (11.5.7) GenOS 제공 로거를 쓰는지 확인한다:
  `from common.logger import Logger; logger = Logger.getLogger(__name__)`.
  출력은 **컨테이너 stdout** 을 통해 GenOS 로그 시스템에 수집된다.
- Trace 연계: 워크플로우가 넣어 준 `data["genos_state"]["trace_id"]` 를 로그에 포함하면
  요청 간 로그를 같은 식별자로 검색할 수 있다. 단 GenOS Trace 화면은 `genos_trace_id` 로
  상세 URL을 만들므로, **임의의 extra 필드가 자동으로 링크가 된다고 가정하지 않는다.**
- 기록 허용 필드만: `event, trace_id, request_id, resource_id, status, duration_ms, item_count, upstream_status, error_code, error_type`
- **기록 금지**: Authorization, Cookie, access_token, refresh_token, api_key, password, 전체 request/response body, **사용자 질문과 LLM 응답 전문**, **문서 원문**, 개인정보, DB 오류 원문, 인증정보 포함 query string

```python
logger.warning("CRM request timed out", extra={
    "event": "upstream_timeout", "trace_id": trace_id,
    "resource_id": "crm", "duration_ms": 10_000,
    "error_type": "TimeoutException",
})
```

---

## D. 워크플로우 Python 단계 (5장)

### D.1 시그니처 — 4가지 중 택1, 섞지 마라
```python
# ① 동기 — CPU 위주
def run(data: dict) -> dict: ...

# ② async — 외부 I/O (권장)
async def run(data: dict) -> dict: ...

# ③ async generator — 토큰 스트리밍
async def run(data: dict):
    async for chunk in ...:
        yield {"event": "token", "data": chunk}
    yield {"event": "result", "data": {**data, "text": acc}}

# ④ sync generator — 드물게
```
- 함수명은 **정확히 `run`**. `Run`/`main`/`execute` → `run function not found` + HTTP 500
- 들여쓰기·구문 오류로 함수가 정의 안 돼도 같은 메시지가 뜬다
- generator는 **마지막 `event: result`의 `data`가 다음 step의 새 `data`**. 안 보내면 이전 `data`가 그대로 흐른다

### D.2 잘못된 예 (5.7) — 그대로 외워라
```python
async def main(data): ...              # ✗ 함수명 → run function not found
async def run(data):
    yield {...}; return data           # ✗ return + yield 혼용 → SyntaxError
db = pymongo.MongoClient(...)          # ✗ 전역 = 컨테이너 부팅 시 1회. connection leak
return {"answer": "..."}               # ✗ data 통째 교체 → genos_state 손실
                                       #   → return {**data, "answer": "..."}
requests.get(...)                      # ✗ blocking I/O → 이벤트 루프 정지
                                       #   → httpx.AsyncClient 또는 asyncio.to_thread
print(data)                            # ✗ 로그 시스템에 안 잡힘 → logger.info(..., extra={})
```

### D.3 컨테이너 (5.5)
- Base image: `python:3.10.19` + poetry
- 사용 가능 모듈: `asyncio, httpx, json, datetime, re, opentelemetry.*, GenOS Logger`
- **워크플로우 단계는 임의 패키지 추가 불가** — workflow image에 포함된 것만 사용
  (MCP 도구는 관리 > 리소스 > PyPI 패키지 사전 등록 가능)

### D.4 스트리밍 주의
- `event: token` 전송 중 `sourceDocuments`를 보내면 UI token 흐름이 깨진다 → buffering 후 마지막에
- `event: end`는 **가장 마지막 1회만**
- 단일 `return` 함수는 중간 token을 전달하지 않는다 (스트리밍이 일괄 반환되는 원인)

---

## E. 코드 서빙 (6장)

### E.1 실행 구조 — **Git 저장소가 배포 단위다** (6.1, 11.2)

GenOS가 **Git 저장소를 가져와** 언어별 기본 이미지에서 빌드하고 실행한다.
화면에 코드를 붙여넣는 방식이 아니다.

- 생성: 서빙 > 코드 서빙 > 코드 서빙 생성 에서 제목·관리 그룹·**저장소 유형과 Git 저장소 정보**
- 리비전 추가: 도커 이미지, 인스턴스 타입, GPU 할당량, 복제본, **브랜치, 커밋 해시**
  (같은 코드를 다시 받을 수 있도록 **커밋 해시를 쓴다** — 브랜치만 지정하지 않는다)
- 리비전 상세 탭 4개: 기본 정보 / 컨테이너 상태 / **환경 설정** / **컨테이너 서비스**
  - 언어·빌드 커맨드·시작 커맨드·환경 변수 → **환경 설정**
  - 워크플로우·전처리기·MCP 연계 경로 → **컨테이너 서비스**

### E.2 빌드·기동 설정 (6.3)

| 항목 | 예 |
|---|---|
| 빌드 (Build) 커맨드 | `pip install -r requirements.txt` |
| 시작 (Run) 커맨드 | `uvicorn main:app --host 0.0.0.0 --port $PORT` |

- **Python 은 저장소 루트의 `main.py` 또는 `src/main.py` 가 있으면 그 파일을 먼저 실행한다.**
  그 경로를 쓰지 않거나 다른 실행 명령이 필요하면 시작(Run) 커맨드를 반드시 등록한다.
  → 진입점이 패키지 안에 있는 구조(`pkg/main.py`)는 **Run 커맨드가 필수**다.
- 의존성 파일은 언어별로 다르다: Python `requirements.txt`/`pyproject.toml`,
  Node `package.json`+lock, Java `pom.xml`/`build.gradle`, Go `go.mod`/`go.sum`, C# `.csproj`.
- **사용자 Dockerfile 은 코드 서빙의 표준 등록 단위가 아니다.** OS 패키지나 별도 이미지가
  꼭 필요하면 운영 배포 방식과 **기본 이미지 변경 절차를 먼저 확인**한다.
- Python 외 언어는 해당 `template-code-serving-*` 이미지가 설치돼 있는지 시스템 이미지
  목록에서 먼저 확인한다.

### E.3 GenOS가 주입하는 환경변수 (6.3, 6.7)

`BUILD_COMMAND`, `START_COMMAND`, `LANGUAGE`, `PORT`, `OPENAPI_PATH` 를 실행 설정으로
전달한다. `PORT`=**8080**, `OPENAPI_PATH`=**/openapi.json** 이 기본값이며 **화면에서 입력하는
등록 항목이 아니다.** 애플리케이션에서 **같은 이름을 다른 목적으로 쓰지 않는다.**

시크릿은 리비전 상세 > 환경 설정 > 환경 변수 에 등록하고 **`.env` 를 저장소에 커밋하지 않는다.**

### E.4 HTTP 작성 기준 (6.4)

- `0.0.0.0` + GenOS가 주입하는 `$PORT`에 bind (`localhost` 만 열면 Gateway·상태확인이 못 붙는다)
- `GET /health` → **HTTP 200 고정 응답** 필수. 상태 확인 프로그램이 이 경로를 직접 호출한다
- 시작(Run) 커맨드는 foreground HTTP process
- async 핸들러 안에서 **동기 blocking 작업 직접 실행 금지** (6.9 잘못된 예 3) → `asyncio.to_thread`
- 업무 API의 경로와 요청·응답 항목은 **사용자 애플리케이션이 정한다**
- **`/json`·`/multipart` 는 Python `service(config, data)` 호환 방식에서만 자동 제공된다.**
  사용자 앱에서 이 경로를 필수로 가정하지 않는다 (6.9 잘못된 예 5) — 실제 route 와 등록 설정을 쓴다
- `repr(exc)` 나 stack trace 를 HTTP 응답 본문에 넣지 않는다. 상세 원인은 같은 `error_code` 와
  함께 내부 로그에만 남긴다

### E.5 GenOS 연계용 표준 경로 (6.5)

컨테이너 서비스 탭에서 코드 서빙을 다른 영역으로 쓰도록 설정할 때만 필요하다.

| 용도 | 기본 경로 | 비고 |
|---|---|---|
| 워크플로우로 사용 | `POST /chat` | 연계 설정에 등록한 요청·응답 항목 |
| 전처리기로 사용 | `POST /preprocess` | `{"code":0,"data":[...]}` 반환 |
| MCP 도구 목록 | `POST /mcp/list` | `{"code":0,"data":{"tools":[...]}}` |
| MCP 도구 호출 | `POST /mcp/call` | `{"code":0,"data":{"content":[...]}}` |

- 경로를 바꾸면 **등록 화면의 호출 경로와 애플리케이션 경로를 같은 값으로** 맞춘다.
- 코드 서빙 전처리기는 **호출 컨테이너와 파일 경로를 공유한다고 가정하지 않는다.**
  요청의 `file_content_base64` 를 디코딩해 처리하고, `file_path` 만 열어 처리하지 않는다.

### E.6 호출·검증 (6.8, 11.3)

```
${GENOS_URL}/api/gateway/code_serving/<id>/<앱이 정한 경로>   + Bearer 토큰
```

배포 검증은 health만으로 끝내지 않는다: **정상 / 입력검증 실패(422) / 외부 timeout(504)**
각각 실행하고, 예상 HTTP 상태와 응답 본문의 필수 key를 API 문서에 함께 적는다.

health check 실패 시 확인 순서 (11.5.3): `/health` 200 여부 → `0.0.0.0:$PORT` bind 여부 →
시작(Run) 커맨드가 foreground HTTP process 인지 → 빌드 산출물 경로와 명령의 일치 여부.

### E.7 패키지 추가 (11.5.6) — 영역마다 방법이 다르다

| 영역 | 방법 |
|---|---|
| 코드 서빙 | 의존성 파일 + **lock file** 갱신 후 빌드 커맨드에서 동일 설치 명령 실행 |
| 워크플로우 Python 단계 | **pod 기본 이미지에 포함된 패키지만** 사용 가능 → 운영팀에 기본 이미지 갱신 요청 |
| MCP 도구 | 관리 > 리소스 > PyPI 패키지 에 `.whl` 업로드 후 선택 |

폐쇄망이면 해당 registry 또는 mirror 접근 여부를 먼저 확인한다.

---

## F. 전처리기 (8장)

- 인자 없이 생성 가능한 `DocumentProcessor`, 비동기 `__call__(request, file_path, **kwargs)`
- 반환: `list[dict]`, 각 항목에 **`text` 키 필수** (임베딩이 직접 읽음), 빈 문자열 불가
- `page`, `i_chunk_on_doc`, 좌표 등 부가정보는 **실제로 쓰는 경우에만** 추가
- 오류 시 오류 객체를 chunk 목록에 넣지 말고 **예외를 던진다**
- 타입 내부 식별자: 첨부용=`attachment`, 적재용=`intelligent`, 변환용=`convert`
- 테스트 필수 케이스: 정상 / **빈 파일(빈 목록 아닌 명시적 오류)** / 손상 파일 / 미지원 확장자 / 파라미터 최소·최대 / 범위 밖
- 실패 실행 후 **임시 파일이 남지 않는지** 확인
- 전처리기 본문·확장자·파라미터를 바꾸면 AI Drive 파일이 `needs_reingest`가 된다. **자동 재적재 아님** → 수동 재적재

---

## G. Flowise Custom JS Function (7장) — 잘못된 예
```js
const token = "Bearer xoxb-...";                  // ✗ 시크릿 하드코딩
const r = syncRequest(...);                        // ✗ 동기 blocking
await axios.post(url, data);                       // ✗ timeout 없음
globalThis.cache[key] = value;                     // ✗ 실행마다 새 NodeVM. cache hit 보장 없음
const d = JSON.parse($input);                      // ✗ 타입 검증 없이 parse
await axios.post("http://workflow-pod-x:8080/run") // ✗ gateway 우회
                                                   //   → `${GENOS_URL}/api/gateway/workflow/...`
const conn = await mysql.createConnection(...);    // ✗ conn.end() 누락 → leak
```
`$vars.genosUploaded`는 **타입 검증 후** 사용한다. 미지원 타입이면 명시적으로 throw.

---

## H. GenOS 표준 호출 경로 (10장) — 우회 금지

| 연계 | 경로 | 금지 |
|---|---|---|
| LLM | `{GENOS_URL}/api/gateway/rep/serving/{LLM_SERVING_ID}/v1/chat/completions` | 관리 대상 모델을 외부 SDK+별도 키로 우회 호출 |
| MCP Tool | `{GENOS_URL}/api/gateway/mcp/<id>/mcp` (tools/call) | K8s service 직접 호출 |
| Prompt | admin-api `GET /prompt/template/{prompt_id}` | 코드 안 긴 문자열 인라인 |
| A2A | `POST /a2a/<agent_card_id>` (JSON-RPC `tasks/send`) | — |

- Prompt 경로: 클러스터 내부 `http://llmops-admin-api-service:8080/prompt/template/{id}`,
  외부 `https://<host>/api/admin/prompt/template/{id}`.
  **`/api/gateway/prompt/...` 경로는 없다.**
- GenOS 내부 라우팅 헤더(`x-genos-litellm-model`, `x-genos-body-*`)를 사용자 코드에서 직접 작성 금지
- LiteLLM 주소 직접 호출 금지

```python
async def call_llm(messages: list[dict], model: str, stream: bool = False):
    url = f"{os.environ['GENOS_URL']}/api/gateway/rep/serving/{os.environ['LLM_SERVING_ID']}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {os.environ['GENOS_TOKEN']}"}
    body = {"model": model, "messages": messages, "stream": stream}
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()
```

> ⚠️ 현재 `translation_pipeline/common/llm.py`의 base_url은 `{GENOS_URL}/rep/serving/{id}/v1`로
> **`/api/gateway` prefix가 빠져 있다.** 운영 배포 전 확인 필요. (§AUDIT)

---

## I. 타입·입출력 (3.3)
- 입력/반환은 **JSON 직렬화 가능한 값**만
- `dataclass`, Pydantic 객체, numpy 배열, 언어별 객체 인스턴스를 **직접 반환하지 마라** (내부에서만 사용)
- Python은 타입힌트 작성

---

## J. 배포 전 최소 합격 조건 (부록 C)

| 영역 | 조건 |
|---|---|
| 워크플로우 | 일반 함수는 정의된 필수 결과 key 반환 / generator는 마지막에 `event: result` |
| 코드 서빙 | `/health` 200 + 정상·입력오류·외부 timeout 결과가 API 문서와 일치 |
| Flowise | 반환 타입이 다음 Node 기대와 일치하고 **10초 안에 종료** |
| 전처리기 | 정상·빈파일·손상·파라미터 경계 테스트 통과 + 변경 후 재적재 |

---

## ✅ 코드 제출 전 셀프 체크

- [ ] 영역 코드(01~06)를 맞게 썼는가
- [ ] 공통 오류 코드를 `00020001/2/3` 안에서만 조합했는가
- [ ] 영역에 맞는 오류 전달 방식인가 (전처리기=예외 / 워크플로우=오류객체)
- [ ] 모든 외부 호출에 timeout이 있는가
- [ ] 재시도에 상한이 있고, 4xx는 재시도에서 제외했는가
- [ ] `print()` / `console.log` 를 안 썼는가
- [ ] 로그에 문서 원문·LLM 응답 전문·시크릿이 안 들어가는가
- [ ] `detail`에 예외 원문/stack trace가 안 들어가는가
- [ ] 시크릿 하드코딩·기본값이 없는가
- [ ] `/api/gateway/...` 경로를 썼는가 (K8s DNS 직접 호출 아님)
- [ ] 워크플로우면 `run` 함수명 정확 + `{**data, ...}` 로 기존 키 보존
- [ ] generator면 마지막에 `event: result`
- [ ] 반환값이 JSON 직렬화 가능한가
