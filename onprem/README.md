# onprem — 온프레미스 이관용 프로덕션 코드

> **이어서 작업하는 사람은 [`HANDOFF.md`](HANDOFF.md) 를 먼저 읽는다** — 무엇이 어디까지
> 검증됐고 어디서부터 이어 하면 되는지가 거기 있다. 이 문서는 배포·환경변수·운영 규약의
> 정본이고, 설계 근거는 [`ARCHITECTURE_SPLIT.md`](ARCHITECTURE_SPLIT.md) 다.

GenOS 폐쇄망에 그대로 옮겨 적는 **실사용 코드만** 담은 디렉토리.
테스트 코드(`tests/`)와 mock/noop 등 테스트 모드 경로는 **전부 제거**했다.
(구조 검증용 mock 은 저장소 루트의 원본 `SFR-006/`, `SFR-018/` 에만 남아 있다.)




## 옮기는 순서

옮기는 대상은 **`codeserving/` 4개 + `mcp/` 4개 + `workflow/` 스텝 9개**다. 저장소 루트의 `SFR-006/`·`SFR-018/`
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
- ~~워크플로우 이미지에 `lxml`·`redis` 가 있는지~~ — **더 이상 전제가 아니다** (2026-08-11
  재배치). 스텝이 쓰는 외부 패키지는 `httpx` 하나이고 그것은 기본 이미지에 있다
  (§D.3). 예전에는 여기서 막히면 그 위를 진행하지 못했다 — 그 차단을 없애려고 재배치했다.
  `check_deploy_contract.py` 가 스텝 9개의 import 를 매번 확인한다.
- PDF 를 쓸 거면 코드서빙 이미지에 `genon.preprocessor` 포함 여부. **pip 로 붙일 수 없고
  사용자 Dockerfile 도 코드 서빙의 표준 등록 단위가 아니다**(가이드 6.3) — 기본 이미지 변경
  절차를 거쳐야 한다. 없어도 hwpx 다운로드는 정상이고 PDF 만 미지원(501)이라 이관 자체를
  막는 조건은 아니다. **이 전제는 이제 006 에만 해당한다** — FAQ 의 PDF 경로는
  2026-08-12 에 걷어냈다(018 산출물은 txt 하나다).

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

**4. MCP 도구(01)를 올린다.** 워크플로우가 이쪽도 호출하므로 코드서빙과 같은 층이다.
`mcp/` 의 **파일 네 개를 각각** 등록한다 — 디렉토리가 아니라 소스 파일 하나가 등록
단위이고, 시작 커맨드도 `requirements.txt` 도 없다. 등록 뒤 도구 목록(`tools/list`)에
15개(`TG` 5 + `LP` 6 + `GL` 3 + `HX` 1)가 다 나오는지 본다 — **하나라도 비면 이름이
겹쳐 덮인 것이다.**

**5. 워크플로우(02)를 캔버스 Python 스텝으로 등록한다.**

- `workflow/` 의 파일을 **통째로** 붙여 넣는다. 기능별 스텝 순서는 위 배포 단위 절의 표.
- **함수명 `run`·인자 `data` 하나는 GenOS 고정 계약**이다 (아래 "워크플로우 스트리밍 규약").
- 스텝별 환경 변수(`*_SERVING_ID`·`*_MCP_ID`)는 `workflow/README.md` 의 표. **시크릿
  기본값이 없으므로** 하나라도 빠지면 그 스텝이 `CONFIG_MISSING` 으로 즉시 끝난다.
- 캔버스 변수 주입: `template_fill_template_id`(필수 — 어느 템플릿을 쓸지),
  `polish_doc_type`·`polish_tone`(선택). `template_fill_tone`/`_tone_fields` 는
  2026-08-12 에 006 의 톤 변환 기능과 함께 없어졌다.

**5. 끝단까지 한 번 통과시킨다.** 대화 한 턴 → `GET /status` 의 `ready_for_download`
→ 다운로드. 2~4 단계가 각각 떠 있어도 Redis·볼륨 공유가 어긋나면 이 지점에서만 드러난다.

`eval/` 은 위와 무관하게 필요할 때 따로 띄운다 (stdio MCP 서버, `eval/README.md`).

## 배포 단위 — 코드서빙 4 + MCP 4, 그리고 워크플로우 스텝 9

**2026-08-11 에 영역별로 다시 나눴다.** 설계와 근거는
[`ARCHITECTURE_SPLIT.md`](ARCHITECTURE_SPLIT.md). 요점은 하나다 — 워크플로우 스텝이
`lxml`·`redis`·`jinja2` 를 로컬 import 하고 있었고(§D.3 위반), 그것이 기본 이미지 변경
요청에 묶여 배포를 막고 있었다. 지금 **워크플로우 이미지에 추가되는 패키지는 0개**다.

### area 03 — `codeserving/` (HTTP 배포 단위 4개)

| 디렉토리                              | 기능               | 진입점                    | 시작 커맨드 대상          |
| ------------------------------------- | ------------------ | ------------------------- | ------------------------- |
| `codeserving/SFR-006_template_fill/`  | HWPX 템플릿 채우기 | `template_fill/main.py`   | `template_fill.main:app`  |
| `codeserving/SFR-018_text_polish/`    | 글다듬이           | `main.py` (루트)          | `main:app`                |
| `codeserving/SFR-018_translation/`    | 번역               | `main.py` (루트)          | `main:app`                |
| `codeserving/SFR-018_faq/`            | FAQ 생성           | `faq/main.py`             | `faq.main:app`            |

**글다듬이는 재배치로 02 에서 03 이 됐다.** LLM 호출과 프롬프트 렌더가 여기로 내려오면서
`requirements.txt` 가 처음 생겼고, 워크플로우에 `jinja2` 를 넣어 달라는 요청이 사라졌다.

### area 01 — `mcp/` (MCP 도구 파일 4개)

전부 **LLM 을 부르지 않는 결정적 도구**라 워크플로우가 마음 놓고 직접 부를 수 있다.

**⚠️ MCP 는 서빙이 아니라 파일이다.** GenOS 는 **소스 파일 한 개**를 받아 실행하고
`mcp` 객체를 런타임이 전역으로 주입한다. FastAPI 앱도 `/health` 도 `$PORT` 도
`requirements.txt` 도 **없다** — 2026-08-11 이전에는 코드서빙처럼 만들어 뒀는데 전부
갈아엎었다. 규율(접두어·shim·`-> str`·빈 문자열 주입)은 [`mcp/README.md`](mcp/README.md).

| 파일                       | 접두어 | 도구                                                                                       |
| -------------------------- | ------ | ------------------------------------------------------------------------------------------ |
| `mcp/genon_text_guard.py`  | `TG`   | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` `evidence_check`   |
| `mcp/genon_lang_policy.py` | `LP`   | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` |
| `mcp/genon_glossary.py`    | `GL`   | `glossary_lookup` `glossary_status` `glossary_reload`                                        |
| `mcp/genon_hwpx_text.py`   | `HX`   | `hwpx_to_markdown`                                                                           |

`genon_text_guard` 가 이 재배치의 최대 이득이다 — 다섯 벌로 흩어져 있던 결정적 검증이
한 파일로 모였고, 앞으로 만들 어떤 워크플로우에서도 같은 판정을 쓴다.

**접두어가 붙은 이유**: 한 서버에 여러 도구 파일이 함께 로드될 수 있고, 최상위 이름이
겹치면 나중 것이 앞엣것을 덮는다. 그 실패는 "도구가 이상한 값을 낸다" 로만 드러난다.

### area 02 — `workflow/` (캔버스 파이썬 스텝 9개)

**파일 1개 = 스텝 1개**이고, 파일을 통째로 캔버스에 붙여 넣는다. 006 은 스텝 셋이
`1 → 2 → 3` 순서로 이어지고 나머지 셋은 스텝 둘이다. 목록·규율은
[`workflow/README.md`](workflow/README.md).

| 기능     | 스텝 순서                                                                       |
| -------- | ------------------------------------------------------------------------------- |
| 006      | `sfr006_01_context` → `sfr006_02_extract` → `sfr006_03_commit`                  |
| 글다듬이 | `sfr018_polish_01_policy` → `sfr018_polish_02_polish`                           |
| FAQ      | `sfr018_faq_01_source` → `sfr018_faq_02_generate`                               |
| 번역     | `sfr018_translate_01_detect` → `sfr018_translate_02_translate`                  |

**중간 스텝은 `dict` 를 돌려주고, 마지막 스텝만 async generator 로 `event: result` 를
1회 낸다.** 오류는 `data["error"]` 로 흐르고 마지막 스텝이 사용자에게 말해 준다 —
중간 스텝은 스트리밍을 하지 않으므로 거기서 끝내면 화면이 빈 채로 남는다.

각 배포 단위는 독립적으로 배포한다. 서로 import 하지 않는다.

`eval/` 은 배포 단위가 아니다 — 위 네 기능의 산출물을 채점하는 평가지표 MCP 서버
(저장소 루트 README 의 지표 정의를 도구로 구현). 자세한 내용은 `eval/README.md`.


## 프롬프트 디렉토리 (`prompt/`) — 배포 단위 **바깥**이다

**디렉토리 이름은 배포 단위 이름과 같다.** 네 단위 모두 프롬프트를 파일로 뺐다.

| 경로                            | 쓰는 단위     | 쓰는 영역 | 템플릿                                                              | 덮어쓰기 환경변수          |
| ------------------------------- | ------------- | --------- | ------------------------------------------------------------------- | -------------------------- |
| `prompt/SFR-006_template_fill/` | 템플릿 채우기 | 02 + 03   | `extract_system` `extract_user`(02) / `tone_system` `tone_user`(03) | `TEMPLATE_FILL_PROMPT_DIR` |
| `prompt/SFR-018_text_polish/`   | 글다듬이      | 03        | `system`                                                            | `POLISH_PROMPT_DIR`        |
| `prompt/SFR-018_translation/`   | 번역          | 03        | `system_batch` `user_batch` `system_single` `user_single`           | `TRANSLATION_PROMPT_DIR`   |
| `prompt/SFR-018_faq/`           | FAQ           | 02 + 03   | `system` `user` `retry_shortfall`                                   | `FAQ_PROMPT_DIR`           |

jinja 템플릿(`*.j2`)이다. 문구 수정이 코드 리뷰·재빌드 없이 끝나고, 나중에 GenOS
Prompt 리소스(10.5절)로 옮길 때 그대로 등록할 수 있다.

- **이미지에 이 디렉토리를 함께 넣어야 한다.** 기본 탐색 경로는 배포 단위 기준
  `../prompt/<이름>` 이고, 다른 곳에 두면 위 환경변수로 지정한다. **006 과 FAQ 는
  02·03 두 이미지 모두** 이 디렉토리를 가져가야 한다 — 006 은 02 가 값 추출, 03 이
  톤 변환으로 서로 다른 템플릿을 쓰고, FAQ 는 03 의 `POST /generate` 도 02 와 같은
  `generate_faqs` 를 타기 때문이다(대화를 거치지 않는 재생성 경로).
- 템플릿이 없으면 **빈 프롬프트로 넘어가지 않고 요청을 세운다.** 지시문 없는
  프롬프트로 LLM 을 돌리면 그 결과가 정상 응답처럼 내려간다.
  렌더 실패는 LLM 실패와 **따로** 로그를 남긴다(`event=prompt_render_failed`) —
  전자는 이미지에 디렉토리를 안 넣은 배포 실수라 운영에서 구분돼야 손을 쓸 수 있다.
  단 006 톤 변환만 예외로 문서 생성을 막지 않는다(원본 값 유지 + 사유 노출).
  톤은 부가 기능이라 프롬프트가 없다고 다운로드까지 못 하게 할 이유가 없다.
- `StrictUndefined` 를 쓴다 — 변수 오타가 빈칸으로 렌더되면 지시 한 줄이 조용히 사라진다.

### 지시문 언어 — 한국어와 영어를 나눠 쓴다

프롬프트를 통째로 한국어로 쓰지 않는다. 판단 기준은 **그 문장이 통제하는 대상**이다.

- **구조·형식·금지 조항은 영어.** JSON 스키마, "코드펜스를 붙이지 마라", "지어내지
  마라" 류다. 영어 지시를 따르는 정확도가 높고 토큰도 덜 든다.
- **산출물의 언어·어투·표기 규칙은 한국어.** 한국어 존댓말·개조식 종결·`2026. 8. 3.`
  같은 표기는 한국어로 적어야 예시와 지시가 같은 언어로 맞물린다. 톤 프리셋
  (`tone_presets.py`)·난이도 문구가 이미 한국어인 것도 이 쪽에 붙는 이유다.
- **번역 단위만 전부 영어다.** 대상 언어가 요청마다 바뀌어서 지시문 언어가 섞이면
  모델이 출력 언어를 헷갈린다(`registers.py` 머리말). 언어 이름도 `Language.label`
  의 영문(`Korean`/`English`…)을 쓴다 — 사용자 노출용 `korean_label` 과 다른 필드다.
- **글다듬이에는 한 줄이 더 있다.** 이 단위는 한국어 원문을 되쓰기 때문에 영어 지시가
  번역을 유발할 수 있고, 그렇게 나온 영어 결과물은 형식상 정상 응답으로 내려간다
  (`markdown_guard` 는 구조만 보므로 언어 전환을 못 잡는다). 그래서 영어 형식 블록
  안에 "출력은 한국어, 번역 금지"를 명시한다.

이 정책은 각 `*.j2` 머리말 주석에 근거와 함께 적혀 있다 — 문구를 고칠 사람이
파일만 열어도 어느 블록을 어느 언어로 둬야 하는지 알 수 있게 하기 위해서다.
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


- `TEMPLATE_FILL_LABEL_FIELDS` : 본문 라벨 항목 인식 (기본 1 = 켜짐)
- `TEMPLATE_FILL_TEMPLATE_DIR` : 관리자가 hwpx 템플릿을 두는 볼륨 경로
- `REDIS_URL` : 멀티턴 세션 + 템플릿 색인 저장소 (기본 사내 GenOS Redis DNS)
- **워크플로우 pod 와 코드서빙 pod 가 같은 Redis 와 같은 `TEMPLATE_DIR` 볼륨을 봐야**
  다운로드 단계가 대화에서 모은 값을 읽는다. 세션은 Redis 로 옮겼으므로 세션 전용
  공유 볼륨은 필요 없다.
- `TEMPLATE_FILL_REDIS_INDEX_PREFIX` / `TEMPLATE_FILL_INDEX_TTL_HOURS` : 템플릿 색인 캐시
- `TEMPLATE_FILL_MAX_PREVIEW_CHARS` : 마크다운 미리보기 길이 상한 (기본 20000)
- `TEMPLATE_FILL_PROMPT_DIR` : 프롬프트 디렉토리 위치를 옮길 때만 지정 (기본은
  배포 단위 기준 `../prompt/SFR-006_template_fill`). **02·03 양쪽에 필요하다**
- PDF 다운로드에는 설정이 없다 — 전처리기 변환기를 그대로 호출하고, 가용 여부는 그 패키지와
  변환 백엔드 존재로 판단한다.
- `TEMPLATE_FILL_ADMIN_TOKEN` : 설정 시 템플릿 등록·삭제에 `X-Admin-Token` 요구.
  비워 두면 검사하지 않으며 **기동 로그에 경고가 남는다**(인증 부재를 조용히 넘기지 않음).
- 캔버스 워크플로우 변수 `template_fill_template_id` 로 템플릿 선택 주입.
- **템플릿 색인 캐시 (`template_index.py`)** — 등록 시점에 한 번 파싱해
  `{항목 스키마 + 마크다운}` 을 Redis 에 두고 재사용한다. 예전에는 `/fields`·`/status`·
  대화의 **매 턴**·`/generate` 가 각각 zip+XML 을 다시 풀었다.
  - 무효화 조건은 캐시 값에 담아 대조한다: 내용 해시(파일 교체 감지), `SCHEMA_VERSION`
    (파서 규칙 변경), `LABEL_FIELDS` 설정. **라벨 인식 규칙이나 `FieldSpec` 을 고치면
    `template_index.SCHEMA_VERSION` 을 올려야 한다** — 안 올리면 새 코드가 옛 판정을 읽는다.
  - 캐시는 성능 장치일 뿐이다. Redis 가 죽으면 직접 파싱으로 degrade 하고 경고만 남긴다
    (세션 저장 실패와 다르다 — 그쪽은 값 유실이라 오류로 올린다).
- **관리자 템플릿 등록/삭제**
  - `POST /templates` (multipart: `template`, `template_id` 선택, `overwrite` 선택)
    — 파싱을 **먼저** 하고 파일을 나중에 쓴다. 순서를 바꾸면 해석 불가 파일이 볼륨에 남는다.
    같은 이름이 있으면 409, `overwrite=true` 면 덮어쓴다(임시 파일 → `os.replace` 로 교체).
  - `DELETE /templates/{template_id}` — 파일과 색인을 함께 없앤다(색인만 남으면 목록에
    유령 템플릿이 보인다).
  - `GET /templates` 는 **캐시에 있는 색인만** 상세(`field_count` 등)를 붙인다. 목록을 만들
    때마다 전체 템플릿을 파싱하지 않기 위해서다. 색인이 없으면 `indexed: false` 로 표시하고,
    그 템플릿의 첫 `/fields` 호출이 색인을 만든다.
- **마크다운 미리보기 (`hwpx_markdown.py`, `GET /preview`)** — 표시 전용.
  브라우저는 hwpx 를 렌더링하지 못하므로 다운로드 전에 확인할 수단이 필요하다.
  - 미리보기는 **다운로드와 같은 채우기 경로**(`fill_template`)를 탄다. 별도 렌더러를 두면
    화면과 실제 파일이 어긋난다. 서식(글꼴·크기)은 마크다운에 반영할 자리가 없어 적용하지 않고,
    세션도 건드리지 않는다(세션 종료는 다운로드만 한다).
  - 표는 마크다운 표로 낸다(첨부형 전처리기 산출 형식과 동일). 셀 좌표는 `cellAddr` 이 정본 —
    병합 셀은 앵커 하나만 존재하므로 등장 순서로 채우면 열이 밀린다. 마크다운에 없는 rowspan 은
    앵커 행에만 값을 둔다.
  - 머리말/꼬리말·각주는 제외, 셀 안 표는 평탄화, 상한 초과는 `truncated: true` 로 알린다
    (잘린 미리보기를 문서 전체로 오인하면 빠진 항목을 못 보고 다운로드한다).
  - 대화 응답(`POST /chat/commit`)에는 **채우기 전 템플릿 모양**(`template_markdown`, 색인에 이미
    있어 추가 파싱 없음)과 **지금 값으로 채운 문서**(`document_markdown`, 매 턴 갱신)가
    함께 나간다. UI 문서 창은 후자를 그린다. 턴마다 채우기 1회가 부담되면
    `TEMPLATE_FILL_CHAT_PREVIEW=0` 으로 끄고 `GET /preview` 로 대체한다.

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

> `TEMPLATE_FILL_VERIFY_OUTPUT`(개봉 안전 검사)·`TEMPLATE_FILL_CHECK_OVERFLOW`(표 셀
> 넘침 추정)는 2026-08-12 에 지웠다 — 실제 배포 템플릿 3개가 전부 표 없는 1~2쪽짜리라
> 둘 다 아무 판정도 안 하고 있었다. CLAUDE.md "python-hwpx 벤더 사본" 절,
> 코드는 `archive/hwpx-genon-vendor` 브랜치.

| 변수                                                                   | 기본값                        | 뜻                                                                                                                                                                                 |
| ---------------------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TEMPLATE_FILL_TEMPLATE_DIR`                                           | `./templates`                 | 관리자가 hwpx 템플릿을 두는 **공유 볼륨** 경로                                                                                                                                     |
| `REDIS_URL`                                                            | 사내 GenOS Redis DNS          | 멀티턴 세션 + 템플릿 색인 저장소                                                                                                                                                   |
| `TEMPLATE_FILL_ADMIN_TOKEN`                                            | (없음)                        | 설정 시 템플릿 등록·삭제에 `X-Admin-Token` 요구. **비우면 검사하지 않으며 기동 로그에 경고가 남는다**                                                                              |
| `TEMPLATE_FILL_SLOT_FIELDS`                                            | `1`                           | 본문 슬롯(`제 목 : {'제목', 16pt}`) 인식. 옛 이름 `TEMPLATE_FILL_LABEL_FIELDS` 도 읽는다                                                                                           |
| `TEMPLATE_FILL_APPLY_STYLE_SPEC`                                       | `1`                           | 슬롯 서식 인자를 실제 서식으로 반영                                                                                                                                                |
| `TEMPLATE_FILL_STYLE_SCOPE`                                            | `slot`                        | `slot`(중괄호 자리 run 에만 — 밖은 원래 서식 유지) / `paragraph`(슬롯이 놓인 문단 전체) / `run`(누름틀도 값 run 에만)                                                              |
| `TEMPLATE_FILL_BODY_BLOCKS`                                            | `1`                           | 본문 블록(항목 밖 내용 이어 쓰기)                                                                                                                                                  |
| `TEMPLATE_FILL_BLOCK_ANCHOR`                                           | (없음)                        | 블록 삽입 기준 항목명. 비우면 **문서 끝**. 서명란이 마지막에 있는 템플릿만 지정                                                                                                    |
| `TEMPLATE_FILL_MAX_BLOCKS` / `_MAX_BLOCK_CHARS`                        | `100` / `4000`                | 본문 블록 개수·길이 상한                                                                                                                                                           |
| `TEMPLATE_FILL_CHAT_PREVIEW`                                           | `1`                           | 대화 응답에 채운 문서 미리보기 포함 (부담되면 `0`, `GET /preview` 로 대체)                                                                                                         |
| `TEMPLATE_FILL_MAX_PREVIEW_CHARS`                                      | `20000`                       | 마크다운 미리보기 길이 상한                                                                                                                                                        |
| `TEMPLATE_FILL_MAX_UPLOAD_BYTES`                                       | `20MB`                        | 업로드 템플릿 크기 상한 (전량 메모리 파싱)                                                                                                                                         |
| `TEMPLATE_FILL_MAX_FIELDS` / `_MAX_VALUE_CHARS` / `_MAX_MESSAGE_CHARS` | `200` / `2000` / `20000`      | 입력 상한                                                                                                                                                                          |
| `TEMPLATE_FILL_SESSION_TTL_HOURS`                                      | `24`                          | 버려진 세션 자동 회수 (안전망)                                                                                                                                                     |
| `TEMPLATE_FILL_REDIS_INDEX_PREFIX` / `_INDEX_TTL_HOURS`                | `template_fill:index` / `720` | 템플릿 색인 캐시                                                                                                                                                                   |

PDF 다운로드에는 설정이 없다 — 전처리기 변환기를 그대로 호출하고, 가용 여부는 그 패키지와
변환 백엔드 존재로 판단한다.

#### 워크플로우 변수 (캔버스에서 주입)

| 변수                        | 값                               | 뜻                                                                     |
| --------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| `template_fill_template_id` | 템플릿 파일명(확장자 제외)       | 어떤 양식을 채울지                                                     |

`template_fill_tone`/`_tone_fields` (톤 변환)는 2026-08-12 에 뺐다 — 실제 배포 템플릿이
정해진 톤으로 채우면 되는 성격이라 사용자 발화별 톤 선택이 불필요했다. CLAUDE.md
"글다듬이(톤)는 006 안에서 했었다" 절, 코드는 `archive/sfr006-tone` 브랜치.

#### 엔드포인트 (코드 서빙 03)

| 경로                       | 인증       | 용도                                                       |
| -------------------------- | ---------- | ---------------------------------------------------------- |
| `GET /health`              | —          | 헬스체크                                                   |
| `GET /templates`           | —          | 목록 + 색인 상태 + 지원 형식                               |
| `POST /templates`          | **관리자** | 등록 (multipart: `template`, `template_id?`, `overwrite?`) |
| `DELETE /templates/{id}`   | **관리자** | 삭제 (파일 + 색인)                                         |
| `GET /fields?template_id=` | —          | 항목 스키마 + `block_styles`                               |
| `GET /status?session_id=`  | 세션       | 채움 현황 · `ready_for_download` · `block_count`           |
| `GET /preview?session_id=` | 세션       | 채운 결과 마크다운 (표시 전용)                             |
| `PATCH /values`            | 세션       | 항목 값 수정 (**빈 문자열 = 지움**)                        |
| `DELETE /values`           | 세션       | 항목 값 비우기                                             |
| `PUT /blocks`              | 세션       | 본문 추가 내용 **통째 교체**                               |
| `POST /generate`           | 세션       | 초안 생성 + 다운로드 (`format`: `hwpx`/`pdf`)              |
| `POST /generate/upload`    | —          | 업로드한 hwpx 로 즉석 생성 (multipart)                     |

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

**엔드포인트**

- `POST /polish` : 문서유형·톤 정책에 맞춰 본문을 다듬는다
- `GET /policies` : 문서유형·톤 목록 (UI 선택지)
- `POST /download` : 다듬은 본문을 **txt 파일**로 (2026-08-12 신규 — 018 산출물 통일)
- `GET /health`, `GET ""`/`GET /`

`POST /download` 는 번역 단위와 **같은 규약**이다: 상태 없이 본문(`text` 또는
`polished_text`)을 받아 UTF-8 BOM + CRLF 로 내고, 마크다운 기호를 풀지 않는다
(`markdown_guard` 가 지켜낸 그 구조를 파일에서 깨뜨리지 않기 위해서다).
되돌려 보낼 값은 `polished_text` 이고 화면 표시용 `text` 가 아니다 — 후자에는 경고문과
변경내역이 붙어 있어 파일에 섞이면 사용자가 메모장에서 지워야 한다.

- 워크플로우 변수 `polish_doc_type`, `polish_tone` 로 문서유형/톤 주입
  (톤 고정군은 사용자 요청과 무관하게 정책 톤으로 강제).
- `POLISH_PROMPT_DIR` : 프롬프트 디렉토리 위치를 옮길 때만 지정 (기본은
  배포 단위 기준 `../prompt/SFR-018_text_polish`).
- `POLISH_MAX_INPUT_CHARS` : 입력 상한 (기본 200000). 넘으면 **자르지 않고 거절**한다 —
  잘린 문서를 다듬어 돌려주면 뒷부분이 통째로 사라진 결과가 정상 응답처럼 나간다.
- `RES_TIMEOUT` / `LLM_RETRY_COUNT` / `MODEL_TEMP` : 번역·FAQ 와 같은 이름·같은 기본값
  (2026-08-13 — `text_polish/config.py` 를 만들어 셋을 같은 모양으로 맞췄다. 그전에는
  `llm.py` 가 모듈 최상위에서 직접 읽어 값이 import 시점에 얼어붙었고 `RES_TIMEOUT`
  기본값만 60 이었다).
- **오류 영역코드는 03 이다** (2026-08-13 정정). 이 단위는 2026-08-11 재배치로 코드 서빙이
  됐는데 오류 코드는 계속 02 를 내고 있었다 — 워크플로우 스텝(`sfr018_polish_0{1,2}.py`)이
  내는 02 와 로그에서 구분되지 않는 상태였다.
- 문서유형·톤 정책은 `tone_presets.py` 의 선언 딕셔너리 한 곳에서만 고친다.
  프롬프트 템플릿(`system.j2`)은 그 라벨과 지시문을 변수로 받기만 한다 —
  정책을 프롬프트 문구에 박으면 관리자 UI 가 내려받는 스키마와 실제 지시가 갈린다.

### SFR-018_translation

**엔드포인트**

- `GET /languages` : 지원 언어·문체 목록 + 한국어 축 제약 (화면이 선택지를 하드코딩하지 않게)
- `POST /translate` : 노드 배열 번역
- `POST /translate/markdown` : 전처리기 산출물(마크다운/HTML 표) 구조 보존 번역
- `POST /translate/hwpx` : **hwpx 업로드 직접 파싱** 후 번역 (multipart)
- `POST /download` : 번역문을 **txt 파일**로 (2026-08-12 신규 — 018 산출물 통일)
- `GET /glossary`, `POST /glossary/reload` : 용어사전 상태·재적재(관리자)
- `GET ""` : 루트 (게이트웨이가 경로 없이 베이스를 때리는 배포 대비)

**txt 내려받기** (2026-08-12) — `translation_pipeline/common/txt_output.py`

- **상태를 두지 않는다.** 화면이 들고 있는 번역문을 요청 본문(`text` 또는 `markdown`)으로
  받아 인코딩만 해서 돌려준다. 이 단위에 Redis 를 새로 붙이지 않으려는 것이기도 하고,
  저장을 거치면 "화면과 파일이 다를 수 있는" 경로가 생기기 때문이다.
- **본문을 손대지 않는다.** 마크다운·HTML 표를 평문으로 풀지 않는다 — 그 구조는 원본
  문서에서 온 것이고 "구조는 입력과 동일" 이 이 단위의 계약이다. 마지막 단계에서 우리가
  풀면 지켜낸 구조를 우리 손으로 깨뜨리는 셈이 된다. (FAQ 는 반대다 — 거기서 떼는 기호는
  우리가 붙인 장식이다. 기준은 **그 기호를 누가 넣었나**다.)
- 파일은 UTF-8 BOM + CRLF 다 (메모장 전제. FAQ 절의 같은 설명 참고).

**입력** (2026-08-14 배선 정리)

- 텍스트 입력 : 사용자가 친 글(`question`). 그대로 LLM 에 태우고 용어사전을 참고한다.
- pdf·docx : 전처리기가 바꾼 `genosUploaded` 마크다운.
- hwpx : **직접 파싱**한다. 워크플로우는 캔버스 변수 `translate_hwpx_path`(공유 볼륨
  경로)가 있으면 MCP `hwpx_text.hwpx_to_markdown` 을 먼저 쓰고, 실패하면 전처리기
  산출물로 떨어진다(사유는 로그에 남는다). 코드서빙은 `POST /translate/hwpx` 로 파일을
  직접 받는다. **FAQ 와 같은 배선·같은 MCP 도구**다.
  - **이 배선이 2026-08-14 까지 없었다.** `POST /translate/hwpx` 는 있었지만 캔버스에서
    닿을 수 없어, 캔버스로 올린 hwpx 는 지능형 전처리기 산출물(PDF 변환 → 레이아웃 모델)
    로만 번역됐다 — 요구사항 §5 가 지적한 "표 안 수치가 깨진다" 를 그대로 맞는 경로다.
  - 원본을 어디서 얻었는지는 `translate_source_kind`(`hwpx`/`preprocessor`/`text`)로
    응답과 로그에 나온다. 표 보존 수준이 다르므로 결과가 이상할 때 첫 질문이 그것이다.
  - `truncated` 를 확인해 경고를 남긴다 — 잘린 문서를 번역하면 뒷부분이 통째로 빠진 채
    정상 결과처럼 내려간다.

**지원 범위와 방향** (`translation_pipeline/office/languages.py`)

- 한국어·영어·중국어·태국어·베트남어·러시아어 6개.
- **선택지는 `GET /languages` 가 준다.** 프론트는 이 응답만 보고 그린다 — 화면이 목록을
  따로 들고 있으면 언어나 용어사전 범위가 바뀔 때 한쪽만 고치게 되고, 그 상태는 예외를
  내지 않고 **잘못된 안내**로만 드러난다. 응답에는 언어별 `glossary_supported` 와
  `glossary_languages`(`["ko","en"]`), `korean_axis_required` 가 함께 온다.
- **한국어를 한쪽에 둔 쌍만** 받는다. `en→ru` 같은 비한국어 쌍은 400 이다 —
  품질 검증 대상 밖이라 열어두면 검증 안 된 경로가 운영에서 조용히 쓰인다.
- `source_lang` 을 안 주면 **스크립트 기반으로 결정적으로 감지**한다(LLM 아님 —
  방향 검증은 거부 판정이라 흔들리면 정상 요청이 400 이 된다). 감지값인지 여부는
  응답 `options.source_lang_detected` 로 알린다.
- 숫자·기호뿐이라 감지 불가한 문서는 **거부하지 않고** 방향 검증만 건너뛴다.

**문체** — `register` = `written`(문어체, 기본) | `spoken`(구어체).
알 수 없는 값은 기본값으로 떨어뜨리되 `options.register_fell_back` 으로 알린다.

**용어사전** (`TRANSLATE_GLOSSARY_PATH`)

- **한국어·영어에만 적용한다** (2026-08-14 요구 확정). 중국어·태국어·베트남어·러시아어는
  사내 용어사전이 없으므로 **LLM 만으로** 번역한다. 정책은 `languages.py` 의
  `glossary_supported` 한 곳에 있고, 화면 안내(`GET /languages`)와 실행
  (`glossary_report`)이 **같은 함수**를 본다 — 어느 한쪽에 하드코딩하면 "화면에는 적용
  이라고 떴는데 실제로는 안 걸린" 상태가 되고, 그때 준수율은 `matched_count=0` 이라
  **1.0** 이라 계기판 어디에도 이상이 안 보인다.
- **쌍으로 판정한다** (`glossary_applies`). 대상만 보면 `ru→ko` 가 통과하는데 그때
  색인은 영어 원문 용어를 들고 있어 러시아어 본문에 맞을 리가 없다. 원문 언어를 감지하지
  못했으면 막지 않는다(조회가 빈손으로 끝날 뿐이다).
- 적용되지 않은 이유는 응답 `glossary.source.reason` 으로 갈린다:
  `not_applicable`(대상 밖 언어 — 설계대로) / `not_configured`·`file_not_found`(경로·파일
  문제) / **`language_missing`**(파일은 정상인데 그 언어 항목이 없다 — 사전을 채워야 한다) /
  `disabled_over_limit`. 예전에는 마지막 경우가 `reason: "ok"` 로 나가 "적용 안 됨(사유:
  ok)" 이 됐다.
- 폐쇄망 볼륨의 JSON 또는 CSV 파일 하나. `genos-glossary` 실험의 **1단계
  (정확 매칭)만** 병합했다 — 2단계(Weaviate + 임베딩)는 보류 결정 그대로다.
  **여기에는 2단계 폴백이 없다.** 사전이 상한을 넘거나 파일이 없으면 그 언어는
  용어사전 없이 번역되고, 그 사실이 응답 `glossary.source` 로 나간다.
- 배치에 **실제로 등장한 용어만** 프롬프트에 싣는다(사전 전체를 싣지 않는다).
- 지시로 끝내지 않는다: 번역 후 코드가 다시 대조해 **준수율(`glossary.compliance`)**
  과 하이라이트 데이터를 낸다. `glossary.term_map` 은 `{"원문 용어": "번역 용어"}`
  평면 JSON(프론트 협의 전 기본형), `glossary.hits` 는 유닛별 상세 + `applied` 여부다.

**품질 장치**

- `TRANSLATE_DEDUPE_UNITS`(기본 1) : 같은 원문은 한 번만 LLM 에 보낸다. 반복 머리글이
  자리마다 다르게 번역되는 흔들림도 함께 없어진다. `stats.deduped_unit_count` 로 노출.
- `TRANSLATE_NUMERIC_GUARD` = `warn`(기본) | `revert` : 번역문의 숫자 보존을 코드가
  검사한다(`numeric_guard.py`). 자릿수 구분 기호를 제거하고 비교하므로
  `1,000` ↔ `1.000` 은 오탐이 나지 않는다. 이탈은 `numeric_warnings` 로 노출하고,
  `revert` 면 그 유닛만 원문으로 되돌린다.
- **마크다운 표 셀 번역문의 `|` 를 이스케이프한다.** 안 하면 그 행부터 열이 밀린다
  (HTML 셀은 escape 경로가 이미 막고 있어 마크다운 셀만 뚫려 있었다).
- `stats` 에 `unit_count`/`failed_unit_count`/`fallback_rate` 를 싣는다 —
  루트 README 018 공통 지표(fallback 발생률)의 분모·분자가 예전엔 응답에 없었다.
- **전량 폴백을 성공으로 흘려보내지 않는다** (2026-08-14). 번역 실패 유닛은 원문이 그대로
  남는 것이 설계인데(한 문장 실패로 문서 전체를 버리지 않는다), 그래서 LLM 이 통째로 죽어도
  HTTP 200 이고 `markdown` 이 비어 있지 않다. 워크플로우 스텝 2 가 `markdown` 만 보고
  `translation_error` 를 **한 번도 읽지 않아**, 사용자는 자기가 넣은 글을 번역문으로 받고
  화면 어디에도 실패 표시가 없었다. 지금은 전량 실패는 오류로 끝내고(설정 부재면
  재시도 불가), 부분 실패는 `⚠ N개 문장은 번역하지 못해 원문이 그대로 남아 있습니다` 로
  화면에 말한다.
- **LLM 설정 부재는 500 이 아니다.** `GENOS_URL`/`LLM_SERVING_ID` 가 없을 때
  `_resolve_client()` 의 `RuntimeError` 가 최종 방어선까지 올라가 "잠시 후 다시 시도해
  주세요"(500)가 나갔다 — 다시 눌러도 같은 자리에서 실패하는 **배포 설정 문제**인데
  일시적 오류로 보였다. 지금은 `LlmResult(error_type="CONFIG_MISSING")` 으로 내려
  스텝이 재시도 불가로 안내한다(FAQ 단위가 이미 이 모양이었고 번역만 갈려 있었다).

**hwpx 입력** — `POST /translate/hwpx` 는 전처리기를 거치지 않고 원본 XML 의
`cellAddr` 좌표로 표 격자를 직접 만든다(전처리기를 태우면 표 안 수치가 깨진다).
그 마크다운이 `/translate/markdown` 과 **같은 스켈레톤 분해 경로**를 탄다 —
hwpx 전용 번역 경로를 따로 두면 구조 보존 계약이 두 벌이 된다.

**문서 출력은 하지 않는다.** 요구사항대로 번역 결과는 텍스트/마크다운으로만 나간다.
원본은 `source_markdown` 으로 함께 돌려준다(UI 좌우 대조용 — 화면이 따로 들고 있으면
번역 요청 전후로 원본이 갈릴 수 있다).

- `TRANSLATE_MAX_NODES`, `TRANSLATE_MAX_TOTAL_CHARS`, `TRANSLATE_MAX_UPLOAD_BYTES` : 입력 상한
- `TRANSLATE_ADMIN_TOKEN` : 설정 시 `/glossary/reload` 에 `X-Admin-Token` 요구.
  비워 두면 검사하지 않으며 **기동 로그에 경고가 남는다**.

### SFR-018_faq

FAQ 생성. 대화(02)에서 만들고 다운로드(03)로 내려받는 구성이라 SFR-006 과 같은 모양이다.
초안은 `archive/FAQ.py` 였고, 거기서 고친 것은 `workflow/sfr018_faq_02_generate.py`
머리말에 적었다
(`print()` 로 접속 정보 노출, 정의되지 않은 `model` 참조로 인한 `NameError`,
글자 단위 emit, `result` 에 `{**data}` 미전달, 5개 고정).

**입력** (요구사항 §1)

- pdf·docx : 전처리기가 바꾼 `genosUploaded` 마크다운.
- hwpx : **직접 파싱**한다(`faq/hwpx_text.py`). 워크플로우는 캔버스 변수
  `faq_hwpx_path`(공유 볼륨 경로)가 있으면 그 경로를 우선 쓰고, 코드서빙은
  `POST /generate/upload` 로 파일을 받는다.

**개수** (요구사항 §4)

- 배포 상한 `FAQ_MAX_COUNT`(기본 10), 기본값 `FAQ_DEFAULT_COUNT`(기본 5).
- 캔버스 변수 `faq_max_count` 로 관리자가 재배포 없이 낮출 수 있다.
  **배포 상한을 넘기지는 못한다** — 넘길 수 있으면 LLM 예산 상한이 캔버스 설정
  하나로 무력해진다.
- 사용자는 캔버스 변수 `faq_count` 로 0~상한 안에서 고른다. 상한을 넘겨 요청하면
  깎고 그 사실을 안내에 노출한다(조용히 바꾸지 않는다).

**근거 명시** (요구사항 §2) — 이게 이 단위의 핵심 계약이다

- LLM 은 항목마다 `evidence`(문서에서 그대로 옮긴 문장)를 함께 낸다.
- **코드가 원문과 대조한다**(`faq/evidence.py`): 정규화 후 완전 포함이면 통과,
  아니면 문자 3-gram 자카드가 `FAQ_EVIDENCE_MIN_RATIO`(기본 0.8) 이상이면 통과.
  통과 못하면 기본값으로 **기각**한다(`FAQ_EVIDENCE_REJECT=1`).
  검증 없이 표시만 하면 근거란이 장식이 되고, 지어낸 답변에 그럴듯한 출처가 붙는다.
- 루트 README 018 지표 4절(FAQ 원천 정합성)의 1차 스크리닝과 같은 판정이다.
- 기각 건수(`rejected.schema/ungrounded/duplicate`)를 응답·안내문에 노출한다 —
  조용히 버리면 왜 5개 요청에 3개만 나왔는지 알 수 없다.
- 요청 개수에 못 미치면 이미 채택된 질문을 알려주고 **한 번만** 더 부른다.

**난이도** (요구사항 §5) — "문서를 처음 보는 사람" 기준. 지시문은
`faq/generator.py` 의 `_DIFFICULTY_NOTE` 한 곳에 있고 프롬프트 변수로 넘어간다.

**엔드포인트** (03)

- `GET /config` : 관리자 상한·기본 개수·내려받을 수 있는 형식(**항상 `["txt"]`**).
  값이 하나로 굳었지만 필드는 배열로 남긴다 — UI 계약이라 모양을 바꾸면 화면도 바뀐다.
- `POST /generate` (마크다운 본문) / `POST /generate/upload` (hwpx multipart)
- `GET /faqs?session_id=` : 저장된 FAQ (다운로드 버튼 활성화 판단)
- `POST /download` : `{session_id 또는 items}` → **txt**. `format` 은 생략 가능하다.

**생성 실패는 네 갈래로 갈린다** (2026-08-13 — 그전에는 통신 실패만 갈리고 나머지 셋이
전부 502 였다). 사용자가 할 일이 다르기 때문이다:

| `generator.FAILURE_*` | HTTP | 오류 코드 | 사용자가 할 일 |
| --- | --- | --- | --- |
| `TRANSPORT` | 504 | `ERR_API_UPSTREAM_TIMEOUT` | 잠시 후 다시 |
| `NO_GROUNDED` | **422** | `ERR_API_NO_GROUNDED` | 문서를 바꾸거나 개수를 줄인다 |
| `PROMPT` | **500** | `ERR_API_PROMPT_UNAVAILABLE` (**재시도 불가**) | 관리자에게 문의 |
| 그 외 | 502 | `ERR_API_UPSTREAM_EXECUTION` | 잠시 후 다시 |

매핑은 `faq/main.py` 의 `_FAILURE_ERRORS` 표 한 곳에 있다. 422 를 고른 이유는 워크플로우
스텝(`sfr018_faq_02_generate.py`)이 **이미 그 상태코드를 근거 미확보로 읽도록** 분기를
걸어 뒀기 때문이다 — 서빙이 그 422 를 낸 적이 없어 그동안 닿을 수 없는 코드였다.
프롬프트 부재를 따로 뗀 것은 그것이 **이미지에 프롬프트 디렉토리를 안 넣은 배포 실수**라
재시도가 무의미한데, 502(retryable)로 나가면 캔버스가 반복 재시도를 걸고 로그의
error_type 도 LLM 실패와 같아 원인이 어디에도 드러나지 않기 때문이다.

**다운로드 — txt 하나다** (2026-08-12 요구 변경)

hwpx·pdf·xlsx 를 전부 걷어냈다. 사용자가 결과를 **메모장에서 이어 편집**하기 때문에
문서 형식이 필요하지 않다. 코드는 `archive/sfr018-doc-export` 브랜치에 있다
(`faq/exporters/`, `faq/download_formats.py`, 그리고 그 형식들이 쓰던 오류 코드 2개).

- **다시 생성하지 않고 저장해 둔 것을 내려준다.** LLM 을 다시 부르면 화면에서 본 FAQ 와
  파일 내용이 달라진다. 저장소는 Redis(`faq/session_store.py`)이고, 다운로드는 세션을
  지우지 않는다 — 같은 FAQ 를 다시 받는 흐름이 정상이다.
- **파일은 평문이고 화면은 마크다운이다.** `**Q1.**`·`> 근거:` 는 **우리가** 붙인 장식이라
  메모장에서는 별표와 꺾쇠가 글자로 보인다. 그래서 파일에서는 `Q1.` / `[근거]` 로 내고
  항목 사이에 구분선을 긋는다. 두 형태를 만드는 함수는 `faq/formatting.py` 에 나란히
  있고 **항목 목록은 공유**한다(`_as_tuples`) — 내용이 갈리지 않게.
- **인코딩은 UTF-8 BOM, 줄바꿈은 CRLF** (`faq/txt_output.py`). 옛 메모장은 BOM 없는
  UTF-8 을 cp949 로 읽어 한글을 깨뜨리고, LF 만 있는 파일을 한 줄로 붙여 보여준다.
  환경변수로 끄지 않는다 — 스위치를 두면 "어떤 PC 에서만 깨진다" 가 되고 그 상태는
  로그에 아무 흔적도 남기지 않는다.
- **옛 형식 이름으로 오는 요청은 거절한다**(400). 조용히 txt 를 내려주면 화면은 xlsx 를
  받았다고 믿는데 파일은 txt 인 상태가 되고, 그 어긋남은 기록되지 않는다.
- 501("수단 없음")이 없어졌다. txt 는 볼륨·외부 변환기·시스템 라이브러리를 요구하지
  않으므로 **환경에 따라 켜졌다 꺼졌다 하는 형식이 더는 없다.**

**환경변수**: `FAQ_MAX_COUNT`, `FAQ_DEFAULT_COUNT`, `FAQ_MAX_CONTEXT_CHARS`,
`FAQ_MAX_UPLOAD_BYTES`, `FAQ_EVIDENCE_MIN_RATIO`, `FAQ_EVIDENCE_REJECT`,
`FAQ_PROMPT_DIR`, `FAQ_REDIS_PREFIX`, `FAQ_SESSION_TTL_HOURS`, `FAQ_ADMIN_TOKEN`,
`REDIS_URL`
(`FAQ_HWPX_TEMPLATE_PATH` 는 없어졌다 — 코드가 더는 읽지 않으므로 배포에 남아 있어도
무해하다.)

## 이관 순서 — 어떤 파일을 어떤 차례로 옮겨 적는가

폐쇄망에 옮길 때 참고할 두 가지 순서를 단위별로 적는다.

- **옮겨 적는 순서** = 의존 방향이다. 위 항목은 아래 항목을 모르고, 아래 항목만 위를
  참조한다. 이 순서로 넣으면 중간에 `ImportError` 없이 한 단계씩 확인하며 올라갈 수 있다.
- **실행 시 호출 순서** = 옮긴 게 맞는지 대조할 기준이다. 진입점부터 따라가며 함수가
  같은 차례로 불리는지 보면, 파일 하나를 빠뜨렸을 때 어디서 어긋나는지 바로 드러난다.

공통 전제:

- `config.py` → `logging_utils.py` → `error_codes.py` 는 **어느 단위든 가장 먼저**다.
  셋 다 다른 모듈을 참조하지 않는 잎(leaf)이고, 나머지 전부가 이 셋을 본다.
- `onprem/prompt/<단위>/` 는 배포 단위 밖이라 **파일 목록에 안 잡힌다.** 마지막에
  따로 챙긴다 — 빠뜨리면 기동은 되고 첫 LLM 호출에서 죽는다.
- 진입점(`main.py`, 006 은 `chat_api.py` → `main.py`)은 **항상 맨 마지막**이다. 먼저 올리면 아직 없는
  모듈을 import 하다 죽어서, 진짜 문제가 어디인지 가려진다.

### SFR-006_template_fill (03) + 워크플로우 스텝 3개

**옮겨 적는 순서** (2026-08-12 정정 — 아래 표는 실제 `from .` import 그래프를 다시 훑어
만들었다. 이전 표는 9개 파일(`document.py`·`hwpx_blocks.py`·`chat_state.py`·
`session_view.py`·`api_download.py`·`api_errors.py`·`api_requests.py`·`chat_reply.py`·
`template_store.py`)이 빠져 있었다 — 그중 `document.py`는 채우기·서식을 묶는 조립점이고
`main.py`가 그 앞의 `api_download.py`를 거쳐 결국 이 전부를 끌어오므로, 빠진 채로 손으로
옮기면 진입점을 올리는 마지막 단계에서야 `ImportError`로 드러난다. `_vendor/`·
`overflow.py`·`hwpx_verify.py`는 그사이 코드 자체가 없어졌다 — CLAUDE.md
"python-hwpx 벤더 사본" 절 참고, `archive/hwpx-genon-vendor` 브랜치에 보존.)

| #   | 파일                                                                    | 비고                                                                |
| --- | ----------------------------------------------------------------------- | ------------------------------------------------------------------- |
| 1   | `config.py`, `logging_utils.py`, `error_codes.py`, `hwpx_fields.py`     | 잎 모듈 + 도메인 코어(라벨 항목·누름틀 파서, 다른 모듈을 참조하지 않는다) |
| 2   | `redis_client.py`                                                       | `from_url` 을 부르는 유일한 곳 — 모듈마다 부르면 연결 풀이 늘어난다 |
| 3   | `api_errors.py`, `template_store.py`, `api_requests.py`                 | 1 위에 얹히는 보조 모듈(오류 응답·템플릿 볼륨 I/O·요청 파싱)         |
| 4   | `hwpx_style.py`, `hwpx_blocks.py`, `chat_reply.py`                      | 1 의 `hwpx_fields.py` 파서를 재사용한다                              |
| 5   | `field_judge.py`                                                        | 4 의 `hwpx_blocks.BodyBlock` 을 쓴다                                |
| 6   | `document.py`                                                           | 1(`config`)·4(`hwpx_blocks`·`hwpx_style`)를 묶는 조립점(서식→채우기→블록) |
| 7   | `hwpx_markdown.py`                                                      | **6(`document.py`)을 import한다** — 1 만 본다는 착각에 주의          |
| 8   | `session_store.py`, `template_index.py`                                | 2·7 위에 얹힌다. `SCHEMA_VERSION` 확인                              |
| 9   | `prompt_loader.py` → `prompts.py`                                       | 순서 고정 (후자가 전자를 import)                                    |
| 10  | `llm.py`                                                                | `_chat_url()` 이 `/api/gateway` 를 붙이는 유일한 곳                 |
| 11  | `pdf_convert.py`                                                        | 전처리기 패키지 호출부 (03 전용)                                    |
| 12  | `chat_state.py`                                                         | 5·8 위에 얹힌다                                                     |
| 13  | `session_view.py`                                                       | 5·7·8·11 위에 얹힌다                                                |
| 14  | `api_download.py`                                                       | 6·13 위에 얹힌다                                                    |
| 15  | `chat_api.py`                                                           | 4(`chat_reply.py`)·12 위에 얹힌다                                   |
| 16  | `main.py`                                                               | 진입점 (순서 고정 — 13·14·15 을 전부 import한다)                    |
| 17  | `onprem/prompt/SFR-006_template_fill/*.j2`                              | 이미지에 함께                                                       |

`tone_presets.py`·`value_guard.py`·`tone_apply.py` 는 표에 없다 — 2026-08-12 에 006 의
톤 변환 기능 자체를 없애면서 지웠다(코드는 `archive/sfr006-tone` 브랜치).

**실행 시 호출 순서 — 대화 (02 스텝 3개 → 03 `chat_api`)**

대화는 **캔버스 스텝 셋이 순서대로** 돌고, 계산은 전부 코드서빙에서 한다. 스텝은
게이트웨이 호출과 스트리밍만 한다 (`lxml`·`redis` 를 쓰지 않기 위해서다).

```
[02] sfr006_01_context   → POST /chat/context
                              ├ session_store.load_session   세션 값 + 템플릿 id
                              └ template_index.get_index     항목 스키마 + 마크다운
                                   └ 미스면 hwpx_fields.scan_fields 직접 파싱 후 캐시
[02] sfr006_02_extract   → POST /chat/extract
                              ├ prompts.build_extract_prompts → llm.llm_call_async
                              └ field_judge.parse_updates     updates/clears/rejected
                                                              ← 판정은 코드가 한다
[02] sfr006_03_commit    → POST /chat/commit                  ※ 마지막 스텝
                              ├ session_store.save_session    값 + raw_values 병합
                              ├ hwpx_fields.missing_field_names  채움 판정(03 과 같은 함수)
                              ├ hwpx_markdown.render_filled   문서 창에 그릴 마크다운
                              └ chat_reply.compose_status_reply  답변 문구
                           → _stream_chunks → emit("token") → yield event: result
```

톤(글다듬이) 변환 단계는 2026-08-12 에 없어졌다 — 006 이 채우는 템플릿은 관리자가 정한
고정 톤으로 채우면 되는 성격이라, 사용자 발화별로 톤을 골라 다시 쓸 이유가 없었다.

**실행 시 호출 순서 — 다운로드 `POST /generate` (03)**

```
generate(body)
 1. _resolve_format                   → hwpx | pdf
 2. session_store.load_session        → 대화에서 모은 값
 3. _load_template_bytes              → TEMPLATE_DIR 볼륨에서 읽기
 4. asyncio.to_thread(_build_document)     ← zip/XML 작업이라 스레드로 뺀다
      ├ hwpx_fields.fill_template      → 값 기록 + 명세 표기 제거
      └ hwpx_style.collect_style_specs → apply_styles  (실패해도 문서는 낸다)
 5. _finalize_document                 → pdf 면 pdf_convert.to_pdf
      └ 501(수단 없음) / 500(변환 실패) 구분. 실패 시 세션을 남긴다
 6. session_store.end_session          ← **성공했을 때만**
 7. _document_response                 → Content-Disposition + X-Styled-Fields
```

### SFR-018_text_polish (03) + 워크플로우 스텝 2개

**옮겨 적는 순서**: `config.py`·`logging_utils.py`·`error_codes.py` → `tone_presets.py`
→ `prompt_loader.py` → `llm.py` → `main.py`
→ `onprem/prompt/SFR-018_text_polish/system.j2`

**`diff_report.py`·`markdown_guard.py`·`fact_guard.py` 는 이 단위에 없다** —
`mcp/genon_text_guard.py` 로 옮겼다 (2026-08-11). 셋 다 LLM 을 부르지 않는 순수
함수라 워크플로우가 직접 부를 수 있고, 이제 번역·FAQ 도 같은 판정을 쓴다.

**실행 시 호출 순서 — 02 스텝 2개 → 03 `/polish` + MCP**

```
[02] sfr018_polish_01_policy  → MCP lang_policy.resolve_tone
                                   → (문서유형, 톤, 정책강제 여부) + tone_notice
                                입력 정규화·업로드 문서 추출도 여기서 한다
[02] sfr018_polish_02_polish  → POST /polish            ※ 마지막 스텝
                                   ├ _build_system_prompt → prompt_loader.render
                                   └ llm.polish_text_async → LlmResult
                              → MCP text_guard ×3 (asyncio.gather — 서로 독립)
                                   ├ markdown_structure_issues  표·제목·코드펜스 지문
                                   ├ fact_issues                숫자·날짜 다중집합
                                   └ diff_changes               difflib 변경 내역
                              → 경고 조립 → _stream_chunks → emit → event: result
```

세 점검은 실패해도 본 결과 전달을 막지 않는다(경고만). **점검 호출 자체가 실패한 경우도
침묵하지 않는다** — `event=text_guard_call_failed` 로 남겨 "경고 없음" 과 구분한다.
이 단위는 **문서 출력이 없다** — 채팅 응답으로 끝난다.

### SFR-018_translation (03)

**옮겨 적는 순서** (2026-08-12 정정 — `api_contract.py`가 빠져 있었다. `main.py`가 최상위
`from api_contract import (...)`로 직접 끌어오는 요청/응답 모델 파일이라, 없으면 진입점
기동 단계에서 `ImportError`로 죽는다.)

| #   | 파일                                                                      | 비고                                |
| --- | ------------------------------------------------------------------------- | ----------------------------------- |
| 1   | `config.py`, `translation_pipeline/common/{logging_utils,error_codes}.py`, `api_contract.py` | 잎 (`api_contract.py`는 error_codes·logging_utils만 본다) |
| 2   | `office/languages.py`, `office/registers.py`                              | 방향 검증·문체. 다른 모듈 참조 없음 |
| 3   | `office/types.py`                                                         | 아래 전부가 쓰는 값 객체            |
| 4   | `common/glossary_store.py` → `common/glossary_exact.py`                   | 적재 → 매칭                         |
| 5   | `common/prompt_loader.py` → `common/prompt_builder.py`                    | 순서 고정                           |
| 6   | `common/llm.py`, `common/validation.py`                                   | 호출·응답 검증                      |
| 7   | `office/markdown_units.py`, `office/hwpx_text.py`, `office/units.py`      | 분해/재조립                         |
| 8   | `office/numeric_guard.py`, `office/glossary_report.py`                    | 사후 검증                           |
| 9   | `office/translation_modes.py` → `office/pipeline.py`                      | 실행 → 오케스트레이션               |
| 10  | `main.py`                                                                 | 진입점                              |
| 11  | `onprem/prompt/SFR-018_translation/*.j2`                                  |                                     |

**실행 시 호출 순서 — `POST /translate/markdown`**

```
translate_markdown(body)
 └ pipeline.run_markdown_translation_job
     1. markdown_units.split_markdown   → (스켈레톤 segments, 번역 units)
                                          구조는 여기서 코드가 쥔다. LLM 은 못 건드린다
     2. _resolve_options
          ├ languages.resolve_direction → 한국어 축 검증 (감지는 스크립트 기반)
          └ registers.resolve_register  → 문어체/구어체 (알 수 없으면 fell_back 표시)
     3. _run
          └ translation_modes.translate_units
               a. _dedupe                    → 같은 원문은 한 번만
               b. _split_batches             → 문자수·건수 상한으로 분할
               c. glossary_report.terms_for_batch → 이 배치에 등장한 용어만
                  prompt_builder.build_batch_prompts → llm.llm_call_async
                  validation.validate_translation_batch_response
                  (실패 시 retry≤2 → 단건 폴백 `build_single_prompts`)
               d. numeric_guard.find_numeric_drift → warn | revert
          └ glossary_report.build_report    → compliance / term_map / hits
     4. markdown_units.rebuild_markdown  → 구조는 원본과 항상 동일
     5. units.build_pairs                → 원문·번역 쌍 (unit_id 포함)
```

`POST /translate` 는 1 대신 `units.build_translation_units(nodes)` 를 타고 나머지가 같다.
`POST /translate/hwpx` 는 앞에 `hwpx_text.to_markdown` 이 붙고 **그 다음은 위와 같은 경로**다
— hwpx 전용 번역 경로를 따로 두면 구조 보존 계약이 두 벌이 된다.

### SFR-018_faq (03) + 워크플로우 스텝 2개

**옮겨 적는 순서** (2026-08-12 갱신 — 내보내기 6파일이 없어지고 `txt_output.py` 가 들어왔다.
옮길 분량이 약 1,000줄 줄었다.)

| #   | 파일                                                       | 비고                                                    |
| --- | ---------------------------------------------------------- | ------------------------------------------------------- |
| 1   | `config.py`, `logging_utils.py`, `error_codes.py`, `api_contract.py` | 잎 (`api_contract.py`는 error_codes·logging_utils만 본다) |
| 2   | `txt_output.py`                                            | 잎. **세 018 단위에 같은 사본** (인코딩·CRLF·파일명)     |
| 3   | `redis_client.py` → `session_store.py`                     |                                                         |
| 4   | `hwpx_xml.py` → `hwpx_text.py`                             | hwpx 직접 파싱 (표 격자) — **입력 전용**                |
| 5   | `evidence.py`                                              | **근거 대조 — 이 단위의 핵심 계약**                     |
| 6   | `prompt_loader.py`, `llm.py`                               |                                                         |
| 7   | `generator.py`                                             | 5·6 을 묶는다                                           |
| 8   | `formatting.py`                                            | 화면 마크다운 + **파일 평문**, 항목 목록은 공유          |
| 9   | `main.py`                                                  | 진입점                                                  |
| 10  | `onprem/prompt/SFR-018_faq/*.j2`                           | 이미지에 함께                                           |

**실행 시 호출 순서 — 생성 (02 스텝 2개 → 03 `/generate`)**

```
[02] sfr018_faq_01_source   → MCP hwpx_text.hwpx_to_markdown   (faq_hwpx_path 가 있을 때)
                                 없거나 실패하면 전처리기 산출물에서 본문 추출
                            → GET /config → 배포 상한 확인
                            → 개수 결정: 배포 상한 ∩ 캔버스 상한 ∩ 사용자 요청
[02] sfr018_faq_02_generate → POST /generate                    ※ 마지막 스텝
                                 a. EvidenceChecker(source)     원문 지문 준비
                                 b. prompt_loader.render → llm.llm_call_async
                                 c. _parse_faq_payload → _adopt 스키마·근거·중복 기각
                                                                (건수 보존)
                                 d. 부족하면 retry_shortfall.j2 로 **한 번만** 추가 요청
                                 e. to_export_rows → session_store.save_faqs
                                    ← 저장 실패해도 응답은 나간다
                            → _stream_chunks → emit → event: result
                              (faq_items / faq_session_id / faq_download_ready)
```

**hwpx 파싱이 MCP 로 갔다.** 예전에는 스텝이 `lxml` 로 직접 팠고, 번역 단위에 사실상
같은 사본이 또 있었다. 지금은 `genon_hwpx_text` 한 벌이고, `check_table_grid.py` 가
그 사본과 코드서빙 3벌의 격자 규칙이 갈리지 않았는지 **출력으로** 대조한다.

**실행 시 호출 순서 — 다운로드 `POST /download` (03)**

```
download(body)
 1. 형식 판정                             ← txt 만. 옛 이름(hwpx/pdf/xlsx)은 400
 2. session_store.load_faqs              ← **다시 생성하지 않는다** (items 를 직접 받으면 생략)
 3. formatting.rows_to_plain_text        ← 평문 조립 (Q1. / [근거] / 구분선)
 4. txt_output.to_bytes                  ← CRLF 변환 + UTF-8 BOM
    txt_output.safe_stem / headers       ← 파일명 정리 + RFC 5987 헤더
 5. 세션은 지우지 않는다 — 같은 FAQ 를 다시 받는 흐름이 정상이다 (006 과 다르다)
```

2026-08-12 전에는 2 뒤에 `_build_bytes(fmt)` 가 있어 xlsx(openpyxl)·pdf(weasyprint 또는
전처리기 변환기)·hwpx(템플릿 반복 블록 deepcopy)로 갈라졌다. 그 셋과 형식 가용성 판별,
501/500 구분이 전부 없어졌다.

03 의 `POST /generate`·`/generate/upload` 는 대화를 거치지 않는 재생성 경로다.
`_generate_and_store` → `generator.generate_faqs` → `session_store.save_faqs` 로
**02 와 같은 생성 함수**를 탄다 — 그래서 03 이미지에도 프롬프트 디렉토리가 필요하다.

### 옮긴 뒤 확인 순서

기능을 눌러 보기 전에 이 차례로 확인하면 원인 추적이 짧아진다.

1. `GET /health` — 기동 자체.
2. 기동 로그 — `prompt_dir_loaded` 가 뜨는지, `admin_token_missing` 경고가 있는지.
3. `GET /config`(FAQ) · `GET /templates`(006) · `GET /languages`(번역) — 설정이 기대대로인지.
   **006 에서 pdf 가 빠져 있으면 이미지 구성 문제**지 코드가 아니다. FAQ 의 `formats` 는
   환경과 무관하게 항상 `["txt"]` 이므로, 다르게 나오면 배포된 리비전이 옛 코드다.
4. LLM 없는 경로 먼저 — 006 `GET /preview`, 번역 `POST /translate/hwpx` 의 파싱 단계.
5. 그 다음에 LLM 경로. 실패하면 로그의 `event` 로 갈린다:
   `prompt_render_failed`(디렉토리 누락) / `upstream_status`(게이트웨이) / 그 외.

## 코드서빙 실행 — **단위별 모듈 경로가 다르다**

리비전 상세 > 환경 설정 에 넣는 값이다 (가이드 6.3).

빌드 커맨드는 여덟 단위 모두 같다: `pip install -r requirements.txt`.
시작 커맨드만 다르다.

```
# 코드서빙 (codeserving/)
SFR-006_template_fill : uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT
SFR-018_text_polish   : uvicorn main:app            --host 0.0.0.0 --port $PORT
SFR-018_translation   : uvicorn main:app            --host 0.0.0.0 --port $PORT
SFR-018_faq           : uvicorn faq.main:app        --host 0.0.0.0 --port $PORT

# MCP (mcp/) — **시작 커맨드가 없다.** 파일을 등록하면 GenOS 가 실행한다.
genon_text_guard.py / genon_lang_policy.py / genon_glossary.py / genon_hwpx_text.py
```

`main:app` 을 006·FAQ 에 쓰면 루트에 `main.py` 가 없어 기동 실패한다. 단위마다 구조가
다른 것이 원인이고, 통일하려면 루트에 `app` 을 재노출하는 `main.py` 를 두면 된다
(지금은 두지 않았다 — 실제 진입점이 두 곳으로 보이는 것도 혼동거리라서).

- **006 과 FAQ 는 시작(Run) 커맨드 등록이 필수다.** 가이드 6.2 는 저장소 루트의 `main.py`
  또는 `src/main.py` 가 있으면 그 파일을 먼저 실행한다고 정하는데, 이 둘의 진입점은
  패키지 안(`template_fill/main.py`·`faq/main.py`)이라 그 자동 경로에 걸리지 않는다.
- 나머지 둘(글다듬이·번역)은 루트에 `main.py` 가 있어 자동 경로를 탄다. 그래서
  `if __name__ == "__main__"` 에 uvicorn 기동 블록을 둔다 — 없으면 모듈만 로드되고
  서버가 뜨지 않는다. `check_deploy_contract.py` 가 이 둘을 갈라서 확인한다.
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

### 저장소 구조 — 서빙은 8개, 저장소는 1개로 간다

**먼저 헷갈리지 말 것: 서빙 등록 수와 저장소 수는 별개다.**

- **서빙 등록은 단위마다 반드시 따로 한다.** 코드 서빙 하나 = 컨테이너 하나 = URL 하나이고,
  리비전·환경 변수·복제본이 전부 서빙 단위로 붙는다. 우리는 코드서빙 4 + MCP 4 = **등록
  8번**이다. 저장소를 어떻게 두든 이 숫자는 줄지 않는다.
- **저장소는 하나로 둘 수 있다.** 서빙 생성 시 적는 것은 저장소 정보와 브랜치·커밋 해시뿐이고,
  **여러 서빙이 같은 저장소·같은 커밋을 가리켜도 된다.** 다만 가이드에 "이 하위 디렉토리를
  루트로 본다" 는 항목이 **없어서**, 디렉토리 구분은 빌드·시작 커맨드가 흡수해야 한다:

  ```
  BUILD : pip install -r onprem/codeserving/SFR-006_template_fill/requirements.txt
  RUN   : cd onprem/codeserving/SFR-006_template_fill && \
          uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT
  ```

**한 저장소로 간다. 근거는 사본 대조다.** 배포 단위 간 import 금지 때문에 이 저장소에는
**의도적으로 유지하는 중복**이 있다 — 표 격자 규칙 4벌(`check_table_grid`), 톤 프리셋
4벌(`check_tone_policy`), 로깅 유틸 8벌. 그 사본들이 갈리지 않았는지는 **한 커밋 안에서
동시에 읽을 수 있어야** 확인할 수 있다. 저장소를 8개로 쪼개면 `onprem/test/` 의 대조
점검이 저장소 경계를 넘어야 해서 **성립하지 않는다.** 커밋 해시 하나로 8단위의 버전이
함께 묶이는 것도 같은 이유로 이득이다(어느 서빙이 어느 사본을 들고 있는지가 자명해진다).

**대가는 안다.** 서빙 8개가 각각 저장소 전체를 받으므로 빌드 컨텍스트가 필요 이상으로
크고, 한 단위만 고쳐도 8개 서빙의 커밋 해시가 같이 움직인다(리비전을 안 올리면 되므로
배포가 강제되지는 않는다). 가이드 §E.1 의 "저장소가 배포 단위" 서술과도 결이 다르다.

**실물에서 확인할 것 하나**: 빌드·시작 커맨드가 셸을 거쳐 실행되는지 —
위 `cd A && B` 와 `&&` 가 그대로 먹는지에 달렸다. 안 먹으면 시작 커맨드를
`uvicorn --app-dir onprem/codeserving/SFR-006_template_fill template_fill.main:app` 형태로
바꾼다(그건 셸이 필요 없다). **이 확인 전까지 저장소를 쪼개지 않는다.**

## 워크플로우 스트리밍 규약 (02 두 단위 공통 — 가이드 5.2 / GENOS_RULES §D)

- **함수명은 정확히 `run`, 인자는 `data` 하나.** 다른 이름이면 `run function not found`
  - HTTP 500 이다. 바꿀 수 있는 값이 아니다.
- `run` 은 async generator 로, 마지막에 `event: result` 를 **1회** yield 한다.
  그 `data` 가 다음 스텝의 `data` 가 되므로 `{**data, ...}` 로 넘겨 `genos_state` 를 잃지 않는다.
- **`sio_server.emit` 뒤에는 반드시 `await asyncio.sleep(0)`.** 양보하지 않고 emit 을
  몰아치면 소켓 쓰기가 버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다(가이드 D.4 "스트리밍이
  일괄 반환되는 원인"). 실제 운영 브리지(`genos_files/bridge.py`)도 매 emit 뒤에 넣는다.
- **토큰은 청크 단위로 보낸다** (`_STREAM_CHUNK_CHARS`, 32자). 글자 하나씩 emit 하면
  현황표 한 장이 emit 수백 회가 되고, 양보 횟수가 그만큼 늘어 오히려 표시가 느려진다.

## 가이드 준수 점검 (2026-08-07 실시 — `genos-project/docs/GENOS_RULES.md` 체크리스트)

네 배포 단위를 조항별로 대조한 결과. **통과 항목은 근거를 함께 적는다** — 다음에
같은 점검을 할 때 다시 처음부터 뒤지지 않기 위해서다.

| 조항                                 | 결과                    | 근거                                                                                                                                                                                                                                                              |
| ------------------------------------ | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A.1 오류코드 `{영역}-{00020001/2/3}` | 통과                    | 네 단위 `error_codes.py` 전수 확인. 실제 등장하는 공통코드는 그 셋뿐이고 영역코드는 `02`/`03` 뿐                                                                                                                                                                  |
| A.3 `detail` 에 예외 원문            | 통과                    | `detail` 필드를 **아예 쓰지 않는다.** 사유는 `error_type` 으로 로그에만 남긴다                                                                                                                                                                                    |
| A.4 영역별 전달 방식                 | 통과                    | 02 는 토큰 스트리밍 후 `{"event":"result","data":{**data,"error":…}}`, 03 은 HTTP 상태 + `{error_code,msg}`                                                                                                                                                       |
| B 외부 호출 timeout·재시도 상한      | 통과                    | `llm.py` 네 사본 모두 클라이언트·호출 양쪽에 timeout, `range(retry_count)` 상한 루프                                                                                                                                                                              |
| C `print()` 금지                     | 통과                    | 저장소 전체 0건                                                                                                                                                                                                                                                   |
| C 로그 화이트리스트                  | 통과                    | `logging_utils.py` 가 허용 필드 외를 값 없이 이름만 남긴다(`[dropped_fields=…]`)                                                                                                                                                                                  |
| D.1 `run` 시그니처                   | 통과                    | 02 두 단위 모두 async generator, 마지막 `event: result` 1회                                                                                                                                                                                                       |
| D.2 전역 가변 상태                   | 통과                    | 세션은 Redis. 모듈 전역은 lazy LLM 클라이언트 캐시뿐이고, 이건 커넥션 재사용이라 D.2 가 막는 대상이 아니다                                                                                                                                                        |
| E `/health` 200                      | 통과                    | 코드서빙 세 단위                                                                                                                                                                                                                                                  |
| E async 안 blocking 금지             | **1건 고침**            | 번역 `_startup` 이 용어사전 파일을 직접 읽고 있었다 → `asyncio.to_thread`. `/glossary/reload` 는 원래 맞게 돼 있어 규약이 한쪽만 달랐다                                                                                                                           |
| H `/api/gateway` 경로                | 통과                    | 네 단위 모두 `llm.py` 의 `_base_url()`/`_chat_url()` 한 곳에서 조립                                                                                                                                                                                               |
| I 타입힌트                           | **부분 미준수(의도적)** | 성공/오류로 반환형이 갈리는 라우트는 주석을 붙이지 않는다. FastAPI 가 `Response` 서브클래스가 아닌 반환 주석을 `response_model` 로 삼아, `JSONResponse \| dict` 같은 Union 은 라우트 등록에서 앱을 죽인다. 번역 `glossary_reload` 하나가 그 형태였고 **떼어냈다** |

**게이트웨이 없이 확인한 범위다.** 위 표는 코드 대조와 로컬 실행 결과이고,
실제 GenOS 에 올려 돌린 결과가 아니다. 아래 두 가지는 여전히 실물 확인이 남았다.

- 로컬에 `fastapi` 가 없어 **앱 구성 단계(라우트 등록)를 실행해 보지 못했다.**
  위 `I` 항목은 FastAPI 의 알려진 동작을 근거로 고친 것이고, 실제 크래시를 재현해
  확인한 것은 아니다.
- 워크플로우(02) 실행은 GenOS 캔버스에서만 가능하다 — `run` 시그니처·스트리밍 규약은
  코드 대조로만 확인했다.

**가이드와 의도적으로 다른 것 하나**: §H 는 프롬프트를 GenOS Prompt 리소스
(admin-api `GET /prompt/template/{id}`)에서 받아오라 하고 "코드 안 긴 문자열 인라인"을
금지한다. 지금은 그 중간 단계로 **배포 단위 밖 jinja 파일**을 쓴다 — 인라인 금지는
지키면서, 폐쇄망에 Prompt 리소스가 준비되면 `prompt_loader.render()` 안쪽만 갈아 끼우면
되도록 호출부를 한 함수로 모아 뒀다.

## 의존 패키지

각 단위의 **`requirements.txt` 가 정본**이고 빌드 커맨드가 그걸 설치한다. 아래 표는
읽는 사람을 위한 요약이다.

| 단위                     | 패키지                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| SFR-006 코드서빙(03)     | `fastapi`, `uvicorn`, `pydantic`, `python-multipart`, `lxml`, `redis`, `httpx`, `jinja2`                            |
| SFR-018 글다듬이(03)     | `fastapi`, `uvicorn`, `pydantic`, `httpx`, `openai`, `jinja2`                                                       |
| SFR-018 번역(03)         | `fastapi`, `uvicorn`, `pydantic`, `python-multipart`, `httpx`, `openai`, `jinja2`, `lxml`                           |
| SFR-018 FAQ 코드서빙(03) | `fastapi`, `uvicorn`, `pydantic`, `python-multipart`, `httpx`, `lxml`, `redis`, `jinja2` — **선택 의존 0개** (2026-08-12: `openpyxl`·`markdown`·`weasyprint` 제거) |
| MCP `genon_text_guard`   | `fastapi`, `uvicorn` — 판정 다섯은 **표준 라이브러리만** 쓴다                                                        |
| MCP `genon_hwpx_text`    | `fastapi`, `uvicorn`, `lxml`                                                                                        |
| MCP `genon_glossary`     | `fastapi`, `uvicorn`                                                                                                |
| MCP `genon_lang_policy`  | `fastapi`, `uvicorn`                                                                                                |
| **워크플로우 스텝 9개**  | **`httpx` 뿐** — 기본 이미지에 있다. `requirements.txt` 를 설치하지 않는다                                          |

**워크플로우 줄이 이 표에서 제일 중요하다.** 재배치 전에는 `lxml`·`redis`·`jinja2` 가
거기 있었고, 그 셋이 기본 이미지 변경 요청(11.5.6)에 묶여 배포를 막고 있었다. 지금은
스텝이 게이트웨이로 코드서빙·MCP 를 부르기만 하므로 **추가 요청이 필요 없다.**
`check_deploy_contract.py` 의 "워크플로우 스텝 / 허용 패키지" 항목이 이 상태를 지킨다.

전부 pip 설치 가능 — 시스템 레벨 도구는 쓰지 않는다. 배포 환경에 달린 것은 **두 가지로
줄었다** (2026-08-12: 018 산출물이 txt 로 통일되면서 하나가 없어졌다):

- **006 의 PDF 는 코드서빙 이미지에 전처리기 패키지(`genon.preprocessor`)가 포함돼야 한다.**
  없으면 `GET /templates` 응답에서 pdf 가 빠지고 요청은 501 이 된다. hwpx 는 정상이다.
- **프롬프트 디렉토리(`onprem/prompt/…`)를 이미지에 함께 넣어야 한다** (위 절 참고).
- ~~FAQ hwpx 템플릿 볼륨(`FAQ_HWPX_TEMPLATE_PATH`)~~ — **전제가 아니게 됐다.** FAQ 는 이제
  txt 만 내므로 볼륨·시스템 라이브러리·한글 폰트 어느 것도 요구하지 않는다.
  018 세 단위 중 **파일을 내기 위해 환경에 무언가를 요구하는 단위는 없다.**
