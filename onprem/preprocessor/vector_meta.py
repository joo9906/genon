"""청크 → VDB 적재 레코드. 기존 전처리기의 `GenOSVectorMeta` 필드에 맞춘다.

`onprem/preprocessor/README.md` 를 먼저 볼 것. 아직 어디에도 배선돼 있지 않다.

## 왜 필드를 맞추나

기존 전처리기(`genos_files/attach_processor.py`)가 이미 이 스키마로 적재하고 있고,
검색 쪽(`quick_search` MCP 도구)이 `file_name`·`file_path`·`i_page`·`i_chunk_on_doc` 를
읽어 출처 표시에 쓴다. **필드 이름이 어긋나면 같은 컬렉션에 못 넣는다.**

여기서는 `pydantic` 모델을 만들지 않고 **dict 를 낸다.** 이 패키지는 배포 단위가 아니라
아직 붙일 곳이 정해지지 않은 부품이라, 의존을 늘리지 않는 편이 합칠 때 자유롭다.
합치는 쪽에서 `GenOSVectorMeta(**record)` 로 감싸면 된다 (`extra='allow'` 라 통과한다).

## 채울 수 없는 필드는 비워 둔다

hwpx 직접 파싱에는 **페이지도 bbox 도 없다.** 흐름 문서라 렌더링 전에는 페이지가
정해지지 않기 때문이다. 그래서 이렇게 둔다:

| 필드 | 값 | 이유 |
|---|---|---|
| `i_page`·`e_page`·`n_page` | `None` | 알 수 없다. **틀린 페이지 번호는 없는 것보다 나쁘다** |
| `i_chunk_on_page`·`n_chunk_of_page` | `None` | 페이지가 없으니 페이지 안 순번도 없다 |
| `chunk_bboxes` | `None` | 좌표는 PDF 렌더 결과에서만 나온다 |
| `media_files` | `None` | 이 경로는 이미지/첨부를 뽑지 않는다 |

대신 `i_section`·`n_section`·`source_kind`·`table_part` 를 **추가로** 싣는다.
`GenOSVectorMeta.Config.extra = 'allow'` 라 그대로 통과한다.

**페이지가 꼭 필요하면** PDF 변환(`genon.preprocessor.converters.hwp_to_pdf`)을 거친
기존 경로를 써야 한다. 그 경로는 표 안 수치가 깨질 수 있다(요구사항 §5) — 그래서 둘 중
하나를 고르는 것이지, 이 모듈이 페이지를 흉내 내서는 안 된다.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _counts(text: str) -> dict:
    """`n_char`/`n_word`/`n_line`. 기존 전처리기와 같은 이름·같은 세는 법."""
    return {
        "n_char": len(text),
        "n_word": len(text.split()),
        "n_line": len(text.splitlines()) or 1,
    }


def to_records(
    chunks: list,
    *,
    file_name: str = "",
    file_path: str = "",
    section_count: int = 0,
    reg_date: str = "",
    extra: dict = None,
) -> list:
    """청크 목록 → VDB 레코드(dict) 목록.

    Args:
        chunks: `chunking.chunk_blocks` 산출물.
        file_name: 원본 파일명 (검색 결과 출처 표시에 쓰인다).
        file_path: 원본 경로.
        section_count: 문서의 섹션 수 (`n_section`).
        reg_date: 적재 일시. 비우면 지금 시각(로컬 타임존)을 쓴다.
        extra: 모든 레코드에 함께 실을 값 (`security_level` 등 배포별 필드).

    Returns:
        `GenOSVectorMeta` 필드 이름을 쓰는 dict 목록.
        `i_chunk_on_doc`/`n_chunk_of_doc` 는 여기서 매긴다 — 호출부가 매기면 문서를
        나눠 처리할 때 번호가 겹친다.
    """
    stamp = reg_date or datetime.now(timezone.utc).astimezone().isoformat()
    total = len(chunks)
    records = []

    for index, chunk in enumerate(chunks):
        record = {
            "text": chunk.text,
            **_counts(chunk.text),
            # 페이지 관련은 전부 None — 위 docstring 참고
            "i_page": None,
            "e_page": None,
            "n_page": None,
            "i_chunk_on_page": None,
            "n_chunk_of_page": None,
            "i_chunk_on_doc": index,
            "n_chunk_of_doc": total,
            "reg_date": stamp,
            "chunk_bboxes": None,
            "media_files": None,
            # ── 이 경로에만 있는 것 (extra='allow' 로 통과한다) ──
            "file_name": file_name,
            "file_path": file_path,
            "i_section": chunk.section,
            "n_section": section_count,
            # 검색 결과를 표로 보여줄지 문단으로 보여줄지 UI 가 고를 근거
            "source_kind": chunk.kind,
        }
        if chunk.table_part is not None:
            part_index, part_total = chunk.table_part
            # 표가 쪼개졌다는 사실을 숨기지 않는다 — 조각만 보고 "표가 이게 전부" 라고
            # 읽으면 안 된다.
            record["table_part"] = part_index
            record["n_table_part"] = part_total
        if extra:
            record.update(extra)
        records.append(record)

    return records
