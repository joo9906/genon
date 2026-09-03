# FRONT.md — 프론트가 주고받는 값

**대상: 템플릿 채우기(SFR-006) · 글다듬이 · 번역(SFR-018).**
FAQ 는 이 문서에 없다(요청 범위 밖). 필요하면 같은 형식으로 덧붙인다.

이 문서의 키·값은 전부 **운영 코드에서 확인한 것**이고 근거 파일을 각 절에 적었다.
추측으로 적은 자리는 없고, 미확정인 것은 §6 에 모아 두었다.

---

## 0. 통신은 두 갈래다

| 갈래 | 무엇 | 언제 |
|---|---|---|
| **캔버스 워크플로우** (소켓) | 실제 실행 — 다듬기·번역·대화 | 사용자가 실행 버튼을 누를 때 |
| **코드서빙 REST** (HTTP) | 선택지 목록·템플릿 목록·미리보기·다운로드 | 화면을 그릴 때 · 다운로드할 때 |

**드롭다운 선택지를 화면이 들고 있으면 안 된다.** 언어·톤·문서유형은 백엔드가 표를
갖고 있고 관리자가 늘릴 수도 있다(글다듬이 톤). 화면이 자기 목록을 들면 한쪽만 고쳐도
**예외가 나지 않고 "지원하지 않는 값" 이나 빈 드롭다운으로만** 드러난다.

---

## 1. 공통 규약 (세 기능 동일)

### 1.1 소켓 이벤트는 `token` 과 `result` 둘뿐이다

```
token  →  token  →  token  → … →  result      (정상)
                                   result      (오류 — 018 두 기능은 토큰이 하나도 안 나간다)
```

| 이벤트 | data | 설명 |
|---|---|---|
| `token` | 문자열 조각 | **정본**(마크다운 원문)이 흐른다. `<mark>` 태그는 **없다** |
| `result` | 아래 payload | **한 번만** 온다. 이 시점에 화면을 완성한다 |

- **`token` 은 연출이다.** 결과가 확정된 뒤 잘라서 보내는 것이라 "AI 가 주루룩 답변하는"
  모양을 만들되, 실제 내용은 `result` 가 정본이다.
- **스트리밍 중에는 원시 마크다운·HTML 표가 그대로 보인다** — 허용된 동작이다(요구 확정).
  `result` 가 오면 그 자리를 하이라이트 두 벌로 **갈아 끼운다.**
- 조각 수에는 상한(400)이 있어 긴 문서에서 조각이 커진다 — 화면은 조각 크기를 가정하지 말 것.
- **오류일 때 018 두 기능은 토큰을 하나도 보내지 않는다.** 006 은 오류 문구를 흘린다
  (채팅이 곧 화면이라 그렇다).

근거: `onprem/workflow/sfr018_polish_02_polish.py:453`,
`sfr018_translate_02_translate.py:467`, `sfr006_03_commit.py:264,348`

### 1.2 payload 는 **화면이 보는 값만** 담는다

내부 판정·검증·지표(준수율·폴백률·기각 건수)는 **로그가 갖는다.** payload 에 없다고
빠뜨린 것이 아니라 **일부러 뺀 것**이니 화면이 그 값을 기대하고 만들지 말 것.

**있을 때만 실리는 키가 둘이다.**

| 키 | 규약 |
|---|---|
| `error` | **오류일 때만.** 정상 응답에 `error: null` 은 없다 (018 두 기능) |
| `notice` | **안내할 것이 있을 때만.** 늘 있는 빈 배열은 읽는 쪽이 "확인했다" 고 믿게 만든다 |

> **006 만 예외다** — 정상 응답에도 `"error": null` 이 실린다. 006 은 `notice` 가 없다
> (안내가 `text` 문장에 들어 있다).

`genos_state` 는 플랫폼 추적값이다 — **화면은 무시한다.**

### 1.3 오류 객체

```json
{ "error": { "error_code": "02-00020001", "msg": "…잠시 후 다시 시도해 주세요.", "retryable": true } }
```

- **`msg` 를 그대로 보여주면 된다.** 고정 한국어 안내문이고 내부 정보(URL·예외 원문)가
  들어가지 않는다. 화면이 문구를 새로 만들지 말 것 — 같은 문장이 두 곳에 살게 된다.
- **`retryable: false` 면 다시 눌러도 같은 자리에서 실패한다**(배포·설정 문제). 재시도
  버튼을 권하지 말고 "관리자 문의" 로 안내한다.
- `error_code` 는 `영역-코드` 꼴이다(`02` 워크플로우 / `03` 코드서빙). 화면에 그대로
  노출할지는 정책이지만, 문의 접수 때 이 값이 있어야 로그를 찾을 수 있다.

### 1.4 하이라이트 — `<mark>` 가 본문에 섞여 온다

**원문과 결과를 좌우로 놓고 비교**하는 화면이 전제다. 양쪽 텍스트에 `<mark>…</mark>`
가 이미 입혀져 있다.

| 기능 | 왼쪽(`original_text`) | 오른쪽 |
|---|---|---|
| 글다듬이 | **지워진** 낱말 | `polished_text` — **새로 들어온** 낱말 |
| 번역 | 사전 용어가 **원문에서** 쓰인 자리 | `translated_text` — 그 용어가 **번역문에서** 쓰인 자리 |

- **번역에서 왼쪽만 형광이고 오른쪽 짝이 없으면 "사전 용어인데 번역이 그 말을 안 썼다"** 다.
  그 건수는 `notice` 로도 온다.
- 칠하는 구간은 문서에 **실제로 적힌 글자**다 — 한국어는 조사까지 덮인다
  (`<mark>신용회복위원회를</mark>`).
- 코드펜스 안과 HTML 태그 가운데는 칠하지 않는다(칠하면 표가 깨진다).

> ⚠ **화면이 raw HTML 을 렌더해야 형광이 보인다.** 막혀 있으면 `<mark>` 가 글자 그대로
> 노출된다. **이 허용 여부는 아직 확인되지 않았다**(§6). 못 쓰면 백엔드 상수 두 곳만
> 고쳐 다른 표기로 바꿀 수 있으니 알려줄 것.

### 1.5 내려받기

| 기능 | 방식 |
|---|---|
| 글다듬이 · 번역 | 결과를 만들 때 서빙이 **txt 를 미리 굳혀 올리고 `download_url` 만** 준다 |
| 템플릿 채우기 | 버튼이 `POST /generate` 를 불러 **hwpx 를 그 자리에서** 받는다 |

- **`download_url` 이 `null` 일 수 있다.** 업로드 실패는 다듬기·번역이 실패한 것과 다른
  사건이라 결과는 그대로 나가고 링크만 빈다 — 화면은 "파일로 받을 수 없습니다" 를
  말할 수 있어야 한다(버튼을 비활성화하거나 숨긴다).
- 파일 본문은 payload 에 없다. **화면이 텍스트를 되돌려 보내 파일을 만드는 방식이 아니다.**
- 폐쇄망에서 링크가 도는지는 **미검증**이라 옛 방식(`POST /download` 에 텍스트를 보내
  파일을 받는다)이 폴백으로 남아 있다.

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

근거: `onprem/codeserving/SFR-018_text_polish/main.py` `GET /policies`,
`text_polish/tone_presets.py` `doc_type_choices`/`tone_choices`/`policy_source`

### 2.2 보내는 값 (캔버스 변수)

| 자리 | 키 | 필수 | 값 |
|---|---|---|---|
| `overrideConfig.vars` | `polish_doc_type` | 선택 | `/policies` 의 `doc_types[].code`. 없으면 `email` |
| `overrideConfig.vars` | `polish_tone` | 선택 | `tones[].code`. 없거나 정책상 불가면 대체된다 |
| `overrideConfig.vars` | `genosUploaded` | 조건부 | 업로드 문서(전처리기 산출물). **이것이 있으면 우선** |
| 최상위 | `question` (또는 `text`) | 조건부 | 채팅으로 붙여 넣은 원문 |

- **원문 출처는 둘 중 하나다** — 업로드 문서가 있으면 그것을, 없으면 발화를 다듬는다.
  둘 다 없으면 `INPUT_EMPTY` 오류다.
- 실질 상한은 **업로드 용량**이다. 긴 문서는 백엔드가 조각으로 나눠 끝까지 처리한다.

근거: `onprem/workflow/sfr018_polish_01_policy.py:260-284`

### 2.3 받는 값 — `result.data`

```json
{
  "original_text": "…<mark>개발함</mark>…",
  "polished_text": "…<mark>개발하였습니다</mark>…",
  "download_url": "https://…/글다듬이결과.txt",
  "notice": ["표·제목 등 문서 구조가 원문과 달라진 곳이 2곳 있습니다. 결과를 확인해 주세요."]
}
```

| 키 | 항상? | 설명 |
|---|---|---|
| `original_text` | ✅ | 원문 + `<mark>`(지워진 낱말) |
| `polished_text` | ✅ | 다듬은 글 + `<mark>`(새 낱말) |
| `download_url` | ✅ (값은 `null` 일 수 있다) | 미리 굳힌 txt |
| `notice` | 있을 때만 | 문자열 배열. 그대로 보여준다 |
| `error` | 오류일 때만 | §1.3 |

**`notice` 에 오는 문구 3종** (건수만 말한다 — 어느 값인지는 문서 내용이라 싣지 않는다):

- `문서 일부 구간(N곳)을 다듬지 못해 원문 그대로 두었습니다. 다시 시도해 주세요.`
- `표·제목 등 문서 구조가 원문과 달라진 곳이 N곳 있습니다. 결과를 확인해 주세요.`
- `숫자·날짜가 원문과 다른 곳이 N곳 있습니다. 결과를 확인해 주세요.`

근거: `onprem/workflow/sfr018_polish_02_polish.py:526-565`

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

근거: `onprem/codeserving/SFR-018_translation/main.py` `GET /languages`,
`translation_pipeline/office/languages.py:64-69,93`, `registers.py:75`

### 3.2 보내는 값 (캔버스 변수)

| 자리 | 키 | 필수 | 값 |
|---|---|---|---|
| `overrideConfig.vars` | `translate_target_lang` | **✅ 필수** | `languages[].code`. 없으면 오류 |
| `overrideConfig.vars` | `translate_source_lang` | 선택 | 원문 언어. **비워도 된다**(아래) |
| `overrideConfig.vars` | `translate_register` | 선택 | `registers[].code` (문어체/구어체) |
| `overrideConfig.vars` | `genosUploaded` | 조건부 | 업로드 문서(전처리기 산출물) |
| `overrideConfig.vars` | `translate_hwpx_path` | 선택 | hwpx 원본 경로. 있으면 **표 보존이 더 좋다** |
| 최상위 | `question` (또는 `text`) | 조건부 | 채팅으로 붙여 넣은 원문 |

**원문 언어(`translate_source_lang`)는 비워도 된다 — 백엔드가 감지한다.** 다만 값을
보내면 그것을 **정본**으로 삼고, 감지 결과와 대조해 "한국어가 아닌 쌍"(예: 선언은
`ko→ru` 인데 실제로는 영어 문서 → `en→ru`)이면 **거부**한다. 즉 원문 드롭다운을 두면
사용자가 잘못 고를 수 있으니, **비워 두고 감지에 맡기는 편이 안전하다.**

근거: `onprem/workflow/sfr018_translate_01_detect.py:302-373,459-469`

### 3.3 받는 값 — `result.data`

```json
{
  "original_text": "…<mark>가맹점</mark>…",
  "translated_text": "…<mark>merchant</mark>…",
  "download_url": "https://…/번역결과.txt",
  "notice": ["용어사전 용어 3개가 번역문에 반영되지 않았습니다 (원문에서 형광으로 표시된 자리입니다). 다시 번역하면 반영될 수 있습니다."]
}
```

글다듬이와 **같은 모양**이고 이름만 `translated_text` 다.

**`notice` 에 오는 문구 3종:**

- `용어사전 용어 N개가 번역문에 반영되지 않았습니다 (원문에서 형광으로 표시된 자리입니다). 다시 번역하면 반영될 수 있습니다.`
- `문장 N개를 번역하지 못해 원문 그대로 두었습니다. 다시 번역해 주세요.`
- `원문과 번역문의 숫자·날짜가 N곳 다릅니다. 결과를 확인해 주세요.`

> **자동 재번역은 하지 않는다** (요구 확정). 사실만 알리고 **다시 번역할지는 사용자가
> 정한다** — 화면에 "다시 번역" 버튼을 두는 것이 이 안내문의 전제다.

근거: `onprem/workflow/sfr018_translate_02_translate.py:529-567`

---

## 4. 템플릿 채우기 (SFR-006)

**앞의 둘과 방향이 반대다 — 전용 UI 가 없고 채팅이 곧 화면이다.** 그래서 `text`(답변
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

### 4.3 보내는 값 (캔버스 변수)

| 자리 | 키 | 필수 | 값 |
|---|---|---|---|
| `overrideConfig.vars` | `template_fill_template_id` | **✅ 필수** | `/templates` 의 `template_id` |
| 최상위 | `question` (또는 `text`) | ✅ | 사용자 발화. **2만 자에서 잘린다** |
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

근거: `onprem/workflow/sfr006_01_context.py:288-291,357`

### 4.4 받는 값 — `result.data`

```json
{
  "text": "제목을 『…』(으)로 채웠습니다. 남은 항목은 담당자, 배포일입니다.",
  "ready_for_download": false,
  "document_markdown": "# …",
  "session_id": "…",
  "template_id": "보도자료",
  "error": null
}
```

| 키 | 설명 |
|---|---|
| `text` | **채팅 말풍선에 그대로 그린다.** 채운 값·`이전 → 새 값`·기각 항목 이름·남은 항목이 전부 문장으로 들어 있다 |
| `ready_for_download` | **다운로드 버튼 활성 여부.** 문장도 "다운로드 버튼을 누르면" 이라고 말하지만 **버튼은 이 불리언으로 정한다** |
| `document_markdown` | 미리보기. **채팅 문장에는 안 들어간다** — 문서 창을 따로 그린다 |
| `session_id` · `template_id` | 화면에 보이지 않지만 **다운로드 버튼이 쓴다** (§4.5) |
| `error` | 006 은 정상일 때도 `null` 로 실린다 |

근거: `onprem/workflow/sfr006_03_commit.py:238-259,369-381`

### 4.5 내려받기 — `POST /generate`

```json
{ "template_id": "보도자료", "session_id": "…", "filename": "보도자료_최종" }
```

응답은 **hwpx 파일 바이트**다. `format` 은 생략한다(hwpx 만 지원하며 다른 값은 400).
`filename` 은 선택이다.

**018 둘과 달리 링크가 아니다** — 대화 중간에 바로 받는 흐름이라 그 자리에서 만든다.

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

근거: `onprem/codeserving/SFR-006_template_fill/template_fill/session_view.py:157,179`,
`api_requests.py:36-61`

---

## 5. 오류 코드

세 기능이 같은 네 갈래를 쓴다. `msg` 를 그대로 보여주면 되고, 화면이 분기할 값은
**`retryable`** 하나다.

| 상황 | retryable | 사용자가 할 일 |
|---|---|---|
| 응답 지연·통신 실패 | `true` | 잠시 후 다시 |
| 실행 실패 | `true` | 잠시 후 다시 |
| **설정 부재** (배포 실수) | `false` | 관리자 문의 — **다시 눌러도 같은 자리에서 실패한다** |
| **최종 실패** (서빙이 재시도 불가로 못 박은 응답) | `false` | 관리자 문의 |

기능별로 더 있는 것:

| 기능 | 상황 | 안내 |
|---|---|---|
| 글다듬이 | 원문 없음 / 입력 초과 | 문서나 텍스트를 넣어 달라 / 길이를 줄여 달라 |
| 번역 | 대상 언어 없음 | 대상 언어를 골라 달라 |
| 번역 | **한국어 축 위반** | 원문·대상 중 하나는 한국어여야 한다 (§3.1 로 미리 막을 것) |
| 006 | 템플릿 없음 | 템플릿을 고르거나 등록해 달라 |

---

## 6. 확인·결정이 필요한 것

프론트 작업 전에 답이 필요한 것들이다. 백엔드에서 정할 수 있는 것은 알려주면 바꾼다.

1. **`<mark>` raw HTML 렌더가 가능한가** (§1.4). 막혀 있으면 형광 대신 태그 글자가
   보인다 — 이 기능들의 핵심 표시라 대안 표기(마커 문자열 + 좌표 배열)로 바꿔야 한다.
   백엔드 상수 두 곳만 고치면 된다.
2. ~~글다듬이 강제 톤을 `/policies` 에 실을 것인가~~ — **구현했다** (§2.1.1).
   `doc_types[].allowed_tones` 가 **언제나 실제 선택 가능한 톤 목록**이고, 원소가
   하나면 잠그면 된다. `forced_tone`(불리언)은 잠금 문구를 나눌 때만 읽는다.
3. **강제 톤이 바뀐 사실을 사용자에게 보일 것인가.** 백엔드는 `tone_overridden` 과
   안내 문구를 만들지만 **최종 payload 에는 넣지 않는다**(캔버스 분기용으로만 쓴다).
   화면이 §2.1.1 대로 잠그면 이 상황이 생기지 않으므로 **당장은 필요 없다** — 화면이
   잠그지 않는 경로(외부 API 호출 등)를 열 때만 `notice` 에 얹으면 된다.
4. **결과 파일 이름을 사용자가 정하게 할 것인가** (018 둘). `polish_title`/`translate_title`
   을 읽는 코드는 있지만 **채우는 자리가 없어** 지금은 언제나 기본값
   (`글다듬이결과.txt` 등)이다. 필요하면 캔버스 변수를 하나 늘린다.
5. **`download_url` 이 폐쇄망에서 실제로 열리는지 미검증이다** (§1.5). 안 되면 옛
   `POST /download` 폴백으로 배선해야 하고, 그때는 화면이 텍스트를 되돌려 보내야 한다.
6. **FAQ 는 이 문서에 없다.** 같은 형식으로 필요하면 알려줄 것.
