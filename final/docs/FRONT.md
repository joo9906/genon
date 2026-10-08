# FRONT.md — 프론트가 주고받는 값

**대상: 네 기능 전부** — 템플릿 채우기(SFR-006) · 글다듬이 · 번역 · FAQ.

**부르는 길이 기능마다 다르다.**

| 기능 | 실행 경로 | 코드 |
|---|---|---|
| 글다듬이 · 번역 · FAQ | **젠포탈이 코드서빙 `POST /chat` 을 직접 부른다.** 코드서빙이 SSE 를 직접 낸다 | `no_pythonstep/<기능>/` |
| 템플릿 채우기 (006) | 캔버스 워크플로우(파이썬 스텝 3개) → 코드서빙 | `final/SFR-006/request/` + `final/workflow/sfr006_*` |

006 도 `/chat` 직접 호출이 구현돼 있지만(`no_pythonstep/SFR-006/`) 세션 id 가 실제로 오는지
확인 전이라 운영 경로는 워크플로우다(§4·§6).

이 문서의 키·값은 전부 **운영 코드에서 확인한 것**이고 근거 파일을 각 절에 적었다.
미확정인 것은 §6 에 모아 두었다.

---

## 요약 — 프론트가 받는 것은 이게 전부다

**렌더링되지 않는 값은 싣지 않는다.** 내부 판정·검증·진단은 우리가 로그로 갖는다 —
화면에 실어 보내면 쓰지 않는 값이 **아무도 안 읽는 채로 계약에 남아** 나중에 바꿀 때
발이 묶인다. 아래가 결과 값의 전부이고, 여기 없는 키는 오지 않는다.

| 기능 | 결과 값 (018 = `complete` 프레임 `data` / 006 = `result.data`) |
|---|---|
| **글다듬이** | `original_text` · `polished_text` · `download_url` · `doc_type` · `tone` · `tone_overridden` |
| **번역** | `original_text`(+`<mark>`) · `translated_text`(+`<mark>`) · `download_url` |
| **FAQ** | `faq_items[]` = `{question, answer, evidence}` · `download_url` |
| **템플릿 채우기** | `text`(채팅 답변 + **아래에 미리보기**) · `download_url` · `session_id` · `template_id` |

```json
// 번역 — 좌우 비교 두 값 + 링크
{ "original_text":   "…<mark>가맹점</mark>…",
  "translated_text": "…<mark>merchant</mark>…",
  "download_url":    "https://…/번역결과.md" }

// 글다듬이 — 원문·결과 + 링크 + 적용된 정책
{ "original_text": "…개발함…", "polished_text": "…개발하였습니다…",
  "download_url": "https://…/글다듬이결과.md",
  "doc_type": "email", "tone": "polite", "tone_overridden": false }

// FAQ — 문답 묶음 + 링크
{ "faq_items": [{ "question": "…", "answer": "…", "evidence": "…" }],
  "download_url": "https://…/FAQ.md" }

// 템플릿 채우기 — 채팅이 곧 화면이다
{ "text": "제목을 『…』(으)로 채웠습니다.\n\n---\n\n**미리보기**\n\n# …",
  "download_url": null, "session_id": "…", "template_id": "보도자료" }
```

**함께 올 수 있는 것** (그리고 이게 전부다):

| 키 | 언제 | 왜 |
|---|---|---|
| `notice` | 있을 때만 (글다듬이·번역·FAQ) | 문자열 배열. 018 은 같은 문구가 **이미 token 으로 채팅에 나갔다** (§1.0) |
| `disclaimer` | FAQ 개수 미달일 때만 | `"N개를 생성하지 못하였습니다."` (§3.5.2) |
| `error` | **오류일 때만** | §1.3. 정상 응답에 `error: null` 은 오지 않는다 |
| `genos_state` | 006, 플랫폼이 넣을 때 | GenOS 추적(`trace_id`). **화면은 안 읽는다** |

- **`download_url` 은 `null` 일 수 있다.** 파일을 못 올린 것은 기능이 실패한 것과 다른
  사건이라 결과는 그대로 내고 링크만 비운다. 006 은 **항목을 다 채우기 전에도** `null` 이다(§4.4).
- **번역은 `<mark>` 가 본문에 섞여 온다** (§1.4).

---

## 0. 통신은 세 갈래다

| 갈래 | 무엇 | 언제 |
|---|---|---|
| **`POST /chat`** (HTTP · SSE) | 018 세 기능의 실행 — 다듬기·번역·FAQ 생성 | 사용자가 보낼 때 |
| **캔버스 워크플로우** (소켓) | 006 의 실행 — 대화로 양식 채우기 | 사용자가 보낼 때 |
| **코드서빙 REST** (HTTP) | 선택지 목록·템플릿 목록·미리보기·다운로드 폴백 | 화면을 그릴 때 · 다운로드할 때 |

**드롭다운 선택지를 화면이 들고 있으면 안 된다.** 언어·톤·문서유형은 백엔드가 표를
갖고 있고 관리자가 늘릴 수도 있다(글다듬이 톤). 화면이 자기 목록을 들면 한쪽만 고쳐도
**예외가 나지 않고 "지원하지 않는 값" 이나 빈 드롭다운으로만** 드러난다.

---

## 1. 공통 규약

### 1.0 `POST /chat` — 018 세 기능 (글다듬이 · 번역 · FAQ)

**요청은 `{question, stream}` 하나다.** 화면에서 고른 값은 `question` 문자열 **맨 앞**에
`키: 값` 줄로 붙인다(머리말). 첨부 문서는 `[입력된 문서]` 표식 뒤에 온다.

```json
{ "question": "target_lang: en\nregister: written\ntitle: 보도자료\n\n번역할 본문…", "stream": true }
```

- **머리말 줄**: 맨 앞의 `키: 값`(또는 `키=값`) 줄들이 옵션이다. **모르는 키가 나오면 그 줄부터
  본문**이다 — 본문 첫 줄이 `날짜: …` 여도 먹히지 않는다. 머리말 뒤 빈 줄이나 `---` 하나는 버린다.
- **JSON 문자열도 받는다**: `"question": "{\"target_lang\": \"en\", \"text\": \"본문\"}"`.
  본문 키는 `text` → `markdown` → `body` → `question` 순서로 찾는다.
- **최상위 키도 받는다**(`{"question": "…", "target_lang": "en"}`). 우선순위는
  **최상위 키 > `question` 머리말 > 배포 기본값 환경변수**다.
- **`[입력된 문서]` 표식이 있으면 그 뒤가 원문**이고 앞쪽에서는 머리말만 읽는다. 표식 뒤에
  `<doc …>…</doc>` 가 있으면 태그 안만 원문이다(여럿이면 빈 줄로 잇는다).
- **자연어는 해석하지 않는다.** 본문에 "영어로 번역해줘" 가 있어도 언어를 바꾸지 않는다 —
  선택값이 유일한 근거다. 화면이 고른 값을 머리말로 붙여야 한다.
- `stream` 은 `true`·`"true"`·`1` 을 모두 받는다. 기능별 옵션 키는 §2.2·§3.2·§3.5.1.

**`stream: true` → SSE.** 프레임은 전부 `data: {"event", "data"}` 한 줄이다.

```
data: {"event": "heartbeat", "data": {"elapsed_seconds": 0}}   ← 시작 1회 + 조용한 동안 5초마다
data: {"event": "token",     "data": "결과 조각"}                ← 채팅에 보인다
data: {"event": "token",     "data": "\n\n---\n\n> ⚠ 안내…\n\n[… 내려받기 (.md)](url)"}
data: {"event": "complete",  "data": { …결과 값… }}              ← 값만. `text` 가 없다
data: {"event": "end",       "data": ""}
```

- **채팅에 보일 글은 전부 `token` 으로 나간다** — 결과 글, 그 아래 안내문(`notice` 와 같은
  문구)과 내려받기 링크, 오류 문구까지. `complete` 에는 `text` 를 싣지 않으므로 채팅이 결과를
  한 번 더 그리지 않는다. `complete.data` 는 좌우 비교 같은 **별도 화면이 읽는 값**이다.
- **오류도 HTTP 200 SSE 다** (입력 오류 포함): `token`(문구) → `complete {"error": {…}}` → `end`.
  스트리밍을 요청한 화면은 SSE 만 읽으므로 400 JSON 을 받으면 아무것도 그리지 못한다.
- `heartbeat` 는 진행 표시용이다(개발가이드에 없는 이벤트 — 글자로 찍히면 서빙에서
  `CHAT_HEARTBEAT_SECONDS=0` 으로 끈다). 이벤트 이름은 서빙 환경변수로 바꿀 수 있다
  (`CHAT_TOKEN_EVENT`·`CHAT_RESULT_EVENT`·`CHAT_END_EVENT`, 마지막을 비우면 `end` 를 안 보낸다).

**`stream: false` → JSON 한 덩어리.** 흘릴 데가 없으므로 `text`(채팅이 그릴 글)에 결과 값을 더해
싣는다. 오류는 상태코드(400/422/500/502/504)와 함께 `{"text": 문구, "error": {…}}` 다.

근거: `no_pythonstep/<기능>/chat_input.py`(입력 해석) · `chat_api.py`(응답),
그물 `Test/check/check_chat_direct.py` · `Test/SFR-018/tests/test_chat_input.py`

### 1.1 소켓 이벤트 — 006 (캔버스 워크플로우)

```
token  →  token  →  token  → … →  result      (정상)
                                   result      (오류 — 오류 문구도 token 으로 흐른다)
```

| 이벤트 | data | 설명 |
|---|---|---|
| `token` | 문자열 조각 | 채팅 답변 + 미리보기가 흐른다 |
| `result` | 아래 payload | **한 번만** 온다. 이 시점에 화면을 완성한다 |

- **`token` 은 연출이다.** 결과가 확정된 뒤 잘라서 보내는 것이라 실제 내용은 `result` 가 정본이다.
- 조각 수에는 상한(400)이 있어 긴 문서에서 조각이 커진다 — 화면은 조각 크기를 가정하지 말 것.

근거: `final/workflow/sfr006_03_commit.py`

### 1.2 결과 값은 **화면이 보는 값만** 담는다

내부 판정·검증·지표(준수율·폴백률·기각 건수)는 **로그가 갖는다.** 결과에 없다고
빠뜨린 것이 아니라 **일부러 뺀 것**이니 화면이 그 값을 기대하고 만들지 말 것.

**있을 때만 실리는 키:**

| 키 | 규약 |
|---|---|
| `error` | **오류일 때만.** 정상 응답에 `error: null` 은 없다 — **네 기능 전부** |
| `notice` | **안내할 것이 있을 때만.** 늘 있는 빈 배열은 읽는 쪽이 "확인했다" 고 믿게 만든다 |

> **006 은 `notice` 가 없다** — 안내가 `text` 문장에 이미 들어 있다.

### 1.2.1 006 캔버스 변수는 최상위에 바로 실어도 된다

§4.3 의 `overrideConfig.vars` 키는 **최상위에 그대로 실어도 읽는다**. 두 방식 모두 받는다.

```json
{ "text": "보도자료 써 줘", "template_id": "보도자료" }
{ "text": "…", "overrideConfig": { "vars": { "template_fill_template_id": "보도자료" } } }
```

- **둘 다 오면 최상위가 이긴다.** 빈 문자열은 안 보낸 것으로 친다.
- 006 은 짧은 이름 `template_id` 도 받는다.
- 발화는 `question` → `text` → `message` → `query` 순으로 찾고, 없으면 중첩 `request_payload`
  에서 같은 순서로 찾는다. **문자열만** 받는다. 근거: 스텝 1 의 `_question`·`_canvas_vars`

### 1.3 오류 객체

```json
{ "error": { "error_code": "ERR-03-00020002", "msg": "번역에 실패했습니다. 잠시 후 다시 시도해 주세요." } }
```

- **`msg` 를 그대로 보여주면 된다.** 고정 한국어 안내문이고 내부 정보(URL·예외 원문)가
  들어가지 않는다. 018 은 같은 문구가 이미 `token` 으로 채팅에 나갔다.
- `error_code` 는 `ERR-영역-코드` 꼴이다(`03` 코드서빙 — 018 `/chat` / `02` 워크플로우 — 006).
  문의 접수 때 이 값이 있어야 로그를 찾을 수 있다.
- **006(워크플로우)은 `retryable` 이 함께 온다.** `false` 면 다시 눌러도 같은 자리에서
  실패한다(배포·설정 문제) — 재시도 대신 "관리자 문의" 로 안내한다. 018 `/chat` 은 이 키가 없다.

### 1.4 하이라이트 — 번역은 `<mark>` 가 본문에 섞여 온다

**원문과 번역문을 좌우로 놓고 비교**하는 화면이 전제다. 양쪽에 `<mark>…</mark>` 가 이미
입혀져 있다 — 왼쪽(`original_text`)은 사전 용어가 **원문에서** 쓰인 자리, 오른쪽
(`translated_text`)은 그 용어가 **번역문에서** 쓰인 자리다.

- **왼쪽만 형광이고 오른쪽 짝이 없으면 "사전 용어인데 번역이 그 말을 안 썼다"** 다.
  그 건수는 `notice` 로도 온다.
- 칠하는 구간은 문서에 **실제로 적힌 글자**다 — 한국어는 조사까지 덮인다
  (`<mark>신용회복위원회를</mark>`).
- 코드펜스 안과 HTML 태그 가운데는 칠하지 않는다(칠하면 표가 깨진다).
- `token` 으로 흐르는 번역문에는 `<mark>` 가 **없다**(정본 마크다운). `<mark>` 는 `complete` 값에만 있다.
- **글다듬이 `/chat` 은 하이라이트가 없다** — `original_text`·`polished_text` 는 원문·결과 그대로다.

> ⚠ **화면이 raw HTML 을 렌더해야 형광이 보인다.** 막혀 있으면 `<mark>` 가 글자 그대로
> 노출된다. **이 허용 여부는 아직 확인되지 않았다**(§6).

### 1.5 내려받기

**네 기능이 모두 `download_url` 이다.**

| 기능 | 무엇이 올라가나 | 채팅에 | 폴백 |
|---|---|---|---|
| 글다듬이 · 번역 · FAQ | 결과 **md** | 결과 아래 `[… 내려받기 (.md)](url)` 링크가 token 으로 나간다 | `POST /download` (화면이 텍스트를 되돌려 보낸다) |
| 템플릿 채우기 | 항목을 **다 채웠을 때** 굳힌 **hwpx** | — | `POST /generate` (`session_id`+`template_id` 만 보내면 파일 바이트가 온다) |

- **`download_url` 이 `null` 일 수 있다.** 업로드 실패는 기능이 실패한 것과 다른 사건이라
  결과는 그대로 나가고 링크만 빈다(018 은 채팅 링크 줄도 빠진다). **006 은 아직 다 안 채웠을 때도 `null` 이다**(§4.4).
- 링크의 **모양**은 GenOS 참조 샘플(MinIO 업로드)과 대조해 맞췄다 — 업로드 URL,
  멀티파트 필드(`hostname`+`file`), 응답 경로(`data.presigned_url`). **실서비스 호출은
  아직 미검증**이라 위 폴백을 남겨 두었다.

---

## 2. 글다듬이

### 2.1 선택지 — `GET {글다듬이 서빙}/policies`

```json
{
  "doc_types": [
    { "code": "email",           "label": "메일",                  "forced_tone": false, "allowed_tones": ["polite", "friendly", "clear", "objective"] },
    { "code": "post",            "label": "게시글",                "forced_tone": false, "allowed_tones": ["polite", "friendly", "clear", "objective"] },
    { "code": "customer_notice", "label": "고객발송문구",          "forced_tone": false, "allowed_tones": ["polite", "friendly", "clear", "objective"] },
    { "code": "debt_reason",     "label": "채무 및 연체발생 사유", "forced_tone": true,  "allowed_tones": ["objective"] },
    { "code": "reviewer_opinion","label": "심사역 의견",           "forced_tone": true,  "allowed_tones": ["objective"] }
  ],
  "tones": [
    { "code": "polite",    "label": "격식·정중" },
    { "code": "friendly",  "label": "친절·안내" },
    { "code": "clear",     "label": "명확·간결" },
    { "code": "objective", "label": "사실·객관" }
  ],
  "default_doc_type": "email",
  "default_tone": "polite",
  "policy": { "source": "builtin", "reason": "not_configured", "rejected": {} }
}
```

- **목록은 고정이 아니다.** 관리자가 GenOS 프롬프트 라이브러리에 톤·문서유형을 추가할
  수 있어 항목이 늘거나 빠지고, **강제 톤도 관리자가 바꿀 수 있다.** 매번 이 응답으로 그린다.
- `policy.source` 는 `builtin` / 관리자 등록 여부를 말한다. 관리자 화면이라면
  `reason`·`rejected`(사유별 불량 건수)를 보여주면 "내가 넣은 톤이 왜 안 뜨나" 를 답할 수 있다.
  일반 사용자 화면에서는 무시해도 된다.

### 2.1.1 톤 드롭다운은 문서유형이 정한다

**규칙은 한 줄이다 — `allowed_tones` 를 그리고, 원소가 하나면 잠근다.**

```js
const tones = docType.allowed_tones;          // 언제나 실제 목록. 비는 일이 없다
if (tones.length === 1) lock(tones[0]);       // 잠금 — 라벨은 tones[] 에서 code 로 찾는다
else showDropdown(tones);
```

- **`allowed_tones` 는 절대 비지 않는다.** 자유 선택군이면 고를 수 있는 톤이 전부 들어
  있고, 강제군이면 그 한 톤만 들어 있다. 우선순위를 따질 필요도, `tones` 전체와 교집합을
  구할 필요도 없다.
- **여기 실리는 톤은 "보내면 그대로 적용되는" 톤이다.** 백엔드가 판정 함수로 목록을
  만들기 때문에 **화면이 잠근 톤과 실제 적용 톤이 어긋날 수 없다.**
- **문서유형 코드를 하드코딩하지 않는다.** 강제 여부·강제 톤은 관리자가 프롬프트
  라이브러리에서 바꿀 수 있다.

**`forced_tone` 은 불리언이고, "왜 하나뿐인가" 만 답한다.** 무엇으로 잠겼는지는
`allowed_tones[0]` 가 이미 말하므로 그 값을 되풀이하지 않는다.

| `forced_tone` | `allowed_tones` | 뜻 | 화면 |
|---|---|---|---|
| `false` | 여러 개 | 자유 선택 | 드롭다운 |
| `false` | 하나 | 관리자가 **허용을 하나만** 등록했다 | 잠금 |
| `true` | 하나 | 이 문서유형은 **톤이 고정**이다 | 잠금 (+「고정」 배지 등) |

두 잠금은 동작이 같고 **문구만 갈릴 수 있다.** 문구를 나누지 않을 거라면 이 필드는
안 읽어도 된다.

현재 내장 표 (**참고용 — 하드코딩하지 말 것**). 잠기는 톤이 문서유형마다 다르다:

| 문서유형 | `forced_tone` | `allowed_tones` |
|---|---|---|
| 메일 · 게시글 · **고객발송문구** | `false` | `["polite","friendly","clear","objective"]` |
| 채무 및 연체발생 사유 | `true` | `["objective"]` (사실·객관) |
| 심사역 의견 | `true` | `["objective"]` (사실·객관) |

> **2026-09-03 요구 변경 — 톤 4종·문서유형 5종.** 톤은 격식·정중 / 친절·안내 /
> 명확·간결 / 사실·객관이고, 옛 `report`(간결 및 보고체, 개조식 `~함/~임`)는 없어졌다.
> 문서유형에서는 보도자료·공문·재산 의견이 빠졌고 **고객발송문구가 고정군 → 자유
> 선택군**이 됐다. 화면이 옛 `report` 를 보내면 백엔드가 `clear` 로 옮겨 받지만
> (조용한 기본값 대체를 막는 별칭), **드롭다운은 이 응답으로 다시 그릴 것.**

**백엔드도 같은 판정을 다시 한다.** 화면이 잠그지 않고 다른 톤을 보내도 결과는 강제 톤으로
나간다 — 프롬프트 지시를 보장으로 보지 않는 것과 같은 규약이다. 다만 그러면 **사용자가
고른 톤이 조용히 바뀌므로**, 잠그는 것은 그 상태를 사용자에게 안 보이게 하는 일이다.

`default_doc_type`·`default_tone` 은 아무것도 안 골랐을 때 백엔드가 쓰는 값이다 —
화면의 초기 선택을 이 값으로 맞추면 "안 고르고 실행" 과 결과가 같아진다.

근거: `no_pythonstep/SFR-018-polish/main.py` `GET /policies`,
`text_polish/tone_presets.py` `doc_type_choices`/`tone_choices`/`policy_source`

### 2.2 보내는 값 — `question` 머리말 (§1.0)

```json
{ "question": "doc_type: email\ntone: polite\ntitle: 안내\n\n다듬을 글…", "stream": true }
```

| 옵션 | 받는 키 | 값 |
|---|---|---|
| 문서유형 | `doc_type` `polish_doc_type` `문서유형` `문서종류` | `/policies` 의 `doc_types[].code` 또는 라벨. 없으면 `POLISH_DEFAULT_DOC_TYPE` |
| 톤 | `tone` `polish_tone` `톤` `어조` | `tones[].code` 또는 라벨. 없거나 정책상 불가면 대체된다 |
| 파일명 | `title` `polish_title` | 내려받는 md 이름 |

- **`제목:` 은 옵션이 아니다** — 다듬을 글의 첫 줄이 `제목: …` 인 경우가 흔해서 받지 않는다.
- **원문은 `[입력된 문서]` 뒤(첨부)가 우선이다.** 표식이 있으면 그 앞에 사용자가 친 글은
  다듬지 않는다. 둘 다 없으면 입력 오류다.
- 목록 밖 값은 기본값으로 대체되고, 강제 톤 문서유형은 그 톤으로 바뀐다(`tone_overridden: true`
  + 안내문 1줄).

근거: `no_pythonstep/SFR-018-polish/chat_input.py`

### 2.3 받는 값 — `complete.data`

```json
{
  "original_text": "…개발함…",
  "polished_text": "…개발하였습니다…",
  "download_url": "https://…/글다듬이결과.md",
  "doc_type": "debt_reason", "tone": "objective", "tone_overridden": true,
  "notice": ["'채무 및 연체발생 사유' 문서는 정책상 '사실·객관' 톤으로 다듬었습니다."]
}
```

| 키 | 항상? | 설명 |
|---|---|---|
| `original_text` | ✅ | 다듬은 대상 원문 (하이라이트 없음) |
| `polished_text` | ✅ | 다듬은 글. 채팅에는 같은 글이 `token` 으로 이미 흘렀다 |
| `download_url` | ✅ (값은 `null` 일 수 있다) | 미리 굳힌 md |
| `doc_type` · `tone` | ✅ | **실제로 적용된** 코드 |
| `tone_overridden` | ✅ | 고른 톤이 정책으로 바뀌었는가 |
| `notice` | 있을 때만 | 문자열 배열 |
| `error` | 오류일 때만 | §1.3 |

**`notice` 에 오는 문구** (건수만 말한다 — 어느 값인지는 문서 내용이라 싣지 않는다):

- `'문서유형' 문서는 정책상 '톤' 톤으로 다듬었습니다.`
- `문서 일부 구간(N곳)을 다듬지 못해 원문 그대로 두었습니다. 다시 시도해 주세요.`
- `표·제목 등 문서 구조가 원문과 달라진 곳이 N곳 있습니다. 결과를 확인해 주세요.`
- `숫자·날짜가 원문과 다른 곳이 N곳 있습니다. 결과를 확인해 주세요.`
- `다듬는 도중 연결이 끊겨 화면에 잠시 보였던 문장이 최종 결과와 다를 수 있습니다. 아래 결과를 확인해 주세요.`

구조·숫자 점검은 MCP `genon_text_guard` 가 한다 — 서빙에 `TEXT_GUARD_MCP_ID` 가 없으면 점검
없이 결과만 나간다(그 두 문구가 안 나온다).

근거: `no_pythonstep/SFR-018-polish/chat_api.py` `_notices`·`_finish`

---

## 3. 번역

### 3.1 선택지 — `GET {번역 서빙}/languages`

```json
{
  "languages": [
    { "code": "ko", "label": "한국어",   "en_label": "Korean",     "glossary_supported": true },
    { "code": "en", "label": "영어",     "en_label": "English",    "glossary_supported": true },
    { "code": "zh", "label": "중국어",   "en_label": "Chinese",    "glossary_supported": false },
    { "code": "th", "label": "태국어",   "en_label": "Thai",       "glossary_supported": false },
    { "code": "vi", "label": "베트남어", "en_label": "Vietnamese", "glossary_supported": false },
    { "code": "ru", "label": "러시아어", "en_label": "Russian",    "glossary_supported": false }
  ],
  "registers": [
    { "code": "written", "label": "문어체" },
    { "code": "spoken",  "label": "구어체" }
  ],
  "korean_axis_required": true,
  "glossary_languages": ["ko", "en"]
}
```

**화면이 이 응답만 보고 그려야 하는 이유가 둘 있다.**

- **`korean_axis_required: true` — 원문·대상 중 하나는 반드시 한국어다.** 6×6=36 조합을
  보여준 뒤 400 을 받게 두지 말 것. `en → ru` 같은 조합은 **고를 수 없게** 막는다.
- **용어사전은 한국어·영어에만 있다.** 나머지 넷은 LLM 만으로 번역된다. `glossary_supported`
  로 배지를 그리면 "왜 이 언어만 용어가 안 지켜지나" 가 되지 않는다.

근거: `no_pythonstep/SFR-018-translate/main.py` `GET /languages`,
`translation_pipeline/office/languages.py:64-69,93`, `registers.py:75`

### 3.2 보내는 값 — `question` 머리말 (§1.0)

```json
{ "question": "target_lang: en\nregister: written\ntitle: 보도자료\n\n번역할 본문…", "stream": true }
```

| 옵션 | 받는 키 | 필수 | 값 |
|---|---|---|---|
| 대상 언어 | `target_lang` `target` `to` `translate_target_lang` `대상언어` | **✅** | `languages[].code`(한국어 이름도 받는다). 없으면 `TRANSLATE_DEFAULT_TARGET_LANG`, 그것도 없으면 오류 |
| 원문 언어 | `source_lang` `source` `from` `translate_source_lang` `원문언어` | 선택 | **비워도 된다**(아래) |
| 문체 | `register` `translate_register` `문체` | 선택 | `registers[].code` 또는 `문어체`·`구어체` |
| 파일명 | `title` `translate_title` | 선택 | 내려받는 md 이름 |

- **대상 언어는 화면이 머리말로 붙여야 한다.** 본문의 "영어로" 는 읽지 않는다(§1.0).
- **원문 언어는 비워도 된다 — 백엔드가 감지한다.** 값을 보내면 그것을 정본으로 삼고, 감지
  결과와 대조해 "한국어가 아닌 쌍"(예: 선언은 `ko→ru` 인데 실제로는 영어 문서 → `en→ru`)이면
  **거부**한다. 원문 드롭다운을 두면 사용자가 잘못 고를 수 있으니 **비워 두는 편이 안전하다.**
- 원문은 `[입력된 문서]` 뒤(첨부)가 우선이다.

근거: `no_pythonstep/SFR-018-translate/chat_input.py`

### 3.3 받는 값 — `complete.data`

```json
{
  "original_text": "…<mark>가맹점</mark>…",
  "translated_text": "…<mark>merchant</mark>…",
  "download_url": "https://…/번역결과.md",
  "notice": ["용어사전 용어 3개가 번역문에 반영되지 않았습니다. 다시 번역하면 반영될 수 있습니다."]
}
```

| 키 | 항상? | 설명 |
|---|---|---|
| `original_text` | ✅ | 원문 + `<mark>`(사전 용어가 원문에서 쓰인 자리) |
| `translated_text` | ✅ | 번역문 + `<mark>`. 채팅에는 `<mark>` 없는 번역문이 `token` 으로 이미 흘렀다 |
| `download_url` | ✅ (값은 `null` 일 수 있다) | 미리 굳힌 md (`<mark>` 없는 정본) |
| `notice` | 있을 때만 | 문자열 배열 |
| `error` | 오류일 때만 | §1.3 |

**`notice` 에 오는 문구:**

- `용어사전 용어 N개가 번역문에 반영되지 않았습니다. 다시 번역하면 반영될 수 있습니다.`
- `N개 부분을 번역하지 못해 원문 그대로 두었습니다. 다시 번역해 주세요.`
- `원문과 번역문의 숫자·날짜가 N곳 다릅니다. 결과를 확인해 주세요.`
- `표·목록 등 문서 구조가 원문과 다를 수 있습니다. 결과를 확인해 주세요.` (스트리밍만 — 아래)

> **자동 재번역은 하지 않는다** (요구 확정). 사실만 알리고 **다시 번역할지는 사용자가
> 정한다** — 화면에 "다시 번역" 버튼을 두는 것이 이 안내문의 전제다.

- **스트리밍(`stream: true`)은 조각 단위로 LLM 을 흘린다.** 표 등 구조 보존이 프롬프트에
  달려 있어서, 끝난 뒤 원문과 구조를 대조해 어긋나면 위 마지막 문구를 붙인다.
  비스트리밍은 스켈레톤 분해로 구조를 코드가 보장한다.

근거: `no_pythonstep/SFR-018-translate/chat_api.py` `_notices`·`_translate_streaming`

---

## 3.5 FAQ

### 3.5.1 보내는 값 — `question` 머리말 (§1.0)

```json
{ "question": "faq_count: 5\ntitle: 휴가 FAQ\n\n[입력된 문서]\n<doc>…</doc>", "stream": true }
```

| 옵션 | 받는 키 | 값 |
|---|---|---|
| 개수 | `faq_count` `count` `개수` | 만들 **총 개수**. 없으면 `FAQ_DEFAULT_COUNT`, 배포 상한(`GET /config` 의 `max_count`)으로 깎인다. 0 이면 오류 |
| 상한 낮추기 | `faq_max_count` `max_count` | 배포 상한 안에서만 |
| 파일명 | `faq_title` `title` `제목` | 내려받는 md 이름 |

- **원문**: 최상위 `genosUploaded` > `[입력된 문서]` 뒤 > 표식이 없을 때의 본문.
- **세션**: 최상위 `socketIOClientId` → `sessionId` → `session_id`. 오면 결과를 Redis 에 남겨
  `POST /download` 폴백이 쓴다. 없으면 저장만 건너뛴다(`download_url` 은 정상).

근거: `no_pythonstep/SFR-018-faq/faq/chat_input.py`

### 3.5.2 받는 값 — `complete.data`

```json
{
  "faq_items": [
    { "question": "위약금은 어떻게 계산하나요?",
      "answer":   "잔여 기간에 비례해 산정합니다.",
      "evidence": "위약금은 잔여 계약기간에 비례하여 산정한다." }
  ],
  "download_url": "https://…/FAQ.md",
  "notice": ["요청하신 5개 중 1개만 문서에서 근거를 확인했습니다."],
  "disclaimer": "4개를 생성하지 못하였습니다."
}
```

| 키 | 항상? | 설명 |
|---|---|---|
| `faq_items` | ✅ | 배열. **세 값만 온다** — `evidence` 는 원문에 실제로 있는 문장이다 |
| `download_url` | ✅ (값은 `null` 일 수 있다) | 미리 굳힌 md |
| `notice` | 있을 때만 | 문자열 배열 |
| `disclaimer` | 개수 미달일 때만 | 부족분 한 줄 — 화면이 이 필드 하나로 부족분을 읽는다 |
| `error` | 오류일 때만 | §1.3. 근거를 하나도 확인하지 못하면 오류다 |

- **문답은 항목 단위로 `token` 에 흐른다.** 근거·중복 검증을 통과한 항목만 흐르므로 화면에
  나타났다 사라지는 항목은 없다.
- **기각 건수는 오지 않는다.** "왜 5개 요청했는데 3개만 나왔나" 는 서버 로그(`event=faq_done`)가 답한다.

**`notice` 에 오는 문구:**

- `문서 일부 구간에서 FAQ 를 만들지 못했습니다. 다시 시도하면 더 나올 수 있습니다.`
- `문서가 길어 전체 N개 구간 중 M개 구간에서 나눠 만들었습니다. 나머지 구간 내용은 반영되지 않았습니다.`
- `문서가 매우 길어 뒷부분은 FAQ 생성에서 제외했습니다.`
- `요청하신 N개 중 M개만 문서에서 근거를 확인했습니다.`

근거: `no_pythonstep/SFR-018-faq/faq/chat_api.py` `_notices`·`_disclaimer`·`_result_payload`

---

## 4. 템플릿 채우기 (SFR-006)

**앞의 셋과 방향이 반대다 — 전용 UI 가 없고 채팅이 곧 화면이다.** 그래서 `text`(답변
문장)가 필수이고, 채운 항목·기각 항목·남은 항목이 **전부 그 문장 안에** 들어 있다.

### 4.1 템플릿 목록 — `GET {006 서빙}/templates`

```json
{
  "templates": ["보도자료", "회의록"],
  "items": [
    { "template_id": "보도자료", "indexed": true, "field_count": 5,
      "table_count": 2, "indexed_at": "2026-09-01T10:00:00Z" }
  ],
  "formats": ["hwpx"]
}
```

`indexed: false` 는 아직 파싱하지 않았다는 뜻이고 문제가 아니다 — 그 템플릿의 `/fields`
첫 호출이 색인을 만든다.

### 4.2 항목 목록 — `GET /fields?template_id=보도자료`

```json
{
  "template_id": "보도자료",
  "fields": [
    { "name": "제목", "guide": "HY헤드라인M, 16pt", "occurrences": 1,
      "filled": false, "current_value": "", "source": "label" }
  ],
  "block_styles": ["본문"],
  "from_cache": true
}
```

`guide` 는 템플릿에 적힌 **값 안내**(글꼴·형식)다. 입력 힌트로 쓸 수 있다.

**반복 묶음 템플릿이면 `repeat_group` 이 온다** (없으면 `null`, 2026-10-07 추가 — 기존 키는
그대로다). `fields` 에는 템플릿에 적힌 **1번만** 있고, 대화가 진행되면 `본문 2`·`내용 2-1`
같은 이름이 `/preview`·`/status` 의 `fields`·`values` 에 **평범한 항목으로** 늘어난다.

```json
"repeat_group": { "members": ["본문 1", "요약 1"], "items": ["내용 1-1"],
                  "items_repeatable": true, "max_groups": 10, "max_items": 10 }
```

화면이 묶음별로 나눠 그리고 싶으면 이름 끝 번호(`k`, `k-j`)로 묶으면 된다.

### 4.3 보내는 값 (캔버스 변수)

| 자리 | 키 | 필수 | 값 |
|---|---|---|---|
| `overrideConfig.vars` | `template_fill_template_id` | **✅ 필수** | `/templates` 의 `template_id` |
| 최상위 | `question` (또는 `text`·`message`·`query`) | ✅ | 사용자 발화. **2만 자에서 잘린다** |
| `overrideConfig.vars` | `genosUploaded` | 선택 | **업로드 문서로 빈 항목을 자동으로 채운다** |

- **문서를 `question` 에 넣지 말 것.** 발화는 2만 자에서 잘리고, 발화 자리에 들어간
  문서는 "지워 달라"·"본문에 추가해 달라" 같은 **지시로 해석될 수 있다.**
- **대화 도중 아무 턴에나 올려도 되고, 여러 번 올려도 된다** (2026-09-02).
  **사용자가 이미 넣은 값은 절대 덮지 않고 남은 빈 항목만** 채운다. 같은 턴에 발화로
  준 값이 문서보다 우선한다.
- **같은 문서를 매 턴 계속 실어 보내도 된다.** 서빙이 문서 표식으로 걸러 **두 번
  태우지 않는다** — 프론트가 "이 턴에 새 파일이 올라왔는지" 를 판단해 변수를 비울
  필요가 없다.
- 항목이 이미 다 차 있으면 자동 채움을 건너뛰고 **그 사실을 답변(`text`)이 한 줄로
  말한다.** 값을 바꾸려면 대화로 말하면 된다.

근거: `final/workflow/sfr006_01_context.py:288-291,357`

### 4.4 받는 값 — `result.data`

```json
{
  "text": "제목을 『…』(으)로 채웠습니다. 남은 항목은 담당자, 배포일입니다.

---

**미리보기**

# …",
  "download_url": null,
  "session_id": "…",
  "template_id": "보도자료"
}
```

| 키 | 항상? | 설명 |
|---|---|---|
| `text` | ✅ | **채팅 말풍선에 그대로 그린다.** 채운 값·`이전 → 새 값`·기각 항목 이름·남은 항목이 전부 문장으로 들어 있고, **그 아래에 `---` 로 구분된 미리보기**가 붙는다 |
| `download_url` | ✅ (값은 `null` 일 수 있다) | 다 채웠을 때만 링크가 온다. **`null` 이면 아직 받을 수 없다** — 버튼을 끄거나 §4.5 폴백으로 받는다 |
| `session_id` · `template_id` | ✅ | 화면에 안 보이지만 **§4.5 폴백이 쓴다** |
| `error` | 오류일 때만 | §1.3 |

**2026-09-08 에 셋이 달라졌다** (프론트 계약 통일):

- **미리보기가 `text` 안으로 들어왔다.** 그전에는 `document_markdown` 이라는 별도 필드
  였는데 **그릴 창이 없었다** — 006 은 전용 UI 가 없고 채팅이 곧 화면이다. 이제 답변
  아래에 붙어 흘러가는 토큰에도 함께 실리므로, 매 턴 "파일이 지금 어떻게 채워졌는지"
  가 그 자리에서 보인다.
- **`ready_for_download` 플래그가 없어졌다.** `download_url` 이 있으면 받을 수 있고
  없으면 못 받는다 — 두 값을 두면 어긋날 자리가 생기고, 그때 화면은 버튼을 켜 놓고
  받을 수 없는 상태가 된다.
- **`error: null` 을 싣지 않는다.** 나머지 셋과 같은 규약이 됐다(오류일 때만 실린다).

근거: `final/workflow/sfr006_03_commit.py`

### 4.5 내려받기 — 링크가 먼저, `POST /generate` 는 폴백

**정상 경로는 `download_url` 이다** (2026-09-08). 대화가 끝나 항목을 다 채우면 서빙이
그 자리에서 문서를 굳혀 올리고 링크를 함께 내려준다 — 네 기능이 모두 같은 모양이다.

**링크가 `null` 이면** 옛 경로로 받는다. 업로드 실패는 대화 실패와 다른 사건이라
링크만 비운다.

> 링크의 **모양**은 GenOS 참조 샘플(MinIO 업로드)과 대조해 맞췄다 — 업로드 URL,
> 멀티파트 필드(`hostname`+`file`), 응답 경로(`data.presigned_url`)가 같다.
> **실서비스 호출은 아직 미검증**이다.

```json
POST {006 서빙}/generate
{ "template_id": "보도자료", "session_id": "…", "filename": "보도자료_최종" }
```

응답은 **hwpx 파일 바이트**다. `format` 은 생략한다(hwpx 만 지원하며 다른 값은 400).

### 4.6 (선택) 화면에서 값을 직접 고치는 경로

폼 형태로 항목을 편집하는 화면을 만든다면 대화 없이 값만 고칠 수 있다.

| 경로 | 본문 |
|---|---|
| `PATCH /values` | `{ "session_id", "template_id?", "values": {"제목": "…"}, "preview": true }` |
| `DELETE /values` | `{ "session_id", "template_id?", "fields": ["제목"], "preview": true }` |
| `PUT /blocks` | `{ "session_id", "template_id?", "blocks": [{"text": "…", "style_ref": "본문"}] }` |
| `GET /preview?session_id=…` | 없음 |

**`PUT /blocks` 는 배열을 통째로 교체한다** (부분 갱신이 아니다). 인덱스가 어긋나 엉뚱한
문단을 지우지 않게 하려는 것이라, 화면은 현재 목록을 손질해 **전부** 다시 보낸다.
`blocks` 는 항목(`values`)과 달리 **순서가 의미를 갖는** 목록이다.

넷 다 **같은 payload** 를 돌려준다:

```json
{ "template_id": "…", "session_id": "…", "markdown": "…", "truncated": false,
  "fields": [ … ], "values": { … }, "fields_missing": ["담당자"],
  "ready_for_download": false, "formats": ["hwpx"],
  "blocks": [ { "text": "…", "style_ref": "본문" } ],
  "block_styles": ["본문"] }
```

`truncated: true` 는 **미리보기가 잘렸다**는 뜻이다 — 문서 전체로 오인하면 빠진 항목을
못 보고 다운로드하게 되므로 표시할 것.

근거: `final/SFR-006/request/template_fill/session_view.py:157,179`,
`api_requests.py:36-61`

---

## 5. 오류 코드

`msg` 를 그대로 보여주면 된다. 018 `/chat` 은 오류 문구가 이미 `token` 으로 채팅에 나가므로
화면이 따로 할 일이 없다.

| 상황 | 018 `/chat` (JSON 상태코드) | 006 `retryable` | 사용자가 할 일 |
|---|---|---|---|
| 응답 지연·통신 실패 | 504 | `true` | 잠시 후 다시 |
| 실행 실패 (LLM 전량 실패 등) | 502 | `true` | 잠시 후 다시 |
| **설정 부재** (배포 실수) | 500 | `false` | 관리자 문의 — **다시 눌러도 같은 자리에서 실패한다** |
| 입력 오류 | 400 · 422 | — | 문구대로 고쳐서 다시 |

`stream: true` 면 상태코드와 무관하게 HTTP 200 SSE 다(§1.0).

기능별 입력 오류:

| 기능 | 상황 | 안내 |
|---|---|---|
| 글다듬이 | 원문 없음 / 입력 초과 | 문서나 텍스트를 넣어 달라 / 길이를 줄여 달라 |
| 번역 | 대상 언어 없음 | 대상 언어를 골라 달라 (머리말 `target_lang` 이 빠졌다) |
| 번역 | **한국어 축 위반** | 원문·대상 중 하나는 한국어여야 한다 (§3.1 로 미리 막을 것) |
| FAQ | 문서 없음 / 개수 0 / 근거 미확보(422) | 문서를 첨부해 달라 / 1개 이상 / 다른 문서로 |
| 018 셋 | **스캔 표식**(`[[GENON_SCAN`) | 스캔 쪽이 든 문서는 아직 이 경로에서 처리할 수 없다 (§6) |
| 006 | 템플릿 없음 | 템플릿을 고르거나 등록해 달라 |

---

## 6. 확인·결정이 필요한 것

프론트 작업 전에 답이 필요한 것들이다. 백엔드에서 정할 수 있는 것은 알려주면 바꾼다.

1. **화면이 고른 값을 `question` 머리말로 붙여 줄 수 있는가** (§1.0). 젠포탈 직접 호출은 값이
   전부 `question` 안에 온다. 머리말이 안 붙으면 018 은 배포 기본값 환경변수
   (`TRANSLATE_DEFAULT_*`·`POLISH_DEFAULT_*`·`FAQ_DEFAULT_COUNT`)만 쓰게 되고, 번역은 기본 대상
   언어가 없으면 매번 "언어를 선택해 주세요" 로 선다.
2. **첨부가 실린 `question` 실물 한 건** — `[입력된 문서]` 뒤에 `<doc>` 태그가 붙는지, 문서가
   여럿일 때 어떻게 이어지는지, 사용자 글이 표식 앞에 오는지 뒤에 오는지. 지금 코드는 모두 받는다.
3. **실제 화면에서** `heartbeat` 가 진행 표시로 돌고 `{"elapsed_seconds": …}` 가 글자로 찍히지
   않는지, `complete` 를 채팅이 다시 그리지 않는지. 찍히면 서빙 환경변수로 끈다(§1.0).
4. **`<mark>` raw HTML 렌더가 가능한가** (§1.4, 번역). 막혀 있으면 형광 대신 태그 글자가
   보인다 — 대안 표기로 바꿔야 한다. 백엔드 상수 두 곳만 고치면 된다.
5. **스캔한 쪽이 든 문서** — 018 `/chat` 은 전처리기의 스캔 표식을 받으면 입력 오류로 선다
   (OCR 을 부르는 워크플로우 스텝이 이 경로에 없다). 첨부 전처리기가 OCR 을 미루지 않고
   직접 읽게 등록하거나(`ocr_defer` 끔), 서빙에 MCP `genon_ocr` 호출을 붙여야 한다.
6. **`download_url` 이 폐쇄망에서 실제로 열리는지 미검증이다** (§1.5). 모양은 GenOS 참조
   샘플과 같다. 안 되면 폴백으로 배선한다: 018 셋은 `POST /download`, 006 은 `POST /generate`.
7. **006 의 `download_url` 은 항목을 다 채운 뒤에만 온다** (§4.4). 그 전에는 `null` 이라
   **"아직 다 안 채웠다" 와 "업로드가 실패했다" 를 화면이 구분할 수 없다.** 구분이 필요하면
   알려 달라(사유를 문장에 얹을 수 있다).
8. **006 을 `/chat` 직접 호출로 옮길 것인가** — 구현은 돼 있다(`no_pythonstep/SFR-006/`).
   젠포탈 직접 호출 payload 에 **대화마다 같은 세션 id** 가 실려 오는지 확인돼야 한다. 안 오면
   매 턴이 새 대화가 된다.
