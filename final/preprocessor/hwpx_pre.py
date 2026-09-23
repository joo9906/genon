"""hwpx 전용 — 청크 **위치 정보**만 뽑는 최소 스크립트.

**등록 단위가 아니다.** GenOS 에 올리는 건 `final_preprocessor.py`(적재용)와
`only_me.py`(첨부용) 둘뿐이고, 이 파일은 그 둘이 이미 계산해 두는 위치 필드
(`i_chunk_on_doc`·`i_section`·`i_page`·`i_chunk_on_page`·`page_basis` 등)를 hwpx
파일 하나에 대해 빠르게 눈으로 확인하려는 로컬 도구다.

**새 hwpx 파서를 안 만든다.** hwpx 파싱 코어는 이미 다섯 벌(006·번역·FAQ·MCP·
전처리기)이고, 갈리면 `check_table_grid.py` 가 대조할 사본이 하나 더 늘어난다.
그래서 여기서는 `final_preprocessor.py`(PART 2, 정본)의 `parse`/`annotate_outline`/
`chunk_blocks`/`to_records` 를 **그대로 import** 한다 — `__init__.py` 가 로컬
테스트용으로 재노출하는 것과 같은 방식이고, 만드는 건 "위치 필드만 추려 보여주는"
얇은 껍데기뿐이다. 벤더(첨부용) 경로·라우터는 필요 없다(hwpx 만 다룬다).

**"페이지"는 진짜 렌더링된 페이지가 아니라 구역(section)이다** — 2026-09-03 결정
그대로다. hwpx 는 흐름 문서라 저장 시점엔 페이지 좌표가 없다(`lineSegArray`·
`vertpos`·표 앵커(`hp:pos`) 전부 실물로 확인해봤지만 페이지 절대좌표를 담지
않는다). `page_basis="section"` 이 그 출처를 밝힌다. 근거는 `final_preprocessor.py`
"페이지 자리를 **비워 두면 GenOS 화면에 안 뜬다**" 절.

사용법::

    python hwpx_pre.py 파일.hwpx
    python hwpx_pre.py 파일.hwpx --json

모듈로 쓸 때::

    from hwpx_pre import build_records, position_summary
    records = build_records("파일.hwpx")
    for row in position_summary(records):
        print(row)
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys

# `final_preprocessor.py` PART 1 이 import 시점에 `fitz`(PyMuPDF 호환 모듈)를 불러오는데,
# 그 모듈이 **stdout 에 `print()`로** 사용 중단 경고를 찍는다(파이썬 `warnings` 가 아니라
# 그냥 print 라 `2>/dev/null` 로 안 걸러진다). `--json` 출력 맨 앞에 그 줄이 섞이면 JSON
# 파싱이 깨지므로, import 하는 동안만 stdout 을 잠깐 막는다 — 이 스크립트 자체의 출력에는
# 손대지 않는다(import 문 한 줄만 감싼다).
with contextlib.redirect_stdout(io.StringIO()):
    try:  # 패키지로 import 될 때(`from preprocessor import hwpx_pre`)
        from .final_preprocessor import (
            ChunkOptions,
            HwpxParseError,
            annotate_outline,
            chunk_blocks,
            parse,
            to_records,
        )
    except ImportError:  # 스크립트로 직접 실행될 때(`python hwpx_pre.py ...`) — 패키지
        # 컨텍스트가 없어 상대 import 가 실패하므로, 같은 디렉토리에서 절대 import 한다.
        from final_preprocessor import (  # type: ignore[no-redef]
            ChunkOptions,
            HwpxParseError,
            annotate_outline,
            chunk_blocks,
            parse,
            to_records,
        )

# 청크 정본 텍스트가 아니라 "무슨 청크인지 알아볼 정도"만 보여주는 미리보기 길이.
_PREVIEW_CHARS = 40

# 이 필드만 있으면 "청크가 문서의 어디에 있는지" 를 전부 말할 수 있다. `to_records`
# 가 이미 내는 값을 그대로 추린 것이지 새로 계산하는 값은 없다.
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

# "document" 모드(공문서 사다리)만 청크 경계 레벨이 다르다 — 조문 레벨(5)로 끊으면
# 공문서 항목이 전부 다섯 단계에서 끊겨 항목 하나가 청크 하나가 된다. 이 상수는
# `final_preprocessor.py` 의 `_DOC_BREAK_LEVEL` 과 같은 값이다(그쪽이 정본).
_DOC_BREAK_LEVEL = 2

# `estimate_pages` 의 기본 "페이지당 글자수". 실측으로 뽑은 값이 아니라 그냥 적당한
# 추정 상수다 — 정확도가 필요하면 `--chars-per-page` 로 문서에 맞춰 조정한다.
_DEFAULT_CHARS_PER_PAGE = 1200


def build_records(
    file_path: str,
    *,
    outline_mode: str = "auto",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    file_name: str | None = None,
) -> list[dict]:
    """hwpx 파일 하나 → 위치 필드가 채워진 레코드 목록.

    `final_preprocessor.HwpxDocumentProcessor._process` 와 같은 파이프라인이다
    (파싱 → 위계 주석 → 청킹 → 레코드화). 벤더 경로(첨부용)·확장자 라우팅은 없다 —
    hwpx 가 아니면 예외를 던진다.
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

    document = parse(hwpx_bytes)
    if not document.blocks:
        raise HwpxParseError(
            f"본문 내용을 찾지 못했습니다(빈 문서이거나 지원하지 않는 구조): {base_name}"
        )

    options = ChunkOptions(
        max_chars=chunk_size if chunk_size is not None else ChunkOptions.max_chars,
        overlap_chars=(
            chunk_overlap if chunk_overlap is not None else ChunkOptions.overlap_chars
        ),
        outline_break_level=(
            _DOC_BREAK_LEVEL if outline_mode == "document" else ChunkOptions.outline_break_level
        ),
    )
    blocks = annotate_outline(document.blocks, outline_mode)
    chunks = chunk_blocks(blocks, options)
    if not chunks:
        raise HwpxParseError(f"청크를 만들지 못했습니다: {base_name}")

    return to_records(
        chunks,
        file_name=file_name or base_name,
        file_path=file_path,
        section_count=document.section_count,
    )


def estimate_pages(records: list[dict], chars_per_page: int = _DEFAULT_CHARS_PER_PAGE) -> list[dict]:
    """`i_page`/`e_page`/`n_page`/`i_chunk_on_page`/`n_chunk_of_page`/`page_basis` 를
    **구역(section) 대신 누적 글자수 기준 추정치**로 덮어쓴다. `records` 를 그 자리에서
    고치고 그대로 돌려준다.

    **표 안이라고 안 쪼개는 게 아니다.** 표든 본문이든 `n_char` 를 그냥 누적해서 문턱을
    넘으면 페이지를 하나 늘린다 — 표 하나가 통째로 한 구역(=한 페이지)에 묶여 청크가
    수십 개라도 전부 `i_page` 가 같던 문제(구역 대체값의 한계)가 이걸로 풀린다. 대신
    **진짜 페이지가 아니라 추정치다** — 실측 렌더링 없이 "글자수 ÷ 문턱" 으로 지어낸
    값이라 표 셀처럼 글자 밀도가 다른 구간에서는 실제 페이지와 어긋날 수 있다.

    **그래서 `page_basis` 에 문턱값을 그대로 박아 넣는다**(`"estimated:1200chars"`).
    `"section"` 과 절대 같은 문자열이 되지 않게 하려는 것 — 이 값을 읽는 쪽이 "구역
    대체값" 과 "글자수 추정값" 을 같은 신뢰도로 다루면 안 된다.

    **구역 경계는 그대로 존중한다.** 구역이 바뀌면 글자수 문턱에 안 닿았어도 페이지를
    새로 연다 — 구역은 hwpx 가 실제로 갖는 경계라(추정이 아니다) 뭉개면 안 된다.
    """
    page = 0
    chars_in_page = 0
    last_section = object()  # 첫 레코드가 무조건 "구역이 바뀌었다" 로 걸리게 하는 sentinel
    for record in records:
        section = record.get("i_section")
        if section != last_section or chars_in_page >= chars_per_page:
            page += 1
            chars_in_page = 0
        record["i_page"] = page
        record["e_page"] = page
        chars_in_page += record.get("n_char", 0)
        last_section = section

    n_page = max((record["i_page"] for record in records), default=1)
    counts: dict[int, int] = {}
    for record in records:
        counts[record["i_page"]] = counts.get(record["i_page"], 0) + 1

    seen: dict[int, int] = {}
    basis = f"estimated:{chars_per_page}chars"
    for record in records:
        current_page = record["i_page"]
        record["n_page"] = n_page
        record["i_chunk_on_page"] = seen.get(current_page, 0)
        seen[current_page] = seen.get(current_page, 0) + 1
        record["n_chunk_of_page"] = counts[current_page]
        record["page_basis"] = basis
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
    header = f"{'doc':>7} {'section':>9} {'page':>10} {'on_page':>9} {'basis':>9}  preview"
    print(header)
    print("-" * len(header))
    for row in rows:
        doc = f"{row['i_chunk_on_doc']}/{row['n_chunk_of_doc']}"
        section = f"{row['i_section']}/{row['n_section']}"
        page = f"{row['i_page']}~{row['e_page']}/{row['n_page']}"
        on_page = f"{row['i_chunk_on_page']}/{row['n_chunk_of_page']}"
        print(
            f"{doc:>7} {section:>9} {page:>10} {on_page:>9} "
            f"{row['page_basis']:>9}  {row['preview']}"
        )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="hwpx 청크의 위치 정보(문서 순서·구역·페이지 대체값)를 출력한다."
    )
    parser.add_argument("file", help="hwpx 파일 경로")
    parser.add_argument(
        "--outline-mode",
        default="auto",
        choices=("auto", "statute", "document", "off"),
        help="위계 판정 모드 (기본 auto — 조문 표기를 세어서 자동 판정)",
    )
    parser.add_argument("--json", action="store_true", help="전체 레코드를 JSON 으로 출력")
    parser.add_argument(
        "--estimate-pages",
        action="store_true",
        help=(
            "구역(section) 대체값 대신 누적 글자수 기준 추정 페이지를 쓴다 — 표 하나가 "
            "구역 전체를 차지해 모든 청크가 같은 page 로 뭉치는 문제를 완화한다. "
            "**진짜 페이지가 아니라 추정치**이며 page_basis 에 그 사실이 표시된다."
        ),
    )
    parser.add_argument(
        "--chars-per-page",
        type=int,
        default=_DEFAULT_CHARS_PER_PAGE,
        help=f"--estimate-pages 의 페이지당 글자수 문턱 (기본 {_DEFAULT_CHARS_PER_PAGE})",
    )
    args = parser.parse_args(argv)

    try:
        records = build_records(args.file, outline_mode=args.outline_mode)
    except HwpxParseError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.estimate_pages:
        records = estimate_pages(records, chars_per_page=args.chars_per_page)

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        _print_table(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
