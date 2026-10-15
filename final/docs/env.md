# 환경변수 — 기능별로 **어디에** 무엇을 넣나

등록 단위는 네 종류다. 같은 이름이라도 **넣는 자리가 다르면 다른 값**이다(예: `GENOS_TOKEN` 은
워크플로우와 코드서빙에 각각 넣는다).

| 자리 | 어디서 넣나 |
|---|---|
| **워크플로우** | 캔버스 워크플로우 리비전 정보 > 환경 변수 (가이드 11.5.4). 그 워크플로우의 파이썬 스텝 전부가 같이 본다 |
| **코드서빙** | 코드서빙 등록 > 환경변수. 단위마다 따로 |
| **MCP** | MCP 서버 등록 > 환경변수. 파일(도구)마다 따로 |
| **전처리기** | 전처리기 파드 환경변수 + **등록 화면 파라미터**(kwargs) |

`PORT`·`OPENAPI_PATH`·`LANGUAGE`·`BUILD_COMMAND`·`START_COMMAND` 는 GenOS 가 주입한다 — 넣지 않는다.

표기: ✅ 필수 · ◻ 선택(기본값 있음) · ⚠ 조건부 필수

---

## 0. 모든 기능 공통

### 워크플로우 (네 워크플로우 전부)

| 변수 | | 뜻 |
|---|---|---|
| `GENOS_URL` | ✅ | 게이트웨이 주소. 코드가 `/api/gateway` 를 붙인다(이미 붙어 있으면 그대로) |
| `GENOS_TOKEN` | ✅ | 게이트웨이 호출 토큰 |
| `OCR_MCP_ID` | ⚠ | MCP `genon_ocr` 등록 ID. 첨부에 스캔 pdf 가 올 수 있으면 필수 — 없으면 스캔 쪽이 든 요청이 `CONFIG_MISSING` 으로 선다 |
| `LOG_LEVEL` | ◻ | 기본 `INFO` |
| `GENON_DEBUG` | ◻ | `1` 이면 디버그 에코(허용 필드 밖 값까지 남는다 — 운영에서는 끈다) |

### 코드서빙 (네 단위 전부)

| 변수 | | 뜻 |
|---|---|---|
| `GENOS_URL` | ✅ | 게이트웨이 주소 |
| `GENOS_TOKEN` | ✅ | 게이트웨이 호출 토큰 |
| `LLM_SERVING_ID` | ✅ | LLM 서빙 ID. 셋 중 하나라도 빠지면 첫 LLM 호출에서 "서비스 설정이 완료되지 않았습니다" |
| `GENOS_ADMIN_API_URL` | ◻ | 프롬프트 라이브러리를 쓸 때. 내부 `http://llmops-admin-api-service:8080` |
| `GENOS_CDN_UPLOAD_URL` | ◻ | 결과 파일 업로드. 기본 `http://llmops-cdn-api-service:8080/minio/upload/temp` |
| `GENOS_CDN_HOSTNAME` | ◻ | presigned URL 의 외부 호스트. 기본 `https://genos.genon.ai`. 틀리면 `download_url` 이 계속 `null` |
| `RES_TIMEOUT` · `LLM_RETRY_COUNT` · `MODEL_TEMP` | ◻ | LLM 응답 대기(초) · 재시도 · 온도 |
| `LOG_LEVEL` · `GENON_DEBUG` | ◻ | 워크플로우와 같다 |

### MCP

| 파일 | 변수 | | 뜻 |
|---|---|---|---|
| `genon_ocr.py` | `OCR_ENDPOINT` | ◻ | Paddle OCR 서빙. 기본 `http://192.168.73.172:48080/ocr` |
| | `OCR_TIMEOUT` | ◻ | 쪽 하나 OCR 대기(초). 기본 60 |
| | `OCR_IMAGE_HOSTS` | ⚠ | 받아도 되는 쪽 이미지 URL 호스트(쉼표 구분). 없으면 `GENOS_CDN_HOSTNAME` 의 호스트, 그것도 없으면 `genos.genon.ai`. **전처리기의 `GENOS_CDN_HOSTNAME`/`scan_hostname` 과 같은 호스트여야 한다** — 어긋나면 모든 스캔 쪽이 `URL_NOT_ALLOWED` |
| | `OCR_FETCH_TIMEOUT` | ◻ | 쪽 이미지 받기 대기(초). 기본 30 |
| `genon_text_guard.py` · `genon_lang_policy.py` · `genon_pii_audit.py` | — | | 없다 |

### 전처리기 (`high_preprocessor.py` — 첨부용)

| 자리 | 이름 | | 뜻 |
|---|---|---|---|
| 등록 파라미터 | `ocr_defer` | ⚠ | **첨부 등록은 `true`.** 스캔 쪽을 여기서 읽지 않고 CDN 에 올려 표식만 남긴다(워크플로우 스텝 1 이 OCR) |
| 등록 파라미터 | `scan_upload_url` · `scan_hostname` | ◻ | 쪽 이미지 업로드 주소 · presigned 호스트. 없으면 아래 환경변수 → 코드서빙과 같은 기본값 |
| 환경변수 | `GENOS_CDN_UPLOAD_URL` · `GENOS_CDN_HOSTNAME` | ◻ | 위 둘의 기본값 |
| 등록 파라미터 | `ocr` · `ocr_endpoint` · `ocr_timeout` | ◻ | `ocr_defer` 가 아닐 때(적재용) 여기서 OCR. 기본 켬 · 지능형과 같은 주소 · 60초 |
| 등록 파라미터 | `chunk_size` · `chunk_overlap` · `outline_mode` · `save_images` · `extra_metadata` | ◻ | 청킹 · 위계 판정 · 그림 저장 |

`final_preprocessor.py` 는 환경변수를 읽지 않는다.

---

## 1. SFR-006 양식 채우기

| 자리 | 변수 | | 뜻 |
|---|---|---|---|
| 워크플로우 | `TEMPLATE_FILL_SERVING_ID` | ✅ | 코드서빙 #1 ID (스텝 1·2·3) |
| 워크플로우 | `TEMPLATE_FILL_DEFAULT_TEMPLATE_ID` | ◻ | 캔버스가 양식을 안 고르면 쓸 양식 |
| 워크플로우 | `DISCLAIMER_MCP_ID` | ◻ | 안내 문구 (§5) |
| 코드서빙 #1 | `REDIS_URL` | ✅ | 세션 저장. **워크플로우 pod 와 같은 Redis** |
| 코드서빙 #1 | `TEMPLATE_FILL_TEMPLATE_DIR` | ✅ | 양식 hwpx 공유 볼륨 경로 |
| 코드서빙 #1 | `TEXT_POLISH_SERVING_ID` | ◻ | 본문 블록을 글다듬이 코드서빙(#2)으로 다듬을 때. 없으면 다듬기 없이 채운다 |
| 코드서빙 #1 | `TEMPLATE_FILL_PROMPT_IDS` | ◻ | 프롬프트 라이브러리 `이름=ID` |
| 코드서빙 #1 | `TEMPLATE_FILL_ADMIN_TOKEN` | ◻ | 관리 라우트(재적재 등) 토큰 |
| 코드서빙 #1 | 그 밖 `TEMPLATE_FILL_*` | ◻ | 상한·TTL·스타일 등 조정값 — 전부 기본값이 있다. 목록과 기본값은 `final/SFR-006/request/template_fill/config.py` |
| MCP `genon_template_draft.py` | `GENOS_URL` · `GENOS_TOKEN` · `TEMPLATE_FILL_SERVING_ID` | ✅ | 사람이 직접 부르는 양식 초안 도구 |
| MCP `genon_template_draft.py` | `GENOS_CDN_UPLOAD_URL` · `GENOS_CDN_HOSTNAME` · `TEMPLATE_DRAFT_TIMEOUT` | ◻ | 초안 파일 업로드 · 대기 |

## 2. SFR-018 글다듬이

| 자리 | 변수 | | 뜻 |
|---|---|---|---|
| 워크플로우 | `LANG_POLICY_MCP_ID` | ✅ | MCP `genon_lang_policy` (다듬-1 `resolve_tone`) |
| 워크플로우 | `TEXT_POLISH_SERVING_ID` | ✅ | 코드서빙 #2 (다듬-1 입력 판단 `/input/check` · 다듬-2) |
| 워크플로우 | `TEXT_GUARD_MCP_ID` | ◻ | MCP `genon_text_guard`. 없으면 구조·사실 점검 없이 결과만 나간다 |
| 워크플로우 | `POLISH_DEFAULT_DOC_TYPE` · `POLISH_DEFAULT_TONE` | ◻ | 캔버스 변수가 비었을 때의 문서유형 · 톤 |
| 워크플로우 | `DISCLAIMER_MCP_ID` | ◻ | 안내 문구 (§5) |
| 코드서빙 #2 | `POLISH_PROMPT_IDS` | ◻ | 프롬프트 라이브러리 `이름=ID` |
| 코드서빙 #2 | `INPUT_CHECK_LLM_SERVING_ID` | ◻ | 입력 판단 LLM 서빙 ID. 작은 모델을 따로 붙일 때. 없으면 `LLM_SERVING_ID` |
| 코드서빙 #2 | `POLISH_MAX_INPUT_CHARS` · `POLISH_MAX_CHUNK_CHARS`(6000) · `POLISH_LLM_CONCURRENCY`(4) · `POLISH_PROMPT_TIMEOUT` | ◻ | 입력 상한 · 조각 크기 · 동시 호출 · 프롬프트 조회 대기 |

Redis·볼륨이 필요 없다(무상태).

## 3. SFR-018 번역

| 자리 | 변수 | | 뜻 |
|---|---|---|---|
| 워크플로우 | `LANG_POLICY_MCP_ID` | ✅ | MCP `genon_lang_policy` (번역-1 `validate_direction`) |
| 워크플로우 | `TRANSLATION_SERVING_ID` | ✅ | 코드서빙 #3 (번역-1 입력 판단 `/input/check` · 번역-2) |
| 워크플로우 | `TEXT_GUARD_MCP_ID` | ◻ | 숫자 점검. 없으면 점검 없이 결과만 |
| 워크플로우 | `TRANSLATE_DEFAULT_TARGET_LANG` | ⚠ | 캔버스가 대상 언어를 안 주는 배선이면 필수 — 없으면 `TARGET_MISSING` |
| 워크플로우 | `TRANSLATE_DEFAULT_SOURCE_LANG` · `TRANSLATE_DEFAULT_REGISTER` | ◻ | 원문 언어 · 문체 기본값 |
| 워크플로우 | `DISCLAIMER_MCP_ID` | ◻ | 안내 문구 (§5) |
| 코드서빙 #3 | `TRANSLATE_GLOSSARY_API_URL` · `TRANSLATE_GLOSSARY_DRIVE_ID` · `TRANSLATE_GLOSSARY_WORKSPACE_ID` | ⚠ | 용어사전을 쓸 때 셋 다. 하나라도 없으면 용어사전 없이 번역(`glossary.source.reason`) |
| 코드서빙 #3 | `TRANSLATE_GLOSSARY_TOKEN` | ◻ | 용어사전 API 토큰이 `GENOS_TOKEN` 과 다를 때 |
| 코드서빙 #3 | `TRANSLATE_PROMPT_IDS` · `TRANSLATE_ADMIN_TOKEN` | ◻ | 프롬프트 라이브러리 · 관리 라우트 토큰 |
| 코드서빙 #3 | `INPUT_CHECK_LLM_SERVING_ID` | ◻ | 입력 판단 LLM 서빙 ID. 작은 모델을 따로 붙일 때. 없으면 `LLM_SERVING_ID` |
| 코드서빙 #3 | `LLM_CONCURRENCY` · `MAX_ITEMS_PER_BATCH` · `MAX_CHARS_PER_BATCH` · `MAX_TOKENS` · `TRANSLATE_MAX_*` · `TRANSLATE_NUMERIC_GUARD` · `TRANSLATE_DEDUPE_UNITS` · `TRANSLATE_STREAM_CHUNK_CHARS` · `TRANSLATE_PROMPT_TIMEOUT` | ◻ | 배치 · 상한 · 숫자 보존 모드(`warn`/`revert`) 등. 기본값은 `final/SFR-018-translate/request/config.py` |
| MCP `genon_glossary.py` | `TRANSLATE_GLOSSARY_API_URL` · `_DRIVE_ID` · `_WORKSPACE_ID` · `_TOKEN` | ⚠ | 코드서빙 #3 과 **같은 값** (사본 두 벌이 같은 사전을 봐야 한다) |

## 4. SFR-018 FAQ

| 자리 | 변수 | | 뜻 |
|---|---|---|---|
| 워크플로우 | `FAQ_SERVING_ID` | ✅ | 코드서빙 #4 (FAQ-1·2) |
| 워크플로우 | `DISCLAIMER_MCP_ID` | ◻ | 안내 문구 (§5) |
| 코드서빙 #4 | `REDIS_URL` | ⚠ | 다운로드 세션 저장. 세션 id 가 올 때만 쓴다 — 없으면 저장만 건너뛴다 |
| 코드서빙 #4 | `FAQ_DEFAULT_COUNT`(5) · `FAQ_MAX_COUNT`(30) | ◻ | 캔버스가 개수를 안 줬을 때 · 배포 상한 |
| 코드서빙 #4 | `FAQ_MAX_CONTEXT_CHARS`(12000) · `FAQ_MAX_CHUNK_CHARS`(40000) · `FAQ_LLM_CONCURRENCY`(6) | ◻ | 조각 크기 하한 · 상한(LLM 한 번에 실을 길이) · 동시 구간 수 |
| 코드서빙 넷 | `LLM_REASONING_EFFORT`(none) | ◻ | LLM 요청의 `reasoning_effort`. 비우면 싣지 않는다 |
| 코드서빙 #4 | `FAQ_EVIDENCE_MIN_RATIO`(0.8) · `FAQ_EVIDENCE_REJECT`(1) | ◻ | 근거 일치 기준 · 미달 항목을 버릴지(기본 버림) |
| 코드서빙 #4 | `FAQ_PROMPT_IDS` · `FAQ_ADMIN_TOKEN` · `FAQ_SESSION_TTL_HOURS` · `FAQ_REDIS_PREFIX` · `FAQ_MAX_UPLOAD_BYTES` · `FAQ_PROMPT_TIMEOUT` | ◻ | 프롬프트 · 관리 토큰 · 세션 · 업로드 상한 |

## 5. 안내 문구 (Disclaimer MCP) — 006 · 글다듬이 · 번역 · FAQ 워크플로우

| 변수 | | 뜻 |
|---|---|---|
| `DISCLAIMER_MCP_ID` | ◻ | Disclaimer MCP 등록 ID (도구 `widget_disclaimer`) |

문구는 워크플로우가 아니라 **Disclaimer MCP 도구의 환경변수** `MCP_TOOL_19_{SFR018|SFR006}_{번호}` 에 둔다.
번호와 문구는 [`disclaimer.md`](disclaimer.md). 문구를 못 받으면 `disclaimer` 맨 앞에 확인 불가 문장이
붙는다(`event=disclaimer_unavailable`).
