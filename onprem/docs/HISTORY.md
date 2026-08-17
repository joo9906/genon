<!-- 루트 CLAUDE.md 에서 옮겨 온 **완료된 작업 기록** (2026-08-17).
     어느 디렉토리에서도 자동 로드되지 않는다 — 필요할 때 직접 읽는다.
     내용은 옮길 때 한 글자도 바꾸지 않았다. -->

# onprem 작업 기록 (완료분)

## 이관 직전 리팩토링 (2026-08-14) — **죽은 코드와 거짓말하는 코드만 걷어냈다**

동작을 바꾸지 않는 정리다. 기준은 하나였다 — **폐쇄망에 손으로 옮겨 적을 값어치가 있는가.**

| 걷어낸 것 | 왜 |
|---|---|
| MCP 네 파일의 `*TOOL_SPECS` (**196줄**) | `/mcp/list` 를 우리가 구현하던 시절의 JSON-Schema 목록. **아무 데서도 읽히지 않았고**, 고쳐도 노출 스키마가 안 바뀐다 — 고친 사람은 바뀐 줄 안다 |
| `glcontains_phrase`·`glload_on_startup`·`glconfigure_logging`·`gllog_error` | 번역 코드서빙에서 옮겨 온 잔재. 독스트링이 **없는 것을 가리키고 있었다**("`main.py` 가 부른다", "코드 서빙 진입점에서 호출") |
| `tgformat_changes_markdown` | 변경 내역 마크다운은 워크플로우 스텝이 조립한다 |
| 006 `chat_reply.stream_chunks`·`STREAM_CHUNK_CHARS` | 2026-08-11 재배치로 스트리밍이 스텝의 일이 됐다. 스텝은 자기완결이라 이쪽을 import 할 수도 없다 |
| FAQ `formatting.rows_to_markdown` | `/faqs` 는 항목 배열을 내고 화면 마크다운은 `render_markdown` 이 만든다 |

**고친 것 셋** (동작이 바뀐다):

1. **MCP 의 `print()` → stderr 로깅.** §C 위반이었고, 무엇보다 **stdout 이 전송 채널일 수
   있다**(stdio 방식) — 로그 한 줄이 프로토콜을 깨뜨린다. 그냥 `logging` 으로 바꾸면
   **더 나빠진다**: 설정 없는 프로세스에서 `logger.info` 는 **아무 데도 안 나온다**(기본
   최후 핸들러가 WARNING 부터). 그래서 파일마다 stderr 핸들러를 붙였다(`propagate=False` —
   루트에 stdout 핸들러가 있으면 그리로 샌다). **점검이 print 금지와 핸들러 유무를 함께
   본다** — 하나만 보면 반대쪽으로 조용히 무너진다.
2. **`genon_hwpx_text` 만 도구 감싸개가 없었다.** 나머지 셋은 `_xx_run → xxcall_tool →
   HANDLERS` 인데 이 파일만 도구 함수가 본문을 직접 부르고 예외 처리를 복제해서,
   `hxcall_tool` 이 죽은 코드로 남아 있었다. 네 파일을 같은 모양으로 맞췄다 — 한 서버에
   함께 올라가는 파일들이라 나란히 놓고 읽을 수 있어야 한다.
3. **`genon_glossary` 의 로거 이름이 `translation_pipeline` 이었다.** 이 MCP 가 남긴 줄이
   번역 코드서빙의 로그처럼 보인다. 로거 이름을 파일 이름으로 맞췄다.

**워크플로우·코드서빙에서도 "하나만 다른 것" 을 찾아 맞췄다** (같은 날 후반):

- **`_post_serving` 이 세 가지 모양이었다.** 다섯 스텝은 전송·재시도를 `_post_json` 으로
  빼 뒀는데 나머지 넷(006 셋 + FAQ-2)은 **같은 로직을 파일 안에 한 벌 더** 갖고 있었다.
  그 안에 재시도 가능 여부 판정(`_upstream_kind`)이 들어 있다 — 2026-08-14 에 아홉 스텝을
  한꺼번에 고쳐야 했던 그 로직이고, 모양이 둘이면 다음 사람이 한쪽만 고친다. 아홉을
  `_post_json` + `_post_serving(env_name, path, payload)` 한 모양으로 맞췄다.
- **그물이 없었다.** `check_workflow_steps` 는 "무엇을 import 하는가" 만 봤다. **공유 헬퍼
  13종이 스텝마다 같은 코드인지** 보는 `check_workflow_step_copies()` 를 넣었다(독스트링은
  비교하지 않는다 — 문구까지 맞추라고 하면 주석을 지우는 쪽으로 도망가게 된다).
  한 스텝의 재시도 간격만 바꿔 FAIL 이 나는 것을 확인했다.
- **`Config` 읽는 시점을 넷이 통일했다** (위 "설정 부재" 절의 미결 항목). 게이트웨이 세
  값이 006·번역·FAQ 에서는 **import 시점에 굳고** 글다듬이만 호출 시점이었다.
  참조 지점이 각 단위 `llm.py` 뿐이라 작은 변경이었고, import 뒤 환경을 주입해도 URL 이
  따라오는 것을 실측했다.

**손대지 않은 것 (의도된 것이라 그대로 둔다)**:

- **워크플로우 스텝의 긴 `run`**(최대 231줄)과 그 밖의 파일 간 중복(로깅·오류표). 공용
  모듈로 빼면 **캔버스에 붙일 수 없다** — 그래서 사본을 없애는 대신 **같게 유지**한다.
- **`llm.py` 가 두 갈래인 것**: 006·FAQ 는 httpx 로 직접, 번역·글다듬이는 `openai` SDK 로
  부른다(그래서 `_chat_url` vs `_base_url`+`_resolve_client`). 전송 방식 자체가 다른 것이라
  이관 직전에 한쪽으로 몰지 않았다 — 바꾸면 재시도·타임아웃 동작이 함께 움직인다.
- **표 격자 4벌·톤 프리셋 3벌·`txt_output` 3벌·로깅 유틸 8벌.** 배포 단위 간 import
  금지로 강제된 사본이고, 갈렸는지는 대조 점검이 출력으로 본다.

**기능 명세는 `onprem/docs/FEATURES.md` 에 있다** — 무엇이 구현돼 있고 어느 경로로
부르며 무엇을 보장하는지. 이 파일(CLAUDE.md)은 "왜 그렇게 했나" 를 맡는다.
**폐쇄망에 옮겨 적을 차례는 `onprem/WORK.MD`** — 어느 단위·어느 파일부터 쓰는지, 파일마다
몇 줄인지, 단계마다 무엇으로 끝났다고 판정하는지 (파일 목록·의존 순서의 정본은
`onprem/README.md` "이관 순서" 절이고, WORK.MD 는 그것을 작업 차례로 엮은 것이다).

**python-hwpx 벤더 사본 — 도입(2026-08-10) 후 철회(2026-08-12).** 006 은 한동안
개봉 안전 게이트·넘침 측정을 위해 python-hwpx 일부를
`onprem/codeserving/SFR-006_template_fill/template_fill/_vendor/` 에 벤더 사본으로 두고
있었다(Apache-2.0, 상류 rev `caeb9cf`, ≈1,670줄) — pip 의존으로 두면 폐쇄망 registry 에
wheel 이 있는지에 따라 두 검사가 켜졌다 꺼졌다 했기 때문이다.

**지금은 뺐다.** 실제 배포 템플릿이 3개뿐이고 전부 표 없는 1~2쪽짜리라, 넘침 측정(표 셀
슬롯만 잰다)과 개봉 안전 게이트 둘 다 실질적으로 아무 판정도 하지 않는 코드였다 — 유지
비용(벤더 사본 약 2,000줄 + `overflow.py`·`hwpx_verify.py` 약 800줄, 전부 폐쇄망 이관 시
손으로 옮겨 적어야 하는 분량)에 값하는 실익이 없었다. `_vendor/` 전체와
`overflow.py`·`hwpx_verify.py`, 그리고 `document.py`의 `verify` 매개변수 및
`TEMPLATE_FILL_VERIFY_OUTPUT`·`TEMPLATE_FILL_CHECK_OVERFLOW` 설정을 지웠다.

**되살릴 일이 생기면 `archive/hwpx-genon-vendor` 브랜치에 그대로 있다** — 도입 판단 근거는
`onprem/docs/hwpx_library_adoption.md`(그 브랜치 시점 기준, 지금은 미적용), 재동기화
절차는 `git show archive/hwpx-genon-vendor:onprem/codeserving/SFR-006_template_fill/template_fill/_vendor/README.md`.
표가 있는 템플릿이 실제로 들어오거나, 한/글 없이 산출물 개봉 여부를 판정해야 할 필요가
다시 생기면 그 브랜치에서 세 파일(`_vendor/`, `overflow.py`, `hwpx_verify.py`)만 가져와
`document.py`에 다시 연결하면 된다.

Windows 콘솔에서는 `PYTHONIOENCODING=utf-8` 을 준다 (cp949 가 `—` 에서 죽는다).

**`onprem/codeserving/SFR-006_template_fill` 을 고치면 위 4개를 돌린다.** 앞의 둘은 특성화 점검이라
"동작이 바뀌지 않았다" 를 보증한다 — main.py·run_chat.py 분리를 이 그물 위에서 했다.

**위 unittest 는 `SFR-006/`·`SFR-018/` 사본을 검증한다. `onprem/` 은 규칙상 `tests/` 를
두지 않아 자동 회귀 테스트가 없다** — 슬롯 모드처럼 `onprem/` 에만 있는 기능은
합성 hwpx 픽스처 스모크로 확인했고(누름틀 0개 템플릿 채움·서식·표기제거·라운드트립,
누름틀 폴백, eval 라운드트립/무결성), 정식 테스트는 아직 없다. 기능을 고칠 때
이 공백을 전제하고 움직일 것.

**대신 `onprem/test/` 에 점검 4개(90건)를 커밋해 뒀다** (위 "검증 명령"). 정식 유닛테스트가
아닌 이유는 사본에 슬롯 파서가 없어서일 뿐이고, 파서를 이식하면 `tests/` 로 옮긴다.

스모크를 쓸 때는 **픽스처를 위험하게 만들 것** — `check_body_blocks` 첫 판은 안전한
모양이라 안전장치를 꺼도 통과했다. 실제 템플릿처럼 secPr 과 슬롯을 한 문단에 두고 표 run 을
텍스트 run 앞에 둬야 잡힌다. 그리고 **가짜 Redis 는 import 보다 먼저 꽂을 것** —
`session_store`·`template_index` 가 `from .redis_client import resolve_client` 로 이름을
복사하므로, 나중에 갈아 끼우면 원본이 계속 쓰여 점검이 통째로 무의미해진다.

## onprem 전수 점검 (2026-08-11)

네 배포 단위 + eval 을 훑어 **기동·배포를 막는 결함 넷**을 고쳤다. 상세는
`onprem/test/README.md` "상태" 절.

1. **`SFR-018_faq` 에 `requirements.txt` 가 없었다.** 2026-08-07 에 배포 단위로 들어왔는데
   의존성 파일 없이 왔고 `check_deploy_contract.py` 의 단위 목록에도 빠져 있었다 —
   빌드 커맨드(`pip install -r`)가 그 자리에서 실패한다. 파일을 만들고 단위로 등록했다.
2. **번역 단위가 `python-multipart`·`lxml` 을 선언하지 않고 있었다.** 둘 다 **기동 자체를
   막는다** — 전자는 `File(...)`/`Form(...)` 라우트를 등록하는 순간 FastAPI 가 RuntimeError
   를 내고(실측 확인), 후자는 `office/hwpx_text.py` 가 모듈 최상단에서 import 한다.
   `jinja2` 는 006·번역·FAQ 셋 다 빠져 있었다(지연 import 라 기동은 되고 첫 요청에서 죽는다).
3. **루트 경로 `@app.get("")` 가 세 단위 전부 404 였다** (위 "실제 운영 코드 대조" 절).
4. **개봉 안전 게이트가 항상 돌게 되면서 `/generate` 가 막히고 있었다** — 점검 픽스처가
   온전한 OPC 패키지가 아니었다. `onprem/test/hwpx_package.py` 로 통일했다.

**`check_deploy_contract.py` 가 FAIL 0 이 됐다.** 그전까지 영구히 빨간색이었고, 그 빨간색에
1번이 묻혀 있었다. FAIL(기동 불가)과 WARN(이미지 제공 / 코드가 `try/except ImportError` 로
방어)을 나눴다 — 후자는 이름 하드코딩이 아니라 **AST 로 방어 여부를 보고** 판정한다.

확인만 하고 **고치지 않은 것** (2026-08-18 재확인 — 셋 중 둘은 그 뒤 고쳐졌다):
- ~~`@app.on_event("startup")` 은 deprecated 다(세 단위 사용). 지금은 돌지만 FastAPI 가
  제거하면 import 단계에서 죽는다 — requirements 에 상한이 없어 시점을 통제할 수 없다.~~
  **고쳤다 (2026-08-11).** `on_event` 는 이제 어디에도 없다. 기동 훅이 있는 두 단위
  (번역·FAQ)가 `lifespan` 을 쓰고, 006·글다듬이는 기동 훅이 아예 없다.
  훅이 **조용히 안 도는** 상태를 `check_service_boot.py` 가 판정한다 — `TestClient` 를
  컨텍스트로 진입해 실제로 돌려 본다.
- ~~업로드 세 경로 모두 `await document.read()` 로 **전량을 읽은 뒤** 크기를 검사한다.
  `UploadFile` 이 디스크로 spool 하므로 OOM 은 아니지만 상한 밖 디스크를 쓴다.~~
  **고쳤다 (2026-08-11).** 세 경로(006 `api_requests`, 번역·FAQ `api_contract`) 모두
  상한을 넘기면 **읽기를 멈추고** `None` 을 돌린다. 상한이 거부 조건이 아니라 자원
  한도로 작동한다.
- 번역 `TranslateRequest.register` 가 `BaseModel.register` 를 가린다는 pydantic 경고 —
  값은 정상 왕복하고 `resolve_register` 까지 도달한다(실측). 경고일 뿐이다.
  **2026-08-18 기준 그대로 열려 있다.**

### 미사용 함수 전수 점검 (2026-08-11) — 운영 코드에 죽은 함수는 없다

함수 **703개 / 파일 115개**를 두 가지 방식으로 걸렀고, **운영 코드 미사용은 0건**이다.
후보는 두 번 다 나왔지만 전부 오탐이었다 — 그 오탐의 정체를 적어 두는 것이 이 절의 목적이다.
같은 점검을 다시 할 사람이 같은 자리에서 또 헛걸음하지 않게.

1. **참조 0건 검색** → 후보 21개. 전부 정상이다:
   - **FastAPI 라우트 핸들러 11개** (006 `register_template`·`delete_template`·
     `patch_values`·`delete_values`·`put_blocks`·`generate_upload`, FAQ `service_config`·
     `generate_upload`·`get_faqs`, 번역 `glossary_status`·`translate_hwpx`).
     데코레이터로 등록되므로 **이름으로 부르는 코드가 없는 것이 정상**이다.
   - 던더(`__str__`·`__bool__`)와 `_vendor`.
2. **엔트리포인트 도달 가능성(호출 그래프)** → 운영 코드 후보 6개. **전부 별칭
   import(`as`)** 라 이름 기반 그래프가 연결을 놓친 것이었다. 여섯 건 다 호출 지점까지 열어
   확인했다:

   | 후보 | 실제 사용처 |
   |---|---|
   | `api_errors.install` | `main.py:50` `as install_error_handler` → `:72` |
   | `hwpx_verify.enforce` | `document.py:54` `as enforce_open_safety` → `:135` |
   | `text_polish.prompt_loader.render` | `main.py:31` `as render_prompt` → `:72` |
   | `languages.supported_payload` | 번역 `main.py:45` `as supported_languages` |
   | `registers.supported_payload` | 번역 `main.py:51` `as supported_registers` |

   FAQ(90개)·eval(92개)은 두 방식 모두 후보 0건이었다.

**`_vendor/` 안 15개는 실제로 안 쓰인다. 그대로 둔다.** `tag_local_name`·`tag_in_family`·
`element_qn_like`·`register_owpml_namespaces`·`SlotMetrics.height_lines*`·`_children_by_local`
등이다. 상류(python-hwpx) 사본이라 미사용이 정상이고, **지우면 재동기화 절차가 어긋난다**
(`template_fill/_vendor/README.md`). 벤더 사본을 줄이는 기준은 미사용 여부가 아니라
`check_vendor_closure.py` 가 재는 **절연**이다.

> 위 두 절(참조 0건 검색의 `hwpx_verify.enforce` 행, `_vendor/` 미사용 15개)은 2026-08-11
> 시점 기록이다. `_vendor/`·`overflow.py`·`hwpx_verify.py`·`check_vendor_closure.py` 는
> 2026-08-12 에 전부 지웠다 — "python-hwpx 벤더 사본" 절 참고. 지금 저장소에는 존재하지
> 않는 코드를 가리키므로, 이 감사 기록은 **당시 상태의 역사적 기록**으로만 읽을 것.

**한계 — 이 점검이 보증하지 않는 것**: 호출 그래프가 이름 단위 매칭이라 **살아 있는 함수와
이름이 겹치는 죽은 함수는 숨을 수 있다**(`render`·`available` 처럼 흔한 이름). 즉 "죽었다고
나온 것은 확실히 죽었다"는 보증만 있고 그 역은 없다. 그 구멍까지 막으려면 import 심볼
테이블로 참조를 해석해야 하는데 **돌리지 않았다.** 점검 스크립트도 세션 임시 디렉토리에
있어 저장소에 남지 않는다 — 다시 필요하면 새로 짜야 한다.
