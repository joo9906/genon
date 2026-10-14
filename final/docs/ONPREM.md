# ONPREM — 폐쇄망에 올리는 것 전부

> **이 문서 하나로 이관이 된다.** 무엇을 몇 개 등록하는가 · 각 등록의 **핵심 파일** ·
> **필요한 환경변수** · 그리고 **지금 상태가 검증됐는가**.
>
> 등록 화면 각 칸에 무엇을 적는지는 [`SERVING_REGISTRY.md`](SERVING_REGISTRY.md), 프론트와 주고받는
> 값은 [`FRONT.md`](FRONT.md) 가 정본이다.
>
> **현행 코드는 전부 `final/` 이다.** 네 기능 모두 캔버스 워크플로우(파이썬 스텝)가 흐름을 쥐고
> 코드서빙을 부른다.
>
> | 무엇 | 현행 코드 |
> |---|---|
> | 코드서빙 네 단위 | `final/<기능>/request/` (+ 이미지에 `final/<기능>/prompt/`) |
> | MCP · 워크플로우 스텝 · 전처리기 | `final/mcp/` · `final/workflow/` · `final/preprocessor/` |
>
> 저장소 다른 곳(`Test/`·`archive/`)은 테스트·참조이고 **올리지 않는다.**

---

## 1. 무엇을 등록하나

| # | 영역 | 무엇 | 등록 형태 |
|---|---|---|---|
| 1 | 03 | `final/SFR-006/request/` (+ 이미지에 `final/SFR-006/prompt/`) | 코드 서빙 |
| 2 | 03 | `final/SFR-018-polish/request/` (+ 이미지에 `final/SFR-018-polish/prompt/`) | 코드 서빙 |
| 3 | 03 | `final/SFR-018-translate/request/` (+ 이미지에 `final/SFR-018-translate/prompt/`) | 코드 서빙 |
| 4 | 03 | `final/SFR-018-faq/request/` (+ 이미지에 `final/SFR-018-faq/prompt/`) | 코드 서빙 |
| 5 | 01 | `final/mcp/genon_text_guard.py` | MCP 도구 (**파일 1개 = 등록 1개**) — 다듬-2 · 번역-2 스텝이 부른다 |
| 6 | 01 | `final/mcp/genon_lang_policy.py` | MCP 도구 — 다듬-1 · 번역-1 스텝이 부른다 |
| 7 | 01 | `final/mcp/genon_ocr.py` | MCP 도구 — 네 기능 스텝 1 이 부른다 (스캔 쪽 표식이 있을 때) |
| 8 | 05 | `final/preprocessor/final_preprocessor.py` 또는 `high_preprocessor.py` | 전처리기 — 적재(검색)용 |
| 9 | 05 | 첨부용 전처리기 | 전처리기 — 질의 시 첨부용 (§3) |

**선택 MCP**: `genon_template_draft.py`(006 대화 도중 부분 초안 — 사람이 부른다) ·
`genon_pii_audit.py`(생성 문서 미마스킹 집계 — 사람이 부른다) · `genon_glossary.py`(도구를 고르는 LLM 용).

그리고 **캔버스에 붙여 넣는 워크플로우 스텝 9개**(`final/workflow/*.py` — 006 셋 · 018 여섯).
서버가 뜨지 않으므로 등록 수에 들어가지 않지만 **이것이 없으면 네 기능 모두 동작하지 않는다.**
화면에서 고른 값은 캔버스 변수로 실려 와야 한다(FRONT §1.2.1).

올리지 않는 것: `Test/`(점검·unittest·평가지표 stdio MCP) · `archive/` · `*.md`.

---

## 2. 기능 넷과 **핵심 파일**

**네 기능 모두 캔버스 스텝(02)이 흐름을 쥐고 무거운 일은 코드서빙(03)이 한다.** 판정·점검이
MCP(01)에 있으면 스텝이 부른다.

### 2-1. SFR-006 템플릿 채우기 (hwpx 양식을 대화로 채운다)

```
[02] sfr006_01_context  → POST /chat/context   템플릿 항목 목록 확보
                        → POST /chat/prefill   첨부 문서로 빈 항목 자동 채움
[02] sfr006_02_extract  → POST /chat/extract   이번 턴 발화에서 값 추출
[02] sfr006_03_commit   → POST /chat/commit    세션에 반영 + 답변 조립   ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `template_fill/chat_api.py` | 대화 세 라우트. **턴 하나의 계약이 여기 있다** |
| `template_fill/hwpx_fields.py` | 슬롯(`{'제목', 16pt}`) 인식·되쓰기 — **쓰기 경로의 정본** |
| `template_fill/hwpx_blocks.py` | 본문 문단 복제·추가 |
| `template_fill/doc_prefill.py` | 첨부 문서 자동 채움 (조각 분할·앞 조각 우선) |
| `template_fill/session_store.py` | Redis 턴 상태 (**전역 dict 금지** — 레플리카 2개면 깨진다) |
| `template_fill/prompts.py` | 프롬프트 조립 — 목록 이어붙이기·구획 넣고 빼기 |
| `template_fill/hwpx_markdown.py` | 채팅 미리보기용 마크다운 |

**전용 UI 가 없어 채팅이 곧 화면이다** — payload 는 `text`·`download_url`(+ 다운로드 버튼이 쓰는
`session_id`·`template_id`)이고 **미리보기는 `text` 안에** 들어 있다. `download_url` 은 항목을
다 채웠을 때만 온다 — 그 유무가 곧 "받을 수 있다" 이고, 플래그를 따로 두면 **버튼을 켜 놓고
받을 수 없는** 상태가 생긴다. `POST /generate`(hwpx 직접 반환)는 폴백이다.

### 2-2. SFR-018 글다듬이

```
[02] sfr018_polish_01_policy  → MCP resolve_tone                문서유형 → 톤 확정 (+ 스캔이면 MCP ocr)
[02] sfr018_polish_02_polish  → POST /polish/stream (폴백 /polish)  조각 분할 · 동시 다듬기
                              → MCP text_guard ×2 (구조·사실)   흘리는 동안 함께 돈다   ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `main.py` | `/polish`·`/polish/stream` 라우트 + 프롬프트 조립 (톤·문서유형 지시문 주입) |
| `text_polish/chunking.py` | 조각 분할 — **코드펜스·여러 줄 HTML 표 안에서 끊지 않는다** |
| `text_polish/polisher.py` | 조각을 동시에 돌리고 부분 실패는 **원문 유지** |
| `text_polish/tone_presets.py` | 톤 4종·문서유형 5종 표 (**사본 3벌 중 하나**) |
| `text_polish/file_store.py` | 결과 md 를 CDN 에 굳혀 `download_url` 만 낸다 |

**무상태다** (Redis 없음) — 파일을 CDN 이 들고 있다.

### 2-3. SFR-018 번역

```
[02] sfr018_translate_01_detect    → genosUploaded 에서 원문 확보 (+ 스캔이면 MCP ocr)
                                   → MCP validate_direction  한국어 축 집행
[02] sfr018_translate_02_translate → POST /translate/stream → /translate/finalize (폴백 /translate/markdown)
                                   → MCP numeric_issues                      ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `translation_pipeline/office/stream_pipeline.py` | 스트리밍 경로 — 옵션 확정·조각 스트리밍·구조 대조 |
| `translation_pipeline/office/markdown_units.py` | **스켈레톤 분해** — 구조는 코드가 쥐고 LLM 에는 문장만 준다 |
| `translation_pipeline/office/pipeline.py` | 배치 번역·단건 폴백·재조립 |
| `translation_pipeline/office/languages.py` | 언어 표·감지·방향 판정 (**MCP `lang_policy` 사본과 짝**) |
| `translation_pipeline/common/glossary_exact.py` | 사내 용어 정확 매칭 (한국어 조사 폴백 포함) |
| `translation_pipeline/common/glossary_store.py` | 용어사전 API 적재 |
| `translation_pipeline/office/glossary_report.py` | 원문·번역문 **양쪽** `<mark>` 하이라이트 |
| `translation_pipeline/office/numeric_guard.py` | 숫자 지문 대조 |

### 2-4. SFR-018 FAQ

```
[02] sfr018_faq_01_source    → genosUploaded 에서 원문 확보 (+ 스캔이면 MCP ocr) → GET /config
[02] sfr018_faq_02_generate  → POST /generate/stream (폴백 /generate)          ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `faq/chunking.py` | 긴 문서를 조각으로 + **총 개수를 조각에 고르게 배분**(`plan_quota`, 모든 조각 최소 1개) |
| `faq/generator.py` | 생성·기각(스키마/근거/중복)·부족분 재요청 |
| `faq/evidence.py` | 근거 대조 — **문서 전체로** 한다 (조각 경계가 문장을 가르면 오탐) |
| `faq/session_store.py` | Redis (`POST /download` 폴백이 찾아온다) |
| `faq/md_output.py` | 산출물 md (마크다운 그대로 · BOM·CRLF) |

**근거·중복 검증을 통과한 항목만 흘린다** — 화면에 나타났다 사라지는 항목이 없다.

---

## 3. 첨부 문서는 **전처리기 산출물 하나**로 받는다 ⭐

**MCP 로 문서를 파싱하지 않는다.** 네 기능의 파일 첨부는 전부 첨부용 전처리기 산출물을 쓴다.

```
첨부 파일 → [첨부용 전처리기] → 캔버스 변수 genosUploaded (<doc …>본문</doc>) → 네 기능 스텝 1
              (파싱 · 청킹 없음)
```

- 스텝 1 은 `<doc>` 태그가 있으면 태그 안만, 없으면 통째로 본문으로 본다.
- **어느 전처리기 파일을 첨부용으로 거는지는 `../../final/preprocessor/CLAUDE.md` 가 정본이다.**
  등록 후보는 `final_preprocessor.py` · `high_preprocessor.py` 이고 지능형(`smart_preprocessor.py`)은
  쓰지 않는다.

### 적재용과 첨부용은 **본문에 들어갈 것이 반대다**

| | 적재용 | 첨부용 |
|---|---|---|
| 소비자 | 임베딩·검색(RAG) | **네 기능이 LLM 에 그대로 던지는 원문** |
| 조문 머리말 `제2장 총칙 > 제5조(목적)` | **넣는다** (임베딩되는 문자열에 있어야 걸린다) | **넣지 않는다** |
| 표 조각 머리말·겹침 | 넣는다 | 넣지 않는다 |
| 계약 | 검색이 걸리는가 | **무손실** — 레코드를 이어붙이면 원문이다 |

**첨부에 적재용 가공이 섞이면** 번역이 원문에 없던 머리말을 **번역해서 결과물에 싣고**, FAQ 는
그것을 원문 문장으로 보고 근거 대조를 하며, 006 자동 채움은 문서 내용으로 읽는다. 셋 다 오류가
아니라 **결과물의 내용으로만** 드러난다.

- **둘을 같은 서버에 함께 올리지 않는다** — 진입점 이름이 둘 다 `DocumentProcessor` 라
  나중에 로드된 것이 앞엣것을 덮는다.

### 스캔 쪽 — 쪽 이미지는 CDN(MinIO)에 올리고 스텝 1 이 MCP 로 읽는다

첨부용 전처리기(`high_preprocessor.py`)를 `ocr_defer=True` 로 등록하면 스캔 쪽을 OCR 하지 않고
쪽 PNG 를 CDN 업로드 API(`/minio/upload/temp` — 코드서빙 `file_store.py` 와 같은 API·기본값)에
올린 뒤 그 자리에 표식 `[[GENON_SCAN doc=<호출별 id> page=N image=<presigned URL>]]` 을 남긴다.
네 기능 스텝 1 이 표식을 찾아 같은 `doc` 의 연속한 쪽을 MCP `genon_ocr.ocr_scan_pages` 로 보내고,
MCP 가 URL 로 PNG 를 받아 OCR 한 글로 표식을 바꾼다.

- **pdf 통째가 아니라 쪽 PNG 를 올린다.** MCP 는 stdlib 만으로 돌아 pdf 를 쪽 이미지로 그릴 수
  없고, 텍스트 쪽이 섞인 pdf 를 OCR 서버에 통째로 보내면 읽을 필요 없는 쪽까지 읽는다.
- **presigned URL 이라 MCP 에 MinIO 자격증명이 필요 없다.** 대신 MCP 는 `OCR_IMAGE_HOSTS`(기본은
  `GENOS_CDN_HOSTNAME` 의 호스트)에 든 호스트의 URL 만 받는다 — 표식은 사용자가 써 넣을 수 있는
  본문 글자라 아무 URL 이나 받으면 MCP 가 내부망을 대신 읽어 주는 통로가 된다.
- **업로드에 실패하면 전처리기가 문서를 세운다.** 표식 없이 넘기면 그 쪽 본문이 조용히 빠진다.
- **링크는 만료된다.** 오래된 대화를 다시 돌리면 MCP 가 `IMAGE_NOT_FOUND`(403·404·410)를 내고 스텝이
  "파일을 다시 올려 주세요" 로 선다(재시도로는 안 낫는다).
- 등록 파라미터: `ocr_defer` · `scan_upload_url`(기본 env `GENOS_CDN_UPLOAD_URL`) ·
  `scan_hostname`(기본 env `GENOS_CDN_HOSTNAME`). 적재용 등록은 표식을 바꿔 줄 스텝이 없으므로
  `ocr_defer` 를 쓰지 않고 전처리기 안에서 OCR 한다.

### 그래도 남는 hwpx 파서 — **직접 업로드 경로**

전처리기를 지나지 않는 HTTP 경로가 셋 있고 **자기 파서로 읽는다**: `POST /translate/hwpx` ·
`POST /generate/upload`(FAQ) · `POST /generate/upload`(006). 그래서 파싱 코어 사본이 여러 벌
남고, `Test/check/check_table_grid.py` 가 **출력으로** 대조한다.

---

## 4. MCP 도구 — **확인 결과**

**MCP 는 서빙이 아니라 파일이다.** GenOS 가 소스 파일 한 개를 실행하고 `mcp` 객체를
전역으로 주입한다. FastAPI 앱도 `/health` 도 `$PORT` 도 `requirements.txt` 도 없다.

| 파일 | 접두어 | 도구 | 누가 부르나 |
|---|---|---|---|
| `genon_text_guard.py` | `TG` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` | **다듬-2**(앞의 둘) · **번역-2**(`numeric_issues`) |
| `genon_ocr.py` | `OC` | `ocr_scan_pages` | **네 기능 스텝 1** (스캔 쪽 표식이 있을 때) |
| `genon_template_draft.py` | `TD` | `template_fill_draft` | 사람이 직접 (006 대화 도중) |
| `genon_pii_audit.py` | `PA` | `pii_audit` `pii_scan_text` `pii_detectors` | 사람이 직접 (야간·주간 감사) |
| `genon_glossary.py` | `GL` | `glossary_lookup` `glossary_status` `glossary_reload` | 도구를 고르는 LLM (번역 서빙은 자체 처리) |
| `genon_lang_policy.py` | `LP` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | **다듬-1**(`resolve_tone`) · **번역-1**(`validate_direction`) |

등록 뒤 `tools/list` 로 센다 — **하나라도 비면 이름이 겹쳐 덮인 것이고**, 그 실패는 "도구가
이상한 값을 낸다" 로만 드러난다. 그래서 도구 함수를 뺀 모든 최상위 심볼에 접두어가 붙어 있다.

### 검증됨 (`Test/check/check_mcp_tools.py`)

- **여러 파일을 한 네임스페이스에 넣어** 덮이는지 본다 (한 서버에 같이 로드될 수 있다)
- 도구를 직접 불러 **결정적 판정**을 확인한다 (호출 성공만 보면 빈 결과도 통과한다)
- **빈 문자열 주입**을 견딘다 — GenOS 는 값이 없을 때 `None` 이 아니라 `""` 를 준다.
  선택 인자를 `int`/`float` 로만 선언하면 **본문에 닿기 전에 타입 검증에서 죽는다**
- 선택지(언어·문체·문서유형·톤)가 **도구 스키마 enum 에 실리는가** ↔ 표와 대조

`check_deploy_contract.py` 가 정적으로: 접두어 · `async … -> str` · `mcp` shim · 상대 import 금지 ·
**`print` 금지**(stdout 은 MCP 전송 채널이라 한 줄만 섞여도 프로토콜이 깨진다) · stderr 로깅.
**MCP 파일은 표준 라이브러리만 쓴다** — 폐쇄망 mirror 접근이 없어도 다 뜬다.

### 전송 규약 — 서빙·스텝이 MCP 를 부를 때

```
{GENOS_URL}/api/gateway/mcp/{serving_id}/mcp     JSON-RPC  tools/call
Accept: application/json, text/event-stream       ← 둘 다 열거해야 한다
```

MCP 스트리머블 HTTP 서버는 **POST 본문을 읽기 전에** Accept 를 본다. httpx 기본값(`*/*`)은 그
검사를 통과하지 못해 `406` 이고, **도구를 아무리 고쳐도 닿지 않는다.** 응답은 SSE 프레임으로 올
수 있으므로 `response.json()` 만 쓰면 도구는 돌았는데 결과만 사라진다. 워크플로우
`_mcp_call` 이 두 모양을 다 받고, `result`/`error` 를
든 프레임이 응답이다.

**다음에 나올 수 있는 실패**: `400 Missing session ID`. 서버가 상태 유지 모드면
`initialize` → `Mcp-Session-Id` 핸드셰이크가 필요하다. 지금은 상태 없는 모드를 전제한다 — **미검증**.

---

## 5. 환경변수

### 5-1. 워크플로우 스텝 9개 (캔버스 Python 스텝 환경 설정)

| 이름 | 스텝 | 없으면 |
|---|---|---|
| `GENOS_URL` · `GENOS_TOKEN` | 전부 | 게이트웨이를 못 찾는다·인증 실패 (`CONFIG_MISSING`) |
| `TEMPLATE_FILL_SERVING_ID` | 006-1·2·3 | 코드서빙 #1 을 못 부른다 |
| `TEXT_POLISH_SERVING_ID` | 다듬-2 | 코드서빙 #2 를 못 부른다 |
| `TRANSLATION_SERVING_ID` | 번역-2 | 코드서빙 #3 을 못 부른다 |
| `FAQ_SERVING_ID` | FAQ-1·2 | 코드서빙 #4 를 못 부른다 |
| `TEXT_GUARD_MCP_ID` | 다듬-2 · 번역-2 | 구조·사실·숫자 점검 없이 결과만 나간다 |
| `LANG_POLICY_MCP_ID` | 다듬-1 · 번역-1 | `CONFIG_MISSING` |
| `OCR_MCP_ID` | 스텝 1 넷 | 첨부 원문에 스캔 쪽 표식이 있을 때만 부른다. 없으면 그 요청이 `CONFIG_MISSING` 으로 선다 |
| `DISCLAIMER_MCP_ID` · `DISCLAIMER_IDS` · `DISCLAIMER_AGENT_ID` | 다듬-2 · 번역-2 · FAQ-2 | 안내 문장을 Disclaimer MCP 에서 받는다. 없거나 못 받으면 스텝의 고정 문장으로 나간다(`event=disclaimer_fallback`) — 안내가 빠지지는 않는다 |
| `POLISH_DEFAULT_DOC_TYPE` · `POLISH_DEFAULT_TONE` | 다듬-1 | (선택) 화면이 안 준 값의 기본값. 없으면 내장 기본값 |
| `TRANSLATE_DEFAULT_TARGET_LANG` · `TRANSLATE_DEFAULT_SOURCE_LANG` · `TRANSLATE_DEFAULT_REGISTER` | 번역-1 | (선택) 화면이 안 준 값의 기본값. 대상 언어가 끝내 없으면 `TARGET_MISSING` |
| `GENON_DEBUG` | 전부 | (선택) `1` 일 때만 켠다 — §6 |

### 5-2. 코드 서빙 4개 — **게이트웨이 3종이 필수다**

| 이름 | 단위 | 없으면 |
|---|---|---|
| `GENOS_URL` | 넷 다 | **설정 부재** — 재시도 불가로 갈라 낸다 |
| `LLM_SERVING_ID` | 넷 다 | 같음. **모델도 이 값이 정한다** |
| `GENOS_TOKEN` | 넷 다 | 인증 실패 |

> **셋은 호출 시점에 읽는다** (`Config.genos_url()` 꼴) — 프로세스가 뜬 뒤 환경이 채워지는 경로가
> 있다. **나머지 값은 import 시점에 굳으므로 운영에서 바꾸려면 서빙을 재기동해야 한다**
> (`LLM_RETRY_COUNT` 가 그 예다).

**Redis** — 006·FAQ 만 필요하다(`REDIS_URL`). FAQ 는 세션 id 가 올 때만 쓴다. 글다듬이·번역은 무상태다.

**CDN(내려받기 링크)** — `GENOS_CDN_UPLOAD_URL`·`GENOS_CDN_HOSTNAME`. 기본값이 있으므로 안 넣어도
뜨지만, 틀리면 **결과는 나오는데 파일만 못 받는다**(fail-open). 등록 뒤 한 번은 링크를 눌러 볼 것.
기본값(업로드 URL `http://llmops-cdn-api-service:8080/minio/upload/temp`, 멀티파트 필드
`hostname`+`file`, 응답 경로 `data.presigned_url`)은 GenOS 참조 샘플과 대조해 맞췄다.

**용어사전** (번역·`genon_glossary` 공용, 쓸 때만):
`TRANSLATE_GLOSSARY_API_URL` · `_DRIVE_ID` · `_WORKSPACE_ID` (+ 토큰이 다르면 `_TOKEN`).
셋 중 하나라도 없으면 **용어사전 없이 동작**하고 그 사실이 `GET /glossary` 의 `reason` 으로 드러난다.

**프롬프트 라이브러리** (선택): `GENOS_ADMIN_API_URL` + `<단위>_PROMPT_IDS`
(`TEMPLATE_FILL_PROMPT_IDS`·`POLISH_PROMPT_IDS`·`TRANSLATE_PROMPT_IDS`·`FAQ_PROMPT_IDS`).
`이름=ID` 꼴이고 **이름은 프롬프트 파일 이름에서 확장자를 뗀 것**이다. 안 넣으면 이미지에 든
`.md` 파일로 돈다 — `GET /prompts` 가 어느 쪽을 썼는지 말한다.

**GenOS 가 주입한다** (다른 목적으로 쓰지 않는다): `PORT` · `OPENAPI_PATH` ·
`LANGUAGE` · `BUILD_COMMAND` · `START_COMMAND`.

### 5-2-1. MCP `genon_ocr` · 첨부용 전처리기 (스캔 쪽)

| 이름 | 어디 | 뜻 |
|---|---|---|
| `OCR_ENDPOINT` · `OCR_TIMEOUT` | MCP `genon_ocr` | Paddle OCR 서빙 주소 · 쪽 하나 요청 제한(초, 기본 60) |
| `OCR_IMAGE_HOSTS` | MCP `genon_ocr` | 받아도 되는 이미지 URL 호스트(쉼표 구분). 없으면 `GENOS_CDN_HOSTNAME` 의 호스트, 그것도 없으면 `genos.genon.ai`. **밖이면 `URL_NOT_ALLOWED`** — 스텝이 `CONFIG_MISSING` 으로 선다 |
| `OCR_FETCH_TIMEOUT` | MCP `genon_ocr` | 쪽 이미지 하나 받기 제한(초, 기본 30). 실패는 `IMAGE_FETCH_FAILED` |
| `GENOS_CDN_UPLOAD_URL` · `GENOS_CDN_HOSTNAME` | 첨부용 전처리기 | 쪽 PNG 업로드 주소 · presigned URL 호스트. 등록 파라미터 `scan_upload_url` · `scan_hostname` 이 이긴다 |

> **전처리기의 `GENOS_CDN_HOSTNAME` 과 MCP 의 `OCR_IMAGE_HOSTS` 는 같은 호스트를 가리켜야 한다.**
> 어긋나면 업로드는 되는데 모든 스캔 쪽이 `URL_NOT_ALLOWED` 로 선다.

### 5-3. 손잡이 — 기본값으로 두어도 되지만 알아 둘 것

| 이름 | 기본 | 단위 | 뜻 |
|---|---|---|---|
| `RES_TIMEOUT` | 90 | 넷 다 | LLM 응답 대기(초) |
| `LLM_RETRY_COUNT` | 2 | 넷 다 | **4xx 는 재시도하지 않는다** |
| `LLM_CONCURRENCY` | 15 | 번역 | 배치 동시 실행 |
| `POLISH_MAX_CHUNK_CHARS` | 6000 | 다듬 | 조각 하나 = 호출 하나의 예산 |
| `POLISH_LLM_CONCURRENCY` | 4 | 다듬 | 동시에 도는 조각 수 |
| `POLISH_MAX_INPUT_CHARS` | 200000 | 다듬 | 넘으면 **자르지 않고 요청을 세운다** |
| `FAQ_MAX_COUNT` | 30 | FAQ | 사용자가 고를 수 있는 **총** 개수 |
| `FAQ_MAX_CONTEXT_CHARS` | 12000 | FAQ | 호출 **한 번**의 예산 (문서 상한이 아니다) |
| `FAQ_LLM_CONCURRENCY` | 6 | FAQ | **동시에 도는 구간 수** — 429 면 여기부터 내린다 |
| `TEMPLATE_FILL_DOC_PREFILL` | 1 | 006 | `0` 이면 첨부 자동 채움을 끈다 |
| `TEMPLATE_FILL_DOC_CHUNK_CHARS` | 12000 | 006 | 자동 채움 조각 크기 |
| `TEMPLATE_FILL_DOC_GROUP_CONCURRENCY` | 4 | 006 | 반복 묶음 자동 채움에서 **동시에 채우는 묶음 수** — 429 면 내린다 |
| `TEMPLATE_FILL_DOC_GROUP_SECTION_CHARS` | 12000 | 006 | 묶음 하나에 보여 줄 문서 구간 상한 |
| `TRANSLATE_MAX_TOTAL_CHARS` | 500000 | 번역 | 넘으면 **자르지 않고 오류다** |

> **개수는 사용자가, 비용은 배포가 정한다.** 한 손잡이에 묶으면 둘 중 하나를 못 지킨다.

### 5-4. 프롬프트 파일은 **이미지에 함께 들어가야 한다**

로더가 단위 루트에서 위로 올라가며 `prompt/<배포단위이름>/` 을 찾는다. 네 단위 모두
`final/<기능>/prompt/<배포단위이름>/` 이 **배포 단위(`request/`) 밖**이라 이미지에 따로 챙긴다. 없으면 **템플릿
부재로 요청이 선다**(빈 프롬프트로 넘어가지 않는다 — 지시문 없는 프롬프트의 결과는 정상 응답처럼
내려간다). 위치가 다르면 `<단위>_PROMPT_DIR` 로 통째 지정한다 — **이 값이 없는 경로를 가리켜도
같은 증상**이다(로그 없이 `PromptRenderError`).

**확장자는 `.md` 다.** 로더는 `{{ name }}` 치환만 하므로 **목록을 이어붙이는 것과 절을 넣고 빼는
판단은 조립 함수의 몫이다** — `Test/check/check_prompt_render.py` 가 네 단위의 실제 빌더를 불러
그 계약을 본다.

---

## 6. 디버그 에코 — **테스트 기간 한정**

3.8절 화이트리스트가 값을 버리기 때문에(허용 목록 밖은 **이름만** 남는다) 로그만으로는 무엇이
왜 실패했는지 알 수 없다.

- **`GENON_DEBUG=1` 일 때만 낸다. 기본은 꺼짐** — 허용 필드 밖 값이 남으므로 원인을 추적할
  때만 켜고 운영에서 켜 두지 않는다.
- `print` 가 아니라 **`sys.stderr.write`** 다. 표준 로그와 섞이지 않게 하려는 것이고(MCP 는
  stdout 이 전송 채널일 수 있다), 플랫폼은 stdout·stderr 를 둘 다 수집한다.
- 값은 **300자에서 자르고** 인자는 **키만** 싣는다 — 문서 원문·프롬프트가 통째로 실리면 이
  에코 자체가 유출 경로가 된다.
- **걷어낼 때는 각 파일의 `디버그 에코` 블록과 그 호출만 지운다** — 로그 경로는 손대지 않았으므로
  지우면 원래 규약으로 정확히 돌아온다.

오류 코드에는 **`ERR-` 접두어**가 붙는다(`ERR-03-00020002`). 분류 판정은 **뒤 8자리**로 한다.

---

## 7. 이관은 **파일이 아니라 사람이 건넌다**

폐쇄망에 파일을 넣을 수 없다 — **화면에 띄워 놓고 타이핑한다.** 전처리기는 벤더 절반이 이미
그쪽에 있어 **우리 코드만** 건넌다. 어디까지 치는지·가드 한 자리가 외부와 다른 이유는
`../../final/preprocessor/CLAUDE.md` "이관" 절이 정본이다.

---

## 8. 검증 — 지금 상태

```bash
export PYTHONIOENCODING=utf-8   # Windows 콘솔 필수 (cp949 가 '—' 에서 죽는다)
python Test/run_all.py                       # 점검 18개 + unittest 3벌
```

| 점검 | 건수 | 무엇을 보나 |
|---|---|---|
| `check_deploy_contract` | 82 | 배포 계약을 소스만 읽고 (코드서빙 4 + MCP + eval + 스텝) |
| `check_service_boot` | 16 | 네 단위를 실제로 띄운다 — lifespan·`/health`·`/` |
| `check_chat_direct` | 13 | 006 코드서빙의 `POST /chat`(`template_fill/chat_direct.py`) — 운영 경로는 워크플로우다 |
| `check_api_contract` | 57 | 006 엔드포인트 |
| `check_unit_endpoints` | 121 | 018 세 단위 엔드포인트 경계 · md 규약 세 단위 대조 |
| `check_chat_turn` | 60 | 006 대화 한 턴 계약·상태 전이 (02 스텝 3개 ↔ 03) |
| `check_workflow_run` | 124 | 스텝 9개 실행 + MCP 전송 규약 + 스트리밍 전송 규약 |
| `check_mcp_tools` | 99 | MCP 파일 공존·결정적 판정·빈 문자열 주입 |
| `check_final_preprocessor` | 153 | 전처리기(첨부용 + hwpx) — 라우팅·조문 위계·무손실 (실물 hwpx 5벌) |
| `check_high_preprocessor` | 90 | `high_preprocessor` — pdf 단·문단·OCR·hwp·그림 (docling_core 없으면 hwp 17건 빠짐) |
| `check_smart_preprocessor` | 35 | 지능형 + hwpx (등록하지 않는다 — 회귀만 본다) |
| `check_table_grid` | 31 | 파싱 코어 사본 대조 (**출력으로**) |
| `check_prompt_render` | 86 | 프롬프트가 실제로 렌더되는가 |
| `check_eval_metrics` | 91 | **가드레일 자체** 점검 |
| `check_tone_policy` | 20 | 톤 사본 3벌 대조 |
| `check_body_blocks` | 17 | 문단 복제 안전장치 |
| `check_output_safety` | 5 | 파트 선언·누름틀 안내문 |
| **합계** | **1,100** | + unittest SFR-006 117 · SFR-018 389 · SFR-006 `/chat` 입력 해석 11 |

기준 건수는 `Test/run_all.py` 의 `EXPECTED` 가 갖는다. **건수가 줄면 FAIL** 이다 —
실물 경로가 어긋나면 FAIL 없이 건수만 조용히 준다.

---

## 9. 남은 미검증 — 폐쇄망에서 확인할 것

| # | 무엇 | 아니면 어떻게 드러나나 |
|---|---|---|
| 1 | **화면이 고른 값이 캔버스 변수로 오는지** (대상 언어·톤·개수) | 018 이 매번 배포 기본값으로 돈다 — 번역은 기본 대상 언어가 없으면 `TARGET_MISSING` |
| 2 | **워크플로우 스텝 간 `data` 크기 한도** | 큰 문서에서 캔버스가 본문을 못 넘긴다 — 본문 대신 핸들(세션 키)만 넘기는 형태로 바꿔야 한다 |
| 3 | **스캔 쪽 presigned URL 호스트(`GENOS_CDN_HOSTNAME`, 외부 호스트)가 MCP 파드에서 접속되는지** | 모든 스캔 쪽이 `IMAGE_FETCH_FAILED` — 스텝이 "글자를 읽지 못했습니다" 로 선다 |
| 4 | **presigned URL 만료 기간** | 그보다 오래된 대화를 다시 돌리면 `IMAGE_NOT_FOUND` — "파일을 다시 올려 주세요" |
| 5 | 첨부용 산출물이 `genosUploaded` 로 오는지 | 원문이 비어 `NO_INPUT`·`INPUT_EMPTY` |
| 6 | MCP 서버가 **상태 없는 모드**인지 | `400 Missing session ID` |
| 7 | 내려받기 링크(MinIO/CDN)가 **실제로 되는지** | **결과는 나오는데 파일만 못 받는다.** `POST /download`(018) · `POST /generate`(006) 폴백 |
| 8 | 게이트웨이가 `model` 없는 요청을 받는지 | 400/422. 되살릴 자리는 네 `config.py` + 네 `llm.py` |
| 9 | hwpx 적재 결과가 **적재 결과 화면**에 뜨는지 | 빈 목록 — 오류가 아니다. 되돌릴 자리는 `_page_fields` 하나 |
| 10 | 빌드·시작 커맨드가 **셸을 거치는지** (`cd A && B`) | 안 먹으면 `uvicorn --app-dir <경로>` |
| 11 | LLM 실호출 품질 (프롬프트가 전부 한국어다) | 한국어가 섞여 나오면 각 `*.md` 의 출력 언어 고정 문장을 먼저 볼 것 |
| 12 | 내려준 `.md` 를 **윈도우 PC**(메모장)에서 열어보기 | BOM·CRLF 는 응답 바이트로만 확인했다 |
| 13 | 프론트가 첨부할 때 **`overrideConfig.file_ids` 를 싣는지** (글다듬이 · 번역) | 키가 없으면 `genosUploaded` 를 읽지 않는다 — 첨부가 오류 없이 무시되고 발화만 처리된다 |
| 14 | 운영 `DISCLAIMER_IDS` 번호 배정 (15종 — [`disclaimer.md`](disclaimer.md)) | 안 넣어도 고정 문장이 나간다. 등록 문장으로 바꾸려면 필요하다 |
| 15 | 입력 판단 LLM(`/input/check`)이 실제 모델에서 정상 문서를 막지 않는지 | 멀쩡한 문서에 "입력 내용을 확인해 주세요" — 프롬프트 `input_check_system.md` 를 먼저 볼 것 |

---

## 10. 더 읽을 곳

| 문서 | 무엇 |
|---|---|
| [`SERVING_REGISTRY.md`](SERVING_REGISTRY.md) | **등록 작업지시서** — 화면 각 칸에 무엇을 적나 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **네 기능의 흐름도** — 무엇이 어디서 돌고 요청이 어떤 길로 지나가나 |
| [`FRONT.md`](FRONT.md) | 프론트와 주고받는 값 — 캔버스 변수·`result` (정본) |
| [`env.md`](env.md) | 환경변수 — 기능별로 어디에 무엇을 넣나 |
| [`disclaimer.md`](disclaimer.md) | 안내 문구 15종 — 언제 · 자리표시 · 고정 문장 |
| `../README.md` | `final/` 배치 · 올리는 법 |
| [`README.md`](../../final/docs/README.md) | 환경변수의 **의미**·기능별 운영 규약 |
| [`FEATURES.md`](../../final/docs/FEATURES.md) | 무엇이 구현돼 있고 어느 경로로 부르나 |
| `../../final/preprocessor/CLAUDE.md` · `README.md` | 전처리기 — 등록 후보·조문 위계·표 HTML·첨부용 |
| `../../final/mcp/README.md` | MCP 규율 (접두어·shim·빈 문자열) |
| `../../final/workflow/README.md` | 스텝·순서·스트리밍 규약 |
| `../../Test/check/README.md` | 점검이 무엇을 보고 무엇을 못 보나 |
| `../../Test/eval/README.md` | 평가지표·합불 기준 |
