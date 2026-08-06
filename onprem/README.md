# onprem — 온프레미스 이관용 프로덕션 코드

GenOS 폐쇄망에 그대로 옮겨 적는 **실사용 코드만** 담은 디렉토리.
테스트 코드(`tests/`)와 mock/noop 등 테스트 모드 경로는 **전부 제거**했다.
(구조 검증용 mock 은 저장소 루트의 원본 `SFR-006/`, `SFR-018/` 에만 남아 있다.)

## 옮기는 순서

옮기는 대상은 **이 디렉토리의 배포 단위 3개뿐**이다. 저장소 루트의 `SFR-006/`·`SFR-018/`
(테스트 보유 사본)과 `genos-project/`(읽기 전용 참조 번들)는 폐쇄망으로 가지 않는다.
`eval/` 은 배포 단위가 아니라 채점 도구라 아래 순서의 바깥에 있다.

**1. 인프라 전제부터 확인한다 — 코드를 옮겨도 이게 없으면 돌지 않는다.**
- **코드서빙은 Git 저장소가 배포 단위다** (가이드 6.1). 폐쇄망에서 접근 가능한 Git 저장소에
  코드가 올라가 있어야 하고, 리비전에 **브랜치가 아니라 커밋 해시**를 박는다.
- **사내 PyPI registry/mirror 접근 여부** (가이드 11.5.6). 빌드 커맨드가 `pip install` 을
  실행하므로 mirror 가 없으면 빌드 단계에서 멈춘다.
- Gateway 4종(`GENOS_URL`, `LLM_SERVING_ID`, `LLM_MODEL_ID`, `GENOS_TOKEN`) 주입.
  mock 을 제거했으므로 빠지면 조용히 넘어가지 않고 첫 LLM 호출에서 오류가 난다.
- Redis(`REDIS_URL`) 도달 가능 여부. **워크플로우 pod 와 코드서빙 pod 가 같은 Redis** 를
  봐야 다운로드가 대화에서 모은 값을 읽는다.
- 템플릿 볼륨(`TEMPLATE_FILL_TEMPLATE_DIR`)이 **양쪽 pod 에 같은 경로로** 마운트되는지.
- 워크플로우 이미지에 `lxml`·`redis` 가 있는지. 워크플로우 단계는 **pod 기본 이미지에 포함된
  패키지만** 쓸 수 있고 `requirements.txt` 로 추가할 수 없다 — 없으면 운영팀에 **기본 이미지
  갱신을 요청**하거나 `run_chat` 을 얇게 바꿔야 한다 (가이드 11.5.6). 설계 변경 사안이므로
  여기서 막히면 그 위는 진행하지 않는다.
- PDF 를 쓸 거면 코드서빙 이미지에 `genon.preprocessor` 포함 여부. **pip 로 붙일 수 없고
  사용자 Dockerfile 도 코드 서빙의 표준 등록 단위가 아니다**(가이드 6.3) — 기본 이미지 변경
  절차를 거쳐야 한다. 없어도 hwpx 다운로드는 정상이고 PDF 만 미지원(501)이라 이관 자체를
  막는 조건은 아니다.

**2. 코드서빙(03)을 먼저 올린다.** 워크플로우가 이쪽을 호출하는 방향이라 반대로 하면
대화는 되는데 다운로드가 죽는 상태로 시작한다.
- 코드 서빙 생성(저장소 정보) → 리비전 추가(브랜치·커밋 해시) → 리비전 상세 > **환경 설정**
  에서 언어·빌드 커맨드·시작 커맨드·환경 변수를 등록한다.
- 빌드 커맨드는 두 단위 모두 `pip install -r requirements.txt` (각 단위에 파일이 있다).
- 시작 커맨드는 **단위마다 모듈 경로가 다르다** (아래 "코드서빙 실행" 절).
- 확인은 `GET /health`. 단, **health 200 만으로 배포 완료로 보지 않는다** — 가이드 11.3 이
  정상 입력·입력 오류(422)·외부 timeout(504)을 각각 실행하라고 요구한다.
  `test/verify_serving.py` 가 앞의 셋을 자동으로 때린다 (timeout 은 수동).
  올리기 **전에** `test/check_deploy_contract.py` 로 빌드·기동 계약을 먼저 본다.
- 006 은 기동 로그에서 `TEMPLATE_FILL_ADMIN_TOKEN` 경고 유무를 같이 본다 — 경고가 떠 있으면
  템플릿 등록·삭제가 인증 없이 열린 상태다.

**3. 템플릿을 등록하고 인식 결과를 눈으로 확인한다.** 대화를 붙이기 전에 해야 한다.
- `POST /templates` 로 hwpx 업로드 → `GET /templates` 에서 `indexed: true` 확인.
- `GET /fields` 로 항목이 다 잡혔는지, `source` 가 `slot`/`field` 중 무엇인지 확인.
  `GET /preview` 로 채우기 전 문서 모양까지 본다.
- **등록 응답의 `bare_braces` 를 반드시 본다.** 따옴표를 빠뜨린 `{제목, 16pt}` 는 채울
  자리로 잡히지 않고 여기에만 나온다. 등록 자체는 **성공하므로**(`fields: []` 로 돌아온다)
  이 경고를 놓치면 항목 0개인 템플릿이 조용히 배포된다.
- 슬롯 인식이 어긋나면 여기서 드러난다. 워크플로우까지 올린 뒤에 발견하면 원인이
  파서인지 LLM 추출인지 갈라내기 어려워진다.

**4. 워크플로우(02)를 캔버스 Python 노드로 등록한다.**
- `SFR-006_template_fill/template_fill/run_chat.py` 의 `run`,
  `SFR-018_text_polish/text_polish/main.py` 의 `run`.
- **함수명 `run`·인자 `data` 하나는 GenOS 고정 계약**이다 (아래 "워크플로우 스트리밍 규약").
- 캔버스 변수 주입: `template_fill_template_id`(필수 — 어느 템플릿을 쓸지),
  `template_fill_tone`·`polish_doc_type`·`polish_tone`(선택).

**5. 끝단까지 한 번 통과시킨다.** 대화 한 턴 → `GET /status` 의 `ready_for_download`
→ 다운로드. 2~4 단계가 각각 떠 있어도 Redis·볼륨 공유가 어긋나면 이 지점에서만 드러난다.

`eval/` 은 위와 무관하게 필요할 때 따로 띄운다 (stdio MCP 서버, `eval/README.md`).

## 배포 단위 3개

| 디렉토리 | 기능 | GenOS 영역 | 진입점 |
|---|---|---|---|
| `SFR-006_template_fill/` | HWPX 템플릿 채우기 | 워크플로우(02) + 코드서빙(03) | `template_fill/run_chat.py` `run(data)`, `template_fill/main.py` `app` |
| `SFR-018_text_polish/` | 글다듬이 | 워크플로우(02) | `text_polish/main.py` `run(data)` |
| `SFR-018_translation/` | 번역 | 코드서빙(03) | `main.py` `app` |

각 디렉토리는 독립적으로 배포한다. 서로 import 하지 않는다.

`eval/` 은 배포 단위가 아니다 — 위 세 기능의 산출물을 채점하는 평가지표 MCP 서버
(저장소 루트 README 의 지표 정의를 도구로 구현). 자세한 내용은 `eval/README.md`.

`test/` 도 배포 단위가 아니다 — 가이드 6장·11.3 이 요구하는 **배포 계약 점검** 스크립트다.
배포 단위 어디에서도 import 하지 않으므로 이미지에 흘러가지 않는다. `test/README.md` 참고.

`docs/` 는 기능별 **설계 심화 문서**다. 이 README 가 배포·환경변수·운영 규약의 정본이고,
`docs/` 는 구조와 데이터 흐름을 다룬다 — SFR-006 의 입출력·처리 파이프라인·가드레일 삽입
지점은 [`docs/SFR-006_architecture.md`](docs/SFR-006_architecture.md).

## 공통 환경변수 (Gateway)

세 기능 모두 GenOS Gateway OpenAI 호환 경로만 사용한다 (가이드 10.2절).

```
GENOS_URL         # Gateway 베이스 URL (호스트 루트. '/api/gateway' 는 코드가 붙인다)
LLM_SERVING_ID    # 서빙 ID
LLM_MODEL_ID      # 모델 ID
GENOS_TOKEN       # 시크릿 — 코드에 기본값 없음. 미설정 시 호출 시점에 실패한다
```

mock 을 제거했으므로 위 값이 없으면 조용히 넘어가지 않고 오류(ERR_INTERNAL 등)로
노출된다. 배포 전 반드시 주입할 것.

**`/api/gateway` prefix 는 세 단위 모두 코드가 붙인다** (`llm.py` 의 `_base_url()`).
`GENOS_URL` 이 이미 그 prefix 로 끝나면 중복 없이 그대로 쓴다. 예전에 018 두 단위가
`{GENOS_URL}/rep/serving/...` 로 prefix 없이 호출해 게이트웨이를 지나지 않았다 —
실제 운영 코드서빙 브리지(`genos_files/bridge.py`)가 `{base}/api/gateway/code_serving/...`
로 조립하는 것으로 확인된 사실이며, prefix 가 빠지면 LLM 호출이 404 로 죽는다.

## 로깅 규약 (네 디렉토리 공통 — GENOS_RULES §C / 가이드 3.7·3.8·3.10)

각 디렉토리의 `logging_utils.py` 는 같은 계약을 가진 사본이다 (배포 단위 간 import 금지).

```python
log_info("세션 저장 완료", event="session_saved", resource_id="redis", item_count=len(values))
```

- **값은 `extra` 필드로만 넘긴다.** 메시지 문자열에 f-string 으로 끼워 넣지 않는다 —
  문자열에 섞인 값은 걸러낼 수 없어 화이트리스트가 무력해진다.
- **허용 필드만 기록된다**: `event, trace_id, request_id, resource_id, status,
  duration_ms, item_count, upstream_status, error_code, error_type`.
  그 밖의 키는 값을 버리고 **이름만** `[dropped_fields=...]` 로 남긴다(호출부 실수를 드러냄).
- 문서 원문·사용자 질문·LLM 응답 전문·시크릿·DB 오류 원문은 로그에 남지 않는다.
  실패는 `error_type`(예외 클래스명)과 `upstream_status`(HTTP 상태코드)로만 분류한다.
- `trace_id` 는 `genos_state` 에서 받아 매 로그에 싣는다 — 워크플로우 단계와 코드 서빙
  로그를 한 요청으로 묶는 유일한 키다.
- 코드 서빙 진입점은 `configure_logging(os.getenv("LOG_LEVEL", "INFO"))` 를 호출한다.
  `eval/` 은 stdio MCP 라서 `configure_stderr_logging()` 으로 **stderr 로만** 내보낸다
  (stdout 은 JSON-RPC 전송 채널 — 로그가 섞이면 프로토콜이 깨진다).
- 오류 전달 방식은 영역마다 다르다: 워크플로우/코드서빙은 오류 **객체**를 반환하고,
  `eval/`(평가지표·MCP 도구)은 **로그를 남긴 뒤 예외를 던진다**(`error_codes.fail()`).

## 기능별 추가 설정

### SFR-006_template_fill

> **설계·흐름의 정본은 [`onprem/docs/SFR-006_architecture.md`](docs/SFR-006_architecture.md)** 다.
> 두 영역 배치, 대화 한 턴의 처리 순서, 문서 조립 파이프라인, 채울 자리 인식 규칙,
> 본문 블록, 글다듬이, 상태 저장, 가드레일 설계가 전부 거기 있다.
> **여기는 배포·운영에 필요한 것만** 적는다 (중복 금지 — `onprem/docs/README.md` 배치 규칙).

#### 배포 전제 (이게 안 맞으면 기능이 조용히 반쪽이 된다)

- **워크플로우 pod 와 코드서빙 pod 가 같은 Redis 와 같은 `TEMPLATE_DIR` 볼륨을 봐야 한다.**
  다운로드 단계가 대화에서 모은 값을 읽는 유일한 통로가 Redis 세션이다. 세션은 Redis 로
  옮겼으므로 세션 전용 공유 볼륨은 필요 없다(템플릿 파일 볼륨은 여전히 공유해야 한다).
- 워크플로우 pod **기본 이미지에 `lxml`·`redis`·`httpx` 가 있어야 한다.** 워크플로우
  단계는 `requirements.txt` 를 설치하지 않는다(11.5.6) — 없으면 운영팀에 기본 이미지
  갱신을 요청해야 한다.
- 코드서빙 이미지에 **`genon.preprocessor` 가 있어야 PDF 다운로드가 동작한다.** pip 설치
  대상이 아니라 기본 이미지 변경 절차를 거쳐야 한다. 없으면 hwpx 만 내려가고
  `formats` 에 `pdf` 가 빠진다(501 로 정직하게 응답).
- 진입점이 패키지 안(`template_fill/main.py`)이라 **시작(Run) 커맨드 등록이 필수**다
  (아래 "코드서빙 실행" 절).

#### 환경변수

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `TEMPLATE_FILL_TEMPLATE_DIR` | `./templates` | 관리자가 hwpx 템플릿을 두는 **공유 볼륨** 경로 |
| `REDIS_URL` | 사내 GenOS Redis DNS | 멀티턴 세션 + 템플릿 색인 저장소 |
| `TEMPLATE_FILL_ADMIN_TOKEN` | (없음) | 설정 시 템플릿 등록·삭제에 `X-Admin-Token` 요구. **비우면 검사하지 않으며 기동 로그에 경고가 남는다** |
| `TEMPLATE_FILL_SLOT_FIELDS` | `1` | 본문 슬롯(`제 목 : {'제목', 16pt}`) 인식. 옛 이름 `TEMPLATE_FILL_LABEL_FIELDS` 도 읽는다 |
| `TEMPLATE_FILL_APPLY_STYLE_SPEC` | `1` | 슬롯 서식 인자를 실제 서식으로 반영 |
| `TEMPLATE_FILL_STYLE_SCOPE` | `slot` | `slot`(중괄호 자리 run 에만 — 밖은 원래 서식 유지) / `paragraph`(슬롯이 놓인 문단 전체) / `run`(누름틀도 값 run 에만) |
| `TEMPLATE_FILL_BODY_BLOCKS` | `1` | 본문 블록(항목 밖 내용 이어 쓰기) |
| `TEMPLATE_FILL_BLOCK_ANCHOR` | (없음) | 블록 삽입 기준 항목명. 비우면 **문서 끝**. 서명란이 마지막에 있는 템플릿만 지정 |
| `TEMPLATE_FILL_MAX_BLOCKS` / `_MAX_BLOCK_CHARS` | `100` / `4000` | 본문 블록 개수·길이 상한 |
| `TEMPLATE_FILL_CHAT_PREVIEW` | `1` | 대화 응답에 채운 문서 미리보기 포함 (부담되면 `0`, `GET /preview` 로 대체) |
| `TEMPLATE_FILL_MAX_PREVIEW_CHARS` | `20000` | 마크다운 미리보기 길이 상한 |
| `TEMPLATE_FILL_MAX_UPLOAD_BYTES` | `20MB` | 업로드 템플릿 크기 상한 (전량 메모리 파싱) |
| `TEMPLATE_FILL_MAX_FIELDS` / `_MAX_VALUE_CHARS` / `_MAX_MESSAGE_CHARS` | `200` / `2000` / `20000` | 입력 상한 |
| `TEMPLATE_FILL_SESSION_TTL_HOURS` | `24` | 버려진 세션 자동 회수 (안전망) |
| `TEMPLATE_FILL_REDIS_INDEX_PREFIX` / `_INDEX_TTL_HOURS` | `template_fill:index` / `720` | 템플릿 색인 캐시 |

PDF 다운로드에는 설정이 없다 — 전처리기 변환기를 그대로 호출하고, 가용 여부는 그 패키지와
변환 백엔드 존재로 판단한다.

#### 워크플로우 변수 (캔버스에서 주입)

| 변수 | 값 | 뜻 |
|---|---|---|
| `template_fill_template_id` | 템플릿 파일명(확장자 제외) | 어떤 양식을 채울지 |
| `template_fill_tone` | `polite` / `friendly` / `report` | 글다듬이 톤 (**opt-in** — 없으면 문체를 건드리지 않는다) |
| `template_fill_tone_fields` | 항목명 배열 | 톤 적용 대상을 관리자가 직접 지정 (지정하면 서술형 자동 판정보다 우선) |

#### 엔드포인트 (코드 서빙 03)

| 경로 | 인증 | 용도 |
|---|---|---|
| `GET /health` | — | 헬스체크 |
| `GET /templates` | — | 목록 + 색인 상태 + 지원 형식 |
| `POST /templates` | **관리자** | 등록 (multipart: `template`, `template_id?`, `overwrite?`) |
| `DELETE /templates/{id}` | **관리자** | 삭제 (파일 + 색인) |
| `GET /fields?template_id=` | — | 항목 스키마 + `block_styles` |
| `GET /status?session_id=` | 세션 | 채움 현황 · `ready_for_download` · `block_count` |
| `GET /preview?session_id=` | 세션 | 채운 결과 마크다운 (표시 전용) |
| `PATCH /values` | 세션 | 항목 값 수정 (**빈 문자열 = 지움**) |
| `DELETE /values` | 세션 | 항목 값 비우기 |
| `PUT /blocks` | 세션 | 본문 추가 내용 **통째 교체** |
| `POST /generate` | 세션 | 초안 생성 + 다운로드 (`format`: `hwpx`/`pdf`) |
| `POST /generate/upload` | — | 업로드한 hwpx 로 즉석 생성 (multipart) |

> 관리자 경로를 뺀 나머지는 **`session_id` 만 알면 호출된다.** 사내 폐쇄망 전제이며,
> 외부 노출 계획이 생기면 세션 소유자 검증이 별도 과제다.

다운로드 응답은 바이너리 + 헤더로 사실을 함께 준다:
`X-Missing-Fields`(비워 둔 항목) · `X-Written-Fields` · `X-Styled-Fields` ·
`X-Body-Blocks`(삽입된 본문 문단 수) · `X-Document-Format`.
버튼 활성화 판단은 `GET /status` 의 `ready_for_download`.

#### 운영에서 알아 둘 것

- **부분 초안이 정상 동작이다.** 값이 없는 항목은 `제목:` 상태로 남고 파일은 내려간다.
  무엇이 비었는지는 `X-Missing-Fields` 로 알린다.
- **문서 생성에 성공하면 세션이 즉시 삭제된다.** PDF 변환에 실패하면 세션을 남긴다 —
  사용자가 hwpx 로 바꿔 다시 시도할 수 있어야 하기 때문이다.
- **라벨 인식 규칙이나 `FieldSpec` 을 고치면 `template_index.SCHEMA_VERSION` 을 올려야
  한다.** 안 올리면 새 코드가 Redis 에 남은 옛 판정을 읽는다.
- **톤 문구는 018 이 원본이다.** 006·eval 은 사본이라 고칠 때
  `python onprem/test/check_tone_policy.py` 로 대조한다.
- 서식 적용 실패는 문서 생성을 막지 않는다(서식 미적용 초안 + 경고 로그). 반면 **본문 블록
  삽입 실패는 오류로 올린다** — 사용자가 직접 쓴 본문을 조용히 빠뜨리면 안 된다.
### SFR-018_text_polish
- 워크플로우 변수 `polish_doc_type`, `polish_tone` 로 문서유형/톤 주입
  (톤 고정군은 사용자 요청과 무관하게 정책 톤으로 강제).

### SFR-018_translation
- `POST /translate` : 노드 배열 번역
- `POST /translate/markdown` : 전처리기 산출물(마크다운/HTML 표) 구조 보존 번역
- `TRANSLATE_MAX_NODES`, `TRANSLATE_MAX_TOTAL_CHARS` : 입력 상한

## 코드서빙 실행 — **단위별 모듈 경로가 다르다**

리비전 상세 > 환경 설정 에 넣는 값이다 (가이드 6.3).

```
# SFR-006_template_fill  (app 이 패키지 안에 있다)
BUILD : pip install -r requirements.txt
RUN   : uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT

# SFR-018_translation    (app 이 단위 루트에 있다)
BUILD : pip install -r requirements.txt
RUN   : uvicorn main:app --host 0.0.0.0 --port $PORT
```

`main:app` 을 006 에 쓰면 루트에 `main.py` 가 없어 기동 실패한다. 두 단위의 구조가
다른 것이 원인이고, 통일하려면 006 루트에 `app` 을 재노출하는 `main.py` 를 두면 된다
(지금은 두지 않았다 — 실제 진입점이 두 곳으로 보이는 것도 혼동거리라서).

- **006 은 시작(Run) 커맨드 등록이 필수다.** 가이드 6.2 는 저장소 루트의 `main.py` 또는
  `src/main.py` 가 있으면 그 파일을 먼저 실행한다고 정하는데, 006 의 진입점은 패키지 안
  (`template_fill/main.py`)이라 그 자동 경로에 걸리지 않는다.
- 018 번역은 루트에 `main.py` 가 있어 자동 경로를 탄다. 그래서 `if __name__ == "__main__"`
  에 uvicorn 기동 블록을 둔다 — 없으면 모듈만 로드되고 서버가 뜨지 않는다.
- **`PORT` 는 GenOS 가 주입하며 기본값 8080 이다.** `BUILD_COMMAND`, `START_COMMAND`,
  `LANGUAGE`, `OPENAPI_PATH`(기본 `/openapi.json`)도 함께 들어온다 — 이 이름들을 앱에서
  다른 목적으로 쓰지 않는다 (가이드 6.7).
- 업무 경로는 우리가 정한다. **`/json`·`/multipart` 는 Python `service(config, data)`
  호환 방식에서만 자동 제공되는 경로**라 우리 `/generate`·`/translate` 가 정상이고,
  운영 참고 코드가 `/json` 하나로 통일한 것을 따라갈 이유는 없다 (가이드 6.9 잘못된 예 5:
  호환용 경로를 필수 경로로 가정하지 말 것).
- 호출 URL 은 `${GENOS_URL}/api/gateway/code_serving/<id>/<우리 경로>` + Bearer 토큰 (6.8).

`GET /health` 로 헬스체크. 워크플로우(02) 기능은 GenOS 캔버스의 Python 노드에
`run` 함수를 등록하는 방식이라 별도 서버 실행이 없다.

### 저장소 구조 — 아직 정하지 않은 것

코드 서빙은 **저장소 하나가 배포 단위**인데(생성 시 저장소 정보, 리비전에 브랜치·커밋 해시),
지금은 한 저장소 안에 배포 단위 3개가 하위 디렉토리로 들어 있다. 가이드에는 하위 디렉토리를
지정하는 항목이 없다. 선택지는 둘이다.

- **빌드·시작 커맨드에서 흡수** — `pip install -r onprem/SFR-006_template_fill/requirements.txt`
  처럼 경로를 붙이고, 시작 커맨드도 해당 디렉토리 기준으로 잡는다. 저장소는 그대로 둔다.
- **저장소 분리** — 배포 단위별로 저장소를 나눠 각 단위가 루트가 되게 한다. 가이드 구조에는
  가장 잘 맞지만 사본 관리가 늘어난다.

**실물 서버가 들어온 뒤에 정한다.** 그때까지 이 저장소 구조는 바꾸지 않는다.

## 워크플로우 스트리밍 규약 (02 두 단위 공통 — 가이드 5.2 / GENOS_RULES §D)

- **함수명은 정확히 `run`, 인자는 `data` 하나.** 다른 이름이면 `run function not found`
  + HTTP 500 이다. 바꿀 수 있는 값이 아니다.
- `run` 은 async generator 로, 마지막에 `event: result` 를 **1회** yield 한다.
  그 `data` 가 다음 스텝의 `data` 가 되므로 `{**data, ...}` 로 넘겨 `genos_state` 를 잃지 않는다.
- **`sio_server.emit` 뒤에는 반드시 `await asyncio.sleep(0)`.** 양보하지 않고 emit 을
  몰아치면 소켓 쓰기가 버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다(가이드 D.4 "스트리밍이
  일괄 반환되는 원인"). 실제 운영 브리지(`genos_files/bridge.py`)도 매 emit 뒤에 넣는다.
- **토큰은 청크 단위로 보낸다** (`_STREAM_CHUNK_CHARS`, 32자). 글자 하나씩 emit 하면
  현황표 한 장이 emit 수백 회가 되고, 양보 횟수가 그만큼 늘어 오히려 표시가 느려진다.

## 의존 패키지

| 단위 | 패키지 |
|---|---|
| SFR-006 코드서빙(03) | `fastapi`, `uvicorn`, `pydantic`, `lxml`, `redis`, `httpx` |
| SFR-006 워크플로우(02) | `httpx`, `lxml`, `redis` (`run_chat` 이 파서·세션을 직접 쓴다) |
| SFR-018 글다듬이(02) | `httpx`, `openai` |
| SFR-018 번역(03) | `fastapi`, `uvicorn`, `pydantic`, `httpx`, `openai` |

코드서빙 두 단위는 각 디렉토리의 **`requirements.txt`** 가 정본이고, 빌드 커맨드가 그걸
설치한다. 위 표는 읽는 사람을 위한 요약이다. 006 은 `python-multipart` 도 필요하다
(`POST /templates`·`/generate/upload` 의 multipart 폼 — 빠지면 기동은 되고 그 두 경로만
런타임에 실패한다).

전부 pip 설치 가능 — 시스템 레벨 도구는 쓰지 않는다. 단 두 가지가 배포 환경에 달려 있고,
**둘 다 `requirements.txt` 로 해결되지 않는다**:
- **워크플로우 이미지에 `lxml`·`redis` 가 있어야 한다.** 워크플로우 단계는 pod 기본 이미지에
  포함된 패키지만 쓸 수 있어 의존성 파일로 추가할 수 없다 (가이드 11.5.6) — 운영팀에 기본
  이미지 갱신을 요청하거나, `run_chat` 을 얇게 만들어 파싱·세션을 코드서빙에 위임하고
  gateway 경유 HTTP 만 쓰는 형태로 바꿔야 한다.
- **PDF 는 코드서빙 이미지에 전처리기 패키지(`genon.preprocessor`)가 포함돼야 한다.**
  pip 대상이 아니고 사용자 Dockerfile 도 코드 서빙의 표준 등록 단위가 아니므로(가이드 6.3),
  운영 배포 방식과 기본 이미지 변경 절차를 통해서만 들어간다.

폐쇄망에서는 위 패키지들이 사내 PyPI registry 또는 mirror 에 있는지 먼저 확인한다 (11.5.6).
