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

## 기능별 추가 설정

### SFR-006_template_fill
- `TEMPLATE_FILL_TEMPLATE_DIR` : 관리자가 hwpx 템플릿을 두는 볼륨 경로
- `TEMPLATE_FILL_SESSION_DIR`  : 멀티턴 세션 저장 볼륨 경로
- **워크플로우 pod 와 코드서빙 pod 가 위 두 경로를 공유**해야 다운로드 단계가
  대화에서 모은 값을 읽는다.
- 캔버스 워크플로우 변수 `template_fill_template_id` 로 템플릿 선택 주입.
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
