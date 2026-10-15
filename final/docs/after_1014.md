# 10/14 커밋 이후 다시 등록할 것

기준: 마지막 커밋 `1f85827`(1015.zip) 이후 작업 트리 변경분. 문서(`final/docs/*`, `README`)와
`Test/` 는 등록 대상이 아니라 뺐다. **다시 등록할 파일은 10개다** — 워크플로우 스텝 8 · 006 코드서빙 2.

## 한눈에

| # | 자리 | 파일 | 바뀐 함수 | 무엇 |
|---|---|---|---|---|
| 1 | 워크플로우 006-1 | `final/workflow/sfr006_01_context.py` | `run` · `_await_with_heartbeat` · `_ocr_scanned_pages` | `scan_ocr` 를 다음 스텝에 넘긴다 · OCR 진행 안내를 이벤트 dict 로 |
| 2 | 워크플로우 006-3 | `final/workflow/sfr006_03_commit.py` | `run` + 새 함수 3개 · 상수 | Disclaimer 호출부 · 자동 채움 진행 `<think>` · 안내 3종 |
| 3 | 워크플로우 다듬-1 | `final/workflow/sfr018_polish_01_policy.py` | `run` · OCR 헬퍼 2 · `_disclaimer` · `_check_input` | `scan_ocr` 넘김 · OCR 진행 안내 dict · 입력 멈춤 문장 MCP 전용 |
| 4 | 워크플로우 다듬-2 | `final/workflow/sfr018_polish_02_polish.py` | `run` · `_disclaimer` · `_disclaimers` | `notice`→`disclaimer` · 문장 MCP 전용 · 톤 강제 · 파일 실패 · OCR |
| 5 | 워크플로우 번역-1 | `final/workflow/sfr018_translate_01_detect.py` | `run` · OCR 헬퍼 2 · `_disclaimer` · `_check_input` | `scan_ocr` 넘김 · OCR 진행 안내 dict · 입력 멈춤 문장 MCP 전용 |
| 6 | 워크플로우 번역-2 | `final/workflow/sfr018_translate_02_translate.py` | `run` · `_finalize_stream` · `_disclaimer` · `_disclaimers` | `notice`→`disclaimer` · 문장 MCP 전용 · 구조 변경 · 사전 부재 · 파일 실패 · OCR |
| 7 | 워크플로우 FAQ-1 | `final/workflow/sfr018_faq_01_source.py` | `run` · OCR 헬퍼 2 | `scan_ocr` 넘김 · OCR 진행 안내 dict |
| 8 | 워크플로우 FAQ-2 | `final/workflow/sfr018_faq_02_generate.py` | `run` · `_disclaimer` · `_disclaimers` | 키 하나로 통합 · 문장 MCP 전용 · 파일 실패 · OCR |
| 9 | 006 코드서빙 | `final/SFR-006/request/template_fill/doc_prefill.py` | `prefill_from_document` | 단계 이벤트(`analyzing`·`filling`) |
| 10 | 006 코드서빙 | `final/SFR-006/request/template_fill/chat_api.py` | `_prefill_progress_text` · `_prefill_success_payload` · `_prefill_skipped` · `commit_turn` | 단계 문구 · `chunks_failed` · `download_failed` |

9·10 은 같은 코드서빙 단위라 **한 번에 배포**한다. 워크플로우 스텝은 캔버스에서 파일 하나씩 바꿔 넣는다.

### 코드서빙 — 추가로 다시 배포할 것

| 단위 | 파일 | 무엇 |
|---|---|---|
| FAQ | `faq/chunking.py` · `faq/generator.py` · `faq/formatting.py` · `faq/config.py`(request·open_ai) · `main.py` | 조각 크기 `총 글자 ÷ 요청 개수`(하한 `FAQ_MAX_CONTEXT_CHARS` · 상한 `FAQ_MAX_CHUNK_CHARS` 40000) · 조각이 더 많으면 후보 중 요청 개수만 고른다(근거 일치율 순, 같은 점수는 문서 전체에 고르게) · 그동안 `<think>` 진행 안내를 흘린다 |
| 네 단위 모두 | `llm.py` · `config.py` (request · open_ai) | 요청 본문에 `reasoning_effort`(`LLM_REASONING_EFFORT`, 기본 `none`, 비우면 싣지 않는다) |

FAQ 결과 개수는 이제 요청 개수를 넘지 않는다 — "요청보다 많이 나왔다" 안내(옛 32번)는 없앴다.

---

## 결과 키 — `disclaimer` 하나로 통일

네 기능 모두 안내는 result 의 **`disclaimer` 한 키**(문자열, 여럿이면 줄바꿈 `\n`)다. 없으면 키가 없다.
`notice` 배열은 더 안 나간다. FAQ 의 `faq_under_requested` 는 `faq_shortfall` 과 같은 판정이라 지웠다.

## 안내 문장은 Disclaimer MCP 에서만 나온다

- 워크플로우는 **언제 띄울지와 숫자만** 정한다. 문장은 `widget_disclaimer(agent_id, disclaimer_id)` 가
  MCP 도구 환경변수 `MCP_TOOL_19_{agent_id}_{disclaimer_id}` 에서 돌려준다(`SFR018` · `SFR006` + 번호).
- 숫자가 필요한 안내는 등록 문구 **다음 줄에** 스텝이 상세 줄(`다듬지 못한 구간: 3곳`)을 붙인다.
- 문구를 못 받으면 `disclaimer` 맨 앞에 `disclaimer를 확인하지 못하였습니다. 결과에 유의해 주세요.` 가
  한 번 붙고 상세 줄 · 결과는 그대로 나간다. 스텝의 고정 문장 · `DISCLAIMER_IDS` · `DISCLAIMER_AGENT_ID` 는 없앴다.
- 다듬-1 · 번역-1 의 입력 판단 멈춤 문장도 같은 MCP(11번 · 21번)에서 받는다. 못 받으면 오류표의 안내문이다.
- 번호 · 등록 문구 · 붙여 넣을 값 전체: `final/docs/disclaimer.md` (21종).

새로 생긴 안내 종류: `polish_tone_forced` · `translate_structure_changed` · `translate_glossary_unavailable` ·
`*_download_failed`(018 셋) · `template_prefill_partial` · `template_download_failed` · `scan_ocr`(네 기능).

---|---|---|---|
| `polish_tone_forced` | 글다듬이 | 고른 톤이 문서유형 정책으로 바뀌었을 때 | lang_policy MCP 문장 (`※ '보도자료' 문서는 정책상 '격식' 톤이 적용됩니다.`) |
| `translate_structure_changed` | 번역 | 스트리밍 경로에서 표·제목 구조가 달라졌을 때 | 표·제목 등 문서 구조가 원문과 달라진 곳이 {count}곳 있습니다. 결과를 확인해 주세요. |
| `translate_glossary_unavailable` | 번역 | 한↔영인데 용어사전을 못 썼을 때 (미설정 배포 제외) | 용어사전을 불러오지 못해 용어사전 없이 번역했습니다. 잠시 후 다시 번역해 주세요. |
| `polish_download_failed` · `translate_download_failed` · `faq_download_failed` | 018 셋 | `download_url` 이 없을 때 | ○○ 파일을 만들지 못했습니다. 파일이 필요하면 다시 시도해 주세요. |
| `template_prefill_partial` | 006 | 문서 자동 채움이 **일부** 구간만 실패 | 문서 일부 구간({count}곳)을 읽지 못해 그 내용은 채우지 못했습니다. 빠진 내용은 말씀해 주시면 채워 드리겠습니다. |
| `template_download_failed` | 006 | 다 채워 파일을 만들려다 실패 (덜 채운 것은 제외) | 문서 파일을 만들지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `scan_ocr` | 네 기능 | 스텝 1 이 스캔 쪽을 OCR 로 읽었을 때 (006 은 그 턴에 문서를 실제로 태웠을 때만) | 스캔 PDF는 글자 인식(OCR)으로 읽어 일부 내용이 틀릴 수 있습니다. 원본과 대조해 확인해 주세요. |

전체 목록은 `final/docs/disclaimer.md`.

---

## 파일별

### 1·3·5·7. 스텝 1 넷 (`sfr006_01_context` · `sfr018_polish_01_policy` · `sfr018_translate_01_detect` · `sfr018_faq_01_source`)

`_await_with_heartbeat` · `_ocr_scanned_pages`
- 진행 안내를 처음부터 `{"event": "token", "data": 문구}` 로 낸다. 끝은 `{"event": "done", "data": …}` 이고
  `run` 이 받아 쓸 뿐 내보내지 않는다.

`run`
- OCR 진행 안내를 받은 그대로 `yield event` 한다.
- OCR 을 부르기 전에 `scan_ocr = bool(_scan_batches(…))` — 첨부에 스캔 쪽 표식이 있었는가.
- 성공 반환 dict 에 `"scan_ocr": scan_ocr` 추가. 마지막 스텝이 읽는다(006 은 스텝 2 가 `{**data}` 로 통과시킨다).
- 다듬-1 은 업로드 원문을 `uploaded` 변수로 한 번 받고 OCR 에 넘기도록 풀어 썼다(동작 같음).

### 2. `sfr006_03_commit.py` (006-3)

새로 들어간 것 (018 세 스텝과 같은 사본)
- 상수 `_MCP_HEADERS` · `_DISCLAIMER_TOOL` · `_DISCLAIMER_READ_TIMEOUT` · `_DISCLAIMER_AGENT`(`"SFR006"`) · `_DISCLAIMER_NUMBERS` · `_DISCLAIMER_UNAVAILABLE` · `_THINK_OPEN` · `_THINK_CLOSE`
- 함수 `_mcp_call` · `_disclaimer` · `_disclaimers`

`run`
- 자동 채움 스트림의 첫 진행 줄 앞에 `<think>`, 스트림이 끝나면(실패해도) `</think>`.
- 자동 채움 결과에서 `chunks_failed` 를 읽는다(`prefill_chunks_failed`).
- `wanted`: `template_prefill_partial`(일부 실패 · 전량 실패 아님) · `template_download_failed`(커밋 응답의
  `download_failed`) · `scan_ocr`(`scan_ocr` 이고 문서가 있고 건너뛰지 않은 턴).
- result 에 `disclaimer` 키(있을 때만).

### 4. `sfr018_polish_02_polish.py` (다듬-2)

`run`
- `wanted` 는 `(종류, 상세 줄)` 목록. 맨 앞 `polish_tone_forced` (`tone_overridden is True`, 상세 줄은 `tone_notice`).
- 끝에 `polish_download_failed`(링크 없음) · `scan_ocr`.
- `disclaimer = await _disclaimers(...)`(문자열), result `notice` → `disclaimer`.

### 6. `sfr018_translate_02_translate.py` (번역-2)

`_finalize_stream`
- 정규화 dict 에 `structure_issue_count` — finalize 응답 `structure.issues` 수(받지 못하면 0).

`run`
- `translate_glossary_unavailable` — `translate_glossary_applies is True` 이고 사전 사유가
  `ok`·`not_applicable`·`unknown`·`not_configured` 가 아닐 때.
- `translate_structure_changed` · `translate_download_failed` · `scan_ocr`.
- `disclaimer = await _disclaimers(...)`, result `notice` → `disclaimer`.

### 8. `sfr018_faq_02_generate.py` (FAQ-2)

`run`
- `faq_under_requested` 삭제, `notice`·`disclaimer` 두 키 → `disclaimer` 하나.
- `faq_download_failed` · `scan_ocr` 추가.

### 9. `doc_prefill.py` (006 코드서빙)

`prefill_from_document`
- 안쪽 함수 `_stage(status)` — `on_progress` 가 있을 때만 `{"status": status}`.
- 반복 묶음: 주제 뽑기 전 `analyzing`, 채우기 전 `filling`. 그 밖·비상 경로: 채우기 전 `filling`.

### 10. `chat_api.py` (006 코드서빙)

- `_prefill_progress_text`: `analyzing` → `LLM이 문서를 분석하고 있습니다…`, `planned` 뒤에
  `추출된 주제를 활용하여 템플릿을 생성합니다.`, `filling` → `템플릿에 내용을 채우는 중입니다…`
- `_prefill_success_payload` · `_prefill_skipped`: `chunks_failed` 추가.
- `commit_turn`(커밋 응답 조립): `download_url` 을 변수로 받고 `download_failed`(= 다 채웠는데 링크 없음) 추가.

---

## 함께 바꿀 설정

| 자리 | 변수 | 할 일 |
|---|---|---|
| Disclaimer MCP 도구 (ID 19) | `MCP_TOOL_19_SFR018_*` · `MCP_TOOL_19_SFR006_*` 21개 | `disclaimer.md` 끝 "그대로 붙여 넣을 등록 값" 을 넣는다 |
| 워크플로우 6 스텝 (다듬-1·2 · 번역-1·2 · FAQ-2 · 006-3) | `DISCLAIMER_MCP_ID` | Disclaimer MCP 서빙 ID |
| 워크플로우 | `DISCLAIMER_IDS` · `DISCLAIMER_AGENT_ID` | 있으면 지운다 — 더 읽지 않는다 |

## 프론트에 알릴 것

- 안내 키는 네 기능 모두 **`disclaimer`(문자열)** 하나다. 여럿이면 `\n` 으로 이어 온다 — 마크다운으로
  렌더하면 한 줄로 붙으니 줄바꿈을 살려 그린다.
- 006 은 문서를 올린 턴에 자동 채움 진행이 `<think>` … `</think>` 로 먼저 온다.
- 정본: `final/docs/FRONT.md` §1 · §2.3 · §3.3 · §3.5.2 · §4.4.

## 배포 순서

- 스텝 1 과 마지막 스텝은 순서 무관 — 스텝 1 만 바뀌면 `scan_ocr` 를 아무도 안 읽고, 마지막 스텝만
  바뀌면 `scan_ocr` 가 없어 OCR 안내가 안 나갈 뿐이다.
- 006 코드서빙(9·10)이 먼저 바뀌어도 안전하다 — 늘어난 키를 옛 스텝은 무시한다.
- **다듬-2 · 번역-2 · FAQ-2 가 바뀌는 순간 화면이 `notice` 를 못 읽는다 — 프론트 변경과 같이** 올린다.

## 검증

`python Test/run_all.py` — 21개 중 20개 통과. 남은 하나는 `check_high_preprocessor`(76/93, 실패 0) —
`docling_core` 가 없는 환경이라 hwp 그림 점검을 건너뛰어 건수만 모자라다(이번 변경과 무관).
`check_workflow_run` 128 → 136 (톤 강제 · `<think>` · 새 안내 4건 · Disclaimer 상세 줄 · 못 받음 · 번호표 대조).
