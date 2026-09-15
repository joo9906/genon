# ONPREM.md 작성 작업 — 진행 기록

> 세션이 끊기면 이 파일부터 읽는다. 목표는 `onprem/ONPREM.md`(신규) 하나에
> **이관 대상 파일·필요 env·MCP/전처리기 점검 결과**를 정리하고, 그 과정에서
> 드러난 결함을 고치는 것이다. README 는 건드리지 않는다.

## 요구 (2026-09-07)
1. `onprem/` 안에 있는 것만 대상으로 서류를 **새로 쓴다** → `onprem/ONPREM.md`
2. 어떤 파일 위주로 돌아가는가 + 어떤 env 가 필요한가 (간략·깔끔)
3. MCP 기능·전처리기가 제대로 만들어져 있는지 **확인**
4. **MCP hwpx 파싱은 날린다** — 네 기능의 파일 첨부는 **전처리기만** 쓴다
5. 확인에서 나온 것은 구현까지

## 조사 결과 (완료)
- 워크플로우 스텝 9개: `genosUploaded` 로 첨부를 받는 자리 **네 곳 모두 전환 완료**
  (`sfr006_01_context`·`sfr018_faq_01_source`·`sfr018_polish_01_policy`·
  `sfr018_translate_01_detect`). 추출기 `_extract_uploaded_markdown` 사본 4벌이
  **본문 동일**(태그 없으면 통째로 본문).
- 워크플로우에 남은 MCP 호출: `LANG_POLICY_MCP_ID`(translate_01·polish_01) ·
  `TEXT_GUARD_MCP_ID`(polish_02·translate_02). **`HWPX_TEXT_MCP_ID` 참조 0건.**
- 그런데 **`onprem/mcp/genon_hwpx_text.py` 파일이 아직 있다** (1,200여 줄,
  운영 호출부 0건). `GLOSSARY_MCP_ID` 도 참조 0건 → `genon_glossary.py` 도
  워크플로우 호출부가 없다(코드서빙이 자기 `glossary_store.py` 로 한다).
- MCP 도구 표면: lang_policy 6 · text_guard 4 · glossary 3 · pii_audit 3 · hwpx 1
- 전처리기 등록 단위 2개: `final_preprocessor.py`(적재용) · `only_me.py`(첨부용)

## 할 일
- [x] 조사 — 첨부 경로 / MCP 호출부 / env 수집
- [x] **`mcp/genon_hwpx_text.py` 삭제** (`git rm -f`) — 등록이 5 → **4개**
- [x] 그물 셋 갱신 (되돌리기 없이 건수만 준다 = 그 판정들이 정말 그 파일만 보고 있었다)
      - `check_mcp_tools` 92 → **86** (hwpx 판정 6건 + 픽스처 2벌 제거, `HX` 접두어 제외)
      - `check_deploy_contract` 72 → **64** (`MCP_PREFIXES` 에서 `HX` 제거)
      - `check_table_grid` 37 → **34** (LLM 입력 경로 사본 셋 → **둘**)
- [ ] 문서 참조 정리 (진행 중)
      - [ ] `mcp/README.md` · `docs/SERVING_REGISTRY.md` · `workflow/README.md`
      - [ ] `docs/FEATURES.md` · `preprocessor/README.md` · `codeserving/CLAUDE.md`
      - [ ] `README.md` 는 **새로 쓰지 않는다**(요구) — 삭제로 거짓이 된 줄만 고친다
      - 이력 문서(`docs/change_08*.md`·`HISTORY.md`)는 **날짜 기록이라 손대지 않는다**
- [ ] `onprem/ONPREM.md` 작성
- [ ] 점검 13개 + unittest 2벌 재실행

## 결정 사항 (되묻지 말 것)
- **코드서빙의 직접 업로드 경로는 남긴다** — `POST /translate/hwpx`·`/faq/hwpx`·
  `/generate/upload`. 캔버스를 지나지 않아 전처리기 산출물이 없고, MCP 와도 무관하다.
  그래서 hwpx 파서 사본은 **3벌**(번역·FAQ·006) + 전처리기 2벌로 남는다.
- 첨부 경로의 정본은 `preprocessor/only_me.py`(첨부용) 하나다. 적재용
  `final_preprocessor.py` 를 첨부에 걸면 검색용 머리말이 LLM 입력에 섞인다.


---

## ⚠️ 조사 중에 찾은 **기존 결함** — 프롬프트 렌더가 깨져 있다 (2026-09-07)

jinja 를 걷어내고 `.j2` → `.txt` 로 옮긴 미커밋 작업에서 **템플릿은 새 규약으로 다시
썼는데 조립 함수는 옛 변수 이름을 그대로 준다.** 로더에 `{% for %}` 가 없어져서
템플릿이 `field_lines`(문자열)·`glossary_block`·`context_line`·`existing_block` 처럼
**미리 조립된 문자열**을 받게 바뀌었는데, 빌더는 아직 `field_lines`(리스트)·
`glossary`(리스트)·`scope`·`existing_questions` 를 넘긴다.

실측(빌더를 직접 불러 확인):

| 자리 | 템플릿이 요구 | 빌더가 주는 | 결과 |
|---|---|---|---|
| 006 `document_user` | `field_lines`(str)·`document`·`chunk_note` | `field_lines`(**list**)·`document`·`chunk_index`·`chunk_total` | **렌더 실패** |
| 번역 `system_batch`/`system_single` | `glossary_block` | `glossary`(list) | **렌더 실패** |
| 번역 `user_single` | `context_line`·`text` | `text`·`scope` | **렌더 실패** |
| FAQ `retry_shortfall` | `existing_block` | `existing_questions`(list) | **렌더 실패** |

**어떻게 드러나나 — 안 드러난다.** 넷 다 `PromptRenderError` 를 잡아 fail-open 한다:
006 자동 채움은 `prefill_failed` 한 줄만 남기고(문서를 올렸는데 아무 일도 안 일어난다),
FAQ 부족분 재요청은 조용히 포기하고, **번역은 전량이 막힌다.** `check_unit_endpoints`
95/107 · `check_chat_turn` IndexError · SFR-006 unittest 11건 실패가 전부 이것이다.

> 리스트를 그대로 넘기면 렌더가 죽지 않고 통과하는 경우도 있다 — 로더가 `str(value)` 로
> 떨어뜨려 **`['- 제목']` 이라는 파이썬 repr 이 프롬프트에 실린다.** 오류가 아니라
> 결과물 품질로만 드러나는 형태라 함께 막아야 한다.

- [ ] 빌더 넷을 템플릿 규약(미리 조립된 문자열)에 맞춘다
- [ ] **그물 신규** `onprem/test/check_prompt_render.py` — 네 단위의 **실제 빌더**를 불러
      모든 템플릿을 렌더한다. 지금 이 층을 보는 점검이 **0건**이라 넉 달을 살아남았다.

### 고쳤다 (2026-09-07)

| 자리 | 고친 것 |
|---|---|
| `template_fill/prompts.py` | `_joined`(목록 → 문자열) · `_body_section`(옛 `{% if %}`) · `_chunk_note` |
| `common/prompt_builder.py` | `_glossary_block(suffix, terms)` · `context_line`(개행 포함) · 접미어로 경로 통일 |
| `faq/generator.py` | `existing_block` 조립 · 템플릿 이름 `.j2` → `.txt` |
| `SFR-018_text_polish/main.py` | `_doc_type_block`(빈 문자열 또는 개행으로 끝난다) |

**그물 신규 `onprem/test/check_prompt_render.py` — 71건.** 네 단위의 **실제 빌더**를
불러 모든 템플릿을 렌더하고, ① 렌더가 죽지 않는가 ② 파이썬 repr 이 실리지 않는가
③ 넣고 빼는 판단(조각 표기·용어사전 절·본문 구획)이 살아 있는가 ④ 템플릿에 `{% %}`
가 남지 않았는가를 본다. **여섯 갈래를 각각 되돌려 FAIL 을 확인했다.**

> 오탐을 한 번 밟았다 — repr 탐지 정규식이 FAQ `system.txt` 의 JSON 예시
> (`{"faqs": [{...`)를 잡았다. 파이썬 repr 은 **홑따옴표**를 쓰므로 그쪽만 보게
> 좁혔다. 오탐을 남기면 결국 사람이 판정을 끈다.

## 전체 점검 재실행 결과 (2026-09-07, 전부 종료 코드 0)

| 점검 | 건수 | 비고 |
|---|---|---|
| `check_api_contract` | 52 | |
| `check_body_blocks` | 17 | |
| `check_chat_turn` | **46** | 프롬프트 조립 수정으로 되살아났다 (그전 IndexError) |
| `check_deploy_contract` | **64** | 72 → 64 (MCP hwpx 제거) |
| `check_eval_metrics` | 88 | |
| `check_final_preprocessor` | 171 | |
| `check_mcp_tools` | **86** | 92 → 86 (hwpx 판정 6건) |
| `check_output_safety` | 5 | |
| **`check_prompt_render`** | **71** | **신규** |
| `check_service_boot` | 16 | |
| `check_table_grid` | **34** | 37 → 34 (사본 셋 → 둘) |
| `check_tone_policy` | 20 | |
| `check_unit_endpoints` | **107** | `SSL_CERT_FILE=` 로 비워야 107 이다 |
| `check_workflow_run` | 103 | |
| **합계** | **880** | + unittest 394 (SFR-006 **64** · SFR-018 **330**) = **1,274** |

- `SFR-006/tests/test_prompt_library.py` 3곳이 **옛 변수 이름**으로 로더를 직접 부르고
  있었다(`block_styles`·`block_lines`). 새 계약(`body_section`)으로 고쳤다 — 변수 계약
  자체는 `check_prompt_render` 가 실제 빌더로 본다.
- [x] 점검 14개 + unittest 2벌 전부 통과
- [x] **`onprem/ONPREM.md` 작성 완료** — 이 작업의 산출물이다
- [x] `test/README.md` 건수 갱신

## 끝났다 (2026-09-07)

산출물은 **`onprem/ONPREM.md`** 다. 이 진행 기록은 그 문서가 있으면 지워도 된다 —
다만 "왜 프롬프트 렌더가 깨져 있었나" 의 조사 과정은 여기에만 있다.
