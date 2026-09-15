# 2026-08-27 이관 작업지시 — 파일별·함수별

변경·용어 표시를 **답변 아래 목록 → 본문 위 하이라이트**로 바꿨다. **고칠 파일은 6개**,
그 밖은 손대지 않는다.

**줄 번호는 전부 이 변경이 적용된 워킹트리 기준**이다(직전 커밋은 `178fb44`). 옮긴 뒤
`git show <이 커밋>:<경로>` 로 대조할 것.

**등록 단위 수·시작 커맨드·환경변수는 하나도 바뀌지 않았다** — 재등록이 아니라 리비전
갱신이다. 새로 만드는 파일도, 지우는 파일도 없다.

> **후속 (2026-08-28).** 아래에 적은 `max_items`(기본 50)·`truncated` 는 **없앴다.**
> 잘린 목록으로 `highlighted` 를 만들어 상한이 곧 하이라이트 상한이었다 —
> 51번째 변경부터 `<mark>` 가 안 붙었다. 근거는 `onprem/mcp/README.md` §4-0.
> 이 문서는 그날의 기록이라 본문은 그대로 둔다.

## 요약 — 파일 6개

| # | 파일 | 등록 단위 | 신규 | 시그니처 | 본문 | 삭제 | 줄 수 |
|---|---|---|---|---|---|---|---|
| 1 | `mcp/genon_text_guard.py` | MCP (4개 중 1개) | 4 | 1 | 3 | 0 | 584 → **760** |
| 2 | `workflow/sfr018_polish_02_polish.py` | 워크플로우 (9개 중 1개) | 0 | 0 | 1 | **1** | 458 → **487** |
| 3 | `workflow/sfr018_translate_02_translate.py` | 워크플로우 (9개 중 1개) | 0 | 0 | 1 | 0 | 499 → **504** |
| 4 | `codeserving/SFR-018_translation/translation_pipeline/office/glossary_report.py` | 코드서빙 번역 | 0 | 0 | 0 | 0 | 234 → **240** |
| 5 | `codeserving/SFR-018_translation/api_contract.py` | 코드서빙 번역 (같은 단위) | 0 | 0 | 0 | 0 | 176 → **177** |
| 6 | `codeserving/SFR-018_translation/translation_pipeline/office/types.py` | 코드서빙 번역 (같은 단위) | 0 | 0 | 0 | 0 | **114** (변동 없음) |

**공개 시그니처가 바뀐 것은 하나뿐이다** — `_TGsplit_units` → `_TGsplit_units_with_spans`
(모듈 내부 함수라 파일 밖 영향은 없다). MCP 도구 `diff_changes` 의 **인자는 그대로**이고
응답에 필드 둘(`highlighted`·`truncated`)과 `changes[].span` 이 늘었다 — **기존 필드는
전부 유지되므로 옛 호출부가 깨지지 않는다.**

**호출부·프롬프트·나머지 워크플로우 스텝 7개·MCP 나머지 3파일·006·FAQ 는 한 줄도 안 고친다.**

**작업 순서**: ① MCP(1) → ② 번역 코드서빙(4·5·6 — 한 단위라 같이) → ③ 워크플로우(2·3).
**1을 먼저 올려야 한다** — 2가 `diff_changes` 의 새 응답 필드를 읽는다. 순서를 뒤집으면
스텝 2가 `highlighted` 를 못 받아 정본을 그대로 화면에 흘리고, **그 상태는 오류 없이
"하이라이트가 안 보이는" 모양**이라 원인이 드러나지 않는다.

**4·5·6 은 반드시 같이** 간다(한 배포 단위 = 리비전 하나). 3은 4가 올라간 뒤여야 화면에
`<mark>` 가 나온다 — 먼저 올려도 깨지지는 않는다(사본이 없으면 정본으로 떨어진다).

---

# 1. `onprem/mcp/genon_text_guard.py`

**`# ── diff_report.py ──`(L306) 부터 `# ── tools.py ──` 앞까지가 통째로 교체 대상**이다.
그 위(구조 지문·사실 대조·숫자 대조)와 아래(도구 등록)는 손대지 않는다.

### 새로 넣을 함수 (4)

| L | 함수 | 하는 일 |
|---|---|---|
| 391 | `_TGwords(units)` | 단위 목록을 `(낱말, start, end)` 로 편다. 좌표는 **문서 전체 기준**이다 |
| 400 | `_TGword_changes(src_units, dst_units)` | 바뀐 단위 쌍을 **낱말 단위로 다시 갈라** 변경 항목을 만든다. 삭제만 → `span=None`, 통째로 신규 → 한 항목 |
| 463 | `_TGprotected_regions(text)` | 태그를 끼우면 손상이 되는 구간 — **코드펜스 안쪽 + HTML 태그**. 닫히지 않은 펜스는 문서 끝까지 코드로 본다 |
| 483 | `tgbuild_highlighted(polished, changes)` | 바뀐 자리에 `<mark>` 를 입힌 **표시용 사본**. 겹침은 병합하고 **뒤에서부터** 넣는다 |

### 이름·반환형이 바뀌는 함수 (1)

| L | 대상 | 무엇을 |
|---|---|---|
| 355 | `_TGsplit_units` → **`_TGsplit_units_with_spans`** | 반환이 `List[str]` → `[(텍스트, start, end)]`. 분해 규칙(줄 → 문장, 구조 줄은 통째로)은 **그대로**이고 절대 위치를 함께 낸다. `re.split` 은 위치를 버리므로 **`finditer` 로 자른다** |

> **이름만 바꾸고 반환형을 안 바꾸면 예외가 나지 않는다.** `tgbuild_change_list` 가
> `u[0]` 을 문자열의 첫 글자로 읽어 **한 글자씩 비교한 변경 목록**이 나온다. 옮긴 뒤
> `check_mcp_tools` 의 "span 이 바뀐 낱말을 가리킨다" 가 이것을 잡는다.

### 본문을 고칠 것 (3)

| L | 대상 | 무엇을 |
|---|---|---|
| 347 | `class TGChangeItem` | 필드 **`span: object` 추가**. `revised` 기준 `[start, end)`, 삭제만 일어난 자리는 `None` |
| 434 | `tgbuild_change_list(original, polished, max_items=50)` | 문장 opcode 를 돌며 **`_TGword_changes` 로 낱말까지 내린다**. `max_items` 도달 시 즉시 반환(그전에는 `break`) |
| 596 | `_TGdiff_changes(arguments)` | 응답에 **`highlighted`**(=`tgbuild_highlighted(revised, changes)`)와 **`truncated`**(=`len(changes) >= max_items`) 추가. `ok`·`changes`·`change_count` 는 그대로 |
| 738 | `async def diff_changes(...)` (`@mcp.tool()`) | **독스트링이 LLM 에 노출되는 계약이라 함께 옮긴다.** 인자 시그니처는 변경 없음 |

### 새 모듈 상수 (4)

| L | 상수 | 값·이유 |
|---|---|---|
| 331 | `_TGWORD_RE` | `r"<[^<>\n]{0,300}>\|[^\s<]+\|<"` — **HTML 태그를 따로 끊는다.** `\S+` 로 두면 전처리기가 낸 한 줄 HTML 표가 통째로 낱말 하나가 되고, 그 구간은 태그에 걸치므로 버려져 **HTML 표 안 변경이 영영 안 칠해진다** |
| 336 | `_TGMARK_OPEN` | `"<mark>"` — 굵게(`<strong>`)가 아니다. 원문에도 나오는 표기라 "누가 넣었나" 를 가릴 수 없다 |
| 337 | `_TGMARK_CLOSE` | `"</mark>"` |
| 344 | `_TGHTML_TAG_RE` | `r"<[^<>\n]{0,300}>"` — 보호 구간 판정용 |

`_TGSENT_SPLIT_RE`(L325)는 **값이 그대로다** — 위치만 밀린다.

### 이 파일에서 **안 고치는 것**

- `tgfind_structure_issues` · `tgfact_issues` · `tgnumeric_drift` 계열 전부.
- `_TGHANDLERS` 표(도구 이름 4개 그대로) · `_tg_run` · shim · 로깅.
- **`TG` 접두어 규약** — 새 심볼 전부 `_TG`/`tg` 로 시작한다. 한 서버에 다른 도구 파일이
  함께 로드될 수 있고, 겹치면 나중 것이 앞엣것을 덮는다(예외 없이 "값이 이상하다" 로만 보인다).

---

# 2. `onprem/workflow/sfr018_polish_02_polish.py`

### 지울 것 (1)

| L | 대상 | 왜 |
|---|---|---|
| 268 | **`_format_changes(changes)`** | 답변 끝에 `---` + "주요 변경 내역" + `` `before` → `after` `` 목록을 만들던 함수. 그 자리에 **근거 주석 블록만 남긴다**(왜 뗐는지가 없으면 되살아난다) |

### 본문을 고칠 것 (1개 함수, 자리 5곳)

| L | 대상 | 무엇을 |
|---|---|---|
| 391 | `run` — 지역변수 선언 | **`highlighted = ""`**, **`changes_truncated = False`** 추가 |
| 414 | `run` — guard 응답 수집 | `diff_changes` 분기에서 `highlighted = str(payload.get("highlighted") or "")`, `changes_truncated = bool(payload.get("truncated"))` 를 함께 읽는다 |
| 452 | `run` — 안내문 조립 | `if changes_truncated:` → `"⚠ 변경이 많아 앞쪽 N건만 표시했습니다."`. 없으면 "뒷부분은 안 바뀌었다" 로 읽힌다 |
| 456 | `run` — 빈 줄 판정 | `if structure_warnings or fact_warnings` → **`or changes_truncated` 추가** |
| 460 | `run` — 화면 텍스트 | `display_text = notice + polished + _format_changes(changes)` → **`notice + (highlighted or polished)`**. 점검이 실패해 사본을 못 얻으면 정본으로 떨어진다 |
| 478 | `run` — `result` payload | **`"polished_text_highlighted": highlighted or polished` 추가**. `polished_text`(정본)·`changes`는 그대로 |

모듈 독스트링도 함께 옮긴다(흐름도의 `diff_changes` 설명 + 내려받기 절 + "변경 표시는
본문 하이라이트다" 절).

### 이 스텝에서 **안 고치는 것**

- `_ERRORS` 오류표 · `_upstream_kind` · `_post_serving` · `_mcp_call` · `_stream_chunks`(L258).
- **세 guard 를 `asyncio.gather` 로 동시에 부르는 구조** — 호출 목록도 그대로다.
- **`polished_text` 에 태그를 섞지 않는다.** `POST /download` 가 그 값을 그대로 파일로
  만든다 — 섞이면 사용자가 메모장에서 지워야 한다.

---

# 3. `onprem/workflow/sfr018_translate_02_translate.py`

### 본문을 고칠 것 (1줄)

| L | 대상 | 무엇을 |
|---|---|---|
| 475 | `run` — 화면 텍스트 | `display_text = notice + translated` → **`notice + highlighted`** |

**한 줄이지만 이 줄이 기능의 유무를 갈랐다.** `highlighted`(L355)는 원래부터 읽고 있었고
`result` payload 에도 실려 있었다. 그런데 화면에 흘리는 값이 정본이라 **용어사전
하이라이트가 캔버스 채팅에 한 번도 나타나지 않았다.** 사본을 만드는 코드가 다 있으므로
값도 로그도 정상이고, **화면에 없다는 것만이 증상**이다.

L355 자체는 안 고친다(주석의 태그 이름만 `<strong>` → `<mark>`).

### 이 스텝에서 **안 고치는 것**

`translated_markdown`(정본, 내려받기용) · `translated_markdown_highlighted` ·
`translate_pairs` · `glossary` · 전량 폴백 판정 · `numeric_issues` 호출.

---

# 4. `.../office/glossary_report.py` (코드서빙 번역)

### 상수 값만 바꾼다 (2)

| L | 상수 | 전 | 후 |
|---|---|---|---|
| 130 | `_OPEN_TAG` | `"<strong>"` | **`"<mark>"`** |
| 131 | `_CLOSE_TAG` | `"</strong>"` | **`"</mark>"`** |

`highlight_translations`(L134)의 **로직은 한 줄도 안 바뀐다** — 독스트링과 모듈 머리말의
근거만 고친다(`<strong>` 이 왜 부족한지: 원문에도 나오는 표기라 사전 용어인지 원문
강조인지 화면에서 가릴 수 없고, **가리는 것이 요구사항 §2 의 요점**이다).

`build_report` · `term_map`/`term_map_unapplied` 분리 · `hits[].spans`/`target_spans` ·
겹침 병합 · 뒤에서부터 삽입 — 전부 그대로.

---

# 5·6. `api_contract.py` · `.../office/types.py` (같은 단위)

**주석의 태그 이름만 고친다.** 코드는 한 줄도 안 바뀐다.

| 파일 | L | 무엇 |
|---|---|---|
| `api_contract.py` | 144, 167 | `markdown_payload` 주변 주석 — "사전 용어에 `<strong>`" → "`<mark>`(형광)" |
| `office/types.py` | 105~107 | `TranslationArtifacts.markdown_highlighted` 주석 |

**두 파일을 건너뛰어도 동작은 같다.** 그래도 옮기는 이유: 주석이 옛 태그를 가리키면
다음 사람이 `_OPEN_TAG` 를 `<strong>` 으로 "고쳐" 되돌린다.

---

# 손대지 않는 것 (명시)

| 대상 | 이유 |
|---|---|
| MCP 나머지 3파일 (`genon_lang_policy`·`genon_glossary`·`genon_hwpx_text`) | 이 변경과 무관 |
| 워크플로우 나머지 7스텝 | `diff_changes` 를 부르는 스텝은 글다듬이-2 하나다 |
| 글다듬이 코드서빙 (`SFR-018_text_polish`) | **변경 산출은 서빙이 아니라 MCP 가 한다.** `/polish` 는 `polished_text` 만 낸다 |
| FAQ·006 코드서빙 | 이 경로를 지나지 않는다 |
| 프롬프트 10파일 | LLM 에 하이라이트를 맡기지 않는다(difflib 결정적 산출) |
| 전처리기 | 적재 경로다 |
| `txt_output.py` 3벌 | **태그는 애초에 정본에 없으므로** 파일 단계에서 지울 것이 없다 |
| eval | 이 지표를 채점하지 않는다 |

---

# 옮긴 뒤 검증

```bash
export PYTHONIOENCODING=utf-8

python onprem/test/check_mcp_tools.py       # 68 → 75건
python onprem/test/check_workflow_run.py    # 74 → 80건
cd SFR-018 && python -m unittest discover -s tests -t .   # 218 → 235건
```

**한 파일만 옮기면 어디가 FAIL 하는지가 갈린다** — 부분 이관이 조용히 통과하지 않는다:

| 빠뜨린 것 | FAIL 하는 판정 |
|---|---|
| 1 (MCP) | `check_mcp_tools` — "span 이 바뀐 낱말을 가리킨다" · "표시용 사본에 `<mark>`" |
| 2 (글다듬이 스텝) | `check_workflow_run` — "화면은 하이라이트 사본" · "표시용 사본 전달" · "변경 좌표 전달" · "하단 변경 목록 없음" |
| 3 (번역 스텝) | `check_workflow_run` — "화면은 하이라이트 사본"(번역) |
| 4 (`_OPEN_TAG`) | SFR-018 unittest — `GlossaryMarkTagTest` 3건 |

**되돌려 FAIL 을 확인한 갈래는 여섯이다** — HTML 태그 토큰화 제거 · 보호 구간 제거 ·
낱말 단위를 문장으로 되돌림 · 화면이 사본을 쓰는가(번역·글다듬이 **각각**) ·
하단 목록 되살림. 전부 이 그물이 잡는 것을 보고 커밋했다.

## 실물에서 확인할 것

**프론트 마크다운 렌더러가 raw HTML 을 허용하는가.** 허용하면 형광이 그대로 나오고,
아니면 프론트가 ① 태그를 걷어내고 자기 스타일을 입히거나 ② `changes[].span`(글다듬이) ·
`hits[].target_spans` + `translate_pairs`(번역)로 직접 칠하면 된다 — **경로가 셋이라
차단 요인이 아니다.** 태그를 바꿔야 하면 상수 2개만 고친다.

번역의 `target_spans` 는 **그 유닛 기준**이라(문서 전체 기준이 아니다) 문서 통째로
칠할 때는 ①이 맞다. 원문/번역 대조 뷰라면 ②가 파싱 없이 된다.
