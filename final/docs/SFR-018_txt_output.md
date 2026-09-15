# SFR-018 산출물 txt 통일 — 파일·함수 단위 변경 내역 (2026-08-12)

> **후속 (2026-08-28).** 아래 `POST /download`(본문 왕복) 는 **주 경로가 아니다.**
> 세 단위가 결과를 만들 때 txt 를 굳혀 GenOS MinIO 에 올리고 `download_url` 만 낸다
> (`file_store.py`, 사본 3벌). 이 라우트는 CDN 업로드가 안 되는 배포를 위한 폴백으로
> 남아 있다. 근거는 `change_0828.md`. txt 규약(BOM+CRLF·강조 제거)은 그대로다.

> **무엇이 바뀌었나**: 글다듬이·번역·FAQ 세 기능의 **최종 산출물이 화면 텍스트 + `.txt`
> 파일 하나**로 통일됐다. FAQ 에 있던 **hwpx·pdf·xlsx 내보내기를 전부 걷어냈고**, 번역과
> 글다듬이에는 **`POST /download` 를 새로 붙였다.**
>
> **입력·화면은 그대로다.** hwpx 직접 파싱, 전처리기 마크다운, 업로드 상한, UI 마크다운
> 표시, 근거 명시, 용어사전 하이라이트, 구조 보존 계약 — 전부 손대지 않았다.
> 달라진 것은 **마지막 산출 형식**뿐이다.
>
> **SFR-006 은 무관하다.** 006 은 사내 hwpx 양식을 채우는 것이 기능 자체라 hwpx/PDF 를
> 그대로 낸다.
>
> 걷어낸 코드: **`archive/sfr018-doc-export` 브랜치** (이 변경 직전 커밋).
> 되살릴 때는 `git show archive/sfr018-doc-export:<경로>` 로 꺼낸다.

---

## 1. 왜 이렇게 했나 (판단 근거)

**요구가 바뀌었다.** 사용자가 결과 파일을 **윈도우 메모장에서 이어 편집**하기로 했다.
문서 형식(hwpx/pdf/xlsx)은 그 흐름에서 쓰이지 않는다.

그래서 걷어내는 쪽이 단순히 "덜 만드는" 것이 아니라 **위험을 없애는** 일이었다:

| 걷어낸 것 | 그것이 안고 있던 문제 |
|---|---|
| hwpx 내보내기 | 관리자 템플릿 실물이 **없어서 한 번도 검증하지 못한 경로**였다. 백지 조립은 `header.xml` 한 글자 차이로 한/글이 문서를 못 여는데 확인할 한/글이 없다 |
| pdf 내보내기 | `weasyprint` 는 시스템 라이브러리(pango/cairo)+한글 폰트가 이미지에 있어야 하고, 대안 경로는 `genon.preprocessor`(기본 이미지 변경 절차)에 묶여 있었다 |
| xlsx 내보내기 | 유일하게 환경에 안 걸리는 형식이었지만, 형식이 하나 남으면 "형식 가용성 판별·501 분기" 전체가 무의미해진다 |

**txt 는 환경을 요구하지 않는다.** 볼륨·외부 변환기·시스템 라이브러리·폰트가 전부
필요 없다. 그래서 이 변경으로 **"어떤 배포에서는 그 버튼이 501" 이라는 상태가 사라졌다.**

## 2. txt 규약 — BOM + CRLF (환경변수 스위치 없음)

파일이 **메모장에서 열린다**는 것이 유일한 목표다.

- **UTF-8 BOM**: BOM 이 없으면 옛 메모장은 파일을 ANSI(cp949)로 읽어 **한글이 깨진다.**
- **CRLF**: 1809 이전 메모장은 LF 만 있는 파일의 줄바꿈을 렌더하지 못해 **전체가 한 줄로**
  붙어 보인다.

폐쇄망 사내 PC 의 윈도우 빌드를 통제할 수 없으므로 둘 다 붙이고, **환경변수로 끄지
않는다** — 스위치를 두면 "어떤 PC 에서만 깨진다"가 되고 그 상태는 로그에 아무 흔적도
남기지 않는다(재현 불가한 제보만 남는다).

### 본문을 평문으로 풀지 말 것 — 기준은 "그 기호를 누가 넣었나"

| 단위 | 파일 본문 | 이유 |
|---|---|---|
| FAQ | **평문으로 바꾼다** (`**Q1.**`→`Q1.`, `> 근거:`→`[근거]`) | 그 기호는 **우리가** 붙인 장식이다. 메모장에서 별표·꺾쇠가 글자로 보인다 |
| 번역 | **받은 그대로** | 표·머리글은 **원본 문서에서 온 구조**다. "구조는 입력과 동일" 이 이 단위의 계약인데, 파일에서 풀면 지켜낸 구조를 마지막 단계에서 우리가 깨뜨린다 |
| 글다듬이 | **받은 그대로** | 같은 이유. `markdown_guard` 가 지문으로 대조해 지켜낸 그 구조다 |

### 줄 **중간**의 강조는 뗀다 (2026-08-14 추가)

위 표는 "구조를 풀지 말 것" 이고, 이 규칙은 그 **안쪽**이다 — 구조가 아닌 **인라인 강조**
(`**단어**`·`*단어*`·`__단어__`·`_단어_`·`` `단어` ``)만 기호를 떼고 글자는 남긴다.
메모장에는 렌더러가 없어 별표가 그대로 보이기 때문이다.

떼지 않는 것이 더 중요하다:

| 남긴다 | 왜 |
|---|---|
| 줄머리 기호 `#` `-` `>` `1.` | 구조다. 지우면 문서 모양이 무너지고 사용자가 되살릴 수 없다 |
| 표의 `\|` 와 구분선 | 격자다 |
| **줄 전체를 감싼 강조** (`**2026년 실적**` 한 줄) | 제목으로 쓴 것이라 기호가 곧 위계 표시다 |
| 코드펜스(```` ``` ````) 블록 안 | 거기서 `*`·`_` 는 코드의 일부다 |
| `snake_case` 의 `_` | 강조로 오인하면 식별자가 깨진다 (앞뒤가 단어 문자면 건드리지 않는다) |

**화면에는 적용하지 않는다** — 렌더러가 굵게 보여주므로 뗄 이유가 없고, 떼면 원문이
강조한 단어를 잃는다. 적용 지점은 `txt_output.to_bytes` **한 곳**이고(세 단위 사본 공통),
호출부가 각자 부르는 형태로 두면 한 곳이 빠져도 아무도 모른다.

---

## 3. FAQ (`onprem/codeserving/SFR-018_faq`)

### 3-1. 삭제한 파일 6개 (약 1,000줄)

| 파일 | 무엇이었나 |
|---|---|
| `faq/exporters/__init__.py` | 세 형식의 성질 표 + 예외 재노출 |
| `faq/exporters/errors.py` | `ExportError` / `ExporterUnavailable` |
| `faq/exporters/hwpx_export.py` | 관리자 템플릿 반복 블록 `deepcopy` |
| `faq/exporters/pdf_export.py` | 마크다운→weasyprint, hwpx→전처리기 변환기 |
| `faq/exporters/xlsx_export.py` | openpyxl 표 조립 + 수식 인젝션 방지 |
| `faq/download_formats.py` | `FORMATS` / `available_formats()` / `build_bytes()` 디스패치 |

### 3-2. 새로 만든 파일

| 파일 | 함수 | 하는 일 |
|---|---|---|
| `faq/txt_output.py` | `to_bytes` | 줄바꿈 CRLF 통일 + UTF-8 BOM. 입력에 CRLF 가 섞여 있어도 **먼저 LF 로 접었다가** 펴서 `\r\r\n` 을 만들지 않는다 |
| | `safe_stem` | 제목 → 파일명 본체. 윈도우 금지 문자·경로 구분자·제어문자 제거, 공백 접기, 80자 절단, 비면 기본값 |
| | `content_disposition` | RFC 5987 (`filename*=UTF-8''…`). ASCII `filename=` 을 **함께 주지 않는다** — 브라우저가 그쪽을 골라 깨진 이름으로 저장하는 것을 막는다 |
| | `headers` | 위 헤더 + 호출부가 주는 추가 헤더 병합 |
| | `MEDIA_TYPE`·`EXTENSION` | `text/plain; charset=utf-8` · `txt` |

### 3-3. 고친 함수

| 파일 | 함수 | 변경 |
|---|---|---|
| `faq/main.py` | `_lifespan` | **형식 가용성 판별 제거.** `_FORMATS_CACHE = _available_formats()` 와 hwpx 템플릿 미등록 경고(`hwpx_template_missing`)를 뺐다. 기동 로그와 `admin_token_missing` 경고만 남는다 |
| | `service_config` (`GET /config`) | `formats` 가 캐시 대신 `list(_FORMATS)` — **항상 `["txt"]`**. 배열 모양은 UI 계약이라 유지 |
| | `get_faqs` (`GET /faqs`) | 같은 이유로 `formats` 를 `list(_FORMATS)` 로 |
| | `download` (`POST /download`) | 형식 판정을 `_FORMATS`(=`["txt"]`) 로. `_build_bytes`/`asyncio.to_thread` → `txt_output.to_bytes(rows_to_plain_text(...))`. `ExporterUnavailable`/`ExportError` 처리 삭제. 파일명은 `safe_stem`, 헤더는 `txt_output.headers`. **옛 형식 이름은 400 으로 거절**한다 |
| | 모듈 상수 | `_FORMATS_CACHE: list = []` → `_FORMATS = [txt_output.EXTENSION]`. `urllib.parse` import 제거(파일명 인코딩이 `txt_output` 으로 갔다) |
| `faq/formatting.py` | `_flat` **(신규)** | 근거의 줄바꿈·연속 공백 접기. 화면·파일이 **같은 평탄화**를 쓴다 |
| | `_render` | 위 평탄화를 `_flat` 으로 위임 (동작 동일) |
| | `_render_plain` **(신규)** | 파일용 평문 조립: `Q{n}. 질문` / 답변 / `[근거] …`, 항목 사이 40자 구분선, 제목이 있으면 첫 줄. 줄바꿈은 LF 로 만든다 — **CRLF 변환은 `txt_output.to_bytes` 한 곳에서만** 한다 |
| | `_as_tuples` **(신규)** | 저장된 평면 형태 → 튜플 목록. **화면·파일이 공유**해 내용이 갈리지 않게 |
| | `rows_to_markdown` | 내부를 `_as_tuples` 로 (동작 동일). **2026-08-14 에 지웠다** — `/faqs` 는 항목 배열을 내고 화면 마크다운은 `render_markdown` 이 만들어, 이 함수는 아무도 부르지 않았다 |
| | `rows_to_plain_text` **(신규)** | 다운로드가 쓰는 유일한 조립 함수 |
| | `to_export_rows` | 동작 그대로. `sources` 키 이름을 **바꾸지 않는 이유**를 주석으로 남겼다 — 이미 저장된 세션이 그 이름이라, 바꾸면 배포 시점 진행 중인 대화의 다운로드가 빈 근거로 나간다 |
| `faq/error_codes.py` | — | `ERR_API_EXPORT_UNAVAILABLE`(501) · `ERR_API_EXPORT_FAILED`(500) **삭제**. txt 는 "환경 때문에 못 만든다"가 성립하지 않고, 실패하면 우리 버그이므로 `ERR_API_INTERNAL` 로 올린다 |
| `faq/config.py` | `Config` | `HWPX_TEMPLATE_PATH`(`FAQ_HWPX_TEMPLATE_PATH`) **삭제**. 배포에 남아 있어도 무해하다(코드가 읽지 않는다) |
| `faq/api_contract.py` | `DownloadRequest` | `format` 이 **필수 → 선택**(기본 `"txt"`, `max_length=16`) |
| `faq/session_store.py` | 머리말 | "hwpx 로 받고 다시 xlsx 로" → 형식이 하나가 된 뒤에도 **세션을 지우지 않는 이유**(두 번째 클릭)로 다시 적었다 |
| `faq/hwpx_xml.py`·`hwpx_text.py` | 머리말 | 삭제된 `exporters/hwpx_export` 참조 정리. **입력 전용**임을 명시 |
| `requirements.txt` | — | `openpyxl` 삭제, weasyprint/markdown 선택 의존 절 삭제. **선택 의존 0개** |

---

## 4. 번역 (`onprem/codeserving/SFR-018_translation`)

| 파일 | 함수 | 변경 |
|---|---|---|
| `translation_pipeline/common/txt_output.py` | — | **신규.** FAQ 사본과 **바이트 단위로 동일** (단위 간 import 금지) |
| `api_contract.py` | `DownloadRequest` **(신규)** | `text` / `markdown` / `title` + `body()`. 두 필드를 받는 이유는 **응답 필드 이름이 경로마다 다르기 때문**(`/translate`=`text`, 마크다운·hwpx=`markdown`) — 화면이 방금 받은 값을 그대로 되돌려 보낼 수 있어야 이름을 옮겨 적는 층이 안 생긴다 |
| `main.py` | `download` **(신규 라우트 `POST /download`)** | 본문 없으면 400, `MAX_TOTAL_CHARS` 초과 400. 상태 없이 인코딩만 한다. **본문은 손대지 않는다**(표를 평문으로 풀지 않는다) |
| | import | `Response`·`DownloadRequest`·`txt_output` 추가 |

## 5. 글다듬이 (`onprem/codeserving/SFR-018_text_polish`)

| 파일 | 함수 | 변경 |
|---|---|---|
| `text_polish/txt_output.py` | — | **신규.** 위 두 사본과 동일 |
| `main.py` | `DownloadRequest` **(신규)** | `text` / `polished_text` / `title` + `body()` |
| | `download` **(신규 라우트 `POST /download`)** | `_MAX_INPUT_CHARS` 상한을 `/polish` 와 공유. 반환 타입 주석을 붙이지 않는다(성공/오류 형이 갈리는 라우트 — Union 주석은 기동 실패를 만든다) |
| | `index` (`GET /`) | `endpoints` 에 `/download` 추가 |

## 6. 워크플로우 (`onprem/workflow`)

| 파일 | 변경 |
|---|---|
| `sfr018_translate_02_translate.py` | **버그 수정.** `run()` 이 코드서빙 응답에서 `translated_markdown` 을 읽고 있었는데 그 키는 응답에 없다(`api_contract.markdown_payload` 는 `markdown` 을 낸다) — **번역이 매번 "결과가 비어 있음"으로 끝나고 있었다.** `markdown` 우선, 옛 이름은 폴백으로 함께 본다. 캔버스로 내보내는 값 이름(`translated_markdown`)은 유지 |
| | 머리말 + `result` 주석: 파일은 스텝이 만들지 않는다(화면 버튼이 `POST /download` 를 직접 부른다). 되돌려 보낼 값은 **경고문이 붙은 `text` 가 아니라 번역문**이다 |
| `sfr018_polish_02_polish.py` | 머리말에 같은 내용 추가. 되돌려 보낼 값은 `polished_text`(경고문과 **`<mark>` 태그**가 붙은 `text` 가 아니다 — 2026-08-27에 하단 변경내역 목록이 본문 하이라이트로 바뀌면서 섞이는 것이 목록에서 태그로 달라졌다) |
| `sfr018_faq_02_generate.py` | 머리말: 형식이 txt 하나가 됐어도 `faq_download_ready`(세션 저장 성공 여부)는 여전히 필요하다 — "화면엔 있는데 파일은 없는" 경우가 그대로 남기 때문이다 |

## 7. 점검 (`onprem/test`)

| 파일 | 변경 |
|---|---|
| `check_unit_endpoints.py` | **11건 → 31건.** 대상이 2단위 → **3단위**(글다듬이 추가). `_check_translation`·`_check_faq` 시그니처에 `probe` 추가, `_check_text_polish` **신규**, `_txt_probe` **신규**(응답에서 BOM·CRLF·헤더·파일명 사실만 뽑는다), `_check_txt_contract` **신규**(세 단위 결과를 **바이트로 대조** — 규약 6개 + 응답 수). FAQ 의 xlsx 생성 판정은 **txt 생성 + 평문 여부 + 제목 첫 줄 + 옛 형식 3종 거절**로 교체 |
| `check_deploy_contract.py` | `_guarded_import_nodes` 머리말에서 weasyprint·openpyxl 예시 정리(그 방어가 없어졌다). **판정 로직은 그대로** |

**전부 통과 상태**: `check_deploy_contract` FAIL 0 / WARN 4(5→4, FAQ 의 `genon` WARN 소멸) ·
`check_service_boot` 16 · `check_workflow_run` 35 · `check_mcp_tools` 37 ·
`check_api_contract` 42 · `check_chat_turn` 20 · `check_unit_endpoints` **31** ·
`check_body_blocks` 17 · `check_output_safety` 5 · `check_table_grid` 18 ·
`check_tone_policy` 18 · unittest 28 + 56.

## 8. 문서

| 파일 | 변경 |
|---|---|
| `README.md`(루트) | 기능 표에서 FAQ 의 "xlsx/pdf/hwpx" 삭제, **"018 세 기능의 산출물은 txt 하나"** 절 신규, 검증 표 건수 갱신(+ 세 번의 제거 이력), 개봉 안전 게이트 관련 공백 문구 정정 |
| `onprem/README.md` | FAQ 절의 다운로드 표(3형식) → txt 절, 환경변수 목록에서 `FAQ_HWPX_TEMPLATE_PATH` 제거, 번역·글다듬이 절에 `POST /download` 추가, 이관 순서 표 갱신(내보내기 6파일 → `txt_output.py`), 호출 순서 갱신, 의존 패키지 표 갱신, "배포 환경에 달린 것" 3→2 |
| `onprem/docs/FEATURES.md` | 번역·글다듬이 엔드포인트에 `/download`, FAQ §4-3·§4-4 재작성 |
| `onprem/docs/SERVING_REGISTRY.md` | 필수 환경변수 표에서 `FAQ_HWPX_TEMPLATE_PATH` 제거, §4 전제 표에서 FAQ hwpx 템플릿 행 폐기 |
| `onprem/test/README.md` | 건수 갱신(`check_unit_endpoints` 31 등 드리프트 정리), 못 보는 것에 **"실제 메모장에서 열어보기"** 추가 |
| `onprem/HANDOFF.md` | 점검 목록 11개로 갱신, 완료된 후속 항목 정리 |
| `data/FAQ_rule.md`·`data/translation_rule.md` | **요구사항 원문은 지우지 않고** 머리말에 변경 메모를 붙였다(요구 이력이라 남긴다) |
| `CLAUDE.md` | "SFR-018 산출물 txt 통일" 절 신규 + FAQ·번역 절 정정 |
| 이 문서 | 신규 |

---

## 9. 아직 확인하지 못한 것

- **실제 윈도우 메모장에서 열어보지 않았다.** BOM·CRLF·헤더는 응답 바이트로 확인했지만
  사내 PC 의 메모장 버전에서 눈으로 본 것은 아니다.
- **UI 배선.** 세 단위의 `POST /download` 를 화면 버튼이 어떻게 부를지는 프런트와 맞춰야
  한다. 번역·글다듬이는 **본문을 요청에 담아 보내는** 형태라 FAQ(세션 기반)와 호출 모양이
  다르다.
- **LLM 실호출 경로**는 이 변경과 무관하게 여전히 미확인이다(게이트웨이 없음).
