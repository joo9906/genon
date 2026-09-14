# `final/` — 등록하는 것 전부, 기능별로 갈라 놓은 배치

**여기 있는 파일은 손으로 고치지 않는다.** `python make_final.py` 가 `onprem/` 과
`not/` 에서 만들어 내는 **파생물**이다. 여기서 고치면 저장소의 어느 판본과도 다른
코드를 등록하게 되고, 그 어긋남은 오류로 드러나지 않는다.

기능을 고칠 때는 **`onprem/`** 을 고치고(전송 계층이면 `not/` 도) 스크립트를 다시 돈다.

---

# 프론트와 주고받는 값

> **정본은 `onprem/docs/FRONT.md`** 다 — 선택지 목록(언어·톤·문서유형·템플릿),
> 직접 편집 경로, 미확정 항목까지 거기에 있다. 아래는 **화면을 그리는 데 필요한
> 최소한**이다.

## 통신은 두 갈래다

| 갈래 | 무엇 | 언제 |
|---|---|---|
| **캔버스 워크플로우** (소켓) | 실제 실행 — 다듬기·번역·FAQ·대화 | 사용자가 실행 버튼을 누를 때 |
| **코드서빙 REST** (HTTP) | 선택지 목록·템플릿 목록·미리보기·다운로드 폴백 | 화면을 그릴 때 |

**드롭다운 선택지를 화면이 들고 있으면 안 된다.** 언어·톤·문서유형은 백엔드가 표를
갖고 있고 관리자가 늘릴 수도 있다 — 화면이 자기 목록을 들면 한쪽만 고쳐도 예외 없이
**빈 드롭다운이나 "지원하지 않는 값"** 으로만 드러난다.

## 소켓 이벤트는 `token` 과 `result` 둘뿐이다

```
token → token → token → … → result      (정상)
                             result      (오류 — 018 셋은 토큰이 하나도 안 나간다)
```

| 이벤트 | data | 설명 |
|---|---|---|
| `token` | 문자열 조각 | **정본**(마크다운 원문)이 흐른다. `<mark>` 태그는 **없다** |
| `result` | 아래 payload | **한 번만** 온다. 이 시점에 화면을 완성한다 |

- **스트리밍 중에는 원시 마크다운·HTML 표가 그대로 보인다** — 허용된 동작이다.
  `result` 가 오면 그 자리를 하이라이트 두 벌로 **갈아 끼운다.**
- **조각 크기를 가정하지 말 것.** 다듬기·번역은 LLM 이 내놓는 대로, FAQ 는 항목이
  검증을 지날 때마다 흐른다. **006 과 스트리밍이 안 되는 배포의 폴백 경로**만 완성된
  글을 잘라 흘리고, 그때는 총 emit 수 상한(400)이 긴 문서에서 조각을 키운다.
- **오류일 때 018 셋은 토큰을 하나도 보내지 않는다.** 006 은 오류 문구를 흘린다
  (채팅이 곧 화면이라 그렇다).

## 보내는 값 (캔버스 변수)

`overrideConfig.vars` 에 넣는다. **최상위 `question`**(또는 `text`)은 사용자 발화다.

| 기능 | 키 | 필수 | 값 |
|---|---|---|---|
| **글다듬이** | `polish_doc_type` | 선택 | `GET /policies` 의 `doc_types[].code`. 없으면 `email` |
| | `polish_tone` | 선택 | `tones[].code`. 정책상 불가하면 대체된다 |
| | `genosUploaded` | 조건부 | 업로드 문서(전처리기 산출물). **있으면 발화보다 우선** |
| | `question` | 조건부 | 붙여 넣은 원문. 업로드도 발화도 없으면 `INPUT_EMPTY` |
| **번역** | `translate_target_lang` | **✅** | `GET /languages` 의 `languages[].code` |
| | `translate_source_lang` | 선택 | **비워도 된다** — 백엔드가 감지한다 |
| | `translate_register` | 선택 | `registers[].code` (문어체/구어체) |
| | `genosUploaded` | 조건부 | 업로드 문서 |
| | `translate_hwpx_path` | 선택 | hwpx 원본 경로. 있으면 **표 보존이 더 좋다** |
| | `question` | 조건부 | 붙여 넣은 원문 |
| **FAQ** | `genosUploaded` | **✅** | 전처리기 산출물 |
| | `faq_count` | 선택 | 만들 **총 개수**. 상한은 `GET /config` 의 `max_count` |
| | `faq_title` | 선택 | 내려받는 파일 이름 |
| **템플릿 채우기** | `template_fill_template_id` | **✅** | `GET /templates` 의 `template_id` |
| | `question` | **✅** | 사용자 발화. **2만 자에서 잘린다** |
| | `genosUploaded` | 선택 | **빈 항목을 이 문서로 자동으로 채운다** |

- **번역의 원문 언어는 비워 두는 편이 안전하다.** 값을 보내면 그것을 **정본**으로
  삼고 감지 결과와 대조해, "한국어가 아닌 쌍"(선언은 `ko→ru` 인데 실제로는 영어 문서
  → `en→ru`)이면 **거부한다.** 원문 드롭다운을 두면 사용자가 잘못 고를 수 있다.
- **006 은 문서를 `question` 에 넣지 말 것.** 발화는 2만 자에서 잘리고, 발화 자리의
  문서는 "지워 달라"·"본문에 추가해 달라" 같은 **지시로 해석될 수 있다.**
- **006 은 같은 문서를 매 턴 계속 실어 보내도 된다.** 서빙이 문서 표식으로 걸러
  **두 번 태우지 않는다** — 프론트가 "이 턴에 새 파일이 올라왔는지" 를 판단할 필요가 없다.
  이미 넣은 값은 **절대 덮지 않고** 남은 빈 항목만 채운다.

## 받는 값 — `result.data` 가 전부다

**렌더링되지 않는 값은 싣지 않는다.** 내부 판정·검증·지표(준수율·폴백률·기각 건수)는
로그가 갖는다 — **여기 없는 키는 오지 않는다.**

| 기능 | `result.data` |
|---|---|
| **글다듬이** | `original_text`(+`<mark>`) · `polished_text`(+`<mark>`) · `download_url` |
| **번역** | `original_text`(+`<mark>`) · `translated_text`(+`<mark>`) · `download_url` |
| **FAQ** | `faq_items[]` = `{question, answer, evidence}` · `download_url` |
| **템플릿 채우기** | `text`(채팅 답변 + **아래에 미리보기**) · `download_url` · `session_id` · `template_id` |

```json
// 글다듬이 · 번역 — 좌우 비교 두 값 + 링크
{ "original_text": "…<mark>개발함</mark>…",
  "polished_text":  "…<mark>개발하였습니다</mark>…",
  "download_url":   "https://…/글다듬이결과.txt" }

// FAQ — 문답 묶음 + 링크
{ "faq_items": [{ "question": "…", "answer": "…", "evidence": "…" }],
  "download_url": "https://…/FAQ.txt" }

// 템플릿 채우기 — 채팅이 곧 화면이다
{ "text": "제목을 『…』(으)로 채웠습니다. 남은 항목은 담당자, 배포일입니다.\n\n---\n\n**미리보기**\n\n# …",
  "download_url": null,
  "session_id": "…", "template_id": "보도자료" }
```

**함께 올 수 있는 것 셋, 그리고 이게 전부다:**

| 키 | 언제 | 화면 |
|---|---|---|
| `genos_state` | 플랫폼이 넣을 때 | GenOS 추적값. **읽지 않는다** — 그대로 두면 된다 |
| `notice` | **있을 때만** (018 셋) | 문자열 배열. **그대로 보여준다** |
| `error` | **오류일 때만** | 아래. 정상 응답에 `error: null` 은 오지 않는다 |

> 늘 실리는 빈 배열·`null` 을 두지 않는 이유는 하나다 — 읽는 쪽이 **"확인했다" 고
> 믿게 만든다.** 006 은 `notice` 가 아예 없다(안내가 `text` 문장에 들어 있다).

### 오류 객체

```json
{ "error": { "error_code": "ERR-02-00020001", "msg": "…잠시 후 다시 시도해 주세요.", "retryable": true } }
```

- **`msg` 를 그대로 보여주면 된다.** 고정 한국어 안내문이고 내부 정보(URL·예외 원문)가
  들어가지 않는다. 화면이 문구를 새로 만들지 말 것 — 같은 문장이 두 곳에 살게 된다.
- **`retryable: false` 면 다시 눌러도 같은 자리에서 실패한다**(배포·설정 문제).
  재시도 버튼을 권하지 말고 "관리자 문의" 로 안내한다.
- `error_code` 는 `ERR-영역-코드` 꼴이다(`02` 워크플로우 / `03` 코드서빙). 문의 접수
  때 이 값이 있어야 로그를 찾을 수 있다.

### 하이라이트 — `<mark>` 가 본문에 섞여 온다

**원문과 결과를 좌우로 놓고 비교**하는 화면이 전제다. 양쪽에 이미 입혀져 있다.

| 기능 | 왼쪽(`original_text`) | 오른쪽 |
|---|---|---|
| 글다듬이 | **지워진** 낱말 | `polished_text` — **새로 들어온** 낱말 |
| 번역 | 사전 용어가 **원문에서** 쓰인 자리 | `translated_text` — 그 용어가 **번역문에서** 쓰인 자리 |

- **번역에서 왼쪽만 형광이고 오른쪽 짝이 없으면 "사전 용어인데 번역이 그 말을 안 썼다"** 다.
  그 건수는 `notice` 로도 온다.
- 칠하는 구간은 문서에 **실제로 적힌 글자**다 — 한국어는 조사까지 덮인다
  (`<mark>신용회복위원회를</mark>`). 코드펜스 안과 HTML 태그 가운데는 칠하지 않는다.

> ⚠ **화면이 raw HTML 을 렌더해야 형광이 보인다.** 막혀 있으면 `<mark>` 가 글자 그대로
> 노출된다 — **이 허용 여부는 아직 확인되지 않았다.** 못 쓰면 백엔드 상수 두 곳만
> 고쳐 다른 표기로 바꿀 수 있으니 알려줄 것.

### 내려받기 — **네 기능이 모두 `download_url`** 이다

| 기능 | 무엇이 올라가나 | 링크가 `null` 이면 |
|---|---|---|
| 글다듬이 · 번역 · FAQ | 결과 **txt** | `POST /download` (화면이 텍스트를 되돌려 보낸다) |
| 템플릿 채우기 | 항목을 **다 채웠을 때** 굳힌 **hwpx** | `POST /generate` (`session_id`+`template_id` 만 보낸다) |

- **`null` 일 수 있다.** 업로드 실패는 기능이 실패한 것과 다른 사건이라 결과는 그대로
  나가고 링크만 빈다 — 화면은 "파일로 받을 수 없습니다" 를 말할 수 있어야 한다.
  **006 은 아직 다 안 채웠을 때도 `null`** 이다(그 둘을 화면이 구분할 수 없다 —
  필요하면 알려 달라).
- 파일 본문은 payload 에 없다.

### `notice` 에 오는 문구 (건수만 말한다)

| 기능 | 문구 |
|---|---|
| 글다듬이 | `문서 일부 구간(N곳)을 다듬지 못해 원문 그대로 두었습니다. 다시 시도해 주세요.` |
| | `표·제목 등 문서 구조가 원문과 달라진 곳이 N곳 있습니다. 결과를 확인해 주세요.` |
| | `숫자·날짜가 원문과 다른 곳이 N곳 있습니다. 결과를 확인해 주세요.` |
| 번역 | `용어사전 용어 N개가 번역문에 반영되지 않았습니다 (원문에서 형광으로 표시된 자리입니다). 다시 번역하면 반영될 수 있습니다.` |
| | `문장 N개를 번역하지 못해 원문 그대로 두었습니다. 다시 번역해 주세요.` |
| | `원문과 번역문의 숫자·날짜가 N곳 다릅니다. 결과를 확인해 주세요.` |
| FAQ | `요청하신 N개 중 M개만 문서에서 근거를 확인했습니다.` |
| | `문서 일부 구간에서 FAQ 를 만들지 못했습니다. 다시 시도하면 더 나올 수 있습니다.` |
| | `문서가 길어 전체 N개 구간 중 M개 구간에서 나눠 만들었습니다. 나머지 구간 내용은 반영되지 않았습니다.` |
| | `문서가 매우 길어 뒷부분은 FAQ 생성에서 제외했습니다.` |

> **자동 재번역·재다듬기를 하지 않는 것이 결정이다.** 사실만 알리고 **다시 할지는
> 사용자가 정한다** — 화면에 "다시 번역" 버튼을 두는 것이 이 안내문의 전제다.
> 어느 용어·어느 문장인지는 **문서 내용이라 싣지 않는다.** 자리는 이미 형광으로 있다.

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

final/workflow/   ← 캔버스 파이썬 스텝 9개. **판본과 무관하게 같다**
final/mcp/        ← MCP 도구 파일 4개. **판본과 무관하게 같다**
```

| 폴더 | 배포 단위 이름 (등록 화면에서 쓰는 이름) | request | open_ai | prompt |
|---|---|---:|---:|---:|
| `SFR-006/` | `SFR-006_template_fill` — hwpx 템플릿 채우기 | 30 | 3 | 5 |
| `SFR-018-polish/` | `SFR-018_text_polish` — 글다듬이 | 13 | 3 | 1 |
| `SFR-018-translate/` | `SFR-018_translation` — 번역 | 30 | 3 | 9 |
| `SFR-018-faq/` | `SFR-018_faq` — FAQ 생성 | 21 | 3 | 3 |

---

## `final/workflow/` — 캔버스 파이썬 스텝 9개

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

**스텝이 읽는 환경변수는 등록 id 여섯 개뿐이다** — `TEMPLATE_FILL_SERVING_ID` ·
`TEXT_POLISH_SERVING_ID` · `TRANSLATION_SERVING_ID` · `FAQ_SERVING_ID` ·
`LANG_POLICY_MCP_ID` · `TEXT_GUARD_MCP_ID` (+ `GENOS_URL`·`GENOS_TOKEN`).
**워크플로우 이미지에 추가할 패키지는 0개다** — 스텝이 쓰는 외부 패키지는 `httpx` 뿐이다.

- **첨부 문서를 스텝이 파싱하지 않는다.** 전처리기 산출물(`genosUploaded`)을 그대로
  원문으로 쓴다 — 같은 문서를 두 번 파싱하지 않고, 검색용 조문 머리말이 LLM 입력에
  섞이지 않는다.
- **스트리밍은 시도하고 안 되면 되돌아간다.** 게이트웨이가 `stream=True` 를 받는지
  폐쇄망에서 확인되지 않았고, 안 받는 배포에서 기능이 통째로 죽으면 안 된다.
  SSE 가 아닌 응답이 오면 스텝이 비스트리밍 경로로 간다.

## `final/mcp/` — MCP 도구 파일 4개

**파일 1개 = 등록 1개다.** GenOS 는 소스 파일 하나를 받아 실행하고 `mcp` 객체를 런타임이
전역으로 주입한다 — **앱도 포트도 `requirements.txt` 도 우리 몫이 아니다.**
도구는 `@mcp.tool()` 로 등록하고 **JSON 문자열**을 돌려준다.

| 파일 | 도구 | 누가 부르나 |
|---|---|---|
| `genon_lang_policy.py` | `resolve_tone` · `validate_direction` · `detect_language` · `list_languages` · `list_registers` · `resolve_register` | 앞의 둘은 **스텝**(다듬-1·번역-1). 나머지는 도구를 고르는 LLM |
| `genon_text_guard.py` | `markdown_structure_issues` · `fact_issues` · `numeric_issues` · `diff_changes` | **스텝**(다듬-2 가 셋, 번역-2 가 `numeric_issues`) |
| `genon_glossary.py` | `glossary_lookup` · `glossary_status` · `glossary_reload` | 도구를 고르는 LLM (**번역 서빙은 자기 사본을 쓴다**) |
| `genon_pii_audit.py` | `pii_audit` · `pii_scan_text` · `pii_detectors` | **사람이 직접** — 생성 문서를 모아 미마스킹 건수를 집계한다. 스케줄러는 없다 |

**모든 최상위 심볼에 파일별 접두어**(`LP`/`TG`/`GL`/`PA`)가 붙어 있다 — 한 서버에 여러
도구 파일이 함께 로드될 수 있고, 겹치면 나중 것이 앞엣것을 덮는다. 그 실패는 **"도구가
이상한 값을 낸다" 로만** 드러난다. **도구 함수 이름만 예외**다(LLM 에 노출되는 계약이라
접두어를 못 붙인다).

> **MCP 호출은 Accept 헤더를 둘 다 열거해야 한다** — `application/json` 과
> `text/event-stream`. 안 그러면 서버가 본문을 읽기도 전에 `406` 으로 끊는다.
> 스텝이 이미 그렇게 보내고, 응답이 SSE 프레임으로 와도 읽는다.

---

# 어떻게 올리나

## 코드 서빙 네 단위

### `httpx` 판 (정본이다)

`request/` 를 그대로 올린다. **`open_ai/` 는 쓰지 않는다.**

### `openai` SDK 판

`request/` 를 복사한 뒤 그 위에 **`open_ai/` 를 덮어쓴다.**

```bash
cp -r final/SFR-018-faq/request   /tmp/faq
cp -r final/SFR-018-faq/open_ai/. /tmp/faq/     # 3개가 덮인다
```

덮어쓴 결과가 `not/SFR-018_faq/` 와 **바이트까지 같은지를 `make_final.py` 가 매번
확인한다** — 안 같으면 스크립트가 선다. 세 판정(한쪽에만 있는 파일 없음 · 갈리는
자리가 목록과 같음)이 다 맞아도 **실제로 합쳐 대조**하지 않으면 "덮어썼는데 SDK 판이
아닌 무언가가 되는" 상태를 못 잡고, 그 상태는 등록해 돌려 보기 전까지 안 드러난다.

> `openai` 판은 사내 mirror 에 `openai>=1.30` 이 있어야 `pip install -r` 이 돈다.
> **둘 중 하나만 등록한다.**

## 나머지

| 무엇 | 어떻게 |
|---|---|
| `final/mcp/*.py` | **파일마다 따로** MCP 서빙으로 등록한다 (4번) |
| `final/workflow/*.py` | 캔버스 파이썬 스텝에 **내용을 통째로 붙여 넣는다** |
| `final/<기능>/prompt/` | 배포 단위 **밖**이다 — 이미지에 함께 넣거나 프롬프트 라이브러리에 올린다 |

**등록 절차·순서·환경변수의 정본은 `onprem/ONPREM.md`** 다. 전체 등록은 **10번**이다 —
코드 서빙 4 + MCP 4 + 전처리기 2(적재용·첨부용).

---

# 두 판본은 무엇이 다른가 — **전송 계층 하나뿐이다**

**기능 차이는 0 이다.** 네 단위가 각각 세 파일에서만 갈린다:

| 파일 | 무엇이 다른가 |
|---|---|
| `<pkg>/llm.py` | `POST {base}/chat/completions` 를 `httpx` 로 직접 부르나(`request`), `AsyncOpenAI` 로 부르나(`open_ai`) |
| `<pkg>/config.py` | `open_ai` 판에만 `llm_model_id()` 가 있다 — **SDK 는 `model` 없이 요청을 만들지 못한다.** 기본값 `"default"`, `LLM_MODEL_ID` 로 덮는다 |
| `requirements.txt` | `open_ai` 판에만 `openai>=1.30` 이 적혀 있다 |

**워크플로우 스텝 9개와 MCP 파일 4개는 두 판본이 바이트까지 같다** — 그쪽은
게이트웨이의 LLM 경로를 직접 부르지 않아 전송 계층이 갈릴 자리가 없다.
`make_final.py` 가 **파일 수까지** 대조한다(하나가 빠져도 나머지는 그대로 복사되는데,
그 상태는 "그 스텝만 캔버스에 없는" 형태로만 드러난다).

**그 밖이 갈리면 기능이 한 판본에만 들어간 것이다.** `make_final.py` 와
`not/check_not_units.py`(`EXPECTED_DIFF`)가 양쪽에서 같은 목록을 지킨다 — 목록 밖이
갈리거나 한쪽에만 파일이 생기면 둘 다 선다. **둘 다 고쳐야 통과한다.**

> **2026-09-14 에 이만큼 줄었다.** 그전에는 번역 스트리밍(`POST /translate/stream` ·
> `/translate/finalize`)이 `openai` 판에만 있어 `main.py`·`api_contract.py`·
> `prompt_builder.py` + 모듈 2개 + 프롬프트 3벌이 더 갈려 있었다(`EXPECTED_DIFF` 15 +
> `EXPECTED_EXTRA` 2 + 프롬프트 3). `translate_stream_async` 를 **`httpx` SSE 로 정본에
> 옮겨 적으면서** 양쪽이 같은 기능을 갖게 됐다 — 글다듬이 `polish_stream_async` 와
> 같은 코드이고, 스트리밍 파이프라인(`stream_pipeline`·`stream_chunking`)은 전송
> 계층을 모르므로 어느 판본에서도 그대로 돈다.

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

# 이 배치가 **실제로 도는 것을 확인했다** (2026-09-14)

`make_final.py` 가 보는 것은 "`onprem/` 과 바이트까지 같은가" 뿐이다. 그런데 **배치가
다르면 같은 코드도 다르게 돈다** — 실제로 그랬다. 그래서 `final/<기능>/request/` 를
루트로 삼아 네 단위를 **띄워서** 확인했다. `onprem/` 과 같은 입력에 같은 출력이다.

| 확인한 것 | 결과 |
|---|---|
| 기동 · `/health` · `/` | 네 단위 ⭕ |
| **프롬프트를 찾아 렌더한다** | 네 단위 ⭕ (`final/` 배치 기준) |
| `POST /polish/stream` | ⭕ SSE · delta 여럿 · **흘린 것 == 정본** |
| `POST /translate/stream` → `/finalize` | ⭕ SSE · 흘린 것 == 정본 · finalize 가 하이라이트 사본·링크 자리를 낸다 |
| `POST /generate/stream` (FAQ) | ⭕ `item_open → delta×3 → item_close → done` |
| **용어사전 미연결 폴백** | ⭕ 프롬프트에 용어 절 없음 · `<mark>` 없음 · `GET /glossary` 가 사유를 말한다 |
| **용어사전 연결 시** | ⭕ 같은 프롬프트에 용어가 실린다 |
| **MinIO 업로드 경로** | ⭕ 실제로 불린다 — MinIO 가 없는 환경이라 `ConnectError` 로 **fail-open**, `download_url: null` |

**다시 돌리려면** (LLM·Redis·MinIO 없이 돈다 — 게이트웨이 호출만 대역으로 꽂는다):

```bash
export PYTHONIOENCODING=utf-8 SSL_CERT_FILE=
for f in SFR-006 SFR-018-polish SFR-018-translate SFR-018-faq; do
    python final/verify_final.py $f
done
```

> **발견하고 고친 것 하나.** 처음 배치는 프롬프트를 `final/<기능>/prompt/` 바로 밑에
> 뒀는데, 로더가 `prompt/<배포단위이름>` 을 찾으므로 **네 단위가 전부 첫 요청에서
> 500**(`PromptRenderError`)이었다. 기동과 `/health` 는 통과해서 **등록하고 눌러 보기
> 전까지 드러나지 않는** 형태다. 하위 디렉토리를 붙여 고쳤고, `make_final.py` 가
> 이제 **로더 소스에서 경로 규약을 읽어** 매번 확인한다(되돌려 4건 FAIL 확인).

---

# 여기 없는 것

| 무엇 | 어디 | 왜 안 옮겼나 |
|---|---|---|
| 전처리기 2벌 | `onprem/preprocessor/` | **파일을 옮기지 않는다** — 화면에 띄워 놓고 손으로 친다. 등록도 적재 설정 화면이라 흐름이 다르다 |
| 평가지표 MCP | `onprem/eval/` | 등록 단위가 아니다. 네 기능 채점용 |
| 배포 계약 점검 | `onprem/test/` | 등록 단위가 아니다 |

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
| 글다듬이 · 번역 · FAQ | `<pkg>/file_store.py` | 결과 **txt** (BOM·CRLF — 메모장) |
| 템플릿 채우기 | `template_fill/file_store.py` | 다 채웠을 때 굳힌 **hwpx** |

**사본 4벌이고 코드가 같아야 한다**(`check_api_contract` 가 AST 로 대조한다). 모양은
GenOS 참조 샘플(`not/minio.py`)과 넷을 맞춰 뒀다 — 업로드 URL · 멀티파트 필드
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

**`final/workflow/` 와 `onprem/workflow/` 중 어느 것을 붙이나?** 내용이 같으니 어느
쪽이든 된다. **고칠 때는 `onprem/` 을 고친다.**

**`final/` 이 `submit/` 에도 들어가나?** 아니다. `submit/` 은 `onprem/` 과 `not/` 을
저장소 배치 그대로 담는 메일 꾸러미다(`make_submit.py`) — 같은 코드를 세 번 싣지
않는다. `final/` 은 **저장소 안에서 읽기 쉬우라고** 두는 배치다.
