"""onprem/preprocessor — hwpx 파싱 + 청킹 (RAG 적재용).

**아직 어디에도 배선돼 있지 않다.** 나중에 기존 전처리기와 합쳐 VDB 적재에 쓰려고
미리 만들어 둔 부품이다. 배경·합치는 법·한계는 `README.md`.

전형적인 흐름:

```python
from preprocessor import chunk_blocks, parse, to_records

document = parse(hwpx_bytes)
chunks = chunk_blocks(document.blocks)
records = to_records(
    chunks,
    file_name="사업계획서.hwpx",
    section_count=document.section_count,
)
```
"""

from .chunking import Chunk, ChunkOptions, chunk_blocks
from .hwpx import Block, Document, HwpxParseError, parse
from .vector_meta import to_records

__all__ = [
    "Block",
    "Chunk",
    "ChunkOptions",
    "Document",
    "HwpxParseError",
    "chunk_blocks",
    "parse",
    "to_records",
]
