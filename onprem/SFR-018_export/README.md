# SFR-018_export — 산출물 파일 내보내기 (코드 서빙, area 03)

글다듬이·번역·FAQ 결과를 hwpx / PDF / XLSX 로 내려준다.
**LLM 을 호출하지 않는다** — 이미 끝난 결과를 세션에서 받아 파일로만 만든다.
내보낼 때 LLM 을 다시 부르면 화면에 보인 문장과 파일 속 문장이 달라진다.

## 출력 형식은 입력 형식을 따른다

| 원본 | hwpx 출력 | PDF 출력 |
|---|---|---|
| hwpx | 되쓰기 — **원본 서식 유지** | 되쓴 hwpx → 전처리기 변환 (원본 서식 유지) |
| docx·pdf | **제공하지 않음** (`ERR_HWPX_ONLY`) | 다듬은 마크다운 → 렌더링 (마크다운 서식) |
| FAQ | 해당 없음 | 마크다운 → 렌더링 + XLSX |

docx→hwpx 변환 능력은 전처리기에도 없다. 빈 템플릿으로 **가짜 서식을 만들어 주지 않는다.**

## 연계 흐름 (이게 이 단위의 핵심 계약)

```
[대화 시작]  클라이언트 ──multipart──> POST /prepare        원본 hwpx
                                        → 문단 배열 + 지문을 Redis 세션에 저장
[대화]       글다듬이(02) / 번역(03) ──> GET  /paragraphs?session_id=…
                                    ──> POST /results       다듬은/번역한 문단
[다운로드]   클라이언트 ──multipart──> POST /export/hwpx     원본 + session_id
                                    ──> POST /export/pdf
```

**왜 워크플로우가 `/prepare` 를 직접 부르지 않는가**: 워크플로우 Python 단계에는 원본 파일
바이트가 오지 않는다(전처리기가 변환한 마크다운만 온다). 그래서 업로드는 클라이언트가 하고
워크플로우는 `session_id` 로 문단만 가져간다.

**왜 전처리기 마크다운을 쓰지 않는가**: 전처리기는 표를 마크다운 한 덩어리로 직렬화하고
`<!-- PB -->` 페이지 마커·`[표 설명]` 요약을 끼워 넣는다. 원본 hwpx 문단과 **1:1 이 아니다.**
그 순서로 되쓰면 엉뚱한 문단이 바뀐다. `POST /prepare` 응답의 문단 index 가 유일한 기준이다.

## 엔드포인트

| 경로 | 입력 | 비고 |
|---|---|---|
| `GET /health` | — | 200 고정 |
| `POST /prepare` | multipart `original`(hwpx), `session_id` | hwpx 전용. 문단 배열 + 지문 |
| `GET /paragraphs` | `session_id` | 준비 안 됐으면 `found:false` (404 아님) |
| `POST /results` | `{session_id, results:{index: text}}` | 부분 갱신 가능 |
| `GET /status` | `session_id` | `ready_for_download`, `hwpx_available` |
| `POST /export/hwpx` | multipart `original`, `session_id`, `filename?` | 되쓰기 |
| `POST /export/pdf` | 위와 같음 | 되쓰기 후 PDF 변환 |
| `POST /export/pdf/markdown` | `{markdown, title?, filename?}` | docx·pdf 원본, FAQ |
| `POST /export/xlsx` | `{items:[{question,answer,sources?}], sheet_title?, filename?}` | FAQ |

## 설계 결정

- **LLM 에 hwpx XML 을 넣지 않는다.** 코드가 문단 평문을 뽑아 넘기고 코드가 되쓴다.
  토큰 낭비보다 `charPrIDRef`·`itemCnt` 훼손(한 글자 틀리면 문서가 안 열림)이 위험하다.
- **되쓰기는 첫 `hp:t` 에 값, 같은 문단의 나머지 run 은 빈 텍스트.** SFR-006
  `_write_occurrence` 와 같은 전략이고 범위만 문단(`hp:p`) 전체다. run 을 새로 만들지
  않으므로 문단·문자 서식이 보존된다.
- **문단 내 부분 서식은 첫 run 서식으로 통일된다.** 번역은 길이가 완전히 달라져 run 별
  재분배가 불가능하다. 문단을 건너뛰는 대안(서식 100% 보존, 일부 미변환)을 버리고 처리율
  100% 를 택했다(2026-08-04 결정). 손실은 `X-Style-Simplified-Paragraphs` 로 보고한다.
- **값이 원문과 같으면 건드리지 않는다.** 쓰면 부분 서식만 잃는다. 글다듬이가 그대로 둔
  문단이 여기 해당해서 실제 손실이 크게 줄어든다.
- **표 셀 문단은 `hp:t` 에서 가장 가까운 조상 `hp:p` 로 귀속시킨다.** `hp:p` 를 순회하면
  표를 감싼 겉 문단이 셀 텍스트까지 집어 같은 텍스트가 두 번 잡힌다. 그 결과 표
  구조(병합셀 포함)는 아예 건드리지 않게 되어 마크다운 왕복보다 안전하다.
- **원본 지문(sha256)을 대조한다.** 문단 index 는 문서 순서에서 파생되므로 원본이 바뀌면
  엉뚱한 문단에 값이 들어간다 — 조용히 망가지는 실패라서 쓰기 전에 막는다.
- **원본 바이트는 세션에 보관하지 않는다.** 20MB 상한이라 Redis 에 부적절하다.
  내보내기 요청에 multipart 로 다시 받는다.
- **섹션은 번호 순서로 읽는다.** 문자열 정렬은 `section10` 을 `section2` 앞에 둔다.
- **PDF 렌더러를 만들지 않는다.** `genon.preprocessor.converters.hwp_to_pdf` 에 위임하고
  (백엔드 `pdf_sdk`/`rhwp`/`libreoffice`), 없으면 빈 PDF 대신 503 으로 알린다.
- **엑셀 수식 인젝션 방지**: 셀 값이 `=`·`+`·`-`·`@` 로 시작하면 홑따옴표를 붙여 텍스트로
  고정한다.
- 손실·오류는 응답 헤더로 노출한다: `X-Rewritten-Paragraphs`, `X-Unchanged-Paragraphs`,
  `X-Style-Simplified-Paragraphs`, `X-Unknown-Paragraphs`.

## 환경변수

```
REDIS_URL                  # 기본 redis://llmops-redis-service:6379/0
EXPORT_REDIS_PREFIX        # 기본 sfr018_export:session
EXPORT_SESSION_TTL_HOURS   # 기본 6
EXPORT_MAX_UPLOAD_BYTES    # 기본 20MB
EXPORT_MAX_PARAGRAPHS      # 기본 5000
EXPORT_MAX_TOTAL_CHARS     # 기본 500000
EXPORT_MAX_FAQ_ITEMS       # 기본 2000
LOG_LEVEL                  # 기본 INFO
```

Gateway 환경변수(`GENOS_URL`/`LLM_*`/`GENOS_TOKEN`)는 **필요 없다** — LLM 을 쓰지 않는다.

호출부(글다듬이·번역)에는 반대로 필요하다:

```
EXPORT_SERVING_ID          # 이 서비스의 코드 서빙 ID (Gateway 경유 호출용)
GENOS_URL, GENOS_TOKEN
EXPORT_BASE_URL            # (선택) 게이트웨이 라우팅이 다른 배포용 탈출구
EXPORT_CLIENT_TIMEOUT      # 기본 10초
```

## 실행

```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

의존: `fastapi`, `uvicorn`, `pydantic`, `lxml`, `redis`, `openpyxl`.
PDF 변환은 전처리기의 외부 변환기에 의존한다(순수 pip 아님).

## 검증

`onprem/` 은 배포용이라 `tests/` 를 두지 않는다. 회귀 테스트는 저장소 루트에 있다.

```
cd SFR-018 && python -m unittest discover -s export/tests -t .        # 되쓰기 코어 16건
cd SFR-018 && python -m unittest discover -s text_polish/tests -t .   # 문단 정렬 포함 22건
```

`SFR-018/export/hwpx_rewrite.py` 는 `export_pipeline/hwpx_rewrite.py` 와 같은 코드다
(import 경로만 다르다 — onprem 배포 단위는 절대 import). 한쪽을 고치면 다른 쪽도 고친다.
