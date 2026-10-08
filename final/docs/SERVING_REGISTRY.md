# 서빙 등록 목록 — 폐쇄망에서 **무엇을 등록하는가**

> 등록 화면에 넣는 값의 정본이다. 무엇이 어디서 돌고 무엇이 필요한지는 [`ONPREM.md`](ONPREM.md),
> 프론트 계약은 [`FRONT.md`](FRONT.md).

## 결론 — 무엇을 등록하나

| 영역 | 무엇을 등록하나 | 개수 | 등록 형태 |
|---|---|---|---|
| 03 | 코드서빙 — 018 셋 `no_pythonstep/<기능>/` + 006 `final/SFR-006/request/` | **4** | 코드 서빙 (컨테이너 1개 = URL 1개) |
| 01 | `final/mcp/` 의 **소스 파일** — 기능이 부르는 것 **2** (`text_guard`·`ocr`) + 선택 | **2 + 선택** | MCP 도구 (파일 1개 = 등록 단위) |
| 05 | `final/preprocessor/` 의 **소스 파일** | 적재용 1 · 첨부용 1 | 전처리기 (§2-1) |
| 02 | `final/workflow/sfr006_*.py` 스텝 **3개** | — | 캔버스 파이썬 스텝에 붙여 넣는다 (서버가 뜨지 않는다) |

**018 세 기능(글다듬이·번역·FAQ)은 젠포탈이 코드서빙 `POST /chat` 을 직접 부른다** — 워크플로우
스텝이 없다. 젠포탈의 "워크플로우로 사용" 연계를 쓰면 기본 경로가 `POST /chat` 이다(개발가이드 §6.5).
**006 은 캔버스 워크플로우**(스텝 3개 → 코드서빙)다.

**코드 서빙 하나 = 컨테이너 하나 = URL 하나**이고 리비전·환경변수·복제본이 전부 서빙
단위로 붙는다. 저장소를 어떻게 두든 이 숫자는 줄지 않는다.

**리소스 하나가 선택적으로 붙는다** — 고객사 관리자가 톤·문서유형을 직접 관리하려면
프롬프트 라이브러리에 **톤·문서유형 프롬프트**를 만든다(§2-2). 안 만들어도 이미지에 든 `.md`
와 내장 표로 정상 동작한다.

---

## 저장소 최상위 — 서빙 대상 판정

등록 대상이 아닌 것을 먼저 확실히 해 둔다. **"코드니까 올려야 하나" 를 매번 다시
따지지 않기 위한 표다.**

| 디렉토리 | 서빙? | 어떻게 다루나 |
|---|---|---|
| `no_pythonstep/SFR-018-*/` | ✅ **3개** | 코드 서빙 (§1). 폴더 하나를 그대로 올린다 — `prompt/` 가 그 안에 있다 |
| `final/SFR-006/request/` | ✅ **1개** | 코드 서빙 (§1). 프롬프트는 한 단계 위 `final/SFR-006/prompt/` — **이미지에 함께** (§4) |
| `final/mcp/` | ✅ 파일 단위 | MCP 도구 파일로 등록 (§2) |
| `final/workflow/sfr006_*.py` | ❌ | **캔버스 Python 스텝에 파일을 통째로 붙여 넣는다.** 018 스텝 여섯은 `/chat` 경로에서 쓰지 않는다 |
| `final/preprocessor/` | ✅ 파일 단위 | **전처리기로 등록한다** (§2-1). 코드 서빙이 아니라 URL 도 `/health` 도 없다 |
| `final/SFR-018-*/` | ❌ | 018 의 워크플로우 경로 판. 현행은 `no_pythonstep/` |
| `no_pythonstep/SFR-006/` | ❌ (대기) | 006 `/chat` 직접 호출 판. 세션 id 확인 뒤 #1 을 이것으로 바꾼다 (FRONT §6) |
| `Test/` | ❌ | 점검·unittest·평가지표(`Test/eval/` — 채점이 필요할 때 **stdio MCP** 로 따로 띄운다) |
| `archive/`, `docs/`, `*.md` | ❌ | 참조·문서 |

---

## §1. 코드 서빙 4개 (area 03)

네 칸 모두 리비전 상세 > **환경 설정** 에 넣는다. `LANGUAGE` 는 `python`,
빌드·시작 커맨드는 **네 단위 모두 같다** — 단위 루트에 `main.py` 가 있어 가이드 6.2 의 자동
실행 경로도 탄다.

```
BUILD : pip install -r requirements.txt
START : uvicorn main:app --host 0.0.0.0 --port $PORT
```

| # | 저장소 경로 | 기능 | 호출하는 쪽 |
|---|---|---|---|
| 1 | `final/SFR-006/request/` | HWPX 템플릿 채우기 | 워크플로우 스텝 006-1·2·3 |
| 2 | `no_pythonstep/SFR-018-polish/` | 글다듬이 | 젠포탈 `POST /chat` |
| 3 | `no_pythonstep/SFR-018-translate/` | 번역 | 젠포탈 `POST /chat` |
| 4 | `no_pythonstep/SFR-018-faq/` | FAQ 생성 | 젠포탈 `POST /chat` |

저장소를 하나로 두고 하위 디렉토리를 쓰면 가이드에 "이 디렉토리를 루트로 본다" 항목이
**없으므로** 커맨드가 흡수해야 한다:

```
BUILD : pip install -r no_pythonstep/SFR-018-translate/requirements.txt
RUN   : cd no_pythonstep/SFR-018-translate && \
        uvicorn main:app --host 0.0.0.0 --port $PORT
```

⚠️ **실물에서 확인할 것 하나**: 빌드·시작 커맨드가 셸을 거치는지(`cd A && B` 가 먹는지).
안 먹으면 `uvicorn --app-dir <경로> …` 로 바꾼다.

### 단위별 필수 환경변수

**공통(네 단위 전부)**: `GENOS_URL` `LLM_SERVING_ID` `GENOS_TOKEN`. 빠지면 첫 LLM 호출에서
"서비스 설정이 완료되지 않았습니다" 로 선다. 선택 변수 전체 목록과 의미는 `README.md`
"기능별 추가 설정" 과 `no_pythonstep/README.md` 단위별 절.

| 단위 | 공통 외 **필수** | 상태 저장 |
|---|---|---|
| 006 | `TEMPLATE_FILL_TEMPLATE_DIR`(공유 볼륨) · `REDIS_URL` | Redis |
| 글다듬이 | **`TEXT_GUARD_MCP_ID`** (MCP `genon_text_guard` 등록 id — 없으면 구조·숫자 점검 없이 결과만 나간다) | **무상태** (Redis·볼륨 불필요) |
| 번역 | 용어사전을 쓸 때만: `TRANSLATE_GLOSSARY_API_URL` · `TRANSLATE_GLOSSARY_DRIVE_ID` · `TRANSLATE_GLOSSARY_WORKSPACE_ID` (+ 토큰이 다르면 `TRANSLATE_GLOSSARY_TOKEN`) | 무상태 |
| FAQ | `REDIS_URL` (세션 id 가 올 때만 쓴다 — 없으면 저장만 건너뛴다) | Redis |

> **006 은 워크플로우 pod 와 코드서빙 pod 가 같은 Redis 를 봐야 한다.** 다운로드가 대화에서
> 모은 값을 읽는 유일한 통로다. `TEMPLATE_DIR` 볼륨도 양쪽에 **같은 경로로** 마운트돼야 한다.

**018 `/chat` 선택 변수** — 전부 기본값이 있다.

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `TRANSLATE_DEFAULT_TARGET_LANG` · `_SOURCE_LANG` · `_REGISTER` | 없음 | `question` 머리말에 값이 없을 때 쓴다. **대상 언어 기본값이 없으면** 머리말 없는 번역 요청은 "언어를 선택해 주세요" 로 선다 |
| `POLISH_DEFAULT_DOC_TYPE` · `POLISH_DEFAULT_TONE` | 내장 기본값 | 〃 |
| `FAQ_DEFAULT_COUNT` | `5` | 〃 |
| `CHAT_HEARTBEAT_SECONDS` | `5` | 진행 표시 프레임 간격. **`0` 이면 끈다** — 화면에 글자로 찍히면 끈다 |
| `CHAT_TOKEN_EVENT` · `CHAT_RESULT_EVENT` · `CHAT_END_EVENT` · `CHAT_HEARTBEAT_EVENT` | `token` · `complete` · `end` · `heartbeat` | SSE 이벤트 이름. `CHAT_END_EVENT` 를 비우면 end 프레임을 안 보낸다 |

**결과 파일 업로드** (018 셋 + 006)

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `GENOS_CDN_UPLOAD_URL` | `http://llmops-cdn-api-service:8080/minio/upload/temp` | 결과 파일을 올릴 곳 |
| `GENOS_CDN_HOSTNAME` | `https://genos.genon.ai` | presigned URL 에 박힐 외부 호스트 (업로드 폼의 `hostname` 필드) |

둘 다 기본값이 있어 **안 넣어도 뜬다.** 다만 배포마다 호스트가 다를 수 있고, 잘못 잡히면
`download_url` 이 계속 `null` 로 나간다 — 그때도 결과는 정상 전달되므로(fail-open)
**증상이 "파일만 못 받는다" 로만 드러난다.** 등록 뒤 한 번은 링크를 눌러 볼 것.

**긴 문서 처리 — 선택 변수**

| 변수 | 기본값 | 단위 | 뜻 |
|---|---|---|---|
| `FAQ_MAX_CONTEXT_CHARS` | `12000` | FAQ | 조각 하나 = LLM 호출 한 번의 예산 |
| `FAQ_MAX_CONTEXT_CHUNKS` | `80` | FAQ | 조각 수 상한(80 × 12,000 ≈ 96만 자). **여기 걸린 문서만** 뒤가 잘린다 |
| `FAQ_LLM_CONCURRENCY` | `6` | FAQ | 동시에 도는 구간 수 |
| `POLISH_MAX_CHUNK_CHARS` | `6000` | 글다듬이 | 조각 하나 = LLM 호출 한 번의 예산 |
| `POLISH_LLM_CONCURRENCY` | `4` | 글다듬이 | 동시에 도는 조각 수 |

**실물 LLM 없이 정한 값**이라 게이트웨이 대기시간을 보고 조정해야 할 수 있다 — 글다듬이
조각은 `RES_TIMEOUT`(90초) 안에 끝나야 하고, 429 가 나면 `*_LLM_CONCURRENCY` 부터 내린다.

### 확인

`GET /health` → 200. 네 단위 모두 `GET /` 와 `GET ""` 도 등록돼 있다(게이트웨이가 경로
없이 베이스를 때리는 배포 대비).

**health 200 만으로 배포 완료로 보지 않는다** — 가이드 11.3 이 정상 입력·입력 오류·외부
timeout 을 각각 실행하라고 요구한다. 018 셋은 `/chat` 을 직접 한 번씩 부른다:

```
POST /chat  {"question": "target_lang: en\n\n안녕하세요.", "stream": true}
→ heartbeat · token… · complete · end 프레임. complete.download_url 이 열리는지 본다
```

`GET /prompts` 가 프롬프트를 어디서 읽었는지 말한다 — 첫 요청이 `PromptRenderError` 면
`prompt/<배포단위이름>/` 이 이미지에 없는 것이다.

주요 업무 경로:

| 단위 | 경로 |
|---|---|
| 006 | `/chat/context` `/chat/extract` `/chat/commit` · `/templates` `/fields` `/status` `/preview` `/values` `/blocks` `/generate` `/generate/upload` |
| 글다듬이 | **`/chat`** · `/policies` `/polish` `/download` |
| 번역 | **`/chat`** · `/languages` `/translate` `/translate/markdown` `/translate/hwpx` `/glossary` `/glossary/reload` `/download` |
| FAQ | **`/chat`** · `/config` `/generate` `/generate/upload` `/faqs` `/download` |

---

## §2. MCP 도구 (area 01)

**⚠️ MCP 는 서빙이 아니라 파일이다.** GenOS 가 **소스 파일 한 개**를 받아 실행하고 `mcp`
객체를 런타임이 전역으로 주입한다. **FastAPI 앱도 `/health` 도 `$PORT` 도 시작 커맨드도
`requirements.txt` 도 없다.** 파일을 **각각** 등록한다.

| 파일 | 접두어 | 도구 | 누가 부르나 | 등록 |
|---|---|---|---|---|
| `final/mcp/genon_text_guard.py` | `TG` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` | **글다듬이 서빙 `/chat`** (`TEXT_GUARD_MCP_ID`) | **필수** |
| `final/mcp/genon_ocr.py` | `OC` | `ocr_scan_pages` | **006 스텝 1** — 첨부에 스캔 쪽 표식이 있을 때만 (`OCR_MCP_ID`) | **필수** (006 첨부에 스캔 pdf 가 올 수 있으면) |
| `final/mcp/genon_template_draft.py` | `TD` | `template_fill_draft` | **사람이 직접** — 006 대화 도중 부분 초안 | 선택 |
| `final/mcp/genon_pii_audit.py` | `PA` | `pii_audit` `pii_scan_text` `pii_detectors` | **사람이 직접** — 생성 문서 미마스킹 집계 | 선택 |
| `final/mcp/genon_glossary.py` | `GL` | `glossary_lookup` `glossary_status` `glossary_reload` | 도구를 고르는 LLM (번역 서빙은 자기 사본을 쓴다) | 선택 |
| `final/mcp/genon_lang_policy.py` | `LP` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 018 **워크플로우 스텝**만 부른다 — `/chat` 경로는 서빙이 같은 판정을 내장한다 | 018 이 `/chat` 이면 불필요 |

**도구 카탈로그를 손으로 적지 않는다.** `@mcp.tool()` 이 시그니처·타입힌트·독스트링에서
카탈로그를 만든다. 도구 설명을 고칠 곳은 각 도구 함수의 독스트링이다.

**파일 하나에 `@mcp.tool()` 이 여러 번 나오는 것이 정상이다.** 등록(카탈로그)과
호출(`tools/call` 은 이름 하나)이 다른 층이다.

### 환경변수

| 파일 | 환경변수 |
|---|---|
| `genon_ocr.py` | `NFS_ROOT`(첨부 전처리기와 같은 NFS 의 이 서버 쪽 마운트 경로) · `OCR_ENDPOINT` · `OCR_TIMEOUT` |
| `genon_template_draft.py` | `GENOS_URL` · `GENOS_TOKEN` · `TEMPLATE_FILL_SERVING_ID`(코드서빙 #1) |
| `genon_glossary.py` | `TRANSLATE_GLOSSARY_API_URL` · `_DRIVE_ID` · `_WORKSPACE_ID` (+ `_TOKEN`). 셋 중 하나라도 없으면 **용어사전 없이 동작**하고 그 사실이 `glossary_status` 의 `reason` 으로 드러난다 |
| 나머지 | **없다** — 결정적 도구고 LLM 도 부르지 않는다 |

**MCP 파일은 stdlib 만 쓴다** — 폐쇄망 mirror 접근이 없어도 뜬다.

### 확인 — **도구가 다 나오는지 센다**

등록 뒤 `tools/list` 에 위 표의 도구가 파일마다 다 있어야 한다(`TG` 4 · `LP` 6 · `GL` 3 · `PA` 3 ·
`OC` 1 · `TD` 1). **하나라도 비면 이름이 겹쳐 덮인 것이다** — 한 서버에 여러 도구 파일이 함께
로드될 수 있고, 그 실패는 "도구가 이상한 값을 낸다" 로만 드러난다. 그래서 도구 함수를 뺀 모든
최상위 심볼에 접두어가 붙어 있다. 규율은 [`../mcp/README.md`](../mcp/README.md),
기계적 확인은 `Test/check/check_mcp_tools.py`.

---

## §2-1. 전처리기 (area 05)

**등록 후보는 `final_preprocessor.py` · `high_preprocessor.py` 다.** `smart_preprocessor.py`(지능형)는
쓰지 않는다(2026-09-29 확정). 어느 파일을 어느 등록(적재·첨부)에 걸지, 등록 화면 kwargs 는
`../preprocessor/CLAUDE.md`·`../preprocessor/README.md` 가 정본이다.

- **적재용과 첨부용은 소비자가 다르다.** 적재용은 임베딩·검색용이라 본문에 조문 머리말·표 조각
  머리말·겹침을 넣는다. 첨부용 산출물은 기능이 **LLM 에 그대로 던지는** 원문이다 — 적재용
  가공이 첨부에 섞이면 번역이 원문에 없던 머리말을 번역해 결과물에 싣는다. 오류가 아니라
  **결과물의 내용으로만** 드러난다.
- **같은 서버에 둘을 함께 올리지 않는다.** 진입점 이름이 둘 다 `DocumentProcessor` 라
  나중에 로드된 것이 앞엣것을 덮는다.
- **`__init__.py` 는 올리지 않는다.** 로컬 테스트용 재노출 파일이다.
- **연결(매핑)이 등록만큼 중요하다.** 등록 화면에서 **받을 확장자를 고를 수 있다.**
  매핑을 안 하면 hwpx 가 PDF 변환 경로로 가 **표 안 수치가 깨진다** — 이 전처리기를 만든
  이유가 그것이다. 확장자 설정을 바꾸면 `needs_reingest` 다(§F, 자동 재적재 아님).
- **첨부 산출물은 018 `/chat` 의 입력이다** — 플랫폼이 첨부를 전처리기에 지나게 하고, 그 산출물이
  `question` 안 `[입력된 문서]` 뒤에 실려 온다(006 은 캔버스 변수 `genosUploaded`).
- ⚠ **스캔 쪽 OCR 을 워크플로우로 미루는 설정(`ocr_defer`)은 018 `/chat` 과 맞지 않는다.** 미루면
  산출물에 스캔 표식 `[[GENON_SCAN …]]` 이 남는데, 018 `/chat` 에는 그것을 OCR 로 바꿔 줄 스텝이 없어
  **입력 오류로 선다.** 018 첨부에는 전처리기가 직접 OCR 하도록 등록한다(FRONT §6).
- **등록 화면에서 정하는 값**: `chunk_size`/`chunk_overlap`(기본 1000/100 은 **임시값** —
  임베딩 모델 컨텍스트에 맞춘다), `security_level`(배포별 필드면 `extra_metadata`).

---

## §2-2. 톤·문서유형 프롬프트 (선택 — 문구를 재배포 없이 고칠 때)

**등록 개수에 포함되지 않는다.** 코드 서빙·MCP·전처리기 10개와 달리 이건 **리소스**이고,
안 만들어도 네 단위는 이미지에 든 `.md` 와 내장 표로 정상 동작한다.

> **2026-09-07 에 방식이 바뀌었다 — JSON 문서 한 건 → 이름=ID 매칭.**
>
> 그전에는 프롬프트 **한 건**의 본문에 `{"tones": [...], "doc_types": [...]}` 를 담고
> 글다듬이 코드서빙과 MCP 가 각각 `json.loads` 로 읽었다
> (`POLISH_POLICY_PROMPT_ID`·`LANG_POLICY_PROMPT_ID`). 요구가 **"프롬프트는 전부
> 라이브러리에서 당겨 쓰되 코드서빙 안에서 JSON 을 해석하지 않는다"** 로 바뀌어
> 그 경로를 걷어냈다. **옛 환경변수 둘은 읽지 않는다** — 남아 있으면 글다듬이가
> `event=policy_legacy_env_ignored` 로 알린다.
>
> **MCP `genon_lang_policy` 는 이제 admin-api 를 아예 부르지 않는다.** 톤 프롬프트를
> 받는 것은 글다듬이 코드서빙이고, MCP 가 하는 일은 표로 하는 **강제 톤 판정**뿐이다.

### 이름 규약 — §2-3 과 **같은 매핑**에 담는다

톤·문서유형이라고 따로 환경변수를 두지 않는다. `POLISH_PROMPT_IDS` 하나에 이름=ID 로
넣으면 된다 — 그래야 `GET /prompts` 하나가 모든 문장의 출처를 답하고,
`POST /prompts/reload` 하나가 전부 비운다.

| 이름 | 본문 | 무엇을 덮나 |
|---|---|---|
| `system` | 시스템 프롬프트 골격 | `system.md` |
| `system_<톤코드>` | **그 톤 전용 시스템 프롬프트** | 있으면 골격 대신 이것을 쓴다 |
| `doc_type_<문서유형코드>` | 문서유형 추가 지시문 | 내장 표의 `extra_instruction` |

```
POLISH_PROMPT_IDS=system=43,system_polite=51,system_objective=54,doc_type_debt_reason=62
```

톤 코드는 `polite` `friendly` `clear` `objective`, 문서유형 코드는 `email` `post`
`customer_notice` `debt_reason` `reviewer_opinion` 이다 (`GET /policies` 가 그대로 낸다).

> **프로토타입 시연분은 코드에 적혀 있다** (2026-09-07). 온프레미스에서 만든 톤 프롬프트
> 번호 넷을 `config.TONE_PROMPT_IDS` 에 적어 뒀다 — `objective=100` · `clear=97` ·
> `friendly=94` · `polite=91`. **등록 화면에 같은 이름을 넣으면 그쪽이 이기므로**
> 최종적으로는 환경변수로 옮기면 되고(§10.5), 그때 코드 표를 비우지 않아도 된다.
> `DOC_TYPE_PROMPT_IDS` 는 문서유형 5종이 **빈 값**으로 자리만 잡혀 있다 —
> **빈 값은 매핑에서 통째로 빠지므로**(`prompt_ids_raw` 가 거른다) 프롬프트를 만든 뒤
> 번호만 채우면 된다.

- **본문은 JSON 이 아니라 문장 그대로**다. `system_<톤>` 은 `{{ doc_type_label }}`·
  `{{ doc_type_instruction }}` 을 쓸 수 있고, 변수 이름은 `prompt/
  SFR-018_text_polish/system.md` 머리말에 적혀 있다.
- **안 적은 이름은 그냥 안 덮인다** — 톤 넷 중 하나만 등록해도 나머지 셋은 `system.md` +
  내장 톤 지시문으로 돈다. **폴백이 살아 있는 것이 요점이다**: 이름만 보고 골랐다가
  `system_objective.md` 파일이 없어 요청이 서면 **톤 하나를 안 만들었다는 이유로
  글다듬이가 통째로 죽는다.**
- **지시문은 한국어로 쓴다** (2026-09-03 요구 확정).

### 못 하게 된 것 둘 — 대체 수단과 함께

ID 하나는 **본문 하나**를 가리킨다. 문장이 아닌 값은 담을 수 없다(담으려면 본문에 형식을
만들어야 하고, 그것이 방금 걷어낸 JSON 이다).

| 못 하는 것 | 그전(JSON) | 지금 |
|---|---|---|
| **톤·문서유형 추가** | `{"code": "legal", "label": "법무체", …}` | 개발자가 `text_polish/tone_presets.py` 표에 넣는다 (+ eval `TONE_RULES`) |
| **내장 톤 감추기** | `{"code": "friendly", "disabled": true}` | 없다. 필요해지면 환경변수로 받는다(본문에 형식을 만들지 않는다) |
| **새 문서유형의 강제 톤** | `"forced_tone": "legal"` | 표에만 있다 |

**내장 항목의 문구를 고치는 것**(요구의 본체)은 그대로 된다.

### 환경변수

| 어디 | 변수 | 값 |
|---|---|---|
| 글다듬이 코드서빙 (#2) | `GENOS_ADMIN_API_URL` | 내부 `http://llmops-admin-api-service:8080` / 외부 `https://<host>/api/admin` |
| | `POLISH_PROMPT_IDS` | 위 이름=ID 목록 |
| MCP `genon_lang_policy` (#6) | **없다** | admin-api 를 부르지 않는다 |

### 확인

```
GET  {글다듬이}/prompts          → 이름마다 source: "prompt_library" | "file" + reason
POST {글다듬이}/prompts/reload   → 리비전을 운영 반영한 뒤 즉시 반영 (안 부르면 최대 60초)
GET  {글다듬이}/policies         → 톤 4 · 문서유형 5 (이 목록은 **표에서** 온다)
```

`source` 가 `file` 이면 그 이름은 아직 안 덮였다. `reason` 을 본다 —
`not_configured`(ID 를 안 적었다) · `fetch_failed_404`(ID 오기입) · `empty_body` ·
`api_error` · `fetch_failed`. 이 구분이 없으면 "안 넣었다" 와 "못 읽었다" 가 화면에서
똑같이 옛 문구로 보인다. **`/prompts` 는 본문을 싣지 않는다** (3.8절).

`POST /policies/reload` 는 **`/prompts/reload` 의 별칭**으로 남겨 뒀다 — 화면·운영 문서가
그 경로를 쥐고 있어 없애면 404 가 "리로드했는데 안 바뀐다" 로 보인다.

### 한계 — **평가 채점은 따라오지 않는다**

`eval` 은 배포 단위를 import 하지 않으므로(파서를 공유하면 파서 버그를 함께 놓친다)
표에 없는 톤의 종결어미·금지표현 규칙을 알 수 없다. 그 톤으로 만든 결과물은
`tone_pass_rate` 의 **`skipped`** 에 담기고 합격률 분모에서 빠진다. 채점하려면
`Test/eval/eval_mcp/tone_metrics.py` 의 `TONE_RULES` 에 규칙을 함께 넣어야 한다.

## §2-3. 프롬프트 **본문**을 라이브러리에 올린다 (선택 — 2026-09-03)

§2-2 가 **톤·문서유형 목록**을 라이브러리에서 받는 경로라면, 이쪽은 **프롬프트 문장
자체**다. 자주 손보는 지시문(006 항목 매핑, FAQ 생성 지시, 번역·글다듬이 문체 지시)을
재배포 없이 고치기 위한 것이고, **고정 골격(시스템 프롬프트)은 파일로 둬도 된다.**

### 1) 프롬프트를 만든다

`도구 > 프롬프트 라이브러리` 에서 프롬프트를 만들고 본문에 **jinja 템플릿 문장**을 넣는다
(§2-2 와 달리 JSON 이 아니다). 변수 이름은 지금 `.md` 파일이 쓰는 것과 같아야 한다 —
각 기능 `prompt/<배포단위이름>/*.md` 의 머리말에 변수 목록이 적혀 있다.

- **문서유형·톤 지시문은 한국어**로 쓴다. 산출물의 어투를 통제하는 문장이라 지시 언어가
  섞이면 모델이 어휘를 헷갈린다 (요구 확정 2026-09-03).
- **시스템 프롬프트도 한국어로 쓴다** (2026-09-03 요구 확정). 예전에는 구조·형식·금지
  조항을 영어로 두는 규약이었다 — 라이브러리에 올릴 때도 한국어로 적는다.
- 변수 이름을 잘못 쓰면 **그 이름만 파일로 폴백**한다(요청은 죽지 않는다). 그 사실은
  `GET /prompts` 의 `source: "file"` 과 `event=prompt_library_render_failed` 로 드러난다.

### 2) 환경변수 — 이름=ID 로 꽂는다

| 어디 | 변수 | 값 |
|---|---|---|
| 네 코드서빙 공통 | `GENOS_ADMIN_API_URL` | §2-2 와 **같은 값** |
| 006 (#1) | `TEMPLATE_FILL_PROMPT_IDS` | `extract_user=41,document_user=42` |
| 글다듬이 (#2) | `POLISH_PROMPT_IDS` | `system=43` |
| 번역 (#3) | `TRANSLATE_PROMPT_IDS` | `system_batch=44,user_batch=45` |
| FAQ (#4) | `FAQ_PROMPT_IDS` | `system=46,user=47` |

**이름은 `.md` 파일 이름에서 확장자를 뗀 것**이다(`extract_user.md` → `extract_user`).
JSON 표기(`{"extract_user": "41"}`)도 받는다. 안 적은 이름은 파일을 쓴다 — **미설정은
오류가 아니라 정상 경로다.**

### 3) 확인

```
GET  {서빙}/prompts         → 이름마다 source: "prompt_library" | "file" + reason
POST {서빙}/prompts/reload  → 리비전을 운영 반영한 뒤 즉시 반영 (안 부르면 최대 60초)
```

`source` 가 `file` 이면 그 이름은 **아직 파일로 돌고 있다.** `reason` 을 본다 —
`not_configured`(ID 를 안 적었다) · `fetch_failed_404`(ID 오기입) · `empty_body`(본문이
비었다) · `api_error` · `fetch_failed`. 이 구분이 없으면 "안 넣었다" 와 "못 읽었다" 가
화면에서 똑같이 옛 문구로 보인다.

**`/prompts` 는 본문을 싣지 않는다** (3.8절) — 이름·ID·사유뿐이다.

**관리자 토큰**: `/prompts/reload` 는 006·번역·FAQ 에서 `X-Admin-Token` 을 요구한다
(그 단위들이 이미 토큰을 갖고 있다). 글다듬이는 토큰 자체가 없는 단위라 열려 있다 —
`POST /policies/reload` 와 같은 규약이다.

## §3. 등록해서 얻은 ID 를 어디에 넣나

| 환경변수 | 가리키는 등록 | 넣는 곳 |
|---|---|---|
| `TEXT_GUARD_MCP_ID` | MCP `genon_text_guard` | **글다듬이 코드서빙(#2)** 환경 설정 |
| `TEMPLATE_FILL_SERVING_ID` | 코드서빙 #1 | 006 워크플로우 스텝 1·2·3 · MCP `genon_template_draft` |
| `OCR_MCP_ID` | MCP `genon_ocr` | 006 워크플로우 스텝 1 (스캔 쪽 표식이 있을 때만 부른다) |

**코드서빙 #2·#3·#4 의 id 는 젠포탈 연계에 건다** — 컨테이너 서비스 "워크플로우로 사용" 연계의
대상으로 고르면 젠포탈이 그 서빙의 `POST /chat` 을 부른다. 화면에서 고른 값(대상 언어·톤·개수)을
`question` 머리말로 붙이는 배선은 FRONT §1.0.

배선이 빠지면: 워크플로우 스텝은 `CONFIG_MISSING` 으로 즉시 끝나고(시크릿 기본값 없음),
글다듬이 서빙은 `TEXT_GUARD_MCP_ID` 가 없으면 점검 없이 결과를 낸다(`event=text_guard_unconfigured`).

스텝 목록·순서는 [`../workflow/README.md`](../workflow/README.md).

---

## §4. 등록만으로는 안 되는 것 — 빠뜨리면 **조용히 반쪽이 된다**

| 전제 | 빠지면 | 조달 방법 |
|---|---|---|
| 프롬프트 디렉토리가 **이미지에** 들어가야 한다 | 기동은 되고 첫 LLM 호출에서 `PromptRenderError` | 018 셋은 `no_pythonstep/<기능>/prompt/` 가 폴더 **안**이라 폴더째 올리면 따라간다. **006 은 `final/SFR-006/prompt/` 가 배포 단위 밖**이라 따로 챙긴다. `<단위>_PROMPT_DIR` 환경변수가 없는 경로를 가리켜도 같은 증상이다 |
| 사내 PyPI registry/mirror | 빌드 커맨드가 그 자리에서 멈춘다 | 운영팀 확인 (가이드 11.5.6) |
| 006 워크플로우·코드서빙이 **같은 Redis** | 대화는 되는데 다운로드가 빈 문서를 만든다 | `REDIS_URL` 을 양쪽 pod 에 같게 |
| 006 `TEMPLATE_DIR` **같은 경로 마운트** | 템플릿을 못 찾는다 | 공유 볼륨 |
| 018 화면이 `question` 머리말을 붙인다 | 매번 배포 기본값으로 돌거나(번역은 언어 미선택 오류) | 젠포탈 연계 배선 (FRONT §6-1). 안 되면 `TRANSLATE_DEFAULT_*` 등으로 고정 |

워크플로우 pod 기본 이미지는 **전제가 아니다** — 스텝이 쓰는 외부 패키지는 `httpx` 하나이고
기본 이미지에 있다.

---

## §5. 순서

코드서빙 → (006) 템플릿 등록·확인 → MCP → 글다듬이에 `TEXT_GUARD_MCP_ID` → 젠포탈 `/chat` 연계(018) ·
워크플로우 스텝(006) → 끝단 통과. **006 워크플로우를 먼저 올리면 대화는 되는데 다운로드가 죽은
상태로 시작한다.** 전처리기는 이 사슬 **밖**이라 아무 때나 끼운다. 무엇을 올리고 무엇이 필요한지는
[`ONPREM.md`](ONPREM.md) 다.

올리기 전에 로컬에서:

```
python Test/run_all.py                          # 점검 17개 + unittest — 요약·FAIL 만
python Test/run_all.py deploy service_boot      # 빌드·기동 계약 + 네 단위 실제 기동
python Test/run_all.py chat_direct              # 018 `/chat` 직접 호출
```
