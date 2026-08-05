# onprem — 온프레미스 이관용 프로덕션 코드

GenOS 폐쇄망에 그대로 옮겨 적는 **실사용 코드만** 담은 디렉토리.
테스트 코드(`tests/`)와 mock/noop 등 테스트 모드 경로는 **전부 제거**했다.
(구조 검증용 mock 은 저장소 루트의 원본 `SFR-006/`, `SFR-018/` 에만 남아 있다.)

## 배포 단위 3개

| 디렉토리 | 기능 | GenOS 영역 | 진입점 |
|---|---|---|---|
| `SFR-006_template_fill/` | HWPX 템플릿 채우기 | 워크플로우(02) + 코드서빙(03) | `template_fill/run_chat.py` `run(data)`, `template_fill/main.py` `app` |
| `SFR-018_text_polish/` | 글다듬이 | 워크플로우(02) | `text_polish/main.py` `run(data)` |
| `SFR-018_translation/` | 번역 | 코드서빙(03) | `main.py` `app` |

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
- `TEMPLATE_FILL_LABEL_FIELDS` : 본문 라벨 항목 인식 (기본 1 = 켜짐)
- `TEMPLATE_FILL_TEMPLATE_DIR` : 관리자가 hwpx 템플릿을 두는 볼륨 경로
- `REDIS_URL` : 멀티턴 세션 + 템플릿 색인 저장소 (기본 사내 GenOS Redis DNS)
- **워크플로우 pod 와 코드서빙 pod 가 같은 Redis 와 같은 `TEMPLATE_DIR` 볼륨을 봐야**
  다운로드 단계가 대화에서 모은 값을 읽는다. 세션은 Redis 로 옮겼으므로 세션 전용
  공유 볼륨은 필요 없다.
- `TEMPLATE_FILL_REDIS_INDEX_PREFIX` / `TEMPLATE_FILL_INDEX_TTL_HOURS` : 템플릿 색인 캐시
- `TEMPLATE_FILL_MAX_PREVIEW_CHARS` : 마크다운 미리보기 길이 상한 (기본 20000)
- PDF 다운로드에는 설정이 없다 — 전처리기 변환기를 그대로 호출하고, 가용 여부는 그 패키지와
  변환 백엔드 존재로 판단한다.
- `TEMPLATE_FILL_ADMIN_TOKEN` : 설정 시 템플릿 등록·삭제에 `X-Admin-Token` 요구.
  비워 두면 검사하지 않으며 **기동 로그에 경고가 남는다**(인증 부재를 조용히 넘기지 않음).
- 캔버스 워크플로우 변수 `template_fill_template_id` 로 템플릿 선택 주입.
- **템플릿 색인 캐시 (`template_index.py`)** — 등록 시점에 한 번 파싱해
  `{항목 스키마 + 마크다운}` 을 Redis 에 두고 재사용한다. 예전에는 `/fields`·`/status`·
  대화의 **매 턴**·`/generate` 가 각각 zip+XML 을 다시 풀었다.
  - 무효화 조건은 캐시 값에 담아 대조한다: 내용 해시(파일 교체 감지), `SCHEMA_VERSION`
    (파서 규칙 변경), `LABEL_FIELDS` 설정. **라벨 인식 규칙이나 `FieldSpec` 을 고치면
    `template_index.SCHEMA_VERSION` 을 올려야 한다** — 안 올리면 새 코드가 옛 판정을 읽는다.
  - 캐시는 성능 장치일 뿐이다. Redis 가 죽으면 직접 파싱으로 degrade 하고 경고만 남긴다
    (세션 저장 실패와 다르다 — 그쪽은 값 유실이라 오류로 올린다).
- **관리자 템플릿 등록/삭제**
  - `POST /templates` (multipart: `template`, `template_id` 선택, `overwrite` 선택)
    — 파싱을 **먼저** 하고 파일을 나중에 쓴다. 순서를 바꾸면 해석 불가 파일이 볼륨에 남는다.
    같은 이름이 있으면 409, `overwrite=true` 면 덮어쓴다(임시 파일 → `os.replace` 로 교체).
  - `DELETE /templates/{template_id}` — 파일과 색인을 함께 없앤다(색인만 남으면 목록에
    유령 템플릿이 보인다).
  - `GET /templates` 는 **캐시에 있는 색인만** 상세(`field_count` 등)를 붙인다. 목록을 만들
    때마다 전체 템플릿을 파싱하지 않기 위해서다. 색인이 없으면 `indexed: false` 로 표시하고,
    그 템플릿의 첫 `/fields` 호출이 색인을 만든다.
- **마크다운 미리보기 (`hwpx_markdown.py`, `GET /preview`)** — 표시 전용.
  브라우저는 hwpx 를 렌더링하지 못하므로 다운로드 전에 확인할 수단이 필요하다.
  - 미리보기는 **다운로드와 같은 채우기 경로**(`fill_template`)를 탄다. 별도 렌더러를 두면
    화면과 실제 파일이 어긋난다. 서식(글꼴·크기)은 마크다운에 반영할 자리가 없어 적용하지 않고,
    세션도 건드리지 않는다(세션 종료는 다운로드만 한다).
  - 표는 마크다운 표로 낸다(첨부형 전처리기 산출 형식과 동일). 셀 좌표는 `cellAddr` 이 정본 —
    병합 셀은 앵커 하나만 존재하므로 등장 순서로 채우면 열이 밀린다. 마크다운에 없는 rowspan 은
    앵커 행에만 값을 둔다.
  - 머리말/꼬리말·각주는 제외, 셀 안 표는 평탄화, 상한 초과는 `truncated: true` 로 알린다
    (잘린 미리보기를 문서 전체로 오인하면 빠진 항목을 못 보고 다운로드한다).
  - 대화 응답(`run_chat`)에는 **채우기 전 템플릿 모양**(`template_markdown`, 색인에 이미
    있어 추가 파싱 없음)과 **지금 값으로 채운 문서**(`document_markdown`, 매 턴 갱신)가
    함께 나간다. UI 문서 창은 후자를 그린다. 턴마다 채우기 1회가 부담되면
    `TEMPLATE_FILL_CHAT_PREVIEW=0` 으로 끄고 `GET /preview` 로 대체한다.

값 수정 경로는 **두 가지를 함께 제공한다.** 서로 대체재가 아니라 보완재다 — 한 항목만
고칠 때는 대화가 빠르고, 여러 항목을 훑어 고칠 때는 화면 폼이 낫다. 어느 쪽을 노출할지는
**UI 가 정한다**(문서 창을 읽기 전용으로 두면 대화 전용 UX). 백엔드는 하나이므로 전환에
재배포가 필요 없다. 두 경로 모두 **판정은 코드가 화이트리스트로** 하고, 반영·지움·기각을
빠짐없이 노출한다.

- **대화로 값 고치기·지우기 (`run_chat.py`, `field_judge.py`)**
  - LLM 출력 형식은 `{"updates": {...}, "clears": ["항목명"]}` 이다. **지움을 빈 문자열로
    표현하게 하면 형식 위반으로 기각돼 사용자 지시가 조용히 사라진다.** 그래서 지움은
    배열로 분리해 받고, `updates` 의 빈 값은 여전히 기각한다(추측으로 삭제하지 않는다).
  - 판정은 코드가 한다: 화이트리스트 검증 → `fields_updated`/`fields_cleared`/
    `fields_rejected` 로 결과를 노출. 기각 건수는 006 환각률 지표의 원천이다.
  - 같은 항목에 수정·삭제가 함께 오면 **수정을 채택**하고 `edit_intent_conflict` 로 로그를
    남긴다(조용히 하나를 고르지 않는다).
  - 세션에 값이 없던 항목은 "비웠다"고 말하지 않는다 — 템플릿에 원래 적힌 값은 문서에
    남으므로 그 항목은 여전히 채워진 상태로 보일 수 있다.
  - 답변은 **새로 채운 항목과 고친 항목을 구분**하고, 고친 항목은 `이전 → 새 값` 으로 보여준다.
    LLM 이 사용자가 건드릴 의도가 없던 항목을 덮어쓸 수 있고, 그걸 알아챌 수단이 이 표시뿐이다.
- **화면에서 직접 수정 (`PATCH /values`, `DELETE /values`)** — 대화를 거치지 않는 편집 경로.
  - 판정 책임은 대화 경로와 같다: **코드가 화이트리스트로 검증**하고, 템플릿에 없는 항목명은
    기각해 `rejected_fields` 로 노출한다(침묵 처리 금지). 화면이 그런 이름을 보냈다는 것은
    스키마 불일치 신호라 로그에도 남는다.
  - **빈 문자열은 "지움"** 이다(`cleared_fields` 로 알린다). 화면의 빈 입력칸을 조용히 무시하면
    사용자는 지웠다고 믿은 값을 그대로 다운로드한다.
  - 톤 변환 원본(`raw_values`)도 함께 갱신한다 — 직접 고친 값이 곧 원본이므로, 나중에 톤
    설정이 바뀌어도 옛 문구가 되살아나지 않는다.
  - 응답은 `GET /preview` 와 **같은 payload** 를 쓴다(같은 `_compose_view`). 수정 직후 화면과
    미리보기가 다른 계산을 하면 사용자가 보는 상태가 갈린다. `preview: false` 로 마크다운
    생성을 생략할 수 있다(연속 편집 중 가벼운 저장).
  - 세션 저장 실패는 **오류로 올린다**(500). 화면에는 반영됐는데 저장이 안 된 상태를 성공으로
    보이게 하지 않는다.
  - `DELETE /values` 는 세션에 모인 값만 지운다. 템플릿에 원래 적혀 있던 값은 문서에 남으므로
    `still_filled_in_template` 로 그 차이를 알린다.
  - 이 두 엔드포인트는 관리자 토큰 대상이 아니라 **`session_id` 만 알면 호출된다**
    (`/status`·`/preview`·`/generate` 도 같은 성질). 사내 폐쇄망 전제이며, 외부 노출 계획이
    생기면 세션 소유자 검증이 별도 과제다.
- **채울 자리 인식 — 라벨 항목이 기본, 누름틀은 폴백** (`hwpx_fields.py`)
  현장 템플릿은 누름틀이 아니라 본문에 그냥 텍스트로 이렇게 적혀 있다:
  ```
  제목: {볼드체, 고딕, 16pt}
  본문: {고딕, 13pt}
  ```
  콜론 앞이 항목명, 뒤 `{…}` 가 서식 명세다. 값은 **라벨을 남기고 뒤에 이어 쓴다**
  (`제목: 2026년 상반기 실적 보고`), 명세 표기는 **값이 없어도 산출물에서 지운다**
  (작성 지시문이므로). 값이 없는 항목은 `제목:` 상태로 남는다 — 부분 초안 계약 유지.
  - 라벨 인정 규칙은 결정적이다: 콜론 앞이 20자·3단어 이내이고 `.!?` 를 포함하지 않을 때만.
    그래서 `참고 사항은 아래 표와 같습니다.` 같은 일반 문장은 항목으로 잡히지 않는다.
  - 표 안 라벨도 인식한다. 단 hwpx 표는 hp:p 안에 hp:p 가 중첩되므로 **문단이 직접
    소유한 텍스트 노드만** 모아 판정한다(`para.iter()` 를 그대로 쓰면 표 전체가 한 줄로
    붙어 라벨 인식과 문단 서식이 함께 깨진다).
  - LLM 이 값에 항목명을 다시 붙여 보내도(`제목: 실적 보고`) 코드가 떼어내 `제목: 제목: …`
    이 되지 않게 막는다 — 프롬프트 지시만으로 보장하지 않는다.
  - 누름틀(CLICK_HERE)·레거시 `{{token}}` 은 그대로 지원한다. 한 문서에 섞여 있어도 되고,
    같은 이름이 양쪽에 있으면 누름틀을 대표로 본다. `GET /fields` 의 `source` 로
    (`label` / `field`) 어느 방식인지 확인할 수 있다.
  - `TEMPLATE_FILL_LABEL_FIELDS=0` 이면 라벨 항목을 무시하고 누름틀만 쓴다.
- **서식 명세 적용 (`hwpx_style.py`)**: 위 명세를 실제 hwpx 서식으로 반영한다.
  `TEMPLATE_FILL_APPLY_STYLE_SPEC=0` 으로 끌 수 있고, `TEMPLATE_FILL_STYLE_SCOPE` 는
  `paragraph`(기본, 문단 전체) 또는 `run`.
  - 명세는 두 위치에서 찾는다: **본문의 `항목명: {…}`**(라벨 항목 파서를 그대로 재사용 —
    라벨과 명세가 다른 run 으로 쪼개진 템플릿에서 정규식만으로는 놓친다) 와
    **누름틀 안내문(stringParam) 안의 `{…}`**.
  - 적용 대상은 라벨 문단, 같은 이름의 누름틀이 있으면 그쪽이 우선이다.
  - 표기는 관대하게 읽는다: `{볼드체, 16pt, 글꼴}`, `{맑은 고딕, 11pt}`,
    `{글꼴: 함초롬바탕, 크기: 11pt}`, `{함초롬돋움 16pt 굵게}` 모두 인식한다.
    `글꼴`·`크기` 같은 **항목 이름은 값으로 보지 않는다**(폰트 미지정 → 원본 폰트 유지).
  - **서식 명세로 인정하려면 근거가 하나는 있어야 한다** — 크기, 효과, 또는 글꼴 어휘를
    담은 토큰. 근거 없는 `{…}` 는 값 안내로 보고 아무 서식도 적용하지 않는다.
    현장 템플릿에 `담당자 : {소속} {성명}`, `배포일 : {YYYY.MM.DD. (요일)}` 처럼 적혀 있어서,
    첫 토큰을 폰트로 채택하던 예전 규칙은 '소속'·'YYYY.MM.DD.' 를 없는 글꼴로 걸었다.
  - 후보는 첫 개에서 멈추지 않고 모아 **항목명과 같은 토큰을 제외**한 뒤 고른다.
    `제 목: {제목, HY헤드라인M, 16pt}` 에서 '제목'(자리표시어)이 아니라 'HY헤드라인M' 이
    실제 글꼴이다.
  - 라벨 표기는 **원문 그대로 다시 쓴다**. 현장 템플릿은 `제 목 : ` 처럼 콜론을 세로로
    맞추는데, `항목명: ` 으로 재조립하면 줄맞춤이 무너진다.
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
- 다운로드 버튼 → 코드서빙 `POST /generate {template_id, session_id, format}`.
  버튼 활성화 판단은 `GET /status` 의 `ready_for_download`.
- **PDF 다운로드 (`pdf_convert.py`)** — `format: "pdf"` (기본 `hwpx`).
  전처리기의 `genon.preprocessor.converters.hwp_to_pdf.convert_hwp_to_pdf` 를
  **호출만** 한다(전처리기 코드는 수정하지 않는다). 순서는 `pdf_sdk → rhwp → libreoffice`
  — `rhwp` 가 HWP/HWPX 전용이라 LibreOffice 보다 정확하다.
  - **모의 변환 경로는 두지 않는다** (`onprem/` 규칙). 전처리기 패키지가 있으면 쓰고,
    없으면 미지원으로 응답한다 — 가짜 PDF 를 만들 수 있게 열어 두면 그게 운영에 흘러간다.
  - 그 패키지는 이 저장소에 없다(전처리기 이미지에 있다). **코드서빙 이미지가 그 패키지를
    포함해야 PDF 가 동작한다** — 유일한 배포 전제다.
  - 변환 백엔드가 0개일 수 있다(빌드에서 `INSTALL_LIBREOFFICE`/`INSTALL_RHWP` 끔, PDF SDK
    미포함). "수단 없음"(501, 재시도 무의미)과 "변환 실패"(500, 재시도 가치)를 다른 코드로
    구분해 내린다. 지금 내려줄 수 있는 형식은 `GET /templates`·`/status`·`/preview` 의
    `formats` 로 알린다 — UI 는 그걸 보고 PDF 버튼을 켠다. 가용성은 이미지 빌드 시점에
    결정되므로 프로세스당 1회만 판별한다(환경이 바뀌면 pod 재시작).
  - 변환기는 실패해도 예외 없이 `None` 을 돌려주므로 여기서 오류로 승격한다. 결과물이
    `%PDF-` 로 시작하지 않으면 내려보내지 않는다.
  - **변환 실패 시 세션을 종료하지 않는다** — 사용자가 hwpx 로 바꿔 다시 시도할 수 있어야 한다.
  - 변환기에 넘기는 임시 파일명은 ASCII 고정(`document.hwpx`)이다. 외부 변환기가 한글·공백
    경로에서 흔들리는 것을 피하고, 사용자에게 보이는 파일명은 `Content-Disposition` 이 정한다.

### SFR-018_text_polish
- 워크플로우 변수 `polish_doc_type`, `polish_tone` 로 문서유형/톤 주입
  (톤 고정군은 사용자 요청과 무관하게 정책 톤으로 강제).

### SFR-018_translation
- `POST /translate` : 노드 배열 번역
- `POST /translate/markdown` : 전처리기 산출물(마크다운/HTML 표) 구조 보존 번역
- `TRANSLATE_MAX_NODES`, `TRANSLATE_MAX_TOTAL_CHARS` : 입력 상한

## 코드서빙 실행 — **단위별 모듈 경로가 다르다**

```
# SFR-006_template_fill  (app 이 패키지 안에 있다)
uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT

# SFR-018_translation    (app 이 단위 루트에 있다)
uvicorn main:app --host 0.0.0.0 --port $PORT
```

`main:app` 을 006 에 쓰면 루트에 `main.py` 가 없어 기동 실패한다. 두 단위의 구조가
다른 것이 원인이고, 통일하려면 006 루트에 `app` 을 재노출하는 `main.py` 를 두면 된다
(지금은 두지 않았다 — 실제 진입점이 두 곳으로 보이는 것도 혼동거리라서).

`GET /health` 로 헬스체크. 워크플로우(02) 기능은 GenOS 캔버스의 Python 노드에
`run` 함수를 등록하는 방식이라 별도 서버 실행이 없다.

## 의존 패키지

| 단위 | 패키지 |
|---|---|
| SFR-006 코드서빙(03) | `fastapi`, `uvicorn`, `pydantic`, `lxml`, `redis`, `httpx` |
| SFR-006 워크플로우(02) | `httpx`, `lxml`, `redis` (`run_chat` 이 파서·세션을 직접 쓴다) |
| SFR-018 글다듬이(02) | `httpx`, `openai` |
| SFR-018 번역(03) | `fastapi`, `uvicorn`, `pydantic`, `httpx`, `openai` |

전부 pip 설치 가능 — 시스템 레벨 도구는 쓰지 않는다. 단 두 가지가 배포 환경에 달려 있다:
- **워크플로우 이미지에 `lxml`·`redis` 가 있어야 한다** (가이드 §5.5 는 워크플로우 단계에
  임의 패키지 추가 불가로 못 박는다). 없으면 `run_chat` 을 얇게 만들어 파싱·세션을
  코드서빙에 위임하고 gateway 경유 HTTP 만 쓰는 형태로 바꿔야 한다.
- **PDF 는 코드서빙 이미지에 전처리기 패키지(`genon.preprocessor`)가 포함돼야 한다.**
