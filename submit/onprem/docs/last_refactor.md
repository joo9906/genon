# SFR-018 최종 점검 (2026-08-13) — 경계에서 유실되던 것들

> **후속 (2026-08-28).** 여기 적힌 `translated_markdown`·`polished_text` 는 캔버스
> payload 에서 빠졌다 — 내려받기가 링크가 되면서 화면이 정본을 들고 있을 이유가
> 사라졌다. 근거와 대체 필드는 `change_0828.md`. 이 문서는 그날의 기록이라 본문은
> 그대로 둔다.

폐쇄망 이관 전 마지막 훑기. **고친 여섯 건이 전부 같은 성격**이다 — 예외를 던지지 않고
조용히 틀린다. `.get()` 이 기본값을 주거나, 두 사건이 같은 오류 코드로 뭉쳐 있거나,
안내문이 엉뚱하거나. 전부 로그에 정상으로 찍혀서 **실행해서 값을 대조하기 전에는
드러나지 않는다.**

이 문서는 **무엇을 왜 고쳤는지의 정본**이다. 루트 `CLAUDE.md` 에 요약이 있고
(「SFR-018 최종 점검 (2026-08-13)」 절), 여기는 파일·함수 단위로 적는다.
운영 규약·환경변수는 `onprem/README.md` 가 정본이므로 여기 복사하지 않는다.

---

## 요약 — 고친 것

| # | 어디 | 증상 | 상태 |
|---|---|---|---|
| 1 | FAQ 워크플로우 스텝 2 | 기각 건수가 캔버스에 **영원히 0** | 고침 |
| 2 | FAQ 코드서빙 | 근거 미확보·프롬프트 부재가 실행 실패와 뭉침 | 고침 |
| 3 | 글다듬이 오류코드 | 코드 서빙인데 **영역코드 02** | 고침 |
| 4 | 글다듬이 입력 검증 | 상한 초과에 "입력이 비었다" 안내 | 고침 |
| 5 | 글다듬이 설정 | env 가 **import 시점에 얼어붙음** | 고침 |
| 6 | 번역 응답 검증 | LLM 응답 원문을 문자열로 만듦 (3.8절) | 고침 |
| — | 점검 | **1·2 를 잡는 그물이 없었다** | 추가 (35→42, 31→39) |

---

## 1. FAQ 기각 건수가 캔버스에 영영 닿지 않고 있었다

**파일**: `onprem/workflow/sfr018_faq_02_generate.py`

`run()` 이 코드서빙 응답에서 `result.get("stats")` 를 읽었다. **그런 키가 없다.**
`faq/generator.py` 의 `FaqResult.as_payload()` 가 내는 것은:

```python
{"items", "count", "requested_count", "max_count", "count_clamped",
 "rejected": {"schema", "ungrounded", "duplicate"}, "source_truncated"}
```

`stats` 는 어디에도 없으므로 `dict(result.get("stats") or {})` 는 **항상 `{}`** 였다. 결과:

- 스텝 로그가 늘 `schema=0 ungrounded=0 duplicate=0` — "문제 없음" 으로 보였다
- 캔버스로 나가는 `faq_stats` 가 항상 빈 dict

**요구사항 §2·§4 가 요구하는 값이 정작 경계를 못 넘고 있었다.** `CLAUDE.md` 가
"기각 건수를 전부 노출한다. 조용히 버리면 왜 5개 요청에 3개만 나왔는지 알 수 없다" 고
못박은 바로 그 값이다.

**고친 방식** — 응답이 실제로 내는 이름을 읽고, `faq_stats` 키 이름은 유지한다
(그 값이 지금껏 항상 비어 있었으므로 화면이 내용에 의존할 수가 없었다):

```python
rejected = dict(result.get("rejected") or {})
stats = {
    "requested_count": int(result.get("requested_count") or 0),
    "count": int(result.get("count") or len(items)),
    "count_clamped": bool(result.get("count_clamped")),
    "source_truncated": bool(result.get("source_truncated")),
    "rejected": rejected,
}
```

로그도 `rejected.get('schema', 0)` 로 바꿨다.

> **같은 결함이 두 번째다.** 2026-08-12 에 번역 스텝이 `translated_markdown` 을 읽고
> 있었고(응답 키는 `markdown`) **번역이 매번 "결과가 비어 있음" 으로 끝나고 있었다.**
> 두 번 났다는 것은 우연이 아니라 **그물이 없다는 뜻**이다 → 아래 「그물」 절.

---

## 2. FAQ 근거 미확보가 실행 실패와 뭉쳐 있었다

**파일**: `faq/main.py`, `faq/error_codes.py`

### 무엇이 문제였나

`_generate_and_store` 가 통신 실패만 갈라내고 나머지를 전부 502 로 냈다:

```python
if result.failure == FAILURE_TRANSPORT:
    return _error_response(ERR_API_UPSTREAM_TIMEOUT)
return _error_response(ERR_API_UPSTREAM_EXECUTION)   # ← 나머지 셋이 여기로
```

그런데 워크플로우 스텝은 **이미** 근거 미확보 분기를 걸어 뒀다:

```python
elif upstream_status == 422:
    # 근거를 찾은 항목이 하나도 없을 때 코드서빙이 422 를 낸다
    key = "NO_GROUNDED"
```

**서빙이 422 를 낸 적이 없다.** 그래서 이 분기도, 그 짝인
`ERR_CHAT_NO_GROUNDED_ITEMS` 도 **닿을 수 없는 코드**였다. 사용자는 "이 문서로는 근거
있는 FAQ 가 안 나온다" 대신 늘 "FAQ 생성에 실패했습니다. 잠시 후 다시 시도해 주세요" 를
봤다. 게다가 422 는 pydantic 검증 실패로도 나므로, **닿는 경우엔 오히려 틀린 안내**가
나갔을 것이다.

`FAILURE_PROMPT` 는 더 나빴다 — 프롬프트 템플릿을 못 찾은 것은 **이미지에
`onprem/prompt/SFR-018_faq/` 를 안 넣은 배포 실수**라 몇 번을 불러도 같은 자리에서
실패하는데, 502 `retryable=True` 로 나가서 캔버스가 재시도를 걸 수 있었고 로그의
`error_type` 도 LLM 실패와 같아 **배포 구성 문제라는 사실이 어디에도 드러나지 않았다.**

### 고친 방식 — 네 갈래, 매핑표 한 곳

`faq/main.py` 에 표를 두고 `_generate_and_store` 는 조회만 한다:

```python
_FAILURE_ERRORS = {
    FAILURE_TRANSPORT:   ERR_API_UPSTREAM_TIMEOUT,
    FAILURE_NO_GROUNDED: ERR_API_NO_GROUNDED,
    FAILURE_PROMPT:      ERR_API_PROMPT_UNAVAILABLE,
}
...
return _error_response(_FAILURE_ERRORS.get(result.failure, ERR_API_UPSTREAM_EXECUTION))
```

| `generator.FAILURE_*` | HTTP | 오류 코드 | retryable | 사용자가 할 일 |
|---|---|---|---|---|
| `TRANSPORT` | 504 | `ERR_API_UPSTREAM_TIMEOUT` | ✓ | 잠시 후 다시 |
| `NO_GROUNDED` | **422** | `ERR_API_NO_GROUNDED` (신규) | ✓ | 문서를 바꾸거나 개수를 줄인다 |
| `PROMPT` | **500** | `ERR_API_PROMPT_UNAVAILABLE` (신규) | **✗** | 관리자에게 문의 |
| 그 외 | 502 | `ERR_API_UPSTREAM_EXECUTION` | ✓ | 잠시 후 다시 |

표에 없는 값은 실행 실패로 떨어진다 — **새 분류를 만들고 여기 안 적어도 조용히 성공으로
넘어가지는 않는다.**

**422 를 고른 이유**: 워크플로우 스텝이 먼저 그 상태코드를 근거 미확보로 읽도록 짜여
있었다. 스텝을 고치는 대신 서빙을 거기 맞췄다 — 캔버스에 붙은 스텝 사본을 다시 배포하는
쪽이 비용이 크다. 3.9.2 의 "새 숫자코드를 만들지 않는다" 는 지킨다(둘 다
`00020002`/`00020003` 조합이고 달라지는 것은 `error_type`·`http_status` 뿐이다).

---

## 3. 글다듬이가 영역코드 02 를 내고 있었다

**파일**: `text_polish/error_codes.py`

`_AREA_CODE = "02"` 이었고 주석에 "워크플로우 Python 단계이므로" 라고 적혀 있었다.
**그 전제는 2026-08-11 영역 재배치로 없어졌다**:

- 글다듬이는 워크플로우(02) → **코드 서빙(03)** 이 됐다
- 02 를 낼 몫은 `onprem/workflow/sfr018_polish_0{1,2}.py` 두 스텝이 각자 `_AREA = "02"`
  오류표를 들고 가져갔다

즉 **02 를 내는 주체가 따로 생겼는데 서빙도 계속 02 를 냈다.** 3.9.1 은 영역코드로
"어디서 난 오류인가" 를 가르는데, 둘이 같은 값이면 로그에서 구분할 수 없다.
번역·FAQ 서빙은 둘 다 03 이라 **이 단위만 어긋나 있었다.** → `03` 으로 고쳤다.

---

## 4. 글다듬이 상한 초과에 "입력이 비었다" 안내가 나갔다

**파일**: `text_polish/error_codes.py`, `SFR-018_text_polish/main.py`

`/polish` 와 `/download` 가 둘 다 이랬다:

```python
if len(source_text) > _MAX_INPUT_CHARS:
    return _error_response(ERR_INPUT_EMPTY, 422)   # ← 안내문: "다듬을 문서나 텍스트를 입력해 주세요."
```

20만 자를 붙여 넣은 사용자가 **"입력해 주세요"** 를 받았다. 무엇을 하라는 건지 알 수 없고,
로그의 `error_type` 도 `POLISH_INPUT_EMPTY` 라 운영에서는 "빈 입력이 왜 이렇게 많나" 로
보인다. **두 사건은 사용자가 할 일이 정반대다.**

→ `ERR_INPUT_TOO_LONG`(422, "문서가 너무 깁니다. 나누어 요청해 주세요.")을 갈라냈다.

### 함께 정리 — `ErrorCode` 가 `http_status` 를 들고 있게 했다

그전에는 `_error_response(코드, 422)` 처럼 **호출부가 상태코드를 손으로** 넘겼다. 같은
코드가 자리마다 다른 상태로 나갈 수 있는 형태이고, 실제로 `ERR_INPUT_EMPTY` 가 400·422
두 곳에 쓰이고 있었다. 번역·FAQ 단위처럼 코드에 붙여 한 곳에서 정한다:

```python
def _error_response(error_code) -> JSONResponse:
    return JSONResponse(status_code=error_code.http_status, content={...})
```

`JSONResponse` 를 함수 안에서 import 하던 것도 모듈 최상위로 올렸다.

---

## 5. 글다듬이 설정이 import 시점에 얼어붙어 있었다

**파일**: `text_polish/config.py`(신규), `text_polish/llm.py`

`llm.py` 가 모듈 최상위에서 읽었다:

```python
GENOS_URL = os.environ.get("GENOS_URL", "").rstrip("/")
RES_TIMEOUT = float(os.environ.get("RES_TIMEOUT", "60"))
```

**import 되는 순간 값이 확정된다.** 프로세스가 뜬 뒤 환경이 채워지는 경로(점검 스크립트가
env 를 세팅한 뒤 단위를 싣는 경우가 정확히 이것이다)에서는 빈 값이 그대로 남아 "설정을
넣었는데 안 읽는다" 가 된다. 번역·FAQ 는 이미 `Config` 클래스로 이 문제를 피하고 있었고
**이 단위만 옛 모양**이었다.

`text_polish/config.py` 를 만들어 셋을 같은 모양으로 맞췄다:

- `genos_url()`·`llm_serving_id()`·`llm_model_id()` — 호출 시점에 읽는다
- `genos_token()` — 시크릿은 클래스 속성으로 두지 않는다(그러면 import 단계에서 검증이
  돌아 **토큰 없는 환경에서는 모듈을 열 수조차 없다**)
- `MAX_INPUT_CHARS` — `POLISH_MAX_INPUT_CHARS` 로 조정 가능 (기본 200000)

**덤**: `RES_TIMEOUT` 기본값을 60 → **90**(번역·FAQ 와 동일)으로 올렸다. 글다듬이는
**문서 전체를 한 번에** LLM 에 보내는 단위라 셋 중 가장 오래 걸리는데 제한이 가장 짧았다 —
긴 문서에서 timeout 이 먼저 나고, 그 실패는 재시도 가능(00020001)으로 분류돼 같은
자리에서 또 걸린다.

---

## 6. 번역 검증이 LLM 응답 원문을 문자열로 만들고 있었다

**파일**: `translation_pipeline/common/validation.py`, `office/translation_modes.py`

```python
result.soft_warnings.append(f"skipping malformed item: {item!r}")
```

아무도 읽지 않는 필드였다 — 호출부(`translation_modes._translate_batch`)는
`len(validation.hard_errors)` 만 본다. 그래도 고친 이유: **3.8절이 금지하는 것은 로그
출력이 아니라 그 경로가 존재하는 것**이다. 나중에 누가 "디버깅에 도움 되겠다" 며 이
목록을 로그에 흘리면 문서 원문과 번역문이 통째로 나간다. 같은 파일의 다른 자리에는
이미 "응답 원문이 섞여 들어올 경로를 아예 만들지 않는다 (3.8절)" 라고 적혀 있었다 —
**규율은 있었는데 이 함수만 어기고 있었다.**

→ **사유별 건수**만 센다:

```python
skipped: Dict[str, int]        # malformed / bad_id / empty
skipped_count -> int
```

그 수를 배치 재시도 로그에 실었다(`status=f"retry={n},skipped={m}"`). 값은 담기지 않는다.

---

## 그물 — 1·2 를 잡는 점검이 **하나도 없었다**

### 왜 없었나

`onprem/test/check_workflow_run.py` 는 그때까지 **설정 부재 경로만** 태웠다(환경변수를
일부러 비우고 `CONFIG_MISSING` 을 확인). 그 경로에서 스텝은 게이트웨이 응답을 **한 번도
읽지 않는다** — 그래서 응답에서 무슨 키를 꺼내는지는 검사된 적이 없었다.

| 언제 | 무엇 | 증상 |
|---|---|---|
| ~2026-08-12 | 번역 스텝이 `translated_markdown` 을 읽었다 (응답 키는 `markdown`) | 번역이 **매번** "결과가 비어 있음" |
| ~2026-08-13 | FAQ 스텝이 `stats` 를 읽었다 (그런 키가 없다) | 기각 건수가 **영원히 0** |

둘 다 예외를 던지지 않는다. `.get()` 이 조용히 기본값을 주므로 정상 동작처럼 보인다.

### 무엇을 붙였나 — `_run_contracts`

게이트웨이 호출부(`_post_serving`/`_mcp_call`)**만** 대역으로 바꾸고 018 마지막 스텝 3개를
**성공 응답으로** 돌린다. 스텝의 응답 해석 코드는 그대로 도는 것이 핵심이다 — 그게 검사
대상이다.

**응답을 지어내지 않는다.** 페이로드를 점검 파일에 손으로 적으면 대조가 성립하지 않는다
(코드서빙이 키 이름을 바꿔도 사본은 그대로다). 각 단위의 **실제 조립 함수**를 불러 만든다:

- `faq.generator.FaqResult.as_payload()` + `faq.formatting.to_markdown`
- `api_contract.markdown_payload(MarkdownTranslationArtifacts(...))`

**기각 건수를 0 이 아닌 값으로 준다**(`schema=1, ungrounded=2, duplicate=3`). 전부 0 이면
스텝이 엉뚱한 키를 읽어도 0 이 나와 통과해 버린다 — 이 점검이 잡으려는 결함이 정확히 그것이다.

판정 7건: 항목 전달 / 기각 건수 / 요청 개수 / 번역문 전달 / 성공 판정(정상 응답에 error 를
내지 않는가) / 다듬기 전달 / 파일용 본문에 경고문이 안 섞이는가.

> **두 결함을 되돌려 FAIL 이 나오는 것을 확인하고 넣었다.** 통과하는 것만 보고 넣으면
> 그물이 실제로 무엇을 거르는지 알 수 없다.

### `check_unit_endpoints.py` 에도

- FAQ 생성 실패 **4갈래**가 서로 다른 상태코드로 갈리는지 (`generate_faqs` 경계에 대역을
  꽂아 LLM 없이 태운다) + 프롬프트 부재가 `retryable=False` 인지
- 글다듬이 `/polish`·`/download` 상한 초과가 **빈 입력과 다른 안내문**인지
- 글다듬이 오류 영역코드가 `03-` 인지

### 건수

| 점검 | 전 | 후 |
|---|---|---|
| `check_workflow_run.py` | 35 | **42** |
| `check_unit_endpoints.py` | 31 | **39** |

나머지 9개는 그대로. 11개 전부 + `SFR-006`(28) · `SFR-018`(56) unittest 통과,
`check_deploy_contract` FAIL 0 / WARN 4.

---

## 손대지 않은 것 (의도)

- **워크플로우 스텝 6개의 `_post_json`·`_emit_log`·`_gateway_base` 중복** — §D.3 이
  자기완결을 요구한다. 공용 모듈로 빼면 캔버스에 못 붙는다.
- **`read_upload_capped` 2벌 · `txt_output.py` 3벌** — 배포 단위 간 import 금지.
  후자는 `check_unit_endpoints` 가 응답 바이트로 대조한다.
- **`_ERRORS["INTERNAL"]`** — 018 스텝 3개·006 스텝 3개에서 실제로 쓰이지 않는다
  (최상위 `except` 가 없어서다). 죽은 표 항목이지만 영향이 없어 남겼다.

## 배포 전에 사람이 확인할 것

1. **캔버스 화면이 `faq_stats` 를 읽는다면** 지금까지 늘 `{}` 였다. 이제 값이 들어간다 —
   `{requested_count, count, count_clamped, source_truncated, rejected:{...}}`.
2. **글다듬이 오류코드가 `02-…` → `03-…`** 로 바뀐다. 로그 대시보드·알림 규칙에
   `02-0002` 필터를 걸어 뒀다면 함께 고친다. 워크플로우 스텝이 내는 02 는 그대로다.

## 여전히 남은 미검증 (이번 작업과 무관하게 그대로)

LLM 실호출 경로 전체, 실제 hwpx 로 `POST /translate/hwpx`, 실제 용어사전 파일 적재,
내려받은 `.txt` 를 **실제 윈도우 메모장에서 열어보기**(BOM·CRLF 는 응답 바이트로만 확인).
로컬에 게이트웨이가 없어 이번에도 확인하지 못했다.
