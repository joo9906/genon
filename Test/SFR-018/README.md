# SFR-018 — 회귀 테스트

구현은 없다. 등록 코드를 직접 import 한다 — `tests/final_path.py` 가 `Test/check/paths.py` 에서 경로를 받는다.

| 대상 | 어디 |
|---|---|
| 번역·글다듬이·FAQ 코드서빙 | `final/SFR-018-*/request/` |
| 구조 훼손 감지·변경 내역 (`test_markdown_guard`·`test_diff_highlight`) | MCP `final/mcp/genon_text_guard.py` — 파일째 싣는다(`load_mcp`) |
| 전처리기 청킹·조문 위계 (`test_preprocessor_chunking`) | `final/preprocessor/` |

```
python Test/run_all.py SFR-018      # 389건
```

번역·글다듬이 코드서빙은 `config`·`main` 같은 흔한 최상위 이름을 겹쳐 쓴다 — 테스트 파일마다
`final_path.install(필요한 단위만)` 으로 경로를 세운다. 엔드포인트는 `Test/check/check_unit_endpoints` 가 본다.
