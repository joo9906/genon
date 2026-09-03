# WORK — 어떤 파일부터 쓰나 (폐쇄망 작성 순서)

> **이 문서는 손을 움직이는 순서만 담는다.** 무엇을 등록하는지는
> [`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md), 환경변수·운영 규약의 정본은
> [`README.md`](README.md), 지금 무엇이 막혀 있는지는 [`HANDOFF.md`](HANDOFF.md) 다.
> 여기서 같은 사실을 반복하지 않고 **차례와 그 차례인 이유**만 적는다.
>
> 작성 대상 총량: **파일 116개 / 33,284줄** — 코드서빙 86(빈 `__init__.py` 포함) +
> MCP 4 + 워크플로우 9 + 전처리기 **1** + 프롬프트 12, 여기에 `requirements.txt` 4개.
> **전처리기는 `final_preprocessor.py` 하나뿐이다**(5,958줄) — 2026-09-03 부터 조각을
> 합쳐 만들던 방식과 hwpx 단독 판본이 없어졌다. **다만 통째로 치지는 않는다** — PART 1
> 벤더 절반(2,587줄)은 이미 폐쇄망에 있어 **1줄만 고치고**, 실제로 치는 것은
> **PART 2·3 = 3,251줄**이다 (§6).
> (2026-09-03 재계수. 112 → 116 은 **`prompt_library.py` 사본 4벌**.)
>
> **아래 줄 수는 전부 `wc -l` 값이다** — 옮겨 적은 파일이 여기 적힌 줄 수와 크게 다르면
> 빠뜨린 것이 있다는 뜻이라 **이 숫자가 그 자체로 점검**이다. 그래서 코드를 고치면 여기도
> 같이 고친다. 확인은 아래 한 줄이면 된다.
>
> ```bash
> wc -l onprem/mcp/*.py onprem/workflow/*.py onprem/preprocessor/final_preprocessor.py \
>       onprem/prompt/*/*.j2
> find onprem/codeserving/<단위> -name '*.py' -not -path '*__pycache__*' | xargs wc -l
> ```
>
> **표가 코드보다 늦는 일이 반복됐다.** 2026-08-27 에 한 번 맞췄는데 08-28·29 작업이
> 또 코드만 커밋됐다 — 2026-08-31 재계수에서 **신규 파일 여섯이 이 문서에 통째로 없었고**
> (`file_store.py`·`chunking.py`·`polisher.py`) 줄 수는 스물여섯 자리가 어긋나 있었다.
> 가장 크게 벌어진 넷: 번역 `glossary_exact` 324→414 · FAQ `generator` 316→444 ·
> 워크플로우 `polish_02` 487→532 · MCP `genon_glossary` 850→925.
> **없는 파일은 "빠뜨렸다" 로도 안 드러난다** — 목록에 없으니 찾지도 않는다.

---

## 최근 변경 — **이미 옮겨 적은 뒤라면 여기만 다시 본다**

아래는 전부 **리비전 갱신**이다 — 등록 단위 수도 시작 커맨드도 안 바뀌었다.
처음 옮기는 것이라면 이 절을 건너뛰고 §0 부터 읽으면 된다. 신규 파일은 §3 의 단위별
목록에 이미 들어가 있다.

| 날짜 | 무엇 | 다시 옮길 것 |
|---|---|---|
| **09-03** | **프롬프트를 라이브러리에서 받는다** (네 단위) | 신규 `prompt_library.py` **4벌** + 수정 12 |
| **09-03** | 톤 **4종** · 문서유형 **5종** 으로 갈아 끼움 | 코드서빙 1 + MCP 1 + eval 1 + 프롬프트 1 |
| **09-03** | FAQ 개수가 **총 개수**로 돌아왔다 (08-31 뒤집음) | FAQ 4 + 워크플로우 2 |
| **09-03** | hwpx 레코드에 **페이지 필드**를 채운다 | 5단계만 (§6) |
| **09-02** | 006 자동 채움을 **대화 중간에도·파일 여러 번** | 코드서빙 5 + 워크플로우 2 (아래) |
| **09-03** | 전처리기 **정본이 `final_preprocessor.py` 하나**가 됐다 (빌드 제거) | 5단계만 (§6). 코드서빙·MCP 무관 |
| **09-01** | 이관 방식이 바뀌었다 — 주석 걷어낸 판본을 쳤다 (**09-03 에 되돌림**) | 5단계만 (§6) |
| **09-01** | 결과 **토큰 스트리밍 되살림** | 워크플로우 3 (`polish_02`·`translate_02`·`sfr006_03`) |
| **08-31** | 006 **업로드 문서 자동 채움** | 신규 3 (`doc_prefill.py` + `.j2` 둘) + 다시 옮길 6 |
| **08-31** | FAQ 개수가 **구간당**이 됐다 | FAQ 4 + 워크플로우 1 |
| **08-31** | 전처리기 **등록 단위가 둘**이 됐다 | 5단계만 — 올릴 파일을 고른다 (§6) |
| **08-30 / 08-29** | 긴 문서 커버·안내문·번역 문맥 | 신규 3 + 다시 옮길 6 |
| **08-28** | 양쪽 하이라이트·**내려받기 링크** | 신규 `file_store.py` **3벌** |
| **08-27** | 변경·용어 표시를 본문 하이라이트로 | 6개 파일 (순서 있음) |

> **08-26 판본을 갖고 있다면 위 열세 줄이 전부 자기 일이다** — 그 시점 이후로 배포
> 단위 파일 **65개**가 움직였다 (신규 13 · 수정 52). 어느 파일의 **어느 함수**를 다시
> 쓰는지는 바로 아래 §−1 이 함수 이름까지 적어 둔 유일한 자리다.

---

## −1. **08-26 판본 → 지금** 함수 단위 대조표

> **읽는 법**: `+` 새로 쓴다 · `~` 이미 있는 것을 고쳐 쓴다 · `−` 지운다.
> 파일을 통째로 다시 치는 것이 언제나 안전하지만, **`~` 표시된 함수만 갈아 끼워도
> 된다** — 여기 이름이 없는 함수는 08-26 이후 한 글자도 안 바뀌었다.
>
> 기준은 커밋 `178fb44`(2026-08-26)이고 목록은 **AST 대조로 뽑았다** — 주석·독스트링만
> 바뀐 함수는 들어 있지 않다. 그래서 **줄 수는 달라졌는데 목록에 없는 파일**
> (`tone_presets.py` · `genon_lang_policy.py` · `sfr018_faq_01_source.py`)은 주석만
> 바뀐 것이라 **안 쳐도 동작이 같다.**
>
> **순서는 §1 그대로다** — MCP → 코드서빙 → 프롬프트 → 워크플로우 → 전처리기.
> 뒤엣것이 앞엣것의 새 응답 키를 읽으므로 뒤집으면 **오류 없이 값만 비는** 상태가 된다.

### −1-1. MCP (1단계) — 2파일

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `mcp/genon_text_guard.py` | 584 → **826** | **+** `_TGWORD_RE` · `_TGHTML_TAG_RE` · `_TGMARK_OPEN` · `_TGMARK_CLOSE` · `_TGwords` · `_TGword_changes` · `_TGspan` · `_TGchange` · `_TGprotected_regions` · `_TGsplit_units_with_spans` · `tgbuild_highlighted`<br>**~** `TGChangeItem` · `tgbuild_change_list` · `_TGdiff_changes` · `diff_changes`<br>**−** `_TGsplit_units` · `_TGMAX_EVIDENCE_ITEMS` |
| `mcp/genon_glossary.py` | 850 → **925** | **+** `_GLHANGUL_WORD_RE` · `_GLKO_PARTICLES` · `glstrip_ko_particle` · `_GLtoken_eq`<br>**~** `glexact_match` |

`genon_hwpx_text.py`(1,171) 는 **안 건드린다.**

**`genon_lang_policy.py` 는 2026-09-03 에 바뀌었다** — 톤 4종·문서유형 5종 표와
`LPLEGACY_TONE_ALIASES`·`lpcanonical_tone`. 글다듬이 `tone_presets.py` 와 **같은
내용이어야 한다**(`check_tone_policy` 가 대조한다) — 한쪽만 고치면 같은 옛 톤 코드가
경로에 따라 다른 톤이 되고, 오류는 나지 않는다.

> `_TGsplit_units` → `_TGsplit_units_with_spans` 는 **반환형이 바뀐 개명**이다
> (`str` → `(텍스트, start, end)`). 옛 이름을 남겨 두면 호출부가 조용히 옛 것을 부르고
> **좌표가 통째로 비는데 오류는 나지 않는다** — 지우는 것까지가 계약이다.

### −1-2. 코드서빙 (2단계)

**글다듬이 — 신규 3 / 수정 3**

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `text_polish/file_store.py` | **신규 125** | 결과 txt 를 CDN 에 올린다 |
| `text_polish/chunking.py` | **신규 200** | 조각 분해 + 원문 복원 (꼬리 공백을 따로 든다) |
| `text_polish/polisher.py` | **신규 126** | 조각을 함께 돌리고 실패를 조각으로 센다 |
| `text_polish/config.py` | 90 → **103** | **+** `MAX_CHUNK_CHARS` · `LLM_CONCURRENCY` |
| `text_polish/txt_output.py` | 153 → **162** | **+** `download_filename` |
| `main.py` | 297 → **323** | **+** `PolishRequest.title` · **~** `polish` (→ `polisher.polish_document` 를 부른다) |

**번역 — 신규 1 / 수정 10**

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `common/file_store.py` | **신규 125** | 글다듬이 것과 같은 사본 |
| `common/glossary_exact.py` | 324 → **414** | **+** `_HANGUL_WORD_RE` · `_KO_PARTICLES` · `strip_ko_particle` · `_token_eq`<br>**~** `_normalize_en` · `match_occurrences` · `contains_phrase` · `phrase_positions` |
| `common/prompt_builder.py` | 69 → **91** | **~** `build_batch_prompts` · `build_single_prompts` (절 제목 `c` 를 싣는다) |
| `common/txt_output.py` | 153 → **162** | **+** `download_filename` |
| `office/glossary_report.py` | 234 → **285** | **+** `highlight_sources` · `highlight_units`<br>**~** `highlight_translations` · `_OPEN_TAG`/`_CLOSE_TAG` 값 (`<strong>` → `<mark>`) |
| `office/markdown_units.py` | 233 → **242** | **~** `_Builder.__init__` · `_Builder._add_unit` · `_split_markdown_lines` (유닛에 절 제목을 단다) |
| `office/translation_modes.py` | 317 → **325** | **~** `_translate_batch` · `_translate_single` |
| `office/pipeline.py` | 234 → **241** | **~** `run_markdown_translation_job` |
| `office/types.py` | 114 → **118** | **+** `MarkdownTranslationArtifacts.source_markdown_highlighted` |
| `api_contract.py` | 177 → **188** | **+** `TranslateMarkdownRequest.title` · **~** `markdown_payload` |
| `main.py` | 384 → **413** | **+** `_upload_result` · **~** `translate_markdown` · `translate_hwpx` |

**FAQ — 신규 2 / 수정 5**

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `faq/file_store.py` | **신규 125** | 같은 사본 |
| `faq/chunking.py` | **신규 148** | 조각 분할 + 개수 배분 (`plan_quota`) |
| `faq/config.py` | 85 → **111** | **+** `MAX_CONTEXT_CHUNKS` · `MAX_TOTAL_FAQ_COUNT` |
| `faq/generator.py` | 316 → **489** | **+** `_generate_from_chunk` · `_fill_shortfall` · `resolve_per_chunk_count` · `resolve_total_cap` · `FaqResult` 필드 6 (`chunks_planned` · `chunks_used` · `coverage_capped` · `per_chunk_count` · `source_chunks` · `total_cap`)<br>**~** `generate_faqs` · `resolve_max_count` · `FaqResult.as_payload`<br>**−** `resolve_count` · `_MAX_SHORTFALL_RETRY` |
| `faq/formatting.py` | 145 → **154** | **~** `build_notice` |
| `faq/txt_output.py` | 153 → **162** | **+** `download_filename` |
| `faq/main.py` | 323 → **340** | **~** `_generate_and_store` · `service_config` |

**006 — 신규 1 / 수정 6**

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `template_fill/doc_prefill.py` | **신규 242** | 업로드 문서로 빈 항목을 채운다 |
| `template_fill/config.py` | 122 → **138** | **+** `DOC_PREFILL` · `DOC_CHUNK_CHARS` · `DOC_MAX_CHUNKS` |
| `template_fill/prompts.py` | 90 → **128** | **+** `build_document_prompts` |
| `template_fill/chat_api.py` | 353 → **508** | **+** `PrefillRequest` · `_doc_hash` · `_prefill_skipped` · `CommitRequest` 필드 3 (`fields_prefilled` · `prefill_failed` · `source_doc_hash`)<br>**~** `install` (→ `POST /chat/prefill` 등록) · `_load_turn` |
| `template_fill/chat_reply.py` | 142 → **180** | **+** `_prefill_notices` · **~** `compose_status_reply` · `_change_notices` |
| `template_fill/session_store.py` | 221 → **230** | **~** `save_session` · `load_session` (`source_doc_hash` 표식) |
| `template_fill/hwpx_style.py` | 549 → **548** | **−** `_STYLE_WORDS` (죽은 상수) |

**006 — 대화 중간 업로드 (2026-09-02) · 수정 7**

위 표를 이미 옮겨 적었더라도 **이 일곱은 다시 쓴다.** 표식이 문자열 → 목록이 되면서
저장·읽기·병합이 함께 움직였다 — 하나만 옛 판본으로 남으면 **오류 없이 표식만 새고**,
증상은 "지운 값이 다음 턴에 되살아난다" 로만 나타난다.

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `template_fill/session_store.py` | 230 → **275** | **+** `normalize_doc_hashes` · `_MAX_DOC_HASHES`<br>**~** `save_session`(`source_doc_hashes=`) · `load_session`(옛 문자열 흡수) · `_STATE_VERSION` 2→**3** |
| `template_fill/chat_api.py` | 508 → **551** | **+** `_merged_doc_hashes` · `CommitRequest.prefill_skipped_reason`<br>**~** `chat_prefill`(게이트 교체) · `chat_commit`(누적 저장) · `_prefill_skipped` |
| `template_fill/session_view.py` | 237 → **245** | **~** `EditingContext`(표식을 들고 다닌다) · `load_context` · `save_state` — **기존 결함 수정** |
| `template_fill/doc_prefill.py` | 242 → **253** | **~** `_pending_specs`(`missing_field_names` 로 판정 일원화) |
| `template_fill/chat_reply.py` | 180 → **196** | **~** `_prefill_notices`(`no_pending_fields` 한 줄) · `compose_status_reply` |
| `workflow/sfr006_01_context.py` | 447 → **455** | **~** `run` (건너뛴 사유를 흘린다) |
| `workflow/sfr006_03_commit.py` | 381 → **384** | **~** `run` (커밋에 사유를 넘긴다) |

**순서는 `session_store` 를 먼저** — 나머지가 `normalize_doc_hashes` 를 부른다.

### −1-3. 프롬프트 (3단계) — 신규 2 / 수정 3

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `SFR-006_template_fill/document_system.j2` | **신규 58** | 자동 채움 지시문 |
| `SFR-006_template_fill/document_user.j2` | **신규 23** | 조각 + 남은 항목 |
| `SFR-018_translation/system_batch.j2` | 47 → **58** | CONTEXT 규칙 (`c` 는 번역·출력 금지) |
| `SFR-018_translation/system_single.j2` | 33 → **37** | 같은 규칙 (폴백에도 싣는다) |
| `SFR-018_translation/user_single.j2` | 5 → **11** | 문맥 줄 |

> **`system_single.j2` · `user_single.j2` 를 빠뜨리기 쉽다.** 배치가 성공하는 동안에는
> 아무 일도 안 일어나고 **배치가 실패한 유닛만 문맥 없이 번역된다** — 그 차이는 결과물
> 두 벌을 나란히 놓고 봐야 보인다.

### −1-4. 워크플로우 (4단계) — 5파일

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `sfr018_polish_02_polish.py` | 458 → **579** | **+** `_STREAM_MAX_EMITS` · **~** `run` · `_stream_chunks` · **−** `_format_changes` |
| `sfr018_translate_02_translate.py` | 499 → **585** | **+** `_STREAM_MAX_EMITS` · **~** `run` · `_stream_chunks` |
| `sfr018_faq_02_generate.py` | 381 → **445** | **~** `run` · **−** `_stream_chunks` · `_STREAM_CHUNK_CHARS` (FAQ 는 안 흘린다) |
| `sfr006_01_context.py` | 347 → **447** | **+** `_DOC_TAG_RE` · `_uploaded_markdown` · **~** `run` (→ `POST /chat/prefill` 을 이어 부른다) |
| `sfr006_03_commit.py` | 331 → **381** | **+** `_STREAM_MAX_EMITS` · **~** `run` · `_stream_chunks` |

`sfr018_faq_01_source.py`(436) 는 주석만 바뀌었다 — **안 쳐도 된다.**

> **`_stream_chunks` 가 3벌인데 셋 다 고친다.** 조각 상한(`_STREAM_MAX_EMITS` 400)을
> 018 둘에만 넣으면 006 만 20만 자에서 emit 6,250회가 된다. 006 은 답변이 짧아
> **동작이 안 바뀌므로 빠뜨려도 티가 안 난다** — 그래서 사본 일치 점검이 잡는다.

### −1-5. 전처리기 (5단계)

`final_preprocessor.py` PART 2 (옛 `hwpx_preprocessor.py`) 2,123 → **2,360**.
**+** `Block.origin` · `Chunk.origin` · `_extend_origin` · `_emit_log` · `_log_info` ·
`_log_warning` · `_debug_dump` · `_DEBUG_TAG` · `_DEBUG_DUMP_CHARS` ·
**`_RECORD_TYPES` · `_check_record_types`**(2026-09-02 — 아래 주)
**~** `annotate_outline` · `chunk_blocks` · `_table_chunks` · `_merge_tiny` ·
`_drop_heading_only_chunks` · `_int_kwarg` · `_Markers.__init__` ·
`_Markers._report_once` · `DocumentProcessor.__call__` · `_ALLOWED_LOG_FIELDS`

**이 목록은 `final_preprocessor.py` PART 2 안의 이름이다** — 치는 법은 §6.

> **2026-09-02 — 레코드 타입 계약을 넣었다.** Weaviate 는 프로퍼티 타입을 **처음 본
> 값으로 굳히므로**, 같은 키가 문서마다 다른 타입으로 나가면 나중 문서가 통째로 거절된다
> (`not a string, but float64` — Go 가 JSON 숫자를 전부 `float64` 로 읽는다). 그런데
> **그 메시지에는 어느 레코드의 어느 키인지가 없다.** `_check_record_types` 가 내보내기
> 전에 우리 필드를 계약과 대조해 **키 이름을 말하고 세우고**, `extra_metadata` 로 들어온
> 값이 문자열이 아니면 **키 이름과 타입 이름을 로그로** 낸다(값은 안 남긴다 — §3.8).
> 후자를 세우지 않는 이유는 이 모듈의 규약 그대로다 — 등록 화면 입력 실수가 재적재
> 전체를 막으면 안 된다.

---

### 2026-09-03 — 프롬프트를 **라이브러리에서 받는다** (네 단위)

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** "프롬프트를 라이브러리에서 받는다" 절과
> [`prompt/README.md`](prompt/README.md).

톤·문서유형 **목록**은 08-18 부터 라이브러리에서 받고 있었다. 이제 **프롬프트 문장
자체**도 그쪽에서 받는다 — 코드 PR 로 프롬프트를 바꾸는 것이 가이드 §10.5 금지사항이다.

**덮어쓰기지 이사가 아니다.** `.j2` 는 기본값이자 폴백으로 남고, ID 를 준 이름만
라이브러리가 이긴다. **프롬프트 12파일은 그대로 옮긴다**(3단계 변동 없음).

**신규 4 — 네 단위에 같은 사본** (본문까지 같아야 한다):

| 파일 | 줄 |
|---|---|
| `template_fill/prompt_library.py` | **신규 205** |
| `text_polish/prompt_library.py` | **신규 204** |
| `common/prompt_library.py` (번역) | **신규 204** |
| `faq/prompt_library.py` | **신규 204** |

**다시 옮길 12** — 단위마다 셋씩:

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `template_fill/prompt_loader.py` | 99 → **140** | **+** `_render_source` · **~** `render`(라이브러리 분기) |
| `template_fill/config.py` | 138 → **158** | **+** `genos_admin_api_url` · `prompt_ids_raw` · `PROMPT_FETCH_TIMEOUT` |
| `template_fill/main.py` | 551 → **575** | **+** `GET /prompts` · `POST /prompts/reload` |
| `text_polish/prompt_loader.py` | 94 → **129** | 위와 같다 |
| `text_polish/config.py` | 103 → **118** | `GENOS_ADMIN_API_URL` 은 이미 있었다 (정책용) |
| `main.py` (글다듬이) | 323 → **363** | 두 라우트. **인증 없음** — 이 단위는 관리자 토큰이 없다 |
| `common/prompt_loader.py` (번역) | 109 → **144** | 위와 같다 |
| `config.py` (번역) | 117 → **136** | |
| `main.py` (번역) | 399 → **441** | 두 라우트 (`X-Admin-Token`) |
| `faq/prompt_loader.py` | 93 → **128** | 위와 같다 |
| `faq/config.py` | 96 → **137** | FAQ 개수 규약(아래)과 **같은 파일**이라 한 번만 친다 |
| `faq/main.py` | 333 → **367** | 두 라우트 (`X-Admin-Token`) |

**새 환경변수 — 전부 안 넣어도 뜬다** (안 넣으면 `.j2` 그대로):

```
GENOS_ADMIN_API_URL          네 단위 공통 (글다듬이·MCP 는 정책용으로 이미 쓰던 값)
TEMPLATE_FILL_PROMPT_IDS     extract_user=41,document_user=42   (JSON 표기도 받는다)
POLISH_PROMPT_IDS            system=43
TRANSLATE_PROMPT_IDS         system_batch=44,user_batch=45
FAQ_PROMPT_IDS               system=46,user=47
<단위>_PROMPT_TIMEOUT         기본 5초
```

- **이름은 파일 이름에서 확장자를 뗀 것**이다(`extract_user.j2` → `extract_user`).
  다르게 적으면 그 이름만 **조용히 옛 문구로 돈다** — `GET /prompts` 의 `source` 로만 보인다.
- **세 갈래가 전부 파일로 떨어진다**: 미설정 · 조회 실패 · **본문 렌더 실패**(관리자가
  변수 이름을 틀리면 `StrictUndefined` 가 죽는다). **파일도 없을 때만** 요청을 세운다.
- **`GET /prompts` 는 본문을 싣지 않는다**(§3.8). 이름·`source`·`reason` 만.

**확인**: `check_api_contract` 46 → **50건** · `check_unit_endpoints` 83 → **89건** ·
`check_deploy_contract` OK 63 → **64** · SFR-006 unittest 54 → **64건**.

---

### 2026-09-03 — 톤 **4종** · 문서유형 **5종**

> 정본은 루트 [`CLAUDE.md`](../CLAUDE.md) "톤 4종·문서유형 5종으로 갈아 끼웠다".

| | 그전 | 지금 |
|---|---|---|
| 톤 | 정중함 · 친절함 · 간결 및 보고체(개조식) | **격식·정중**(`polite`) · **친절·안내**(`friendly`) · **명확·간결**(`clear`) · **사실·객관**(`objective`) |
| 자유 선택군 | 메일 · 게시글 · 보도자료 · 공문 | 메일 · 게시글 · **고객발송문구** |
| 톤 고정군 | 채무 사유 · 심사역 의견 · 재산 의견 · 고객발송문구 | 채무 사유 · 심사역 의견 — **둘 다 `objective` 고정** |

**다시 옮길 4**:

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `text_polish/tone_presets.py` | 256 → **330** | **+** `LEGACY_TONE_ALIASES` · `canonical_tone` · **~** `TONE_PRESETS` · `DOC_TYPE_POLICIES` · `resolve_tone` · `resolve_policy` |
| `mcp/genon_lang_policy.py` | 1,153 → **1,165** | 같은 표의 `LP` 접두어 사본 + `lpcanonical_tone` |
| `eval/eval_mcp/tone_metrics.py` | → **305** | `TONE_RULES` 4종 · `FORCED_TONE_SNAPSHOT` |
| `prompt/SFR-018_text_polish/system.j2` | → **49** | 주석 예시만. **목록은 여기 적지 않는다** |

- **옛 톤 코드를 별칭으로 받는다** (`report` → `clear`). 없으면 캔버스에 남은 `report`
  가 "모르는 톤" 이 되어 **조용히 기본 톤으로** 떨어진다. **별칭표가 2벌**이라 한쪽만
  고치면 같은 옛 값이 경로에 따라 다른 톤이 된다.
- **없어진 문서유형에는 별칭을 두지 않았다** — 어느 유형으로 옮길지가 자명하지 않다.
  보도자료·공문·재산 의견은 기존 규약대로 기본값(메일)으로 떨어진다.
- **eval 은 배포 단위를 import 하지 않는다** — 관리자가 톤을 추가하면 그쪽은
  `skipped` 로 드러난다(통과로 세지 않는다).

**확인**: `check_tone_policy` 22 → **24건** · `check_eval_metrics` 80 → **81건**.

---

### 2026-09-03 — FAQ 개수가 다시 **총 개수** (08-31 을 뒤집는다)

> 정본은 루트 [`CLAUDE.md`](../CLAUDE.md) "긴 문서에서 뒷부분이 통째로 빠지고 있었다"
> 절의 09-03 요구 확정분.

**사용자는 총 개수만 고르고 배분은 우리가 한다.** 고른 숫자가 곧 받는 개수다 —
08-31 판(구간당 개수)은 **고른 숫자와 받는 개수가 달라졌다**(구간이 여섯이면 5를 골라도
30개). 그 규약이 막으려던 것(긴 문서에서 조각당 몫이 0 에 가까워지는 것)은 이제
**호출 수 상한**이 막는다 — 태울 구간 수가 묶여 있어 몫이 1 밑으로 안 내려간다.

**다시 옮길 7**:

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `faq/chunking.py` | 129 → **152** | **~** `plan_quota`(총 개수 + 호출 수 상한으로 배분, 구간을 **고르게 표집**) |
| `faq/config.py` | 96 → **137** | **+** `MAX_CHUNK_CALLS`(기본 6) · **~** `MAX_FAQ_COUNT` 기본 10 → **30** · **−** `MAX_TOTAL_FAQ_COUNT` |
| `faq/generator.py` | 444 → **486** | **+** `resolve_count` · `resolve_call_cap` · **−** `resolve_per_chunk_count` · `resolve_total_cap` |
| `faq/formatting.py` | 145 → **153** | 안내문 문구 |
| `faq/main.py` | 333 → **367** | `/config` 에서 `total_max_count` 를 뺀다 |
| `workflow/sfr018_faq_01_source.py` | → **437** | 안내문·로그 |
| `workflow/sfr018_faq_02_generate.py` | → **469** | 안내문·로그(`asked=`) |

- **`FaqResult` 필드가 바뀐다**: `per_chunk_count`·`total_cap` 이 없어지고 **`call_cap`**
  이 생긴다. `requested_count` 는 **사용자 선택 그대로**다(08-31 의 "배정된 몫의 합" 보정은
  필요 없어졌다).
- **옛 환경변수 `FAQ_MAX_TOTAL_COUNT` 는 없앤다** — 언제나 안 걸리는 상한은 읽는 쪽이
  "확인했다" 고 믿게 만든다. 새 손잡이는 **`FAQ_MAX_CHUNK_CALLS`**(기본 6)다.
  **개수는 사용자가, 비용은 배포가** 정한다.
- 상한에 걸려 못 태운 구간은 그대로 `coverage_capped` 로 알린다.

**확인**: `check_unit_endpoints` 81 → **83건** · SFR-018 unittest 298 → **300건**.

---

### 2026-09-03 — hwpx 레코드에 **페이지 필드**를 채운다 (5단계만)

hwpx 로 적재한 문서가 **GenOS 적재 결과 화면에 안 떴다.** 화면은 청크를 페이지로 묶어
그리는데 이 경로가 페이지 다섯 필드와 `chunk_bboxes`·`media_files` 를 전부 `None` 로
뒀기 때문이다 — **오류가 아니라 빈 목록**이라 로그 어디에도 안 남는다.

**페이지 자리에 구역(section)을 넣는다.** 지어내는 것과 다른 이유는 **`page_basis`** 다 —
값의 출처를 레코드가 말하므로 나중에 "페이지 수가 실물과 다르다" 를 추적할 수 있다.

| 파일 | 무엇을 |
|---|---|
| `preprocessor/final_preprocessor.py` PART 2 | **+** `_page_fields` · `_PAGE_BASIS_SECTION` · **~** `to_records` · `_RECORD_TYPES` |

- 기준을 벤더와 맞춘다 — `i_page` 는 **1-based**, `i_chunk_on_page` 는 **0-based**.
- 빈 값도 벤더가 쓰는 것을 쓴다 — `chunk_bboxes="[]"` · `media_files=""`.
  `None` 은 벤더가 절대 내지 않는 값이라 화면이 그 필드를 읽다 멈춘다.
- **되돌릴 자리는 `_page_fields` 하나**다. `i_section`/`n_section` 은 그대로라 이 매핑이
  사라져도 구역 정보는 안 잃는다.
- **미검증**: 실제 화면에 뜨는지는 폐쇄망에서 확인해야 한다. 화면이 페이지가 아니라
  **원본 미리보기(PDF 렌더)** 를 요구하는 것이면 이 값으로는 해결되지 않는다.

**고친 뒤 생성물 셋을 다시 만든다** (§6) — 안 하면 **옛 코드를 타이핑하게 된다.**

**확인**: `check_final_preprocessor` **155건** 통과(실물 5벌 레코드 대조 포함) ·
SFR-018 unittest `VectorRecordTest` 2건.

---

### 2026-09-03 — 전처리기 **정본이 한 파일**이 됐다 (빌드 제거)

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** "이관은 파일이 아니라 사람이 건넌다" 절과
> [`preprocessor/README.md`](preprocessor/README.md) 최상단.
>
> **5단계만 바뀐다.** 코드서빙·MCP·워크플로우는 하나도 안 건드린다.

**`final_preprocessor.py` 를 화면에 띄워 놓고 친다.** 그전에는 조각 셋
(`hwpx_preprocessor.py`·`router_template.py`·벤더 사본)을 빌드가 합쳐 생성물을 만들고,
따로 주석·docstring 을 걷어낸 타이핑 판본(`transfer/`)을 뽑았다. **보는 파일과 치는
파일이 달랐던 것**이고, 정본을 고치고 키트 재생성을 빼먹으면 **옛 코드를 타이핑하게
되는데 치는 순간에는 맞아 보였다.**

**벤더 절반은 이미 폐쇄망에 있다.** 첨부용 전처리기가 등록돼 있으므로 에어갭을 건너는
것은 **PART 2·3 뿐**이다.

| 조각 | 이 파일의 줄 | 실제로 치는 양 |
|---|---|---|
| PART 1 첨부용 (벤더) | 2,587 | **1줄 수정** (`class DocumentProcessor:` → `AttachDocumentProcessor`) |
| PART 2 hwpx 파서 | 2,360 | 2,360 |
| PART 3 라우터 | 891 | 891 |
| | **5,958** | **3,251 + 벤더 1줄** |

- **주석·docstring 을 걷어내지 않는다.** 분량은 1,764 → 3,251 로 늘었지만, 보는 것과
  치는 것이 같은 파일이다. 오타 검출 해시표(`40_expect.txt`)도 함께 없어졌다 —
  다시 필요해지면 `git show HEAD:onprem/preprocessor/build_transfer_kit.py`.
- **가드 한 자리가 외부 판본과 다르다.** 저장소의 이 파일은 PART 1 을 `try:` 안에
  넣지만 그건 우리 사정이다(로컬에 docling 이 없어도 점검이 돌아야 한다). 온프레미스
  에서는 `_FP_ATTACH_IMPORT_ERROR = None` / `_FP_ATTACH_IMPORT_TRACE = ""` 두 줄이 그
  자리를 메운다.
- **등록은 한 번이고 갈리는 것은 받을 확장자다.** `hwpx` 만 걸면 나머지는 사이트의 기존
  첨부용 등록이 맡는다 — PART 1 이 안 뜨는 설치본에서도 안전하다(가드가
  `except Exception` 이고 PART 2·3 은 가드 밖이다).
- **없어진 그물 하나를 알고 있을 것** — "생성물이 원본 셋과 같은가"(AST 대조).
  `check_final_preprocessor` 168 → **155건**. 그 판정이 2026-09-03 에 벤더 참조 사본의
  오타(`split_docuㄱments`)를 실제로 잡은 적이 있으므로 **PART 1 은 되도록 손대지 않고**,
  고쳐야 하면 `genos_files/attach_processor.py` 와 눈으로 대조한다.

---

### 2026-09-01 — 결과 **토큰 스트리밍 되살림**

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** "결과는 흘리고, 하이라이트는 끝나고
> 갈아 끼운다" 절.
>
> **워크플로우 3파일만이다.** 코드서빙·MCP·프롬프트는 안 바뀐다.

08-28 에 없앴던 토큰 스트리밍을 **번역·글다듬이 둘에 되살렸다** — 그때 적은 근거
("전용 UI 가 한 번에 그린다")는 화면이 **완성된 뒤**를 말한 것이고, 그 전 수십 초 동안
화면이 비어 있다는 사실은 다루지 않았다. **FAQ 는 그대로 안 흘린다**(산출물이 흐르는
글이 아니라 문답 목록이다).

| 파일 | 무엇 |
|---|---|
| `sfr018_polish_02_polish.py` (→579) | `_stream_chunks` 되살림 + `_STREAM_MAX_EMITS` |
| `sfr018_translate_02_translate.py` (→585) | 같음 |
| `sfr006_03_commit.py` (→381) | 원래 흘리고 있었다 — **`_STREAM_MAX_EMITS` 만** 더한다 |
| `sfr018_faq_02_generate.py` (→445) | **죽은 `_stream_chunks` 를 지운다** |

- **흘리는 것은 정본이다.** 사본(`<mark>`)을 흘리면 하이라이트가 스트리밍 중에 이미
  나타나고, 태그가 조각 경계에서 갈려 `<ma` 같은 부스러기가 남는다. 하이라이트는
  **끝나고 갈아 끼운다.**
- **오류 경로에서는 토큰이 한 개도 나가지 않는다.** 번역은 **전량 폴백 판정까지 끝난
  뒤**에 흘린다 — 그 앞에서 흘리면 원문을 번역문인 양 뿌린 뒤 오류로 갈아엎게 되고,
  사용자에게는 **답이 나왔다가 사라지는** 것으로 보인다.
- **`_STREAM_MAX_EMITS`(400) 를 006 에도 넣는다.** 006 은 답변이 짧아 동작이 안
  바뀌지만(12,800자 미만에서는 조각이 그대로 32자) **사본 셋이 갈리면 안 된다.**

**확인**: `python onprem/test/check_workflow_run.py` — 85 → **91건**.

---

### 2026-08-31 — 006 **업로드 문서로 알아서 채운다**

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** "업로드 문서로 알아서 채운다" 절과
> [`docs/SFR-006_architecture.md`](docs/SFR-006_architecture.md).
>
> **006 한 단위 + 그 워크플로우 스텝 1 뿐이다.** 018 셋은 무관하다.
> **스텝은 3개 그대로다** — 넷으로 만들면 캔버스 등록을 다시 해야 한다.

채팅 시작 시 문서를 올리면 그 내용으로 **빈 항목을 자동으로 채운다.** 문서는 캔버스
변수 `genosUploaded`(전처리기 산출물)로 오고, 스텝 1 이 `/chat/context` 뒤에
**`POST /chat/prefill`** 을 이어 부른다.

**새로 쓰는 파일 3**

| 파일 | 줄 | 무엇 |
|---|---|---|
| `template_fill/doc_prefill.py` | 242 | 조각 분할 → LLM → 화이트리스트 |
| `prompt/SFR-006_template_fill/document_system.j2` | 58 | 지시문 |
| `prompt/SFR-006_template_fill/document_user.j2` | 23 | 조각 + 남은 항목 |

**다시 옮길 파일 6**: `chat_api.py`(→508) · `chat_reply.py`(→180) · `config.py`(→138) ·
`prompts.py`(→128) · `session_store.py`(→230) · `workflow/sfr006_01_context.py`(→447).

- **사용자 값을 절대 덮지 않는다.** 두 층으로 막는다 — 프롬프트에서 채워진 항목을 아예
  빼고, 그래도 온 값은 버리고 `conflicts` 로 센다. **커밋에서 한 번 더** 본다.
- **같은 턴 발화가 문서를 이긴다.** 커밋이 **문서분을 먼저, 발화분을 나중에** 병합한다.
  뒤집으면 "이 문서로 채우고 제목은 A 로" 가 문서의 제목으로 되돌아간다.
- ~~**첫 턴에만 태운다.**~~ **09-02 에 뒤집혔다** (아래 §−1-2 의 006 항목). 지금 판정은
  둘이다 — **이미 태운 문서**(`source_doc_hashes` **목록** 멤버십)이거나 **빈 항목이
  없으면** 안 돈다. 표식이 같으면 안 도는 규칙은 그대로다 — 없으면 캔버스가
  매 턴 같은 문서를 실어 올 때 **사용자가 지운 값을 우리가 되살린다**(오류가 나지 않아
  제보로만 드러난다). 표식은 저장이 덮어쓰기라 **커밋이 매 턴 다시 실어야 한다.**
- **실패는 오류가 아니다** — `prefill_failed` 를 답변에 한 줄 싣는다. 조용히 넘기면
  "문서를 올렸는데 아무 일도 일어나지 않았다" 가 된다.
- **채운 값을 답변에 전부 나열한다.** 006 은 전용 UI 가 없어 **대화가 곧 화면**이고,
  그것이 사용자가 잘못된 값을 그 자리에서 고칠 수 있는 유일한 수단이다.

**새 환경변수 셋 — 전부 기본값이 있어 안 넣어도 뜬다**:
`TEMPLATE_FILL_DOC_PREFILL`(기본 1, `0` 이면 끈다) · `DOC_CHUNK_CHARS`(12,000) ·
`DOC_MAX_CHUNKS`(20).

**확인**: `check_chat_turn` 23 → **34건** · SFR-006 unittest 32 → **48건**.

---

### 2026-08-31 — FAQ 개수가 **구간당**이 됐다 (→ **09-03 에 되돌렸다**)

> ⚠ **이 절은 역사다. 09-03 에 뒤집혔다** — 사용자 선택이 다시 **총 개수**이고,
> 배분은 우리가 한다. 08-31 판을 아직 안 옮겼다면 **이 절을 건너뛰고**
> 아래 "2026-09-03 — FAQ 개수가 다시 총 개수" 절만 옮긴다.

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** "긴 문서에서 뒷부분이 통째로 빠지고
> 있었다" 절의 08-31 요구 변경분.

08-29~31 에는 사용자가 고른 개수를 **전체**로 보고 조각들이 나눠 가졌는데, 그러면
문서가 길수록 한 조각의 몫이 0 에 가까워진다 — 40조각 규정집에서 5개를 요청하면 조각당
0~1개라 **그 조각을 대표하는 FAQ 가 나올 수 없고**, 몫이 0 인 조각의 내용은 후보에서
빠진다(자르던 시절의 결함이 형태만 바꿔 남아 있었다).

지금 사용자 선택은 **구간당 개수**이고 총량은 `FAQ_MAX_TOTAL_COUNT`(기본 30 = 5 × 여섯
구간)가 잡는다.

**다시 옮길 파일 5**: `faq/chunking.py`(→148) · `faq/config.py`(→111) ·
`faq/generator.py`(→489) · `faq/formatting.py`(→154) ·
`workflow/sfr018_faq_02_generate.py`(→445).

- **`resolve_count` 가 없어지고 `resolve_per_chunk_count`·`resolve_total_cap` 둘이 됐다.**
  옛 이름을 남겨 두면 호출부가 조용히 옛 배분을 쓴다.
- **`requested_count` 의 뜻이 바뀌었다** — 사용자 선택이 아니라 **배정된 몫의 합**
  (구간당 개수 × 태운 구간 수)이다. 그대로 두면 여섯 구간 문서에서 "5개 중 28개를
  만들었습니다" 가 된다. 구간당 값은 `per_chunk_count` 로 따로 낸다.
- **총량에 걸려 못 태운 구간은 `coverage_capped` 로 알린다** — `source_truncated`
  (조각 수 상한)와 **다른 사건**이라 갈라 뒀다.

**새 환경변수 하나**: `FAQ_MAX_TOTAL_COUNT`(기본 30).

**확인**: `check_unit_endpoints` 74 → **75건** · `check_workflow_run` 84 → **85건** ·
SFR-018 unittest 290 → **298건**.

---

### 2026-08-31 — 전처리기 **등록 단위가 둘**이 됐다 (→ **09-03 에 하나가 됐다**)

> ⚠ **이 절은 역사다.** 2026-09-03 에 `final_preprocessor.py` 한 파일이 정본이 되면서
> (ㄱ)/(ㄴ) 구분과 빌드 스크립트·`transfer/` 가 전부 없어졌다. 지금 치는 법은 §6 이고,
> 아래의 **파일 이름·줄 수·건수는 그때 값**이다.

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** "등록 단위가 둘이 됐다" 절과
> [`preprocessor/README.md`](preprocessor/README.md).
>
> **코드서빙·MCP·워크플로우는 하나도 안 바뀌었다.** 5단계(전처리기)만 갈린다.

5단계에서 **올리는 파일을 고르게 됐다.** 둘 다 유효하고 **하나만** 올린다:

| 고르는 쪽 | 치는 양 | 언제 |
|---|---|---|
| (ㄱ) `preprocessor/hwpx_preprocessor.py` | 2,341 | 등록 화면에서 **확장자별로 매핑을 나눌 수 있을 때.** 더 단순하다 — 기존 첨부용은 그대로 두고 `hwpx` 만 우리 것으로 건다 |
| (ㄴ) `transfer/10_hwpx.py` + `20_router.py` | **1,764** | **한 등록이 모든 확장자를 받아야 할 때.** 벤더(첨부용) 사본을 뜨고 **1줄만 고친** 뒤 그 뒤에 이어 붙인다 |

> **(ㄴ)를 8,675줄이라고 적어 뒀던 것은 2026-09-01 에 틀린 값이 됐다.** ① 지능형을
> 걷어내 5,817줄이 됐고 ② **벤더 절반은 이미 폐쇄망에 있어 칠 필요가 없다.**
> `final_preprocessor.py`(5,900)는 **외부 검증용 생성물**이지 타이핑 대상이 아니다 —
> 온프레미스 결과물과 가드 한 자리가 일부러 다르다(위 09-01 절).

> **셋 다 생성물이라 손으로 고치지 않는다.** `build_final_preprocessor.py`(578)가
> `final_preprocessor.py` 를, `build_transfer_kit.py`(422)가 `transfer/` 를 만들고
> **AST 로 원본과 대조**한다. 폐쇄망에서 고칠 일이 생기면 `hwpx_preprocessor.py`·
> `router_template.py`(909) 를 고치고 **빌드를 둘 다 다시 돌린다** — 생성물을 직접
> 고치면 다음 빌드에 지워지고, 그 사이 원본과 갈린 상태도 **정상으로 돈다.**

**폐쇄망에 저장소를 못 두면 (ㄱ)을 고르는 편이 낫다** — (ㄴ)는 다음에 고칠 때 빌드
스크립트 둘과 라우터 조각이 이쪽에 있어야 한다.

**확인**: `python onprem/test/check_final_preprocessor.py` — **163건**.
163 이 아니면 실물 hwpx(`data/` 5벌)를 못 찾은 것이다(있는 것만 태우므로 **조용히**
142 로 준다). docling 이 반쯤 설치된 환경에서는 `벤더 부재…` 1건이 FAIL 하는데
코드 결함이 아니다.

---

### 2026-08-30 / 08-29 — 긴 문서 커버·안내문·번역 문맥

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** 의 세 절 — "긴 문서에서 뒷부분이 통째로
> 빠지고 있었다" · "미준수는 알리고, 다시 할지는 사용자가 정한다" · "가드레일이
> 검증되지 않은 채 있었다". 아래는 **옮겨 적을 때 필요한 것만** 추린 것이다.
>
> **등록 단위 수·시작 커맨드는 바뀌지 않았다** — 재등록이 아니라 리비전 갱신이다.

**새로 만드는 파일 (배포 단위 안 3개)**

| 파일 | 단위 | 무엇 |
|---|---|---|
| `codeserving/SFR-018_faq/faq/chunking.py` | FAQ | 문서를 LLM 예산 크기로 나누고 생성 개수를 배분 |
| `codeserving/SFR-018_text_polish/text_polish/chunking.py` | 글다듬이 | 조각 분해 + **원문 복원**(꼬리 공백을 따로 든다) |
| `codeserving/SFR-018_text_polish/text_polish/polisher.py` | 글다듬이 | 조각을 함께 돌리고 실패를 조각 단위로 센다 |

> **두 `chunking.py` 는 사본이 아니다.** 계약이 다르다 — FAQ 는 버리는 글자만 없으면
> 되고, 글다듬이는 **이어붙이면 원문과 문자 단위로 같아야** 한다. 맞추려 하지 말 것.

**배포 단위 밖 2개** (옮겨 적을 필요 없음 — 폐쇄망에 안 올라간다):
`eval/eval_mcp/pairs.py` · `test/check_eval_metrics.py`.

**다시 옮겨 적을 파일**

| 파일 | 왜 |
|---|---|
| `faq/generator.py` · `faq/config.py` | 조각 생성. `FAQ_MAX_CONTEXT_CHARS` 의 **뜻이 바뀌었다**(문서 상한 → 호출 1회 예산) |
| `SFR-018_text_polish/main.py` · `text_polish/config.py` | 라우트가 `polisher.polish_document` 를 부른다 (`polish_text_async` 직접 호출 아님) |
| `translation_pipeline/common/prompt_builder.py` · `office/markdown_units.py` · `office/translation_modes.py` | 배치 항목에 절 제목(`c`)을 싣는다 |
| `prompt/SFR-018_translation/system_batch.j2` · `system_single.j2` · `user_single.j2` | CONTEXT 규칙 (번역·출력 금지) |
| `workflow/sfr018_{faq_02_generate,polish_02_polish,translate_02_translate}.py` | payload `notice` + 죽은 `_stream_chunks` 제거 |
| `preprocessor/final_preprocessor.py` | 로그 화이트리스트를 **실제로 강제**한다(`_emit_log`) |

**새 환경변수 셋 — 전부 기본값이 있어 안 넣어도 뜬다**

| 변수 | 기본 | 뜻 |
|---|---|---|
| `FAQ_MAX_CONTEXT_CHUNKS` | 40 | 조각 수 상한 (≈96만 자). **여기 걸린 문서만** 뒤가 잘린다 |
| `POLISH_MAX_CHUNK_CHARS` | 6000 | 글다듬이 조각 크기 = LLM 호출 1회 예산 |
| `POLISH_LLM_CONCURRENCY` | 4 | 동시에 도는 조각 수 (번역은 15 — 그쪽은 조각이 작다) |

**옮긴 뒤 확인**: `check_unit_endpoints`(74) · `check_workflow_run`(84) ·
`check_eval_metrics`(68) · SFR-018 unittest(290).

---

### 2026-08-28 — 양쪽 하이라이트·**내려받기 링크**

> **정본은 [`docs/change_0828.md`](docs/change_0828.md)** — 이 절이 WORK.MD 에 통째로
> 빠져 있었다(2026-08-31 에 채웠다). 그래서 아래 `file_store.py` 3벌이 파일 목록에
> 없었고, **없는 파일은 "빠뜨렸다" 로도 안 드러난다.**

**새로 만드는 파일 (배포 단위 안 3개 — 같은 규약의 사본이다)**

| 파일 | 단위 | 줄 |
|---|---|---|
| `SFR-018_text_polish/text_polish/file_store.py` | 글다듬이 | 125 |
| `SFR-018_translation/translation_pipeline/common/file_store.py` | 번역 | 125 |
| `SFR-018_faq/faq/file_store.py` | FAQ | 125 |

결과 txt 를 서빙이 미리 굳혀 **GenOS MinIO 에 올리고 `download_url` 만 싣는다.**
`txt_output.py` 와 같은 사본 규약이라 **한쪽만 고치면 그 단위에서 받은 파일만 깨진다.**

> **운영 MCP 예제를 그대로 옮기면 안 되는 것 셋**: 동기 `urllib`(async 라우트의 이벤트
> 루프를 멈춘다) · 예외 원문 반환(내부 URL 이 실린다, §3.8) · 임시 파일 `delete=False`
> (예외 경로에서 남는다). 우리 사본은 셋 다 피해 있다 — **줄여 적지 말 것.**

**업로드 실패는 fail-open 이다.** `download_url` 을 비우고 결과는 그대로 낸다 — 예외를
올리면 잘 만들어진 다듬기·번역 결과가 통째로 사라진다.
**폐쇄망에서 MinIO 가 되는지는 미검증**이라 옛 `POST /download` 를 폴백으로 남겼다.

**새 환경변수 둘 — 기본값이 있어 안 넣어도 뜬다** (`docs/SERVING_REGISTRY.md` §1):
`GENOS_CDN_UPLOAD_URL`(기본 `http://llmops-cdn-api-service:8080/minio/upload/temp`) ·
`GENOS_CDN_HOSTNAME`(기본 `https://genos.genon.ai` — presigned URL 에 박힐 외부 호스트).
클러스터 안 이름이 다르면 `download_url` 이 계속 비어 나가는데 **오류가 아니라 버튼만
안 생기는 모양**이다.

---

### 2026-08-27 — 변경·용어 표시를 **본문 하이라이트**로

> **정본은 [`docs/change_0827.md`](docs/change_0827.md)** — 파일별·함수별 줄 번호,
> 안 고치는 것, 부분 이관 시 어디가 FAIL 하는지가 거기 있다. 아래는 그 요약이다.
>
> **이미 옮겨 적은 뒤라면 아래 6개 파일만 다시 옮긴다.** 새로 만드는 파일도 지우는 파일도
> 없고, 등록 단위 수·시작 커맨드·환경변수는 **하나도 바뀌지 않았다** — 재등록이 아니라
> 리비전 갱신이다.
>
> **아래 "→ 줄 수" 와 점검 건수는 이 변경 직후 값이다.** 08-28·29 가 같은 파일을 또
> 건드려 지금은 더 크다(예: `genon_text_guard` 760 → **826**, `check_mcp_tools` 75 →
> **80**). **지금 값은 §2·§3·§5 의 표**를 볼 것 — 여기 숫자로 대조하면 멀쩡한 파일이
> 어긋난 것처럼 보인다.

무엇이 바뀌었나 한 줄로: 글다듬이는 변경 내역을 **답변 끝 목록**으로 붙이던 것을 떼고
**바뀐 낱말에 `<mark>`** 를 입힌다. 번역은 용어사전 하이라이트가 payload 에만 실려
**화면에 한 번도 안 나오고 있었는데** 이제 `text` 가 사본을 담는다. 태그는 두 기능 다
`<strong>` → **`<mark>`** 다. 근거는 루트 `CLAUDE.md` "변경·용어 표시는 …" 절.

| # | 파일 | 줄 수 | 고치는 것 |
|---|---|---|---|
| 1 | `mcp/genon_text_guard.py` | 584 → **760** | 신규 함수 4 · **`_TGsplit_units` → `_TGsplit_units_with_spans`**(반환형 변경) · `tgbuild_change_list`·`_TGdiff_changes`·`TGChangeItem` · 새 상수 4 · 도구 독스트링 |
| 2 | `workflow/sfr018_polish_02_polish.py` | 458 → **487** | **`_format_changes` 삭제** · `run` 5곳 · 모듈 독스트링 |
| 3 | `workflow/sfr018_translate_02_translate.py` | 499 → **504** | `run` **1줄** (`display_text` 를 정본 → 사본) |
| 4 | `.../office/glossary_report.py` | 234 → **240** | `_OPEN_TAG`·`_CLOSE_TAG` 값 (로직 불변) |
| 5 | `.../api_contract.py` | 176 → **177** | 주석만 |
| 6 | `.../office/types.py` | **114** | 주석만 |

**순서: ① MCP(1) → ② 번역 코드서빙(4·5·6 — 한 단위라 같이) → ③ 워크플로우(2·3).**
1을 먼저 올려야 한다 — 2가 `diff_changes` 의 새 응답 필드를 읽는다. 뒤집으면 스텝이
정본을 화면에 흘리고, **그 상태는 오류 없이 "하이라이트가 안 보이는" 모양**이다.

```bash
export PYTHONIOENCODING=utf-8
python onprem/test/check_mcp_tools.py       # 68 → 75건
python onprem/test/check_workflow_run.py    # 74 → 80건
cd SFR-018 && python -m unittest discover -s tests -t .   # 218 → 235건
```

**부분 이관은 조용히 통과하지 않는다** — 1을 빼면 `check_mcp_tools`, 2·3을 빼면
`check_workflow_run` 의 "화면은 하이라이트 사본", 4를 빼면 unittest 의
`GlossaryMarkTagTest` 가 FAIL 한다. 갈래별 대응표는 `docs/change_0827.md` 끝에 있다.

---

## 0. 시작 전 — 이게 없으면 순서가 무의미하다

| 전제 | 없으면 | 어디까지 진행되나 |
|---|---|---|
| 폐쇄망 Git 저장소 | 코드서빙 등록 자체가 불가 | MCP·워크플로우·전처리기는 파일 붙여넣기라 **진행된다** |
| 사내 PyPI mirror | 빌드 커맨드가 그 자리에서 멈춘다 | 파일 작성은 다 되고 기동만 안 된다 |
| Gateway 4종(`GENOS_URL` `LLM_SERVING_ID` `LLM_MODEL_ID` `GENOS_TOKEN`) | 기동은 되고 첫 LLM 호출에서 실패 | LLM 없는 경로(파싱·미리보기)까지 확인 가능 |
| Redis(`REDIS_URL`) — 006·FAQ | 대화는 되는데 다운로드가 빈 문서 | 글다듬이·번역은 **무상태라 무관** |
| 템플릿 볼륨(`TEMPLATE_FILL_TEMPLATE_DIR`) — 006 | 템플릿을 못 찾는다 | 006 외 전부 무관 |
| 관리자 정책 프롬프트(`GENOS_ADMIN_API_URL` + 프롬프트 ID) — 글다듬이·MCP `lang_policy` | **막지 않는다** — 내장 톤 3종으로 정상 동작 | 전부 진행된다. 고객사가 톤을 직접 추가할 때만 필요하다 (`docs/SERVING_REGISTRY.md` §2-2) |

**막힌 전제가 있어도 순서를 바꾸지 않는다.** 아래 1~3단계는 위 전제 중 앞의 둘만
요구하고, Redis·볼륨은 마지막 단위(006)에서만 필요하다 — 그래서 006 을 뒤에 둔다.

---

## 1. 큰 순서 — 왜 이 차례인가

의존 방향이 한 방향이다. **워크플로우가 코드서빙·MCP 를 부르고, 반대는 없다.**
그래서 부르는 쪽을 나중에 쓴다 — 반대로 하면 스텝을 붙여도 부를 상대가 없어
`CONFIG_MISSING` 만 보게 되고, 그게 배선 실수인지 아직 안 올린 것인지 구분되지 않는다.

| 단계 | 대상 | 파일 | 줄 수 | 선행 | 끝났다는 증거 |
|---|---|---|---|---|---|
| **1** | `mcp/` 4파일 | 4 | 4,075 | 없음 | `tools/list` 에 **14개**가 다 나온다 |
| **2** | `codeserving/` 4단위 | 77 | 17,288 | Git·mirror | 단위마다 `GET /health` 200 |
| **3** | `prompt/` 12파일 | 12 | 439 | 2단계 | 기동 로그 `prompt_dir_loaded` |
| **4** | `workflow/` 9스텝 | 9 | 3,980 | 1~3단계 **전부** | 끝단 한 바퀴 통과 |
| **5** | `preprocessor/` 1파일 | 1 | 2,341 **또는 1,764** | **없음 — 독립 트랙** | hwpx 적재 후 검색 결과의 표가 살아 있다 |

**5단계는 언제 해도 된다.** hwpx 전용 전처리기는 RAG 적재 경로이고 위 네 기능 어디에도
배선돼 있지 않다. 파일 하나뿐이라 대기 시간이 생겼을 때 끼워 넣기 좋다.
**어느 파일을 올릴지는 §6 에서 고른다** — 줄 수가 두 개인 이유가 그것이다.

**단계 안에서는 잎(leaf)부터.** `config.py` → `logging_utils.py` → `error_codes.py` 가
어느 단위든 맨 앞이고 진입점(`main.py`)이 맨 뒤다. 진입점을 먼저 올리면 아직 없는
모듈을 import 하다 죽어서 **진짜 문제가 어디인지 가려진다.**

---

## 2. 1단계 — MCP 도구 파일 4개

**서로 완전히 독립이다** (파일 하나가 등록 단위이고 import 이 없다). 그래도 이 차례를
권한다:

| # | 파일 | 줄 | 먼저 쓰는 이유 |
|---|---|---|---|
| 1 | `mcp/genon_hwpx_text.py` | 1,171 | **유일하게 `lxml` 이 필요하다.** `requirements.txt` 를 쓸 수 없어 파일 안에서 설치하는데, mirror 접근이 없으면 여기서만 실패한다 — 그 사실을 제일 먼저 알아야 나머지 계획이 선다 |
| 2 | `mcp/genon_lang_policy.py` | 1,153 | 워크플로우 첫 스텝 둘(다듬-1·번역-1)이 이걸 부른다. **넷 중 유일하게 환경변수를 볼 수 있다** — 관리자 정책 프롬프트를 쓸 때만 (`GENOS_ADMIN_API_URL`·`LANG_POLICY_PROMPT_ID`, 없으면 내장값) |
| 3 | `mcp/genon_text_guard.py` | 826 | 마지막 스텝 둘이 부른다. 표준 라이브러리만 쓴다. **낱말 변경 좌표·`<mark>` 사본이 여기 있다** (2026-08-27) — 좌표는 원문·결과 **양쪽**이다(2026-08-28) |
| 4 | `mcp/genon_glossary.py` | 925 | **지금 어느 스텝도 부르지 않는다** — 번역 코드서빙이 자체 `glossary_exact.py` 로 처리한다. 뒤로 미뤄도 아무것도 막히지 않는다 |

**확인**: 넷을 다 올린 뒤 `tools/list` 에 **14개**(`TG` 4 + `LP` 6 + `GL` 3 + `HX` 1).
**하나라도 비면 이름이 겹쳐 덮인 것이다** — 최상위 심볼 접두어(`TG`/`LP`/`GL`/`HX`)를
옮겨 적다 빠뜨렸는지 본다.

> `TG` 가 5 → 4 다 (2026-08-18). 호출부가 하나도 없던 `evidence_check` 를 뺐다 —
> 근거 대조는 FAQ 코드서빙 `faq/evidence.py` 가 한다. **옛 문서를 보고 15 를 세면
> "하나가 덮였다" 고 오판한다.**

---

## 3. 2단계 — 코드서빙 4단위

### 단위 순서: 작고 전제 없는 것부터

| 순 | 단위 | 파일 | 줄 | 상태 저장 | 왜 이 자리인가 |
|---|---|---|---|---|---|
| 1 | `SFR-018_text_polish` | 12 | 2,000 | 무상태 | **가장 작다.** 빌드·시작 커맨드·환경변수·게이트웨이 왕복이라는 배포 절차 전체를 최소 분량으로 한 번 통과시킨다 |
| 2 | `SFR-018_translation` | 23 | 4,990 | 무상태 | 루트 `main.py` 라 시작 커맨드가 1번과 같다. LLM 없는 경로(`/translate/hwpx` 파싱)가 있어 게이트웨이 전에도 확인된다 |
| 3 | `SFR-018_faq` | 17 | 3,340 | **Redis** | Redis 전제가 여기서 처음 붙는다. 시작 커맨드가 `faq.main:app` 로 달라지는 첫 단위이기도 하다 |
| 4 | `SFR-006_template_fill` | 24 | 6,377 | Redis + 볼륨 | **가장 크고 전제가 가장 많다.** 앞의 셋에서 배포 절차가 검증된 뒤에 붙는 것이 낫다 |

빌드 커맨드는 넷 다 `pip install -r requirements.txt`. **시작 커맨드만 다르다** —
006 과 FAQ 에 `main:app` 을 쓰면 기동 실패한다(진입점이 패키지 안이다). 값은
`docs/SERVING_REGISTRY.md` §1.

> **패키지 디렉토리를 만들 때 `__init__.py` 를 빼먹지 말 것.** 파일 목록에 안 잡히는데
> 없으면 import 가 안 된다. 006 `template_fill/`(9줄) · FAQ `faq/`(11줄) ·
> 번역 `translation_pipeline/`·`common/`·`office/`(**셋 다 빈 파일**).

### 3-1. SFR-018_text_polish (14파일)

```
 1  text_polish/config.py           118    ┐ 잎 셋. 나머지 전부가 이걸 본다
 2  text_polish/logging_utils.py     82    │
 3  text_polish/error_codes.py      102    ┘ ErrorCode 가 http_status 를 들고 있다
 4  text_polish/policy_store.py     231    ★ 관리자 정책(프롬프트 라이브러리) 적재 — 5 가 이걸 쓴다
 5  text_polish/tone_presets.py     330      내장 톤 + 4 의 병합. MCP lang_policy 의 사본
 6  text_polish/txt_output.py       162      잎. 018 세 단위에 같은 사본 (BOM+CRLF)
 7  text_polish/file_store.py       125    ★ 잎. 결과 txt 를 CDN 에 올린다 — 018 세 단위 사본 (08-28)
 7a text_polish/prompt_library.py   204    ★ 라이브러리 조회 — 8 이 쓴다 (09-03). 네 단위 사본
 8  text_polish/prompt_loader.py    129
 9  text_polish/llm.py              196      CONFIG_MISSING 상수가 여기 있다
10  text_polish/chunking.py         200    ★ 조각 분해 + 원문 복원 (꼬리 공백을 따로 든다)
11  text_polish/polisher.py         126    ★ 10·9 를 묶는다 — 조각을 함께 돌리고 실패를 조각으로 센다
12  main.py                         363      진입점 (루트). 11 을 부른다
    ──────────────────────────────────────
    합계 2,368
    requirements.txt                 25
```

**10 → 11 → 12 순서를 지킨다.** `polisher.py` 가 `chunking`·`llm` 을 끌어오고 `main.py`
가 `polisher.polish_document` 를 부른다 — `polish_text_async` 를 직접 부르던 옛 배선을
그대로 두면 **긴 문서가 90초 타임아웃으로 돌아간다**(오류는 재시도 가능으로 분류돼
같은 자리에서 반복된다).

**`policy_store.py` 가 `tone_presets.py` 보다 먼저다** (2026-08-18 신규). 뒤엣것이
`from text_polish import policy_store` 로 앞엣것을 끌어온다 — 순서를 바꾸면 잎부터
올리는 원칙이 깨져 `tone_presets` 를 올리는 자리에서 `ImportError` 가 난다.

`markdown_guard.py`·`fact_guard.py`·`diff_report.py` 를 찾지 말 것 — **이 단위에 없다.**
2026-08-11 에 `mcp/genon_text_guard.py` 로 갔다.

### 3-2. SFR-018_translation (28파일)

```
 1  config.py                                   136   ┐ 잎
 2  translation_pipeline/common/logging_utils.py 71   │
 3  translation_pipeline/common/error_codes.py   65   │
 4  api_contract.py                             188   ┘ main.py 가 최상위에서 직접 끌어온다
 5  translation_pipeline/common/txt_output.py   162     잎. POST /download (2026-08-12)
 6  translation_pipeline/common/file_store.py   125   ★ 잎. 결과 txt 를 CDN 에 (08-28). 사본 3벌
 7  translation_pipeline/office/languages.py    334     한국어 축 검증(+원문 언어 교차검증) + 용어사전 적용 언어
 8  translation_pipeline/office/registers.py     86
 9  translation_pipeline/office/types.py        118     아래 전부가 쓰는 값 객체
10  common/glossary_store.py                    284   ┐ 적재 → 매칭. 순서 고정
11  common/glossary_exact.py                    414   ┘ 한국어 조사 폴백이 여기 있다(08-28)
11a common/prompt_library.py                    204   ┐ 순서 고정. 라이브러리 조회 (09-03)
12  common/prompt_loader.py                     144   │ 12 가 11a 를 쓴다
13  common/prompt_builder.py                     91   ┘ 배치 항목에 절 제목(`c`)을 싣는다
14  common/llm.py                               196     _base_url() 이 /api/gateway 를 붙인다
15  common/validation.py                         68
16  office/markdown_units.py                    242   ┐ 분해/재조립. 구조 보존 계약의 몸통
17  office/hwpx_text.py                         950   │ lxml — 모듈 최상단 import. 누락 방지 층 포함(2026-08-23)
18  office/units.py                              47   ┘
19  office/numeric_guard.py                      73   ┐ 사후 검증
20  office/glossary_report.py                   285   ┘ term_map·hits[].spans·**target_spans**·`<mark>` 사본
21  office/translation_modes.py                 325   ┐ 실행 → 오케스트레이션
22  office/pipeline.py                          241   ┘ DirectionVerdict 를 받는다
23  main.py                                     441     진입점 (루트)
    ─────────────────────────────────────────────
    합계 5,290 (빈 __init__.py 3개 포함)
    requirements.txt                             21
    translation_pipeline/{,common/,office/}__init__.py  ← 빈 파일 3개
```

### 3-3. SFR-018_faq (20파일)

```
 1  faq/config.py           137   ┐ 잎
 2  faq/logging_utils.py     66   │
 3  faq/error_codes.py      189   │ 실패 4갈래(504/422/500/502)가 이 표에 있다
 4  faq/api_contract.py     115   ┘
 5  faq/txt_output.py       162     잎. 세 018 단위에 같은 사본
 6  faq/file_store.py       125   ★ 잎. 결과 txt 를 CDN 에 (08-28). 사본 3벌
 7  faq/redis_client.py      33   ┐ from_url 을 부르는 유일한 곳
 8  faq/session_store.py    128   ┘
 9  faq/hwpx_xml.py         163   ┐ hwpx 직접 파싱 (입력 전용)
10  faq/hwpx_text.py        825   ┘ 표 격자 + 누락 방지 — MCP 사본과 같아야 한다
11  faq/evidence.py          84     근거 대조 — 이 단위의 핵심 계약. **문서 전체로** 대조한다
12  faq/chunking.py         152   ★ 문서를 호출 1회 예산으로 나누고 **생성 개수를 배분**한다
12a faq/prompt_library.py   204    ★ 라이브러리 조회 — 13 이 쓴다 (09-03). 네 단위 사본
13  faq/prompt_loader.py    128
14  faq/llm.py              199     CONFIG_MISSING → FAILURE_CONFIG
15  faq/generator.py        486     11·12·13·14 를 묶는다
16  faq/formatting.py       153     화면 마크다운 + 파일 평문 (항목 목록 공유)
17  faq/main.py             367     진입점
    ─────────────────────────────────────
    합계 3,727 (빈 __init__.py 11줄 포함)
    requirements.txt         38
    faq/__init__.py          11
```

**12 가 11 보다 뒤인 것에 이유가 있다.** 조각을 나눠도 **근거 대조와 중복 판정은
문서 전체·조각 전체로** 한다 — 조각별로 따로 하면 경계에 걸친 문장이 오탐 기각되고,
같은 주제가 여러 절에 나올 때 같은 질문이 조각마다 통과한다.

### 3-4. SFR-006_template_fill (28파일)

```
 1  template_fill/config.py         158   ┐ 잎 셋
 2  template_fill/logging_utils.py   71   │
 3  template_fill/error_codes.py    162   ┘
 4  template_fill/hwpx_fields.py    890     ★ hwpx 판정의 정본 (슬롯·누름틀·채움 판정)
 5  template_fill/redis_client.py    35
 6  template_fill/api_errors.py      60   ┐ 4 위에 얹히는 보조
 7  template_fill/template_store.py 159   │
 8  template_fill/api_requests.py   147   ┘
 9  template_fill/hwpx_style.py     548   ┐ 4 의 파서를 재사용
10  template_fill/hwpx_blocks.py    423   │
11  template_fill/chat_reply.py     196   ┘ 기각 **항목 이름**까지 문장에 담는다 (08-28).
                                            자동 채움 안내도 여기 (08-31)
12  template_fill/field_judge.py    225     10 의 BodyBlock 을 쓴다
13  template_fill/document.py       171     조립점 — 서식→채우기→블록 순서가 여기 한 곳
14  template_fill/hwpx_markdown.py  819     **13 을 import 한다** (4 만 본다는 착각 주의).
                                            누락 방지 층 포함(2026-08-23)
15  template_fill/session_store.py  275   ┐ SCHEMA_VERSION 4 / **_STATE_VERSION 3**
                                            + `source_doc_hashes` **목록** (09-02)
16  template_fill/template_index.py 341   ┘
16a template_fill/prompt_library.py 205   ┐ 순서 고정. 라이브러리 조회 (09-03)
17  template_fill/prompt_loader.py  140   │ 17 이 16a 를 쓴다
18  template_fill/prompts.py        128   ┘ build_document_prompts 포함 (08-31)
19  template_fill/llm.py            191     _chat_url()
19a template_fill/doc_prefill.py    253   ★ 업로드 문서 자동 채움 — 18·19 를 쓴다 (08-31).
                                            **대화 중간에도 돈다** (09-02)
20  template_fill/chat_state.py     185
21  template_fill/session_view.py   245     화면 편집도 **문서 표식을 실어야** 한다 (09-02)
22  template_fill/api_download.py   114     hwpx 응답 조립 (형식이 하나라 분기가 없다)
23  template_fill/chat_api.py       551     /chat/context·**prefill**·extract·commit
24  template_fill/main.py           575     진입점 (21·22·23 을 전부 끌어온다)
    ────────────────────────────────────────────
    합계 7,276 (__init__.py 9줄 포함, 2026-09-03 재계수)
    requirements.txt                 34
    template_fill/__init__.py         9
```

`tone_presets.py`·`value_guard.py`·`tone_apply.py`·`overflow.py`·`hwpx_verify.py`·
`_vendor/`·**`pdf_convert.py`** 는 **찾지 말 것.** 앞의 다섯과 `_vendor/` 는 2026-08-12
(`archive/sfr006-tone`·`archive/hwpx-genon-vendor`), `pdf_convert.py` 는 2026-08-14 에
지웠다(`archive/sfr006-pdf` — 산출 형식이 hwpx 하나가 됐다).

### 단위마다 끝에 확인

1. `GET /health` 200 → 2. 기동 로그(`prompt_dir_loaded`, 006 은 `admin_token_missing`
경고 유무) → 3. 설정 조회(`GET /config`·`/templates`·`/languages`) → 4. LLM 없는 경로
→ 5. LLM 경로. 실패하면 로그 `event` 로 갈린다: `prompt_render_failed`(3단계 누락) /
`upstream_status`(게이트웨이) / 그 외.

---

## 4. 3단계 — 프롬프트 12파일

**배포 단위 밖이라 파일 목록에 안 잡힌다.** 빠뜨리면 기동은 되고 첫 LLM 호출에서
`PromptRenderError` 로 죽는다.

```
prompt/SFR-006_template_fill/extract_system.j2   65
                            /extract_user.j2     45
prompt/SFR-018_text_polish/system.j2             44
prompt/SFR-018_translation/system_batch.j2       58   ← CONTEXT 규칙 (번역·출력 금지)
                          /user_batch.j2          9
                          /system_single.j2      37   ← 같은 규칙. 단건 폴백에도 싣는다
                          /user_single.j2        11
prompt/SFR-018_faq/system.j2                     50
                  /user.j2                       15
                  /retry_shortfall.j2            24
                                              ─────
                                                358
```

**번역 셋의 CONTEXT 규칙을 빼먹지 말 것** (2026-08-29). 유닛에 절 제목을 문맥으로 다는데
"`c` 는 배경이며 번역하지도 출력하지도 말라" 가 없으면 **모델이 문맥을 번역문에 섞고,
구조는 코드가 지키므로 그 결과가 정상 응답으로 내려간다.** 단건 폴백(`system_single`)에만
빠뜨리면 **배치가 실패했을 때만** 드러나 더 어렵다.

**필요한 이미지는 코드서빙 4개뿐이다.** 워크플로우 스텝은 `jinja2` 를 쓸 수 없어
(§D.3) 프롬프트를 렌더하지 않는다 — 재배치 전 "006·FAQ 는 02·03 두 이미지 모두" 라는
서술은 지금 해당 없다.

`*.j2` 머리말의 한/영 분리 근거 주석을 **함께 옮긴다.** 문구를 고칠 사람이 파일만 열어도
어느 블록을 어느 언어로 둘지 알아야 한다.

---

## 5. 4단계 — 워크플로우 스텝 9개

**파일을 통째로 캔버스에 붙여 넣는다.** 파일 간 import 이 하나도 없어 순서 제약은
없지만, 기능 단위로 묶어 **그 기능을 끝까지 통과시키고 다음으로 간다** — 스텝만 아홉 개
붙여 놓고 한꺼번에 눌러 보면 어느 층에서 어긋났는지 갈라내기 어렵다.

| 순 | 기능 | 스텝 | 필요한 ID |
|---|---|---|---|
| 1 | 글다듬이 | `sfr018_polish_01_policy`(333) → `sfr018_polish_02_polish`(**579**) | `LANG_POLICY_MCP_ID` · `TEXT_POLISH_SERVING_ID` · `TEXT_GUARD_MCP_ID` |
| 2 | 번역 | `sfr018_translate_01_detect`(471) → `sfr018_translate_02_translate`(**585**) | `LANG_POLICY_MCP_ID` · **`HWPX_TEXT_MCP_ID`** · `TRANSLATION_SERVING_ID` · `TEXT_GUARD_MCP_ID` |
| 3 | FAQ | `sfr018_faq_01_source`(436) → `sfr018_faq_02_generate`(**445**) | `HWPX_TEXT_MCP_ID` · `FAQ_SERVING_ID` |
| 4 | 006 | `sfr006_01_context`(**455**) → `sfr006_02_extract`(303) → `sfr006_03_commit`(**384**) | `TEMPLATE_FILL_SERVING_ID` |

여기에 `GENOS_URL`·`GENOS_TOKEN` 이 전 스텝 공통이다. **시크릿 기본값이 없으므로**
하나라도 빠지면 그 스텝이 `CONFIG_MISSING`(`02-00020003`)으로 즉시 끝난다.

**번역-1 이 `HWPX_TEXT_MCP_ID` 를 쓴다.** 캔버스가 `translate_hwpx_path` 를 채워 줄 때
hwpx 전용 파서를 태우는 경로이고, 없으면 전처리기 산출물로 떨어진다(그 폴백은 로그에
사유를 남긴다). 예전 표에 이 줄이 빠져 있었다.

캔버스 변수: `template_fill_template_id`(006 필수) · `polish_doc_type`·`polish_tone`(선택)
· `faq_max_count` · `faq_hwpx_path` · `translate_target_lang`(**번역 필수**) ·
`translate_source_lang`·`translate_register`(선택) · `translate_hwpx_path`.

**`translate_source_lang` 은 선택이지만 화면에 드롭다운이 있다.** 비우면 문서에서
감지하고, 채우면 그 값이 정본이 되되 **문서와 대조한다**(2026-08-18) — 선언이 한국어인데
문서에 한글이 없고 대상도 비한국어면 거부된다(실제로는 `en→ru` 이므로). 통과한 불일치는
`translate_source_mismatch`·`translate_detected_lang` 으로 다음 스텝에 넘어간다.

---

## 6. 5단계 — 전처리기 (독립 트랙, **파일 하나**)

```
preprocessor/final_preprocessor.py  5,958   ⭐ **정본 · 등록 단위 · 치는 대상**
                                              PART 1 첨부용(벤더) 2,587 — **1줄만 수정**
                                              PART 2 hwpx 파서   2,360 — 친다
                                              PART 3 라우터        891 — 친다
──────────────────────────────────────────
preprocessor/__init__.py               58      로컬 테스트용 재노출 (등록 대상 아님)
```

**2026-09-03 부터 판본이 하나다.** 그전에는 hwpx 단독(`hwpx_preprocessor.py`)과 합친
생성물 중 하나를 골랐고, 합친 쪽은 주석을 걷어낸 `transfer/` 판본을 쳤다. 지금은 **보는
파일·치는 파일·정본이 전부 같다.**

### 등록 화면에서 **받을 확장자**를 고른다

파일은 하나이고 등록도 한 번이다. 갈리는 것은 확장자 매핑뿐이다.

| 무엇을 걸까 | 언제 |
|---|---|
| **`hwpx` 만** | 확장자별로 매핑을 나눌 수 있을 때. **이쪽이 기본**이다 — 나머지는 사이트의 기존 첨부용 등록이 그대로 맡고, PART 1 이 안 뜨는 설치본에서도 안전하다 |
| 전 확장자 | 한 등록이 모든 확장자를 받아야 할 때. 사이트 패키지 판본이 참조 사본과 맞아야 한다 (§6 아래 주) |

- **PART 1 이 안 떠도 hwpx 는 돈다** — 가드가 `except Exception` 이고 PART 2·3 은 가드
  밖이다. 그래서 `hwpx` 만 걸어 먼저 올리고, 판본을 맞춘 뒤 확장자를 넓히면 된다.
- **`hwp`(구버전 바이너리)를 hwpx 파서에 걸지 말 것** — zip 기반 hwpx 전용이라 못 연다.
  라우터가 첨부용(GenosHwp SDK 네이티브)으로 보낸다.
- **hwpx 청킹만 고쳐도 이 등록으로 적재한 pdf·docx 까지 `needs_reingest`** 다(전 확장자를
  걸었을 때). 재적재 비용이 큰 컬렉션이면 `hwpx` 만 거는 쪽이 낫다.

### 치는 법

1. 사이트의 **첨부용 전처리기 파일을 그대로 뜬다**(그게 PART 1 이다).
2. `class DocumentProcessor:` → `class AttachDocumentProcessor:` **1줄만 고친다.**
   안 고치면 GenOS 가 벤더 것을 실행해 **라우팅이 통째로 사라지는데 적재는 성공으로 보인다.**
3. 그 뒤에 `_FP_ATTACH_IMPORT_ERROR = None` / `_FP_ATTACH_IMPORT_TRACE = ""` 두 줄을 넣는다
   (저장소 판본은 PART 1 을 `try:` 로 감싸지만 **그건 우리 사정**이다 — 로컬에 docling 이
   없어도 점검이 돌아야 해서다. 온프레미스에는 벤더 스택이 이미 있다).
4. **PART 2 · PART 3 을 이어 친다** (3,251줄).

**순서가 계약이다** — 뒤엣것이 앞엣것을 덮으므로 `DocumentProcessor` 라는 이름은 **PART 3
라우터 것**이 마지막에 남아야 한다.

**확인**: `python onprem/test/check_final_preprocessor.py` — **155건**.
155 가 아니면 실물 hwpx(`data/` 5벌)를 못 찾은 것이다(있는 것만 태우므로 **조용히**
134 로 준다). docling 이 반쯤 설치된 환경에서는 `벤더 부재…` 1건이 FAIL 하는데
코드 결함이 아니다.

---

## 6-1. 선택 트랙 — 관리자 정책 프롬프트 (파일을 쓰는 일이 아니다)

**이건 옮겨 적는 대상이 아니라 GenOS 화면에서 만드는 리소스다.** 그래서 위 총량
116개에 없다. **안 만들어도 네 기능이 전부 정상 동작한다** — 내장 톤 4종·문서유형 5종으로
돈다. 고객사가 **톤을 직접 추가·수정**하겠다고 할 때만 만든다.

| 순 | 할 일 | 어디서 |
|---|---|---|
| 1 | `도구 > 프롬프트 라이브러리` 에 정책 프롬프트 생성 (본문 = JSON) | GenOS 화면 |
| 2 | 리비전을 **운영 반영** | GenOS 화면 |
| 3 | 글다듬이 코드서빙에 `GENOS_ADMIN_API_URL` + `POLISH_POLICY_PROMPT_ID` | 리비전 상세 > 환경 설정 |
| 4 | MCP `genon_lang_policy` 에 `GENOS_ADMIN_API_URL` + `LANG_POLICY_PROMPT_ID` (**같은 ID**) | MCP 등록 화면 |
| 5 | `GET {글다듬이}/policies` 에서 `policy.source == "prompt_library"` 확인 | curl |

JSON 형식·필드표·`reason` 진단표는 [`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md)
§2-2 에 있다. 여기서 반복하지 않는다.

**3·4 를 반드시 같이 한다.** 화면 드롭다운은 글다듬이가 그리고 **강제 톤 판정은 MCP 가**
한다 — 한쪽에만 넣으면 사용자가 화면에서 고른 톤을 워크플로우가 "알 수 없는 톤" 으로
되돌린다. 예외도 오류 코드도 없다.

**언제 해도 된다.** 2단계(코드서빙)·1단계(MCP)가 올라간 뒤라면 순서 제약이 없고, 나중에
붙여도 그때부터 반영된다(재배포 불필요 — 그게 이 기능의 목적이다).

---

## 6-2. 선택 트랙 — 프롬프트 **본문** 라이브러리 (2026-09-03)

**§6-1 과 같은 성격이다 — 화면에서 만드는 리소스이고 총량 116개에 없다.** 다만 담는
것이 다르다: §6-1 은 톤·문서유형 **목록(JSON)** 이고, 여기는 **프롬프트 문장 그 자체**다.

**안 만들어도 네 기능이 전부 정상 동작한다** — 이미지에 든 `.j2` 로 돈다. 고객사가
**프롬프트 문구를 직접 고치겠다**고 할 때만 만든다.

| 순 | 할 일 | 어디서 |
|---|---|---|
| 1 | `도구 > 프롬프트 라이브러리` 에 프롬프트 생성 (본문 = `.j2` 내용 그대로) | GenOS 화면 |
| 2 | 리비전을 **운영 반영** | GenOS 화면 |
| 3 | 그 단위 코드서빙에 `GENOS_ADMIN_API_URL` + `<단위>_PROMPT_IDS` | 리비전 상세 > 환경 설정 |
| 4 | `GET {단위}/prompts` 에서 `source == "prompt_library"` 확인 | curl |

**이름을 파일 이름과 똑같이 적는다**(`extract_user.j2` → `extract_user`). 다르면 그
이름만 조용히 옛 문구로 돌고, **오류도 빈 응답도 나지 않는다.**

**지시문 언어 규약을 그대로 지킨다** — 톤·문서유형처럼 **산출물의 어투를 통제하는
문장은 한국어**, 시스템 프롬프트(출력 형식·금지 조항)는 영어여도 된다. 형식·필드표는
[`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md) §2-3, 설계 근거는
[`prompt/README.md`](prompt/README.md).

**언제 해도 된다** — 2단계가 올라간 뒤라면 순서 제약이 없고 재배포도 필요 없다.

---

## 7. 옮겨 적을 때 반복해서 나는 실수

| 실수 | 어떻게 드러나나 |
|---|---|
| 프롬프트 디렉토리를 안 넣음 | 기동·헬스체크 정상, **첫 LLM 호출에서만** `PromptRenderError` |
| 006·FAQ 에 `main:app` 등록 | 기동 실패 (진입점이 패키지 안이다) |
| 빈 `__init__.py` 누락 | 진입점 올리는 마지막 단계에서 `ImportError` — 앞 단계는 전부 통과한 뒤다 |
| MCP 접두어(`TG`/`LP`/`GL`/`HX`) 누락 | 도구가 **덮인다.** 예외 없이 "값이 이상하다" 로만 보인다 |
| 006·FAQ 가 서로 다른 Redis | 대화는 정상, 다운로드가 빈 문서 |
| 사본을 한쪽만 고침 (hwpx 파싱 코어 **5벌**·**`prompt_library` 4벌**·톤 3벌·`txt_output` 3벌·**`file_store` 3벌**·**언어 방향 2벌**·**정책 파서 2벌**·**톤 별칭 2벌**·용어사전 적재 2벌·**하이라이트 태그 2벌**) | 그 기능에서 받은 파일만 깨진다. 사용자 제보로만 드러난다 |
| 목록에 **없는 파일**을 안 옮김 (`file_store`·`chunking`·`polisher`) | 이 문서가 08-28·29 작업을 놓쳐 실제로 생겼던 구멍이다. 없으면 `ImportError` 로 죽지만 **어느 파일인지는 진입점을 올릴 때까지 안 보인다** |
| PART 순서를 바꿔 침 (라우터를 먼저) | `DocumentProcessor` 가 벤더 것으로 남아 **라우팅이 통째로 사라지는데 적재는 성공으로 보인다** — §6 |
| `<단위>_PROMPT_IDS` 의 **이름을 파일 이름과 다르게** 적음 | 그 이름만 라이브러리를 안 타고 **조용히 옛 `.j2` 문구로 돈다.** `GET /prompts` 의 `source` 로만 보인다 |
| 관리자 정책 프롬프트 ID 를 **한쪽에만** 넣음 (글다듬이 ○ / MCP `lang_policy` ×) | 화면 드롭다운에는 추가한 톤이 뜨는데 **고르면 기본 톤으로 되돌아간다.** 오류가 아니라 "고른 톤이 조용히 무시되는" 모양이다 |

**올리기 전에 로컬에서 한 번 돌린다** (전부 서버·LLM·Redis 불필요):

```bash
export PYTHONIOENCODING=utf-8
python onprem/test/check_deploy_contract.py   # FAIL 0 / WARN 3 / OK 64 — 배치가 어긋났는지
python onprem/test/check_service_boot.py      # 16건
python onprem/test/check_mcp_tools.py         # 80건
python onprem/test/check_tone_policy.py       # 24건 — 사본 대조. 옮겨 적다 한쪽만 고쳤는지
python onprem/test/check_table_grid.py        # 33건 — hwpx 파싱 코어 5벌
python onprem/test/check_final_preprocessor.py  # 168건 — §6 (ㄴ)를 고를 때만 필요
```

전체 목록·건수는 루트 `CLAUDE.md` "검증 명령".

---

## 8. 다 옮긴 뒤 남는 일

**여기부터는 파일을 쓰는 일이 아니라 실물로 확인하는 일이다.** 목록과 우선순위는
[`HANDOFF.md`](HANDOFF.md) §4 — LLM 실호출, 게이트웨이의 JSON-RPC 통과 여부,
빌드·시작 커맨드의 셸 통과 여부, 스텝 간 `data` 크기 한도, 메모장에서 `.txt` 열기,
한/글에서 006 산출물 열기.
