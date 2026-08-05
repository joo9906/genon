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
- `TEMPLATE_FILL_SESSION_DIR`  : 멀티턴 세션 저장 볼륨 경로
- **워크플로우 pod 와 코드서빙 pod 가 위 두 경로를 공유**해야 다운로드 단계가
  대화에서 모은 값을 읽는다.
- 캔버스 워크플로우 변수 `template_fill_template_id` 로 템플릿 선택 주입.
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

## 코드서빙 실행 (참고)

```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

`GET /health` 로 헬스체크. 워크플로우(02) 기능은 GenOS 캔버스의 Python 노드에
`run` 함수를 등록하는 방식이라 별도 서버 실행이 없다.

## 의존 패키지

`lxml`(SFR-006), `fastapi`/`uvicorn`/`pydantic`(코드서빙), `openai`/`httpx`(LLM 호출).
전부 pip 설치 가능 — 시스템 레벨 도구는 쓰지 않는다.
