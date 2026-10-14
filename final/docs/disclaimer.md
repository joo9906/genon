# 안내 문구 (disclaimer) — 상황별 문장

결과는 냈지만 사용자가 알아야 하는 것을 화면에 말하는 문장이다. **언제 띄울지와 숫자는 워크플로우
스텝이 정하고, 문장만 Disclaimer MCP(`widget_disclaimer`)에서 받는다.**

- 번호 연결: 워크플로우 환경변수 `DISCLAIMER_IDS` 에 `종류=번호` (예: `faq_shortfall=1,translate_failed_units=4`).
  `agent_id` 는 `DISCLAIMER_AGENT_ID`(기본 `SFR018`). 환경변수 전체는 [`env.md`](env.md) §5.
- **자리표시**: 등록 문장에 `{count}` 처럼 쓰면 그 자리에 숫자가 들어간다. 자리표시가 하나도 없으면
  **첫 번째 숫자를 문장 앞에 붙인다** — `faq_shortfall` 에 `개의 FAQ를 생성하는데 실패하였습니다` 를
  등록하면 `3개의 FAQ를 생성하는데 실패하였습니다` 가 된다.
- **번호가 없거나 MCP 를 못 부르면 아래 "고정 문장"이 나간다.** 안내가 빠지지는 않는다.
- 문장에는 **건수만** 싣는다. 어느 용어·어느 숫자·어느 문장인지는 싣지 않는다(문서 내용이다).
- 화면에는 result 의 `notice`(목록)로 나간다. `faq_shortfall` 만 따로 `disclaimer` 필드다.

코드 위치: `final/workflow/sfr018_polish_02_polish.py` · `sfr018_translate_02_translate.py` ·
`sfr018_faq_02_generate.py` 의 `wanted` 목록 (함수는 세 파일에 같은 사본 `_disclaimer`·`_disclaimers`).
입력 판단으로 멈출 때의 문장은 다듬-1 · 번역-1 의 `_check_input` 이 받는다(같은 사본 `_disclaimer`).

---

## 입력 판단 (다듬-1 · 번역-1) — 결과 대신 나가는 문장

코드서빙 `POST /input/check` 가 뜻을 알 수 없는 입력(낱자모 나열 · 빈 표 틀)이라고 판단하면 스텝 1 이
오류 `INPUT_UNUSABLE`(재시도 불가)로 멈추고 이 문장을 `error.msg` 로 낸다. 판단을 못 하면(서빙 장애 등)
막지 않고 그대로 진행한다.

| 종류 | 언제 | 자리표시 | 고정 문장 |
|---|---|---|---|
| `polish_input_unusable` | 다듬을 만한 글이 아니라고 판단했을 때 | 없음 | 입력 내용을 확인해 주세요. |
| `translate_input_unusable` | 번역할 만한 글이 아니라고 판단했을 때 | 없음 | 입력 내용을 확인해 주세요. |

---

## 글다듬이 (다듬-2)

| 종류 (`DISCLAIMER_IDS` 이름) | 언제 | 자리표시 | 고정 문장 |
|---|---|---|---|
| `polish_failed_chunks` | 긴 문서를 나눠 다듬다가 일부 구간이 실패해 원문을 그대로 둔 경우 | `{count}` 실패 구간 수 | 문서 일부 구간({count}곳)을 다듬지 못해 원문 그대로 두었습니다. 다시 시도해 주세요. |
| `polish_structure_changed` | 표·제목 등 마크다운 구조가 원문과 달라진 곳이 있을 때 (`markdown_structure_issues`) | `{count}` 달라진 곳 | 표·제목 등 문서 구조가 원문과 달라진 곳이 {count}곳 있습니다. 결과를 확인해 주세요. |
| `polish_fact_mismatch` | 숫자·날짜가 원문과 다른 곳이 있을 때 (`fact_issues`) | `{count}` 다른 곳 | 숫자·날짜가 원문과 다른 곳이 {count}곳 있습니다. 결과를 확인해 주세요. |
| `polish_stream_diverged` | 흘리는 도중 연결이 끊겨 화면에 보였던 글과 최종 결과가 다를 때 | 없음 | 다듬는 도중 연결이 끊겨 화면에 잠시 보였던 문장이 최종 결과와 다를 수 있습니다. 아래 결과를 확인해 주세요. |

## 번역 (번역-2)

| 종류 | 언제 | 자리표시 | 고정 문장 |
|---|---|---|---|
| `translate_glossary_unapplied` | 원문에 나온 용어사전 용어를 번역문이 쓰지 않았을 때 | `{count}` 반영 안 된 용어 수 | 용어사전 용어 {count}개가 번역문에 반영되지 않았습니다 (원문에서 형광으로 표시된 자리입니다). 다시 번역하면 반영될 수 있습니다. |
| `translate_failed_units` | 일부 문장 번역이 실패해 원문을 그대로 둔 경우 (전량 실패는 안내가 아니라 오류) | `{count}` 실패 문장 수 | 문장 {count}개를 번역하지 못해 원문 그대로 두었습니다. 다시 번역해 주세요. |
| `translate_numeric_mismatch` | 원문과 번역문의 숫자·날짜가 다를 때 (`numeric_issues`) | `{count}` 다른 곳 | 원문과 번역문의 숫자·날짜가 {count}곳 다릅니다. 결과를 확인해 주세요. |

## FAQ (FAQ-2)

| 종류 | 언제 | 자리표시 | 고정 문장 |
|---|---|---|---|
| `faq_chunks_missing` | 긴 문서의 일부 구간에서 FAQ 를 하나도 못 만들었을 때 | 없음 | 문서 일부 구간에서 FAQ 를 만들지 못했습니다. 다시 시도하면 더 나올 수 있습니다. |
| `faq_over_requested` | 문서가 길어 구간마다 만들다 보니 요청보다 많이 나왔을 때 | `{chunks}` 구간 수 · `{requested}` 요청 개수 · `{count}` 나온 개수 | 문서가 길어 {chunks}개 구간으로 나눠 구간마다 만들었습니다. 요청하신 {requested}개보다 많은 {count}개가 나왔습니다. |
| `faq_under_requested` | 근거가 확인된 항목이 요청보다 적을 때 | `{requested}` 요청 개수 · `{count}` 나온 개수 | 요청하신 {requested}개 중 {count}개만 문서에서 근거를 확인했습니다. |
| `faq_shortfall` | 위와 같은 판정 — result 의 **`disclaimer` 필드**(화면이 부족분을 이 필드로 읽는다) | `{shortfall}` 모자란 개수 | {shortfall}개를 생성하지 못하였습니다. |

`faq_under_requested` 와 `faq_shortfall` 은 같은 상황에서 함께 나간다(앞은 `notice` 목록, 뒤는 `disclaimer` 필드).
화면이 둘 다 보여 주면 같은 말을 두 번 하게 되니 등록 문장을 정할 때 함께 볼 것.

## 자리표시 없이 등록하면 앞에 붙는 숫자

| 종류 | 앞에 붙는 값 |
|---|---|
| `polish_*` · `translate_*` (`polish_stream_diverged` 제외) | `{count}` |
| `faq_over_requested` | `{chunks}` (구간 수) — 이 안내는 숫자가 셋이라 자리표시를 쓰는 편이 맞다 |
| `faq_under_requested` | `{requested}` (요청 개수) — 마찬가지로 자리표시 권장 |
| `faq_shortfall` | `{shortfall}` |
| `polish_stream_diverged` · `faq_chunks_missing` · `*_input_unusable` | 숫자 없음 — 등록 문장 그대로 |
