# onprem — 온프레미스 이관용 프로덕션 코드

GenOS 폐쇄망에 그대로 옮겨 적는 **실사용 코드만** 담은 디렉토리.
테스트 코드(`tests/`)와 mock/noop 등 테스트 모드 경로는 **전부 제거**했다.
(구조 검증용 mock 은 저장소 루트의 원본 `SFR-006/`, `SFR-018/` 에만 남아 있다.)

## 배포 단위 4개

| 디렉토리 | 기능 | GenOS 영역 | 진입점 |
|---|---|---|---|
| `SFR-006_template_fill/` | HWPX 템플릿 채우기 | 워크플로우(02) + 코드서빙(03) | `template_fill/run_chat.py` `run(data)`, `template_fill/main.py` `app` |
| `SFR-018_text_polish/` | 글다듬이 | 워크플로우(02) | `text_polish/main.py` `run(data)` |
| `SFR-018_translation/` | 번역 | 코드서빙(03) | `main.py` `app` |
| `SFR-018_export/` | 산출물 파일 내보내기 (hwpx·PDF·XLSX) | 코드서빙(03) | `main.py` `app` |

각 디렉토리는 독립적으로 배포한다. 서로 import 하지 않는다.

`eval/` 은 배포 단위가 아니다 — 위 세 기능의 산출물을 채점하는 평가지표 MCP 서버
(저장소 루트 README 의 지표 정의를 도구로 구현). 자세한 내용은 `eval/README.md`.

## 공통 환경변수 (Gateway)

세 기능 모두 GenOS Gateway OpenAI 호환 경로만 사용한다 (가이드 10.2절).

```
GENOS_URL         # Gateway 베이스 URL
LLM_SERVING_ID    # 서빙 ID
LLM_MODEL_ID      # 모델 ID
GENOS_TOKEN       # 시크릿 — 코드에 기본값 없음. 미설정 시 호출 시점에 실패한다
```

mock 을 제거했으므로 위 값이 없으면 조용히 넘어가지 않고 오류(ERR_INTERNAL 등)로
노출된다. 배포 전 반드시 주입할 것.

## 로깅 규약 (네 디렉토리 공통 — GENOS_RULES §C / 가이드 3.7·3.8·3.10)

각 디렉토리의 `logging_utils.py` 는 같은 계약을 가진 사본이다 (배포 단위 간 import 금지).

```python
log_info("세션 저장 완료", event="session_saved", resource_id="redis", item_count=len(values))
```

- **값은 `extra` 필드로만 넘긴다.** 메시지 문자열에 f-string 으로 끼워 넣지 않는다 —
  문자열에 섞인 값은 걸러낼 수 없어 화이트리스트가 무력해진다.
- **허용 필드만 기록된다**: `event, trace_id, request_id, resource_id, status,
  duration_ms, item_count, upstream_status, error_code, error_type`.
  그 밖의 키는 값을 버리고 **이름만** `[dropped_fields=...]` 로 남긴다(호출부 실수를 드러냄).
- 문서 원문·사용자 질문·LLM 응답 전문·시크릿·DB 오류 원문은 로그에 남지 않는다.
  실패는 `error_type`(예외 클래스명)과 `upstream_status`(HTTP 상태코드)로만 분류한다.
- `trace_id` 는 `genos_state` 에서 받아 매 로그에 싣는다 — 워크플로우 단계와 코드 서빙
  로그를 한 요청으로 묶는 유일한 키다.
- 코드 서빙 진입점은 `configure_logging(os.getenv("LOG_LEVEL", "INFO"))` 를 호출한다.
  `eval/` 은 stdio MCP 라서 `configure_stderr_logging()` 으로 **stderr 로만** 내보낸다
  (stdout 은 JSON-RPC 전송 채널 — 로그가 섞이면 프로토콜이 깨진다).
- 오류 전달 방식은 영역마다 다르다: 워크플로우/코드서빙은 오류 **객체**를 반환하고,
  `eval/`(평가지표·MCP 도구)은 **로그를 남긴 뒤 예외를 던진다**(`error_codes.fail()`).

## 기능별 추가 설정

### SFR-006_template_fill
- `TEMPLATE_FILL_TEMPLATE_DIR` : 관리자가 hwpx 템플릿을 두는 볼륨 경로
- `TEMPLATE_FILL_SESSION_DIR`  : 멀티턴 세션 저장 볼륨 경로
- **워크플로우 pod 와 코드서빙 pod 가 위 두 경로를 공유**해야 다운로드 단계가
  대화에서 모은 값을 읽는다.
- 캔버스 워크플로우 변수 `template_fill_template_id` 로 템플릿 선택 주입.
- **서식 명세 적용 (`hwpx_style.py`)**: 템플릿에 `제목: {함초롬돋움, 16pt, bold}` 처럼
  적힌 서식 명세를 읽어 실제 hwpx 서식으로 반영한다. `TEMPLATE_FILL_APPLY_STYLE_SPEC=0`
  으로 끌 수 있고, `TEMPLATE_FILL_STYLE_SCOPE` 는 `paragraph`(기본, 문단 전체) 또는 `run`.
  - 명세는 두 위치에서 찾는다: **누름틀 안내문(stringParam) 안의 `{…}`** 와
    **본문의 `항목명: {…}`**. 본문 표기는 산출물에서 제거한다(작성 지시문이므로).
  - 표기는 관대하게 읽는다: `{볼드체, 16pt, 글꼴}`, `{맑은 고딕, 11pt}`,
    `{글꼴: 함초롬바탕, 크기: 11pt}`, `{함초롬돋움 16pt 굵게}` 모두 인식한다.
    `글꼴`·`크기` 같은 **항목 이름은 값으로 보지 않는다**(폰트 미지정 → 원본 폰트 유지).
  - **파싱·XML 조작은 전부 코드가 한다.** `charPr` 복제·`fontface` 등록·`itemCnt` 갱신은
    한 글자만 틀려도 문서가 안 열리는 값이라 LLM 에 맡기지 않는다. 정형 명세면 LLM 호출 0회.
  - 같은 서식은 `charPr` 을 재사용해 목록이 무한히 늘지 않게 한다.
  - 서식 적용 실패는 문서 생성을 막지 않는다(서식 미적용 초안 + 경고 로그).
  - 적용 결과는 `X-Styled-Fields` 응답 헤더로 알린다 (UI 표시용 노출은 없음).
- **업로드 파일로 바로 생성**: `POST /generate/upload` (multipart)
  — `template`(hwpx 파일), `session_id`(선택), `values`(선택, JSON 문자열), `filename`(선택).
  템플릿을 `TEMPLATE_DIR` 에 미리 등록하지 않고 **업로드한 파일 그대로** 채우고,
  그 파일 안에 적힌 서식 명세도 같은 파이프라인으로 반영한다.
  `TEMPLATE_FILL_MAX_UPLOAD_BYTES`(기본 20MB) 로 크기 상한. hwpx 가 아니거나 손상된
  파일은 400 으로 안내한다(500 아님).
- **톤(문체) 적용 — opt-in**: `template_fill_tone` = `polite` | `friendly` | `report`
  (018 글다듬이와 같은 프리셋. 변수가 없으면 문체를 건드리지 않는다).
  - 추출과 분리된 2단계다: 값 추출 → **서술형 필드만** 문체 변환. 이름·날짜·금액처럼
    한글 문장 성분이 거의 없는 값은 대상에서 제외한다(변환해도 얻는 것 없이 사실만 훼손).
  - 변환 결과는 **숫자·날짜 보존을 코드가 검증**하고(`value_guard`), 어긋나면 그 필드는
    원본을 유지하고 기각 사유를 사용자·로그·`tone_rejected_fields` 에 노출한다.
  - 톤 LLM 호출이 실패해도 문서 생성은 막지 않는다(원본 값으로 진행 + 안내).
  - 서술형 후보가 없으면 LLM 을 호출하지 않는다.
  - `template_fill_tone_fields` 로 관리자가 대상 필드를 직접 지정하면 그 목록이 우선한다.
  - 세션에는 변환 전 원본(`raw_values`)과 최종 값(`values`)을 함께 보존한다 —
    매 턴 누적 값을 다시 변환하면 문체가 중첩돼 원문에서 멀어지기 때문.
- 다운로드 버튼 → 코드서빙 `POST /generate {template_id, session_id}`.
  버튼 활성화 판단은 `GET /status` 의 `ready_for_download`.

### SFR-018_text_polish
- 워크플로우 변수 `polish_doc_type`, `polish_tone` 로 문서유형/톤 주입
  (톤 고정군은 사용자 요청과 무관하게 정책 톤으로 강제).

### SFR-018_translation
- `POST /translate` : 노드 배열 번역
- `POST /translate/markdown` : 전처리기 산출물(마크다운/HTML 표) 구조 보존 번역
- `TRANSLATE_MAX_NODES`, `TRANSLATE_MAX_TOTAL_CHARS` : 입력 상한

### SFR-018_export

글다듬이·번역·FAQ 산출물을 파일로 내려준다. **LLM 을 호출하지 않는다** — 이미 끝난
결과를 세션에서 받아 파일로만 만든다. 내보낼 때 LLM 을 다시 부르면 화면에 보인 문장과
파일 속 문장이 달라지기 때문이다.

**출력 형식은 입력 형식을 따른다.** 없는 서식을 만들어내지 않는다.

| 입력 | hwpx 출력 | PDF 출력 |
|---|---|---|
| hwpx | 되쓰기 — **원본 서식 유지** | 되쓴 hwpx → 전처리기 변환 (원본 서식 유지) |
| docx·pdf | **제공하지 않음** (되쓸 원본이 없다) | 다듬은 마크다운 → 렌더링 (마크다운 서식) |
| FAQ | 해당 없음 | 마크다운 → 렌더링 + XLSX |

docx→hwpx 변환 능력은 전처리기에도 없다. `ERR_HWPX_ONLY` 로 안내한다.

- `GET /health` : 200 고정
- `POST /prepare` (multipart) : `original`(hwpx), `session_id` → 문단 배열 + 지문, 세션 생성.
  **문단 index 는 이 응답이 유일한 기준**이다. 전처리기 마크다운을 쓰지 않는 이유는
  그것이 표를 한 덩어리로 직렬화하고 페이지 마커·표 설명을 끼워 넣어 원본 hwpx 문단과
  1:1 이 아니기 때문이다 — 그대로 되쓰면 엉뚱한 문단이 바뀐다.
- `POST /results` : `{session_id, results:{문단 index: 다듬은 텍스트}}` 누적 저장.
  화면에 쓴 값과 **같은 값**을 보내야 한다.
- `GET /status?session_id=…` : `ready_for_download`, `hwpx_available` (버튼 활성화 판단)
- `POST /export/hwpx` (multipart) : `original`, `session_id`, `filename`(선택)
- `POST /export/pdf` (multipart) : 위와 같고 hwpx 되쓰기 후 PDF 변환
- `POST /export/pdf/markdown` : `{markdown, title, filename}`
- `POST /export/xlsx` : `{items:[{question, answer, sources}], sheet_title, filename}`

되쓰기 응답 헤더로 손실을 함께 알린다(침묵 처리 금지):
`X-Rewritten-Paragraphs`, `X-Unchanged-Paragraphs`, `X-Unknown-Paragraphs`,
그리고 **`X-Style-Simplified-Paragraphs`** — 문단 안에서 일부만 굵게/색이던 부분 서식이
첫 run 서식으로 통일된 문단 수다. 번역은 길이가 완전히 달라져 run 별 재분배가
불가능해서 이 손실을 택했다(2026-08-04 결정). 값이 원문과 같은 문단은 건드리지 않으므로
글다듬이에서는 손실이 크게 줄어든다.

- **원본 hwpx 는 세션에 보관하지 않는다.** 20MB 상한이라 Redis 에 넣기 부적절해서
  내보내기 요청에 multipart 로 다시 받는다. 대화에 쓴 원본과 같은 파일인지는
  **sha256 지문**으로 대조한다 — 원본이 바뀌면 문단 index 가 밀려 엉뚱한 문단에 값이
  들어가는데, 그건 조용히 망가지는 실패라서 쓰기 전에 막는다.
- 환경변수: `REDIS_URL`, `EXPORT_REDIS_PREFIX`, `EXPORT_SESSION_TTL_HOURS`(기본 6),
  `EXPORT_MAX_UPLOAD_BYTES`(기본 20MB), `EXPORT_MAX_PARAGRAPHS`, `EXPORT_MAX_TOTAL_CHARS`,
  `EXPORT_MAX_FAQ_ITEMS`. Gateway 환경변수는 필요 없다(LLM 미사용).
- **PDF 변환은 전처리기에 위임한다** (`genon.preprocessor.converters.hwp_to_pdf`,
  백엔드 `pdf_sdk`/`rhwp`/`libreoffice`). 렌더러를 직접 만들지 않는다 —
  `genos-project/CLAUDE.md` 대로 변환기 구축은 다른 담당자 소관이고 우리는 호출만 한다.
  변환기가 없으면 빈 PDF 를 주지 않고 `ERR_PDF_CONVERTER_MISSING`(503)로 알린다.

## 코드서빙 실행 (참고)

```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

`GET /health` 로 헬스체크. 워크플로우(02) 기능은 GenOS 캔버스의 Python 노드에
`run` 함수를 등록하는 방식이라 별도 서버 실행이 없다.

## 의존 패키지

`lxml`(SFR-006, SFR-018_export), `fastapi`/`uvicorn`/`pydantic`(코드서빙),
`openai`/`httpx`(LLM 호출), `redis`(세션 — SFR-006, SFR-018_export),
`openpyxl`(SFR-018_export XLSX).

전부 pip 설치 가능하다. 예외가 하나 있다 — **SFR-018_export 의 PDF 변환은 전처리기의
외부 변환기(사내 PDF SDK / rhwp / LibreOffice)에 의존한다.** 순수 pip 로 해결되지 않고
컨테이너에 그 도구가 있어야 한다. 없으면 503 으로 안내하고 빈 PDF 를 만들지 않는다.
마크다운→PDF 경로는 `markdown` + `weasyprint` 를 쓰는데, weasyprint 는 pip 설치되지만
시스템 라이브러리(pango/cairo)를 요구한다.

## 로컬 검증

`onprem/` 은 배포용이라 `tests/` 를 두지 않는다. 회귀 테스트는 저장소 루트의
`SFR-006/`, `SFR-018/` 쪽에 있다.

```
cd SFR-018 && python -m unittest discover -s export/tests -t .   # 내보내기 되쓰기 코어
cd SFR-006 && python -m unittest discover -s template_fill/tests -t .
```

`SFR-018/export/hwpx_rewrite.py` 는 이 디렉토리의
`SFR-018_export/export_pipeline/hwpx_rewrite.py` 와 같은 코드다(import 경로만 다르다 —
onprem 배포 단위는 절대 import 를 쓴다). 한쪽을 고치면 다른 쪽도 고친다.
