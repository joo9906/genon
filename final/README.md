# `final/` — MCP · 워크플로우 · 전처리기와 006 코드서빙

**018 세 코드서빙(글다듬이·번역·FAQ)의 현행은 `no_pythonstep/` 이다** — 젠포탈이 `POST /chat` 을
직접 부르고 코드서빙이 SSE 를 직접 낸다. 이 폴더의 `SFR-018-*/request/` 는 그물(`Test/`)이 보지
않는 옛 판이고, 018 고칠 곳은 `no_pythonstep/<기능>/` 이다.

| 무엇 | 현행 코드 |
|---|---|
| 글다듬이 · 번역 · FAQ 코드서빙 | `no_pythonstep/SFR-018-*/` |
| 템플릿 채우기(006) 코드서빙 | `final/SFR-006/request/` (직접 호출 판 `no_pythonstep/SFR-006/` 이 함께 있다 — 고치면 두 벌 다) |
| MCP · 워크플로우 · 전처리기 | `final/mcp/` · `final/workflow/` · `final/preprocessor/` |

어느 코드를 현행으로 볼지는 `Test/check/paths.py` 의 `SOURCE` 표가 정본이다.

---

# 프론트와 주고받는 값

**정본은 `docs/FRONT.md`** 다 — 요청 머리말 키, 결과 값, 안내 문구, 미확정 항목까지 거기 있다.

| 기능 | 부르는 길 | 결과 값 |
|---|---|---|
| 글다듬이 | `POST /chat` `{question, stream}` → SSE | `complete`: `original_text`·`polished_text`·`download_url`·`doc_type`·`tone`·`tone_overridden` |
| 번역 | 〃 | `complete`: `original_text`·`translated_text`(둘 다 `<mark>`)·`download_url` |
| FAQ | 〃 | `complete`: `faq_items`·`download_url`(+`disclaimer`) |
| 템플릿 채우기 | 캔버스 워크플로우 (소켓 `token`·`result`) | `result.data`: `text`·`download_url`·`session_id`·`template_id` |

- 018 은 화면에서 고른 값을 **`question` 맨 앞 `키: 값` 줄**로 붙이고, 첨부는 `[입력된 문서]` 뒤에 온다.
- 채팅에 보일 글은 전부 `token` 으로 나가고 `complete` 에는 `text` 가 없다. 오류도 200 SSE 다.
- 공통으로 `notice`(있을 때만)·`error`(오류일 때만)가 올 수 있다. `download_url` 은 `null` 일 수 있다.
- 선택지 목록(언어·톤·문서유형·템플릿)은 코드서빙 REST 로 그린다 — 화면이 목록을 들지 않는다.

---

# 배치

```
final/<기능>/
  request/   ← 정본. 게이트웨이를 `httpx` 로 직접 부른다. **그대로 등록할 수 있다**
  open_ai/   ← `openai` SDK 판에서 갈리는 파일만 (3개)
  prompt/<배포단위이름>/
             ← 그 기능의 프롬프트. **배포 단위 밖**이다 (이미지에 함께 넣는다)
               ⚠ **하위 디렉토리 이름이 계약이다.** 로더가 배포 단위에서 상위로
               올라가며 `prompt/<배포단위이름>` 을 찾는다 — 파일을 `prompt/` 바로
               밑에 두면 **기동과 `/health` 는 통과하고 첫 요청에서 500** 이 난다

final/workflow/   ← 캔버스 파이썬 스텝 9개. 018 `/chat` 경로에서는 006 스텝 3개만 쓴다
final/mcp/        ← MCP 도구 파일 6개. **판본과 무관하게 같다**
```

| 폴더 | 배포 단위 이름 (등록 화면에서 쓰는 이름) | request | open_ai | prompt |
|---|---|---:|---:|---:|
| `SFR-006/` | `SFR-006_template_fill` — hwpx 템플릿 채우기 | 30 | 3 | 5 |
| `SFR-018-polish/` | `SFR-018_text_polish` — 글다듬이 | 13 | 3 | 1 |
| `SFR-018-translate/` | `SFR-018_translation` — 번역 | 30 | 3 | 9 |
| `SFR-018-faq/` | `SFR-018_faq` — FAQ 생성 | 21 | 3 | 3 |

---

## `final/workflow/` — 캔버스 파이썬 스텝 9개

**018 이 `/chat` 직접 호출이면 등록하는 스텝은 006 셋(`sfr006_*`)뿐이다** — 아래 다듬·FAQ·번역
스텝 여섯은 그 셋이 워크플로우로 돌 때의 것이다.

**파일 1개 = 스텝 1개이고, 내용을 통째로 캔버스에 붙여 넣는다.** 각 파일은 자기완결이다 —
로깅 유틸·오류표·게이트웨이 클라이언트가 파일마다 반복되는데 **그 중복은 의도한 것**이다.
공용 모듈로 빼면 스텝이 자기완결이 아니게 되어 캔버스에 붙일 수 없다.

| 순서 | 파일 | 시그니처 | 부르는 것 |
|---|---|---|---|
| 006-1 | `sfr006_01_context.py` | `async def run(data) -> dict` | 서빙 `POST /chat/context` → `POST /chat/prefill`(업로드 문서 자동 채움) |
| 006-2 | `sfr006_02_extract.py` | `async def run(data) -> dict` | 서빙 `POST /chat/extract` |
| 006-3 | `sfr006_03_commit.py` | async generator | 서빙 `POST /chat/commit` |
| 다듬-1 | `sfr018_polish_01_policy.py` | `async def run(data) -> dict` | MCP `lang_policy.resolve_tone` |
| 다듬-2 | `sfr018_polish_02_polish.py` | async generator | 서빙 `POST /polish/stream`(폴백 `/polish`) + MCP `text_guard` ×3 |
| FAQ-1 | `sfr018_faq_01_source.py` | `async def run(data) -> dict` | `genosUploaded` 파싱 + 서빙 `GET /config` |
| FAQ-2 | `sfr018_faq_02_generate.py` | async generator | 서빙 `POST /generate/stream`(폴백 `/generate`) |
| 번역-1 | `sfr018_translate_01_detect.py` | `async def run(data) -> dict` | `genosUploaded` 파싱 + MCP `lang_policy.validate_direction` |
| 번역-2 | `sfr018_translate_02_translate.py` | async generator | 서빙 `POST /translate/stream` → `POST /translate/finalize`(폴백 `/translate/markdown`) + MCP `text_guard.numeric_issues` |

**스텝이 읽는 환경변수는 등록 id 일곱 개뿐이다** — `TEMPLATE_FILL_SERVING_ID` ·
`TEXT_POLISH_SERVING_ID` · `TRANSLATION_SERVING_ID` · `FAQ_SERVING_ID` ·
`LANG_POLICY_MCP_ID` · `TEXT_GUARD_MCP_ID` · `OCR_MCP_ID` (+ `GENOS_URL`·`GENOS_TOKEN`).
**워크플로우 이미지에 추가할 패키지는 0개다** — 스텝이 쓰는 외부 패키지는 `httpx` 뿐이다.

- **첨부 문서를 스텝이 파싱하지 않는다.** 전처리기 산출물(`genosUploaded`)을 그대로
  원문으로 쓴다 — 같은 문서를 두 번 파싱하지 않고, 검색용 조문 머리말이 LLM 입력에
  섞이지 않는다.
- **스트리밍은 시도하고 안 되면 되돌아간다.** 게이트웨이가 `stream=True` 를 받는지
  폐쇄망에서 확인되지 않았고, 안 받는 배포에서 기능이 통째로 죽으면 안 된다.
  SSE 가 아닌 응답이 오면 스텝이 비스트리밍 경로로 간다.

## `final/mcp/` — MCP 도구 파일 6개

**파일 1개 = 등록 1개다.** GenOS 는 소스 파일 하나를 받아 실행하고 `mcp` 객체를 런타임이
전역으로 주입한다 — **앱도 포트도 `requirements.txt` 도 우리 몫이 아니다.**
도구는 `@mcp.tool()` 로 등록하고 **JSON 문자열**을 돌려준다.

| 파일 | 도구 | 누가 부르나 |
|---|---|---|
| `genon_lang_policy.py` | `resolve_tone` · `validate_direction` · `detect_language` · `list_languages` · `list_registers` · `resolve_register` | 앞의 둘은 **스텝**(다듬-1·번역-1). 나머지는 도구를 고르는 LLM |
| `genon_text_guard.py` | `markdown_structure_issues` · `fact_issues` · `numeric_issues` · `diff_changes` | **글다듬이 서빙 `/chat`**(`markdown_structure_issues`·`fact_issues`, `TEXT_GUARD_MCP_ID`). 워크플로우 경로면 스텝 다듬-2·번역-2 |
| `genon_glossary.py` | `glossary_lookup` · `glossary_status` · `glossary_reload` | 도구를 고르는 LLM (**번역 서빙은 자기 사본을 쓴다**) |
| `genon_pii_audit.py` | `pii_audit` · `pii_scan_text` · `pii_detectors` | **사람이 직접** — 생성 문서를 모아 미마스킹 건수를 집계한다. 스케줄러는 없다 |
| `genon_ocr.py` | `ocr_scan_pages` | **스텝**(스텝 1 — 첨부에 스캔 쪽 표식이 있을 때만). 018 `/chat` 은 부르지 않는다(스캔 표식은 입력 오류) |
| `genon_template_draft.py` | `template_fill_draft` | **사람이 직접** — 템플릿 채우기 대화 도중 부분 초안을 찍어 본다(006 `POST /draft`, 세션 유지) |

**모든 최상위 심볼에 파일별 접두어**(`LP`/`TG`/`GL`/`PA`/`OC`/`TD`)가 붙어 있다 — 한 서버에 여러
도구 파일이 함께 로드될 수 있고, 겹치면 나중 것이 앞엣것을 덮는다. 그 실패는 **"도구가
이상한 값을 낸다" 로만** 드러난다. **도구 함수 이름만 예외**다(LLM 에 노출되는 계약이라
접두어를 못 붙인다).

> **MCP 호출은 Accept 헤더를 둘 다 열거해야 한다** — `application/json` 과
> `text/event-stream`. 안 그러면 서버가 본문을 읽기도 전에 `406` 으로 끊는다.
> 스텝이 이미 그렇게 보내고, 응답이 SSE 프레임으로 와도 읽는다.

---

# 어떻게 올리나

## 코드 서빙 네 단위

018 셋은 **`no_pythonstep/<기능>/` 폴더를 그대로 올린다**(루트에 `main.py`, 시작 커맨드
`uvicorn main:app --host 0.0.0.0 --port $PORT`). 등록·환경변수는 `no_pythonstep/README.md` 단위별 절.
아래는 006(`final/SFR-006/`)과 `final/` 판 018 의 방식이다.

### `httpx` 판 (정본이다)

`request/` 를 그대로 올린다. **`open_ai/` 는 쓰지 않는다.**

### `openai` SDK 판

`request/` 를 복사한 뒤 그 위에 **`open_ai/` 를 덮어쓴다.**

```bash
cp -r final/SFR-018-faq/request   /tmp/faq
cp -r final/SFR-018-faq/open_ai/. /tmp/faq/     # 3개가 덮인다
```

> `openai` 판은 사내 mirror 에 `openai>=1.30` 이 있어야 `pip install -r` 이 돈다.
> **둘 중 하나만 등록한다.**

## 나머지

| 무엇 | 어떻게 |
|---|---|
| `final/mcp/*.py` | **파일마다 따로** MCP 서빙으로 등록한다 |
| `final/workflow/sfr006_*.py` | 캔버스 파이썬 스텝에 **내용을 통째로 붙여 넣는다** (018 이 `/chat` 이면 006 셋만) |
| `final/<기능>/prompt/` | 배포 단위 **밖**이다 — 이미지에 함께 넣거나 프롬프트 라이브러리에 올린다 |

**등록 절차·순서·환경변수의 정본은 `docs/ONPREM.md`** · `docs/SERVING_REGISTRY.md` 다.

---

# 두 판본은 무엇이 다른가 — **전송 계층 하나뿐이다**

**기능 차이는 0 이다.** 네 단위가 각각 세 파일에서만 갈린다:

| 파일 | 무엇이 다른가 |
|---|---|
| `<pkg>/llm.py` | `POST {base}/chat/completions` 를 `httpx` 로 직접 부르나(`request`), `AsyncOpenAI` 로 부르나(`open_ai`) |
| `<pkg>/config.py` | `open_ai` 판에만 `llm_model_id()` 가 있다 — **SDK 는 `model` 없이 요청을 만들지 못한다.** 기본값 `"default"`, `LLM_MODEL_ID` 로 덮는다 |
| `requirements.txt` | `open_ai` 판에만 `openai>=1.30` 이 적혀 있다 |

**워크플로우 스텝과 MCP 파일은 판본이 없다** — 게이트웨이의 LLM 경로를 직접 부르지 않아
전송 계층이 갈릴 자리가 없다. `no_pythonstep/` 018 셋은 `httpx` 판 하나뿐이다.

### 판본과 무관하게 네 단위가 다 갖는 것

```
POST /polish/stream        (SSE)  다듬어지는 대로 흘린다
POST /translate/stream     (SSE)  번역문이 문서 순서대로 흐른다
POST /translate/finalize   (JSON) 하이라이트 재료 + 내려받기 링크
POST /generate/stream      (SSE)  FAQ 를 항목마다 흘린다
```

모두 **비스트리밍 경로가 폴백으로 남는다.** 되돌아간 사실은 응답의 `stream_fallback`
과 로그가 말한다.

---

# 단위를 띄워 보기

`final/<기능>/request/` 를 루트로 삼아 단위 하나를 **실제로 띄워** 기동 · `/health` · 프롬프트 렌더 ·
스트리밍 · 용어사전 폴백 · 업로드 fail-open 을 본다 (LLM·Redis·MinIO 없이 — 게이트웨이 호출만 대역).

```bash
export PYTHONIOENCODING=utf-8 SSL_CERT_FILE=
python final/verify_final.py SFR-006
```

> **프롬프트는 `prompt/<배포단위이름>/` 아래에 있어야 한다.** `prompt/` 바로 밑에 두면 기동과
> `/health` 는 통과하고 **첫 요청에서 500**(`PromptRenderError`)이다 — 등록하고 눌러 보기 전까지
> 안 드러난다. `check_prompt_render` 가 이 배치를 본다.

018 `/chat` 직접 호출 경로는 `python Test/check/check_chat_direct.py` 가 같은 방식(대역)으로 본다.

---

# 여기 없는 것

| 무엇 | 어디 | 왜 |
|---|---|---|
| 018 현행 코드서빙 | `no_pythonstep/` | 젠포탈 `/chat` 직접 호출 판. 이 폴더 바깥이다 |
| 평가지표 MCP | `Test/eval/` | 등록 단위가 아니다. 네 기능 채점용 |
| 배포 계약 점검 | `Test/check/` | 등록 단위가 아니다 |

---

# 용어사전 — **구현돼 있고, 안 붙이면 참고하지 않는다**

번역 단위에 **전부 들어 있다.** 끄기 위해 코드를 덜어낸 자리가 없다.

| 파일 | 하는 일 |
|---|---|
| `common/glossary_store.py` | GenOS AI 드라이브 용어사전 API 적재 |
| `common/glossary_exact.py` | 정확 매칭 — **한국어 조사 폴백**(`가맹점을` → `가맹점`) 포함 |
| `office/glossary_report.py` | 원문·번역문 **양쪽** `<mark>` 하이라이트 + 준수율 |
| `common/prompt_builder.py` | 이 조각에 나온 용어만 프롬프트 용어 절에 싣는다 |

**연결하지 않으면 폴백 하나로 통째로 꺼진다.** `TRANSLATE_GLOSSARY_API_URL` ·
`TRANSLATE_GLOSSARY_DRIVE_ID` · `TRANSLATE_GLOSSARY_WORKSPACE_ID` **중 하나라도 비면**
`glossary_store` 가 적재를 건너뛰고(`not_configured`), 그 뒤가 **전부 따라 꺼진다**:

```
기동 로그: 용어사전 설정 미완료 — 용어사전 없이 번역한다
  → 프롬프트에 용어 절이 없다        (LLM 이 없는 사전을 따르려 들지 않는다)
  → 준수율 판정을 하지 않는다
  → 번역문·원문 어디에도 <mark> 가 없다
  → notice 의 "용어 N개 미반영" 안내가 나가지 않는다
```

**코드는 안 고친다.** 지금 상태는 `GET /glossary` 가 답한다.
용어사전을 붙이면 위 넷이 **같이** 켜진다 — 반쪽만 켜지는 상태가 없다.

> ⚠ 지금은 **"안 쓰기로 했다" 와 "설정을 빠뜨렸다" 가 둘 다 `not_configured`** 로
> 나간다. 둘을 가르려면 `TRANSLATE_GLOSSARY_ENABLED` 같은 명시적 스위치를 두고
> 사유를 `disabled_by_config` 로 갈라야 한다 — **아직 안 만들었다** (2026-09-14 판단:
> 운영이 환경변수로 끄면 충분하다).

---

# 내려받기 링크 — **MinIO 업로드가 네 단위에 다 들어 있다**

결과를 만든 자리에서 서빙이 파일을 굳혀 올리고 **`download_url` 만** 싣는다.
화면이 본문을 되돌려 보내 파일을 만드는 방식이 아니다.

| | 파일 | 무엇을 올리나 |
|---|---|---|
| 글다듬이 · 번역 · FAQ | `no_pythonstep/<기능>/<pkg>/file_store.py` | 결과 **md** (마크다운 그대로 · BOM·CRLF) |
| 템플릿 채우기 | `template_fill/file_store.py` | 다 채웠을 때 굳힌 **hwpx** |

**사본 4벌이고 코드가 같아야 한다**(`check_api_contract` 가 AST 로 대조한다). 모양은
GenOS 참조 샘플(MinIO 업로드)과 넷을 맞춰 뒀다 — 업로드 URL · 멀티파트 필드
(`hostname` + `file`) · 응답 경로(`data.presigned_url`).

- **`httpx` 로 올린다** — 참조 샘플의 동기 `urllib` 을 그대로 옮기면 async 라우트의
  이벤트 루프가 업로드 내내 멈춘다.
- **fail-open 이다.** 업로드가 실패하면 `download_url` 만 비우고 결과는 그대로 낸다
  (`event=file_upload_failed status=degraded`). 잘 만들어진 번역·FAQ 가 파일 하나
  때문에 통째로 사라지면 안 된다. **화면은 `null` 을 "파일로 받을 수 없다" 로 그린다.**
- **예외 원문을 응답에 담지 않는다** — 내부 URL 이 실린다(3.8절).
- 폐쇄망에서 실제로 열리는지는 **아직 미검증**이라 옛 경로를 폴백으로 남겼다
  (018 셋 `POST /download` · 006 `POST /generate`).

---

# 자주 묻는 것

**`open_ai/` 만 올리면?** 안 된다 — 3개짜리 조각이다. `request/` 위에 덮는 것이
쓰는 방법이다.

**018 을 고칠 때 `final/SFR-018-*/request/` 도 고치나?** 아니다. 현행은 `no_pythonstep/` 이고
그물도 그쪽만 본다. 006 은 `final/SFR-006/request/` 와 `no_pythonstep/SFR-006/` **두 벌을 함께** 고친다.
