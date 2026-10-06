# 리팩토링 진행 기록 (2026-10-06) — 끝나면 지운다

## 요구 원문
1. "1~3 수정하고, 주석이나 전체적인 코드 리팩토링까지 진행해줘"
   - 1~3 = md 전환 후 남은 txt/메모장 문구 (README 프론트 예시·FAQ requirements/config/hwpx_text/session_store·번역 main/api_contract)
3. (세션 3) "다 해줘. 용어사전은 API까지 맞춰 정보를 줬으니 실 구현해봐. admin api 는 내가 나중에 넣으면 되니 문서 기준으로"
   → 스펙 `archive/genos-project/용어사전.md` 기준으로 glossary_store ↔ mcp/genon_glossary 적재 구현을 완성. 실제 URL/토큰은 환경변수로 비워 둔다.
2. (추가) "다 끝나면 최종적으로 docs 에 api request/response 도 적어줘" → `final/docs/API.md` 신규로 계획

## 되묻지 말 것
- `txt_output.py` 파일 이름은 그대로 둔다 (사용자 결정).
- 리팩토링 = 동작 보존. 라우트·payload 키·오류 코드·`run` 시그니처·환경변수 이름은 바꾸지 않는다.
- 사본(단위 간 같은 파일): file_store(4, AST 대조), logging_utils(4), prompt_library(4), prompt_loader(4),
  txt_output(3, 바이트 동일), tone presets(polish tone_presets ↔ mcp genon_lang_policy 값), hwpx 파싱 코어,
  용어사전(glossary_store·glossary_exact ↔ mcp/genon_glossary), llm/config 는 request↔open_ai 짝.
- **smart_preprocessor.py 의 PART 2 는 final_preprocessor.py PART 2 와 텍스트 동일이어야 한다**
  (`check_smart_preprocessor` 가 문자열 비교). final 쪽 주석을 고치면 smart 로 그대로 복사할 것.

## 세션 3 후반 — 완료, 브랜치 `refactor/cleanup-glossary-workflow` 커밋 e26a70c (이 파일은 커밋 안 함) — 점검 후 추가 지시 ("A 고치고 C 이력 문서 지우고 B 5·7·8·9 수정")
- [x] A1 코드 주석 4곳: preprocessor/__init__.py, 번역 config.py:157·markdown_units.py:78 `.j2`, verify_final.py:5
- [x] A2 006 prompts.py:88 `_tone_prompt_name`, workflow sfr006_01/02 jinja2 서술
- [x] A3 CLAUDE.md 낡은 사실 (루트 hwpx 5벌, final only_me·file_not_found, preprocessor 155/33)
- [x] A4 FEATURES·FRONT ↔ 코드 불일치 (라우트 표, indexed_at float, source field|slot, policy 블록, §3-1 감지 거부)
- [x] C 이력 문서 삭제: HISTORY, change_0823/0827/0828, last_refactor, ONPREM_PROGRESS, WIP_prompt_dynamic, WIP_pdf_tables (참조 정리 포함)
- [x] B5 번역 /translate/stream 내부오류 ERR_INPUT→내부 코드, 번역·FAQ 재적재 403 → 권한 오류 코드
- [x] B7 006 llm.py 비스트리밍 timeout connect/read 분리
- [x] B8 다듬-1 tone_notice → 다듬-2 notice 맨 앞 (tone_overridden 일 때). check_workflow_run +2 → 130. FRONT.md §2.3 반영.
- [x] B9 첨부용 전처리기 문서 정리 (only_me 삭제 반영)

## 세션 3 끝 — "정리 이어서" (브랜치 refactor/cleanup-glossary-workflow, e26a70c 푸시됨)
- [ ] 문서 에이전트 A: final/docs/README.md · ONPREM.md · SERVING_REGISTRY.md · final/README.md
- [ ] 문서 에이전트 B: DESIGN_NOTES.md · FEATURES.md · SFR-006_architecture.md · SFR-018_txt_output.md · hwpx_library_adoption.md · final/CLAUDE.md · preprocessor/CLAUDE.md·SMART_PROGRESS.md
- [x] 직접: final_preprocessor PART2 주석 2곳(+smart PART2 동기화, preprocessor·table_grid 4/4). final/ 코드에 남은 날짜·"옛" 은 전부 현재 동작 설명·예시라 유지.
- [ ] Test 주석 에이전트: Test/check·run_all·SFR-*/tests·onprem 의 주석·독스트링만 (리터럴·판정 불변)
- [ ] 끝나면 run_all → 커밋·푸시 (같은 브랜치)

## 현재 상태 (세션 3 마감)
- **할 일 전부 끝남.** `python Test/run_all.py` 18/18 통과 (점검 988 + unittest 494).
- 남은 것은 아래 "사용자 결정이 필요한 것" 뿐이다. 결정이 끝나면 이 파일을 지운다.

## 완료
- [x] 1~3 문구 수정
- [x] FAQ error_codes.py 복구 — 1차 에이전트 유실로 `_WORKFLOW` 미정의 상태였음. 미사용 ERR_CHAT_* 7개 삭제.
- [x] 단위별 리팩토링 6개 전부 완료·점검 OK:
  - **FAQ**: generator/main/chunking/session_store/md_system.txt 이력·옛 경로 정리.
  - **글다듬이**: 루트 main.py 의 `if __name__` 기동 블록이 중간에 있어 스크립트 기동 시 /prompts·/prompts/reload·/polish/stream
    미등록이던 **실결함 수정**(맨 끝으로). polisher `_record_failure` 통합, `PolishChunk.size` 삭제, 이력 정리.
  - **번역**: 같은 기동 블록 결함 수정(/prompts·/prompts/reload·/translate/stream·/translate/finalize).
    `PromptContext.from_options()` 로 중복 통합, stream_pipeline `_settle_failed()`, 사실과 다른 주석 정정.
  - **006**: chat_api import 정리, field_judge 쓰레기 문자, run_chat/onprem/.j2 이력 정리, request/CLAUDE.md 재작성.
  - **전처리기**: final PART2 주석만·PART3 미사용 상수 삭제. high 번호 헬퍼 공용화·pdf 헬퍼 4개(실물 10벌 대조 동일). README 재작성.
  - **mcp+workflow**: 주석·README 만, 스텝 머리말 사실 오류 다수 정정.
- [x] smart_preprocessor PART 2 를 final 과 동기화 (전처리기 에이전트가 final 주석만 고쳐 check_smart 가 FAIL 났었음. 코드는 동일 확인).

- [x] **용어사전 실구현 (세션 3)** — `용어사전.md` v1.9.3 기준. glossary_store ↔ mcp/genon_glossary 같은 규칙:
  대표어 `text` → 한국어, 영문명 속성(`TRANSLATE_GLOSSARY_TARGET_KEY`) → 영어, 동의어(`_SYNONYM_KEY`, 선택) → 한국어 이형.
  URL 통째로 설정(`TRANSLATE_GLOSSARY_API_URL`, `{glossary_id}` 치환, `_ID`), 인증 = 사전 읽기 전용 키(`_TOKEN`, GENOS_TOKEN 폴백 제거),
  `_WORKSPACE_ID` 선택. 사유 `target_key_missing` 신설. 페이지 파라미터 `_PAGE_PARAMS`(스펙 미기재). 상한 20,000.
  테스트: GlossaryAdminApiLoadTest 6→12, check_mcp_tools 에 사본 대조 3건 신설 → EXPECTED mcp_tools 92, SFR-018 402.
  문서: final/CLAUDE.md·docs/README·DESIGN_NOTES·ONPREM·SERVING_REGISTRY·final/README 갱신.
  **사용자가 나중에 넣을 것**: 실제 용어 목록 URL, 사전 ID, 읽기 전용 키, 영문명/동의어 속성 키. 페이지 파라미터가 pg/pgSize 가 아니면 _PAGE_PARAMS(두 사본).

## 남은 일
- [x] **사본 일괄 정리** 완료 (txt_output 3벌 바이트 동일 유지). 남긴 의심점: 006 llm.py 비스트리밍 timeout 단일값(머리말과 불일치),
  006 prompts.py:88 없는 `_tone_prompt_name` 참조, workflow sfr006_01/02 의 jinja2 서술, 루트 CLAUDE.md hwpx "5벌(MCP 포함)".
  대상: file_store/logging_utils/prompt_library/prompt_loader/txt_output/llm(짝)/config(짝)/hwpx 사본 주석/glossary_store 주석.
  남은 이력 표기 약 150곳(onprem·.j2·날짜·옛/예전·jinja2 틀린 서술·`#h` 오타·docs/GENOS_RULES 경로).
  같은 역할 사본은 같은 문구로, txt_output 3벌은 바이트 동일 유지.
- [x] glossary_exact ↔ genon_glossary 매칭부 이력 주석 정리 (mcp_tools·SFR-018 통과).
- [x] **API 문서** — `final/docs/API.md` (글다듬이 10·번역 13·FAQ 11·006 20 라우트). 루트 CLAUDE.md 에서 가리킴.
- [x] `python Test/run_all.py` 전체 18/18 통과.

- [x] API 초안 3단위 완료 (scratchpad api/polish.md 10라우트·faq.md 11·sfr006.md 20). 번역 초안 대기.
  초안 에이전트가 찾은 문서↔코드 불일치(API.md 에 코드 기준으로 적고 FRONT/FEATURES 는 따로 손볼 것):
  글다듬이 FRONT §2.1 policy 블록 없음·/polish download_url 실패 시 "" (FAQ·006 은 None)·FEATURES 에 /polish/stream 없음·GET / endpoints 누락.
  FAQ FEATURES §4-3 에 /generate/stream·/prompts 없음·**POST /download items 는 근거를 `sources` 에서만 읽어 /generate 의 `evidence` 를 되보내면 근거 빈 줄**.
  006 ERR_CHAT_* http_status 미지정 → /chat/* 오류 전부 500, FRONT §4.1 indexed_at 은 실제 epoch float, §4.2 source "label" 없음(field|slot),
  §4.6 라우트별 추가 필드, /chat/prefill/stream error 프레임 없음. 세 단위 모두 RequestValidationError 핸들러 없음 → 기본 422 {detail}.
- [x] **(세션 3 사용자 제보) "워크플로우 마지막 result 가 프론트에 전혀 안 간다" 수정** — 원인: 마지막 스텝 4개가 token 은
  `sio_server.emit` 으로 보내면서 result 는 `yield` 만 했다. 가이드 §D.1: yield 한 result.data 는 **다음 step 의 data** 일 뿐 소켓으로
  안 간다. → 각 스텝에 `emit_result()` 추가(소켓 "result" 로 보내되 genos_state 제외 + 같은 값 yield). check_workflow_run 에
  소켓 대역 점검 4건(`_check_result_reaches_socket`) → EXPECTED 124→128. **실환경 확인 필요**: 프론트가 소켓 "result" 이벤트를 듣는지.
- [x] API 번역 초안 완료 (scratchpad api/translate.md, 13라우트).
- [x] **result 경로 최종 (세션 3)** — 인프라 답변: workflow 컨테이너 `flowise_adapter.py` 가 허용 목록 밖 이벤트(result·metadata·end 포함)를 버린다.
  사용자가 adapter·프론트에 `pythonstep_result` 를 등록해 둠. 소켓 emit·emit_result 는 전부 걷고, 마지막 스텝 4개는
  **result 를 원래 그대로 두고** 바로 앞에 `yield {"event": "pythonstep_result", "data": result_data - genos_state}` 한 줄(정상·오류 경로 둘 다).
  check_workflow_run `_check_pythonstep_result`(오류 경로만 탐). FRONT.md §1.1 갱신. agentFlowExecutedData(B안)는 사용자 실환경에서 실패.
- [x] **open_ai 판 전부 삭제** — final/*/open_ai 4개 + 문서·paths.open_ai_dir 참조 제거.
  대상: final/*/open_ai/ 4개, 참조 문서(CLAUDE.md:19, final/README.md 189~446, ONPREM.md:15, DESIGN_NOTES 1317, 006 CLAUDE.md:253,
  polish requirements.txt:18, Test/onprem README·_harness 주석), Test/check/paths.py open_ai_dir(미사용).

## 사용자 결정이 필요한 것 (동작 변경이라 손대지 않음)
1. **보안**: FAQ `/faqs` 토큰 검사가 `x_admin_token and ...` → 헤더를 비우면 `FAQ_ADMIN_TOKEN` 이 있어도 통과 (faq/main.py:515).
2. FAQ `/prompts/reload` 403 이 ERR_API_INPUT + 하드코딩 문구 (ERR_API_ADMIN_FORBIDDEN 미사용).
3. `check_deploy_contract` 가 기동 블록 **위치**도 보게 할지 (두 단위에서 실제 결함이었음, EXPECTED 갱신 필요).
4. 번역 프롬프트에 언어명이 영문("English(으)로만"), register_instruction 이 영어 문장 — "프롬프트 전부 한국어" 규칙과 어긋남.
5. 번역 `/translate/stream` 내부 오류 프레임의 error_code 가 ERR_INPUT.
6. **첨부용 전처리기 미확정** — only_me.py 는 지워졌는데 ONPREM/SERVING_REGISTRY/final/CLAUDE.md/DESIGN_NOTES 가 등록 단위로 적음.
7. 다듬-1 `tone_overridden`·`tone_notice` 가 다듬-2 result payload 에 안 실려 강제 톤 안내가 화면에 안 나감.
8. 006 `ERR_CHAT_NO_FIELDS` 사용자 문구가 "누름틀"(기본은 슬롯).

## 문서 쪽 낡은 곳 (담당 밖이라 남김)
- final/CLAUDE.md·루트 CLAUDE.md: hwpx 코어 "5벌(MCP 포함)" — MCP hwpx 도구는 이미 없음. FAQ 절 등 날짜 이력.
- preprocessor/__init__.py 의 only_me/onprem 안내, preprocessor/CLAUDE.md 건수 155/33(실제 153/31).
- Test/check 머리말의 onprem 경로 (Test 는 이번 범위 밖).
