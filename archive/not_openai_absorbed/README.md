# `not/openai/` — **`not/` 으로 흡수됐다** (2026-09-09)

> 이 디렉토리는 **참고용 보관본**이다. 등록하지 않는다.

## 무슨 일이 있었나

`not/openai/` 는 `onprem/codeserving/` 을 떠서 **LLM 전송 계층만** `openai` SDK 로 바꾼
한시 판본이었고, 그 위에 **번역 스트리밍**과 **FAQ 스트리밍**이 얹혀 있었다.

2026-09-09 에 사내 mirror 에 **`lxml`·`openai` 가 들어왔다.** 그래서 `not/` 이 깎아낸
판본일 이유가 없어졌고, **반입 판본을 `not/` 하나로 정했다** — 이 판본의 네 단위가
그대로 `not/` 이 됐다(전송 계층 + 스트리밍이 이미 여기에 있었다).

그때 이 판본에 있던 결함 하나를 고쳐서 옮겼다: **FAQ 스트리밍이 HTTP 로 열려 있지
않았다.** 엔진(`markdown_items.py` 증분 파서 · `faq_stream_async` ·
`generate_faqs_stream`)은 다 있는데 `main.py` 가 그것을 import 조차 하지 않아
**호출부가 0건**이었고, 점검(`check_openai_units.py`)은 오히려 "FAQ 는 스트리밍이
없다" 를 기대해 **FAIL 1건**으로 남아 있었다(점검이 기능보다 먼저 굳은 자리다).
`not/` 에는 `POST /generate/stream` 이 붙어 있다.

## 지금 어디를 봐야 하나

| 알고 싶은 것 | 정본 |
|---|---|
| 반입 판본이 무엇인가 | `not/README.md` |
| 왜 그렇게 정했나 | `not/PROGRESS.md` |
| 그물 | `not/check_not_units.py` (**91건**) |
| 기능 설계의 근거 | 루트 `CLAUDE.md` · `onprem/` 정본 문서 |

## 이 보관본의 그물은 낡았다

`check_openai_units.py` 는 **FAIL 1건**(FAQ 스트리밍 기대값)으로 남아 있다. 고치지
않고 그대로 둔다 — 이 판본은 더 이상 유지 대상이 아니고, 그 FAIL 이 **"여기는 옛
판본이다" 를 말하는 표식**이기 때문이다. 되살릴 일이 생기면 `not/` 에서 옮겨 적는다.
