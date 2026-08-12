"""onprem/preprocessor — hwpx 전용 GenOS 전처리기(area 05).

**실제 등록 단위는 `hwpx_preprocessor.py` 한 파일이다.** GenOS 전처리기는 MCP 와 같은
방식으로 파일 하나를 그대로 받아 실행하므로, 그 파일은 이 `__init__.py` 를 포함해
어떤 것도 import 하지 않는다 — 등록 화면에 올리는 것은 `hwpx_preprocessor.py` 뿐이다.

이 `__init__.py` 는 로컬 테스트가 `import preprocessor` 로 편하게 쓸 수 있게 하는
얇은 재노출이다. 배경·설계 결정·한계는 `README.md`.

```python
from preprocessor import DocumentProcessor, chunk_blocks, parse, to_records

document = parse(hwpx_bytes)
chunks = chunk_blocks(document.blocks)
records = to_records(chunks, file_name="사업계획서.hwpx",
                     section_count=document.section_count)

# GenOS 가 실제로 부르는 진입점
processor = DocumentProcessor()
records = await processor(request, file_path)
```
"""

from .hwpx_preprocessor import (
    Block,
    Chunk,
    ChunkOptions,
    Document,
    DocumentProcessor,
    HwpxParseError,
    chunk_blocks,
    parse,
    to_records,
)

__all__ = [
    "Block",
    "Chunk",
    "ChunkOptions",
    "Document",
    "DocumentProcessor",
    "HwpxParseError",
    "chunk_blocks",
    "parse",
    "to_records",
]
