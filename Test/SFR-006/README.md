# SFR-006 — 회귀 테스트

구현은 없다. 등록 코드를 직접 import 한다 — `tests/final_path.py` 가 `Test/check/paths.py` 에서 경로를 받는다.

| 묶음 | 대상 | 언제 도나 |
|---|---|---|
| `tests/` (117건) | 006 코드서빙 — 기본 `final/SFR-006/request/` | 늘. `no_pythonstep/SFR-006/` 으로 바꿔도 같은 117건이 통과한다 |
| `tests_chat/` (11건) | `/chat` 직접 호출 입력 해석 (`template_fill/chat_input.py`) | `GENON_SFR006_SOURCE=no_pythonstep` 일 때만 (final 판에는 그 파일이 없어 건너뛴다) |

```
python Test/run_all.py SFR-006                      # final 판
python Test/run_all.py --006=no_pythonstep SFR-006  # no_pythonstep 판 (+ tests_chat)
```

엔드포인트·대화 한 턴·`/chat` SSE 는 `Test/check/` 가 본다(`check_api_contract`·`check_chat_turn`·`check_chat_direct`).
