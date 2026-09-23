"""hwpx 전용 — **실제에 가까운 페이지**를 매기는 전처리기.

`hwpx_pre.py` 로 확인한 것: 위치 필드(`i_chunk_on_doc`·`i_section`·`i_page`·
`i_chunk_on_page`·`page_basis` 등)의 배선 자체는 맞다. 이 파일이 바꾸는 것은
**페이지 값을 무엇으로 채우는가** 하나뿐이다.

- `page_basis="section"`(2026-09-03 결정)은 hwpx 가 흐름 문서라 렌더링 전에는 진짜
  페이지가 없다는 사실에서 나온 **대체값**이었다 — 표 하나가 통째로 한 구역을 차지하면
  구역 안 청크 수십 개가 전부 같은 `i_page` 를 받는다.
- 실물 hwpx 를 열어 보면 더 나은 신호가 있다: 표 **밖** 문단은 `hp:linesegarray/
  hp:lineseg/@vertpos` 가 "같은 문단 안에서, 그리고 같은 문단들이 이어지는 동안" 계속
  누적되다가(다음 줄 vertpos = 이전 줄 vertpos + vertsize + spacing) **새 페이지에서
  0 으로 되돌아간다.** 표 **셀**은 각 셀이 저 나름의 독립된 흐름이라 셀마다 vertpos 가
  0 에서 다시 시작하고, 그래서 표 안에서는 이 신호를 쓸 수 없다 — 표는 대신 렌더된
  글자 수를 1000자 단위로 끊어 페이지를 매긴다(그 값이 `ChunkOptions.max_chars` 의
  기본값과 같은 것은 우연이 아니라, 표 조각 하나가 대략 한 페이지 분량이 되게 하려는
  것이다). 그래서 "표는 1000자, 그 외 문단은 vertpos" 로 신호가 갈린다.

**새 hwpx 파서를 만들지 않는다.** 표 격자·상자·자동 번호·tail 처리(2026-08-19~23 에
고친 그 층)는 `final_preprocessor.py`(정본)의 `_emit_paragraph`/`_emit_table` 을 그대로
불러 쓴다 — 이 파일이 더하는 것은 **그 함수들을 최상위 문단 하나씩 불러서, 어느
블록이 어느 문단에서 나왔는지, 그 문단의 vertpos 가 얼마였는지를 짝지어 두는 것**뿐이다.
청킹(`chunk_blocks`)도 그대로 쓴다 — 다만 "페이지가 바뀌는 자리에서도 청크를 끊고
싶다" 는 것 하나를 위해, 청킹 **전에** `Block.section` 자리에 `(진짜 section, 페이지
그룹)` 쌍을 가리키는 정수 하나를 잠깐 넣는다 — `chunk_blocks()` 의 기존 "섹션이
바뀌면 끊는다" 분기를 코드 한 줄 안 고치고 페이지 그룹 경계에도 그대로 태우는
것이다. **실제 페이지 번호(`i_page`/`e_page`)는 그 뒤, 청킹이 끝난 다음에 매긴다** —
표 하나가 몇 "1000자 페이지" 를 차지하는지는 `_table_chunks()` 가 머리말·반복 셀을
붙여 몇 조각으로 쪼갠 뒤에야 알 수 있어서다. 표는 이미 `chunk_blocks()` 가 무조건
표 경계에서 끊으므로 이 인코딩이 실제로 필요한 자리는 문단 사이뿐이다.

**한계 하나를 실물로 확인했다.** `vertpos` 는 한/글이 마지막으로 저장할 때 계산해
둔 **레이아웃 캐시**라, 그 계산 없이 저장된 hwpx 는 `<hp:lineseg>` 자체가 없을 수
있다(실물 5벌 중 훈령 hwpx 한 벌이 그랬다). 그런 문서는 표·상자 신호만 남고
"vertpos==0" 신호가 전혀 없어 예전 구역 기준 대체값과 큰 차이가 안 난다 —
예외를 던지지 않고 **그 구조에서 얻을 수 있는 최선**으로 조용히 떨어진다.

**등록 단위가 아니다.** `final/preprocessor/CLAUDE.md` 가 정한 등록 대상은
`final_preprocessor.py`(첨부용+hwpx 통합)와 `only_me.py`(첨부용 전용) 둘뿐이다 —
이 파일을 GenOS 에 그대로 올리지 않는다.

사용법::

    python only_hwpx.py 파일.hwpx
    python only_hwpx.py 파일.hwpx --json

모듈로 쓸 때::

    from only_hwpx import build_records
    records = build_records("파일.hwpx")
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import sys

# `final_preprocessor.py` PART 1 이 import 시점에 `fitz`(PyMuPDF 호환 모듈)를 불러오는데,
# 그 모듈이 **stdout 에 `print()`로** 사용 중단 경고를 찍는다 — `hwpx_pre.py` 와 같은
# 이유로 import 하는 동안만 막는다.
with contextlib.redirect_stdout(io.StringIO()):
    try:  # 패키지로 import 될 때(`from preprocessor import only_hwpx`)
        from .final_preprocessor import (
            HP_NS,
            ChunkOptions,
            HwpxParseError,
            _DOC_BREAK_LEVEL,
            _HEADER_ENTRY,
            _Markers,
            _PARA,
            _check_record_types,
            _emit_paragraph,
            _iter_section_xml,
            _nearest_para,
            _own_text,
            _parse_xml,
            _read_entry,
            annotate_outline,
            chunk_blocks,
            to_records,
        )
    except ImportError:  # 스크립트로 직접 실행될 때 — 패키지 컨텍스트가 없어 상대
        # import 가 실패하므로, 같은 디렉토리에서 절대 import 한다.
        from final_preprocessor import (  # type: ignore[no-redef]
            HP_NS,
            ChunkOptions,
            HwpxParseError,
            _DOC_BREAK_LEVEL,
            _HEADER_ENTRY,
            _Markers,
            _PARA,
            _check_record_types,
            _emit_paragraph,
            _iter_section_xml,
            _nearest_para,
            _own_text,
            _parse_xml,
            _read_entry,
            annotate_outline,
            chunk_blocks,
            to_records,
        )

# 청크 정본 텍스트가 아니라 "무슨 청크인지 알아볼 정도"만 보여주는 미리보기 길이.
_PREVIEW_CHARS = 40

_POSITION_FIELDS = (
    "i_chunk_on_doc",
    "n_chunk_of_doc",
    "i_section",
    "n_section",
    "i_page",
    "e_page",
    "n_page",
    "i_chunk_on_page",
    "n_chunk_of_page",
    "page_basis",
)

# 표는 이 글자 수마다 페이지 하나로 센다. `ChunkOptions.max_chars` 기본값(1000)과
# 일부러 같다 — 표 조각 하나가 대략 한 페이지 분량이 되게 하려는 값이지, 등록 화면에서
# 청크 크기를 바꾼다고 같이 바뀌어야 하는 값이 아니다. 그래서 `ChunkOptions.max_chars`
# 를 참조하지 않고 **독립 상수**로 둔다.
_TABLE_PAGE_CHARS = 1000

# `hp:p` 의 직접 자식. 표 셀·상자 안 문단은 이 헬퍼를 부르지 않는다 — 그쪽은 저마다
# 독립된 흐름이라 vertpos 가 0 이어도 "새 페이지" 가 아니다.
_LSA = f"{{{HP_NS}}}linesegarray"
_LINESEG = f"{{{HP_NS}}}lineseg"


def _first_vertpos(para) -> int | None:
    """이 문단 **자신**의 첫 줄 `vertpos`. 없으면(개체만 매단 빈 문단 등) `None`.

    실물로 확인한 값: 본문 흐름 문단은 다음 줄의 vertpos 가 `이전 줄 vertpos + vertsize
    + spacing` 으로 이어지다가, 새 페이지의 첫 줄에서 0 으로 되돌아간다. 표 **셀**
    안에서는 셀마다 독립적으로 0 에서 다시 시작하므로(같은 문서에서 실측), 이 값을
    셀 안 문단에 쓰면 "표를 지날 때마다 페이지가 늘어나는" 오검출이 난다 — 이 함수는
    `parse()` 와 같은 필터(`_nearest_para(para) is None`)를 통과한 **최상위** 문단
    에만 부른다.
    """
    lsa = para.find(_LSA)
    if lsa is None:
        return None
    first = lsa.find(_LINESEG)
    if first is None:
        return None
    try:
        return int(first.get("vertpos", ""))
    except (TypeError, ValueError):
        return None


def _forced_break(para) -> bool:
    """한/글의 "쪽 나눔"(수동 페이지/단 나눔)이 걸린 문단인가.

    `python-hwpx` 의 `hwpx-page-guard` 도구가 페이지 드리프트를 비교할 때 쓰는 것과
    같은 속성(`pageBreak`/`columnBreak`)이다 — vertpos 리셋과 달리 **선언된 사실**이라
    오검출이 없다. vertpos 신호에 곁들이는 안전장치이지, 이것만으로 판정하지 않는다
    (자동 줄바꿈으로 넘어간 페이지는 이 속성이 없다).
    """
    return para.get("pageBreak") == "1" or para.get("columnBreak") == "1"


def _gather_blocks_and_hints(hwpx_bytes: bytes):
    """`final_preprocessor.parse()` 와 같은 순회를 하되, 최상위 문단 하나마다 **그
    문단이 낸 블록들**과 **그 문단 자신의 위치 신호**를 짝지어 기록한다.

    `_emit_paragraph`(정본의 렌더링 함수, 그대로 재사용)를 최상위 문단 **하나씩**
    부른다 — `parse()` 처럼 한 번에 전부 부르면 어떤 블록이 어떤 문단에서 나왔는지
    알 방법이 없다. `_Markers` 는 문서 전체에서 하나만 만들어 계속 넘긴다 — 자동
    번호는 누적 상태라 문단마다 새로 만들면 번호가 매번 1부터 다시 센다.

    Returns:
        `(blocks, hints, section_count)`. `hints` 는 `blocks` 와 길이·순서가 같다.
        원소는 `("own", vertpos, forced)`(이 문단 자신의 글) /
        `("table", None, False)`(표) / `("inherit", None, False)`(상자·캡션 등,
        독자적인 흐름이라 페이지를 물려받기만 한다) 셋 중 하나다.
    """
    blocks: list = []
    hints: list = []
    section_count = 0
    markers = _Markers(_read_entry(hwpx_bytes, _HEADER_ENTRY))

    for section_index, (_name, xml_bytes) in enumerate(_iter_section_xml(hwpx_bytes)):
        section_count += 1
        root = _parse_xml(xml_bytes)

        for para in list(root.iter(_PARA)):
            if _nearest_para(para) is not None:
                continue
            own_text = _own_text(para)
            local: list = []
            _emit_paragraph(para, section_index, local, markers)
            if not local:
                continue
            if own_text:
                hints.append(("own", _first_vertpos(para), _forced_break(para)))
                rest = local[1:]
            else:
                rest = local
            for block in rest:
                if block.kind == "table":
                    hints.append(("table", None, False))
                else:
                    hints.append(("inherit", None, False))
            blocks.extend(local)

    return blocks, hints, section_count


def _page_basis(table_page_chars: int) -> str:
    """두 신호를 합쳐 만든 값이라는 사실을 그대로 남긴다 — `"section"` 이나
    `"estimated:1200chars"` 와 절대 같은 문자열이 되면 안 된다(읽는 쪽이 출처를
    혼동한다)."""
    return f"hybrid:table_{table_page_chars}chars+para_vertpos"


def _annotate_block_groups(blocks: list, hints: list) -> list:
    """블록마다 "페이지 그룹" 번호를 낸다. `blocks` 와 길이가 같다.

    **이 값은 아직 페이지 번호가 아니다** — 몇 번째 그룹인지만 말한다. 실제 페이지
    번호(`i_page`/`e_page`)는 `chunk_blocks()` 가 청크를 만든 **뒤**, 청크의 실제
    글자 수로 다시 낸다(`_assign_chunk_pages`). 여기서 페이지 번호까지 미리 정하면
    안 되는 이유는 표 하나다 — 표가 몇 "1000자 페이지" 를 차지할지는 청킹이
    끝나야(`_table_chunks` 가 행을 쪼개며 머리말·반복 셀을 더 붙이므로) 알 수 있다.
    그룹은 "청크 경계를 어디서 더 끊을까" 만 정하면 되므로 그 정보가 필요 없다.

    - **구역(section) 경계는 항상 새 그룹이다** — 구역은 hwpx 가 실제로 갖는 경계라
      추정으로 뭉개지 않는다는 기존 규약(2026-09-03) 그대로다.
    - **표는 항상 자기 그룹**이고, **표 다음 블록도 무조건 새 그룹**이다 — 표 앞뒤
      문단이 표와 페이지를 공유하는 경우가 있어도(짧은 표) 여기서는 표를 페이지
      경계로 다룬다(표는 이미 `chunk_blocks()` 가 무조건 자기 경계에서 끊는 것과
      같은 취급이다).
    - **그 외 문단**("own" 힌트)은 vertpos 가 0 으로 되돌아가거나(자동 줄바꿈으로
      넘어간 페이지) 쪽 나눔이 걸려 있으면(`forced`, 수동 페이지 나눔) 새 그룹이다.
      단, **그 그룹에 아직 아무것도 안 실렸으면** 신호를 무시한다 — 구역/표 직후의
      첫 문단은 vertpos 가 0 이어도 "이미 새 그룹" 이므로 거기서 또 넘기면 빈
      그룹이 생긴다.
    - **상자·캡션("inherit" 힌트)** 은 독자적인 흐름이라(각주·머리말·글상자가 저마다
      다른 vertpos 로 논다) 스스로 그룹을 넘기지 않고, 지금 그룹을 그대로 받는다.
    - **`lineSegArray` 캐시가 아예 없는 문서가 실제로 있다** — 실물 5벌 중 훈령
      hwpx 한 벌은 `<hp:lineseg>` 가 문서 전체에 **0개**였다(마지막으로 저장한
      프로그램이 레이아웃을 계산하지 않고 저장한 것으로 보인다). 그런 문서는
      "own" 힌트의 vertpos 가 전부 `None` 이라 이 신호로는 한 번도 그룹을 못
      넘기고, **표·상자 신호만으로 남는 그룹 수**가 나온다(구역 하나뿐인 문서라면
      최소 1개) — 이전 `page_basis="section"` 대체값의 바닥과 같거나 그보다
      낫다. vertpos 가 없다고 옛 방식보다 나빠지지는 않지만, 이런 문서에서는
      "실제에 가까운 페이지" 라는 이 파일의 장점이 살지 않는다.
    """
    groups: list = []
    group = 0
    current_section = None
    group_has_content = False

    for block, hint in zip(blocks, hints):
        if block.section != current_section:
            current_section = block.section
            if groups:
                group += 1
            group_has_content = False

        if block.is_table:
            if group_has_content:
                group += 1
            groups.append(group)
            group += 1  # 표 다음은 언제나 새 그룹 — 실제 페이지 폭은 청킹 뒤에 정한다.
            group_has_content = False
            continue

        kind, vertpos, forced = hint
        if group_has_content and kind == "own" and (forced or vertpos == 0):
            group += 1
            group_has_content = False

        groups.append(group)
        group_has_content = True

    return groups


def _encode_blocks(blocks: list, groups: list):
    """`(진짜 section, 그룹)` 쌍마다 정수 하나를 배정해 `block.section` 자리에 넣는다.

    `chunk_blocks()` 의 "섹션이 바뀌면 끊는다" 분기(`final_preprocessor.py`)를 코드
    한 줄 안 고치고 그룹 경계에도 태우려는 것이다 — 표는 이미 `chunk_blocks()` 가
    무조건 표 경계에서 끊으므로(첨부용·hwpx 공통 규약) 이 인코딩이 실제로 필요한
    자리는 **문단↔문단 전환**뿐이다.

    Returns:
        `(encoded_blocks, id_to_key)`. `id_to_key[synthetic] == (true_section, group)`.
    """
    key_to_id: dict = {}
    encoded: list = []
    for block, group in zip(blocks, groups):
        key = (block.section, group)
        synthetic = key_to_id.setdefault(key, len(key_to_id))
        encoded.append(dataclasses.replace(block, section=synthetic))
    id_to_key = {synthetic: key for key, synthetic in key_to_id.items()}
    return encoded, id_to_key


def _assign_chunk_pages(
    chunks: list, id_to_key: dict, table_page_chars: int = _TABLE_PAGE_CHARS
) -> list:
    """청크마다 `(i_page, e_page)` 를 낸다. `chunks` 와 길이·순서가 같다.

    **한 번의 순방향 훑기로 낸다** — 그룹이 바뀔 때만 표의 **시작 페이지**
    (`table_base_page`)를 새로 잡고, 표 청크는 그 안에서 실제 글자 수
    (`len(chunk.text)`, 머리말·반복 셀이 이미 더해진 값)를 누적해 1000자마다
    시작 페이지 위에 한 페이지씩 더 얹는다. **표 블록의 원문 길이로 미리
    어림잡지 않는다** — `_table_chunks()` 가 조각마다 머리말(`(표 N/19)`)을
    붙이고 넘치는 행은 짧은 칸을 조각마다 반복하므로, 조각들의 글자 수 **합**은
    표 블록의 원문 길이보다 늘 크다. 미리 어림잡으면 실제로 쓴 조각 수보다
    페이지가 모자라 표가 끝난 뒤 문단이 표 한가운데 페이지로 되돌아가는 역행이
    생긴다(고치기 전 실물 문서로 재현했다) — 그래서 표를 다 쓴 뒤에야 "표가
    끝난 페이지" 를 확정하고, 그 값 위에 다음 그룹을 얹는다.

    **`table_base_page` 를 따로 두는 이유.** `page`(다음 그룹이 쌓일 자리)는 표를
    지나는 동안 조각마다 갱신되는데, 그 갱신된 값을 표 안 페이지 계산에 다시 쓰면
    이미 반영한 누적분을 한 번 더 더하는 꼴이 된다(표 조각이 늘수록 페이지가
    제곱으로 튀는 결함으로 실제로 나타났다) — 표의 시작 페이지는 표를 만난
    순간에 한 번만 정하고, 표가 끝날 때까지 그 값을 그대로 기준으로 쓴다.
    """
    result: list = []
    page = 0
    running_table_chars = 0
    table_base_page = 0
    previous_key = None

    for chunk in chunks:
        key = id_to_key[chunk.section]
        if key != previous_key:
            page += 1
            running_table_chars = 0
            table_base_page = page

        if chunk.kind == "table":
            i_page = table_base_page + running_table_chars // table_page_chars
            running_table_chars += len(chunk.text)
            e_page = table_base_page + max(0, running_table_chars - 1) // table_page_chars
            page = e_page  # 다음 그룹이 여기서부터 새로 시작하도록 확정한다.
        else:
            i_page = e_page = page

        result.append((i_page, e_page))
        previous_key = key

    return result


def _apply_real_pages(
    records: list,
    chunks: list,
    id_to_key: dict,
    table_page_chars: int = _TABLE_PAGE_CHARS,
) -> None:
    """`to_records()` 가 채운 **구역 대체값** 페이지 필드 여섯 개를, 표 1000자·문단
    vertpos 로 계산한 실제 값으로 덮어쓴다. `to_records()` 는 그대로 둔다 — 글자 수
    집계·출처(`i_section`/`n_section`)·표 조각 번호·조문 줄기는 이미 맞다.

    `i_chunk_on_page`/`n_chunk_of_page` 는 **시작 페이지(`i_page`) 기준으로** 묶는다.
    표 조각 하나가 여러 페이지에 걸쳐도(`i_page != e_page`) 그 조각은 시작 페이지의
    묶음에 한 번만 들어간다 — 조각을 여러 페이지에 중복으로 세면 화면의 청크 수와
    `n_chunk_of_doc` 가 어긋난다.
    """
    per_chunk_pages = _assign_chunk_pages(chunks, id_to_key, table_page_chars)
    n_page = max((e_page for _i, e_page in per_chunk_pages), default=1)
    basis = _page_basis(table_page_chars)

    per_page_count: dict = {}
    for i_page, _e_page in per_chunk_pages:
        per_page_count[i_page] = per_page_count.get(i_page, 0) + 1

    seen: dict = {}
    for record, (i_page, e_page) in zip(records, per_chunk_pages):
        order = seen.get(i_page, 0)
        seen[i_page] = order + 1
        record["i_page"] = i_page
        record["e_page"] = e_page
        record["n_page"] = n_page
        record["i_chunk_on_page"] = order
        record["n_chunk_of_page"] = per_page_count[i_page]
        record["page_basis"] = basis


def build_records(
    file_path: str,
    *,
    outline_mode: str = "auto",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    file_name: str | None = None,
    reg_date: str = "",
    extra: dict | None = None,
    table_page_chars: int = _TABLE_PAGE_CHARS,
) -> list[dict]:
    """hwpx 파일 하나 → 페이지 필드가 **실제에 가깝게** 채워진 레코드 목록.

    파이프라인은 `final_preprocessor.HwpxDocumentProcessor._process` 와 같다(파싱 →
    위계 주석 → 청킹 → 레코드화) — 다른 것은 청킹 **전**에 블록마다 페이지를 매기고,
    그 값을 `chunk_blocks()` 의 섹션 분기에 실어 보내는 것뿐이다. 벤더 경로(첨부용)·
    확장자 라우팅은 없다 — hwpx 가 아니면 예외를 던진다.
    """
    base_name = os.path.basename(file_path)
    if os.path.splitext(file_path)[1].lower() != ".hwpx":
        raise HwpxParseError(
            f"hwpx 전용 스크립트입니다 — 지원하지 않는 확장자: {base_name}"
        )

    try:
        with open(file_path, "rb") as fh:
            hwpx_bytes = fh.read()
    except OSError as exc:
        raise HwpxParseError(f"파일을 읽지 못했습니다: {base_name}") from exc

    if not hwpx_bytes:
        raise HwpxParseError(f"빈 파일입니다: {base_name}")

    blocks, hints, section_count = _gather_blocks_and_hints(hwpx_bytes)
    if not blocks:
        raise HwpxParseError(
            f"본문 내용을 찾지 못했습니다(빈 문서이거나 지원하지 않는 구조): {base_name}"
        )

    # annotate_outline 은 블록을 새로 만들어 돌려주지만 순서·개수·`.section` 은 그대로
    # 지킨다(outline_level/outline_path 만 채운다) — hints 와의 위치 대응이 유지된다.
    blocks = annotate_outline(blocks, outline_mode)

    groups = _annotate_block_groups(blocks, hints)
    encoded_blocks, id_to_key = _encode_blocks(blocks, groups)

    options = ChunkOptions(
        max_chars=chunk_size if chunk_size is not None else ChunkOptions.max_chars,
        overlap_chars=(
            chunk_overlap if chunk_overlap is not None else ChunkOptions.overlap_chars
        ),
        outline_break_level=(
            _DOC_BREAK_LEVEL if outline_mode == "document" else ChunkOptions.outline_break_level
        ),
    )
    chunks = chunk_blocks(encoded_blocks, options)
    if not chunks:
        raise HwpxParseError(f"청크를 만들지 못했습니다: {base_name}")

    # `to_records()` 는 그대로 두고 `.section` 만 **진짜** 섹션으로 되돌려 넘긴다 —
    # `i_section`/`n_section`·글자 수 집계·표 조각 번호는 여기서 이미 다 맞다.
    decoded_chunks = [
        dataclasses.replace(chunk, section=id_to_key[chunk.section][0]) for chunk in chunks
    ]
    records = to_records(
        decoded_chunks,
        file_name=file_name or base_name,
        file_path=file_path,
        section_count=section_count,
        reg_date=reg_date,
        extra=extra,
    )
    _apply_real_pages(records, chunks, id_to_key, table_page_chars)
    _check_record_types(records)
    return records


def position_summary(records: list[dict]) -> list[dict]:
    """레코드에서 위치 필드 + 짧은 미리보기만 추린다(전문은 `text` 에 그대로 있다)."""
    rows = []
    for record in records:
        row = {key: record.get(key) for key in _POSITION_FIELDS}
        text = record.get("text", "")
        preview = text[:_PREVIEW_CHARS].replace("\n", " ")
        row["preview"] = preview + ("…" if len(text) > _PREVIEW_CHARS else "")
        rows.append(row)
    return rows


def _print_table(records: list[dict]) -> None:
    rows = position_summary(records)
    header = f"{'doc':>7} {'section':>9} {'page':>10} {'on_page':>9} {'basis':<28}  preview"
    print(header)
    print("-" * len(header))
    for row in rows:
        doc = f"{row['i_chunk_on_doc']}/{row['n_chunk_of_doc']}"
        section = f"{row['i_section']}/{row['n_section']}"
        page = f"{row['i_page']}~{row['e_page']}/{row['n_page']}"
        on_page = f"{row['i_chunk_on_page']}/{row['n_chunk_of_page']}"
        print(
            f"{doc:>7} {section:>9} {page:>10} {on_page:>9} "
            f"{row['page_basis']:<28}  {row['preview']}"
        )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "hwpx 청크의 위치 정보(문서 순서·구역·페이지)를 출력한다 — 표는 1000자 "
            "단위, 그 외 문단은 vertpos 리셋 기준으로 실제에 가깝게 페이지를 매긴다."
        )
    )
    parser.add_argument("file", help="hwpx 파일 경로")
    parser.add_argument(
        "--outline-mode",
        default="auto",
        choices=("auto", "statute", "document", "off"),
        help="위계 판정 모드 (기본 auto — 조문 표기를 세어서 자동 판정)",
    )
    parser.add_argument(
        "--table-page-chars",
        type=int,
        default=_TABLE_PAGE_CHARS,
        help=f"표를 페이지로 나누는 글자 수 문턱 (기본 {_TABLE_PAGE_CHARS})",
    )
    parser.add_argument("--json", action="store_true", help="전체 레코드를 JSON 으로 출력")
    args = parser.parse_args(argv)

    try:
        records = build_records(
            args.file,
            outline_mode=args.outline_mode,
            table_page_chars=args.table_page_chars,
        )
    except HwpxParseError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        _print_table(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
