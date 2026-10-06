# SFR-018 산출 파일 규약 — 마크다운(.md) 하나

글다듬이·번역·FAQ 세 기능의 **최종 산출물은 화면 마크다운 + `.md` 파일 하나**다.
규약의 정본은 `txt_output.py` 머리말이다(사본 3벌, 파일 이름은 그대로 둔다).
SFR-006 은 사내 hwpx 양식을 채우는 것이 기능 자체라 hwpx 를 낸다 — 이 규약 밖이다.

| 단위 | 사본 |
|---|---|
| FAQ | `final/SFR-018-faq/request/faq/txt_output.py` |
| 번역 | `final/SFR-018-translate/request/translation_pipeline/common/txt_output.py` |
| 글다듬이 | `final/SFR-018-polish/request/text_polish/txt_output.py` |

배포 단위 간 import 금지라 사본이다. 갈렸는지는 `Test/check/check_unit_endpoints.py` 가
세 단위의 응답 **바이트를 직접 대조**해 본다(정적 diff 가 아니라 동작으로 본다).

---

## 1. 파일을 내는 두 경로

- **주 경로 — 결과를 만들 때 올린다.** 세 단위가 결과를 만들면서 파일을 굳혀 GenOS
  MinIO 에 올리고 응답에 `download_url` 만 싣는다(`file_store.py`). 화면이 정본 텍스트를
  되돌려 보낼 필요가 없다. 업로드가 실패하면 `download_url` 만 비우고 결과는 그대로
  낸다(fail-open).
- **폴백 — `POST /download`.** 업로드가 안 되는 배포를 위한 라우트다.
  - FAQ: 세션(`session_id`) 또는 화면이 든 `items` 로 만든다. 다시 생성하지 않는다.
    `format` 은 선택(기본 `md`)이고 `md` 가 아닌 이름(`txt`/`hwpx`/`pdf`/`xlsx` 등)은
    400 으로 거절한다 — 조용히 md 를 내려주면 화면과 파일이 어긋난 채 기록이 남지 않는다.
  - 번역·글다듬이: **본문을 요청으로 받는다**(상태 없음). 번역은 `text`/`markdown`,
    글다듬이는 `text`/`polished_text` 를 함께 받는다 — 응답 필드 이름이 경로마다 달라
    화면이 방금 받은 필드를 그대로 되돌려 보낼 수 있어야 이름을 옮겨 적는 층이 안 생긴다.
    상한은 번역 `MAX_TOTAL_CHARS`, 글다듬이 `MAX_INPUT_CHARS`(`/polish` 와 공유).

## 2. 본문 — 화면 마크다운을 그대로

| 단위 | 파일 본문 | 이유 |
|---|---|---|
| FAQ | 화면과 같은 마크다운 + 제목이 있으면 맨 위 `# 제목` | `formatting.rows_to_markdown` 이 두 경로(업로드·`/download`)의 유일한 조립 함수라 화면·파일이 갈리지 않는다 |
| 번역 | **받은 그대로** | 표·머리글은 원본 문서에서 온 구조다. "구조는 입력과 동일" 이 이 단위의 계약인데 파일에서 풀면 지켜낸 구조를 마지막 단계에서 우리가 깨뜨린다 |
| 글다듬이 | **받은 그대로** | 같은 이유. `markdown_guard` 가 지문으로 대조해 지켜낸 그 구조다 |

강조(`**`)·제목(`#`)·표(`|`) 기호를 떼지 않는다 — 마크다운 뷰어에서 화면과 같은 모양으로
열리는 것이 목적이다.

FAQ 저장 형태의 근거 키는 `sources` 다(`to_export_rows`). 이미 저장된 세션이 이 이름이라
바꾸면 배포 시점에 진행 중인 대화의 다운로드가 빈 근거로 나간다. `POST /download` 의
`items` 는 `/generate` 응답 이름인 `evidence` 도 읽는다(`formatting._as_tuples`) — 화면이
받은 항목을 그대로 되보내도 근거 줄이 비지 않는다.

## 3. 인코딩 — BOM + CRLF (환경변수 스위치 없음)

마크다운 뷰어가 없는 PC 는 윈도우 메모장으로 연다. 그래서 둘 다 붙인다.

- **UTF-8 BOM**: BOM 이 없으면 구버전 메모장은 파일을 ANSI(cp949)로 읽어 **한글이 깨진다.**
  마크다운 뷰어는 BOM 을 무시한다.
- **CRLF**: 1809 이전 메모장은 LF 만 있는 파일의 줄바꿈을 렌더하지 못해 **전체가 한 줄로**
  붙어 보인다.

폐쇄망 사내 PC 의 윈도우 빌드를 통제할 수 없으므로 **환경변수로 끄지 않는다** — 스위치를
두면 "어떤 PC 에서만 깨진다"가 되고 그 상태는 로그에 흔적을 남기지 않는다.

CRLF 변환은 `to_bytes` **한 곳에서만** 한다. 입력에 CRLF 가 섞여 있어도 먼저 LF 로
접었다가 펴서 `\r\r\n` 을 만들지 않는다. 조립 함수들은 LF 로 만든다.

## 4. `txt_output.py` 의 함수

| 이름 | 하는 일 |
|---|---|
| `to_bytes` | 줄바꿈 CRLF 통일 + UTF-8 BOM. 내용은 바꾸지 않는다 |
| `safe_stem` | 제목 → 파일명 본체. 윈도우 금지 문자·경로 구분자·제어문자 제거, 공백 접기, 80자 절단, 비면 기본값 |
| `download_filename` | 업로드에 쓸 파일명 `stem.md`. 세 단위의 확장자가 갈리지 않게 조립을 여기 둔다 |
| `content_disposition` | RFC 5987 (`filename*=UTF-8''…`). ASCII `filename=` 을 **함께 주지 않는다** — 브라우저가 그쪽을 골라 깨진 이름으로 저장하는 것을 막는다 |
| `headers` | 위 헤더 + 호출부가 주는 추가 헤더 병합 |
| `MEDIA_TYPE`·`EXTENSION` | `text/markdown; charset=utf-8` · `md` |

FAQ 의 `GET /config`·`GET /faqs` 는 `formats` 를 배열(`["md"]`)로 낸다. 형식이 하나여도
배열 모양은 UI 계약이라 유지한다.

## 5. 아직 확인하지 못한 것

- **실제 윈도우 메모장에서 열어보지 않았다.** BOM·CRLF·헤더는 응답 바이트로 확인했지만
  사내 PC 의 메모장 버전에서 눈으로 본 것은 아니다.
- **업로드 경로가 폐쇄망에서 실제로 열리는지**는 미검증이라 `POST /download` 폴백을 둔다.
