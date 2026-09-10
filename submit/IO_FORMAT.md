# 입출력 포맷 — 단계마다 JSON 이 어떻게 들어오고 나가나

> `README.md` 가 **무엇을 어디에 등록하나**를 말하고, 이 문서는 **그 사이로 어떤 JSON 이
> 흐르나**를 말한다. 화면(프론트)이 보는 값만 따로 정리한 것은
> `onprem/docs/FRONT.md` 이고, 여기는 **경계 전부**(캔버스 → 스텝 → 서빙 → 스텝 → 캔버스)를 담는다.

## 0. 경계가 네 개다

```
 ① 캔버스 변수            ② 스텝 사이 data           ③ 서빙 HTTP           ④ 소켓 이벤트
사용자 선택 ──────► 스텝1 ──────────► 스텝2 ─────► 코드서빙 ─────► 스텝N ──────► 화면
            overrideConfig      dict 반환        JSON 요청/응답      token / result
```

| 경계 | 모양 | 규약 |
|---|---|---|
| ① 캔버스 → 스텝 | `data["overrideConfig"]["vars"]` | 값은 **전부 문자열**로 온다. 숫자·불리언도 문자열이다 |
| ② 스텝 → 스텝 | 스텝의 `run` 이 돌려준 `dict` 가 다음 스텝의 `data` 다 | 마지막 스텝만 payload 를 새로 만든다 (아래 §1-3) |
| ③ 스텝 → 서빙 | `POST` JSON | 응답 오류는 **객체 반환**이지 예외가 아니다 |
| ④ 스텝 → 화면 | `token`(조각) · `result`(최종) | `result` 는 **정확히 한 번**, 마지막에 |

---

## 1. 공통 규약

### 1-1. 스텝의 계약

```python
async def run(data: dict) -> dict          # 스텝 1 (그리고 중간 스텝)
async def run(data: dict)                  # 마지막 스텝 — async generator
```

- 함수 이름 `run` 은 **GenOS 고정 계약**이다.
- 마지막 스텝은 `yield` 로 이벤트를 낸다. 나머지는 `dict` 를 `return` 한다.
- **첫 스텝이 받는 `data` 가 문자열일 수 있다** — 캔버스 배선에 따라 발화만 오는 경우가
  있어 스텝이 `{"question": data}` 로 감싼다.

### 1-2. 들어오는 공통 필드

```json
{
  "question": "제목은 8월 첫째 주 보고로 해줘",
  "genos_state": { "session_id": "sess-1", "trace_id": "trace-1" },
  "socketIOClientId": "…",
  "overrideConfig": { "vars": { "polish_tone": "polite" } },
  "genosUploaded": "전처리기가 변환한 마크다운 본문…"
}
```

| 키 | 뜻 |
|---|---|
| `question` | 이번 턴 사용자 발화. 별칭 `text` 도 받는다 |
| `genos_state.session_id` | Redis 세션 키의 근거 (006·FAQ) |
| `genos_state.trace_id` | 로그 상관관계 |
| `socketIOClientId` | 소켓 emit 대상 |
| `overrideConfig.vars` | 캔버스 드롭다운·입력칸 값 (**전부 문자열**) |
| `genosUploaded` | 전처리기 산출물 (업로드 문서의 마크다운/HTML) |

### 1-3. 나가는 이벤트 — `token` 과 `result` 둘뿐

```jsonc
// 진행 중 — 여러 번
{ "event": "token", "data": "다듬어진 문장 조각" }

// 마지막 — 정확히 한 번
{ "event": "result", "data": { /* 아래 기능별 payload */ } }
```

- **`result` 가 마지막 이벤트다.** 뒤에 아무것도 오지 않는다.
- **payload 는 화면이 보는 값만 담는다.** `{**data}` 로 펼치지 않는다 — 그러면 앞 스텝이
  넣은 내부 값과 캔버스 입력이 전부 프론트로 간다.
- 흘리는 것은 **정본**이다(하이라이트 사본이 아니다). 하이라이트는 `result` 에서 갈아 낀다.
- **오류 경로에서는 `token` 이 한 개도 나가지 않는다.**

### 1-4. 오류 객체 — 모양이 하나다

```json
{
  "event": "result",
  "data": {
    "error": {
      "error_code": "02-00020001",
      "msg": "요청이 지연되었습니다. 잠시 후 다시 시도해 주세요.",
      "retryable": true
    }
  }
}
```

| `error_code` 끝 | 뜻 | `retryable` |
|---|---|---|
| `00020001` | 통신 실패 (타임아웃) | `true` |
| `00020002` | 실행 실패 | `true` |
| `00020003` | **그 밖 전부** — 설정 부재·입력 오류·근거 미확보 | `false` |

- **앞 두 자리는 영역**이다 — `02` 워크플로우, `03` 코드서빙.
- `retryable: false` 는 **재시도로 풀리지 않는다**는 뜻이다(환경변수 누락 등).
  캔버스가 재시도를 걸지 않게 하는 유일한 신호다.
- **정상 응답에는 `error` 키가 없다.** `error: null` 을 넣지 않는다.

---

## 2. 글다듬이 — 스텝 2개

### 2-1. 캔버스가 보내는 값

```json
{
  "question": "이 문서 좀 다듬어줘",
  "genos_state": { "session_id": "s1", "trace_id": "t1" },
  "overrideConfig": { "vars": {
    "polish_doc_type": "email",
    "polish_tone": "polite",
    "polish_title": "8월 보고",
    "polish_source_text": "(선택) 업로드 대신 직접 넣는 원문"
  }},
  "genosUploaded": "업로드 문서의 마크다운"
}
```

| 변수 | 값 |
|---|---|
| `polish_doc_type` | `email` `post` `customer_notice` `debt_reason` `reviewer_opinion` |
| `polish_tone` | `polite` `friendly` `clear` `objective` (옛 `report` 는 `clear` 로 받는다) |
| `polish_title` | 파일 이름에 쓴다 |

> **원문은 `genosUploaded` 를 먼저 보고, 없으면 `question`** 을 쓴다.
> 선택지 목록은 `GET {글다듬이}/policies` 가 준다 — 화면이 목록을 베끼지 않는다.

### 2-2. 스텝 1 → 스텝 2 (경계 ②)

`sfr018_polish_01_policy.py` 가 MCP `resolve_tone` 을 부른 뒤 돌려주는 것:

```json
{
  "genos_state": { "session_id": "s1", "trace_id": "t1" },
  "polish_source_text": "다듬을 원문 전체",
  "polish_doc_type": "email",
  "polish_tone": "polite",
  "polish_tone_overridden": false,
  "polish_tone_notice": "",
  "polish_title": "8월 보고"
}
```

- `polish_tone_overridden` 이 `true` 면 **문서유형이 톤을 강제**한 것이고
  `polish_tone_notice` 에 사용자 안내문이 들어 있다.
- 오류면 `{**data, "error": {...}}` 를 돌려주고 스텝 2 가 그걸 그대로 흘린다.

### 2-3. 스텝 2 → 서빙 (경계 ③)

```
POST {글다듬이}/polish
```
```json
{
  "text": "다듬을 원문 전체",
  "doc_type": "email",
  "tone": "polite",
  "title": "8월 보고"
}
```

응답 (200):

```json
{
  "polished_text": "다듬어진 본문 전체",
  "download_url": "https://…/글다듬이결과_20260903.txt",
  "doc_type": "email",
  "tone": "polite",
  "tone_overridden": false,
  "chunk_count": 3,
  "failed_chunk_count": 0
}
```

- **`failed_chunk_count` 가 0 이 아니면 그 구간은 원문 그대로**다. 전량 실패만 오류다.
- `download_url` 이 `null` 이면 CDN 업로드가 실패한 것이다 — **결과는 그대로 유효하다**
  (fail-open). 옛 `POST /download` 가 폴백이다.

오류 (4xx/5xx):

```json
{ "error_code": "03-00020003", "msg": "…", "retryable": false }
```

### 2-4. 스텝 2 → 화면 (경계 ④)

`token` 으로 `polished_text` 를 조각내 흘린 뒤:

```json
{
  "event": "result",
  "data": {
    "original_text": "<mark>개발함</mark> …",
    "polished_text": "<mark>개발하였습니다</mark> …",
    "download_url": "https://…/글다듬이결과_20260903.txt",
    "notice": ["구조가 일부 바뀌었습니다(표 1곳)."]
  }
}
```

- **`original_text`·`polished_text` 는 하이라이트 사본**이다 — 바뀐 낱말에 `<mark>` 가
  붙어 있다. 정본은 payload 에 없고 **파일에만** 있다.
- `notice` 는 **있을 때만** 실린다 (조각 실패·구조 훼손·숫자 경고).

---

## 3. 번역 — 스텝 2개

### 3-1. 캔버스가 보내는 값

```json
{
  "overrideConfig": { "vars": {
    "translate_target_lang": "en",
    "translate_source_lang": "",
    "translate_register": "written",
    "translate_title": "기술협상서",
    "translate_hwpx_path": "/mnt/shared/upload/abc.hwpx"
  }},
  "genosUploaded": "전처리기 마크다운"
}
```

| 변수 | 값 |
|---|---|
| `translate_target_lang` | `ko` `en` `zh` `th` `vi` `ru` |
| `translate_source_lang` | 비우면 원문에서 **감지**한다 |
| `translate_register` | `written`(문어체) · `spoken`(구어체) |
| `translate_hwpx_path` | 있으면 **원본 hwpx 를 직접** 파싱한다(표가 더 정확하다). 없으면 `genosUploaded` |

> **한국어가 한쪽에 없는 쌍은 거부된다** (`en→ru` 등). 선언한 원문 언어와 실제 문서가
> 어긋나면 그것도 여기서 걸린다 — 선언을 그대로 믿지 않는다.

### 3-2. 스텝 1 → 스텝 2

```json
{
  "genos_state": { "session_id": "s1", "trace_id": "t1" },
  "translate_markdown": "번역할 본문 (hwpx 우선, 없으면 전처리기 산출물)",
  "translate_source_kind": "hwpx",
  "translate_target_lang": "en",
  "translate_source_lang": "ko",
  "translate_register": "written",
  "translate_title": "기술협상서"
}
```

`translate_source_kind` 가 `preprocessed` 면 hwpx 직접 파싱에 실패해 **전처리기 산출물로
폴백**한 것이다 — 표 정확도가 떨어질 수 있고 그 사실이 로그에 남는다.

### 3-3. 스텝 2 → 서빙

```
POST {번역}/translate/markdown
```
```json
{
  "markdown": "번역할 본문",
  "target_lang": "en",
  "source_lang": "ko",
  "register": "written",
  "title": "기술협상서"
}
```

응답 (200):

```json
{
  "markdown": "번역문 (정본)",
  "markdown_highlighted": "번역문 (<mark> 사본)",
  "source_markdown": "원문 (정본)",
  "source_markdown_highlighted": "원문 (<mark> 사본)",
  "download_url": "https://…/기술협상서_en.txt",
  "pairs": [{ "source": "가맹점", "target": "merchant" }],
  "translation_error": "",
  "stats": { "units": 120, "fallback_rate": 0.0 },
  "glossary": { "enabled": true, "compliance": 1.0, "matched_count": 8 },
  "numeric_warnings": [],
  "options": { "target_lang": "en", "source_lang": "ko", "register": "written" }
}
```

| 필드 | 읽는 법 |
|---|---|
| `translation_error` | 빈 문자열이면 정상. `CONFIG_MISSING` 이면 환경변수 누락 |
| `stats.fallback_rate` | 배치 실패로 단건 재시도한 비율 |
| `glossary.compliance` | 용어사전 준수율. `enabled: false` 면 사전이 안 붙은 것이다 |
| `pairs` | **실제로 참고한** 용어 쌍만 |

**다른 두 입력 경로** — 계약이 다르다:

| 경로 | 요청 | 언제 |
|---|---|---|
| `POST /translate` | `{"nodes": [...], "target_lang": "en", ...}` | 노드 목록을 직접 줄 때 |
| `POST /translate/hwpx` | `multipart/form-data` (`file` + 폼 필드) | hwpx 를 직접 업로드할 때 |

### 3-4. 스텝 2 → 화면

```json
{
  "event": "result",
  "data": {
    "original_text": "원문 (<mark> 사본)",
    "translated_text": "번역문 (<mark> 사본)",
    "download_url": "https://…/기술협상서_en.txt",
    "notice": ["용어사전 용어 2건이 번역문에 반영되지 않았습니다."]
  }
}
```

**양쪽 다 하이라이트 사본**이다. 좌우로 놓고 비교할 때 **왼쪽 형광의 짝이 오른쪽에 없으면
그 용어가 미준수**라는 뜻이다.

---

## 4. FAQ — 스텝 2개

### 4-1. 캔버스가 보내는 값

```json
{
  "overrideConfig": { "vars": {
    "faq_count": "10",
    "faq_title": "취업규칙",
    "faq_hwpx_path": "/mnt/shared/upload/rule.hwpx"
  }},
  "genosUploaded": "전처리기 마크다운"
}
```

**`faq_count` 는 총 개수**다 (구간당이 아니다). 고른 숫자가 곧 받는 개수이고, 문서를
나눠 태우는 배분은 서빙이 한다. 상한은 `GET {FAQ}/config` 가 준다.

### 4-2. 스텝 1 → 스텝 2

```json
{
  "genos_state": { "session_id": "s1", "trace_id": "t1" },
  "faq_markdown": "원본 본문",
  "faq_source_kind": "hwpx",
  "faq_count": 10,
  "faq_title": "취업규칙"
}
```

### 4-3. 스텝 2 → 서빙

```
POST {FAQ}/generate
```
```json
{
  "markdown": "원본 본문",
  "count": 10,
  "session_id": "s1",
  "title": "취업규칙"
}
```

응답 (200):

```json
{
  "items": [
    {
      "question": "연차는 며칠인가요?",
      "answer": "입사 1년 미만은 매월 1일씩 …",
      "evidence": "제20조(연차 유급휴가) 사용자는 …",
      "evidence_ratio": 1.0
    }
  ],
  "count": 8,
  "requested_count": 10,
  "max_count": 30,
  "call_cap": 6,
  "count_clamped": false,
  "coverage_capped": false,
  "rejected": { "schema": 0, "ungrounded": 2, "duplicate": 0 },
  "source_truncated": false,
  "source_chunks": 12,
  "chunks_planned": 6,
  "chunks_used": 6,
  "download_url": "https://…/취업규칙_FAQ.txt"
}
```

| 필드 | 읽는 법 |
|---|---|
| `count` < `requested_count` | 기각이 있었다 — `rejected` 가 사유별 건수를 준다 |
| `rejected.ungrounded` | 문서에 근거가 없어 버린 항목 |
| `coverage_capped` | **호출 수 상한에 걸려 못 태운 구간이 있다** (문서 일부만 본 것) |
| `source_truncated` | 조각 수 상한에 걸릴 만큼 문서가 길다 |

오류 분류가 넷이다 — 사용자가 할 일이 다르다:

| HTTP | 뜻 | 사용자가 할 일 |
|---|---|---|
| 504 | 통신 실패 | 잠시 후 다시 |
| **422** | **근거 미확보** | 문서를 바꾸거나 개수를 줄인다 |
| **500** | **프롬프트 부재** (재시도 불가) | 관리자에게 문의 |
| 502 | 그 외 실행 실패 | 잠시 후 다시 |

### 4-4. 스텝 2 → 화면

```json
{
  "event": "result",
  "data": {
    "faq_items": [{ "question": "…", "answer": "…", "evidence": "…" }],
    "download_url": "https://…/취업규칙_FAQ.txt",
    "notice": ["근거가 없어 2건을 제외했습니다."]
  }
}
```

**FAQ 는 `token` 을 흘리지 않는다** — 산출물이 흐르는 글이 아니라 문답 목록이다.

---

## 5. 템플릿 채우기 (006) — 스텝 3개

**여기만 전용 UI 가 없어 대화가 곧 화면**이다. 그래서 payload 에 `text`(답변 문장)가 있다.

### 5-1. 캔버스가 보내는 값

```json
{
  "question": "제목은 8월 첫째 주 보고로 해줘",
  "genos_state": { "session_id": "s1", "trace_id": "t1" },
  "overrideConfig": { "vars": { "template_fill_template_id": "주간보고" } },
  "genosUploaded": "(선택) 업로드 문서 — 빈 항목을 자동으로 채운다"
}
```

### 5-2. 스텝 1 — 세션·템플릿 확정

```
POST {006}/chat/context
```
```json
{ "session_id": "s1", "template_id": "주간보고" }
```

응답:

```json
{
  "template_id": "주간보고",
  "field_names": ["제 목", "주요 내용"],
  "block_styles": ["제 목", "주요 내용"],
  "field_values": { "제 목": "8월 첫째 주 보고" },
  "blocks": [{ "text": "1. 추진 배경", "style_ref": "제 목" }],
  "fields_missing": ["주요 내용"],
  "ready_for_download": false,
  "template_markdown": "템플릿 미리보기",
  "template_markdown_truncated": false,
  "from_cache": true
}
```

**업로드 문서가 있으면 스텝 1 이 이어서** 부른다 (스텝을 늘리지 않는다):

```
POST {006}/chat/prefill
```
```json
{ "session_id": "s1", "template_id": "주간보고", "document": "업로드 문서 본문" }
```

응답:

```json
{
  "applied": true,
  "skipped_reason": "",
  "template_id": "주간보고",
  "fields_prefilled": { "주요 내용": "전사 과제 재정렬" },
  "source_doc_hash": "sha256:…",
  "prefill_failed": false,
  "chunk_count": 3,
  "chunks_called": 1
}
```

| 필드 | 읽는 법 |
|---|---|
| `applied: false` + `skipped_reason` | `already_applied`(이미 태운 문서) · `no_pending_fields`(빈 항목이 없다) · `disabled` |
| `source_doc_hash` | **커밋이 세션에 쌓는다** — 같은 문서를 매 턴 다시 태우지 않게 하는 표식 |
| `chunks_called` < `chunk_count` | 항목이 다 채워져 남은 조각을 부르지 않은 것이다 |

### 5-3. 스텝 2 — 발화에서 값 추출

```
POST {006}/chat/extract
```
```json
{ "session_id": "s1", "template_id": "주간보고", "question": "제목은 8월 첫째 주 보고로 해줘" }
```

응답 — **저장하지 않는다.** 뽑은 것만 돌려준다:

```json
{
  "fields_updated": { "제 목": "8월 첫째 주 보고" },
  "fields_cleared": [],
  "fields_rejected": ["없는항목"],
  "blocks_added": [{ "text": "1. 추진 배경", "style_ref": "제 목" }],
  "block_clears": [2]
}
```

- **`fields_rejected` 는 템플릿에 없는 항목명**이다 — LLM 이 지어낸 것을 코드가 화이트
  리스트로 걸렀다.
- `block_clears` 의 번호는 **추가 이전 목록** 기준이다.
- **같은 값을 다시 말하면 `fields_updated` 에 새 값이 온다** — 세션에서 덮어써진다
  (A → B). hwpx 는 이때 손대지 않고 **다운로드 때 한 번** 채운다.

### 5-4. 스텝 3 — 병합·저장·답변

```
POST {006}/chat/commit
```
```json
{
  "session_id": "s1",
  "template_id": "주간보고",
  "fields_updated": { "제 목": "8월 첫째 주 보고" },
  "fields_prefilled": { "주요 내용": "전사 과제 재정렬" },
  "source_doc_hash": "sha256:…",
  "prefill_failed": false,
  "prefill_skipped_reason": "",
  "fields_cleared": [],
  "fields_rejected": ["없는항목"],
  "blocks_added": [{ "text": "1. 추진 배경", "style_ref": "제 목" }],
  "block_clears": [2]
}
```

> **`fields_prefilled` 를 `fields_updated` 와 따로 받는다.** 병합 순서가 다르다 —
> **문서분을 먼저, 발화분을 나중에** 합친다. 한 dict 로 뭉치면 "이 문서로 채우고 제목은
> A 로" 가 문서의 제목으로 되돌아간다.

응답:

```json
{
  "text": "제목을 '8월 첫째 주 보고' 로 바꿨습니다(이전: 7월 보고). …",
  "field_values": { "제 목": "8월 첫째 주 보고", "주요 내용": "전사 과제 재정렬" },
  "fields_filled": ["제 목", "주요 내용"],
  "fields_missing": [],
  "ready_for_download": true,
  "blocks": [{ "text": "1. 추진 배경", "style_ref": "제 목" }],
  "blocks_removed": 1,
  "document_markdown": "채운 결과 미리보기",
  "document_markdown_truncated": false
}
```

### 5-5. 스텝 3 → 화면

```json
{
  "event": "result",
  "data": {
    "text": "제목을 '8월 첫째 주 보고' 로 바꿨습니다(이전: 7월 보고). 남은 항목: 없음",
    "ready_for_download": true,
    "document_markdown": "채운 결과 미리보기",
    "session_id": "s1",
    "template_id": "주간보고"
  }
}
```

- **`text` 가 화면의 전부**다 — 채운 값·기각 항목·본문 추가 번호·남은 항목을 전부 문장으로
  낸다. 006 은 전용 UI 가 없어 이것이 사용자가 잘못된 값을 발견하는 유일한 수단이다.
- `session_id`·`template_id` 는 **다운로드 버튼이 쓴다.**
- `ready_for_download` 는 "빈 항목이 없다"는 **판정**이다 (파일이 만들어졌다는 뜻이 아니다).

### 5-6. 다운로드 — **클릭 시점에 만든다**

```
POST {006}/generate
```
```json
{ "template_id": "주간보고", "session_id": "s1", "filename": "8월보고" }
```

응답은 **JSON 이 아니라 hwpx 바이너리**다.

```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="8월보고.hwpx"
X-Document-Format: hwpx
X-Body-Blocks: 2
```

> **006 만 파일을 직접 내려준다.** 018 세 단위는 결과를 만들 때 txt 를 굳혀 CDN 에 올리고
> `download_url` 을 주는데, 006 은 **대화 중간에 바로 받는 흐름**이라 그 순간 문서를
> 만든다. `download_url` 은 006 payload 에 **없다.**

`values` 를 직접 줘서 세션 없이 만들 수도 있다(단발 호출):

```json
{ "template_id": "주간보고", "values": { "제 목": "즉석" }, "blocks": [] }
```

- `format` 은 생략이 기본이고 **`hwpx` 외의 값은 400** 이다.
- 템플릿이 없으면 **404**, 손상·삽입 위치 없음이면 **422**.

---

## 6. 화면이 직접 부르는 조회·편집 (스텝을 지나지 않는다)

### 6-1. 선택지

| 요청 | 응답 요지 |
|---|---|
| `GET {글다듬이}/policies` | 문서유형 5종 + 톤 4종, 문서유형별 `allowed_tones`·`forced_tone`, `policy.source`/`reason` |
| `GET {번역}/languages` | 언어 6종 + 문체 2종, 지원 방향 |
| `GET {FAQ}/config` | `formats: ["txt"]`, 개수 기본값·상한 |
| `GET {006}/templates` | 템플릿 목록 + 항목 수·색인 여부 |
| `GET {006}/fields?template_id=주간보고` | 항목 명세 (이름·안내문·서식) |

### 6-2. 006 화면 편집 — 대화를 거치지 않고 값 고치기

```
PATCH  {006}/values   { "session_id": "s1", "values": {"제 목": "새 제목"}, "preview": true }
DELETE {006}/values   { "session_id": "s1", "fields": ["제 목"], "preview": true }
PUT    {006}/blocks   { "session_id": "s1", "blocks": [...], "preview": true }
```

세 경로 모두 갱신된 화면 payload 를 돌려준다. `preview: false` 면 마크다운을 만들지
않아 가볍다 — 연속 편집에 쓴다.

> `PUT /blocks` 는 **전체 목록을 그대로 받는다**(부분 갱신이 아니다).

### 6-3. 프롬프트 출처

```
GET  {단위}/prompts          → { "prompts": [{ "name": "system", "configured": true,
                                              "source": "prompt_library", "reason": "ok" }] }
POST {단위}/prompts/reload   → 같은 모양 (TTL 60초를 건너뛴다)
```

**본문(`body`)은 실리지 않는다** — 담으면 이 경로가 지시문 유출 경로가 된다.

---

## 7. 자주 어긋나는 자리

| 증상 | 원인 |
|---|---|
| 캔버스에서 고른 톤이 무시된다 | 정책 프롬프트 ID 를 글다듬이·MCP **한쪽에만** 넣었다 |
| 다운로드가 빈 문서 | 006·FAQ 의 워크플로우 pod 와 코드서빙 pod 가 **다른 Redis** 를 본다 |
| 결과는 오는데 파일만 못 받는다 | `GENOS_CDN_*` 이 잘못 잡혔다 (`download_url` 이 `null`) |
| 재시도가 무한히 걸린다 | `retryable` 판정이 뒤집혔다 — 스텝은 **상태코드가 아니라 응답 본문의 `error_code` 분류**로 판정해야 한다 |
| 화면에 값이 두 벌 보인다 | 마지막 스텝이 `{**data}` 로 payload 를 만들었다 |
| 번역문에 한국어가 섞인다 | 프롬프트의 출력 언어 고정 문장이 약해졌다 (`system_batch.j2` 두 자리) |
| 표가 깨진다 | 전처리기 확장자 매핑에 `hwpx` 를 안 걸어 예전 경로가 받았다 |
