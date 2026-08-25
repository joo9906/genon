# 2026-08-23 이관 작업지시 — 파일별·함수별

대상 커밋 **`d174423` "전처리기 일부 수정"** (2026-08-23). **8/21 이후 유일한 커밋**이고
커밋 이름과 달리 전처리기 밖까지 간다. **고칠 파일은 6개**, 그 밖은 손대지 않는다.

**줄 번호는 전부 `d174423`(= 현재 HEAD) 기준**이다. `git show d174423:<경로>` 로 대조할 것.

## 요약 — 파일 6개

| # | 파일 | 등록 단위 | 신규 | 시그니처 | 본문 | 삭제 |
|---|---|---|---|---|---|---|
| 1 | `preprocessor/hwpx_preprocessor.py` | 전처리기 (area 05) | 5 | 0 | 5 | 0 |
| 2 | `mcp/genon_hwpx_text.py` | MCP (4개 중 1개) | 21 | 6 | 2 | 1 |
| 3 | `codeserving/SFR-006_template_fill/template_fill/hwpx_markdown.py` | 코드서빙 006 | 25 | 2 | 1 | 1 |
| 4 | `codeserving/SFR-018_translation/translation_pipeline/office/hwpx_text.py` | 코드서빙 번역 | 21 | 6 | 2 | 1 |
| 5 | `codeserving/SFR-018_faq/faq/hwpx_text.py` | 코드서빙 FAQ | 15 | 6 | 2 | 1 |
| 6 | `codeserving/SFR-018_faq/faq/hwpx_xml.py` | 코드서빙 FAQ (같은 단위) | 6 | 0 | 0 | 1 |

**공개 시그니처는 하나도 안 바뀌었다** — `to_markdown(hwpx_bytes, max_chars=0)`,
`render_markdown(hwpx_bytes, max_chars=None)`, MCP `hwpx_to_markdown` 도구 인자.
**호출부·프롬프트·워크플로우 스텝 9개·MCP 나머지 3파일은 한 줄도 안 고친다.**

**작업 순서**: ① 전처리기부터 (이 층의 **정본**) → ②③④⑤⑥ 사본. 사본 넷은 서로
독립이라 순서 무관하지만, **5와 6은 한 단위라 반드시 같이** 간다(`hwpx_text.py` 가
`hwpx_xml.py` 를 import 한다 — 한쪽만 옮기면 `ImportError` 로 기동이 죽는다).

---

# 1. `onprem/preprocessor/hwpx_preprocessor.py`

두 가지가 섞여 있다 — **②공문서 사다리(신규 기능)** 와 **③`_cell_parts` 중복·
`_boxed_text` 카운터 결함(버그 수정)**. `@idRef` 해석은 8/20 작업이라 **8/21 워킹트리에
이미 있을 수 있다**(`_Markers._resolve` 와 `_ID_NONE` 이 있으면 반영된 것).

### 새로 넣을 함수 (5)

| L | 함수 | 하는 일 |
|---|---|---|
| 683 | `_head_depth(level, levels)` | `hh:heading/@level`(0-based) ↔ `hh:paraHead/@level`(1-based) 를 맞추고, 정의가 없으면 폴백 깊이를 돌려준다 |
| 1172 | `_doc_candidate(stripped)` | 표기를 보기 **전에** 문단 모양으로 거른다 (40자 초과·종결어미면 제목 아님) |
| 1179 | `_doc_ordinal(marker)` | 표기에서 순서값 하나. **표기 문자열만 넘길 것** — 문단 전체를 넘기면 `가. 2025년 계획` 에서 `20` 을 집는다 |
| 1198 | `_document_levels(blocks)` | 문서를 **한 번 먼저 훑어** 실제로 쓰이는 공문서 레벨만 남긴다 (`_DOC_MIN_HITS`·`_DOC_FIRST_ORDINAL` 은 문단 하나로 판정할 수 없다) |
| 1222 | `_match_document(text, levels)` | 공문서 표기 판정. `levels` 에 없는 레벨은 제목으로 안 올린다 |

### 본문을 고칠 것 (5)

| L | 대상 | 무엇을 |
|---|---|---|
| 562 | `class _Markers` | 메서드 **2개 추가** — `_report_once(event, ref)`(폴백 로그를 **문서마다 한 번만**), `_resolve(table, ref, event)`(**id 로 먼저, 없으면 문서 순서 0-based 인덱스**로. `(키, 정의)` 를 돌려준다). `advance()` 는 그 둘을 쓰도록 고치고 `_ID_NONE` 이면 즉시 `""` 반환, **카운터를 `_resolve` 가 준 키로** 든다 |
| 808 | `_cell_parts(tc, markers=None)` | 소유 판정을 `_owning_box` → **`_owning_object`** 로. 표는 상자가 아니라서 중첩 표 셀에서 위로 올라가면 표를 지나쳐 **바깥 셀이 소유자로 잡히고 같은 글자가 두 번 실린다** |
| 1000 | `_boxed_text(tbl, markers=None)` | 중첩 표 판정을 **`_cell_parts` 앞으로** 옮긴다 — `if any(node is not tbl for node in tbl.iter(_TBL)): return None`. `_cell_parts` 는 자동 번호 카운터를 진행시키므로 결과를 보고 표로 되돌아가면 **그 뒤 문서의 번호가 전부 밀린다** |
| 1255 | `annotate_outline(blocks, mode)` | `document` 분기 추가 — `_document_levels` 로 사다리 확정 → 없으면 그대로 반환 → 있으면 **관측 순서대로 1..N 재매김**(`doc_rank`), `path_max` 를 `_DOC_PATH_MAX`(3)로 |
| 2015 | `class DocumentProcessor` | `__call__` 에서 `outline_mode` 를 `.strip().lower()` 로 정규화하고, 청크 경계를 `_DOC_BREAK_LEVEL`(2) / `_LEVEL_ARTICLE`(5) 로 모드에 따라 가른다 |

### 새 모듈 상수

`_OUTLINE_DOCUMENT` · `_OUTLINE_MODES`(4개로) · `_ROMAN_UPPER` · **`_DOCUMENT_RULES`**(7단
사다리) · `_DOC_HEADING_MAX_CHARS=40` · `_DOC_SENTENCE_END` · `_DOC_MIN_HITS=2` ·
`_DOC_FIRST_ORDINAL=1` · `_DOC_BREAK_LEVEL=2` · `_DOC_PATH_MAX=3` ·
`_ID_NONE="4294967295"` · `_BULLET_FALLBACK="-"` · `_NUMBER_FALLBACK_TEMPLATE="^{depth}."`

`Block.outline_level` 독스트링도 고친다 — **문서 모드에서는 뜻이 다르다**(절대 위계가
아니라 그 문서 안에서의 상대 순위).

### 운영 시 확인할 것

**`auto` 는 `document` 를 절대 고르지 않는다.** `_detect_outline_mode` 는 여전히
`제N조` 를 세어 `statute` 아니면 `off` 만 낸다. 공문서에 쓰려면 등록/요청에서
**`outline_mode="document"` 를 명시**해야 한다. 안 넣으면 그전과 동작이 같다.

---

# 2. `onprem/mcp/genon_hwpx_text.py`

**접두어 `_HX` 를 빠뜨리지 말 것** — 한 MCP 서버에 여러 도구 파일이 함께 로드되고
겹치면 나중 것이 앞엣것을 덮는다. 그 실패는 "도구가 이상한 값을 낸다" 로만 드러난다.

### 새로 넣을 함수 (21)

| L | 함수 | 묶음 |
|---|---|---|
| 196 | `_HXread_entry(hwpx_bytes, name)` | ZIP 에서 `Contents/header.xml` 을 꺼낸다 |
| 222 | `_HXinline_text(node)` | **탭·강제 줄바꿈 뒤 글자** — `hp:t` 는 혼합 내용이라 그 글자가 자식의 `tail` 에 있다 |
| 347·355·366 | `_HXcycle` · `_HXroman` · `_HXformat_number` | 번호 서식 (가나다·ⅰⅱⅲ·DIGIT…) |
| 389 | `class _HXMarkers` | `header.xml` 정의 적재 + `advance(para)` + `_resolve` + `_report_once` |
| 508·526·532 | `_HXhead_depth` · `_HXexpand_head` · `_HXmarker_of` | 표시 문자열의 `^N` 을 카운터로 채운다 |
| 537·546·561 | `_HXis_box` · `_HXowning_box` · `_HXowning_object` | **상자 판정은 이름 목록이 아니라 생김새**(`hp:subList` 를 직접 자식으로 두는가) |
| 575·580·598 | `_HXparas_of` · `_HXowned_objects` · `_HXcaptions_of` | 상자 안 문단·문단에 매달린 개체·캡션 |
| 603 | `_HXbox_parts(box, markers=None, inherited="")` | 글상자·각주·머리말 안 글을 펴서 낸다 (라벨 포함) |
| 820·844 | `_HXvertical_key` · `_HXin_visual_order` | 한 문단에 개체가 둘 이상이면 **XML 순서 ≠ 화면 순서** — `hp:pos` 세로 위치로 정렬 |
| 861 | `_HXboxed_text(tbl, markers=None)` | **1칸 표(제목상자)를 표가 아니라 문단으로** |
| 897·922 | `_HXemit_paragraph` · `_HXemit_table` | 블록 조립을 함수로 뺐다 (`hxto_markdown` 본문이 이 둘을 부른다) |

### 인자만 추가할 것 (6) — `markers=None` + 호출부에서 넘기기

`_HXcell_parts`(625) · `_HXcell_text`(660) · `_HXcell_html`(671) ·
`_HXtable_markdown`(755) · `_HXtable_html`(775) · `_HXrender_table`(811).
**셀 안에서도 번호가 이어져야** 하므로 표 렌더 경로 전체에 `markers` 를 태운다.

### 본문을 고칠 것 (2)

| L | 대상 | 무엇을 |
|---|---|---|
| 240 | `_HXown_text(para)` | 글자 출처를 `hp:t` **와 `hp:equation > hp:script`** 둘로. `_HXinline_text` 를 쓰고 `\t` 도 치환 |
| 940 | `hxto_markdown(...)` | 섹션 루프를 다시 짠다 — `markers = _HXMarkers(...)` 한 번 만들고, 상자 안 문단은 건너뛴 뒤 `_HXin_visual_order` 순서로 `_HXemit_paragraph`/`_HXemit_table` 를 부른다. **`owned_tables` 로 표를 묶던 옛 코드는 통째로 없어진다** |

### 지울 것 (1)

`_HXowning_cell(node)` (옛 L186) — `_HXowning_object` 가 대체한다.

### 새 모듈 상수

`_HXPOS` · `_HXHEADER_ENTRY` · `_HXDRAW_TEXT` · `_HXCAPTION` · `_HXFOOT_NOTE` ·
`_HXEND_NOTE` · `_HXPAGE_HEADER` · `_HXPAGE_FOOTER` · `_HXHIDDEN_COMMENT` · `_HXMEMO` ·
`_HXBOX_LABELS` · `_HXSUBLIST` · `_HXEQUATION` · `_HXSCRIPT` · `_HXINLINE_CHARS` ·
**`HXHH_NS`**(머리 네임스페이스) · `_HXHEADING` · `_HXPARA_PR` · `_HXNUMBERING` ·
`_HXPARA_HEAD` · `_HXBULLET` · `_HXHEADING_NUMBERED` · `_HXHEADING_BULLET` ·
`_HXID_NONE` · `_HXBULLET_FALLBACK` · `_HXNUMBER_FALLBACK_TEMPLATE` ·
`_HXHEAD_TOKEN_RE` · `_HXHANGUL_SYLLABLES` · `_HXHANGUL_JAMO` · `_HXROMAN_UNITS`

**`_hx_ensure_packages`(L64)·`_HXint_attr`(L269)는 안 바뀌었다** — 그 아래 상수 블록이
늘어나 diff 가 걸리는 것뿐이다.

### 이 파일에서 **안 고치는 것**

`_HXrender_table` 의 `_needs_html` 판정. 전처리기는 표를 언제나 HTML 로 내지만 **여기는
손실이 있을 때만** 이다. 근거가 다르다 — 평탄화는 RAG 검색 결과를 프롬프트로 조립하는
경로의 일이고, MCP 산출물은 그 경로를 지나지 않는다. **형식을 맞추려고 따라가지 말 것.**

---

# 3. `onprem/codeserving/SFR-006_template_fill/template_fill/hwpx_markdown.py`

**미리보기(읽기) 전용 파일이다.** 006 은 되쓰기 단위라 여기가 제일 헷갈린다 — 아래
"안 고치는 것" 을 먼저 읽을 것.

### 새로 넣을 함수 (25)

2번(MCP)과 같은 21개에서 접두어만 뗀 것 + **006 전용 4개**:

| L | 함수 | 006 에만 있는 이유 |
|---|---|---|
| 564 | `_flatten_table_text(tbl, markers=None)` | **셀 안 중첩 표를 글자로 편다.** 다른 셋은 이때 HTML 로 바꾸는데 006 은 HTML 경로가 없다 — 이게 없으면 **셀 안 표가 통째로 사라진다** |
| 597 | `_table_grid(tbl)` | 격자 계산을 `_render_table` 에서 뗀 것 (`_boxed_text` 도 써야 한다) |
| 166·175·194 | `_read_entry` · `_inline_text` · `_own_text` | `_own_text` 는 **신규**다 — 아래 삭제 항목 참고 |

나머지 21: `_cycle`(269) `_roman`(277) `_format_number`(288) `_Markers`(311)
`_head_depth`(430) `_expand_head`(447) `_marker_of`(453) `_is_box`(458) `_owning_box`(467)
`_owning_object`(477) `_paras_of`(491) `_owned_objects`(496) `_captions_of`(512)
`_box_parts`(517) `_cell_parts`(535) `_boxed_text`(635) `_vertical_key`(686)
`_in_visual_order`(708) `_emit_paragraph`(721) `_emit_table`(743).

### 인자만 추가할 것 (2)

`_cell_text`(582) · `_render_table`(668) — `markers=None`.
(006 은 `_cell_html`·`_table_markdown`·`_table_html` 이 없다. **만들지 말 것.**)

### 본문을 고칠 것 (1)

`render_markdown`(761) — 섹션 루프를 다시 짠다. **`blocks` 의 원소가 문자열에서
`(kind, text)` 튜플로 바뀐다**. 그래서 마지막 `table_count` 도
`sum(1 for kind, _ in blocks if kind == "table")` 로 고쳐야 한다(옛 코드는 루프에서
세었다). `MarkdownResult` 자체는 그대로다.

### 지울 것 (1)

`_para_text(para)` (옛 L75) → **`_own_text` 로 대체**. 이름이 바뀐 이유는 아래.

### 이 파일에서 **안 고치는 것** — 006 에서 제일 위험한 자리

- **`hwpx_fields.py` 는 이번 커밋에 없다. 열지 말 것.** `own_nodes`·`para_text` 는 슬롯
  offset 의 **기준 문자열**을 만든다 — 거기에 조판 문자나 자동 번호를 끼우면 **채울
  자리의 좌표가 밀린다.** 미리보기는 "화면에 보이는 것", 채우기는 "본문 XML 에 있는
  것" 을 봐야 해서 텍스트 조립을 일부러 따로 둔다. `_para_text` → `_own_text` 개명도
  `hwpx_fields.para_text` 와 헷갈리지 않게 하려는 것이다.
- `render_filled` 를 비롯한 쓰기 경로 전부.

---

# 4. `onprem/codeserving/SFR-018_translation/translation_pipeline/office/hwpx_text.py`

### 새로 넣을 함수 (21)

`_read_entry`(172) `_inline_text`(198) `_cycle`(323) `_roman`(331) `_format_number`(342)
`_Markers`(365) `_head_depth`(487) `_expand_head`(505) `_marker_of`(511) `_is_box`(516)
`_owning_box`(525) `_owning_object`(540) `_paras_of`(554) `_owned_objects`(559)
`_captions_of`(577) `_box_parts`(582) `_vertical_key`(799) `_in_visual_order`(823)
`_boxed_text`(840) `_emit_paragraph`(876) `_emit_table`(901).

### 인자만 추가할 것 (6)

`_cell_parts`(604) `_cell_text`(639) `_cell_html`(650) `_table_markdown`(734)
`_table_html`(754) `_render_table`(790) — `markers=None`.

### 본문을 고칠 것 (2)

| L | 대상 | 무엇을 |
|---|---|---|
| 216 | `_own_text(para)` | `hp:t` + `hp:equation > hp:script`, `_inline_text` 사용, `\t` 치환 |
| 919 | `to_markdown(...)` | 섹션 루프 재작성 (2번과 같은 모양). `paragraph_count`·`table_count` 를 루프에서 세던 코드가 없어진다 |

### 지울 것 (1)

`_owning_cell(node)` (옛 L142).

### 새 모듈 상수

`_POS` `_HEADER_ENTRY` `_DRAW_TEXT` `_CAPTION` `_FOOT_NOTE` `_END_NOTE` `_PAGE_HEADER`
`_PAGE_FOOTER` `_HIDDEN_COMMENT` `_MEMO` `_BOX_LABELS` `_SUBLIST` `_EQUATION` `_SCRIPT`
`_INLINE_CHARS` **`HH_NS`** `_HEADING` `_PARA_PR` `_NUMBERING` `_PARA_HEAD` `_BULLET`
`_HEADING_NUMBERED` `_HEADING_BULLET` `_ID_NONE` `_BULLET_FALLBACK`
`_NUMBER_FALLBACK_TEMPLATE` `_HEAD_TOKEN_RE` `_HANGUL_SYLLABLES` `_HANGUL_JAMO`
`_ROMAN_UNITS`

### 로깅 — **여기만 필드 이름이 다르다**

번역·FAQ 의 3.8절 화이트리스트에 `id_ref` 가 **없어서 값이 버려지고 이름만 남는다** —
그러면 "폴백을 밟았다" 는 사실은 남는데 어느 정의에서인지가 사라져 진단이 안 된다.
**`_Markers._report_once` 의 `extra` 를 `resource_id` 로 바꿔서 옮길 것**(문서 안 정의
번호이지 본문 내용이 아니다). MCP·006·전처리기는 화이트리스트가 없어 `id_ref` 그대로다.

---

# 5. `onprem/codeserving/SFR-018_faq/faq/hwpx_text.py`

**6번과 한 세트다.** XML 헬퍼가 `hwpx_xml.py` 에 있으므로 이 파일에 넣는 함수가
넷보다 6개 적다(`_is_box`·`_owning_box`·`_owning_object`·`_paras_of`·`_owned_objects`·
`_captions_of` 가 그쪽으로 간다).

### 맨 먼저 — import 문을 고친다 (L57)

```python
from .hwpx_xml import (
    BOX_LABELS, CAPTION, CELL_ADDR, CELL_SPAN, EQUATION, INLINE_CHARS,
    PARA, POS, SCRIPT, TBL, TC, TEXT, TR,
    captions_of, is_box, nearest_para, owned_objects, owning_object, paras_of,
)
from .logging_utils import log_warning
```
`own_text_nodes` 를 **빼고** 위 이름들을 넣는다. `log_warning` import 도 새로 필요하다.

### 새로 넣을 함수 (15)

`_read_entry`(130) `_inline_text`(146) `_cycle`(266) `_roman`(274) `_format_number`(285)
`_Markers`(308) `_head_depth`(430) `_expand_head`(448) `_marker_of`(454) `_box_parts`(459)
`_vertical_key`(674) `_in_visual_order`(698) `_boxed_text`(715) `_emit_paragraph`(751)
`_emit_table`(776).

### 인자만 추가할 것 (6)

`_cell_parts`(481) `_cell_text`(516) `_cell_html`(527) `_table_markdown`(610)
`_table_html`(630) `_render_table`(665) — `markers=None`.

### 본문을 고칠 것 (2)

`_own_text`(164) · `to_markdown`(794) — 4번과 같은 내용.

### 지울 것 (1)

`_owning_cell(node)` (옛 L126).

### 새 모듈 상수

`_HEADER_ENTRY` **`HH_NS`** `_HEADING` `_PARA_PR` `_NUMBERING` `_PARA_HEAD` `_BULLET`
`_HEADING_NUMBERED` `_HEADING_BULLET` `_ID_NONE` `_BULLET_FALLBACK`
`_NUMBER_FALLBACK_TEMPLATE` `_HEAD_TOKEN_RE` `_HANGUL_SYLLABLES` `_HANGUL_JAMO`
`_ROMAN_UNITS` (나머지 XML 이름은 6번 파일에 있다)

**로깅은 4번과 같다** — `resource_id` 로 싣는다.

---

# 6. `onprem/codeserving/SFR-018_faq/faq/hwpx_xml.py`

### 새로 넣을 함수 (6)

| L | 함수 |
|---|---|
| 100 | `is_box(elem)` — **생김새로 판정**(`hp:subList` 를 직접 자식으로 두는가) |
| 109 | `owning_box(node)` |
| 124 | `owning_object(node)` |
| 138 | `paras_of(box)` |
| 143 | `owned_objects(para)` |
| 161 | `captions_of(obj)` |

### 지울 것 (1)

`own_text_nodes(para)` (옛 L45) — 5번의 `_own_text` 가 `nearest_para` 로 직접 판정한다.

### 새 모듈 상수

`POS` `DRAW_TEXT` `CAPTION` `FOOT_NOTE` `END_NOTE` `PAGE_HEADER` `PAGE_FOOTER`
`HIDDEN_COMMENT` `MEMO` `SUBLIST` `EQUATION` `SCRIPT` `BOX_LABELS` `INLINE_CHARS`
(**밑줄 없는 공개 이름** — 이 파일의 규약이다)

---

# 손대지 않는 것 (명시)

| 대상 | 왜 |
|---|---|
| 워크플로우 스텝 9개 (`onprem/workflow/`) | 한 줄도 안 바뀐다. 재배포 불필요 |
| MCP `genon_text_guard`·`genon_lang_policy`·`genon_glossary` | 이 커밋에 없다 |
| `onprem/prompt/` 네 디렉토리 | 이 커밋에 없다 |
| 006 `hwpx_fields.py`(쓰기 경로) | 슬롯 offset 기준 문자열 — 건드리면 채울 자리가 밀린다 |
| 세 사본의 `_needs_html` 판정 | 전처리기만 언제나 HTML. 근거가 다르다 |
| `onprem/eval/` | 이 커밋에 없다 |

배포 대상이 아닌 변경분(참고용): `test/check_table_grid.py`(그물 18→33건),
`test/diagnose_hwpx_markers.py`(신규 진단 도구), `SFR-018/tests/
test_preprocessor_chunking.py`(103→126건), README·CLAUDE.md 넷.

---

# 옮긴 뒤 검증

```
export PYTHONIOENCODING=utf-8
python onprem/test/check_table_grid.py                              # OK 33 / 33
cd SFR-018 && python -m unittest tests.test_preprocessor_chunking   # 126건
cd SFR-018 && python -m unittest discover -s tests -t .             # 218건
```

`check_table_grid` 가 FAIL 하면 **어느 층이 FAIL 했는지로 범위가 갈린다** — 스크립트가
층별 대상 파일 목록을 직접 찍는다:

| 층 | 대상 | FAIL 이면 |
|---|---|---|
| **[병합표]** | MCP(정본)·번역·FAQ | 표 형식 규칙이 갈렸다 |
| **[단순표]** | 위 셋 + 006 | 격자·이스케이프·폴백이 갈렸다 |
| **[누락 방지]** | 위 넷 + **전처리기(이 층의 정본)** | 글자를 잃었다 |

3층은 ① 네 벌 출력 상호 대조, ② **값 아홉 개를 따로** 확인(상호 대조만으로는 **다섯이
똑같이 잃는 것**을 못 잡는다 — 개요 번호·2단계 번호 서식·글자 없는 번호 문단의 번호
소비·글머리표·**탭 뒤 글자**·수식·본문 글상자·각주·셀 안 글상자), ③ **전처리기의 문단
텍스트와 일치**를 본다.

**번호가 안 붙는 문서를 만나면** 진단 도구를 먼저 돌린다 — `_Markers` 는 값이 없을 때
예외 대신 **빈 표시**를 돌려주므로 증상 하나에 원인이 여러 갈래다:

```
python onprem/test/diagnose_hwpx_markers.py <문서.hwpx>
```

`header.xml` 이 있는가 → 네임스페이스가 맞는가 → 번호 정의·문단 모양이 있는가 →
참조가 이어지는가 순으로 가른다. **문서 발췌를 출력하므로 로그·저장소에 남기지 말 것**(§3.8).

---

# 부록 A — 왜 사본 넷을 건드리나 (한 문단)

전처리기에만 있던 누락 방지 층을 미뤄 둔 근거는 "요청 경로는 사용자가 결과를 눈으로
본다" 였다. **번역에서 성립하지 않는다** — 그쪽은 이 파서의 산출물이 **그대로 번역돼
최종 결과물이 된다.** 대조할 원문이 화면에 없다.

| 단위 | 빠지면 어떻게 보이나 |
|---|---|
| 번역 | 원문에 있던 목록·글상자·각주가 **없는 번역문**을 받는다 |
| FAQ | 그 문장이 **원문에 없는 것으로 취급** — `ungrounded` 기각도 아니라 기각 건수에도 안 잡힌다 |
| MCP | 도구를 부른 LLM 이 원문에 목록이 있었다는 것을 알 방법이 없다 |
| 006 | **파일에는 있는데 화면에만 없다** — "템플릿에 그 내용이 없다" 로 읽힌다 |

1칸 표 문단화(`_boxed_text`)는 처음에 "근거가 검색·임베딩뿐" 이라고 보고 뺐다가 **실물로
돌려 보니 그것 때문에 전처리기와 사본이 갈려서** 도로 넣었다 — 저장소 기술협상서 2벌이
문서 제목을 1칸 표로 담고 있어 사본 쪽에서는 제목이 `| 『…』 |` + `|---|` 로 나갔다.

# 부록 B — 문서가 코드보다 뒤처져 있다

**코드가 맞고 문서가 틀린 자리 셋.** 옮기다 헷갈리면 코드를 믿을 것.

- `preprocessor/README.md` "아직 안 한 것" 에 **공문서 사다리가 여전히 "붙이지 않았다"**
  로 남아 있다. 같은 파일 파라미터 표에는 `document` 가 들어가 있어 **자기모순**이다.
- 루트 `CLAUDE.md` 에 `outline_mode="document"` 언급이 **없다.**
- 파일별 테스트 건수가 낡았다 — `test_preprocessor_chunking` 은 **126건**인데
  `preprocessor/README.md:413` 은 `# 103건`, 루트 `CLAUDE.md:546` 은 `80 → 103건`,
  `@idRef` 절은 `103 → 109건`. (**합계 218건과 `check_table_grid` 33건은 맞다.**)
