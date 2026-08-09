# onprem/test — 배포 계약 점검

GenOS 개발가이드 6장(코드 서빙)·11.3·11.5 가 요구하는 **배포 확인 항목**을 스크립트로
모아 둔 곳이다. 기능 회귀 테스트가 아니다.

## 이게 왜 여기 있나 — `onprem/` 은 tests 를 두지 않는 디렉토리인데

`onprem/` 규칙은 **배포 단위 안에** 테스트 코드와 mock 경로를 두지 않는 것이다. 폐쇄망에
올라가는 이미지에 가짜 경로가 섞여 흘러가는 것을 막기 위해서다.

이 폴더는 **배포 단위 바깥**(`onprem/SFR-*` 형제 위치)이고, 세 단위 중 어느 것에도
import 되지 않는다. Git 저장소를 그대로 올리더라도 빌드 커맨드가 설치하지 않고 시작
커맨드가 실행하지 않으므로 런타임에 존재하지 않는다.

기능 회귀 테스트는 여전히 `SFR-006/`·`SFR-018/` 사본에 둔다 (루트 `CLAUDE.md` 의
"검증 명령" 절).

## 두 단계로 나뉜다

| 스크립트 | 언제 | 서버 필요 | 포트 |
|---|---|---|---|
| `check_deploy_contract.py` | 지금, 커밋 전 | 없음 | 열지 않음 |
| `verify_serving.py` | 서빙 배포한 뒤 | 배포된 서빙 | 열지 않음 (요청만 보냄) |

여기에 더해 **점검 네 개가 더 있다.** 배포 계약이 아니라 기능·사본 점검인데, `onprem/`
규칙상 배포 단위 안에 `tests/` 를 둘 수 없어서 여기 모였다. 가짜 Redis·가짜 LLM 주입은
**배포 단위 바깥에서만** 해야 운영 코드에 테스트 분기가 생기지 않는다.

| 스크립트 | 건수 | 성격 | 무엇을 잡나 |
|---|---|---|---|
| `check_api_contract.py` | 40 | 특성화 | 코드 서빙 12개 엔드포인트 한 바퀴 (인프로세스 FastAPI) |
| `check_chat_turn.py` | 23 | 특성화 | 대화 한 턴 계약(`token`…`result`)과 상태 전이 |
| `check_body_blocks.py` | 17 | 기능 | 문단 복제 안전장치·서식 상속·적용 순서 |
| `check_tone_policy.py` | 10 | 사본 대조 | 018↔006↔eval 톤 문구 일치 |
| `check_table_grid.py` | 9 | 사본 대조 | 006↔번역↔FAQ **표 격자 규칙** 일치 (텍스트가 아니라 출력으로 대조) |
| `check_output_safety.py` | 12 | 기능 | 파트 XML 선언·누름틀 안내문·개봉 안전 게이트·표 셀 넘침 |

앞의 둘은 **특성화(characterization) 점검**이다 — "지금 동작이 이렇다" 를 못 박아 두고
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

**기능 회귀 테스트의 제자리는 `SFR-006/template_fill/tests/` 다.** 그런데 그 사본에는
라벨 항목 파서가 없다(`collect_label_occurrences`·`own_nodes`·`nearest_para` 가 onprem
에만 있다 — 루트 `CLAUDE.md` "남은 일"). 본문 블록은 그 파서 위에 서 있어서, 사본에
유닛테스트를 붙이려면 라벨 파서부터 통째로 이식해야 한다. 그건 별건이라 그 이식이 끝날
때까지만 여기 둔다. **이식하는 순간 이 파일은 `tests/` 로 옮겨 unittest 로 바꾼다.**

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
| `SFR-018_text_polish/.../tone_presets.py` | **원본.** 톤 문구는 여기부터 고친다 |
| `SFR-006_template_fill/.../tone_presets.py` | 006 이 값·본문에 적용하는 사본 |
| `eval/eval_mcp/tone_metrics.py` | 평가가 채점 기준으로 쓰는 사본 |

앞의 두 스크립트와 달리 이건 **예외가 아니라 제자리다.** 런타임에는 서로를 import 할 수
없으니 대조할 수 있는 곳이 배포 단위 바깥뿐이고, 그게 여기다.

대조 대상: 006↔018 톤 키·label·지시문(**글자 단위**), eval↔018 톤 키,
eval `FORCED_TONE_SNAPSHOT`↔018 `forced_tone`. 006 에 문서유형 정책이 **없는지**도 본다
(2026-08-06 결정 — 생겼다면 결정이 바뀐 것이므로 이 스크립트도 고쳐야 한다).

실제로 갈려 있었다 — 006 `friendly` 에서 "안내·권유 표현(…)을 활용한다" 한 문장이 빠져
있었다(2026-08-06 발견·수정). 사본이 갈리면 **같은 톤을 골라도 기능마다 결과가 달라지고
평가가 틀린 기준으로 채점한다.**

## 아직 여기서 못 보는 것

배포 전제 자체를 확인하는 항목이라 스크립트로 잡을 수 없다. `onprem/README.md` 의
"옮기는 순서" 1단계에서 사람이 확인한다.

- 워크플로우 pod 기본 이미지의 `lxml`·`redis` 유무 (운영팀 요청 사항)
- 코드 서빙 이미지의 `genon.preprocessor` 유무 → PDF 다운로드 가용성
- 워크플로우 pod ↔ 코드 서빙 pod 의 Redis·템플릿 볼륨 공유
- 다운로드 버튼이 실제로 어느 경로로 배선되는지

## 상태 (2026-08-06)

- `check_api_contract.py` — **40/40 통과.**
- `check_chat_turn.py` — **23/23 통과.**
- `check_body_blocks.py` — **17/17 통과.** 안전장치를 일부러 무력화하면 실패하는 것까지
  확인했다(화이트리스트 제거 → 6건 FAIL, 적용 순서 뒤집기 → 3건 FAIL).
- `check_tone_policy.py` — **10/10 통과.** 006 사본을 수정 전으로 되돌려 보고 FAIL 이
  나는 것까지 확인했다.
- `check_deploy_contract.py` — **첫 실행 완료. FAIL 2 / WARN 1 / OK 17.**
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
