# `not/openai/` 작업 진행 기록

> **세션이 끊겨도 여기부터 이어간다.** 무엇을 왜 그렇게 정했는지와, 다음에 손댈 자리를
> 적는다. 완료된 것의 **설계 근거**는 `not/openai/README.md` 와 각 파일 머리말이 정본이고,
> 이 문서는 **진행 상태**만 든다.

최종 갱신: 2026-09-09

---

## 0. 이 판본이 무엇인가 (한 줄)

`onprem/codeserving/` 을 떠 와서 **LLM 전송 계층만** `openai` SDK 로 바꾼 한시 판본.
그 위에 **번역 스트리밍**과 **FAQ 스트리밍**이 얹힌다. 정본은 계속 `onprem/` 이다.

**셋 중 하나만 등록한다** — `onprem/codeserving/` · `not/`(lxml 없음) · `not/openai/`.
문제가 생기면 앞의 둘로 되돌아가면 된다(별개 사본이라 서로 건드리지 않는다).

> ⚠ **프롬프트 이름이 겹치면 그 안전망이 샌다.** 프롬프트 라이브러리 ID 로 덮어쓰면
> 세 판본이 **같은 이름**을 본다. 그래서 이 판본이 새로 만든 프롬프트는 전부
> `stream_` 접두어를 쓴다 — 기존 `system.txt`·`user.txt` 는 **한 글자도 안 건드렸다.**

---

## 1. 완료

### 1-1. 네 단위 SDK 전환 ✅

- `llm.py` 4벌을 `AsyncOpenAI` 판으로 다시 썼다. 공개 API(`llm_call_async` /
  `polish_text_async` / `CONFIG_MISSING` / `LlmResult`)는 그대로라 호출부를 안 고쳤다.
- 정본이 `httpx` 판에서 얻은 셋을 유지했다: **전역 클라이언트 없음**(§D.2) ·
  **4xx 미재시도** · **`max_retries=0`**(SDK 기본 2회가 우리 재시도와 곱해지는데 그
  추가 호출은 우리 로그에 안 남는다).
- **정본과 갈리는 유일한 설정**: `Config.llm_model_id()` (`LLM_MODEL_ID`, 기본
  `"default"`). SDK 가 `model` 없이 요청을 만들지 않는다.
- 네 `requirements.txt` 에 `openai>=1.30` 추가.

### 1-2. 번역 스트리밍 ✅

```
POST /translate/stream    (SSE)   delta … done{translated_text, options, …}
POST /translate/finalize  (JSON)  {original_text, translated_text, glossary, structure,
                                   download_url, options}
```

- 새 파일: `office/stream_chunking.py`(조각 분할·무손실) ·
  `office/stream_pipeline.py`(순서 버퍼·문서 단위 용어 좌표·구조 지문).
- 프롬프트: `system_stream.txt` · `user_stream.txt` · `glossary_stream.txt`.
- `config.STREAM_CHUNK_CHARS`(`TRANSLATE_STREAM_CHUNK_CHARS`, 기본 6000).
- **감수한 것**: 스켈레톤을 안 쓰므로 구조 보장이 코드 → 프롬프트로 넘어간다.
  `structure_diff` 가 끝나고 지문을 대조해 알린다. 정본 경로
  (`POST /translate/markdown`)는 그대로 두었다.

### 1-3. 그물 ✅

`python not/openai/check_openai_units.py` — **62건** (게이트웨이·LLM 불필요).
정적(전송 규약 4벌) · 기동(4단위) · 동작(번역 스트리밍·finalize 좌표).

---

## 2. 진행 중 — FAQ 스트리밍

**요구**: 화면 첫 글자까지 **10초**. 지금 FAQ 는 조각 전체를 다 만들고 내보내서
30~60초다.

### 2-1. 왜 이 설계인가 (다시 세션이 끊겨도 이 판단을 되풀이하지 않게)

- **토큰을 그대로 흘릴 수 없다.** FAQ 항목은 스키마·근거 대조·중복 기각을 지나야
  화면에 나갈 자격이 생기는데, 토큰으로 흘리면 **기각될 항목이 이미 화면에 나타난
  뒤**다("답이 나왔다가 사라진다" — 이 저장소가 계속 피해 온 실패).
- **항목 단위로 버퍼링하면 10초를 못 지킬 수 있다.** 항목 하나 ≈ 300~500토큰
  ≈ 6~16초. 근거(evidence)가 원문을 그대로 베끼는 필드라 짧지 않다.
- **그래서 필드 순서를 뒤집는다** — `근거 → 질문 → 답변`. 검증이 **접두어 연산**이 된다:
  - `근거:` 가 닫히면 → 근거 대조 가능 (실패면 한 글자도 안 내보낸다)
  - `질문:` 이 닫히면 → 중복 판정 가능
  - `답변:` 부터 → 통과한 항목이므로 **토큰 그대로** 흘린다
  - 화면 첫 글자 = 근거 + 질문 ≈ 100~200토큰 ≈ **2~5초**
- **덤**: 근거 우선은 추출형이라 groundedness 에 유리하다. 질문을 먼저 짓고 근거를
  끼워 맞추면 `ungrounded` 기각이 구조적으로 는다.
- **JSON 이 아니라 구분자 형식인 이유**: JSON 은 미완성 상태를 파싱할 수 없어 이
  설계 자체가 불가능하다.
- **조각 순서를 강제하지 않는다.** 번역은 문서 순서가 곧 결과물이라 머리 조각 버퍼가
  필수였지만, FAQ 는 **항목 목록**이라 도착 순서대로 흘려도 된다 — 제일 먼저 끝난
  조각의 첫 항목이 화면에 뜨고 그게 TTFT 를 당긴다. 다만 **최종 `faq_items` 순서를
  흘린 순서와 같게** 맞춰야 한다(안 그러면 마지막에 항목이 재정렬되며 튄다).
- **비스트리밍 경로도 같은 형식으로 바꾼다** (이 판본 안에서만). 형식이 둘이면
  마크다운 파서가 스트리밍 요청에서만 돌아 **거의 검증되지 않는 갈래**가 된다.
  JSON 경로는 `not/` · `onprem/` 두 판본에 그대로 남아 있으므로 폴백은 유지된다.

### 2-2. 체크리스트

- [x] 프롬프트 3벌 — `stream_system.txt` · `stream_user.txt` ·
      `stream_retry_shortfall.txt` (`prompt/SFR-018_faq/`)
- [ ] `faq/markdown_items.py` — **증분 파서**. `feed(text)` 로 델타를 먹이고 완성된
      항목을 뱉는다. 라벨 상수는 프롬프트와 **사본 대조 대상**이다.
- [ ] `faq/llm.py` — `faq_stream_async(system, user, on_delta)` (SDK `stream=True`).
      `STREAM_UNSUPPORTED` 를 갈라 돌려준다.
- [ ] `faq/generator.py` — `generate_faqs_stream(...)`
      - 조각 분할·몫 배분(`plan_quota`)은 **지금 것 그대로**
      - 조각마다 스트리밍 + 증분 파싱 + **항목 단위 검증**
      - `_adopt` 를 항목 하나짜리(`_adopt_one`)로 쪼갠다
      - 도착 순서대로 채택·통보, 최종 목록도 같은 순서
      - `STREAM_UNSUPPORTED` → 비스트리밍으로 폴백
- [ ] `faq/main.py` — `POST /faq/stream` (SSE). 프레임:
      `{"type":"item", …}` · `{"type":"delta", …}`(답변) · `{"type":"done", …}`
- [ ] 비스트리밍 `POST /faq` 도 같은 파서를 타게 한다
- [ ] `check_openai_units.py` 에 FAQ 스트리밍 판정 추가 (되돌려 FAIL 확인)
- [ ] `README.md` · 루트 `CLAUDE.md` 갱신

### 2-3. 되돌려 FAIL 을 봐야 할 갈래 (구현 뒤)

1. 근거 대조를 **항목 완성 뒤로** 미루기 → 기각될 항목이 흘러나가는지
2. 증분 파서에 **미완성 묶음**을 먹였을 때 항목을 내놓는지 (내놓으면 안 된다)
3. 라벨을 하나 바꿨을 때 `rejected_schema` 로 세는지 (조용히 통과하면 안 된다)
4. 흘린 항목 순서 ≠ 최종 `faq_items` 순서
5. `STREAM_UNSUPPORTED` 에서 폴백이 같은 결과를 내는지

---

## 3. 미검증 (실환경에서만 확인 가능)

- SDK 경로가 실제로 뜨는지 — **이 판본을 만든 이유가 그것이다.**
- 게이트웨이가 `stream=True` 를 받는지. 안 받으면 서빙이 비스트리밍으로 되돌아간다.
- 중간 프록시가 SSE 를 모아 보내지 않는지 (모으면 "한방에" 로만 보이고 오류가 없다 —
  그래서 `X-Accel-Buffering: no` 를 실어 둔다).
- **12,000자 프롬프트의 prefill 시간.** 이게 5초를 넘으면 필드 순서를 바꿔도 10초를
  못 지킨다 — 그때는 `FAQ_MAX_CONTEXT_CHARS` 를 더 줄인다(병렬이라 조각 수가 늘어도
  대기시간은 안 는다).
- `model` 값을 게이트웨이가 어떻게 다루는지.
