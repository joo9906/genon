# SFR-018 — 회귀 테스트

구현은 없다. 등록 코드를 직접 import 한다 — `tests/final_path.py` 가 `Test/check/paths.py` 에서 경로를 받는다.

| 대상 | 어디 |
|---|---|
| 번역·글다듬이·FAQ 코드서빙 | `no_pythonstep/SFR-018-*/` |
| 구조 훼손 감지·변경 내역 (`test_markdown_guard`·`test_diff_highlight`) | MCP `final/mcp/genon_text_guard.py` — 파일째 싣는다(`load_mcp`) |
| 전처리기 청킹·조문 위계 (`test_preprocessor_chunking`) | `final/preprocessor/` |
| `/chat` 입력 해석 (`test_chat_input`) | 세 단위의 `chat_input.py` — 번역·글다듬이는 최상위 이름이 같아 파일 경로로 싣는다 |

```
python Test/run_all.py SFR-018      # 404건
```

번역·글다듬이 코드서빙은 `config`·`main` 같은 흔한 최상위 이름을 겹쳐 쓴다 — 테스트 파일마다
`final_path.install(필요한 단위만)` 으로 경로를 세운다. 엔드포인트·`/chat` SSE 는 `Test/check/` 가 본다
(`check_unit_endpoints`·`check_chat_direct`).
