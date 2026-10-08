# Test/check — 배포 계약·기능 점검

배포 단위 **바깥**에 둔다 — 가짜 LLM·Redis·게이트웨이 주입을 등록 코드 안에 두지 않기 위해서다.
어느 배포 단위도 이 폴더를 import 하지 않는다.

## 경로는 `paths.py` 한 곳이 안다

`SOURCE` 표가 코드서빙 네 단위를 `final/` 과 `no_pythonstep/` 중 어디서 볼지 정한다 —
018 셋은 `no_pythonstep`, 006 은 `GENON_SFR006_SOURCE`(기본 `final`). MCP·워크플로우·전처리기는 `final/`.
점검마다 경로를 들면 옮길 때 한둘이 빠지고, 그 상태는 **FAIL 이 아니라 건수가 조용히 줄어드는** 모양으로만
드러난다 — 그래서 `run_all.py` 가 건수까지 본다.

## 점검

| 스크립트 | 무엇을 보나 |
|---|---|
| `check_deploy_contract` | 소스만 읽는 정적 점검 — requirements·`/health`·루트 `main.py`·예약 환경변수·`print` 금지·사본 대조·MCP 규약·워크플로우 스텝 |
| `check_service_boot` | 네 단위를 실제로 띄운다 — lifespan·`/health`·`/`·라우트 등록 |
| `check_chat_direct` | **018 `/chat`** (006 은 `no_pythonstep` 판일 때) — SSE 프레임 규약·`complete` 값·오류 SSE·`[입력된 문서]`·머리말·heartbeat·이벤트 이름·업로드 실패·LLM 전량 실패·글다듬이 MCP 점검 |
| `check_api_contract` | 006 엔드포인트 한 바퀴 |
| `check_unit_endpoints` | 018 세 단위 엔드포인트 경계 · md 규약 세 단위 대조 |
| `check_chat_turn` | 006 대화 한 턴 (워크플로우 스텝 3개 ↔ 코드서빙) |
| `check_workflow_run` | 워크플로우 스텝 9개 실행 · MCP 전송 규약 · 스트리밍 전송 규약 |
| `check_mcp_tools` | MCP 파일 공존·결정적 판정·빈 문자열 주입·스키마 enum |
| `check_final_preprocessor` | `final_preprocessor.py` — 라우팅·조문 위계·무손실 (실물 hwpx 5벌, 있는 것만) |
| `check_high_preprocessor` | `high_preprocessor.py` — pdf 단·문단·OCR·hwp·그림 (docling_core 없으면 hwp 빠짐) |
| `check_smart_preprocessor` | 지능형 + hwpx (등록하지 않는다 — 회귀만) |
| `check_table_grid` | hwpx 파싱 코어 사본 대조 (출력으로) |
| `check_prompt_render` | 네 단위 프롬프트가 실제로 렌더되는가 |
| `check_tone_policy` | 톤 사본 3벌 · 옛 톤 별칭 대조 |
| `check_body_blocks` | 006 문단 복제 안전장치 |
| `check_output_safety` | 006 파트 선언·누름틀 안내문 |
| `check_eval_metrics` | 평가지표(eval) 자체 |

점검이 아닌 파일: `paths.py`(경로) · `hwpx_package.py`(점검용 hwpx 픽스처를 온전한 패키지로 감싼다) ·
`verify_serving.py`(**배포된** 서빙에 실제 요청 — 배포 뒤에 손으로 돌린다) · `diagnose_hwpx_markers.py`(진단 도구).

코드서빙 단위들이 최상위 이름(`main`·`config`·`chat_api`)을 겹쳐 쓰므로 `check_service_boot`·
`check_unit_endpoints`·`check_chat_direct` 는 **단위마다 subprocess** 로 띄운다. `check_mcp_tools` 는 반대로
**일부러 한 네임스페이스에** 넣는다 — 이름이 겹쳐 덮이는지가 곧 MCP 의 계약이다.

## 실행

```
python Test/run_all.py                       # 전부 (006 = final)
python Test/run_all.py --006=no_pythonstep   # 006 도 no_pythonstep
python Test/run_all.py chat_direct           # 이름 일부로 골라서
```

기준 건수는 `run_all.py` 의 `EXPECTED`·`EXPECTED_BY_006`. 점검을 늘리거나 줄이면 같이 고친다.
