# SFR-018 산출물 md — 파일·함수 단위 규약

> **무엇인가**: 글다듬이·번역·FAQ 세 기능의 **최종 산출물은 화면 텍스트 + `.md` 파일
> 하나**다. 파일 본문은 화면에 보인 마크다운 그대로이고, 사용자는 그것을 받아 이어
> 편집한다.
>
> **주 경로는 `download_url` 이다.** 세 단위가 결과를 만들 때 md 를 굳혀 GenOS MinIO 에
> 올리고 링크만 낸다(`file_store.py`, 사본 3벌). `POST /download`(본문 왕복)는 CDN 업로드가
> 안 되는 배포를 위한 폴백이다. 두 경로 모두 아래 `md_output.py` 를 지나므로 바이트 규약이
> 같다.
>
> **입력·화면은 이 규약과 무관하다.** hwpx 직접 파싱, 전처리기 마크다운, 업로드 상한,
> UI 마크다운 표시, 근거 명시, 용어사전 하이라이트, 구조 보존 계약은 각 단위 문서가 정본이다.
>
> **SFR-006 은 무관하다.** 006 은 사내 hwpx 양식을 채우는 것이 기능 자체라 hwpx 를 낸다.

---

## 1. 왜 md 하나인가

- **화면과 파일이 같은 모양이다.** 화면이 마크다운을 보여주므로 파일도 마크다운이면
  사용자가 본 것을 그대로 받는다. 조립을 두 갈래로 두면 내용이 갈린다.
- **환경을 요구하지 않는다.** 볼륨·외부 변환기·시스템 라이브러리·폰트가 전부 필요 없다.
  그래서 "어떤 배포에서는 그 버튼이 501" 인 상태가 없고, 형식 가용성 판별도 없다.

## 2. md 규약 — BOM + CRLF (환경변수 스위치 없음)

사용자는 이 파일을 **윈도우 PC** 에서 연다. 마크다운 뷰어가 없으면 메모장으로 열리므로
둘을 붙인다.

- **UTF-8 BOM**: BOM 이 없으면 옛 메모장은 파일을 ANSI(cp949)로 읽어 **한글이 깨진다.**
- **CRLF**: 1809 이전 메모장은 LF 만 있는 파일의 줄바꿈을 렌더하지 못해 **전체가 한 줄로**
  붙어 보인다. 마크다운 문법은 CRLF 를 줄바꿈으로 읽으므로 렌더 결과는 같다.

폐쇄망 사내 PC 의 윈도우 빌드를 통제할 수 없으므로 둘 다 붙이고, **환경변수로 끄지
않는다** — 스위치를 두면 "어떤 PC 에서만 깨진다"가 되고 그 상태는 로그에 아무 흔적도
남기지 않는다(재현 불가한 제보만 남는다).

### 본문은 마크다운 그대로 — 기호를 떼지 않는다

강조(`**`·`*`·`_`·`` ` ``)·머리글 `#`·목록·인용 `>`·표 `|`·코드펜스를 전부 남긴다.

| 단위 | 파일 본문 | 이유 |
|---|---|---|
| 번역 | **받은 그대로** | 표·머리글은 **원본 문서에서 온 구조**다. "구조는 입력과 동일" 이 이 단위의 계약인데, 파일에서 풀면 지켜낸 구조를 마지막 단계에서 우리가 깨뜨린다 |
| 글다듬이 | **받은 그대로** | 같은 이유. `markdown_guard` 가 지문으로 대조해 지켜낸 그 구조다 |
| FAQ | **화면과 같은 마크다운** (`# 제목` + `**Q1. 질문**` / 답변 / `> 근거: …`) | 화면과 파일이 같은 조립기(`formatting._render`)를 지나 내용이 갈리지 않는다 |

**되돌려 보낼 값은 정본이다.** 번역·글다듬이 화면 표시용 `text` 에는 경고문과 `<mark>`
태그가 붙어 있다. 파일에 실리는 것은 정본(`markdown`·`polished_text`)이다 — 파일 단계에서
태그를 **지우는** 방식은 원문에 원래 있던 태그까지 지운다.

---

## 3. `md_output.py` — 세 단위 공통 사본

| 위치 |
|---|
| `final/SFR-018-faq/request/faq/md_output.py` |
| `final/SFR-018-polish/request/text_polish/md_output.py` |
| `final/SFR-018-translate/request/translation_pipeline/common/md_output.py` |

배포 단위 간 import 금지라 사본이다. 표 격자 규칙·톤 프리셋과 같은 성격의 **의도된
중복**이고 세 파일은 같아야 한다.

| 이름 | 하는 일 |
|---|---|
| `to_bytes` | 줄바꿈 CRLF 통일 + UTF-8 BOM. 입력에 CRLF 가 섞여 있어도 **먼저 LF 로 접었다가** 펴서 `\r\r\n` 을 만들지 않는다. 파일을 만드는 유일한 길목이다 |
| `safe_stem` | 제목 → 파일명 본체. 윈도우 금지 문자·경로 구분자·제어문자 제거, 공백 접기, 80자 절단, 비면 기본값 |
| `download_filename` | 업로드 폼에 쓸 파일명 `stem.md`. 확장자 조립을 호출부마다 하면 세 단위가 갈릴 수 있어 여기에 둔다 |
| `content_disposition` | RFC 5987 (`filename*=UTF-8''…`). ASCII `filename=` 을 **함께 주지 않는다** — 브라우저가 그쪽을 골라 깨진 이름으로 저장하는 것을 막는다 |
| `headers` | 위 헤더 + 호출부가 주는 추가 헤더 병합 |
| `MEDIA_TYPE`·`EXTENSION` | `text/markdown; charset=utf-8` · `md` |

기본 파일명은 `글다듬이결과.md` · `번역결과.md` · `FAQ.md` 다.

## 4. 단위별 진입점

### FAQ (`final/SFR-018-faq/request/faq`)

| 파일 | 함수 | 하는 일 |
|---|---|---|
| `main.py` | 모듈 상수 `_FORMATS` | `[md_output.EXTENSION]` — **항상 `["md"]`** |
| | `service_config` (`GET /config`) · `get_faqs` (`GET /faqs`) | `formats` 를 `list(_FORMATS)` 로 낸다. 값이 하나여도 배열 모양은 UI 계약이라 유지한다 |
| | `download` (`POST /download`) | `format` 은 생략 가능(기본 `md`). **옛 이름 `txt`/`hwpx`/`pdf`/`xlsx` 는 400**("md 형식으로만 내려받을 수 있습니다.") — 조용히 md 를 내려주면 화면은 다른 형식을 받았다고 믿는데 파일은 md 인 상태가 되고 그 어긋남은 기록되지 않는다. 저장된 세션(또는 요청의 `items`)을 `rows_to_markdown` → `md_output.to_bytes` 로 낸다. **다시 생성하지 않고 세션을 지우지 않는다** |
| `formatting.py` | `_render` | (질문, 답변, 근거) 튜플 → 마크다운. **화면과 파일이 공유**한다 |
| | `_flat` | 근거의 줄바꿈·연속 공백 접기 — 줄바꿈이 인용구(`>`)를 끊으므로 근거는 한 줄이다 |
| | `_as_tuples` | 저장된 평면 형태 → 튜플 목록 |
| | `rows_to_markdown(rows, notice=, title=)` | 다운로드가 쓰는 조립 함수. 제목이 있으면 `# 제목` 한 줄을 앞에 붙인다. 줄바꿈은 LF 로 만들고 **CRLF 변환은 `md_output.to_bytes` 한 곳에서만** 한다 |
| | `to_export_rows` | 세션 저장 형태. `sources` 키 이름을 바꾸지 않는다 — 이미 저장된 세션이 그 이름이라, 바꾸면 배포 시점 진행 중인 대화의 다운로드가 빈 근거로 나간다 |
| `api_contract.py` | `DownloadRequest` | `format`(선택, 기본 `"md"`, `max_length=16`) · `session_id` · `items` · `title` |

### 번역 (`final/SFR-018-translate/request`)

| 파일 | 함수 | 하는 일 |
|---|---|---|
| `api_contract.py` | `DownloadRequest` | `text` / `markdown` / `title` + `body()`. 두 필드를 받는 이유는 **응답 필드 이름이 경로마다 다르기 때문**(`/translate`=`text`, 마크다운·hwpx=`markdown`) — 화면이 방금 받은 값을 그대로 되돌려 보낼 수 있어야 이름을 옮겨 적는 층이 안 생긴다 |
| `main.py` | `download` (`POST /download`) | 본문 없으면 400, `MAX_TOTAL_CHARS` 초과 400. 상태 없이 인코딩만 한다. **본문은 손대지 않는다** |

### 글다듬이 (`final/SFR-018-polish/request`)

| 파일 | 함수 | 하는 일 |
|---|---|---|
| `main.py` | `DownloadRequest` | `text` / `polished_text` / `title` + `body()` |
| | `download` (`POST /download`) | `_MAX_INPUT_CHARS` 상한을 `/polish` 와 공유. 반환 타입 주석을 붙이지 않는다(성공/오류 형이 갈리는 라우트 — Union 주석은 기동 실패를 만든다) |

## 5. 점검

`Test/check/check_unit_endpoints.py` 의 **"md 규약 대조"** 가 세 단위의 내려받기 응답을
**바이트로** 대조한다(정적 diff 가 아니라 동작으로 본다): BOM · 전부 CRLF ·
`Content-Type: text/markdown; charset=utf-8` · RFC 5987 파일명 · 확장자 `.md` · 파일명
정리 · 마크다운 기호 보존(강조·표·목록·펜스) · FAQ 답변 안 강조 보존 · 세 단위 모두 응답.
FAQ 쪽은 옛 형식 이름(`txt`/`xlsx`/`pdf`/`hwpx`) 거절도 본다.

`Test/check/check_prompt_render.py` 는 프롬프트 파일 확장자가 `.md` 인지도 본다(프롬프트
템플릿도 `final/<기능>/prompt/<단위>/*.md` 다). 로더(`_TEMPLATE_SUFFIX = ".md"`)는
`.txt`·`.j2` 를 붙인 옛 이름도 같은 프롬프트로 읽는다 — 옛 호출부·옛 환경변수 키가
조용히 다른 프롬프트로 떨어지지 않게 하기 위해서다.

## 6. 아직 확인하지 못한 것

- **실제 윈도우 PC 에서 열어보지 않았다.** BOM·CRLF·헤더는 응답 바이트로 확인했지만
  사내 PC 의 메모장·마크다운 뷰어에서 눈으로 본 것은 아니다.
- **폐쇄망에서 CDN 업로드가 실제로 되는지** 미검증이다 — 안 되면 `download_url` 이
  `null` 로 나가고 `POST /download` 폴백을 쓴다.
