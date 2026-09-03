# onprem/test — 배포 계약 점검

GenOS 개발가이드 6장(코드 서빙)·11.3·11.5 가 요구하는 **배포 확인 항목**을 스크립트로
모아 둔 곳이다. 기능 회귀 테스트가 아니다.

## 이게 왜 여기 있나 — `onprem/` 은 tests 를 두지 않는 디렉토리인데

`onprem/` 규칙은 **배포 단위 안에** 테스트 코드와 mock 경로를 두지 않는 것이다. 폐쇄망에
올라가는 이미지에 가짜 경로가 섞여 흘러가는 것을 막기 위해서다.

이 폴더는 **배포 단위 바깥**(`onprem/SFR-*` 형제 위치)이고, 세 단위 중 어느 것에도
import 되지 않는다. Git 저장소를 그대로 올리더라도 빌드 커맨드가 설치하지 않고 시작
커맨드가 실행하지 않으므로 런타임에 존재하지 않는다.

함수 단위 회귀 테스트는 `SFR-006/tests/`·`SFR-018/tests/` 가 맡는다. 2026-08-11 부터
그쪽은 **사본이 아니라 onprem 을 직접 import 한다** — 사본을 두면 운영 코드를 고쳐도
옛 코드가 통과해서, 회귀 테스트가 회귀를 못 잡는다.

## 두 단계로 나뉜다

| 스크립트 | 언제 | 서버 필요 | 포트 |
|---|---|---|---|
| `check_deploy_contract.py` | 지금, 커밋 전 | 없음 | 열지 않음 |
| `verify_serving.py` | 서빙 배포한 뒤 | 배포된 서빙 | 열지 않음 (요청만 보냄) |

여기에 더해 **점검 열두 개가 더 있다.** 배포 계약이 아니라 기능·사본 점검인데, `onprem/`
규칙상 배포 단위 안에 `tests/` 를 둘 수 없어서 여기 모였다. 가짜 Redis·가짜 LLM 주입은
**배포 단위 바깥에서만** 해야 운영 코드에 테스트 분기가 생기지 않는다.

| 스크립트 | 건수 | 성격 | 무엇을 잡나 |
|---|---|---|---|
| `check_api_contract.py` | 50 | 특성화 | **006** 코드 서빙 엔드포인트 한 바퀴 (인프로세스 FastAPI) + **산출 형식이 hwpx 하나인가**(옛 `format=pdf` 는 400, `formats` 는 환경 무관) + **화면 편집이 업로드 문서 표식을 지우지 않는가**(2026-09-02) |
| `check_unit_endpoints.py` | 89 | 특성화 | **018 세 단위**(번역·글다듬이·FAQ) 엔드포인트 경계 + **txt 규약 3단위 대조** + 설정 부재가 내부·실행 실패와 갈리는가 + **원문 언어 교차검증**(선언 ↔ 문서) + **관리자 정책 출처 노출** — 위 점검이 006 전용이라 생긴 구멍을 메운다 |
| `check_chat_turn.py` | 41 | 특성화 | 대화 한 턴 계약(`token`…`result`)과 상태 전이 (02 스텝 3개 ↔ 03 `chat_api`) + **업로드 문서 자동 채움**(2026-08-31) + **대화 중간 업로드·파일 여러 번**(남은 자리만·표식 누적·채울 자리 없음 안내, 2026-09-02) |
| `check_service_boot.py` | 16 | 기동 | **코드서빙 4단위가 실제로 뜨는가** — lifespan·`/health`·`/`·라우트 등록 |
| `check_workflow_run.py` | 91 | 실행 | **워크플로우 스텝 9개를 돌린다** — 반환형·`result` 1회·오류 객체·`data` 보존 + **성공 경로에서 코드서빙 응답 키 대조** + **서빙의 재시도 불가 판정이 스텝을 넘어오는가**(`_upstream_kind`, 9개 스텝 전부) + **용어사전 하이라이트 전달**(`term_map`·`hits[].spans`·`translate_pairs`) + **화면(`text`)이 하이라이트 사본을 쓰는가**(번역·글다듬이) + **양쪽 하이라이트 사본 전달**(원문·결과 각각)·**다운로드 링크 전달**·하단 목록 부재 + **무엇을 흘렸는가**(번역·글다듬이 — 정본인가·사본이 아닌가·오류 경로에서는 안 흘리는가·emit 상한, 2026-09-01) |
| `check_mcp_tools.py` | 80 | 실행 | **MCP 도구 파일 4개** — 한 서버에 올려도 안 덮이는가, 결정적 판정이 나오는가, 빈 문자열 주입을 견디는가 + **선택지가 도구 스키마(enum)에 실리는가** + **원문 언어 교차검증** + **관리자 정책 반영** + **`diff_changes` 낱말 좌표·`<mark>` 사본·보호 구간**(HTML 표 셀·코드펜스·삭제·상한) |
| `check_body_blocks.py` | 17 | 기능 | 문단 복제 안전장치·서식 상속·적용 순서 |
| `check_tone_policy.py` | 24 | 사본 대조 | 톤 문구 3벌 일치 (006 톤 제거로 4벌→3벌, 2026-08-12) + **관리자 정책 파서 2벌**을 같은 입력에 태워 대조 (2026-08-18) + **옛 톤 별칭표 2벌**(`report`→`clear`)이 같고 **판정을 실제로 지나는가** (2026-09-03) |
| `check_table_grid.py` | 33 | 사본 대조 | 006↔번역↔FAQ↔MCP **파싱 코어** 일치 (전처리기까지 **5벌**) (텍스트가 아니라 출력으로 대조). 3층 "누락 방지"(상자·자동 번호·tail·수식)는 **전처리기를 정본으로** 함께 본다 |
| `check_output_safety.py` | 5 | 기능 | 파트 XML 선언·누름틀 안내문 (개봉 안전 게이트·표 셀 넘침은 2026-08-12 에 뺐다 — §6 참고) |
| `check_final_preprocessor.py` | 155 | 실행·소스 | **등록 단위**(area 05 — `final_preprocessor.py` 한 파일. PART 1 첨부용 벤더 · PART 2 hwpx · PART 3 라우터. 지능형은 2026-09-01 에 걷어냈다). 이름 충돌 셋(`DocumentProcessor`·`Document`·`_log`) · 형식별 라우팅 · **조/항/호를 pdf·docx 에도**(어댑터 둘) · **사이트 설치본 가드**(`page_description`) · **페이지 필드가 구역을 따라가는가** · 벤더 부재를 통과로 보이게 하지 않는가. **실물 hwpx 5벌(`data/`)을 있는 것만 태우므로 경로가 어긋나면 건수가 조용히 134 로 준다** (2026-08-31 에 실제로 밟았다) |
| `check_eval_metrics.py` | 81 | 가드레일 | **평가지표(eval) 자체를 검증한다** (2026-08-30 신설 — 그전에는 회귀 점검이 0건이었다). 미측정을 통과로 세지 않는가 · 빈 비교로 만점을 주지 않는가 · 판정이 실제로 갈리는가 · **기준 경로가 산출물에 도달하는가**(지표 키를 바꾸면 그 기준은 영원히 `not_measured` 가 된다) · hwpx 지표(합성 픽스처) · 게이트 규율 · 도구 표면 ↔ 카탈로그 · **PII 마스킹 누락**(절대 건수·체크섬 오탐 차단·값 미노출, 2026-09-02) · **표시용 `<mark>` 를 벗기는가** |

### 정적 점검이 못 잡는 층 — 2026-08-11 에 추가한 셋

`check_deploy_contract.py` 는 소스를 `ast` 로 읽기만 한다. 그래서 "`/health` 라우트를
정의하는 코드가 있다" 는 보지만 **"앱이 실제로 뜬다"** 는 못 본다. 그 사이로 빠져나간
결함이 실제로 넷 있었다 (`python-multipart` 미선언, `@app.get("")` 404, 프롬프트 경로
유실, Union 반환 주석). `check_service_boot`·`check_workflow_run`·`check_mcp_tools` 가
그 층을 맡는다 — **셋 다 실제로 실행해 본다.**

`check_service_boot`·`check_unit_endpoints` 는 단위마다 **subprocess** 를 띄운다.
코드서빙 단위들이 같은 최상위 모듈 이름(`main`·`config`)을 쓰기 때문에, 한 프로세스에서
이어 import 하면 먼저 들어간 쪽이 뒤엣것을 가려 **같은 앱을 여러 번 검사**하게 된다 —
그러면 전부 통과한 것처럼 보인다.

`check_mcp_tools` 는 반대로 **일부러 한 네임스페이스에 넣는다.** MCP 도구 파일은 한
서버에 함께 로드될 수 있어서, 이름이 겹쳐 덮이는지가 곧 확인할 계약이다.

점검이 아닌 파일이 하나 있다. **`hwpx_package.py`** 는 점검용 hwpx 픽스처를 온전한 OPC
패키지(container·manifest·version·preview)로 감싸는 공용 헬퍼다. 위 셋
(`check_api_contract`·`check_body_blocks`·`check_output_safety`)이 각자 파트 세 개짜리
반쪽 zip 을 만들고 있었는데, 개봉 안전 게이트가 항상 돌게 된 뒤로는 그게 전부 정당하게
거절된다. 뼈대를 세 곳에 복사하면 그게 곧 사본 드리프트라 한 벌만 둔다.
**표의 필수 자식은 채워 주지 않는다** — 그건 검사기가 잡아야 할 결함이고, 헬퍼가 조용히
메우면 픽스처가 결함을 감춘다.

`check_api_contract`·`check_chat_turn`·`check_unit_endpoints` 는
**특성화(characterization) 점검**이다 — "지금 동작이 이렇다" 를 못 박아 두고
리팩토링이 그것을 바꾸지 않았음을 확인하는 용도다. 실제로 `main.py`(1199→689줄)와
`run_chat.py`(600→350줄) 분리를 이 그물 위에서 했다.

### 1. `check_deploy_contract.py` — 소스만 읽는 정적 점검

```
python onprem/test/check_deploy_contract.py
```

import 도 하지 않고 `ast` 로 소스를 읽기만 한다. 의존 패키지가 설치돼 있지 않아도 돌고,
네트워크도 포트도 쓰지 않는다. FAIL 이 하나라도 있으면 종료 코드 1.

| 점검 | 근거 | 무엇을 잡나 |
|---|---|---|
| `requirements` | 6.3, 11.5.6 | 빌드 커맨드(`pip install -r`)가 설치할 파일이 있는지, 선언이 실제 import 를 덮는지. `UploadFile`/`File(`/`Form(` 을 쓰면 `python-multipart` 도 요구한다 — import 문에 안 나타나서 놓치기 쉽다 |
| `/health` | 6.4, 11.5.3 | 코드 서빙 진입 파일에 `/health` 라우트가 있는지 |
| `진입점` | 6.2 | 루트 `main.py` 가 있으면 GenOS 가 그 파일을 먼저 실행하므로 `if __name__ == "__main__"` 기동 블록 + `0.0.0.0` bind 가 있어야 한다. 없으면 모듈만 로드되고 서버가 안 뜬다. 진입점이 패키지 안이면 WARN 으로 "시작(Run) 커맨드 필수" 를 알린다 |
| `예약 환경변수` | 6.7 | `PORT`·`OPENAPI_PATH`·`LANGUAGE`·`BUILD_COMMAND`·`START_COMMAND` 를 앱이 덮어쓰지 않는지 |
| `print 금지` | GENOS_RULES §C | `print()` 는 GenOS 로그 시스템에 안 잡히고 stdout 을 오염시킨다 |
| `tests 미보유` | onprem 규칙 | 배포 단위 안에 `tests/`·`test/` 가 생기지 않았는지 |

워크플로우(02)인 `SFR-018_text_polish` 는 `requirements.txt` 를 요구하지 않는다. 워크플로우
단계는 pod 기본 이미지에 포함된 패키지만 쓸 수 있어 의존성 파일이 설치 입력이 아니기
때문이다(11.5.6). 대신 **기본 이미지에 있어야 할 패키지 목록**을 출력한다.

### 2. `verify_serving.py` — 배포된 서빙에 실제로 요청

```
python onprem/test/verify_serving.py translation \
    --base-url https://<genos-host> --serving-id <id> --token "$GENOS_TOKEN"

python onprem/test/verify_serving.py template_fill \
    --base-url https://<genos-host> --serving-id <id> --token "$GENOS_TOKEN"
```

stdlib(`urllib`)만 쓴다. 호출 URL 은 가이드 6.8 형식으로 조립한다:

```
{base-url}/api/gateway/code_serving/{serving-id}/{앱 경로}
```

`--base-url` 이 이미 `/api/gateway` 로 끝나면 중복시키지 않는다. 디버깅용으로 게이트웨이를
건너뛰려면 `--direct http://127.0.0.1:8080` — 운영 호출 경로가 아니므로 판정 근거로 쓰지 않는다.

**가이드 11.3 의 네 자리 중 셋을 자동으로 본다**: `/health` 200, 정상 입력, 입력 검증 실패(422).
네 번째인 **외부 시스템 timeout(504)은 자동화하지 않는다** — 게이트웨이 LLM 서빙을 실제로
지연시켜야 하고, 스텁으로 만들면 확인한 것이 없어진다. 대신 어떻게 만들어야 하는지를
스크립트가 마지막에 출력한다.

### 3. `check_api_contract.py` · `check_chat_turn.py` — 특성화 점검

```
python onprem/test/check_api_contract.py    # 코드 서빙 (03)
python onprem/test/check_chat_turn.py       # 대화 (02)
```

FastAPI 앱을 **인프로세스**로 띄우거나(`TestClient`) `run_chat.run()` 을 직접 돌린다.
Redis 는 메모리 가짜, LLM 은 대본을 돌려주는 가짜로 갈아 끼운다. 네트워크·포트·외부
서비스가 필요 없다.

**가짜를 꽂는 시점이 중요하다.** `session_store`·`template_index` 는
`from .redis_client import resolve_client` 로 **이름을 복사**하므로, 모듈이 로드된 뒤에
`redis_client` 쪽만 갈아 끼우면 이미 복사된 원본이 계속 쓰인다. 그러면 세션이 매 턴
초기화돼 점검이 통째로 무의미해진다 — 실제로 처음에 그렇게 실패했다.
두 스크립트 모두 **import 보다 먼저** 꽂거나 소비 모듈까지 함께 바꾼다.

`check_chat_turn.py` 가 보는 것: `result` 이벤트가 정확히 마지막 1회, 값 누적과 화이트리스트
기각, 본문 블록 추가/삭제(**삭제 번호는 추가 이전 목록 기준**), 톤이 값과 블록 양쪽에
걸리고 숫자가 틀어지면 원문 유지, 다음 턴이 이전 턴 값을 이어받음, 오류도 `result` 로 끝남.

### 4. `check_body_blocks.py` — 본문 블록 기능 스모크 (예외적으로 여기 있음)

```
python onprem/test/check_body_blocks.py
```

**"사본에 파서가 없어서" 는 더 이상 이유가 아니다** (2026-08-11). `SFR-006/tests/` 가
이제 onprem 을 직접 태우므로 슬롯 스캔·채우기 회귀 테스트는 그쪽으로 갔다.

이 파일이 여기 남는 이유는 다르다. 본문 블록 검증은 **문단을 통째로 복제한 결과의 XML
모양**을 보는데, 그러려면 secPr·표·그림이 뒤섞인 위험한 픽스처와 `hwpx_package.py`(온전한
OPC 패키지 헬퍼)가 필요하다. 그 뭉치를 `check_output_safety`·`check_api_contract` 와
공유하므로 셋이 같은 자리에 있는 편이 맞다 — 쪼개면 뼈대가 세 벌이 되고, 그게 곧 이
저장소가 계속 싸우는 사본 드리프트다.

표본 hwpx 없이 메모리에서 합성 문서를 만들고, LLM·서버·Redis 없이 결정적으로 돈다.
문서를 깨뜨릴 수 있는 지점만 본다:

| 점검 | 무엇을 잡나 |
|---|---|
| 표 안 라벨 | 채울 항목으로는 잡히되 **블록 서식 원본으로는 안 쓰인다** |
| 복제 안전장치 | 문단을 복제해도 표·구역정의(secPr)·누름틀이 딸려오지 않는다 |
| 서식 상속 | 지정한 항목의 `paraPrIDRef`·`charPrIDRef` 를 그대로 물려받는다 |
| header 불변 | 블록은 서식 정의를 새로 만들지 않는다 |
| 적용 순서 | 서식 적용 **뒤에** 복제한다 (앞에서 하면 명세 반영 전 모양을 물려받는다) |
| 화면 일치 | 미리보기와 다운로드 문서의 본문이 글자 단위로 같다 |
| 입력 검증 | 잘못된 서식 이름·범위 밖 삭제 번호는 버리되 **본문은 잃지 않는다** |

픽스처는 **일부러 위험하게** 만들었다 — 첫 문단이 secPr 과 `제 목 :` 라벨을 함께 담고
(현장 템플릿이 그렇다), 표를 담은 문단이 자기 텍스트도 갖고 표 run 이 텍스트 run 보다
앞에 있다. 안전한 모양으로 만들면 안전장치를 꺼도 통과해서 점검이 아무것도 안 잡는다
(실제로 첫 판이 그랬다).

### 5. `check_tone_policy.py` — 톤 정책 사본 대조 (여기가 제자리다)

```
python onprem/test/check_tone_policy.py
```

톤 프리셋은 **세 곳에 복제돼 있다.** 배포 단위 간 import 가 금지돼(각 단위가 독립 저장소로
배포된다 — 6.1) 공유 모듈로 뺄 수 없기 때문이다.

| 위치 | 역할 |
|---|---|
| `mcp/genon_lang_policy.py` (`LPTONE_PRESETS`) | **원본.** 톤 문구는 여기부터 고친다 — 판정(`resolve_tone`)하는 쪽이 원본을 갖는다 |
| `codeserving/SFR-018_text_polish/.../tone_presets.py` | 다듬기 프롬프트를 렌더하는 사본 |
| `eval/eval_mcp/tone_metrics.py` | 평가가 채점 기준으로 쓰는 사본 |

> **006 사본은 2026-08-12 에 없어졌다.** 006 의 톤 변환 기능(사용자 발화별로 값·본문을
> LLM 으로 다시 쓰는 것) 자체를 없앴다 — 관리자가 정한 고정 톤으로 채우면 되는 성격이라
> 그럴 이유가 없었다. 코드는 `archive/sfr006-tone` 브랜치. 대조도 4벌 → 3벌로 줄었다.

앞의 두 스크립트와 달리 이건 **예외가 아니라 제자리다.** 런타임에는 서로를 import 할 수
없으니 대조할 수 있는 곳이 배포 단위 바깥뿐이고, 그게 여기다.

대조 대상: eval↔018 톤 키, eval `FORCED_TONE_SNAPSHOT`↔018 `forced_tone`.

실제로 갈려 있었다 — 006 `friendly` 에서 "안내·권유 표현(…)을 활용한다" 한 문장이 빠져
있었다(2026-08-06 발견·수정, 지금은 그 사본 자체가 없다). 사본이 갈리면 **같은 톤을
골라도 기능마다 결과가 달라지고 평가가 틀린 기준으로 채점한다.**

### 6. `check_vendor_closure.py` — 벤더 사본이 절연돼 있는가 (2026-08-12 삭제, 역사적 기록)

> ⚠️ 이 스크립트와 그것이 지키던 `_vendor/`·`overflow.py`·`hwpx_verify.py` 는 지웠다 —
> 실제 배포 템플릿 3개가 전부 표 없는 1~2쪽짜리라 개봉 안전 게이트·넘침 측정 둘 다
> 아무 판정도 하지 않고 있었다. 아래는 **지우기 전 시점의 기록**이고, 지금 저장소에는
> 해당 파일이 없다. 되살릴 일이 생기면 `archive/hwpx-genon-vendor` 브랜치.

```
python onprem/test/check_vendor_closure.py
```

`SFR-006_template_fill/template_fill/_vendor/hwpx/` 는 python-hwpx 의 **일부 사본**이다
(개봉 안전 검사기 + 넘침 측정기, ≈1,670줄). 상류 패키지에는 문서 모델 40k 줄이 더 있고,
우리는 `__init__.py` 를 **빈 스텁**으로 갈아 끼워 그 아래를 끊어 뒀다.

**그 절연은 눈에 보이지 않는다.** 재동기화 때 파일 하나를 상류 것으로 덮어쓰면
`from ..oxml.body import …` 같은 줄이 딸려 들어오고, 그 순간 배포 단위가 없는 모듈을
import 하다 **기동 시점에** 죽는다 — 그때는 이미 폐쇄망이다.

보는 것 넷: ① 벤더 트리의 import 가 stdlib·lxml·내부로만 향하는가 ② 상류를 절대 경로로
부르지 않는가(`from hwpx.… import` 는 설치된 pip 패키지를 집어 온다) ③ 잘라낸 심볼
(`validate_editor_open_safety` 등)이 되살아나지 않았는가 ④ 배포 단위 코드가 `hwpx` 를
직접 import 하지 않고 requirements 에도 없는가.

**import 시도로 때우지 않는 이유**: `import template_fill.overflow` 가 성공해도 폐포가
닫힌 것은 아니다. 함수 안에 숨은 지연 import 는 호출 전까지 조용하고, 상류가 실제로 그렇게
쓴다(`validate_editor_open_safety` 안의 `from ..document import HwpxDocument` 가 그 예다).
그래서 `ast` 로 **소스를 읽어** 판정한다.

가져온 것·뺀 것·재동기화 절차는 `_vendor/README.md`, 왜 pip 의존이 아닌지는
`onprem/docs/hwpx_library_adoption.md` §6.

## 아직 여기서 못 보는 것

배포 전제 자체를 확인하는 항목이라 스크립트로 잡을 수 없다. `onprem/README.md` 의
"옮기는 순서" 1단계에서 사람이 확인한다.

- 워크플로우 pod 기본 이미지의 `lxml`·`redis` 유무 (운영팀 요청 사항)
- 코드 서빙 이미지의 `genon.preprocessor` 유무 → **006** PDF 다운로드 가용성
  (FAQ 는 2026-08-12 부터 txt 만 내므로 이 전제와 무관하다)
- 워크플로우 pod ↔ 코드 서빙 pod 의 Redis·템플릿 볼륨 공유
- **폐쇄망에서 CDN 업로드(`/minio/upload/temp`)가 실제로 되는지** — 안 되면 `download_url`
  이 계속 `None` 이고 사용자는 결과를 화면에서 복사해야 한다 (fail-open 이라 결과는 나간다)
- presigned URL 수명 — 경로가 `/temp` 라 만료가 있는데 그 값을 우리가 정하지 못한다
- 다운로드 버튼이 `download_url` 을 여는지, 옛 `POST /download` 를 부르는지
- **받은 .txt 를 실제 윈도우 메모장에서 열어보기** — BOM·CRLF 규약은 바이트로 확인했지만
  사내 PC 의 메모장 버전에서 눈으로 본 것은 아니다

## 상태 (2026-09-03 — **13개 스크립트 전부 종료 코드 0**, OK 755건 / WARN 3)

> **2026-09-03 3차 (톤 4종·문서유형 5종)**: `check_tone_policy` 22→**24**(톤 3→4 로 +2,
> 문서유형 8→5 로 −3, **옛 톤 별칭** 판정 +3), `check_eval_metrics` 80→**81**(새 톤
> `clear` 가 실제로 갈리는가). SFR-018 unittest 는 300 그대로 — `test_admin_policy` 넷이
> 내장 목록을 **베끼고 있어** 함께 고쳤고, 다시 베끼지 않게 `TONE_PRESETS` 에서 파생시켰다.
>
> **2026-09-03 후반 (FAQ 총 개수 규약 + hwpx 페이지 필드)**: `check_unit_endpoints`
> 81→**83**(총 개수 상한 하나만 노출 · 배분이 총 개수를 지킨다 · 호출 수 상한),
> SFR-018 unittest 298→**300**(페이지 필드가 구역을 따라간다).
> `check_final_preprocessor` 는 그때 168 이었다 — **벤더 참조 사본에 오타가 들어가 한 번
> FAIL 했다**(`split_docuㄱments`, IDE 에서 열어 둔 파일에 실수로 입력). 되돌리고 세
> 생성물(`final`·`test`·`transfer`)을 다시 만들어 통과. 그 판정이 그물 노릇을 했다.
>
> **2026-09-03 (프롬프트 라이브러리)**: 네 단위가 프롬프트 문장을 라이브러리 ID 로
> 덮어쓰게 되면서 넷이 늘었다 — `check_api_contract` 46→**50**,
> `check_unit_endpoints` 83→**89**, `check_deploy_contract` OK 63→**64**
> (`check_prompt_library_copies` — 사본 4벌 AST 대조), SFR-006 unittest 54→**64**
> (`test_prompt_library` 신설 10건). **로더의 라이브러리 분기를 끄면
> "라이브러리 본문이 파일을 덮는다" 가 FAIL** 하는 것을 확인했다.
>
> **2026-09-03 (전부 다시 돌렸다)**: 위 표의 건수는 이날 실측값이다 — 13개 점검 **755건**
> (`check_deploy_contract` OK 64 포함) + unittest **364건**(SFR-006 64 · SFR-018 300).
> 2026-08-30~09-02 사이에 늘어난 것: 006 **대화 중간 업로드**(`check_chat_turn` 34→41 ·
> `check_api_contract` 45→46 · SFR-006 unittest 48→54) · **스트리밍 되살림**
> (`check_workflow_run` 85→91) · **PII 마스킹 누락**(`check_eval_metrics` 68→80) ·
> 전처리기 **지능형 제거·이관 키트·설치본 가드**(`check_final_preprocessor` 119→168,
> 그 뒤 **빌드 제거로 155**).
>
> **2026-08-30 (eval 강화)**: `check_eval_metrics` **신설 68건** — 평가지표 자체를
> 검증한다. 그전에는 eval 에 회귀 점검이 **0건**이었고, 붙이자마자 결함 일곱이 나왔다
> (**대부분 "재지 않고 통과" 쪽으로 틀려 있었다**). 나머지 열한 개는 그대로다.
> 일곱 갈래를 각각 되돌려 FAIL 을 확인했다 — 별칭 계약 · 환각률 measurable ·
> 조사 정밀도 · 자카드 문장 단위 · 어미 미측정 · 슬롯 잔여 표기 · 카탈로그 행.
>
> **2026-08-29 (긴 문서 커버·안내문·번역 문맥)**: `check_workflow_run` 80→**84**
> (용어 미준수 안내문 — 건수만 말하는가·재번역을 유도하는가·정상 응답엔 키가 없는가·
> 값이 안 실리는가), `check_unit_endpoints` 68→**74**(글다듬이 조각 분할 — 라우트가
> 실제로 나누는가·문단 경계가 남는가·실패한 조각에 원문이 남는가·전량 실패는 오류인가).
> SFR-018 unittest 249→**290**(`test_faq_chunking` 14 · `test_polish_chunking` 16 ·
> `test_translation_context` 11). 일곱 갈래를 되돌려 FAIL 을 봤다.
>
> **`check_chat_turn` 이 22→23 인 것은 이번 변경과 무관한 드리프트다** — 006 은
> 건드리지 않았고, 표의 숫자가 낡아 있었다.

> **2026-08-28 (2차 — 양쪽 하이라이트·MinIO 링크)**: `check_mcp_tools` 75→**76**
> (삭제가 원문 사본에 보이는가), `check_unit_endpoints` 66→**68**(원문 사본을 함께
> 내는가 · 업로드 실패가 결과를 버리지 않는가). SFR-018 unittest 236→**249**.
> **한국어 조사 폴백**으로 `check_mcp_tools` 가 76→**80** 이 됐다(폴백 3갈래 +
> 과절단 가드) — 두 방향을 각각 되돌려 FAIL 을 봤다. 그 폴백이 없으면 하이라이트가
> 아니라 **프롬프트·준수율이 먼저 틀린다**(ko→en 은 용어가 안 실리고 준수율 1.0,
> en→ko 는 제대로 옮긴 번역이 준수율 0.0).
> 되돌려 FAIL 을 본 갈래는 둘이다 — MCP 원문 사본 제거(`check_mcp_tools`·
> `check_workflow_run` **동시 FAIL**), 번역 원문 사본을 번역문 쪽 규칙으로 되돌림
> (`test_glossary_policy` 2건 FAIL). **후자는 엔드포인트 점검이 못 잡는다** —
> 게이트웨이가 없는 점검 환경에서는 전량 폴백돼 사본과 정본이 같아지므로,
> 그물을 유닛 테스트로 옮겼다.
>
> **2026-08-28 (1차 — 하이라이트 상한 제거)**: 건수는 그대로(444)이고 `check_mcp_tools` 의 `diff_changes` 판정
> 하나가 바뀌었다 — "상한에 걸린 사실을 낸다" → **"변경 건수에 상한을 두지 않는다"**.
> 잘린 목록으로 표시용 사본을 만들어 **상한이 곧 하이라이트 상한**이었다(51번째
> 변경부터 `<mark>` 미부착). SFR-018 unittest 는 235→**236**. 상한을 되살려 두 그물이
> 동시에 FAIL 하는 것을 확인했고, 판정은 **끝 낱말이 칠해졌는지**까지 본다 —
> 건수만 세면 상한이 80 으로 올라간 상태도 통과한다.

> **2026-08-27 에 둘이 늘었다**: `check_mcp_tools` 68→**75**, `check_workflow_run`
> 74→**80** — 변경 낱말 하이라이트(`diff_changes` 좌표·`<mark>` 사본, 화면이 사본을
> 쓰는가). 함께 SFR-018 unittest 가 218→**235** 가 됐다(`test_diff_highlight` 17건 신규).
> 되돌려 FAIL 을 본 갈래는 여섯이다 — HTML 태그 토큰화 · 보호 구간 · 낱말 단위 ·
> 화면이 사본을 쓰는가(번역·글다듬이 **각각**) · 하단 목록 부재.
>
> 그 전 2026-08-23 에 `check_table_grid` 18→**33**(누락 방지 3층, 사본 5벌).
> 2026-08-18 에 네 건: `check_mcp_tools` 46→68(스키마 enum·언어 교차검증·관리자 정책),
> `check_unit_endpoints` 61→**66**, `check_workflow_run` 72→74,
> `check_tone_policy` 18→**22**(정책 파서 사본 대조). `check_deploy_contract` 는 63 그대로다.
>
> **`SSL_CERT_FILE` 이 없는 경로를 가리키면**(conda 기본값이 그럴 수 있다)
> `check_unit_endpoints` 의 두 단위가 `FileNotFoundError` 로 실패한다 — 코드 결함이
> 아니다. 그 변수를 비우고 다시 돌린다.

> **지금 값은 이 문서 위쪽 표(스크립트별 건수)와 `HANDOFF.md` §3-1 이 정본이다.**
> 아래는 **그때그때의 역사적 기록**이라 지금 수치와 다르다 — 무엇이 왜 늘고 줄었는지를
> 남기려고 지우지 않았다. 이 아래에서 본 숫자로 판단하지 말 것.
> (`check_vendor_closure.py` 는 2026-08-12 에 **삭제됐다** — 아래 기록에는 아직 나온다.)

### 영역 재배치 시점 기록 (2026-08-11)

> **영역 재배치 반영 (2026-08-11 후반).** 배포 단위가 `onprem/codeserving/` 아래로
> 내려가고 `onprem/mcp/`·`onprem/workflow/` 가 생기면서 이 폴더 전체를 손봤다.
> 아래 개별 항목의 건수는 재배치 **전** 기록이고, 지금 수치는 이렇다:
>
> | 스크립트 | 지금 | 바뀐 이유 |
> |---|---|---|
> | `check_deploy_contract.py` | FAIL 0 / WARN 5 / **OK 53** | 단위 목록이 코드서빙 4 + **MCP 4** + eval 로 늘고, **워크플로우 스텝 점검 3건**이 새로 생겼다 |
> | `check_chat_turn.py` | **25/25** | 대화가 02 스텝 3개 ↔ 03 `chat_api` 로 갈렸다 |
> | `check_tone_policy.py` | **26/26** | 원본이 글다듬이 → **MCP `lang_policy`**, 대조 사본이 3벌 → **4벌** |
> | `check_table_grid.py` | **10/10** | MCP `genon_hwpx_text` 사본이 대조 대상에 추가됐다 |
> | 나머지 4개 | 그대로 (42·17·17·7) | 경로만 바뀌었다 |
>
> **`check_workflow_steps()` 가 이번 추가분 중 제일 중요하다.** 스텝 9개가 (ㄱ)
> `run(data)` 단일 정의인지 (ㄴ) 외부 패키지가 `httpx` 뿐인지 (ㄷ) 서로 import 하지
> 않는지를 AST 로 본다. (ㄴ)가 재배치의 계약 자체이고, (ㄷ)는 공용 모듈로 빼려는 시도를
> 잡는다 — 로컬에서는 잘 돌아 보이지만 캔버스에는 붙일 수 없게 된다.
>
> 재배치가 드러낸 결함 둘(프롬프트 경로·톤 실패 유실)은 `../ARCHITECTURE_SPLIT.md`
> "실행 결과" 절에 있다.

- `check_api_contract.py` — **42/42 통과.** `fastapi` 를 설치해 처음으로 돌렸고, 거기서
  두 가지가 드러났다: ① `POST /generate` 가 개봉 안전 게이트에 막히고 있었다(픽스처가
  온전한 패키지가 아니어서 — `hwpx_package` 로 고쳤다) ② **루트 경로 점검이 아예 없었다.**
  ②를 메우려고 넣은 2건이 곧바로 실패했다 — `@app.get("")` 만으로는 `/` 도 `""` 도
  404 다(세 코드서빙 단위 전부 그 상태였다). 지금은 `@app.get("/")` 를 함께 등록한다.
- `check_chat_turn.py` — **23/23 통과.**
- `check_body_blocks.py` — **17/17 통과.** 안전장치를 일부러 무력화하면 실패하는 것까지
  확인했다(화이트리스트 제거 → 6건 FAIL, 적용 순서 뒤집기 → 3건 FAIL).
  2026-08-10 에 `_build_document` 가 `verify=False` 로 바뀌었다 — 개봉 안전 게이트가 이제
  항상 돌아서, 파트 세 개짜리 최소 픽스처를 **정당하게** 거절하기 때문이다(이 파일이 재는
  것은 문단 복제이지 패키지 계약이 아니다).
- `check_tone_policy.py` — **10/10 통과.** 006 사본을 수정 전으로 되돌려 보고 FAIL 이
  나는 것까지 확인했다.
- `check_table_grid.py` — **9/9 통과.**
- `check_output_safety.py` — **17/17 통과.** SKIP 경로가 없어졌다(벤더 사본 도입).
- `check_vendor_closure.py` — **7/7 통과.** 위반을 일부러 심어 FAIL 이 나는 것까지
  확인했다(상류 절대 import + 미허용 패키지 + 잘라낸 심볼 부활 → 3건 FAIL).
- `check_deploy_contract.py` — **FAIL 0 / WARN 5 / OK 27** (2026-08-11). 드디어 종료 코드
  0 이라 CI 에 걸 수 있다. 그 전까지 이 점검은 **영구히 빨간색**이었고, 그래서 아무도
  보지 않았다 — `SFR-018_faq` 가 배포 단위인데 `requirements.txt` 도 없고 이 스크립트의
  단위 목록에도 없다는 사실이 그 빨간색에 묻혀 넉 달을 살아남았다. 고친 것 넷:
  - **실제 누락을 채웠다**: 006 `jinja2`, 번역 `jinja2`·`lxml`·`python-multipart`,
    FAQ 는 `requirements.txt` 를 새로 만들었다. 번역의 뒤 둘은 **기동 자체를 막는다.**
  - **단위 목록에 `SFR-018_faq` 를 등록**했다.
  - **FAIL 과 WARN 을 나눴다.** 이미지가 제공하는 것(`genon`·`main_socketio`)과 코드가
    `try/except ImportError` 로 이미 방어하는 것(당시엔 `weasyprint`·`markdown`·`fastmcp`,
    지금은 `fastmcp` 하나 — 앞 둘은 FAQ 내보내기와 함께 2026-08-12 에 없어졌다)은
    WARN 이다. 후자는 이름 하드코딩이 아니라 **AST 로 방어 여부를 보고** 판정한다.
  - `File(` 이 `zipfile.ZipFile(` 에 걸려 eval 이 오탐으로 잡히던 것을 고쳤다.

  남은 WARN 4는 전부 의도된 것이다(위 두 부류 + 루트 `main.py` 없음 → 시작 커맨드 필수).
  2026-08-12 에 5→4 가 됐다 — FAQ 가 `genon.preprocessor`(PDF 변환기)를 더는 부르지 않는다.
  FAIL 둘 다 **기존 사항이고 의도된 것**이라 판단해 그대로 둔다:
  - SFR-006 의 `genon`(전처리기)·`main_socketio`(GenOS 런타임)은 requirements 로 설치하는
    대상이 아니라 **이미지·pod 가 제공해야 하는 것**이다 (11.5.6). 스크립트가 "import 는
    있는데 선언이 없다"로 잡는 것이 맞지만, 조치는 requirements 추가가 아니라 이미지 확인이다.
  - 평가지표 MCP 는 배포 단위가 아니다.

  WARN(루트 `main.py` 없음 → 시작 커맨드 필수)도 이미 알고 있는 사항이다(`onprem/README.md`
  "코드서빙 실행"). **스크립트를 고쳐 이 셋을 예외 처리할지는 결정하지 않았다** — 지금은
  FAIL 이 보이는 편이 낫다고 보고 남겨 둔다. 종료 코드가 1이라 CI 에 그대로 걸면 막힌다.
- `verify_serving.py` — **아직 실행하지 않았다** (배포된 서빙이 필요하다).

Windows 콘솔에서 돌릴 때는 `PYTHONIOENCODING=utf-8` 을 준다 — 안 그러면 cp949 가
출력의 `—` 에서 죽는다(점검 결과와 무관한 콘솔 문제).
