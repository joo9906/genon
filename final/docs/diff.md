# `1030.zip` 과 현재 `final/` 의 차이

비교 기준: 저장소 루트의 `1030.zip`(`final/` 전체, 220개 항목) ↔ 현재 작업 트리 `final/`.
줄바꿈(CRLF/LF) 차이는 빼고 내용만 대조했다(`diff -r --strip-trailing-cr`).

## 요약

**내용이 다른 것은 두 묶음이다.**

1. **내려받는 md 파일의 모양** — 세 기능(FAQ · 글다듬이 · 번역)의 md 맨 위에 열람 안내를 붙였고,
   FAQ 파일 본문에서 `# 제목` 줄을 뺐다. (§1 · §2)
2. **번역 용어사전 적재 API 전환** — AI 드라이브 용어사전(`/data/ai-drive/…`)에서 독립 용어사전
   (`/data/glossaries/{id}/…`)으로 바꿨다. 기준은 루트 `load_glossary.py`. (§3)

그 밖의 코드 · 프롬프트 · 워크플로우 · 전처리기는 zip 과 같다.

| 묶음 | 구분 | 파일 | 내용 |
|---|---|---|---|
| md | 코드 | `SFR-018-faq/request/faq/md_output.py` | `GUIDE` 상수 추가, `to_bytes` 가 맨 위에 붙인다 |
| md | 코드 | `SFR-018-polish/request/text_polish/md_output.py` | 위와 같은 사본 |
| md | 코드 | `SFR-018-translate/request/translation_pipeline/common/md_output.py` | 위와 같은 사본 |
| md | 코드 | `SFR-018-faq/request/faq/formatting.py` | `rows_to_markdown` 에서 `title` 인자와 `# 제목` 줄 제거 |
| md | 코드 | `SFR-018-faq/request/main.py` | `rows_to_markdown` 호출 두 곳에서 `title=` 제거 |
| md | 문서 | `CLAUDE.md` · `docs/FEATURES.md` · `docs/README.md` · `docs/SFR-018_md_output.md` | 파일 모양 설명을 위에 맞춤 |
| md | 점검 | `Test/check/check_unit_endpoints.py` (zip 밖) | 기대값을 새 파일 모양에 맞춤 |
| 용어사전 | 코드 | `SFR-018-translate/request/translation_pipeline/common/glossary_store.py` | 적재부 다시 씀 (새 API · 속성 매핑) |
| 용어사전 | 코드 | `mcp/genon_glossary.py` | 위와 같은 규칙의 MCP 사본 |
| 용어사전 | 코드 | `SFR-018-translate/request/config.py` · `open_ai/config.py` | 환경변수 교체 (두 파일 같은 변경) |
| 용어사전 | 코드 | `SFR-018-translate/request/main.py` | `_load_glossary` 가 넘기는 인자 |
| 용어사전 | 문서 | `CLAUDE.md` · `README.md` · `docs/README.md` · `docs/env.md` · `docs/ONPREM.md` · `docs/SERVING_REGISTRY.md` · `docs/DESIGN_NOTES.md` | 환경변수 · 엔드포인트 · 매핑 설명 |
| 용어사전 | 점검 | `Test/SFR-018/tests/test_glossary_policy.py` · `Test/check/check_mcp_tools.py` · `Test/check/check_integration.py` · `Test/run_all.py` (zip 밖) | 새 API 모양 · 환경변수 · 건수 |

## 1. 내려받는 md 의 모양

### 순서

세 기능 모두 다음 순서다.

```
열람 안내 (GUIDE)
---
> 안내문(disclaimer) — 있을 때만
본문 (번역문 · 다듬은 글 · FAQ 문답)
```

| 기능 | zip | 현재 |
|---|---|---|
| FAQ | `# 제목` → 안내문 → 문답 | 열람 안내 → 안내문 → 문답 |
| 글다듬이 | 안내문 → 본문 | 열람 안내 → 안내문 → 본문 |
| 번역 | 안내문 → 본문 | 열람 안내 → 안내문 → 본문 |

### 열람 안내 (`md_output.GUIDE`)

```
이 파일은 마크다운(.md) 형식입니다. 마크다운 뷰어에서 열면 서식이 적용되어 보이고,
메모장에서는 `#`, `**`, `>` 같은 기호가 그대로 보입니다.

---
```

- **붙이는 자리는 `md_output.to_bytes` 한 곳이다.** 내려받는 파일은 모두 이 함수를 지나므로
  업로드(`download_url`)와 `POST /download` 폴백 어느 경로로 받아도 빠지지 않는다.
  ```python
  normalized = (GUIDE + (text or "")).replace("\r\n", "\n").replace("\r", "\n")
  ```
- **모듈 상수다. 환경변수로 바꾸지 않는다.** 문구를 바꿀 때는 `md_output.py` 세 벌을 함께
  고친다 — 어긋나도 오류가 나지 않고 기능마다 파일 맨 위가 달라질 뿐이다.
- 줄바꿈은 LF 로 쓰고 CRLF 변환은 `to_bytes` 가 한다. 끝의 빈 줄은 뒤따르는 안내문 인용
  블록이 이 문단에 붙지 않게 하는 것이다.
- 화면에 나가는 `markdown` 에는 붙지 않는다(`to_bytes` 를 지나지 않는다).

### FAQ 제목

- `faq_title`(프론트 → 스텝 1 → 스텝 2 → 서빙 `title`)은 그대로 받는다. 프론트가 보내지 않는다.
- **파일 본문에는 넣지 않는다.** 파일명(`safe_stem(title, "FAQ")`)에만 쓰고, 비면 `FAQ.md` 다.
- 세션 저장(`save_faqs(..., title=)`)과 `/download` 의 `title` 도 파일명용으로 그대로 남아 있다.

## 2. md 점검 (`Test/check/check_unit_endpoints.py`)

zip 밖이지만 위 변경으로 기대값이 바뀌어 함께 고쳤다. 건수(137)는 그대로다.

- `_after_guide(text)` 추가 — `\n---\n` 앞에 안내가 있으면 그 아래 본문을, 없으면 빈 문자열을 준다.
- **마크다운 기호 보존**: "열람 안내 아래가 받은 마크다운 글자 그대로"인지 본다. 안내가 빠져도 FAIL 한다.
- **FAQ 제목**: "제목이 첫 줄 `#` 머리로 들어간다" → "제목은 본문에 넣지 않는다(열람 안내 아래가
  바로 `**Q1.`)" 로 바꿨다.

## 3. 번역 용어사전 적재 API 전환

### 옮기는 법

**코드 5개는 파일을 통째로 덮어써도 된다.** zip 과의 차이가 이 변경뿐이다(`diff` 로 확인).

| 파일 | 옮기는 법 |
|---|---|
| `SFR-018-translate/request/translation_pipeline/common/glossary_store.py` | 통째로 교체 (거의 새로 썼다) |
| `mcp/genon_glossary.py` | 통째로 교체 (아래 두 구간 + 머리 주석만 바뀜) |
| `SFR-018-translate/request/config.py` | 통째로 교체 또는 아래 diff |
| `SFR-018-translate/open_ai/config.py` | 위와 **같은 diff** (용어사전 절만) |
| `SFR-018-translate/request/main.py` | 통째로 교체 또는 아래 diff (한 곳) |

문서는 §1 의 md 변경과 같은 파일에 섞여 있으니(`CLAUDE.md` · `docs/README.md`) 통째로 옮길 때
두 변경이 함께 간다.

### 무엇이 바뀌었나

| | zip (`1030`) | 현재 |
|---|---|---|
| 엔드포인트 | `GET {URL}/data/ai-drive/{drive_id}/glossary/terms` | `GET {URL}/data/glossaries/{id}/attributes` → `GET {URL}/data/glossaries/{id}/terms` |
| 헤더 | `Authorization` + `x-genos-workspace-id` | `Authorization` + `Accept: application/json` |
| 응답 | `items`/`data`/`list`/최상위 배열 아무거나 | 래퍼 `{code, message, data}` — `code` ≠ 0 이면 실패. 속성 `data.items`, 용어 `data.list` + `total_count` |
| 한국어 | 항목의 `term`(용어명) | 이름이 `ko` 인 속성, **없으면 대표어**(`is_representative`) |
| 영어 | 항목의 `description`(설명) | 이름이 `en` 인 속성 (`values[키]`, `text[]` 면 첫 비어 있지 않은 값) |
| 거르는 규칙 | 용어명 30자 · 금지문자 · 설명 500자 · 중복 · 2,000건 상한 | 한국어 빈 값 · 영어 빈 값 · 같은 한국어 중복만 (상한 없음 — 색인 쪽 `disabled_over_limit` 는 그대로) |
| 기각 사유 코드 | `term_empty` · `term_too_long` · `term_forbidden_char` · `description_empty` · `description_too_long` · `duplicate_term` · `not_an_object` | `ko_empty` · `en_empty` · `duplicate_ko` · `not_an_object` |
| 페이지 상한 | 50 | 500 |
| 적재 실패 `reason` | `not_configured` · `fetch_failed` · `fetch_failed_{HTTP}` · `empty` | 왼쪽 + **`invalid_response`**(JSON 아님 · 래퍼 `code` ≠ 0) + **`attribute_not_found`**(ko/en 속성 못 찾음) |
| MCP HTTP 오류 사유 | `fetch_failed` 로 뭉뚱그림 | 코드서빙과 같이 `fetch_failed_{HTTP}` |

**바뀌지 않은 것**: 양방향 색인(`en`: 한국어→영어, `ko`: 영어→한국어), 매칭(`glossary_exact`),
프롬프트 용어 절, 준수율 · 하이라이트, `status()` · `language_status()` 모양, `GET /glossary` ·
`POST /glossary/reload`, MCP 도구 세 개의 입출력.

### 환경변수 (코드서빙 · MCP 공용 — 같은 값을 넣는다)

| 이름 | zip | 현재 |
|---|---|---|
| `TRANSLATE_GLOSSARY_API_URL` | 필수 | **선택** — 비우면 `https://genos.genon.ai/api/admin` |
| `TRANSLATE_GLOSSARY_DRIVE_ID` | 필수 | **삭제** |
| `TRANSLATE_GLOSSARY_WORKSPACE_ID` | 필수 | **삭제** |
| `TRANSLATE_GLOSSARY_ID` | — | **신규 · 필수** (없으면 `not_configured`) |
| `TRANSLATE_GLOSSARY_TOKEN` | 선택 (없으면 `GENOS_TOKEN`) | 그대로 |
| `TRANSLATE_GLOSSARY_KO_ATTR` | — | 신규 · 선택 (기본 `ko`, 그런 속성이 없으면 대표어) |
| `TRANSLATE_GLOSSARY_EN_ATTR` | — | 신규 · 선택 (기본 `en`) |

> ⚠ 기본 URL 이 생겨서 **id 만 넣으면 적재를 시도한다.** 폐쇄망이면 `TRANSLATE_GLOSSARY_API_URL`
> 을 내부 주소로 꼭 넣는다 — 안 넣으면 `fetch_failed` 로 나간다(번역은 사전 없이 계속된다).

사전 쪽 준비: 용어사전에 속성 `en`(text) 을 만들고 **대표어에 한국어, `en` 에 영어**를 넣는다.
용어 추가는 변경 승인을 거치므로 승인 뒤에 `POST /glossary/reload`(MCP 는 `glossary_reload`).

### `config.py` (두 벌 같은 diff)

```diff
     # ── 용어사전 (요구사항 §2 — 주어지는 용어사전을 기반으로 번역) ──
     #
-    # **GenOS AI 드라이브 용어사전 API 에서 받는다.** 관리 화면에서 등록한 용어가
-    # 곧바로 반영되고, 볼륨에 파일을 따로 올릴 필요가 없다.
-    # 셋 중 하나라도 비면 용어사전 없이 번역하고 그 사실을 `glossary.source` 로 노출한다.
+    # **GenOS 독립 용어사전(`데이터 > 용어사전`) API 에서 받는다.** 관리 화면에서 등록한
+    # 용어가 곧바로 반영되고, 볼륨에 파일을 따로 올릴 필요가 없다.
+    # 용어사전 id 가 비면 용어사전 없이 번역하고 그 사실을 `glossary.source` 로 노출한다.
     #
     # 값은 호출 시점에 읽는다 — 게이트웨이 설정과 같은 이유다(위 절 참고).
     @staticmethod
     def glossary_api_url() -> str:
-        """admin-api 베이스 URL. 예: `https://admin-api.genos.internal`"""
-        return os.environ.get("TRANSLATE_GLOSSARY_API_URL", "").strip().rstrip("/")
+        """admin-api 베이스 URL. 비우면 `https://genos.genon.ai/api/admin`."""
+        return (os.environ.get("TRANSLATE_GLOSSARY_API_URL", "").strip()
+                or "https://genos.genon.ai/api/admin").rstrip("/")
 
     @staticmethod
-    def glossary_drive_id() -> str:
-        """용어를 등록해 둔 AI 드라이브 id."""
-        return os.environ.get("TRANSLATE_GLOSSARY_DRIVE_ID", "").strip()
-
-    @staticmethod
-    def glossary_workspace_id() -> str:
-        """`x-genos-workspace-id` 헤더 값. admin-api 가 항상 요구한다."""
-        return os.environ.get("TRANSLATE_GLOSSARY_WORKSPACE_ID", "").strip()
+    def glossary_id() -> str:
+        """용어사전 id (`/data/glossaries/{id}`)."""
+        return os.environ.get("TRANSLATE_GLOSSARY_ID", "").strip()
 
     @staticmethod
     def glossary_token() -> str:
@@ (glossary_token 은 그대로, 그 아래에 추가) @@
         return (os.environ.get("TRANSLATE_GLOSSARY_TOKEN", "").strip()
                 or os.environ.get("GENOS_TOKEN", "").strip())
 
+    @staticmethod
+    def glossary_ko_attr() -> str:
+        """한국어로 읽을 속성 이름. 그런 속성이 없으면 대표어를 쓴다."""
+        return os.environ.get("TRANSLATE_GLOSSARY_KO_ATTR", "").strip() or "ko"
+
+    @staticmethod
+    def glossary_en_attr() -> str:
+        """영어로 읽을 속성 이름."""
+        return os.environ.get("TRANSLATE_GLOSSARY_EN_ATTR", "").strip() or "en"
+
     # ── 품질 장치 ──
```

### `SFR-018-translate/request/main.py` — `_load_glossary`

```diff
     두 자리에서 각각 인자를 조립하면 한쪽만 고쳤을 때 **기동은 되는데 재적재만 다른
-    드라이브를 보는** 상태가 된다. 조용히 틀리는 종류라 함수 하나로 묶었다.
+    사전을 보는** 상태가 된다. 조용히 틀리는 종류라 함수 하나로 묶었다.
     """
     return await glossary_store.load_from_admin_api(
         Config.glossary_api_url(),
-        Config.glossary_drive_id(),
-        Config.glossary_workspace_id(),
+        Config.glossary_id(),
         Config.glossary_token(),
+        Config.glossary_ko_attr(),
+        Config.glossary_en_attr(),
     )
```

### `glossary_store.py` — 함수 단위

시그니처가 바뀌었다:
`load_from_admin_api(base_url, drive_id, workspace_id, token)` →
**`load_from_admin_api(api_url, glossary_id, token, ko_attr="ko", en_attr="en")`**
(예외를 던지지 않는 계약은 그대로).

| zip | 현재 |
|---|---|
| `_MAX_TERM_CHARS` · `_MAX_DESCRIPTION_CHARS` · `_MAX_TERMS` · `_FORBIDDEN_CHARS` | 삭제 |
| `_endpoint()` | `_base()` — `…/data/glossaries/{id}` |
| `_fetch_items()` (응답 모양 아무거나) | `_get_data()`(래퍼 검사) + `_fetch()` → `(attributes, items)` |
| — | `_LoadError(reason, upstream_status)` — 사유를 그대로 `status()["reason"]` 으로 |
| — | `_attr_key()` · `_resolve_keys()` — 속성 이름 → 키, ko 없으면 대표어 |
| — | `_text()` — `text[]` 면 첫 비어 있지 않은 값 |
| `_valid_pair()` + `_pairs_from_items(items)` | `_pairs_from_items(items, ko_key, en_key)` (빈 값 · 중복만) |
| 실패 로그 두 벌(`HTTPStatusError` / 그 밖) | `_fail(reason, **fields)` 한 곳 — `event=glossary_fetch_failed`, `status=disabled,reason=…` |
| `_index_pairs` · `status` · `language_status` | 그대로 |

### `mcp/genon_glossary.py` — 바뀐 구간

통째로 교체하지 않고 손으로 옮길 때는 세 군데다.

1. **파일 머리 주석** `## 적재는 …` 절 — 엔드포인트 두 줄과 "이름이 `ko`·`en` 인 속성(없으면 대표어)" 으로.
2. **`# ── 적재: GenOS AI 드라이브 용어사전 API` 부터 `# ── 언어 코드 정규화` 직전까지** —
   주석을 새 API 로, 상수에서 `_GLMAX_TERM_CHARS` · `_GLMAX_DESCRIPTION_CHARS` · `_GLMAX_TERMS` ·
   `_GLFORBIDDEN_CHARS` 삭제, `_GLDEFAULT_API_URL` 추가, `_GLMAX_PAGES` 50 → 500.
3. **`def _GLvalid_pair(` 부터 `def glstatus()` 직전까지** — 현재 파일의 같은 구간으로 바꾼다.
   들어 있는 것: `_GLLoadError` · `_GLget_data` · `_GLfetch` · `_GLattr_key` · `_GLresolve_keys` ·
   `_GLtext` · `_GLpairs_from_items(items, ko_key, en_key)` · `_GLapi_settings` · `_GLfail` ·
   `glload_from_admin_api(api_url, glossary_id, token, ko_attr, en_attr)`.
   - `_GLapi_settings()` 는 이제 **5-튜플** `(api_url, glossary_id, token, ko_attr, en_attr)` 를
     돌려주고, `TRANSLATE_GLOSSARY_ID` 가 없을 때만 `None` 이다. 호출부 `_gl_ensure_loaded` 는
     `glload_from_admin_api(*settings)` 라 고칠 것이 없다.
   - 모든 새 최상위 이름에 `GL` 접두어가 붙어 있다(`check_mcp_tools` 접두어 규율).

### 점검 (zip 밖)

| 파일 | 변경 |
|---|---|
| `Test/SFR-018/tests/test_glossary_policy.py` | `GlossaryAdminApiLoadTest` 를 새 API 모양으로 다시 씀 — 6건 → **9건** (대표어 · `ko` 속성 우선 · 양방향 · 빈 값/중복 필터 · 속성 부재 · 설정 부재 · 403 · 래퍼 오류 · 언어 상태) |
| `Test/run_all.py` | `EXPECTED["SFR-018"]` 399 → **402** |
| `Test/check/check_mcp_tools.py` | 걷어내는 환경변수 목록을 `_API_URL` · `_ID` · `_TOKEN` · `_KO_ATTR` · `_EN_ATTR` 로 |
| `Test/check/check_integration.py` | `_CLEAR_ENV` 의 `_DRIVE_ID` · `_WORKSPACE_ID` → `_ID` |

결과: `SFR-018` 402/402 · `check_mcp_tools` 99/99 · `check_unit_endpoints` 137/137 ·
`check_service_boot` · `check_deploy_contract` 통과. 실제 GenOS API 에는 붙여 보지 않았다(대역 transport 로만 확인).

## 4. 내용 차이가 아닌 것

- **SFR-006 스타일 프롬프트 3개** (`SFR-006/prompt/SFR-006_template_fill/style__공문.md` ·
  `style__보고서.md` · `style__보도자료.md`): zip 안에서는 파일명이 `style__ъ│╡ым╕.md` 처럼
  깨져 보인다. zip 이 파일명을 UTF-8 표시 없이 담아서 생긴 것이고, **내용은 바이트 단위로 같다.**
  zip 을 풀어 쓸 때는 파일명을 바로잡아야 프롬프트 로더가 찾는다.
- **줄바꿈만 다른 파일 7개**: zip 과 작업 트리는 CRLF, 저장소(`HEAD`)는 LF 다(`.gitattributes`
  정책). `SFR-006/request/template_fill/chat_reply.py` · `config.py` · `prompts.py`,
  `SFR-018-translate/request/translation_pipeline/office/units.py`, `docs/architect.html`,
  `workflow/sfr018_polish_02_polish.py` · `sfr018_translate_02_translate.py`. 내용은 같다.
- `SFR-018-faq/request/faq/md_output.py` 의 `safe_stem` 아래 공백만 있는 줄 한 줄은 이 작업 전부터
  있던 미커밋 변경이다.

## 5. 이 비교와 무관하게 지금 FAIL 인 점검

zip 상태(이번 변경 전)에서도 똑같이 FAIL 이다.

| 점검 | 내용 |
|---|---|
| `check_workflow_run` 10건 | 안내문 번호 기대값 어긋남(`SFR018_31` ↔ `33`), `faq_download_failed` KeyError, 입력 판단 등 |
| `check_high_preprocessor` 2건 | 2단 PDF 의 전폭 표 위치 · 그림 블록 순서 |
| `check_integration` 2건 | 뜻 없는 입력에서 스텝 1 이 `INPUT_UNUSABLE` 로 멈추지 않음 |
| `check_prompt_render` | 건수 108, `EXPECTED` 는 102 |
