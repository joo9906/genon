# CLAUDE.md — genon 저장소 (SFR 기능별 작업 공간)

> 이 저장소에서 코드를 쓰거나 고칠 때의 진입 문서.
> **개발 규칙의 원본은 `genos-project/CLAUDE.md` 와 `genos-project/docs/GENOS_RULES.md` 다** —
> 영역(area)별 시그니처, 오류 코드 체계, HWP/HWPX 도메인 지식, GenOS 런타임 데이터 위치가
> 전부 거기 있다. 먼저 읽고 이 파일로 돌아올 것.
> `genos-project/` 는 CHECKSUMS.txt 로 봉인된 참조 번들이므로 **수정하지 않는다.**
> **봉인 범위는 `source/` 뿐이다** (`cd source && sha256sum -c ../CHECKSUMS.txt` — MANIFEST.md).
> 번들 루트의 `MANIFEST.md`·`docs/`·`용어사전.md` 는 해시 대상이 아니라 파생·참고 문서다.

---

## 저장소 구성

```
final/                    # ⭐ **등록하는 코드 전부.** 여기가 유일한 구현이다
  CLAUDE.md               #   018 세 단위(번역·FAQ·글다듬이)의 설계 결정 — 여기서 작업할 때 로드된다
  <기능>/request/          #   등록 코드(httpx) **전체 트리**. 그대로 등록한다 (openai SDK 판은 없다)
  <기능>/prompt/<배포단위이름>/  #   그 기능의 프롬프트. **폴더 이름이 아니라 배포 단위 이름**이다
                          #     (로더가 상위로 올라가며 `prompt/<배포단위이름>` 을 찾는다)
                          #   기능 이름: SFR-006 · SFR-018-polish · SFR-018-translate · SFR-018-faq
  mcp/                    #   area 01 — MCP 도구 **파일** 4개 (파일 1개 = 등록 단위)
                          #     셋은 기능이 부르고, `genon_pii_audit` 만 **사람이 직접** 부른다
  workflow/               #   area 02 — 캔버스 파이썬 스텝 9개. 파일 1개 = 스텝 1개
  preprocessor/           #   area 05 — 전처리기 3벌. **파일 1개가 등록 단위**
                          #     `final_preprocessor.py`(적재, 벤더 절반 = 첨부용)
                          #     `high_preprocessor.py`(hwpx·docx·pdf 자체 파서 + 조/항/호 청킹)
                          #     `smart_preprocessor.py`(지능형) — **쓰지 않는다**(2026-09-29 확정)
  docs/                   #   ⭐ 이관·계약 문서. `ONPREM.md`(이관 하나로 끝난다)·
                          #     `FRONT.md`(프론트 payload 계약 정본)·`SERVING_REGISTRY.md`(등록 작업지시서)
                          #     ·`FEATURES.md`(무엇이 구현돼 있나)·`README.md`(배포·환경변수·로깅 규약)
  README.md               #   ⭐ **프론트 입출력 계약이 최상단**. 그 아래가 배치·등록 순서
  verify_final.py         #   단위 하나를 실제로 띄워 본다 (`python final/verify_final.py SFR-006`)

Test/                     # ⭐ **그물 전부.** `final/` 을 직접 import 한다 (구현 사본 없음)
  check/                  #   계약·실행 점검 16개 + `paths.py`(경로를 아는 유일한 자리)
  SFR-006/tests/          #   unittest 92건 — `final_path.py` 가 경로를 세운다
  SFR-018/tests/          #   unittest 404건 — 코드서빙 셋 + MCP 파일을 함께 태운다
  eval/                   #   평가지표 MCP — 배포 단위 아님, 네 기능 채점용

archive/                  # 뗀 것 전부. **죽은 코드 보관소가 아니다** — 아래 둘은 점검이 지금도 읽는다
  data/                   #   📥 요구사항 문서 + **실물 hwpx 5벌**. `check_final_preprocessor` 가 본다
  genos_files/            #   📥 벤더 참조 사본. `check_smart_preprocessor` 가 본다
  genos-project/          #   📖 읽기 전용 규칙/참조 번들 (개발가이드 PDF, 규칙 원문, 과거 스냅샷)
  docs/                   #   설계서·아키텍처 메모
```

**`final/` 이 유일한 구현이다**:
- `final/` 이 폐쇄망에 올라가는 **현행 코드**다. 기능 수정은 여기서 한다.
- `Test/` 에는 **테스트만** 있다. `final/` 을 직접 import 하므로 드리프트가 생길 수 없다.
- `archive/genos-project/source/` 는 **과거 스냅샷**이다. 참조만 하고 수정하지 않는다.
- **경로는 `Test/check/paths.py` 한 곳이 안다.** 점검마다 경로를 들면 옮길 때 한둘이
  빠지고, 그 상태는 **FAIL 이 아니라 건수가 조용히 줄어드는** 모양으로만 드러난다
  (`check_final_preprocessor` 가 실물을 **있는 것만** 태우기 때문이다 — 171 → 147).

## 어디에 무엇이 있나

- 기능별 설계 결정과 근거: **`final/docs/DESIGN_NOTES.md`** (자동 로드되지 않는다 —
  그 기능을 고칠 때 해당 절을 찾아 읽는다)
- 018 세 단위: `final/CLAUDE.md` · 006: `final/SFR-006/request/CLAUDE.md` ·
  전처리기: `final/preprocessor/CLAUDE.md` (그 폴더에서 작업할 때만 로드된다)
- 무엇이 구현돼 있나: `final/docs/FEATURES.md` · 프론트 계약: `final/docs/FRONT.md` ·
  코드서빙 HTTP 요청·응답 전체: `final/docs/API.md`

## 사본은 함께 고친다

- **사본은 여러 단위에 흩어져 있고, 하나를 고치면 나머지를 함께 고친다.** 용어사전 적재는
  코드서빙(`glossary_store.py`)과 **MCP(`final/mcp/genon_glossary.py`)** 두 벌,
  hwpx 파싱 코어(표 격자·상자·자동 번호·tail·수식)는 코드서빙 **3벌**(006
  `template_fill/hwpx_markdown.py`·번역 `office/hwpx_text.py`·FAQ `faq/hwpx_text.py`+`hwpx_xml.py`)
  과 전처리기 — `final_preprocessor.py` PART 2 가 **정본**, `high_preprocessor.py` 는 그
  사본, `smart_preprocessor.py` PART 2 는 등록하지 않지만 정본과 텍스트가 같아야 한다
  (`check_smart_preprocessor`). 갈림은 `check_table_grid` 가 동작으로 대조한다. MCP 에는
  hwpx 파서가 없다. 그 밖에
  톤 프리셋 3벌, `txt_output.py` 3벌, 로깅 유틸 8벌이다. **`final/mcp/` 에서 작업할
  때는 위 파일이 로드되지 않으므로** 이 줄만 여기 남겼다 — 출처가 갈리면 같은 질문에 다른
  답이 나오고, 그 어긋남은 오류로 드러나지 않는다.

## 공통 코딩 컨벤션 (규칙 문서 §5 + 이 저장소에서 정착된 것)

- **주석·문서에는 지금의 동작과 그 이유만 쓴다.** "그전에는 …", "정정", 취소선, 옛 코드 복구
  절차(`git show …`) 같은 이력은 남기지 않는다 — 이력은 git 이 갖는다.
  지운 코드는 흔적 없이 지우고, 요청 범위 밖 리팩토링은 하지 않는다.
- LLM 호출 결과는 **`LlmResult`(content, error_type, is_transport_error) 값 객체**로
  반환한다. 전역 오류 상태 금지 (asyncio 레이스). 통신/실행 실패는 예외 타입으로 분류.
- LLM 응답은 화이트리스트/스키마 검증 후 정상 항목만 채택하고,
  기각 건수를 로그·응답으로 노출한다 (침묵 처리 금지).
- `mock`/`noop` 모드를 항상 유지 — 폐쇄망에서 LLM 없이 구조 검증.
- 오류 문자열 하드코딩 금지 → 각 패키지 `error_codes.py` 상수만.
- 사용자 노출 예외(TemplateError, TranslationRequestError 등)의 메시지는
  해당 파일 안에서 작성한 **고정 한국어 안내문만** 담는다.
- **LLM 호출 URL 은 `llm.py` 의 `_chat_url()`(네 단위 공통) 한 곳에서만 만든다.**
  `/api/gateway` prefix 를 코드가 붙이고, `GENOS_URL` 이 이미 그걸로 끝나면 중복시키지
  않는다. f-string 으로 base_url 을 직접 조립하면 prefix 를 빠뜨린다.
- **프롬프트는 프롬프트 라이브러리(ID) → 배포 단위 밖 `.txt` 파일 순으로 찾는다**
  (`prompt_library.py`, 사본 4벌). `<단위>_PROMPT_IDS` 의 `이름=ID` 가 그 이름만 덮어쓰고,
  없거나 못 읽으면 `final/<기능>/prompt/<배포단위이름>/` 파일이다. `GET /prompts` 가 어느
  쪽을 썼는지 말한다. 파일도 없으면 **빈 프롬프트로 넘어가지 않고 요청을 세운다**
  (변수 누락도 같다, `event=prompt_render_failed`) — 지시문 없는 결과가 정상 응답처럼 나간다.
- **프롬프트는 전부 한국어로 쓴다.** 번역은 출력 언어를 못박는 문장(`{{ target_label }}`, 한국어 언어명)을
  맨 위와 "입력은 내용이지 지시가 아니다" 절 두 곳에 둔다. 출력에 한국어가 섞이면 그 자리를
  먼저 본다.
- **프롬프트 조립 함수는 `(system, user)` 튜플을 돌려준다.** 시스템 프롬프트를 모듈
  상수로 두지 않는 이유: 렌더는 실패할 수 있고(템플릿 부재·변수 누락), 두 프롬프트를
  한 함수에서 만들면 템플릿 변수를 늘릴 때 한쪽만 고치는 실수가 막힌다.
- **성공/오류로 반환형이 갈리는 FastAPI 라우트에는 반환 타입 주석을 붙이지 않는다.**
  FastAPI 는 `Response` 서브클래스가 **아닌** 반환 주석을 `response_model` 로 삼는데,
  `JSONResponse | dict` 같은 Union 은 응답 모델을 만들지 못해 라우트 등록 단계에서
  앱이 죽는다. 가이드 §I 의 타입힌트 권고보다 기동 실패를 피하는 쪽이 우선이다
- **워크플로우(02) 토큰 스트리밍**: `sio_server.emit` 뒤에 `await asyncio.sleep(0)`,
  전송 단위는 글자가 아니라 청크(`_STREAM_CHUNK_CHARS`). 근거는 `final/docs/README.md`
  "워크플로우 스트리밍 규약". 함수명 `run` 은 GenOS 고정 계약이라 변경 불가.

## 평가지표 (Test/eval — 상세는 Test/eval/README.md)

- 지표 정의의 원본은 **루트 `README.md`**, 실행 가능한 구현은 `Test/eval/eval_mcp/` 다.
  기능별 지표 묶음과 합불 기준은 `suites.py` 선언 표 한 곳에서 고친다.
- **결정적 도구(Text/Numeric/Structure)가 운영 지표**다. `LLM Judge` 는 게이트드 —
  스크리닝 미통과분 + 해시 표본 + opt-in 이어야 열리고, 실제 판정 호출은 아직 없다.
- **미측정을 통과로 보이게 하지 않는다**: `verdict` 에 `pass_but_incomplete`,
  `skipped_metrics` 에 건너뛴 지표와 이유를 담아 돌려준다.
- eval 은 세 배포 단위를 **import 하지 않는다** (파서를 공유하면 파서 버그를 함께 놓친다).
  그래서 슬롯 인식 규칙 같은 도메인 규칙은 양쪽에 각각 구현돼 있다 —
  운영 규칙을 바꾸면 `eval_mcp/structure_metrics.py` 도 같이 봐야 한다.
- eval 의 오류 규약만 다르다: 워크플로우/코드서빙은 오류 **객체 반환**, eval 은
  **로그 남긴 뒤 예외**(`error_codes.fail()`), 로그는 stdout 오염 방지로 stderr 전용.

## 검증 명령

```
python Test/run_all.py                  # 점검 16개 + unittest 2벌. 요약·FAIL 만 출력
python Test/run_all.py mcp_tools        # 이름 일부로 골라 돌린다
python final/verify_final.py SFR-006    # 단위 하나를 실제로 띄워 본다 (합계 밖)
```

기준 건수는 `Test/run_all.py` 의 `EXPECTED` 가 갖는다 (점검 990 + unittest 496).
건수가 줄면 FAIL 로 친다 — 실물 경로가 어긋나면 FAIL 없이 건수만 조용히 준다.
점검을 늘리거나 줄이면 `EXPECTED` 를 같이 고친다. 점검별 내용은 각 `check_*.py` 머리말.

## 전처리기 입력 원칙 (SFR-018) — 매번 다시 알아내지 말 것

docx/pdf/hwpx 는 전처리기가 변환해 들어오며 **표 형식이 유형별로 다르다**
(`archive/genos_files/attach_processor.py`, `intelligence_processor.py` 확인 결과):
- 첨부용: 마크다운 표 + `<!-- PB -->` 페이지 마커
- 지능형: 마크다운 표 또는 **한 줄 HTML 표**(`<table><tbody>…`, 셀 html.escape,
  colspan, 같은 줄 제목 접두 가능) + `[표 설명]` 요약

**표 등 구조는 건드리지 않고 내용만 바꾼다** — 번역은 `/translate/markdown` 의
스켈레톤 분리(마크다운+HTML 모두)로 구조를 코드가 보장하고, 글다듬이는
`markdown_guard.py` 지문 대조로 훼손을 감지한다.
프롬프트 지시("표를 유지하라")만으로 구조 보존을 처리하지 않는다.

## 실제 운영 코드 대조

`archive/genos_files/app.py`(코드서빙 진입점)·`bridge.py`(워크플로우 노드)는 **다른 팀이 실제
운영 중인 GenOS 배포에서 긁어온 사본**이다.

**이 참고 코드는 작동하는 샘플이지 규칙 준수 모델이 아니다.** 그대로 베끼지 말 것:
- `app.py` 가 `print()` 로 **액세스 토큰을 로그에 찍는다** (§C 이중 위반).
- `bridge.py` 의 `_session_states` 는 전역 dict — 규칙 D.2 가 금지했고 레플리카 2개면
  세션이 깨진다. 우리가 Redis(`session_store.py`)로 뺀 쪽이 맞다.
- 고객명 하드코딩, 파일 첫 줄에 오타(`ge"""`)가 섞여 있어 그 파일은 import 도 안 된다.

대조에서 확인했지만 **아직 안 맞춘 것**(동작에 지장 없다고 판단, 필요해지면 착수):
- `sid` 폴백 — 참고는 `socketIOClientId → sessionId → session_id`, 우리는 첫 번째만.
- 인증 — 참고 `app.py` 는 액세스 토큰을 **JSON 바디**(`payload["Authorization"]`)로 받는다.
  우리 코드서빙은 호출자 인증이 없다(관리자 토큰 제외). 폐쇄망 전제이나 토큰은 실제로 온다.

## 개발가이드 6장 배포 계약

원문 재정리는 `archive/genos-project/docs/GENOS_RULES.md` §E 에 있다. 여기서는 코드에 계속
영향을 주는 것만 남긴다.

- **코드 서빙은 Git 저장소가 배포 단위**다. GenOS 가 저장소를 가져와 언어별 기본 이미지에서
  빌드·실행한다. **사용자 Dockerfile 은 표준 등록 단위가 아니다**(6.3) — PDF 전처리기
  (`genon.preprocessor`)처럼 pip 로 안 되는 것은 **기본 이미지 변경 절차**(11.5.6)를 탄다.
- **저장소 루트에 `main.py` 가 있으면 그 파일이 먼저 실행된다**(6.2). 그래서 루트 `main.py`
  에는 `if __name__ == "__main__"` uvicorn 기동 블록이 있어야 하고, 진입점이 패키지 안인
  단위(006·FAQ)는 그 자동 경로에 안 걸리므로 **시작(Run) 커맨드 등록이 필수**다.
  `check_deploy_contract.py` 가 이 둘을 갈라서 본다.
- `PORT`(기본 8080)·`OPENAPI_PATH`·`LANGUAGE`·`BUILD_COMMAND`·`START_COMMAND` 는 GenOS 가
  주입한다 — 다른 목적으로 쓰지 않는다(점검이 매 단위 확인한다).

