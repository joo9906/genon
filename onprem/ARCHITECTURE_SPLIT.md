# 영역 재배치 — 워크플로우가 몸통, 세부 기능은 MCP/코드서빙

> 2026-08-11 작성, **같은 날 실행 완료.** 기존 `onprem/SFR-*` 4개 배포 단위를
> **영역(area)별로 다시 나눈** 설계다. 아래 "이동 명세" 는 이제 **실행 기록**이다 —
> 디렉토리는 옮겨졌고 옛 워크플로우 노드(`run_chat.py` ×2, `text_polish/main.py`)는
> 삭제했다. 실행하며 드러난 결함과 남은 일은 문서 끝 "실행 결과" 절에 있다.
>
> **2026-08-13 에 area 05(`preprocessor/`)가 한 칸 더 붙었다** — 이 재배치가 만든
> 세 칸(01/02/03)과 성격이 다른 트랙이라 문서 끝 "그 뒤에 붙은 것" 절에 따로 적는다.
> 지금 상태·남은 일은 [`HANDOFF.md`](HANDOFF.md), 옮겨 적는 차례는 [`WORK.MD`](WORK.MD).

---

## 왜 바꾸는가 — 미관이 아니라 배포 차단 요인이다

지금 워크플로우 노드(`run_chat.py`, `text_polish/main.py`)는 게이트웨이로 코드서빙을 부르는
게 아니라 **같은 패키지를 로컬 import** 한다:

```
006  run_chat.py → chat_state.py → template_index.py → redis_client.py   (redis)
                                  → hwpx_fields.py                        (lxml)
FAQ  run_chat.py → hwpx_text.py (lxml) → session_store.py (redis) → prompt_loader.py (jinja2)
글다듬이 main.py → prompt_loader.py                                        (jinja2)
```

**GENOS_RULES §D.3 위반이다** — "워크플로우 단계는 임의 패키지 추가 불가, workflow image 에
포함된 것만 사용" 이고 사용 가능 목록은 `asyncio, httpx, json, datetime, re, opentelemetry,
GenOS Logger` 뿐이다. `lxml`·`redis`·`jinja2` 는 전부 **기본 이미지 변경 절차(11.5.6)** 를
운영팀에 요청해야 하는 것들이고, 그 요청은 열려 있지 않다.

재배치하면 **워크플로우 이미지에 추가되는 패키지가 0개**가 된다.

### 스트리밍은 걸림돌이 아니었다 (확인 완료)

"LLM 호출을 코드서빙으로 내리면 토큰 스트리밍이 깨진다" 고 볼 수 있지만, **지금도 실시간
토큰 스트리밍이 아니다.** 세 노드 전부 LLM 응답을 **전부 받은 뒤** `_stream_chunks(...)` 로
32자씩 잘라 emit 한다 (`run_chat.py:320`, `faq/run_chat.py:251`, `text_polish/main.py:275`).
따라서 LLM 호출 위치를 옮겨도 **UI 동작은 동일하다.** 스트리밍 규약(`emit` 뒤 `sleep(0)`,
청크 단위, `event: result` 1회)은 워크플로우 스텝에 그대로 남는다.

---

## 배치도

```
onprem/
  workflow/      area 02 — 캔버스 파이썬 스텝. 파일 1개 = 스텝 1개. 단일 파일 자기완결.
  mcp/           area 01 — MCP 도구. **파일 1개 = 등록 단위 1개.** 결정적(LLM 없는) 도구.
  codeserving/   area 03 — HTTP 배포 단위. LLM 호출·프롬프트·Redis·lxml·볼륨이 여기 산다.
```

### area 02 — `onprem/workflow/` (9개 스텝)

| 파일 | 스텝 이름 | 시그니처 | 호출 대상 |
|---|---|---|---|
| `sfr006_01_context.py` | 템플릿 컨텍스트 | `async def run(data) -> dict` | 서빙 `/chat/context` |
| `sfr006_02_extract.py` | 발화 추출·판정 | `async def run(data) -> dict` | 서빙 `/chat/extract` |
| `sfr006_03_commit.py` | 병합·미리보기·응답 | async generator | 서빙 `/chat/commit` |
| `sfr018_polish_01_policy.py` | 문서유형·톤 결정 | `async def run(data) -> dict` | MCP `lang_policy` |
| `sfr018_polish_02_polish.py` | 다듬기·검증·응답 | async generator | 서빙 `/polish` + MCP `text_guard` |
| `sfr018_faq_01_source.py` | 원본 확보·개수 결정 | `async def run(data) -> dict` | MCP `hwpx_text` + 서빙 `/config` |
| `sfr018_faq_02_generate.py` | 생성·저장·응답 | async generator | 서빙 `/generate` |
| `sfr018_translate_01_detect.py` | 원본 확보·언어 감지·방향 검증 | `async def run(data) -> dict` | MCP `hwpx_text` + MCP `lang_policy` |
| `sfr018_translate_02_translate.py` | 번역·숫자검증·응답 | async generator | 서빙 `/translate/markdown` + MCP `text_guard` |

**규율 세 가지**

1. **파일을 세부 기능별로 쪼개지 않는다.** 캔버스 파이썬 스텝은 코드 한 덩어리로 등록된다.
   로깅·오류표·게이트웨이 클라이언트가 파일마다 반복되는데, **그 중복은 의도한 것이다.**
   공용 모듈로 빼면 스텝이 자기완결이 아니게 되어 캔버스에 붙일 수 없다.
2. **중간 스텝은 generator 가 아니다.** 스트리밍이 필요한 **마지막 스텝만** async generator 로
   만들고 `event: result` 를 1회 yield 한다. 중간 스텝은 `dict` 를 돌려준다 (§D.1).
3. **오류는 `data["error"]` 로 흘린다** (§A.4). 각 스텝은 첫머리에서 앞 스텝의 `error` 를
   확인하고 있으면 **그대로 통과**시킨다. 캔버스에서 `data.error` 로 분기를 걸 수 있다.

### area 01 — `onprem/mcp/` (4개 서빙)

전부 **LLM 을 부르지 않는 결정적 도구**다. 그래서 워크플로우가 마음 놓고 직접 호출할 수 있고,
어느 워크플로우에서나 재사용된다.

| 파일 | 도구 (**합친 뒤 확정된 이름**) | 원본 (통합 대상) |
|---|---|---|
| `genon_text_guard.py` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` `evidence_check` | 글다듬이 `markdown_guard`·`fact_guard`·`diff_report`, 번역 `numeric_guard`, FAQ `evidence` |
| `genon_hwpx_text.py` | `hwpx_to_markdown` | 번역 `office/hwpx_text.py`(243줄) + FAQ `hwpx_text.py`(227줄) — **사실상 동일 사본이라 한 벌로 합친다** |
| `genon_glossary.py` | `glossary_lookup` `glossary_status` `glossary_reload` | 번역 `glossary_exact`·`glossary_store`·`glossary_report` |
| `genon_lang_policy.py` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 번역 `languages`·`registers`, 글다듬이 `tone_presets` |

**도구는 15개다** (`TG` 5 + `LP` 6 + `GL` 3 + `HX` 1). 이 문서를 쓸 당시 적었던
`glossary_compliance` 는 만들지 않았다 — 준수율 판정은 번역 코드서빙이 번역문을 들고
있어야 성립하는데 MCP 는 그 문맥이 없다. 대신 `glossary_report.py` 가 코드서빙 안에서
낸다. `GL` 셋은 **지금 어느 스텝도 부르지 않는다**(등록해 두면 다른 워크플로우에서 쓴다).

**MCP 등록 형식은 이 문서를 쓸 당시 잘못 잡았다** (2026-08-11 정정). `POST /mcp/list`·
`POST /mcp/call` 라우트를 우리가 구현하는 FastAPI 서빙으로 만들었는데, 실제 GenOS MCP 는
**소스 파일 한 개**를 받아 실행하고 `mcp` 객체를 런타임이 주입한다. 도구는 `@mcp.tool()`
로 등록하고 JSON 문자열을 돌려주며, 엔벨로프는 런타임이 씌운다 — 앱도 포트도 없다.
지금 구조와 규율은 [`mcp/README.md`](mcp/README.md).

호출 경로는 그대로다: `{GENOS_URL}/api/gateway/mcp/<id>/mcp` (JSON-RPC `tools/call`).

> **`genon_text_guard` 가 이 재배치의 최대 이득이다.** 지금 다섯 벌로 흩어진 결정적 검증이
> 한 파일로 모이고, 앞으로 만들 어떤 워크플로우에서도 쓸 수 있다.

### area 03 — `onprem/codeserving/` (4개 배포 단위)

| 단위 | 상태 | 갖는 것 |
|---|---|---|
| `SFR-006_template_fill` | 기존 + `chat_api.py` 신규 | 템플릿 볼륨, hwpx 되쓰기, Redis 세션, LLM 추출, 프롬프트 |
| `SFR-018_faq` | 기존 (`run_chat.py` 제거) | FAQ 생성 LLM, 근거검증, 내보내기, Redis 세션 |
| `SFR-018_translation` | 기존 그대로 | 번역 LLM, 스켈레톤 분해, 용어사전 적재 |
| `SFR-018_text_polish` | **신규 03 단위** | 다듬기 LLM + 프롬프트 (지금은 02 안에 있다) |

---

## 이동 명세 — **실행 완료 (2026-08-11)**

아래가 실제로 실행한 순서다. 기록으로 남긴다.

```bash
# 1) 코드서빙 — 기존 단위를 통째로 옮긴다
git mv onprem/SFR-006_template_fill  onprem/codeserving/SFR-006_template_fill
git mv onprem/SFR-018_faq            onprem/codeserving/SFR-018_faq
git mv onprem/SFR-018_translation    onprem/codeserving/SFR-018_translation

# 2) 워크플로우 노드는 코드서빙에서 제거한다 (역할이 onprem/workflow/ 로 옮겨갔다)
git rm onprem/codeserving/SFR-006_template_fill/template_fill/run_chat.py
git rm onprem/codeserving/SFR-018_faq/faq/run_chat.py

# 3) 글다듬이 — 02 단위를 03 단위로 바꾼다. LLM·프롬프트·검증 모듈만 남긴다.
git mv onprem/SFR-018_text_polish onprem/codeserving/SFR-018_text_polish
git rm onprem/codeserving/SFR-018_text_polish/text_polish/main.py   # ← 02 진입점이었다
#     남길 것: llm.py, prompt_loader.py, tone_presets.py, error_codes.py, logging_utils.py
#     MCP 로 옮길 것: markdown_guard.py, fact_guard.py, diff_report.py → onprem/mcp/genon_text_guard.py

# 4) MCP — 결정적 모듈을 각 서빙으로 복사한다 (배포 단위 간 import 금지라 사본이다)
cp onprem/codeserving/SFR-018_text_polish/text_polish/{markdown_guard,fact_guard,diff_report}.py \
   onprem/mcp/genon_text_guard.py 안
cp onprem/codeserving/SFR-018_translation/translation_pipeline/office/numeric_guard.py \
   onprem/mcp/genon_text_guard.py 안
cp onprem/codeserving/SFR-018_faq/faq/evidence.py \
   onprem/mcp/genon_text_guard.py 안
cp onprem/codeserving/SFR-018_translation/translation_pipeline/office/{hwpx_text.py,languages.py,registers.py} ...
```

> **`cp` 인 이유**: eval 이 세 배포 단위를 import 하지 않는 것과 같은 규칙이다. 배포 단위 간
> import 은 금지이고, MCP 도구 파일도 별개 등록 단위다. 사본이 갈리는지는 `onprem/test/` 의
> 대조 점검(`check_table_grid.py` 방식)으로 잡는다 — 새 사본에도 같은 점검을 붙인다.

---

## 실행 결과 (2026-08-11)

### 이동이 드러낸 결함 둘 — 둘 다 조용히 죽는 종류였다

1. **프롬프트가 네 단위에서 동시에 사라졌다.** 네 `prompt_loader.py` 가 전부
   `dirname(unit_root)/prompt/<단위>` 라는 **고정 깊이**로 디렉토리를 찾고 있었는데,
   단위가 `onprem/codeserving/` 아래로 한 겹 내려가면서 전부 빗나갔다. 증상은
   "프롬프트 생성 실패" 라는 요청 실패 하나뿐이라 디렉토리 이동이 원인이라는 것이
   드러나지 않는다. **상위로 훑어 찾는 방식으로 바꿨다** — 단위가 어느 깊이에 있든,
   이미지에서 프롬프트를 단위 옆에 두든 같은 코드로 걸린다.
2. **톤 LLM 실패 사실이 HTTP 경계에서 유실됐다.** `chat_api` 가 적용·기각 이름 목록만
   넘기고 `llm_error_type` 을 빠뜨려, 스텝 3 의 답변 조립이 `AttributeError` 로 죽었다.
   `tone_llm_error_fields`/`_blocks` 를 계약에 추가했다. 이게 없으면 톤 실패가
   **"적용 0건" 과 구분되지 않아** 문체가 그대로인 이유가 사용자에게 전달되지 않는다.

### 점검 갱신

- 경로를 하드코딩하던 스크립트 6개를 새 배치로 옮겼다.
- `check_deploy_contract.py`: 단위 목록을 **코드서빙 4 + MCP 4 + eval** 로 바꾸고,
  `check_workflow_steps()` 를 새로 넣었다. 스텝 9개가 (ㄱ) `run(data)` 단일 정의인지,
  (ㄴ) 외부 패키지가 `httpx` 뿐인지, (ㄷ) 서로 import 하지 않는지를 AST 로 본다.
  **(ㄴ)가 이 재배치의 계약 그 자체**라 그물이 없으면 슬그머니 되돌아간다.
- `check_table_grid.py`: 대조 대상이 3벌 → **4벌**(MCP 사본 추가).
- `check_tone_policy.py`: 원본이 글다듬이 → **MCP `lang_policy`** 로 바뀌었다. 판정하는
  쪽이 원본을 갖는 것이 맞다. 글다듬이 사본도 대조 대상에 넣었다 — 안 그러면 원본이
  옮겨간 뒤 다듬기 프롬프트만 옛 문구로 남는 경로가 그물 밖에 놓인다.

**8개 점검 전부 통과, 종료 코드 0.** (`check_deploy_contract` FAIL 0 / WARN 5 / OK 53,
나머지 7개는 OK 135/135.) — **이 숫자는 재배치 당일(2026-08-11) 기록이다.** 그 뒤 점검이
11개로 늘고 건수도 크게 움직였다(지금은 unittest 157건 + 점검 350건). 현재 값과 변화
사유는 [`HANDOFF.md`](HANDOFF.md) §3-1 이 정본이다.

### 실물 없이 확인한 것

- **배포 단위 8개가 전부 import 되고 앱이 구성된다** (라우트 수 확인).
- **워크플로우 스텝 9개가 실행된다.** 환경변수 없이 불러 `CONFIG_MISSING` 경로를 태웠다 —
  중간 5개는 `dict` 를 돌려주고, 마지막 4개는 token 스트리밍 후 `event: result` 를
  정확히 1회 낸다.
- **MCP 도구 호출이 실제로 동작한다.** 네 서빙에 `tools/list` 와 `tools/call` 을 넣어
  판정 결과를 받았다(표 훼손·숫자 누락·언어 감지·방향 거부 등).
- **스텝 ↔ MCP 연결이 맞다.** 글다듬이 스텝 2 의 httpx 를 가로채 실제 `genon_text_guard`
  앱으로 보냈고, JSON-RPC `result.content[].text` 를 스텝이 제대로 풀어 변경 내역·구조
  경고·숫자 경고를 조립했다. `workflow/README.md` 가 "미확인" 으로 적어 둔 **MCP 호출
  형식이 이 범위에서 확인됐다** — 다만 확인한 것은 **우리 MCP 앱과의 계약**이고,
  게이트웨이가 JSON-RPC 를 그대로 통과시키는지는 여전히 실물 확인 대상이다.

### 아직 하지 않은 것 (판단이 필요하다)

- **저장소 분리 — 2026-08-11 에 "한 저장소로 간다" 로 결정했다.** 근거는 사본 대조
  점검이 한 커밋 안에서만 성립한다는 것이고, 상세는 `README.md` "저장소 구조" 절.
  등록 수는 그 뒤 **9번**이 됐다(코드서빙 4 + MCP 4 + 전처리기 1).
- **번역 02 스텝 2개는 캔버스에 등록된 적이 없다.** 코드는 있고 실행도 되지만 신규다.
- **LLM 실호출 경로는 여전히 미검증이다.** 게이트웨이가 없어 `/polish`·`/chat/extract`·
  `/generate`·`/translate` 의 LLM 왕복을 본 적이 없다.

---

## 그 뒤에 붙은 것 — area 05 `preprocessor/` (2026-08-13)

**이 재배치와 다른 트랙이다.** 01/02/03 은 네 기능(006·글다듬이·번역·FAQ)을 영역별로
가른 것이고, 05 는 **RAG 적재 경로**다 — 네 기능 어디에도 배선돼 있지 않고, 워크플로우가
부르지도 않는다. 그래서 위 배치도에 끼워 넣지 않고 여기 따로 적는다.

```
onprem/
  preprocessor/hwpx_preprocessor.py   area 05 — 등록 단위 1파일 (파싱+청킹+VDB 레코드)
```

- **등록 형태는 MCP 와 같다** — 소스 파일 한 개를 생성·수정 화면에 올린다. 그래서 이
  파일은 **다른 파일을 import 하지 않는다**(표준 라이브러리 + `lxml`). 예전에 `hwpx.py`/
  `chunking.py`/`vector_meta.py` 로 나눠 뒀던 것을 한 파일로 합쳤다 — 셋 중 하나만 올려
  나머지가 빠진 채 배포되는 실수를 구조적으로 없앤다.
- **지능형/첨부용 전처리기와 합치지 않는다.** 그쪽은 읽기 전용 참조 사본이고, 설치
  패키지 쪽은 다른 파일 형식(pdf/docx/xlsx)이 걸려 있어 손대면 회귀 범위가 넓어진다.
  hwpx 업로드가 이 전처리기로 가도록 **관리 화면에서 매핑**하는 것이 배선의 전부다.
- **표 형식이 세 사본과 일부러 갈라져 있다.** 이 파일은 표를 **언제나 HTML** 로 내고,
  MCP·번역·FAQ 사본은 병합·중첩이 있을 때만 HTML 로 낸다. 개행이 뭉개지는 것은 **RAG
  검색 결과를 프롬프트로 조립하는 경로**에서 생기는 일이고 세 사본은 그 경로를 지나지
  않는다 — 맞추려고 어느 쪽을 따라가지 말 것.

설계 결정 다섯 개와 실물 점검 결과는 [`preprocessor/README.md`](preprocessor/README.md).

---

## 등록해야 할 환경변수 (스텝별)

워크플로우 스텝은 **리비전 정보 > 환경 변수** 에 등록한다 (§C, 11.5.4).

| 이름 | 쓰는 스텝 | 값 |
|---|---|---|
| `GENOS_URL` | 전부 | 게이트웨이 베이스. `/api/gateway` 로 끝나도 되고 아니어도 된다(코드가 흡수) |
| `GENOS_TOKEN` | 전부 | Bearer 토큰 |
| `TEMPLATE_FILL_SERVING_ID` | 006 3개 | 코드서빙 id |
| `TEXT_POLISH_SERVING_ID` | 글다듬이 02 | 코드서빙 id |
| `FAQ_SERVING_ID` | FAQ 2개 | 코드서빙 id |
| `TRANSLATION_SERVING_ID` | 번역 02 | 코드서빙 id |
| `TEXT_GUARD_MCP_ID` | 글다듬이 02, 번역 02 | MCP 등록 id |
| `HWPX_TEXT_MCP_ID` | FAQ 01, **번역 01** | MCP 등록 id |
| `LANG_POLICY_MCP_ID` | 글다듬이 01, 번역 01 | MCP 등록 id |

번역 01 이 이 표에 늦게 들어왔다 — `POST /translate/hwpx` 는 처음부터 있었는데
**워크플로우가 그 경로를 부르지 않아** hwpx 를 올리면 전처리기 산출물로 번역되고 있었다
(2026-08-14 수정). FAQ 는 이미 같은 도구를 쓰고 있었다.

시크릿 기본값은 두지 않는다. 누락 시 **값을 포함하지 않은 메시지로 즉시 실패**한다 (§C).
