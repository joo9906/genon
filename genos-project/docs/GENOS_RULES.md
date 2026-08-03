# GENOS_RULES.md — 개발가이드 v1.02 강제 규칙 요약

> 출처: `260721_GenOS_엔지니어_개발가이드_v1.02.pdf`
> 이 파일은 **코드를 쓰기 전에 읽는 체크리스트**다. 조항 번호는 원문 절 번호.

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

- `0.0.0.0` + GenOS가 주입하는 `$PORT`에 bind
- `GET /health` → **HTTP 200 고정 응답** 필수
- 시작(Run) 커맨드는 foreground HTTP process
- async 핸들러 안에서 **동기 blocking 작업 직접 실행 금지** (6.9 잘못된 예 3) → `asyncio.to_thread`
- 배포 검증은 health만으로 끝내지 않는다: 정상 / 입력검증 실패(422) / 외부 timeout(504) 각각 실행

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
