# 폐쇄망 실측 검증 (`Test/onprem/`)

`Test/check/*.py` 15개와 `Test/SFR-006`·`Test/SFR-018` unittest 는 게이트웨이를
**대역(mock)**으로 갈아 끼워 로직만 본다 — 그게 이 저장소의 회귀 그물이고, 여기서는
그걸 다시 하지 않는다. 이 디렉토리는 반대다: **실제 LLM 게이트웨이**로 실제 hwpx
파일을 네 기능(번역·글다듬이·FAQ·006)에 태우고, 그 결과를 `Test/eval/eval_mcp`
(통과율·숫자 보존·용어사전 준수·PII 등을 내는 채점기)에 먹여 **수치 리포트**를 낸다.

**여기엔 assert 가 없다.** 있는 그대로의 수치를 JSON 으로 남기고 사람이 본다 —
LLM 출력은 실행마다 달라질 수 있어 "항상 이래야 한다" 를 코드로 못박을 수 없다.

## 먼저 — 이 저장소(코드스페이스)에서는 이 스크립트들이 돌지 않는다

`GENOS_URL`/`LLM_SERVING_ID`/`GENOS_TOKEN` 이 없으면 각 단위가 자체적으로
`CONFIG_MISSING` 오류를 낸다(조용히 죽지 않는다). **폐쇄망에서 그 값을 실제로
채운 뒤에만** 의미가 있다. 006 은 추가로 `REDIS_URL` 이 필요하다(세션 저장소) —
없으면 `/chat/*` 흐름이 "세션이 매번 비어서 시작" 으로 떨어져 조용히 왜곡된다
(오류는 아니고, 대화 흐름을 흉내 낸 세션 일관성 검증이 무의미해질 뿐이다).

## 실행 전 준비

```
export GENOS_URL=...
export LLM_SERVING_ID=...
export GENOS_TOKEN=...
export REDIS_URL=...              # 006 만 필요
export TEMPLATE_FILL_ADMIN_TOKEN=...   # 설정돼 있으면 --admin-token 으로 같이 넘긴다
```

`Test/data/<기능>/` 에 hwpx 파일을 넣는다 — 어디서 구하는지는
`Test/data/README.md`. **한 파이썬 프로세스에서 기능을 하나만 돌린다** —
`run_*.py` 넷을 순서대로 이어 부르면 두 번째 기능부터 `main`/`config` 모듈이
sys.modules 에 이미 있어 조용히 첫 기능 설정으로 돈다(`_harness._import_app`
이 이 실수를 막는 가드를 갖고 있다 — 걸리면 바로 세운다).

## 실행

```
cd Test/onprem
python run_translation.py --target-lang en
python run_text_polish.py --doc-type email --tone polite
python run_faq.py --count 5
python run_template_fill.py --template <실제 hwpx 템플릿 경로> \
    --admin-token "$TEMPLATE_FILL_ADMIN_TOKEN" \
    --values-json Test/data/template_fill/values.json
```

넷 다 별도 프로세스로 돈다(위 이유). 각자 `Test/onprem/reports/<기능>_<시각>.json`
에 전체 리포트를 남기고, 콘솔에는 문서별 요약 한 줄씩만 찍는다.

## 006 만 다른 이유 — 템플릿은 외부에서 구할 수 없다

`{{필드명}}` 슬롯 문법은 이 프로젝트 내부 규약이라 공공 데이터셋에 그런 문서가
없다. `--template` 으로 **실제 사내 템플릿**을 직접 지정해야 한다. 두 갈래를
돈다:

- **라운드트립(구조, LLM 불필요)** — `--values-json` 을 주면(`{필드명: 값}` JSON),
  그 값으로 한 번 채워 보고 "박아 넣은 값이 정확한가" 만 결정적으로 잰다.
  안 주면 이 갈래는 건너뛴다(추측한 값으로 잘못 채우고 통과라고 말하지 않는다).
- **문서 자동 채움(LLM 사용)** — `Test/data/template_fill/sources/*.hwpx` 각각을
  "이 문서로 채워줘" 넣어 실제 LLM 추출을 태우고, 세션이 값을 잃거나 덮어쓰지
  않는지(`multiturn_scenario_score`)를 본다. 정답 값을 알고 있으면
  `Test/data/template_fill/expected.json` 에 `{"파일명.hwpx": {"필드명": "정답"}}`
  형태로 적어 두면 필드 추출 정밀도·재현율·환각률(`field_extraction_score`)도
  같이 낸다 — 없으면 그 지표만 건너뛴다.

## 리포트 읽는 법 — `verdict` 넷

`Test/eval/eval_mcp/suites.run_suite` 가 내는 값 그대로다:

| verdict | 뜻 |
|---|---|
| `pass` | 잴 수 있었던 기준을 전부 통과했다 |
| `fail` | 하나 이상 기준을 못 미쳤다 — 리포트의 `targets[].status=="fail"` 항목을 본다 |
| `pass_but_incomplete` | 실패는 없지만 입력이 없어 못 잰 기준이 있다(`skipped_metrics`) |
| `not_measured` / `no_operational_target` | 아무 기준도 못 쟀다 — 대개 그 문서에서 결과 자체가 안 나온 경우다 |

**`fail` 이 나쁜 신호가 아닐 수도 있다.** 예를 들어 번역에서 원문에 없던 숫자가
결과에 생기면(`fact_preservation_check`) 정확히 그걸 잡으려고 만든 지표다 — 통과
못 한 것 자체가 유용한 정보다.

## 이 킷이 검증한 것 / 검증하지 않은 것

- **검증했다(구현 중 실물 hwpx + 대역 LLM 으로 4기능 전부 왕복 확인)**: 네 스크립트가
  실제 라우트를 올바른 필드로 부르는가, 응답 키를 올바르게 읽는가, eval 채점기에
  올바른 모양으로 먹이는가, 오류 응답(4xx/5xx)에서 예외 없이 `DocResult(ok=False)`
  로 떨어지는가.
- **검증하지 못했다(이 환경엔 게이트웨이가 없다)**: 실제 LLM 출력의 품질. 그건
  폐쇄망에서 이 킷을 돌려야 나온다.
- **`variant="open_ai"`(SDK 오버레이)는 다루지 않는다.** 프롬프트 디렉토리를
  상위 탐색으로 찾는 경로가 오버레이 배치에서 달라져, 여기서 흉내 내면 그 자체가
  또 다른 버그 원인이 된다 — 그 판본을 검증하려면 실제로 그 판본을 등록해서 본다.
