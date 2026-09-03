"""onprem/preprocessor — GenOS 통합 전처리기(area 05).

**등록 단위는 `final_preprocessor.py` 한 파일이고, 그 파일이 정본이다.** GenOS
전처리기는 MCP 와 같은 방식으로 파일 하나를 그대로 받아 실행하므로, 그 파일은 이
`__init__.py` 를 포함해 어떤 것도 import 하지 않는다.

이 `__init__.py` 는 로컬 테스트가 `import preprocessor` 로 편하게 쓰기 위한 얇은
재노출이다. 배경·설계 결정·"어느 함수를 고치나" 는 `README.md`.

**이름이 파일 안과 다르다.** 파일 안에서는 PART 1(첨부용)·PART 3(라우터)과 겹치지
않으려고 hwpx 쪽이 `HwpxDocument`·`HwpxDocumentProcessor` 다. 여기서는 hwpx 를 직접
쓰는 테스트가 읽기 쉽도록 `Document`·`HwpxDocumentProcessor` 로 내놓는다 —
`DocumentProcessor` 라는 이름은 **라우터 것**(진입점)이라 그대로 둔다.

```python
from preprocessor import DocumentProcessor, chunk_blocks, parse, to_records

document = parse(hwpx_bytes)                      # hwpx 부품만 쓸 때
chunks = chunk_blocks(document.blocks)
records = to_records(chunks, file_name="사업계획서.hwpx",
                     section_count=document.section_count)

processor = DocumentProcessor()                   # GenOS 가 부르는 진입점(라우터)
records = await processor(request, file_path)
```
"""

from .final_preprocessor import (
    Block,
    Chunk,
    ChunkOptions,
    DocumentProcessor,
    HwpxDocument,
    HwpxDocumentProcessor,
    HwpxParseError,
    annotate_outline,
    chunk_blocks,
    parse,
    to_records,
)

# hwpx 데이터클래스의 옛 이름. 파일 안에서는 langchain `Document` 와 겹쳐 비켜 뒀지만,
# 이 패키지 밖에서는 겹칠 상대가 없다.
Document = HwpxDocument

__all__ = [
    "Block",
    "Chunk",
    "ChunkOptions",
    "Document",
    "DocumentProcessor",
    "HwpxDocument",
    "HwpxDocumentProcessor",
    "HwpxParseError",
    "annotate_outline",
    "chunk_blocks",
    "parse",
    "to_records",
]
