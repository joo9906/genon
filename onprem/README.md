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
| `SFR-018_faq/` | FAQ 생성 | 워크플로우(02) + 코드서빙(03) | `faq/run_chat.py` `run(data)`, `faq/main.py` `app` |

각 디렉토리는 독립적으로 배포한다. 서로 import 하지 않는다.

`eval/` 은 배포 단위가 아니다 — 위 네 기능의 산출물을 채점하는 평가지표 MCP 서버
(저장소 루트 README 의 지표 정의를 도구로 구현). 자세한 내용은 `eval/README.md`.

## 프롬프트 디렉토리 (`prompt/`) — 배포 단위 **바깥**이다

**디렉토리 이름은 배포 단위 이름과 같다.** 네 단위 모두 프롬프트를 파일로 뺐다.

| 경로 | 쓰는 단위 | 쓰는 영역 | 템플릿 | 덮어쓰기 환경변수 |
|---|---|---|---|---|
| `prompt/SFR-006_template_fill/` | 템플릿 채우기 | 02 + 03 | `extract_system` `extract_user`(02) / `tone_system` `tone_user`(03) | `TEMPLATE_FILL_PROMPT_DIR` |
| `prompt/SFR-018_text_polish/` | 글다듬이 | 02 | `system` | `POLISH_PROMPT_DIR` |
| `prompt/SFR-018_translation/` | 번역 | 03 | `system_batch` `user_batch` `system_single` `user_single` | `TRANSLATION_PROMPT_DIR` |
| `prompt/SFR-018_faq/` | FAQ | 02 + 03 | `system` `user` `retry_shortfall` | `FAQ_PROMPT_DIR` |

jinja 템플릿(`*.j2`)이다. 문구 수정이 코드 리뷰·재빌드 없이 끝나고, 나중에 GenOS
Prompt 리소스(10.5절)로 옮길 때 그대로 등록할 수 있다.

- **이미지에 이 디렉토리를 함께 넣어야 한다.** 기본 탐색 경로는 배포 단위 기준
  `../prompt/<이름>` 이고, 다른 곳에 두면 위 환경변수로 지정한다. **006 과 FAQ 는
  02·03 두 이미지 모두** 이 디렉토리를 가져가야 한다 — 006 은 02 가 값 추출, 03 이
  톤 변환으로 서로 다른 템플릿을 쓰고, FAQ 는 03 의 `POST /generate` 도 02 와 같은
  `generate_faqs` 를 타기 때문이다(대화를 거치지 않는 재생성 경로).
- 템플릿이 없으면 **빈 프롬프트로 넘어가지 않고 요청을 세운다.** 지시문 없는
  프롬프트로 LLM 을 돌리면 그 결과가 정상 응답처럼 내려간다.
  렌더 실패는 LLM 실패와 **따로** 로그를 남긴다(`event=prompt_render_failed`) —
  전자는 이미지에 디렉토리를 안 넣은 배포 실수라 운영에서 구분돼야 손을 쓸 수 있다.
  단 006 톤 변환만 예외로 문서 생성을 막지 않는다(원본 값 유지 + 사유 노출).
  톤은 부가 기능이라 프롬프트가 없다고 다운로드까지 못 하게 할 이유가 없다.
- `StrictUndefined` 를 쓴다 — 변수 오타가 빈칸으로 렌더되면 지시 한 줄이 조용히 사라진다.
- **호출부는 확장자 없는 논리 이름만 넘긴다** — `render("system")`. 위 표의 "템플릿"
  칸이 그 이름이다. 파일명을 넘기면 저장 방식이 호출부마다 박혀, 나중에 프롬프트를
  GenOS Prompt 리소스(가이드 §10.5, `GET /prompt/template/{id}`)로 옮길 때 갈아 끼울
  자리가 `prompt_loader` 하나가 아니라 전 호출부가 된다. 확장자는 로더가 붙인다.

### 지시문 언어 — 한국어와 영어를 나눠 쓴다

프롬프트를 통째로 한국어로 쓰지 않는다. 판단 기준은 **그 문장이 통제하는 대상**이다.

- **구조·형식·금지 조항은 영어.** JSON 스키마, "코드펜스를 붙이지 마라", "지어내지
  마라" 류다. 영어 지시를 따르는 정확도가 높고 토큰도 덜 든다.
- **산출물의 언어·어투·표기 규칙은 한국어.** 한국어 존댓말·개조식 종결·`2026. 8. 3.`
  같은 표기는 한국어로 적어야 예시와 지시가 같은 언어로 맞물린다. 톤 프리셋
  (`tone_presets.py`)·난이도 문구가 이미 한국어인 것도 이 쪽에 붙는 이유다.
- **번역 단위만 전부 영어다.** 대상 언어가 요청마다 바뀌어서 지시문 언어가 섞이면
  모델이 출력 언어를 헷갈린다(`registers.py` 머리말). 언어 이름도 `Language.label`
  의 영문(`Korean`/`English`…)을 쓴다 — 사용자 노출용 `korean_label` 과 다른 필드다.
- **글다듬이에는 한 줄이 더 있다.** 이 단위는 한국어 원문을 되쓰기 때문에 영어 지시가
  번역을 유발할 수 있고, 그렇게 나온 영어 결과물은 형식상 정상 응답으로 내려간다
  (`markdown_guard` 는 구조만 보므로 언어 전환을 못 잡는다). 그래서 영어 형식 블록
  안에 "출력은 한국어, 번역 금지"를 명시한다.

이 정책은 각 `*.j2` 머리말 주석에 근거와 함께 적혀 있다 — 문구를 고칠 사람이
파일만 열어도 어느 블록을 어느 언어로 둬야 하는지 알 수 있게 하기 위해서다.

## 공통 환경변수 (Gateway)

세 기능 모두 GenOS Gateway OpenAI 호환 경로만 사용한다 (가이드 10.2절).

```
GENOS_URL         # Gateway 베이스 URL (호스트 루트. '/api/gateway' 는 코드가 붙인다)
LLM_SERVING_ID    # 서빙 ID
LLM_MODEL_ID      # 모델 ID
GENOS_TOKEN       # 시크릿 — 코드에 기본값 없음. 미설정 시 호출 시점에 실패한다
```

mock 을 제거했으므로 위 값이 없으면 조용히 넘어가지 않고 오류(ERR_INTERNAL 등)로
노출된다. 배포 전 반드시 주입할 것.

**`/api/gateway` prefix 는 세 단위 모두 코드가 붙인다** (`llm.py` 의 `_base_url()`).
`GENOS_URL` 이 이미 그 prefix 로 끝나면 중복 없이 그대로 쓴다. 예전에 018 두 단위가
`{GENOS_URL}/rep/serving/...` 로 prefix 없이 호출해 게이트웨이를 지나지 않았다 —
실제 운영 코드서빙 브리지(`genos_files/bridge.py`)가 `{base}/api/gateway/code_serving/...`
로 조립하는 것으로 확인된 사실이며, prefix 가 빠지면 LLM 호출이 404 로 죽는다.

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
- `TEMPLATE_FILL_SLOTS` : 본문 슬롯(`{'항목명', 16pt, 고딕, 볼드}`) 인식 (기본 1 = 켜짐)
- `TEMPLATE_FILL_TEMPLATE_DIR` : 관리자가 hwpx 템플릿을 두는 볼륨 경로
- `REDIS_URL` : 멀티턴 세션 + 템플릿 색인 저장소 (기본 사내 GenOS Redis DNS)
- **워크플로우 pod 와 코드서빙 pod 가 같은 Redis 와 같은 `TEMPLATE_DIR` 볼륨을 봐야**
  다운로드 단계가 대화에서 모은 값을 읽는다. 세션은 Redis 로 옮겼으므로 세션 전용
  공유 볼륨은 필요 없다.
- `TEMPLATE_FILL_REDIS_INDEX_PREFIX` / `TEMPLATE_FILL_INDEX_TTL_HOURS` : 템플릿 색인 캐시
- `TEMPLATE_FILL_MAX_PREVIEW_CHARS` : 마크다운 미리보기 길이 상한 (기본 20000)
- `TEMPLATE_FILL_PROMPT_DIR` : 프롬프트 디렉토리 위치를 옮길 때만 지정 (기본은
  배포 단위 기준 `../prompt/SFR-006_template_fill`). **02·03 양쪽에 필요하다**
- PDF 다운로드에는 설정이 없다 — 전처리기 변환기를 그대로 호출하고, 가용 여부는 그 패키지와
  변환 백엔드 존재로 판단한다.
- `TEMPLATE_FILL_ADMIN_TOKEN` : 설정 시 템플릿 등록·삭제에 `X-Admin-Token` 요구.
  비워 두면 검사하지 않으며 **기동 로그에 경고가 남는다**(인증 부재를 조용히 넘기지 않음).
- 캔버스 워크플로우 변수 `template_fill_template_id` 로 템플릿 선택 주입.
- **템플릿 색인 캐시 (`template_index.py`)** — 등록 시점에 한 번 파싱해
  `{항목 스키마 + 마크다운}` 을 Redis 에 두고 재사용한다. 예전에는 `/fields`·`/status`·
  대화의 **매 턴**·`/generate` 가 각각 zip+XML 을 다시 풀었다.
  - 무효화 조건은 캐시 값에 담아 대조한다: 내용 해시(파일 교체 감지), `SCHEMA_VERSION`
    (파서 규칙 변경), `SLOTS` 설정. **슬롯 인식 규칙이나 `FieldSpec` 을 고치면
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
- **채울 자리 인식 — 슬롯이 기본, 누름틀은 폴백** (`hwpx_fields.py`)
  관리자는 템플릿 본문에 **중괄호로 자리를 명시**한다:
  ```
  제 목  : {'제목', 16pt, 함초롬돋움, 볼드}
  담당자 : {'소속'} {'성명'}
  ```
  **첫 인자는 따옴표로 감싼 필수값**이고, 그것이 곧 항목명이자 "여기에 무엇을 쓰라"는
  AI 안내문이다. 뒤따르는 인자 0~3개가 크기·글꼴·굵게이며 **순서와 개수가 자유롭다**
  (`{'제목', 볼드, 고딕}` 도 `{'제목'}` 도 유효하다). 지정하지 않은 인자는 그 자리 run 의
  `charPrIDRef` 를 그대로 따른다 — 서식을 지어내지 않는다.
  - **중괄호 안만 채울 자리다.** 값을 넣어도 중괄호 밖 텍스트(`제 목  : `)는 들여쓰기와
    줄맞춤 공백까지 원문 그대로 남는다. 라벨 방식은 `항목명: 값` 으로 줄을 재조립하느라
    이 공백을 잃었고 `prefix` 를 따로 보존해야 했는데, 자리를 중괄호로 명시하면 그
    문제가 아예 생기지 않는다.
  - **따옴표가 없는 `{…}` 는 채울 자리가 아니다.** `{소속} {성명}`,
    `{YYYY.MM.DD. (요일)}` 같은 값 안내는 **문서에 원문 그대로 남기고** 등록 시
    경고(`bare_braces`)로만 알린다. 지워 버리면 값 안내로 쓰던 문구가 조용히 사라지고,
    등록을 거부하면 본문에 중괄호를 쓴 정상 문서를 막는다. 따옴표를 빠뜨린 오타인지
    일부러 적은 안내인지는 사람만 아는 판단이라 코드는 알리기만 한다.
  - **값이 없는 슬롯은 표기를 지운다** (`{'제목', 16pt}` 는 작성 지시문이므로).
    라벨은 남으므로 `제 목  : ` 상태가 되어 한/글에서 이어 쓸 자리가 그대로 보인다 —
    부분 초안 계약 유지.
  - 한/글 자동 고침이 `'제목'` 을 `‘제목’` 으로 바꿔 저장하므로 **굽은 따옴표도 받는다.**
    한쪽만 바뀐 문서(`‘제목'`)도 열어 준다 — 눈으로 구분 못 하는 차이로 항목이 통째로
    사라지는 편이 훨씬 나쁘다. 짝이 어긋나면(`‘제목"`) 슬롯으로 보지 않는다.
  - **한 문단에 슬롯이 여러 개 올 수 있다** (`담당자 : {'소속'} {'성명'}`). 라벨 방식의
    "문단당 1개" 제약이 없어졌다.
  - 슬롯이 여러 run 에 걸쳐 쪼개져 있어도(`{'구` + `분', 14pt}`) 문단 텍스트를 이어 붙여
    판정한다. 되쓸 때 조각을 못 받는 run 을 비우지 않으면 옛 글자가 남아 같은 값이 두 번
    적힌다 — 그 처리가 `rewrite_slots` 에 들어 있다.
  - LLM 이 값에 항목명을 다시 붙여 보내도(`제목: 실적 보고`) 코드가 떼어낸다 —
    프롬프트 지시만으로 보장하지 않는다.
  - 누름틀(CLICK_HERE)·레거시 `{{token}}` 은 그대로 지원한다. 한 문서에 섞여 있어도 되고,
    같은 이름이 양쪽에 있으면 누름틀을 대표로 본다. `GET /fields` 의 `source` 로
    (`slot` / `field`) 어느 방식인지 확인할 수 있다. 누름틀이 있는 문단은 슬롯 경로가
    건너뛴다 — 같은 문단을 두 경로가 고치면 값이 이중으로 들어간다.
  - `TEMPLATE_FILL_SLOTS=0` 이면 슬롯을 무시하고 누름틀만 쓴다.
- **서식 인자 적용 (`hwpx_style.py`)**: 슬롯 인자를 실제 hwpx 서식으로 반영한다.
  `TEMPLATE_FILL_APPLY_STYLE_SPEC=0` 으로 끌 수 있고, `TEMPLATE_FILL_STYLE_SCOPE` 는
  `slot`(기본, 중괄호 자리 run 만) · `paragraph`(문단 전체) · `run`(누름틀도 값 run 만).
  - **이 단계가 채우기보다 먼저 돈다.** 슬롯은 값을 채우는 순간 `{…}` 가 사라지므로,
    채운 뒤에는 어디에 무슨 서식을 걸어야 하는지 알 방법이 없다. 서식 단계가 슬롯을
    **전용 run 으로 떼어내 `charPrIDRef` 를 걸어 두고**, 채우기가 그 run 안 글자만
    갈아 끼운다. `main.py` 의 `_build_document` 가 그 순서를 지킨다 — 뒤집으면 서식이
    통째로 유실된다.
  - 인자는 **생김새로** 판정하므로 순서에 매이지 않는다: `16pt`·`16`·`16포인트` → 크기,
    `볼드`·`굵게`·`bold` → 굵게, `보통`·`normal` → 굵게 해제, 남은 첫 토큰이 글꼴.
  - **자리 표시어를 가장 먼저 걸러낸다.** 문법 설명(`{'제목', 글씨크기, 폰트, 볼드여부}`)을
    그대로 복사해 붙인 템플릿이 실제로 있는데, 효과 판정이 부분 문자열 매칭이라
    `볼드여부` 가 `볼드` 에 걸려 굵어지는 결함이 있었다. 자리 표시어는 완전 일치로
    거르므로 진짜 지시(`볼드`)를 삼키지 않는다.
  - 슬롯 인자에는 **글꼴 어휘 근거를 요구하지 않는다.** 따옴표가 경계를 이미 정했으므로
    사내 전용 글꼴이 목록에 없다고 관리자의 명시적 지시를 버릴 이유가 없다.
    근거를 요구하는 것은 **누름틀 안내문 경로뿐**이다(거기엔 따옴표 경계가 없다).
  - 서식을 지정한 슬롯이 한 문단에 둘 이상이면 `paragraph` 범위라도 슬롯 범위로
    떨어뜨린다 — 문단 전체에 걸면 뒤엣것이 앞엣것을 덮는다.
  - **파싱·XML 조작은 전부 코드가 한다.** `charPr` 복제·`fontface` 등록·`itemCnt` 갱신은
    한 글자만 틀려도 문서가 안 열리는 값이라 LLM 에 맡기지 않는다. LLM 호출 0회.
  - 같은 서식은 `charPr` 을 재사용해 목록이 무한히 늘지 않게 한다.
  - 서식 적용 실패는 문서 생성을 막지 않는다(원본 바이트로 채우기 진행 + 경고 로그).
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
- `POLISH_PROMPT_DIR` : 프롬프트 디렉토리 위치를 옮길 때만 지정 (기본은
  배포 단위 기준 `../prompt/SFR-018_text_polish`).
- 문서유형·톤 정책은 `tone_presets.py` 의 선언 딕셔너리 한 곳에서만 고친다.
  프롬프트 템플릿(`system.j2`)은 그 라벨과 지시문을 변수로 받기만 한다 —
  정책을 프롬프트 문구에 박으면 관리자 UI 가 내려받는 스키마와 실제 지시가 갈린다.

### SFR-018_translation

**엔드포인트**
- `GET /languages` : 지원 언어·문체 목록 + 한국어 축 제약 (화면이 선택지를 하드코딩하지 않게)
- `POST /translate` : 노드 배열 번역
- `POST /translate/markdown` : 전처리기 산출물(마크다운/HTML 표) 구조 보존 번역
- `POST /translate/hwpx` : **hwpx 업로드 직접 파싱** 후 번역 (multipart)
- `GET /glossary`, `POST /glossary/reload` : 용어사전 상태·재적재(관리자)
- `GET ""` : 루트 (게이트웨이가 경로 없이 베이스를 때리는 배포 대비)

**지원 범위와 방향** (`translation_pipeline/office/languages.py`)
- 한국어·영어·중국어·태국어·베트남어·러시아어 6개.
- **한국어를 한쪽에 둔 쌍만** 받는다. `en→ru` 같은 비한국어 쌍은 400 이다 —
  품질 검증 대상 밖이라 열어두면 검증 안 된 경로가 운영에서 조용히 쓰인다.
- `source_lang` 을 안 주면 **스크립트 기반으로 결정적으로 감지**한다(LLM 아님 —
  방향 검증은 거부 판정이라 흔들리면 정상 요청이 400 이 된다). 감지값인지 여부는
  응답 `options.source_lang_detected` 로 알린다.
- 숫자·기호뿐이라 감지 불가한 문서는 **거부하지 않고** 방향 검증만 건너뛴다.

**문체** — `register` = `written`(문어체, 기본) | `spoken`(구어체).
알 수 없는 값은 기본값으로 떨어뜨리되 `options.register_fell_back` 으로 알린다.

**용어사전** (`TRANSLATE_GLOSSARY_PATH`)
- 폐쇄망 볼륨의 JSON 또는 CSV 파일 하나. `genos-glossary` 실험의 **1단계
  (정확 매칭)만** 병합했다 — 2단계(Weaviate + 임베딩)는 보류 결정 그대로다.
  **여기에는 2단계 폴백이 없다.** 사전이 상한을 넘거나 파일이 없으면 그 언어는
  용어사전 없이 번역되고, 그 사실이 응답 `glossary.source` 로 나간다.
- 배치에 **실제로 등장한 용어만** 프롬프트에 싣는다(사전 전체를 싣지 않는다).
- 지시로 끝내지 않는다: 번역 후 코드가 다시 대조해 **준수율(`glossary.compliance`)**
  과 하이라이트 데이터를 낸다. `glossary.term_map` 은 `{"원문 용어": "번역 용어"}`
  평면 JSON(프론트 협의 전 기본형), `glossary.hits` 는 유닛별 상세 + `applied` 여부다.

**품질 장치**
- `TRANSLATE_DEDUPE_UNITS`(기본 1) : 같은 원문은 한 번만 LLM 에 보낸다. 반복 머리글이
  자리마다 다르게 번역되는 흔들림도 함께 없어진다. `stats.deduped_unit_count` 로 노출.
- `TRANSLATE_NUMERIC_GUARD` = `warn`(기본) | `revert` : 번역문의 숫자 보존을 코드가
  검사한다(`numeric_guard.py`). 자릿수 구분 기호를 제거하고 비교하므로
  `1,000` ↔ `1.000` 은 오탐이 나지 않는다. 이탈은 `numeric_warnings` 로 노출하고,
  `revert` 면 그 유닛만 원문으로 되돌린다.
- **마크다운 표 셀 번역문의 `|` 를 이스케이프한다.** 안 하면 그 행부터 열이 밀린다
  (HTML 셀은 escape 경로가 이미 막고 있어 마크다운 셀만 뚫려 있었다).
- `stats` 에 `unit_count`/`failed_unit_count`/`fallback_rate` 를 싣는다 —
  루트 README 018 공통 지표(fallback 발생률)의 분모·분자가 예전엔 응답에 없었다.

**hwpx 입력** — `POST /translate/hwpx` 는 전처리기를 거치지 않고 원본 XML 의
`cellAddr` 좌표로 표 격자를 직접 만든다(전처리기를 태우면 표 안 수치가 깨진다).
그 마크다운이 `/translate/markdown` 과 **같은 스켈레톤 분해 경로**를 탄다 —
hwpx 전용 번역 경로를 따로 두면 구조 보존 계약이 두 벌이 된다.

**문서 출력은 하지 않는다.** 요구사항대로 번역 결과는 텍스트/마크다운으로만 나간다.
원본은 `source_markdown` 으로 함께 돌려준다(UI 좌우 대조용 — 화면이 따로 들고 있으면
번역 요청 전후로 원본이 갈릴 수 있다).

- `TRANSLATE_MAX_NODES`, `TRANSLATE_MAX_TOTAL_CHARS`, `TRANSLATE_MAX_UPLOAD_BYTES` : 입력 상한
- `TRANSLATE_ADMIN_TOKEN` : 설정 시 `/glossary/reload` 에 `X-Admin-Token` 요구.
  비워 두면 검사하지 않으며 **기동 로그에 경고가 남는다**.

### SFR-018_faq

FAQ 생성. 대화(02)에서 만들고 다운로드(03)로 내려받는 구성이라 SFR-006 과 같은 모양이다.
초안은 `archive/FAQ.py` 였고, 거기서 고친 것은 `faq/run_chat.py` 머리말에 적었다
(`print()` 로 접속 정보 노출, 정의되지 않은 `model` 참조로 인한 `NameError`,
글자 단위 emit, `result` 에 `{**data}` 미전달, 5개 고정).

**입력** (요구사항 §1)
- pdf·docx : 전처리기가 바꾼 `genosUploaded` 마크다운.
- hwpx : **직접 파싱**한다(`faq/hwpx_text.py`). 워크플로우는 캔버스 변수
  `faq_hwpx_path`(공유 볼륨 경로)가 있으면 그 경로를 우선 쓰고, 코드서빙은
  `POST /generate/upload` 로 파일을 받는다.

**개수** (요구사항 §4)
- 배포 상한 `FAQ_MAX_COUNT`(기본 10), 기본값 `FAQ_DEFAULT_COUNT`(기본 5).
- 캔버스 변수 `faq_max_count` 로 관리자가 재배포 없이 낮출 수 있다.
  **배포 상한을 넘기지는 못한다** — 넘길 수 있으면 LLM 예산 상한이 캔버스 설정
  하나로 무력해진다.
- 사용자는 캔버스 변수 `faq_count` 로 0~상한 안에서 고른다. 상한을 넘겨 요청하면
  깎고 그 사실을 안내에 노출한다(조용히 바꾸지 않는다).

**근거 명시** (요구사항 §2) — 이게 이 단위의 핵심 계약이다
- LLM 은 항목마다 `evidence`(문서에서 그대로 옮긴 문장)를 함께 낸다.
- **코드가 원문과 대조한다**(`faq/evidence.py`): 정규화 후 완전 포함이면 통과,
  아니면 문자 3-gram 자카드가 `FAQ_EVIDENCE_MIN_RATIO`(기본 0.8) 이상이면 통과.
  통과 못하면 기본값으로 **기각**한다(`FAQ_EVIDENCE_REJECT=1`).
  검증 없이 표시만 하면 근거란이 장식이 되고, 지어낸 답변에 그럴듯한 출처가 붙는다.
- 루트 README 018 지표 4절(FAQ 원천 정합성)의 1차 스크리닝과 같은 판정이다.
- 기각 건수(`rejected.schema/ungrounded/duplicate`)를 응답·안내문에 노출한다 —
  조용히 버리면 왜 5개 요청에 3개만 나왔는지 알 수 없다.
- 요청 개수에 못 미치면 이미 채택된 질문을 알려주고 **한 번만** 더 부른다.

**난이도** (요구사항 §5) — "문서를 처음 보는 사람" 기준. 지시문은
`faq/generator.py` 의 `_DIFFICULTY_NOTE` 한 곳에 있고 프롬프트 변수로 넘어간다.

**엔드포인트** (03)
- `GET /config` : 관리자 상한·기본 개수·**지금 내려받을 수 있는 형식**. UI 는 이걸 보고
  버튼을 켠다(못 만드는 형식 버튼을 켜두면 눌러 보고서야 501 을 받는다).
- `POST /generate` (마크다운 본문) / `POST /generate/upload` (hwpx multipart)
- `GET /faqs?session_id=` : 저장된 FAQ (다운로드 버튼 활성화 판단)
- `POST /download` : `{format: hwpx|pdf|xlsx, session_id 또는 items}`

**다운로드** (요구사항 §2)

| 형식 | 방식 | 가용 조건 |
|---|---|---|
| xlsx | `openpyxl` 로 표를 새로 만든다 (번호/질문/답변/근거) | pip 설치만 |
| pdf | 템플릿이 있으면 hwpx→PDF(전처리기 변환기), 없으면 마크다운→weasyprint | 변환기 또는 weasyprint |
| hwpx | **템플릿의 반복 블록 복제** (기본 템플릿 번들) | 이미지에 `faq/assets/` 포함 |

- **다시 생성하지 않고 저장해 둔 것을 내려준다.** LLM 을 다시 부르면 화면에서 본 FAQ 와
  파일 내용이 달라진다. 저장소는 Redis(`faq/session_store.py`)이고, 다운로드는 세션을
  지우지 않는다 — 형식만 바꿔 여러 번 받는 흐름이 정상이다.
- **hwpx 를 백지에서 만들지 않는다.** `header.xml` 의 `charPr`/`itemCnt` 를 손으로 맞추다
  한 글자만 틀려도 한/글이 문서를 열지 못하고, 이를 확인할 한/글이 없다. 그래서 실제
  한/글이 만든 hwpx 를 뼈대로 두고 그 문단을 `deepcopy` 해서 항목 수만큼 늘린다.
  - **기본 템플릿을 배포 단위에 싣는다** (`faq/assets/faq_template.hwpx`).
    요구사항 §2 가 요구하는 건 Q/A/근거를 보여주는 것뿐이라 **관리자 등록을 전제로
    두지 않는다** — 아무 설정 없이 hwpx 다운로드가 동작한다.
    산출물은 `FAQ — {제목} ({n}건 / {날짜})` 뒤에 `Q1. 질문` / `답변` / `근거: …` 가
    항목 수만큼 반복되는 모양이다.
  - `FAQ_HWPX_TEMPLATE_PATH` 는 **사내 서식으로 덮어쓸 때만** 쓴다. 그 경우에도 아래
    토큰 규약을 지켜야 한다.
  - 템플릿 토큰: 반복 블록 `{{question}}`(앵커·필수) `{{answer}}` `{{evidence}}` `{{no}}`,
    스칼라 `{{title}}` `{{count}}` `{{date}}`. 토큰이 여러 run 으로 쪼개져 있어도
    문단 단위로 이어 붙여 처리한다(문단을 넘어가면 못 잡고, 잔존 토큰은 경고 로그로 남긴다).
  - 501 은 **번들 템플릿까지 없을 때만** 난다(이미지 빌드 누락). 빈 문서를 만들어
    내려주지 않는 규약은 그대로다.
- **"수단 없음"(501)과 "생성 실패"(500)를 다른 코드로 구분**한다. 전자는 재시도해도
  소용없고(다른 형식으로 받으면 된다), 후자는 재시도 가치가 있다.
- xlsx 셀은 `=` `+` `-` `@` 로 시작하면 홑따옴표를 붙여 텍스트로 고정한다(수식 인젝션 방지).

**환경변수**: `FAQ_MAX_COUNT`, `FAQ_DEFAULT_COUNT`, `FAQ_MAX_CONTEXT_CHARS`,
`FAQ_MAX_UPLOAD_BYTES`, `FAQ_EVIDENCE_MIN_RATIO`, `FAQ_EVIDENCE_REJECT`,
`FAQ_HWPX_TEMPLATE_PATH`, `FAQ_PROMPT_DIR`, `FAQ_REDIS_PREFIX`,
`FAQ_SESSION_TTL_HOURS`, `FAQ_ADMIN_TOKEN`, `REDIS_URL`

## 이관 순서 — 어떤 파일을 어떤 차례로 옮겨 적는가

폐쇄망에 옮길 때 참고할 두 가지 순서를 단위별로 적는다.

- **옮겨 적는 순서** = 의존 방향이다. 위 항목은 아래 항목을 모르고, 아래 항목만 위를
  참조한다. 이 순서로 넣으면 중간에 `ImportError` 없이 한 단계씩 확인하며 올라갈 수 있다.
- **실행 시 호출 순서** = 옮긴 게 맞는지 대조할 기준이다. 진입점부터 따라가며 함수가
  같은 차례로 불리는지 보면, 파일 하나를 빠뜨렸을 때 어디서 어긋나는지 바로 드러난다.

공통 전제:
- `config.py` → `logging_utils.py` → `error_codes.py` 는 **어느 단위든 가장 먼저**다.
  셋 다 다른 모듈을 참조하지 않는 잎(leaf)이고, 나머지 전부가 이 셋을 본다.
- `onprem/prompt/<단위>/` 는 배포 단위 밖이라 **파일 목록에 안 잡힌다.** 마지막에
  따로 챙긴다 — 빠뜨리면 기동은 되고 첫 LLM 호출에서 죽는다.
- 진입점(`run_chat.py` / `main.py`)은 **항상 맨 마지막**이다. 먼저 올리면 아직 없는
  모듈을 import 하다 죽어서, 진짜 문제가 어디인지 가려진다.

### SFR-006_template_fill (02 + 03)

**옮겨 적는 순서**

| # | 파일 | 비고 |
|---|---|---|
| 1 | `config.py`, `logging_utils.py`, `error_codes.py` | 잎 모듈 |
| 2 | `redis_client.py` | `from_url` 을 부르는 유일한 곳 — 모듈마다 부르면 연결 풀이 늘어난다 |
| 3 | `hwpx_fields.py` | 슬롯·누름틀 파서. 이 단위의 도메인 코어다 |
| 4 | `hwpx_style.py`, `hwpx_markdown.py` | 3 의 파서를 재사용한다 |
| 5 | `session_store.py`, `template_index.py` | 2·3 위에 얹힌다. `SCHEMA_VERSION` 확인 |
| 6 | `prompt_loader.py` → `prompts.py` | 순서 고정 (후자가 전자를 import) |
| 7 | `llm.py` | `_chat_url()` 이 `/api/gateway` 를 붙이는 유일한 곳 |
| 8 | `field_judge.py`, `tone_presets.py`, `value_guard.py` → `tone_apply.py` | 톤 경로 |
| 9 | `pdf_convert.py` | 전처리기 패키지 호출부 (03 전용) |
| 10 | `run_chat.py`(02) / `main.py`(03) | 진입점 |
| 11 | `onprem/prompt/SFR-006_template_fill/*.j2` | **02·03 이미지 양쪽에** |

**실행 시 호출 순서 — 대화 `run_chat.run(data)` (02)**

```
run(data)
 1. main_socketio.sio_server import (없으면 스킵)
 2. 입력 정규화 (문자열로 온 data 흡수) → sid 확보
 3. session_store.load_session       → 세션 값 + 템플릿 id
    _resolve_template_path            → 이번 턴 지정 > 세션 저장분
 4. template_index.get_index          → (캐시 히트) 항목 스키마 + 마크다운
      └ 미스면 hwpx_fields.scan_fields(슬롯+누름틀) 로 직접 파싱 후 캐시 적재
 5. prompts.build_extract_prompts     → (system, user)   ※ PromptRenderError 별도 처리
    llm.llm_call_async                → LlmResult
    field_judge.parse_updates         → updates / clears / rejected  ← 판정은 코드가 한다
 6. tone_apply.apply_tone             → 이번 턴 새 값 중 서술형만
      └ prompts.build_tone_prompts → llm_call_async → value_guard.fact_diff
 7. session_store.save_session        → 값 + raw_values 병합 저장
 8. hwpx_fields.missing_field_names   → 채움 판정 (03 과 같은 함수)
    hwpx_markdown.render_filled       → 문서 창에 그릴 마크다운
 9. _stream_chunks → emit_event("token") → yield {"event": "result", "data": {**data, ...}}
```

**실행 시 호출 순서 — 다운로드 `POST /generate` (03)**

```
generate(body)
 1. _resolve_format                   → hwpx | pdf
 2. session_store.load_session        → 대화에서 모은 값
 3. _load_template_bytes              → TEMPLATE_DIR 볼륨에서 읽기
 4. asyncio.to_thread(_build_document)     ← zip/XML 작업이라 스레드로 뺀다
      ├ hwpx_style.apply_styles        → **먼저.** 슬롯을 전용 run 으로 떼고 charPr 을 건다
      │                                  (실패해도 원본 바이트로 다음 단계 진행)
      └ hwpx_fields.fill_template      → 그 run 안 글자만 교체 + 슬롯 표기 제거
                                         ※ 순서를 뒤집으면 `{…}` 가 사라진 뒤라 서식 유실
 5. _finalize_document                 → pdf 면 pdf_convert.to_pdf
      └ 501(수단 없음) / 500(변환 실패) 구분. 실패 시 세션을 남긴다
 6. session_store.end_session          ← **성공했을 때만**
 7. _document_response                 → Content-Disposition + X-Styled-Fields
```

### SFR-018_text_polish (02)

**옮겨 적는 순서**: `config.py`·`logging_utils.py`·`error_codes.py` → `tone_presets.py`
→ `prompt_loader.py` → `llm.py` → `diff_report.py`·`markdown_guard.py` → `main.py`
→ `onprem/prompt/SFR-018_text_polish/system.j2`

**실행 시 호출 순서 — `main.run(data)`**

```
run(data)
 1. sio_server import → sid
 2. 입력 정규화 → question / overrideConfig.vars
 3. tone_presets.resolve_tone          → (문서유형, 톤, 정책강제 여부)
 4. _extract_uploaded_markdown         → 업로드 문서 우선, 없으면 채팅 텍스트
 5. _build_system_prompt               → prompt_loader.render("system.j2", …)
 6. llm.polish_text_async              → LlmResult
 7. diff_report.build_change_list      → difflib 로 결정적 산출 (LLM 재호출 없음)
 8. markdown_guard.find_structure_issues  → 표·제목·코드펜스 지문 대조
 9. _stream_chunks → emit → yield result (polished_text / changes / structure_warnings)
```

7·8 은 실패해도 본 결과 전달을 막지 않는다(경고만). 이 단위는 **문서 출력이 없다** —
채팅 응답으로 끝난다.

### SFR-018_translation (03)

**옮겨 적는 순서**

| # | 파일 | 비고 |
|---|---|---|
| 1 | `config.py`, `translation_pipeline/common/{logging_utils,error_codes}.py` | 잎 |
| 2 | `office/languages.py`, `office/registers.py` | 방향 검증·문체. 다른 모듈 참조 없음 |
| 3 | `office/types.py` | 아래 전부가 쓰는 값 객체 |
| 4 | `common/glossary_store.py` → `common/glossary_exact.py` | 적재 → 매칭 |
| 5 | `common/prompt_loader.py` → `common/prompt_builder.py` | 순서 고정 |
| 6 | `common/llm.py`, `common/validation.py` | 호출·응답 검증 |
| 7 | `office/markdown_units.py`, `office/hwpx_text.py`, `office/units.py` | 분해/재조립 |
| 8 | `office/numeric_guard.py`, `office/glossary_report.py` | 사후 검증 |
| 9 | `office/translation_modes.py` → `office/pipeline.py` | 실행 → 오케스트레이션 |
| 10 | `main.py` | 진입점 |
| 11 | `onprem/prompt/SFR-018_translation/*.j2` | |

**실행 시 호출 순서 — `POST /translate/markdown`**

```
translate_markdown(body)
 └ pipeline.run_markdown_translation_job
     1. markdown_units.split_markdown   → (스켈레톤 segments, 번역 units)
                                          구조는 여기서 코드가 쥔다. LLM 은 못 건드린다
     2. _resolve_options
          ├ languages.resolve_direction → 한국어 축 검증 (감지는 스크립트 기반)
          └ registers.resolve_register  → 문어체/구어체 (알 수 없으면 fell_back 표시)
     3. _run
          └ translation_modes.translate_units
               a. _dedupe                    → 같은 원문은 한 번만
               b. _split_batches             → 문자수·건수 상한으로 분할
               c. glossary_report.terms_for_batch → 이 배치에 등장한 용어만
                  prompt_builder.build_batch_prompts → llm.llm_call_async
                  validation.validate_translation_batch_response
                  (실패 시 retry≤2 → 단건 폴백 `build_single_prompts`)
               d. numeric_guard.find_numeric_drift → warn | revert
          └ glossary_report.build_report    → compliance / term_map / hits
     4. markdown_units.rebuild_markdown  → 구조는 원본과 항상 동일
     5. units.build_pairs                → 원문·번역 쌍 (unit_id 포함)
```

`POST /translate` 는 1 대신 `units.build_translation_units(nodes)` 를 타고 나머지가 같다.
`POST /translate/hwpx` 는 앞에 `hwpx_text.to_markdown` 이 붙고 **그 다음은 위와 같은 경로**다
— hwpx 전용 번역 경로를 따로 두면 구조 보존 계약이 두 벌이 된다.

### SFR-018_faq (02 + 03)

**옮겨 적는 순서**

| # | 파일 | 비고 |
|---|---|---|
| 1 | `config.py`, `logging_utils.py`, `error_codes.py` | 잎 |
| 2 | `redis_client.py` → `session_store.py` | |
| 3 | `hwpx_xml.py` → `hwpx_text.py` | hwpx 직접 파싱 (표 격자) |
| 4 | `evidence.py` | **근거 대조 — 이 단위의 핵심 계약** |
| 5 | `prompt_loader.py`, `llm.py` | |
| 6 | `generator.py` | 4·5 를 묶는다 |
| 7 | `formatting.py` | 채팅 마크다운 = 파일 내용 (같은 함수) |
| 8 | `exporters/{errors,xlsx_export,pdf_export,hwpx_export}.py` + `assets/faq_template.hwpx` | 03 전용. **assets 를 빠뜨리면 hwpx 만 501** |
| 9 | `run_chat.py`(02) / `main.py`(03) | 진입점 |
| 10 | `onprem/prompt/SFR-018_faq/*.j2` | **02·03 이미지 양쪽에** (03 의 `/generate` 도 생성한다) |

**실행 시 호출 순서 — 생성 `run_chat.run(data)` (02)**

```
run(data)
 1. sio_server import → sid
 2. 입력 정규화
 3. 원본 확보: faq_hwpx_path 있으면 hwpx_text.to_markdown (스레드),
    없거나 실패하면 _extract_uploaded_markdown (전처리기 산출물)
 4. generator.resolve_count            → 배포 상한 ∩ 캔버스 상한 ∩ 사용자 요청
 5. generator.generate_faqs
      a. EvidenceChecker(source)       → 원문 지문 준비
      b. prompt_loader.render(system/user) → llm.llm_call_async
      c. _parse_faq_payload → _adopt   → 스키마·근거·중복 기각 (건수 보존)
      d. 부족하면 retry_shortfall.j2 로 **한 번만** 추가 요청
 6. formatting.to_export_rows → session_store.save_faqs   ← 저장 실패해도 채팅은 나간다
 7. formatting.build_notice + to_markdown
 8. _stream_chunks → emit → yield result (faq_items / faq_session_id / faq_download_ready)
```

**실행 시 호출 순서 — 다운로드 `POST /download` (03)**

```
download(body)
 1. session_store.load_faqs            ← **다시 생성하지 않는다**
 2. _build_bytes(fmt)
      ├ xlsx  → exporters.xlsx_export  (수식 인젝션 방지 후 표 조립)
      ├ pdf   → hwpx 템플릿 있으면 hwpx→PDF, 없으면 markdown→weasyprint
      └ hwpx  → exporters.hwpx_export  (템플릿 반복 블록 deepcopy)
 3. 세션은 지우지 않는다 — 형식만 바꿔 여러 번 받는 흐름이 정상이다 (006 과 다르다)
```

03 의 `POST /generate`·`/generate/upload` 는 대화를 거치지 않는 재생성 경로다.
`_generate_and_store` → `generator.generate_faqs` → `session_store.save_faqs` 로
**02 와 같은 생성 함수**를 탄다 — 그래서 03 이미지에도 프롬프트 디렉토리가 필요하다.

### 옮긴 뒤 확인 순서

기능을 눌러 보기 전에 이 차례로 확인하면 원인 추적이 짧아진다.

1. `GET /health` — 기동 자체.
2. 기동 로그 — `prompt_dir_loaded` 가 뜨는지, `admin_token_missing` 경고가 있는지.
3. `GET /config`(FAQ) · `GET /templates`(006) · `GET /languages`(번역) — 설정과 가용
   형식이 기대대로인지. **여기서 pdf/hwpx 가 빠져 있으면 이미지 구성 문제**지 코드가
   아니다.
4. LLM 없는 경로 먼저 — 006 `GET /preview`, 번역 `POST /translate/hwpx` 의 파싱 단계.
5. 그 다음에 LLM 경로. 실패하면 로그의 `event` 로 갈린다:
   `prompt_render_failed`(디렉토리 누락) / `upstream_status`(게이트웨이) / 그 외.

## 코드서빙 실행 — **단위별 모듈 경로가 다르다**

```
# SFR-006_template_fill  (app 이 패키지 안에 있다)
uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT

# SFR-018_translation    (app 이 단위 루트에 있다)
uvicorn main:app --host 0.0.0.0 --port $PORT

# SFR-018_faq            (app 이 패키지 안에 있다 — 006 과 같은 모양)
uvicorn faq.main:app --host 0.0.0.0 --port $PORT
```

`main:app` 을 006 에 쓰면 루트에 `main.py` 가 없어 기동 실패한다. 두 단위의 구조가
다른 것이 원인이고, 통일하려면 006 루트에 `app` 을 재노출하는 `main.py` 를 두면 된다
(지금은 두지 않았다 — 실제 진입점이 두 곳으로 보이는 것도 혼동거리라서).

`GET /health` 로 헬스체크. 워크플로우(02) 기능은 GenOS 캔버스의 Python 노드에
`run` 함수를 등록하는 방식이라 별도 서버 실행이 없다.

## 워크플로우 스트리밍 규약 (02 두 단위 공통 — 가이드 5.2 / GENOS_RULES §D)

- **함수명은 정확히 `run`, 인자는 `data` 하나.** 다른 이름이면 `run function not found`
  + HTTP 500 이다. 바꿀 수 있는 값이 아니다.
- `run` 은 async generator 로, 마지막에 `event: result` 를 **1회** yield 한다.
  그 `data` 가 다음 스텝의 `data` 가 되므로 `{**data, ...}` 로 넘겨 `genos_state` 를 잃지 않는다.
- **`sio_server.emit` 뒤에는 반드시 `await asyncio.sleep(0)`.** 양보하지 않고 emit 을
  몰아치면 소켓 쓰기가 버퍼에 쌓여 UI 가 마지막에 한꺼번에 받는다(가이드 D.4 "스트리밍이
  일괄 반환되는 원인"). 실제 운영 브리지(`genos_files/bridge.py`)도 매 emit 뒤에 넣는다.
- **토큰은 청크 단위로 보낸다** (`_STREAM_CHUNK_CHARS`, 32자). 글자 하나씩 emit 하면
  현황표 한 장이 emit 수백 회가 되고, 양보 횟수가 그만큼 늘어 오히려 표시가 느려진다.

## 가이드 준수 점검 (2026-08-07 실시 — `genos-project/docs/GENOS_RULES.md` 체크리스트)

네 배포 단위를 조항별로 대조한 결과. **통과 항목은 근거를 함께 적는다** — 다음에
같은 점검을 할 때 다시 처음부터 뒤지지 않기 위해서다.

| 조항 | 결과 | 근거 |
|---|---|---|
| A.1 오류코드 `{영역}-{00020001/2/3}` | 통과 | 네 단위 `error_codes.py` 전수 확인. 실제 등장하는 공통코드는 그 셋뿐이고 영역코드는 `02`/`03` 뿐 |
| A.3 `detail` 에 예외 원문 | 통과 | `detail` 필드를 **아예 쓰지 않는다.** 사유는 `error_type` 으로 로그에만 남긴다 |
| A.4 영역별 전달 방식 | 통과 | 02 는 토큰 스트리밍 후 `{"event":"result","data":{**data,"error":…}}`, 03 은 HTTP 상태 + `{error_code,msg}` |
| B 외부 호출 timeout·재시도 상한 | 통과 | `llm.py` 네 사본 모두 클라이언트·호출 양쪽에 timeout, `range(retry_count)` 상한 루프 |
| C `print()` 금지 | 통과 | 저장소 전체 0건 |
| C 로그 화이트리스트 | 통과 | `logging_utils.py` 가 허용 필드 외를 값 없이 이름만 남긴다(`[dropped_fields=…]`) |
| D.1 `run` 시그니처 | 통과 | 02 두 단위 모두 async generator, 마지막 `event: result` 1회 |
| D.2 전역 가변 상태 | 통과 | 세션은 Redis. 모듈 전역은 lazy LLM 클라이언트 캐시뿐이고, 이건 커넥션 재사용이라 D.2 가 막는 대상이 아니다 |
| E `/health` 200 | 통과 | 코드서빙 세 단위 |
| E async 안 blocking 금지 | **1건 고침** | 번역 `_startup` 이 용어사전 파일을 직접 읽고 있었다 → `asyncio.to_thread`. `/glossary/reload` 는 원래 맞게 돼 있어 규약이 한쪽만 달랐다 |
| H `/api/gateway` 경로 | 통과 | 네 단위 모두 `llm.py` 의 `_base_url()`/`_chat_url()` 한 곳에서 조립 |
| I 타입힌트 | **부분 미준수(의도적)** | 성공/오류로 반환형이 갈리는 라우트는 주석을 붙이지 않는다. FastAPI 가 `Response` 서브클래스가 아닌 반환 주석을 `response_model` 로 삼아, `JSONResponse \| dict` 같은 Union 은 라우트 등록에서 앱을 죽인다. 번역 `glossary_reload` 하나가 그 형태였고 **떼어냈다** |

**게이트웨이 없이 확인한 범위다.** 위 표는 코드 대조와 로컬 실행 결과이고,
실제 GenOS 에 올려 돌린 결과가 아니다. 아래 두 가지는 여전히 실물 확인이 남았다.

- 로컬에 `fastapi` 가 없어 **앱 구성 단계(라우트 등록)를 실행해 보지 못했다.**
  위 `I` 항목은 FastAPI 의 알려진 동작을 근거로 고친 것이고, 실제 크래시를 재현해
  확인한 것은 아니다.
- 워크플로우(02) 실행은 GenOS 캔버스에서만 가능하다 — `run` 시그니처·스트리밍 규약은
  코드 대조로만 확인했다.

**가이드와 의도적으로 다른 것 하나**: §H 는 프롬프트를 GenOS Prompt 리소스
(admin-api `GET /prompt/template/{id}`)에서 받아오라 하고 "코드 안 긴 문자열 인라인"을
금지한다. 지금은 그 중간 단계로 **배포 단위 밖 jinja 파일**을 쓴다 — 인라인 금지는
지키면서, 폐쇄망에 Prompt 리소스가 준비되면 `prompt_loader.render()` 안쪽만 갈아 끼우면
되도록 호출부를 한 함수로 모아 뒀다.

## 의존 패키지

| 단위 | 패키지 |
|---|---|
| SFR-006 코드서빙(03) | `fastapi`, `uvicorn`, `pydantic`, `lxml`, `redis`, `httpx`, `jinja2` |
| SFR-006 워크플로우(02) | `httpx`, `lxml`, `redis`, `jinja2` (`run_chat` 이 파서·세션·프롬프트를 직접 쓴다) |
| SFR-018 글다듬이(02) | `httpx`, `openai`, `jinja2` |
| SFR-018 번역(03) | `fastapi`, `uvicorn`, `pydantic`, `httpx`, `openai`, `jinja2` |
| SFR-018 FAQ 코드서빙(03) | `fastapi`, `uvicorn`, `pydantic`, `httpx`, `lxml`, `redis`, `jinja2`, `openpyxl` (+ pdf 용 `markdown`·`weasyprint`) |
| SFR-018 FAQ 워크플로우(02) | `httpx`, `lxml`, `redis`, `jinja2` (`run_chat` 이 hwpx 파싱·세션·프롬프트를 직접 쓴다) |

전부 pip 설치 가능 — 시스템 레벨 도구는 쓰지 않는다. 단 네 가지가 배포 환경에 달려 있다:
- **워크플로우 이미지에 `lxml`·`redis`·`jinja2` 가 있어야 한다** (가이드 §5.5 는 워크플로우
  단계에 임의 패키지 추가 불가로 못 박는다). 없으면 `run_chat` 을 얇게 만들어 파싱·세션·
  프롬프트를 코드서빙에 위임하고 gateway 경유 HTTP 만 쓰는 형태로 바꿔야 한다.
  **글다듬이(02)는 `jinja2` 만 새로 필요하다** — 프롬프트를 파일로 빼면서 생긴 유일한
  추가 의존이고, 이 단위는 `lxml`·`redis` 를 쓰지 않는다. 그 하나가 막히면 이 단위만
  프롬프트를 코드 문자열로 되돌리는 선택지도 있다(다른 셋과 규약이 갈리는 대가는 있다).
- **PDF 는 코드서빙 이미지에 전처리기 패키지(`genon.preprocessor`)가 포함돼야 한다.**
  FAQ 의 마크다운→PDF 경로는 그 대신 `markdown`+`weasyprint` 를 쓰는데, weasyprint 는
  pip 로 깔려도 시스템 라이브러리(pango/cairo)와 **한글 폰트**가 이미지에 있어야 한다.
  둘 다 없으면 `GET /config` 의 `formats` 에서 pdf 가 빠지고, 눌러도 501 이 나간다.
- **프롬프트 디렉토리(`onprem/prompt/…`)를 이미지에 함께 넣어야 한다** (위 절 참고).
- **FAQ hwpx 다운로드는 `faq/assets/faq_template.hwpx` 가 이미지에 들어가야 동작한다.**
  배포 단위 안에 있으므로 디렉토리째 복사하면 따라가지만, 파일 목록을 손으로 추리는
  빌드라면 `.py` 만 챙기다 빠뜨리기 쉽다. 없으면 hwpx 만 501 이 된다.
