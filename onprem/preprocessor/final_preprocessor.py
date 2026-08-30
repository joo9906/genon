"""GenOS 통합 전처리기 — hwpx 는 우리 파서, 나머지는 형식마다 더 나은 벤더 처리기로.

**이 파일은 생성물이다. 직접 고치지 말 것** — 고칠 자리는 넷 중 하나이고, 고친 뒤
`python onprem/preprocessor/build_final_preprocessor.py` 로 다시 만든다:

| 고칠 것 | 자리 |
|---|---|
| hwpx 파싱·청킹 | `onprem/preprocessor/hwpx_preprocessor.py` |
| 라우팅·폴백·스키마 정렬 | `onprem/preprocessor/router_template.py` |
| pdf/pptx/이미지 처리 | `genos_files/intelligence_processor.py` (GenOS 참조 사본) |
| docx/hwp/오디오/텍스트 처리 | `genos_files/attach_processor.py` (GenOS 참조 사본) |
| 병합 방식·겹침 처리 | `onprem/preprocessor/build_final_preprocessor.py` |

## 왜 한 파일인가

GenOS 전처리기 등록은 **소스 파일 하나**를 받아 그 파일이 정의하는 `DocumentProcessor`
를 실행한다. 서로 import 할 수 없으므로(벤더 원본도 같은 이유로 `convert_to_pdf` 를
자기 안에 복제해 두고 있다) 한 등록에서 세 처리기를 쓰려면 한 파일에 있어야 한다.

## 라우팅 — 형식마다 **덜 잃는 쪽**으로 보낸다

| 입력 | 어디로 | 근거 |
|---|---|---|
| `.hwpx` (내용도 hwpx 컨테이너) | **hwpx 파서** | 표 병합(rowSpan/colSpan)·조문 위계를 지킨다 |
| `.hwp`, `.hml` | 첨부용 | GenosHwp SDK **네이티브**. 지능형은 PDF 로 바꾼다 |
| `.docx` | 첨부용 | `GenosMsWordDocumentBackend` **네이티브**. 지능형은 PDF 변환을 거쳐 표 병합이 깨질 수 있다 |
| `.pdf` | 지능형 | docling layout + TableFormer + OCR + enrichment. 첨부용은 `PyMuPDFLoader` 평문 + 문자 수 분할이라 **표 구조가 통째로 사라진다** |
| `.ppt`, `.pptx` | 지능형 | 둘 다 PDF 변환이지만 지능형이 enrichment 가 많다 |
| `.xlsx`, `.xlsm`, `.csv` | 지능형 | PDF 변환 없이 직접 처리 + tabular 모드 |
| 이미지 | 지능형 | docling OCR |
| `.wav`, `.mp3`, `.m4a` | 첨부용 | Whisper STT. **지능형에는 이 경로가 없다** |
| `.txt`, `.md`, `.json` | 첨부용 | 지능형은 이것들도 PDF 로 바꾼다 |
| 그 외 | 지능형 | 모르는 형식은 PDF 변환 + docling 쪽이 폭넓다 |

**확장자만 보고 보내지 않는다** — `.hwpx` 는 zip 을 열어 실제로 hwpx 컨테이너인지 본다.
이름만 `.hwpx` 인 파일을 우리 파서에 넣으면 예외가 나고 **그 문서는 검색에서 통째로
사라진다.** 벤더로 보내면 표는 덜 정확해도 적재는 된다.

## 합친 순서가 계약이다 — 뒤엣것이 앞엣것을 덮는다

PART 1 첨부용 → PART 2 지능형 → PART 3 hwpx → PART 4 라우터.

첨부용과 지능형이 최상위 이름 **24개를 둘 다 정의**한다. 합치면 전부 지능형 판본이
이기므로, 본문이 같은 것은 지우고(죽은 코드다) 다른 것은 개명해 둘 다 남겼다. 지운
자리·개명한 자리에 `[병합 제거]`·`[병합 개명]` 표식 주석이 있다. 판정 근거와 개수는
`build_final_preprocessor.py` 머리말에 있다.

`Document` 도 겹쳤다 — 첨부용은 langchain 것을 import 하고 hwpx 는 같은 이름의
데이터클래스를 정의한다. hwpx 가 마지막이라 그대로 두면 첨부용의 20개 호출부가
**호출 시점에** 터지므로(import 는 통과한다) hwpx 쪽을 `HwpxDocument` 로 바꿨다.

## 벤더 절반이 없는 환경에서도 이 파일은 import 된다

PART 1·2 는 각각 `try:` 안에 있다. docling·`genon.preprocessor.*` 가 없으면 그 절반만
비활성이 되고 **hwpx 경로는 그대로 돈다.** 비활성 사실은 숨기지 않는다 — 그 엔진으로
가야 할 파일이 들어오면 **사유를 담아 예외를 던진다**(조용히 빈 결과를 내지 않는다).

**주의**: 지운 14개는 지능형 판본을 쓴다. 그래서 **첨부용 경로는 지능형 절반도 함께
적재돼야 돈다.** 라우터가 그것까지 확인하고 실패를 갈라 보고한다.

## 등록 화면에서 더 받는 값

hwpx 경로는 `hwpx_preprocessor.py` 의 값(`chunk_size`·`chunk_overlap`·`outline_mode`·
`file_name`·`extra_metadata`)을, 벤더 경로는 각 원본의 값을 그대로 받는다. 라우터 몫:

| 키 | 기본값 | 의미 |
|---|---|---|
| `hwpx_engine` | `auto` | `auto`=hwpx 파서, 실패하면 첨부용으로 폴백(GenosHwp SDK 네이티브라 지능형보다 덜 잃는다) / `native`=폴백 없음 / `attach`·`intelligent`=hwpx 도 그쪽으로 |
| `route_overrides` | 없음 | `{{".pdf": "attach"}}` 꼴로 확장자별 라우팅을 덮어쓴다 |
| `align_vector_schema` | `true` | hwpx 레코드에 벤더 예약 필드(`title`·`created_date`·`appendix`·`guardrail_categories`)를 채워 **한 컬렉션 안 메타 스키마를 맞춘다** |
| `intelligent_config_path` / `attachment_config_path` | 없음 | 벤더 설정 yaml. 없으면 환경변수 → 벤더 기본 경로 → 이 파일 주변 순으로 찾는다 |

값이 잘못된 타입/범위면 에러를 내지 않고 기본값으로 떨어지되 로그에 남긴다.

## 페이지 번호는 hwpx 경로에 없다

hwpx 는 흐름 문서라 렌더링 전에는 페이지가 정해지지 않는다. 지어내지 않고 `None` 으로
둔다. 페이지·bbox 가 꼭 필요하면 `hwpx_engine="intelligent"` 로 그 문서만 PDF 경로에
태울 수 있고, 그건 표가 깨지는 쪽이다.
"""

from __future__ import annotations

import asyncio
import json
import traceback

# ===========================================================================
# PART 1 — 첨부용 (genos_files/attach_processor.py, 겹침 처리 후)
# ===========================================================================
# 통째로 try 안에 있다. docling/genon 스택이 없는 환경에서도 이 파일이 import 되고
# hwpx 경로가 살아 있어야 하기 때문이다 — 무거운 의존 하나가 빠졌을 때 hwpx 적재까지
# 같이 죽으면 안 되고, 회귀 점검이 로컬(표준 라이브러리 + lxml)에서 이 파일을 태울 수
# 있어야 한다. 실패 사실은 숨기지 않는다 — 라우터가 그대로 드러낸다.
_FP_ATTACH_IMPORT_ERROR = None
_FP_ATTACH_IMPORT_TRACE = ""
try:
    # 첨부용 전처리기 v.2.2.4 (2026-07-30 Release)

    from collections import defaultdict

    import asyncio
    import fitz
    import html
    import json
    import math
    import os
    import pandas as pd
    import pydub
    import re
    import requests
    import shutil
    import subprocess
    import sys
    import threading
    import uuid
    import warnings
    import yaml
    from datetime import datetime
    import logging
    from fastapi import Request

    # [병합 제거] `_log` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:26-26


    # ── 비정상/암호화 파일 사전 감지 (이슈 #278/#307) ─────────────────────────────
    # intelligent_processor.py 의 동일 블록을 복제한 것. facade 는 단일 파일로 배포되므로
    # import 공유 대신 복제한다. 수정 시 네 파일(intelligent/parser/convert/attachment) 동기화 필요.
    # 지원 포맷의 매직 헤더(allowlist). 각 값은 아래 공식 출처로 근거 확인 + 실제 샘플로 검증함.
    #   - 정본 매직 DB: file/file(libmagic) magic/Magdir — 실제 본 모듈이 쓰는 python-magic의 DB.
    #     (PDF=Magdir/pdf "%PDF-", PNG/GIF=Magdir/images, JPEG=Magdir/jpeg 0xffd8ff, ZIP=Magdir/msooxml "PK\3\4")
    #   - 포맷 공식 스펙: PDF=ISO 32000(%PDF-), PNG=W3C PNG/RFC2083(89 50 4E 47 0D 0A 1A 0A),
    #     ZIP=PKWARE APPNOTE(local file header 0x04034b50), OLE2/CFB=[MS-CFB] §2.2 Header(D0CF11E0A1B11AE1).
    # zip(PK)=docx/xlsx/pptx/hwpx, OLE2(d0cf..)=hwp/doc/ppt/xls(레거시).
    # [병합 제거] `_KNOWN_MAGIC_PREFIXES` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:38-55

    # 텍스트로 봐줄 수 없는 제어 바이트(탭/개행/CR/FF 제외). 텍스트 파일엔 거의 없음.
    # [병합 제거] `_TEXT_ALLOWED_CTRL` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:58-58


    # [병합 제거] `_looks_like_text` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:61-74


    # [병합 제거] `_is_encrypted_pdf` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:77-84


    # [병합 제거] `_is_encrypted_office` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:87-101


    # [병합 제거] `_is_protected_hwp` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:104-126


    # [병합 제거] `_detect_unsupported_file` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:129-171


    from glob import glob
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.document_loaders import (
        # TextLoader,                       # TXT
        PyMuPDFLoader,  # PDF
        DataFrameLoader,  # DataFrame
        UnstructuredWordDocumentLoader,  # DOC and DOCX
        UnstructuredPowerPointLoader,  # PPT and PPTX
        UnstructuredImageLoader,  # JPG, PNG
        UnstructuredMarkdownLoader,  # Markdown
        UnstructuredFileLoader,  # Generic fallback
    )
    from langchain_core.documents import Document
    from markdown2 import markdown
    from pandas import DataFrame
    from pathlib import Path
    from pydantic import BaseModel, ConfigDict, PositiveInt, TypeAdapter, model_validator
    from typing import Any, Iterable, Iterator, List, Optional, Union
    from typing_extensions import Self

    try:
        import semchunk
        from transformers import AutoTokenizer, PreTrainedTokenizerBase
    except ImportError:
        raise RuntimeError(
            "Module requires 'chunking' extra; to install, run: "
            "`pip install 'docling-core[chunking]'`"
        )
    try:
        import chardet
    except ImportError:
        raise RuntimeError("Module 'chardet' not imported. Run `pip install chardet`.")
    try:
        from weasyprint import HTML
    except ImportError:
        print("Warning: WeasyPrint could not be imported. PDF conversion features will be disabled.")
        HTML = None

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PipelineOptions, PdfPipelineOptions
    from docling.datamodel.document import ConversionResult, InputDocument
    from docling.pipeline.simple_pipeline import SimplePipeline
    from docling.document_converter import (
        DocumentConverter, HwpxFormatOption, WordFormatOption, PdfFormatOption,
    )
    from genon.preprocessor.facade.enrichment.page_description import (
        PageDescriptionOptions,
        describe_pages,
    )
    from docling_core.transforms.chunker import BaseChunk, BaseChunker, DocChunk, DocMeta
    from docling_core.types import DoclingDocument as DLDocument
    from docling_core.types.doc import (
        DocItem, DocItemLabel, DoclingDocument,
        PictureItem, SectionHeaderItem, TableItem, TextItem
    )
    from docling_core.types.doc.document import LevelNumber, ListItem, CodeItem
    from docling.backend.genos_msword_backend import GenosMsWordDocumentBackend
    from docling.backend.genos_hwp_backend import GenosHwpDocumentBackend
    from docling.backend.hwp_backend import HwpDocumentBackend
    from docling.backend.xml.hwpx_backend import HwpxDocumentBackend
    from docling.exceptions import HwpConversionError

    try:
        from genos_utils import upload_files
    except ImportError:
        upload_files = None

    from pathlib import Path
    import os
    import subprocess
    import tempfile
    import shutil
    import unicodedata

    import logging

    for n in ("fontTools", "fontTools.ttLib", "fontTools.ttLib.ttFont"):
        lg = logging.getLogger(n)
        lg.setLevel(logging.CRITICAL)
        lg.propagate = False
        logging.getLogger().setLevel(logging.WARNING)
    # pdf 변환 대상 확장자
    CONVERTIBLE_EXTENSIONS = ['.hwp', '.txt', '.json', '.md', '.ppt', '.pptx', '.docx']

    _DEFAULT_TOKENIZER_LOCAL_PATH = "/models/doc_parser_models/sentence-transformers-all-MiniLM-L6-v2"
    _DEFAULT_TOKENIZER_ID = "sentence-transformers/all-MiniLM-L6-v2"
    _DEFAULT_HYBRID_MAX_TOKENS = int(1e30)


    # [병합 개명] `_warn_unresolved_placeholders` → `_at_warn_unresolved_placeholders` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    def _at_warn_unresolved_placeholders(cfg: dict, config_path: str) -> None:
        """config 에 남아있는 미치환 플레이스홀더(<UPPER_SNAKE>)를 탐지해 경고한다.

    Site 배포 시 Whisper endpoint 등의 치환 누락을 조기에 드러내기 위함.
    fail-fast 하지 않고(기동 보존) WARNING 로그만 남긴다.
    """
        pattern = re.compile(r"<[A-Z0-9_]+>")
        found = []

        def _scan(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    _scan(v, f"{path}.{k}" if path else str(k))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    _scan(v, f"{path}[{i}]")
            elif isinstance(node, str):
                for ph in pattern.findall(node):
                    found.append((path, ph))

        _scan(cfg, "")
        if found:
            lines = "\n".join(f"  - {path}: {ph}" for path, ph in found)
            _log.warning(
                "[DocumentProcessor] 미치환 설정 플레이스홀더가 발견되었습니다 "
                f"(config='{config_path}'). Site 배포 시 실제 값으로 변경하세요:\n{lines}"
            )


    # [병합 개명] `_load_config` → `_at_load_config` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    def _at_load_config(config_path: str) -> dict:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            _log.warning(f"[DocumentProcessor] Config file not found: {config_path}. Using defaults.")
            return {}
        except Exception as e:
            _log.warning(f"[DocumentProcessor] Failed to load config '{config_path}': {e}. Using defaults.")
            return {}

        if not isinstance(cfg, dict):
            _log.warning(
                f"[DocumentProcessor] Invalid config format in '{config_path}' "
                f"(expected mapping, got {type(cfg).__name__}). Using defaults."
            )
            return {}
        _at_warn_unresolved_placeholders(cfg, config_path)
        return cfg


    # [병합 제거] `_as_dict` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:313-314


    # [병합 제거] `_parse_optional_bool` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:317-332


    # [병합 제거] `_parse_optional_int` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:335-343


    # [병합 제거] `_parse_optional_float` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:346-354


    def _resolve_default_attachment_config_path() -> str:
        base_dir = Path(__file__).resolve().parent
        local_config = (base_dir / "../resource_dev/attachment_processor_config.yaml").resolve()
        default_config = (base_dir / "../resource/attachment_processor_config.yaml").resolve()

        if local_config.exists():
            return str(local_config)
        return str(default_config)


    # [병합 제거] `_resolve_tokenizer` — intelligent 판본과 **본문이 완전히 같다**(AST 대조).
    #             attach → intelligent 순서라 어차피 intelligent 것이 이겼으므로,
    #             지워도 도는 코드는 그대로다. 원본: attach_processor.py:367-375


    # [병합 개명] `convert_to_pdf` → `at_convert_to_pdf` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    def at_convert_to_pdf(file_path: str, use_pdf_sdk: bool = True) -> str | None:
        """
    PDF 변환을 시도한다. 실패해도 예외를 던지지 않고 None을 반환한다.

    chain (HWP/HWPX 입력):
      use_pdf_sdk=True  → pdf_sdk → rhwp → libreoffice
      use_pdf_sdk=False → rhwp → libreoffice
    chain (그 외 입력, 예: docx/pptx):
      use_pdf_sdk=True  → pdf_sdk → libreoffice
      use_pdf_sdk=False → libreoffice

    rhwp 는 HWP/HWPX 전용이라 비-HWP 입력에는 chain 에 들어가지 않는다. HWP/HWPX
    변환은 rhwp 를 libreoffice 보다 우선한다 (pdf_sdk 가 있으면 그 다음 순위).
    내부 구현은 `genon.preprocessor.converters.hwp_to_pdf` 모듈에 통합되어 있다.
    """
        from genon.preprocessor.converters.hwp_to_pdf import convert_hwp_to_pdf
        # 이슈 #286 — 변환 backend(pdf_sdk/rhwp/libreoffice)가 전무하면(빌드 시 OFF) 변환 시도가
        # 무의미하므로, PDF 직접 입력을 안내하는 warning 한 번만 남기고 None 을 반환한다.
        if not _at_has_any_pdf_converter():
            _log.warning(
                "[convert_to_pdf] PDF 변환기(rhwp/LibreOffice/PDF SDK)가 설치되어 있지 않습니다 "
                f"(이슈 #286). '{os.path.basename(file_path)}' 변환을 건너뜁니다. PDF 로 변환된 "
                "파일을 입력하거나, 변환기를 포함해 전처리기 이미지를 다시 빌드하세요 (genon/README.md 참고)."
            )
            return None
        ext = os.path.splitext(file_path)[1].lower()
        is_hwp = ext in (".hwp", ".hwpx")
        if use_pdf_sdk:
            order = ["pdf_sdk", "rhwp", "libreoffice"] if is_hwp else ["pdf_sdk", "libreoffice"]
        else:
            order = ["rhwp", "libreoffice"] if is_hwp else ["libreoffice"]
        return convert_hwp_to_pdf(file_path, order=order)


    # [병합 개명] `_has_any_pdf_converter` → `_at_has_any_pdf_converter` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    def _at_has_any_pdf_converter() -> bool:
        """PDF 변환 backend(pdf_sdk / rhwp / libreoffice) 가 하나라도 가용한지 확인 (이슈 #286).

    빌드 시 INSTALL_LIBREOFFICE / INSTALL_RHWP 를 끄거나 PDF SDK 미포함(standard)이면
    변환 backend 가 0개가 될 수 있다. 가용성 판단 자체가 불가하면(import 실패 등) True 를
    반환해 기존 동작을 유지한다.
    """
        try:
            from genon.preprocessor.converters.hwp_to_pdf.availability import (
                libreoffice_available,
                pdf_sdk_available,
                rhwp_available,
            )
            return bool(pdf_sdk_available() or rhwp_available() or libreoffice_available())
        except ImportError:
            # facade 단일 파일 실행 등으로 모듈 import 가 안 되는 경우 → 기존 동작 유지(가용 가정)
            return True
        except Exception as exc:
            # 가용성 probe 자체가 예기치 못하게 실패하면 로그만 남기고 파이프라인은 막지 않는다
            _log.warning(f"[_has_any_pdf_converter] PDF 변환기 가용성 확인 실패: {exc}")
            return True


    def _get_pdf_path(file_path: str) -> str:
        """
    다양한 파일 확장자를 PDF 확장자로 변경하는 공통 함수

    Args:
        file_path (str): 원본 파일 경로

    Returns:
        str: PDF 확장자로 변경된 파일 경로
    """
        pdf_path = file_path
        for ext in CONVERTIBLE_EXTENSIONS:
            pdf_path = pdf_path.replace(ext, '.pdf')
        return pdf_path


    def install_packages(packages):
        for package in packages:
            try:
                __import__(package)
            except ImportError:
                _log.warning(f"{package} 패키지가 없습니다. 설치를 시도합니다.")
                subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)
    # 민감정보 분류/마스킹(#315)은 facade/guardrail 모듈로 분리 — gr.* 로 사용.
    from genon.preprocessor.facade import guardrail as gr


    # [병합 개명] `GenOSVectorMeta` → `ATGenOSVectorMeta` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    class ATGenOSVectorMeta(BaseModel):
        class Config:
            extra = 'allow'

        text: str | None = None
        n_char: int | None = None
        n_word: int | None = None
        n_line: int | None = None
        i_page: int | None = None
        e_page: int | None = None
        i_chunk_on_page: int | None = None
        n_chunk_of_page: int | None = None
        i_chunk_on_doc: int | None = None
        n_chunk_of_doc: int | None = None
        n_page: int | None = None
        reg_date: str | None = None
        chunk_bboxes: str | None = None
        media_files: str | None = None
        guardrail_categories: Optional[list] = None    # #315 민감정보 분류 라벨(부동산/인사/민감 등). 미적용 시 None


    # [병합 개명] `GenOSVectorMetaBuilder` → `ATGenOSVectorMetaBuilder` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    class ATGenOSVectorMetaBuilder:
        def __init__(self):
            """빌더 초기화"""
            self.text: Optional[str] = None
            self.n_char: Optional[int] = None
            self.n_word: Optional[int] = None
            self.n_line: Optional[int] = None
            self.i_page: Optional[int] = None
            self.e_page: Optional[int] = None
            self.i_chunk_on_page: Optional[int] = None
            self.n_chunk_of_page: Optional[int] = None
            self.i_chunk_on_doc: Optional[int] = None
            self.n_chunk_of_doc: Optional[int] = None
            self.n_page: Optional[int] = None
            self.reg_date: Optional[str] = None
            self.chunk_bboxes: Optional[str] = None
            self.media_files: Optional[str] = None
            self.guardrail_categories: Optional[list] = None   # #315 민감정보 분류 라벨
            # self.title: Optional[str] = None
            # self.created_date: Optional[int] = None

        def set_guardrail_categories(self, guardrail_categories: Optional[list]) -> "GenOSVectorMetaBuilder":
            """#315 청크 민감정보 분류 라벨 설정 (부동산/인사/민감 등의 list, 미적용 시 None)"""
            self.guardrail_categories = guardrail_categories or None
            return self

        def set_text(self, text: str) -> "GenOSVectorMetaBuilder":
            """텍스트와 관련된 데이터를 설정"""
            self.text = text
            self.n_char = len(text)
            self.n_word = len(text.split())
            self.n_line = len(text.splitlines())
            return self

        def set_page_info(self, i_page: int, i_chunk_on_page: int, n_chunk_of_page: int) -> "GenOSVectorMetaBuilder":
            """페이지 정보 설정"""
            self.i_page = i_page
            self.i_chunk_on_page = i_chunk_on_page
            self.n_chunk_of_page = n_chunk_of_page
            return self

        def set_chunk_index(self, i_chunk_on_doc: int) -> "GenOSVectorMetaBuilder":
            """문서 전체의 청크 인덱스 설정"""
            self.i_chunk_on_doc = i_chunk_on_doc
            return self

        def set_global_metadata(self, **global_metadata) -> "GenOSVectorMetaBuilder":
            """글로벌 메타데이터 병합"""
            for key, value in global_metadata.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            return self

        def set_chunk_bboxes(self, doc_items: list, document: DoclingDocument) -> "GenOSVectorMetaBuilder":
            chunk_bboxes = []
            for item in doc_items:
                for prov in item.prov:
                    label = item.self_ref
                    type_ = item.label
                    size = document.pages.get(prov.page_no).size
                    page_no = prov.page_no
                    bbox = prov.bbox
                    bbox_data = {
                        'l': bbox.l / size.width,
                        't': bbox.t / size.height,
                        'r': bbox.r / size.width,
                        'b': bbox.b / size.height,
                        'coord_origin': bbox.coord_origin.value
                    }
                    chunk_bboxes.append({
                        'page': page_no,
                        'bbox': bbox_data,
                        'type': type_,
                        'ref': label
                    })
            self.e_page = max([bbox['page'] for bbox in chunk_bboxes]) if chunk_bboxes else 0
            self.chunk_bboxes = json.dumps(chunk_bboxes)
            return self

        def set_media_files(self, doc_items: list) -> "GenOSVectorMetaBuilder":
            temp_list = []
            if not doc_items:
                self.media_files = ""
                return self
            for item in doc_items:
                if isinstance(item, PictureItem) and item.image:
                    path = str(item.image.uri)
                    name = path.rsplit("/", 1)[-1]
                    temp_list.append({'name': name, 'type': 'image', 'ref': item.self_ref})
            self.media_files = json.dumps(temp_list)
            return self

        def build(self) -> ATGenOSVectorMeta:
            """설정된 데이터를 사용해 최종적으로 GenOSVectorMeta 객체 생성"""
            return ATGenOSVectorMeta(
                text=self.text,
                n_char=self.n_char,
                n_word=self.n_word,
                n_line=self.n_line,
                i_page=self.i_page,
                e_page=self.e_page,
                i_chunk_on_page=self.i_chunk_on_page,
                n_chunk_of_page=self.n_chunk_of_page,
                i_chunk_on_doc=self.i_chunk_on_doc,
                n_chunk_of_doc=self.n_chunk_of_doc,
                n_page=self.n_page,
                reg_date=self.reg_date,
                chunk_bboxes=self.chunk_bboxes,
                media_files=self.media_files,
                guardrail_categories=self.guardrail_categories,  # #315 민감정보 분류 라벨
            )

    class TextLoader:
        def __init__(self, file_path: str):
            self.file_path = file_path
            self.output_dir = os.path.join('/tmp', str(uuid.uuid4()))
            os.makedirs(self.output_dir, exist_ok=True)

        def load(self):
            try:
                with open(self.file_path, 'rb') as f:
                    raw = f.read()
                enc = chardet.detect(raw).get('encoding') or ''
                encodings = [enc] if enc and enc.lower() not in ('ascii', 'unknown') else []
                encodings += ['utf-8', 'cp949', 'euc-kr', 'iso-8859-1', 'latin-1']

                content = None
                for e in encodings:
                    try:
                        content = raw.decode(e)  # 전체 파일로 디코딩
                        break
                    except UnicodeDecodeError:
                        continue
                if content is None:
                    content = raw.decode('utf-8', errors='replace')

                # 4) PDF 변환 유지
                # <pre> 기본값(white-space: pre)은 자동 줄바꿈을 하지 않아, A4 폭을 넘는 긴 줄이
                # weasyprint 렌더 단계에서 잘려(discard) PDF·청킹에서 누락됨(이슈 #333).
                #  - white-space: pre-wrap  → 원문 줄바꿈/공백 유지 + 폭 초과 시 자동 줄바꿈
                #  - overflow-wrap: anywhere → 공백 없는 초장문(URL 등)도 강제 개행
                #  - html.escape           → <, & 등이 태그로 해석돼 뒤 텍스트가 유실되는 것 방지
                html_doc = (
                    "<html><meta charset='utf-8'><body>"
                    "<pre style='white-space: pre-wrap; overflow-wrap: anywhere;'>"
                    f"{html.escape(content)}</pre></body></html>"
                )
                html_path = os.path.join(self.output_dir, 'temp.html')
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(html_doc)
                # pdf_path = (self.file_path
                #             .replace('.txt', '.pdf')
                #             .replace('.json', '.pdf'))
                pdf_path = _get_pdf_path(self.file_path)
                if HTML:
                    HTML(html_path).write_pdf(pdf_path)
                    loader = PyMuPDFLoader(pdf_path)
                    return loader.load()
                # PDF가 불가하면 Document 직접 반환 (원형 스키마 유지)
                return [Document(page_content=content, metadata={'source': self.file_path, 'page': 0})]

            except Exception:
                # 실패 시에도 스키마는 그대로 유지해 반환
                for e in ['utf-8', 'cp949', 'euc-kr', 'iso-8859-1']:
                    try:
                        with open(self.file_path, 'r', encoding=e) as f:
                            content = f.read()
                        return [Document(page_content=content, metadata={'source': self.file_path, 'page': 0})]
                    except UnicodeDecodeError:
                        continue
                with open(self.file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                return [Document(page_content=content, metadata={'source': self.file_path, 'page': 0})]
            finally:
                if os.path.exists(self.output_dir):
                    shutil.rmtree(self.output_dir)


    class TabularLoader:
        def __init__(self, file_path: str, ext: str, encoding_detect_sample_bytes: int = 10000):
            packages = ['openpyxl', 'chardet']
            install_packages(packages)

            self.file_path = file_path
            self.encoding_detect_sample_bytes = max(int(encoding_detect_sample_bytes), 1)
            if ext == ".csv":
                # convert_to_pdf(file_path) csv는 Pdf 변환 안 함
                self.data_dict = self.load_csv_documents(file_path)
            elif ext == ".xlsx":
                # convert_to_pdf(file_path) xlsx는 Pdf 변환 안 함
                self.data_dict = self.load_xlsx_documents(file_path)
            else:
                _log.warning(f"Inadequate extension for TabularLoader: {ext}")
                return

        def check_sql_dtypes(self, df):
            df = df.convert_dtypes()
            res = []
            for col in df.columns:
                # col_name = col.strip().replace(' ', '_')
                dtype = str(df.dtypes[col]).lower()

                if 'int' in dtype:
                    if '64' in dtype:
                        sql_dtype = 'BIGINT'
                    else:
                        sql_dtype = 'INT'
                elif 'float' in dtype:
                    sql_dtype = 'FLOAT'
                elif 'bool' in dtype:
                    sql_dtype = 'BOOLEAN'
                elif 'date' in dtype:
                    sql_dtype = 'DATE'
                    df[col] = df[col].astype(str)
                elif 'datetime' in dtype:
                    sql_dtype = 'DATETIME'
                    df[col] = df[col].astype(str)
                # else:
                #     max_len = df[col].str.len().max().item() + 10
                #     sql_dtype = f'VARCHAR({max_len})'
                else:
                    lens = df[col].astype(str).str.len()
                    max_len_val = lens.max()
                    max_len = int(0 if pd.isna(max_len_val) else max_len_val) + 10
                    sql_dtype = f'VARCHAR({max_len})'

                res.append([col, sql_dtype])

            return df, res

        def process_data_rows(self, data: dict):
            """Arg: data (keys: 'sheet_name', 'page_column', 'page_column_type', 'documents')"""

            rows = []
            for doc in data["documents"]:
                row = {}
                if 'int' in data["page_column_type"]:
                    row[data["page_column"]] = int(doc.page_content)
                elif 'float' in data["page_column_type"]:
                    row[data["page_column"]] = float(doc.page_content)
                elif 'bool' in data["page_column_type"]:
                    if doc.page_content.lower() == 'true':
                        row[data["page_column"]] = True
                    elif doc.page_content.lower() == 'false':
                        row[data["page_column"]] = False
                    else:
                        raise ValueError(f"Invalid boolean string: {doc.page_content}")
                else:
                    row[data["page_column"]] = doc.page_content

                row.update(doc.metadata)
                rows.append(row)

            processed_data = {"sheet_name": data["sheet_name"], "data_rows": rows, "data_types": data["dtypes"]}
            return processed_data

        def load_csv_documents(self, file_path: str, **kwargs: dict):
            import chardet

            with open(file_path, "rb") as f:
                raw_file = f.read(self.encoding_detect_sample_bytes)
            enc_type = chardet.detect(raw_file)['encoding']
            df = pd.read_csv(file_path, encoding=enc_type, index_col=False)
            df = df.fillna('null')  # csv 파일에서도 xlsx 파일과 동일하게 null로 채움
            df, dtypes_str = self.check_sql_dtypes(df)

            for i in range(len(df.columns)):
                try:
                    col = df.columns[0]
                    # col_type = str(type(col))
                    col_type = str(df[col].dtype)
                    df = df.astype({col: 'str'})
                    break
                except:
                    raise ValueError(
                        f"Any columns cannot be converted into the string type so that can't load LangChain Documents: {dtypes_str}")

            loader = DataFrameLoader(df, page_content_column=col)
            documents = loader.load()

            data = {
                "sheet_name": "table_1",
                "page_column": col,
                "page_column_type": col_type,
                "documents": documents,
                "dtypes": dtypes_str
            }
            data = self.process_data_rows(data)  # including only one sheet as it's a csv file
            data_dict = {"data": [data]}
            return data_dict

        def load_xlsx_documents(self, file_path: str, **kwargs: dict):
            dfs = pd.read_excel(file_path, sheet_name=None)
            sheets = []
            for sheet_name, df in dfs.items():
                df = df.fillna('null')
                df, dtypes_str = self.check_sql_dtypes(df)

                for i in range(len(df.columns)):
                    try:
                        col = df.columns[0]
                        col_type = str(type(col))
                        df = df.astype({col: 'str'})
                        break
                    except:
                        raise ValueError(
                            f"Any columns cannot be converted into string type so that can't load LangChain Documents: {dtypes_str}")

                loader = DataFrameLoader(df, page_content_column=col)
                documents = loader.load()

                sheet = {
                    "sheet_name": sheet_name,
                    "page_column": col,
                    "page_column_type": col_type,
                    "documents": documents,
                    "dtypes": dtypes_str
                }
                sheets.append(sheet)

            data_dict = {"data": []}
            for sheet in sheets:
                data = self.process_data_rows(sheet)
                data_dict["data"].append(data)

            return data_dict

        def return_vectormeta_format(self):
            if not self.data_dict:
                return None

            text = "[DA] " + str(self.data_dict)  # Add a token to indicate this string is for data analysis
            vectors = [ATGenOSVectorMeta.model_validate({
                'text': text,
                'n_char': 1,
                'n_word': 1,
                'n_line': 1,
                'i_page': 1,
                'e_page': 1,
                'n_page': 1,
                'i_chunk_on_page': 1,
                'n_chunk_of_page': 1,
                'i_chunk_on_doc': 1,
                'reg_date': datetime.now().isoformat(timespec='seconds') + 'Z',
                'chunk_bboxes': ".",
                'media_files': "."
            })]
            return vectors


    class AudioLoader:
        def __init__(self,
                     file_path: str,
                     req_url: str,
                     req_data: dict,
                     chunk_sec: int = 29,
                     chunk_overlap_ms: int = 300,
                     tmp_path: str = '.',
                     ):
            self.file_path = file_path
            self.tmp_path = tmp_path
            self.chunk_sec = chunk_sec
            self.chunk_overlap_ms = max(int(chunk_overlap_ms), 0)
            self.req_url = req_url
            self.req_data = req_data

        def split_file_as_chunks(self) -> list:
            audio = pydub.AudioSegment.from_file(self.file_path)
            chunk_len = self.chunk_sec * 1000
            n_chunks = math.ceil(len(audio) / chunk_len)

            for i in range(n_chunks):
                start_ms = i * chunk_len
                overlap_start_ms = start_ms - self.chunk_overlap_ms if start_ms > 0 else start_ms
                end_ms = start_ms + chunk_len
                audio_chunk = audio[overlap_start_ms:end_ms]
                audio_chunk.export(os.path.join(self.tmp_path, "tmp_{}.wav".format(str(i))), format="wav")
            tmp_files = glob(os.path.join(self.tmp_path, "*.wav"))
            return tmp_files

        def transcribe_audio(self, file_path_lst: list):
            transcribed_text_chunks = []

            def _send_request(filepath: str):
                """Send a request to 'whisper' model served"""
                files = {
                    'file': (filepath, open(filepath, 'rb'), 'audio/mp3'),
                }

                response = requests.post(self.req_url, data=self.req_data, files=files)
                text = response.json().get('text', ', ')
                transcribed_text_chunks.append({
                    'file_name': os.path.basename(filepath),
                    'text': text
                })

            # Send parallel requests
            threads = [threading.Thread(target=_send_request, args=(f,)) for f in file_path_lst]
            for t in threads: t.start()
            for t in threads: t.join()

            # Merge transcribed text snippets in order
            transcribed_text_chunks.sort(key=lambda x: x['file_name'])
            transcribed_text = "[AUDIO]" + ' '.join([t['text'] for t in transcribed_text_chunks])
            return transcribed_text

        def return_vectormeta_format(self):
            audio_chunks = self.split_file_as_chunks()
            transcribed_text = self.transcribe_audio(audio_chunks)
            res = [ATGenOSVectorMeta.model_validate({
                'text': transcribed_text,
                'n_char': 1,
                'n_word': 1,
                'n_line': 1,
                'i_page': 1,
                'e_page': 1,
                'n_page': 1,
                'i_chunk_on_page': 1,
                'n_chunk_of_page': 1,
                'i_chunk_on_doc': 1,
                'reg_date': datetime.now().isoformat(timespec='seconds') + 'Z',
                'chunk_bboxes': ".",
                'media_files': "."
            })]
            return res


    ### for HWPX from 지능형 전처리기 ###
    #  * GenOSVectorMetaBuilder     #
    #  * HierarchicalChunker        #
    #  * HybridChunker              #
    #  * HwpxProcessor              #
    #  * GenosServiceException      #

    class HierarchicalChunker(BaseChunker):
        r""" Chunker implementation leveraging the document layout.
    Args:
        merge_list_items (bool): Whether to merge successive list items.
            Defaults to True.
        delim (str): Delimiter to use for merging text. Defaults to "\n".
    """
        merge_list_items: bool = True

        @classmethod
        def _triplet_serialize(cls, table_df: DataFrame) -> str:
            # copy header as first row and shift all rows by one
            table_df.loc[-1] = table_df.columns  # type: ignore[call-overload]
            table_df.index = table_df.index + 1
            table_df = table_df.sort_index()

            rows = [str(item).strip() for item in table_df.iloc[:, 0].to_list()]
            cols = [str(item).strip() for item in table_df.iloc[0, :].to_list()]

            nrows = table_df.shape[0]
            ncols = table_df.shape[1]
            texts = [
                f"{rows[i]}, {cols[j]} = {str(table_df.iloc[i, j]).strip()}"
                for i in range(1, nrows)
                for j in range(1, ncols)
            ]
            output_text = ". ".join(texts)

            return output_text

        def chunk(self, dl_doc: DLDocument, **kwargs: Any) -> Iterator[BaseChunk]:
            r"""Chunk the provided document.
        Args:
            dl_doc (DLDocument): document to chunk

        Yields:
            Iterator[Chunk]: iterator over extracted chunks
        """
            heading_by_level: dict[LevelNumber, str] = {}
            list_items: list[TextItem] = []
            for item, level in dl_doc.iterate_items():
                captions = None
                if isinstance(item, DocItem):
                    # first handle any merging needed
                    if self.merge_list_items:
                        if isinstance(
                                item, ListItem
                        ) or (  # TODO remove when all captured as ListItem:
                                isinstance(item, TextItem)
                                and item.label == DocItemLabel.LIST_ITEM
                        ):
                            list_items.append(item)
                            continue
                        elif list_items:  # need to yield
                            yield DocChunk(
                                text=self.delim.join([i.text for i in list_items]),
                                meta=DocMeta(
                                    doc_items=list_items,
                                    headings=[heading_by_level[k] for k in sorted(heading_by_level)] or None,
                                    origin=dl_doc.origin,
                                ),
                            )
                            list_items = []  # reset

                    if isinstance(item, SectionHeaderItem) or (
                            isinstance(item, TextItem) and item.label in [DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE]):
                        level = (
                            item.level
                            if isinstance(item, SectionHeaderItem)
                            else (0 if item.label == DocItemLabel.TITLE else 1)
                        )
                        heading_by_level[level] = item.text
                        text = ''.join(str(value) for value in heading_by_level.values())

                        # remove headings of higher level as they just went out of scope
                        keys_to_del = [k for k in heading_by_level if k > level]
                        for k in keys_to_del:
                            heading_by_level.pop(k, None)
                        c = DocChunk(
                            text=text,
                            meta=DocMeta(
                                doc_items=[item],
                                headings=[heading_by_level[k] for k in sorted(heading_by_level)] or None,
                                captions=captions,
                                origin=dl_doc.origin
                            ),
                        )
                        yield c
                        continue

                    if isinstance(item, TextItem) or (
                            (not self.merge_list_items) and isinstance(item, ListItem)) or isinstance(item, CodeItem):
                        text = item.text

                    elif isinstance(item, TableItem):
                        text = item.export_to_markdown(dl_doc)
                        # dataframe으로 추출할 때 사용되는 코드
                        # if table_df.shape[0] < 1 or table_df.shape[1] < 2:
                        #     # at least two cols needed, as first column contains row headers
                        #     continue
                        # text = self._triplet_serialize(table_df=table_df)
                        captions = [c.text for c in [r.resolve(dl_doc) for r in item.captions]] or None

                    elif isinstance(item, PictureItem):
                        text = ''.join(str(value) for value in heading_by_level.values())
                    else:
                        continue
                    c = DocChunk(
                        text=text,
                        meta=DocMeta(
                            doc_items=[item],
                            headings=[heading_by_level[k] for k in sorted(heading_by_level)] or None,
                            captions=captions,
                            origin=dl_doc.origin,
                        ),
                    )
                    yield c

            if self.merge_list_items and list_items:  # need to yield
                yield DocChunk(
                    text=self.delim.join([i.text for i in list_items]),
                    meta=DocMeta(
                        doc_items=list_items,
                        headings=[heading_by_level[k] for k in sorted(heading_by_level)] or None,
                        origin=dl_doc.origin,
                    ),
                )


    class HybridChunker(BaseChunker):
        r"""Chunker doing tokenization-aware refinements on top of document layout chunking.
    Args:
        tokenizer: The tokenizer to use; either instantiated object or name or path of
            respective pretrained model
        max_tokens: The maximum number of tokens per chunk. If not set, limit is
            resolved from the tokenizer
        merge_peers: Whether to merge undersized chunks sharing same relevant metadata
    """

        model_config = ConfigDict(arbitrary_types_allowed=True)
        tokenizer: Union[PreTrainedTokenizerBase, str, Path] = (
                Path(_DEFAULT_TOKENIZER_LOCAL_PATH)
                if Path(_DEFAULT_TOKENIZER_LOCAL_PATH).exists()
                else _DEFAULT_TOKENIZER_ID
            )
        max_tokens: int = _DEFAULT_HYBRID_MAX_TOKENS  # type: ignore[assignment]
        merge_peers: bool = True
        # 토큰 수 계산 방식. "char"(default)=문자 수 기준 | "huggingface"=HF 토크나이저 기준
        tokenizer_type: str = "char"
        _inner_chunker: HierarchicalChunker = HierarchicalChunker()

        @model_validator(mode="after")
        def _patch_tokenizer_and_max_tokens(self) -> Self:
            mode = (self.tokenizer_type or "char").strip().lower()
            if mode not in {"char", "huggingface"}:
                _log.warning(f"[HybridChunker] Unknown tokenizer_type '{mode}', fallback to 'char'.")
                mode = "char"
            self.tokenizer_type = mode
            if mode == "char":
                # 문자 수 기반: HF 토크나이저 로드 불필요 (외부 모델 의존 제거)
                self._tokenizer = None
                if self.max_tokens is None:
                    self.max_tokens = _DEFAULT_HYBRID_MAX_TOKENS
            else:
                self._tokenizer = (
                    self.tokenizer
                    if isinstance(self.tokenizer, PreTrainedTokenizerBase)
                    else AutoTokenizer.from_pretrained(self.tokenizer)
                )
                if self.max_tokens is None:
                    self.max_tokens = TypeAdapter(PositiveInt).validate_python(
                        self._tokenizer.model_max_length
                    )
            return self

        def _count_text_tokens(self, text: Optional[Union[str, list[str]]]):
            if text is None:
                return 0
            elif isinstance(text, list):
                total = 0
                for t in text:
                    total += self._count_text_tokens(t)
                return total
            if self._tokenizer is None:   # 문자 수 기반
                return len(text)
            return len(self._tokenizer.tokenize(text))

        class _ChunkLengthInfo(BaseModel):
            total_len: int
            text_len: int
            other_len: int

        def _count_chunk_tokens(self, doc_chunk: DocChunk):
            ser_txt = self.serialize(chunk=doc_chunk)
            if self._tokenizer is None:   # 문자 수 기반
                return len(ser_txt)
            return len(self._tokenizer.tokenize(text=ser_txt))

        def _doc_chunk_length(self, doc_chunk: DocChunk):
            text_length = self._count_text_tokens(doc_chunk.text)
            total = self._count_chunk_tokens(doc_chunk=doc_chunk)
            return self._ChunkLengthInfo(
                total_len=total,
                text_len=text_length,
                other_len=total - text_length,
            )

        def _make_chunk_from_doc_items(
                self, doc_chunk: DocChunk, window_start: int, window_end: int
        ):
            doc_items = doc_chunk.meta.doc_items[window_start: window_end + 1]
            meta = DocMeta(
                doc_items=doc_items,
                headings=doc_chunk.meta.headings,
                captions=doc_chunk.meta.captions,
                origin=doc_chunk.meta.origin,
            )
            window_text = (
                doc_chunk.text
                if len(doc_chunk.meta.doc_items) == 1
                else self.delim.join(
                    [
                        doc_item.text
                        for doc_item in doc_items
                        if isinstance(doc_item, TextItem)
                    ]
                )
            )
            new_chunk = DocChunk(text=window_text, meta=meta)
            return new_chunk

        def _split_by_doc_items(self, doc_chunk: DocChunk) -> list[DocChunk]:
            chunks = []
            window_start = 0
            window_end = 0  # an inclusive index
            num_items = len(doc_chunk.meta.doc_items)
            while window_end < num_items:
                new_chunk = self._make_chunk_from_doc_items(
                    doc_chunk=doc_chunk,
                    window_start=window_start,
                    window_end=window_end,
                )
                if self._count_chunk_tokens(doc_chunk=new_chunk) <= self.max_tokens:
                    if window_end < num_items - 1:
                        window_end += 1
                        # 아직 청크에 여유가 있고, 남은 아이템도 있으므로 계속 추가 시도
                        continue
                    else:
                        # 현재 윈도우의 모든 아이템이 청크에 들어갔고, 더 이상 아이템이 없음
                        window_end = num_items  # signalizing the last loop
                elif window_start == window_end:
                    # 아이템 1개도 청크에 안 들어감 → 단독 청크로 처리, 이후 재분할
                    window_end += 1
                    window_start = window_end
                else:
                    # 마지막 아이템 빼고 청크 생성 → 남은 아이템으로 새 윈도우 시작
                    new_chunk = self._make_chunk_from_doc_items(
                        doc_chunk=doc_chunk,
                        window_start=window_start,
                        window_end=window_end - 1,
                    )
                    window_start = window_end
                chunks.append(new_chunk)
            return chunks

        def _split_using_plain_text(self, doc_chunk: DocChunk) -> list[DocChunk]:
            lengths = self._doc_chunk_length(doc_chunk)
            if lengths.total_len <= self.max_tokens:
                return [doc_chunk]
            else:
                # 헤더/캡션을 제외하고 본문 텍스트에 할당 가능한 토큰 수 계산
                available_length = self.max_tokens - lengths.other_len
                # char 모드는 문자 수 카운터 len 사용
                counter = len if self._tokenizer is None else self._tokenizer
                sem_chunker = semchunk.chunkerify(
                    counter, chunk_size=available_length
                )
                if available_length <= 0:
                    warnings.warn(
                        f"Headers and captions for this chunk are longer than the total amount of size for the chunk, chunk will be ignored: {doc_chunk.text=}"
                        # noqa
                    )
                    return []
                text = doc_chunk.text
                segments = sem_chunker.chunk(text)
                chunks = [type(doc_chunk)(text=s, meta=doc_chunk.meta) for s in segments]
                return chunks

        def _merge_chunks_with_matching_metadata(self, chunks: list[DocChunk]):
            output_chunks = []
            window_start = 0
            window_end = 0  # an inclusive index
            num_chunks = len(chunks)

            while window_end < num_chunks:
                chunk = chunks[window_end]
                headings_and_captions = (chunk.meta.headings, chunk.meta.captions)
                ready_to_append = False

                if window_start == window_end:
                    current_headings_and_captions = headings_and_captions
                    window_end += 1
                    first_chunk_of_window = chunk

                else:
                    chks = chunks[window_start: window_end + 1]
                    doc_items = [it for chk in chks for it in chk.meta.doc_items]
                    candidate = DocChunk(
                        text=self.delim.join([chk.text for chk in chks]),
                        meta=DocMeta(
                            doc_items=doc_items,
                            headings=current_headings_and_captions[0],
                            captions=current_headings_and_captions[1],
                            origin=chunk.meta.origin,
                        ),
                    )

                    if (headings_and_captions == current_headings_and_captions
                            and self._count_chunk_tokens(doc_chunk=candidate) <= self.max_tokens
                    ):
                        # 토큰 수 여유 있음 → 청크 확장 계속
                        window_end += 1
                        new_chunk = candidate
                    else:
                        ready_to_append = True

                if ready_to_append or window_end == num_chunks:
                    # no more room OR the start of new metadata.
                    if window_start + 1 == window_end:
                        output_chunks.append(first_chunk_of_window)
                    else:
                        output_chunks.append(new_chunk)
                    window_start = window_end

            return output_chunks

        def chunk(self, dl_doc: DoclingDocument, **kwargs: Any) -> Iterator[BaseChunk]:
            r"""Chunk the provided document.
        Args:
            dl_doc (DLDocument): document to chunk
        Yields:
            Iterator[Chunk]: iterator over extracted chunks
        """
            res: Iterable[DocChunk]
            res = self._inner_chunker.chunk(dl_doc=dl_doc, **kwargs)  # type: ignore
            res = [x for c in res for x in self._split_by_doc_items(c)]
            res = [x for c in res for x in self._split_using_plain_text(c)]

            if self.merge_peers:
                res = self._merge_chunks_with_matching_metadata(res)
            return iter(res)


    # --- 이슈 #183 / #80 -------------------------------------------------------
    # DoclingDocument를 markdown으로 export한 뒤 RecursiveCharacterTextSplitter로 분할.
    # 페이지 정보는 export_to_markdown(page_break_placeholder=...)로 삽입한 마커를
    # 청크별로 카운트해 복원한다. 한 청크가 여러 페이지에 걸칠 수 있다.
    _RECURSIVE_PAGE_BREAK = "<!-- PB -->"


    def _char_split_text(text: str, chunk_size=None, chunk_overlap=None) -> list[str]:
        """문자수 기반 청킹 공용 헬퍼 (generic/recursive 경로 공유).

    chunk_size 가 0 이하/None 이면 분할하지 않고 전체를 1청크로 둔다.
    chunk_size > 0 이면 RecursiveCharacterTextSplitter 로 문자 단위 분할한다.
    """
        if not text:
            return []

        cs = int(chunk_size) if chunk_size is not None else 0
        co = max(int(chunk_overlap), 0) if chunk_overlap is not None else 100

        if cs > 0:
            # overlap >= size 면 RecursiveCharacterTextSplitter 가 ValueError 로 크래시하므로 size-1 이하로 클램프.
            co = min(co, cs - 1)
            raw_chunks = RecursiveCharacterTextSplitter(
                chunk_size=cs, chunk_overlap=co,
            ).split_text(text)
        else:
            raw_chunks = [text]

        return [c for c in raw_chunks if c]


    def _split_with_recursive_chunker(
        document: DoclingDocument,
        chunk_size=None,
        chunk_overlap=None,
    ) -> List[dict]:
        """Markdown export + 문자수 기반 청킹(_char_split_text)으로 docling 문서를 분할.

    chunk_size 로 문자 분할 (0 이하이면 분할 안 함 = 전체 1청크).

    Returns: list of dict {text, page_no, pages, doc_items}
    """
        md_full = document.export_to_markdown(page_break_placeholder=_RECURSIVE_PAGE_BREAK)
        if not md_full:
            return []

        co = max(int(chunk_overlap), 0) if chunk_overlap is not None else 100
        raw_chunks = _char_split_text(
            md_full,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        # 페이지별 doc_items 캐시 (반복 조회 방지)
        page_items_cache: dict[int, list] = {}

        def _items_for_page(p: int):
            if p not in page_items_cache:
                page_items_cache[p] = [
                    it for it, _ in document.iterate_items(page_no=p)
                    if isinstance(it, DocItem)
                ]
            return page_items_cache[p]

        results: list[dict] = []
        cursor = 0
        search_backoff = max(co * 4, 200)
        for raw in raw_chunks:
            pos = md_full.find(raw, max(0, cursor - search_backoff))
            if pos < 0:
                pos = cursor
            end_pos = pos + len(raw)

            start_page = md_full[:pos].count(_RECURSIVE_PAGE_BREAK) + 1
            end_page = md_full[:end_pos].count(_RECURSIVE_PAGE_BREAK) + 1

            text = raw.replace(_RECURSIVE_PAGE_BREAK, "").strip()
            cursor = end_pos
            if not text:
                continue

            doc_items: list = []
            for p in range(start_page, end_page + 1):
                doc_items.extend(_items_for_page(p))

            results.append({
                "text": text,
                "page_no": start_page,
                "pages": list(range(start_page, end_page + 1)),
                "doc_items": doc_items,
            })

        return results


    class DocxProcessor:
        def __init__(self, tokenizer=None, guardrail_url="", guardrail_workflow_id=None, guardrail_api_key="", guardrail_timeout=30, guardrail_masking_enabled=False):
            # 청킹용 토크나이저 (config 기반; 미지정 시 현행 기본값)
            self._tokenizer = tokenizer if tokenizer is not None else _resolve_tokenizer({})
            # PII 마스킹(#315) 접속 정보 — DocumentProcessor 가 config 에서 읽어 주입.
            self._guardrail_url = guardrail_url
            self._guardrail_workflow_id = guardrail_workflow_id
            self._guardrail_api_key = guardrail_api_key
            self._guardrail_timeout = guardrail_timeout
            self._guardrail_masking_enabled = guardrail_masking_enabled
            self.page_chunk_counts = defaultdict(int)
            self.pipeline_options = PipelineOptions()
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.DOCX: WordFormatOption(
                    pipeline_cls=SimplePipeline, backend=GenosMsWordDocumentBackend
                    ),
                }
            )

        def get_paths(self, file_path: str):
            output_path, output_file = os.path.split(file_path)
            filename, _ = os.path.splitext(output_file)
            artifacts_dir = Path(f"{output_path}/{filename}")
            if artifacts_dir.is_absolute():
                reference_path = None
            else:
                reference_path = artifacts_dir.parent
            return artifacts_dir, reference_path

        def get_media_files(self, doc_items: list):
            temp_list = []
            for item in doc_items:
                if isinstance(item, PictureItem) and item.image:
                    path = str(item.image.uri)
                    name = path.rsplit("/", 1)[-1]
                    temp_list.append({'path': path, 'name': name})
            return temp_list

        def safe_join(self, iterable):
            if not isinstance(iterable, (list, tuple, set)):
                return ''
            return ''.join(map(str, iterable)) + '\n'

        def load_documents(self, file_path: str, **kwargs: dict) -> DoclingDocument:
            conv_result: ConversionResult = self.converter.convert(file_path, raises_on_error=True)
            return conv_result.document

        def split_documents(self, document: DoclingDocument, **kwargs: dict):
            """chunker_type에 따라 HybridChunker 또는 RecursiveCharacterTextSplitter로 분할.

        반환 형식이 chunker_type에 따라 다르다 (DocChunk 리스트 또는 dict 리스트).
        compose_vectors가 동일한 chunker_type 분기로 처리한다.
        """
            # 같은 DocxProcessor 인스턴스가 여러 요청에서 재사용되므로 매 호출마다 초기화
            self.page_chunk_counts = defaultdict(int)
            chunker_type = kwargs.get("chunker_type", "recursive")

            if chunker_type == "recursive":
                recursive_chunk_size = kwargs.get("chunk_size")
                if recursive_chunk_size is None:
                    recursive_chunk_size = kwargs.get("recursive_chunk_size")
                recursive_chunk_overlap = kwargs.get("chunk_overlap")
                if recursive_chunk_overlap is None:
                    recursive_chunk_overlap = kwargs.get("recursive_chunk_overlap")
                chunks = _split_with_recursive_chunker(
                    document,
                    chunk_size=recursive_chunk_size,
                    chunk_overlap=recursive_chunk_overlap,
                )
                for ch in chunks:
                    self.page_chunk_counts[ch["page_no"]] += 1
                return chunks

            # hybrid
            hybrid_chunk_size = _parse_optional_int(kwargs.get("hybrid_chunk_size"), "hybrid_chunk_size")
            if hybrid_chunk_size is None or hybrid_chunk_size <= 0:
                hybrid_chunk_size = _DEFAULT_HYBRID_MAX_TOKENS
            hybrid_merge_peers = _parse_optional_bool(kwargs.get("hybrid_merge_peers"), "hybrid_merge_peers")
            if hybrid_merge_peers is None:
                hybrid_merge_peers = True
            chunker_kwargs = {
                "max_tokens": hybrid_chunk_size,
                "merge_peers": hybrid_merge_peers,
                "tokenizer": self._tokenizer,
                "tokenizer_type": kwargs.get("hybrid_tokenizer_type", "char"),
            }
            chunker = HybridChunker(**chunker_kwargs)
            chunks: List[DocChunk] = list(chunker.chunk(dl_doc=document, **kwargs))
            for chunk in chunks:
                if chunk.meta.doc_items[0].prov:
                    self.page_chunk_counts[chunk.meta.doc_items[0].prov[0].page_no] += 1
            return chunks

        async def compose_vectors(self, document: DoclingDocument, chunks, file_path: str, request: Request,
                                  **kwargs: dict) -> list[dict]:
            chunker_type = kwargs.get("chunker_type", "recursive")
            _sensitive_infos: list = kwargs.get("_sensitive_infos") or []      # #315 분류 결과
            _gr_masking: bool = bool(kwargs.get("_guardrail_masking", False))   # #315 마스킹 치환 on/off

            global_metadata = dict(
                n_chunk_of_doc=len(chunks),
                n_page=document.num_pages(),
                reg_date=datetime.now().isoformat(timespec='seconds') + 'Z',
            )

            current_page = None
            chunk_index_on_page = 0
            vectors = []
            upload_tasks = []
            scheduled_upload_paths = set()  # 청크 간 동일 이미지(헤더 그림 등) 중복 업로드 방지
            for chunk_idx, chunk in enumerate(chunks):
                if chunker_type == "recursive":
                    chunk_page = chunk["page_no"]
                    content = chunk["text"]
                    doc_items = chunk["doc_items"]
                else:
                    chunk_page = chunk.meta.doc_items[0].prov[0].page_no if chunk.meta.doc_items[0].prov else 0
                    content = self.safe_join(chunk.meta.headings) + chunk.text
                    doc_items = chunk.meta.doc_items

                if chunk_page != current_page:
                    current_page = chunk_page
                    chunk_index_on_page = 0

                # #315 가드레일 분류 후처리: quote 매칭 → guardrail_categories 부착(항상) + 마스킹 치환(옵션)
                content, chunk_cats = gr.apply_to_text(content, _sensitive_infos, _gr_masking)

                vector = (ATGenOSVectorMetaBuilder()
                          .set_text(content)
                          .set_page_info(chunk_page, chunk_index_on_page, self.page_chunk_counts[chunk_page])
                          .set_chunk_index(chunk_idx)
                          .set_global_metadata(**global_metadata)
                          .set_chunk_bboxes(doc_items, document)
                          .set_media_files(doc_items)
                          .set_guardrail_categories(sorted(chunk_cats) if chunk_cats else None)
                          ).build()
                vectors.append(vector)

                chunk_index_on_page += 1
                if upload_files:
                    # 동일 이미지(#56 docx 헤더 그림 등)가 여러 청크에 반복 참조되면 upload_files 가
                    # 같은 파일을 중복 업로드·삭제해 FileNotFoundError 로 전체 요청이 실패한다.
                    # 경로 기준으로 최초 1회만 업로드하도록 dedupe.
                    file_list = []
                    for f in self.get_media_files(doc_items):
                        if f['path'] not in scheduled_upload_paths:
                            scheduled_upload_paths.add(f['path'])
                            file_list.append(f)
                    if file_list:
                        upload_tasks.append(asyncio.create_task(
                            upload_files(file_list, request=request)
                        ))

            if upload_tasks:
                await asyncio.gather(*upload_tasks)
            return vectors

        async def __call__(self, request: Request, file_path: str, **kwargs: dict):
            document: DoclingDocument = self.load_documents(file_path, **kwargs)

            artifacts_dir, reference_path = self.get_paths(file_path)
            document = document._with_pictures_refs(image_dir=artifacts_dir, page_no=None, reference_path=reference_path)

            # 민감정보 분류(#315): 청킹 전, 문서 전체를 분류 워크플로우에 1회 호출 → sensitive_infos.
            sensitive_infos: list = []
            if gr.call_enabled(kwargs):
                sensitive_infos = gr.classify_document(
                    gr.doc_text(document), self._guardrail_url, self._guardrail_workflow_id,
                    self._guardrail_api_key, self._guardrail_timeout,
                )

            chunks = self.split_documents(document, **kwargs)
            if len(chunks) == 0:
                raise ATGenosServiceException(1, "chunk length is 0")
            return await self.compose_vectors(
                document, chunks, file_path, request, _sensitive_infos=sensitive_infos, _guardrail_masking=(gr.call_enabled(kwargs) and self._guardrail_masking_enabled), **kwargs
            )


    class HwpProcessor:
        def __init__(self, tokenizer=None, guardrail_url="", guardrail_workflow_id=None, guardrail_api_key="", guardrail_timeout=30, guardrail_masking_enabled=False):
            # 청킹용 토크나이저 (config 기반; 미지정 시 현행 기본값)
            self._tokenizer = tokenizer if tokenizer is not None else _resolve_tokenizer({})
            # PII 마스킹(#315) 접속 정보 — DocumentProcessor 가 config 에서 읽어 주입.
            self._guardrail_url = guardrail_url
            self._guardrail_workflow_id = guardrail_workflow_id
            self._guardrail_api_key = guardrail_api_key
            self._guardrail_timeout = guardrail_timeout
            self._guardrail_masking_enabled = guardrail_masking_enabled

        def get_paths(self, file_path: str):
            """이미지 등 리소스가 저장될 경로 계산 (기존 로직 유지)"""
            output_path, output_file = os.path.split(file_path)
            filename, _ = os.path.splitext(output_file)
            artifacts_dir = Path(f"{output_path}/{filename}")
            reference_path = None if artifacts_dir.is_absolute() else artifacts_dir.parent
            return artifacts_dir, reference_path

        def safe_join(self, iterable):
            """청크 내 헤딩들을 텍스트로 합침"""
            if not isinstance(iterable, (list, tuple, set)):
                return ''
            return ' '.join(map(str, iterable)) + '\n'

        def load_documents(self, file_path: str, **kwargs: dict) -> DoclingDocument:
            """SDK 백엔드를 통해 문서를 로드"""
            # 요청마다 독립적인 pipeline_options 생성 (공유 상태 변이 방지) --> save_images, dump_sdk_output
            pipeline_options = PipelineOptions()
            pipeline_options.save_images = kwargs.get('save_images', True)

            use_hwp_sdk = kwargs.get('use_hwp_sdk', True)
            pipeline_options.dump_sdk_output = kwargs.get('dump_sdk_output', False) if use_hwp_sdk else False

            if use_hwp_sdk:
                converter = DocumentConverter(
                    format_options={
                        InputFormat.HWP: HwpxFormatOption(
                            pipeline_options=pipeline_options,
                            backend=GenosHwpDocumentBackend
                        ),
                        InputFormat.XML_HWPX: HwpxFormatOption(
                            pipeline_options=pipeline_options,
                            backend=GenosHwpDocumentBackend
                        ),
                    }
                )
            else:
                converter = DocumentConverter(
                    format_options={
                        InputFormat.HWP: HwpxFormatOption(
                            pipeline_options=pipeline_options,
                            backend=HwpDocumentBackend
                        ),
                        InputFormat.XML_HWPX: HwpxFormatOption(
                            pipeline_options=pipeline_options,
                            backend=HwpxDocumentBackend
                        ),
                    }
                )

            conv_result: ConversionResult = converter.convert(Path(file_path).resolve(), raises_on_error=True)
            return conv_result.document

        @staticmethod
        def _hwp_sdk_text_is_empty(document: DoclingDocument) -> bool:
            """GenosHwp SDK 결과 문서에 본문 텍스트가 전혀 없는지 판단(레거시 폴백 트리거용).

        SDK 가 exit 0 으로 "성공"해도 본문을 한 글자도 못 뽑는 경우가 있다(일부 .hwp/.hwpx;
        DRM/암호화 등). 텍스트 run 이 하나도 없으면 True. (convert_processor 와 형평성)
        """
            texts = getattr(document, "texts", None) or []
            return not any((getattr(t, "text", "") or "").strip() for t in texts)

        def split_documents(self, document: DoclingDocument, **kwargs: dict):
            """chunker_type에 따라 HybridChunker 또는 RecursiveCharacterTextSplitter로 분할.

        반환: (chunks, page_chunk_counts). chunks 형식은 chunker_type에 따라 다르다
        (DocChunk 리스트 또는 dict 리스트). compose_vectors가 동일한 chunker_type 분기로 처리한다.
        """
            chunker_type = kwargs.get("chunker_type", "recursive")
            page_chunk_counts: dict[int, int] = defaultdict(int)

            if chunker_type == "recursive":
                recursive_chunk_size = kwargs.get("chunk_size")
                if recursive_chunk_size is None:
                    recursive_chunk_size = kwargs.get("recursive_chunk_size")
                recursive_chunk_overlap = kwargs.get("chunk_overlap")
                if recursive_chunk_overlap is None:
                    recursive_chunk_overlap = kwargs.get("recursive_chunk_overlap")
                chunks = _split_with_recursive_chunker(
                    document,
                    chunk_size=recursive_chunk_size,
                    chunk_overlap=recursive_chunk_overlap,
                )
                for ch in chunks:
                    page_chunk_counts[ch["page_no"]] += 1
                return chunks, page_chunk_counts

            # hybrid
            hybrid_chunk_size = _parse_optional_int(kwargs.get("hybrid_chunk_size"), "hybrid_chunk_size")
            if hybrid_chunk_size is None or hybrid_chunk_size <= 0:
                hybrid_chunk_size = _DEFAULT_HYBRID_MAX_TOKENS
            hybrid_merge_peers = _parse_optional_bool(kwargs.get("hybrid_merge_peers"), "hybrid_merge_peers")
            if hybrid_merge_peers is None:
                hybrid_merge_peers = True
            chunker_kwargs = {
                "max_tokens": hybrid_chunk_size,
                "merge_peers": hybrid_merge_peers,
                "tokenizer": self._tokenizer,
                "tokenizer_type": kwargs.get("hybrid_tokenizer_type", "char"),
            }
            chunker = HybridChunker(**chunker_kwargs)
            chunks: List[DocChunk] = list(chunker.chunk(dl_doc=document, **kwargs))
            for chunk in chunks:
                if chunk.meta.doc_items[0].prov:
                    page_chunk_counts[chunk.meta.doc_items[0].prov[0].page_no] += 1
            return chunks, page_chunk_counts

        async def compose_vectors(self, document: DoclingDocument, chunks, page_chunk_counts: dict[int, int],
                                  request: Any, **kwargs: dict) -> list[dict]:
            """빌더를 사용하여 최종 GenOSVectorMeta 리스트 생성"""
            chunker_type = kwargs.get("chunker_type", "recursive")
            _sensitive_infos: list = kwargs.get("_sensitive_infos") or []      # #315 분류 결과
            _gr_masking: bool = bool(kwargs.get("_guardrail_masking", False))   # #315 마스킹 치환 on/off

            global_metadata = dict(
                n_chunk_of_doc=len(chunks),
                n_page=document.num_pages(),
                reg_date=datetime.now().isoformat(timespec='seconds') + 'Z',
            )

            current_page = None
            chunk_index_on_page = 0
            vectors = []
            upload_tasks = []

            for chunk_idx, chunk in enumerate(chunks):
                if chunker_type == "recursive":
                    chunk_page = chunk["page_no"]
                    content = chunk["text"]
                    doc_items = chunk["doc_items"]
                else:
                    chunk_page = chunk.meta.doc_items[0].prov[0].page_no if chunk.meta.doc_items[0].prov else 0
                    content = self.safe_join(chunk.meta.headings) + chunk.text
                    doc_items = chunk.meta.doc_items

                if chunk_page != current_page:
                    current_page = chunk_page
                    chunk_index_on_page = 0

                # #315 가드레일 분류 후처리: quote 매칭 → guardrail_categories 부착(항상) + 마스킹 치환(옵션)
                content, chunk_cats = gr.apply_to_text(content, _sensitive_infos, _gr_masking)

                builder = ATGenOSVectorMetaBuilder()
                vector_obj = (builder
                          .set_text(content)
                          .set_page_info(chunk_page, chunk_index_on_page, page_chunk_counts[chunk_page])
                          .set_chunk_index(chunk_idx)
                          .set_global_metadata(**global_metadata)
                          .set_chunk_bboxes(doc_items, document)
                          .set_media_files(doc_items)
                          .set_guardrail_categories(sorted(chunk_cats) if chunk_cats else None)
                          ).build()
                vectors.append(vector_obj)
                chunk_index_on_page += 1

            if upload_tasks:
                await asyncio.gather(*upload_tasks)

            return vectors

        async def __call__(self, request: Any, file_path: str, **kwargs: dict):
            """외부에서 호출되는 통합 프로세서 입구"""
            ext = os.path.splitext(file_path)[-1].lower()

            # 1. SDK 백엔드로 문서 변환 (실패 시 폴백)
            document: DoclingDocument = None
            try:
                document = self.load_documents(file_path, **kwargs)
            except Exception as sdk_err:
                _log.warning(f"[HwpProcessor] GenosHwp SDK 변환 실패: {sdk_err}")
                if ext in ('.hwp', '.hwpx'):
                    # GenosHwp SDK 실패 시 레거시 백엔드로 폴백 (.hwp → HwpDocumentBackend, .hwpx → HwpxDocumentBackend)
                    backend_name = "HwpDocumentBackend" if ext == '.hwp' else "HwpxDocumentBackend"
                    try:
                        _log.info(f"[HwpProcessor] {backend_name}로 폴백 시도: {file_path}")
                        kwargs_fallback = dict(kwargs, use_hwp_sdk=False)
                        document = self.load_documents(file_path, **kwargs_fallback)
                        _log.info(f"[HwpProcessor] {backend_name} 폴백 성공")
                    except Exception as fallback_err:
                        _log.warning(f"[HwpProcessor] {backend_name} 폴백도 실패: {fallback_err}")
                        raise sdk_err
                else:
                    raise

            # 1-b. SDK 가 예외 없이(exit 0) 끝났어도 본문 텍스트가 비어 있으면(빈 doc_items 로
            #      다운스트림이 깨지거나 무의미한 표 청크만 나오는 경우) 레거시 백엔드로 폴백한다.
            #      그래도 본문을 못 얻으면 예외로 올려 DocumentProcessor.__call__ 의 PDF 변환 폴백에
            #      위임한다. (convert_processor 와 형평성 — convert 는 GenosSmartChunker 예외로 잡히지만
            #      attachment 는 recursive splitter 라 예외가 안 나므로 여기서 명시적으로 처리한다.)
            # .hml(HWPML)은 GenosHwp SDK 전용 포맷 — 레거시 백엔드가 없어 빈 결과면 바로
            # 상위(DocumentProcessor.__call__)의 PDF 변환 폴백으로 위임한다 (이슈 #323).
            if ext == '.hml' and self._hwp_sdk_text_is_empty(document):
                raise HwpConversionError(
                    f"HML SDK 결과가 비어 있음(hml 은 레거시 백엔드 없음): {file_path}"
                )
            if ext in ('.hwp', '.hwpx') and self._hwp_sdk_text_is_empty(document):
                backend_name = "HwpDocumentBackend" if ext == '.hwp' else "HwpxDocumentBackend"
                _log.warning(f"[HwpProcessor] GenosHwp SDK 결과에 본문 텍스트가 없어 {backend_name} 폴백 시도: {file_path}")
                fallback_doc = None
                try:
                    fallback_doc = self.load_documents(file_path, **dict(kwargs, use_hwp_sdk=False))
                except Exception as fallback_err:
                    _log.warning(f"[HwpProcessor] {backend_name} 폴백 실패, 상위 PDF 폴백으로 위임: {fallback_err}")
                if fallback_doc is not None and not self._hwp_sdk_text_is_empty(fallback_doc):
                    _log.info(f"[HwpProcessor] {backend_name} 폴백 성공(본문 텍스트 확보)")
                    document = fallback_doc
                else:
                    _log.info(f"[HwpProcessor] {backend_name} 폴백으로도 본문 복구 실패, 상위 PDF 폴백으로 위임")
                    raise HwpConversionError(
                        f"HWP/HWPX SDK 결과가 비어 있고 레거시 백엔드로도 본문 복구 실패: {file_path}"
                    )

            # 2. 이미지 참조 경로 설정
            artifacts_dir, reference_path = self.get_paths(file_path)
            document = document._with_pictures_refs(
                image_dir=artifacts_dir,
                page_no=None,
                reference_path=reference_path
            )

            # 민감정보 분류(#315): 청킹 전, 문서 전체를 분류 워크플로우에 1회 호출 → sensitive_infos.
            sensitive_infos: list = []
            if gr.call_enabled(kwargs):
                sensitive_infos = gr.classify_document(
                    gr.doc_text(document), self._guardrail_url, self._guardrail_workflow_id,
                    self._guardrail_api_key, self._guardrail_timeout,
                )

            # 3. 청킹 + 4. 벡터화
            chunks, page_chunk_counts = self.split_documents(document, **kwargs)
            if len(chunks) == 0:
                raise ATGenosServiceException(1, "chunk length is 0")
            return await self.compose_vectors(
                document, chunks, page_chunk_counts, request, _sensitive_infos=sensitive_infos, _guardrail_masking=(gr.call_enabled(kwargs) and self._guardrail_masking_enabled), **kwargs
            )

    # [병합 개명] `GenosServiceException` → `ATGenosServiceException` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    class ATGenosServiceException(Exception):
        """GenOS 와의 의존성 부분 제거를 위해 추가"""

        def __init__(self, error_code: str, error_msg: Optional[str] = None, msg_params: Optional[dict] = None) -> None:
            self.code = 1
            self.error_code = error_code
            self.error_msg = error_msg or "GenOS Service Exception"
            self.msg_params = msg_params or {}

        def __repr__(self) -> str:
            class_name = self.__class__.__name__
            return f"{class_name}(code={self.code!r}, errMsg={self.error_msg!r})"


    # [병합 개명] `DocumentProcessor` → `AttachDocumentProcessor` — intelligent 판본과 **본문이 다르다**. 지우면
    #             attach 가 intelligent 판본을 쓰게 되어 동작이 바뀌므로 둘 다 남긴다.
    class AttachDocumentProcessor:
        def __init__(self, config_path: str | None = None):
            if config_path is None:
                config_path = _resolve_default_attachment_config_path()
            cfg = _at_load_config(config_path)
            self._config_dir = Path(config_path).resolve().parent

            defaults_cfg = _as_dict(cfg.get("defaults"))
            chunking_cfg = _as_dict(cfg.get("chunking"))
            generic_chunk_cfg = _as_dict(chunking_cfg.get("generic"))
            recursive_chunk_cfg = _as_dict(chunking_cfg.get("recursive"))
            hybrid_chunk_cfg = _as_dict(chunking_cfg.get("hybrid"))
            loaders_cfg = _as_dict(cfg.get("loaders"))
            image_loader_cfg = _as_dict(loaders_cfg.get("image"))
            tabular_loader_cfg = _as_dict(loaders_cfg.get("tabular"))
            whisper_cfg = _as_dict(cfg.get("whisper"))

            # PPT 페이지 단위 설명(page-level image description) 설정.
            # config 위치: formats.ppt.page_description. 공통 모듈(enrichment/page_description)로 파싱.
            formats_cfg = _as_dict(cfg.get("formats"))
            ppt_fmt_cfg = _as_dict(formats_cfg.get("ppt"))
            hwp_fmt_cfg = _as_dict(formats_cfg.get("hwp"))
            ppt_pd_cfg = _as_dict(ppt_fmt_cfg.get("page_description"))
            self._page_desc_options = PageDescriptionOptions.from_config(ppt_pd_cfg, self._config_dir)

            # 청킹용 토크나이저 (chunking config 기반; 미지정 시 현행 기본값)
            self._tokenizer = _resolve_tokenizer(chunking_cfg)

            # 청킹 모드는 chunking.chunker_type 에서 읽는다(구버전 호환: 없으면 defaults.chunker_type).
            chunker_type = str(
                chunking_cfg.get("chunker_type", defaults_cfg.get("chunker_type", "recursive"))
            ).strip().lower()
            if chunker_type not in {"recursive", "hybrid"}:
                _log.warning(
                    f"[DocumentProcessor] Unknown defaults.chunker_type '{chunker_type}', fallback to 'recursive'."
                )
                chunker_type = "recursive"

            use_pdf_sdk = _parse_optional_bool(defaults_cfg.get("use_pdf_sdk"), "defaults.use_pdf_sdk")

            # HWP/HWPX 전용 옵션은 formats.hwp 에서 읽는다(구버전 호환: 없으면 defaults 폴백).
            use_hwp_sdk = _parse_optional_bool(hwp_fmt_cfg.get("use_hwp_sdk"), "formats.hwp.use_hwp_sdk")
            if use_hwp_sdk is None:
                use_hwp_sdk = _parse_optional_bool(defaults_cfg.get("use_hwp_sdk"), "defaults.use_hwp_sdk")
            dump_sdk_output = _parse_optional_bool(
                hwp_fmt_cfg.get("dump_sdk_output"), "formats.hwp.dump_sdk_output"
            )
            if dump_sdk_output is None:
                dump_sdk_output = _parse_optional_bool(
                    defaults_cfg.get("dump_sdk_output"), "defaults.dump_sdk_output"
                )
            save_images = _parse_optional_bool(hwp_fmt_cfg.get("save_images"), "formats.hwp.save_images")
            if save_images is None:
                save_images = _parse_optional_bool(defaults_cfg.get("save_images"), "defaults.save_images")

            log_level = _parse_optional_int(defaults_cfg.get("log_level"), "defaults.log_level")
            if log_level is None:
                log_level = 4

            # 청크 크기 공통 옵션(chunking.chunk_size). recursive/hybrid 는 chunker_type 으로
            # 택일되므로 값 하나를 활성 모드가 자기 단위(recursive=문자 수 · hybrid=토큰 수)로 해석한다.
            common_chunk_size = _parse_optional_int(chunking_cfg.get("chunk_size"), "chunking.chunk_size")

            # 문자수 기반 통합 청킹 설정. 우선순위: recursive.chunk_size > chunking.chunk_size(공통)
            # > (레거시)chunking.generic.chunk_size > 0.
            recursive_chunk_size = _parse_optional_int(
                recursive_chunk_cfg.get("chunk_size"), "chunking.recursive.chunk_size"
            )
            if recursive_chunk_size is None:
                recursive_chunk_size = common_chunk_size
            if recursive_chunk_size is None:
                recursive_chunk_size = _parse_optional_int(
                    generic_chunk_cfg.get("chunk_size"), "chunking.generic.chunk_size"
                )
            if recursive_chunk_size is None or recursive_chunk_size < 0:
                recursive_chunk_size = 0  # 0 = 전체 문서를 1청크로 (문자수 분할 안 함)
            recursive_chunk_overlap = _parse_optional_int(
                recursive_chunk_cfg.get("chunk_overlap", generic_chunk_cfg.get("chunk_overlap")),
                "chunking.recursive.chunk_overlap",
            )
            if recursive_chunk_overlap is None or recursive_chunk_overlap < 0:
                recursive_chunk_overlap = 100

            # hybrid(토큰 수). 우선순위: hybrid.chunk_size > chunking.chunk_size(공통) > 무제한 기본값.
            hybrid_chunk_size = _parse_optional_int(
                hybrid_chunk_cfg.get("chunk_size"), "chunking.hybrid.chunk_size"
            )
            if hybrid_chunk_size is None:
                hybrid_chunk_size = common_chunk_size
            if hybrid_chunk_size is None or hybrid_chunk_size <= 0:
                hybrid_chunk_size = _DEFAULT_HYBRID_MAX_TOKENS
            hybrid_merge_peers = _parse_optional_bool(
                hybrid_chunk_cfg.get("merge_peers"), "chunking.hybrid.merge_peers"
            )
            if hybrid_merge_peers is None:
                hybrid_merge_peers = True
            hybrid_tokenizer_type = str(hybrid_chunk_cfg.get("tokenizer_type", "char")).strip().lower()
            if hybrid_tokenizer_type not in {"char", "huggingface"}:
                _log.warning(
                    f"[DocumentProcessor] Unknown chunking.hybrid.tokenizer_type '{hybrid_tokenizer_type}', fallback to 'char'."
                )
                hybrid_tokenizer_type = "char"

            image_ocr_languages = image_loader_cfg.get("ocr_languages", ["kor", "eng"])
            if isinstance(image_ocr_languages, (list, tuple, set)):
                image_ocr_languages = [str(v).strip() for v in image_ocr_languages if str(v).strip()]
            else:
                image_ocr_languages = ["kor", "eng"]
            if not image_ocr_languages:
                image_ocr_languages = ["kor", "eng"]

            tabular_sample_bytes = _parse_optional_int(
                tabular_loader_cfg.get("encoding_detect_sample_bytes"),
                "loaders.tabular.encoding_detect_sample_bytes",
            )
            if tabular_sample_bytes is None or tabular_sample_bytes <= 0:
                tabular_sample_bytes = 10000

            whisper_chunk_sec = _parse_optional_int(whisper_cfg.get("chunk_sec"), "whisper.chunk_sec")
            if whisper_chunk_sec is None or whisper_chunk_sec <= 0:
                whisper_chunk_sec = 29
            whisper_chunk_overlap_ms = _parse_optional_int(
                whisper_cfg.get("chunk_overlap_ms"), "whisper.chunk_overlap_ms"
            )
            if whisper_chunk_overlap_ms is None or whisper_chunk_overlap_ms < 0:
                whisper_chunk_overlap_ms = 300
            whisper_tmp_dir_prefix = str(
                whisper_cfg.get("tmp_dir_prefix", "./tmp_audios_")
            ).strip() or "./tmp_audios_"

            self._default_kwargs = {
                "log_level": log_level,
                "chunker_type": chunker_type,
                "use_pdf_sdk": True if use_pdf_sdk is None else use_pdf_sdk,
                "use_hwp_sdk": True if use_hwp_sdk is None else use_hwp_sdk,
                "dump_sdk_output": False if dump_sdk_output is None else dump_sdk_output,
                "save_images": True if save_images is None else save_images,
                "recursive_chunk_size": recursive_chunk_size,
                "recursive_chunk_overlap": recursive_chunk_overlap,
                "hybrid_chunk_size": hybrid_chunk_size,
                "hybrid_merge_peers": hybrid_merge_peers,
                "hybrid_tokenizer_type": hybrid_tokenizer_type,
                "image_ocr_languages": image_ocr_languages,
                "tabular_encoding_detect_sample_bytes": tabular_sample_bytes,
                "whisper_url": str(
                    whisper_cfg.get("url", "http://192.168.74.164:30100/v1/audio/transcriptions")
                ).strip() or "http://192.168.74.164:30100/v1/audio/transcriptions",
                "whisper_model": str(whisper_cfg.get("model", "model")).strip() or "model",
                "whisper_language": str(whisper_cfg.get("language", "ko")).strip() or "ko",
                "whisper_response_format": str(
                    whisper_cfg.get("response_format", "json")
                ).strip() or "json",
                "whisper_temperature": str(whisper_cfg.get("temperature", "0")).strip() or "0",
                "whisper_stream": str(whisper_cfg.get("stream", "false")).strip() or "false",
                "whisper_timestamp_granularities": str(
                    whisper_cfg.get("timestamp_granularities", "word")
                ).strip() or "word",
                "whisper_chunk_sec": whisper_chunk_sec,
                "whisper_chunk_overlap_ms": whisper_chunk_overlap_ms,
                "whisper_tmp_dir_prefix": whisper_tmp_dir_prefix,
            }

            # 민감정보 분류(#315): GenOS 분류 워크플로우 접속 정보(환경 종속값). on/off 는 요청별 kwargs.
            gm_cfg = _as_dict(cfg.get("guardrail"))
            self._guardrail_url = str(gm_cfg.get("url") or "").strip()
            self._guardrail_workflow_id = _parse_optional_int(gm_cfg.get("workflow_id"), "guardrail.workflow_id")
            self._guardrail_api_key = str(gm_cfg.get("api_key") or "").strip()
            gm_timeout = _parse_optional_int(gm_cfg.get("timeout"), "guardrail.timeout")
            self._guardrail_timeout = gm_timeout if gm_timeout and gm_timeout > 0 else 60
            self._guardrail_masking_enabled = bool(_parse_optional_bool(gm_cfg.get("masking_enabled"), "guardrail.masking_enabled"))

            self.page_chunk_counts = defaultdict(int)
            _gm = dict(
                guardrail_url=self._guardrail_url,
                guardrail_workflow_id=self._guardrail_workflow_id,
                guardrail_api_key=self._guardrail_api_key,
                guardrail_timeout=self._guardrail_timeout,
                guardrail_masking_enabled=self._guardrail_masking_enabled,
            )
            self.hwp_processor = HwpProcessor(tokenizer=self._tokenizer, **_gm)
            self.docx_processor = DocxProcessor(tokenizer=self._tokenizer, **_gm)

        def _merge_runtime_kwargs(self, kwargs: dict) -> dict:
            merged = dict(self._default_kwargs)
            for k, v in kwargs.items():
                if v is not None:
                    merged[k] = v
            return merged

        def _get_ppt_pdf_converter(self) -> DocumentConverter:
            """이미지 기반 PPT(→PDF) 파싱용 경량 docling 컨버터(lazy, 캐시).

        첨부용은 dotsocr(genos_layout) 미수행 + do_ocr=False 로 최소 파싱만 수행한다.
        페이지 단위 설명이 켜져 있으면 generate_page_images=True 로 페이지 렌더 이미지를 만든다.
        """
            converter = getattr(self, "_ppt_pdf_converter", None)
            if converter is not None:
                return converter
            opts = PdfPipelineOptions()
            opts.do_ocr = False
            opts.do_table_structure = False
            opts.generate_page_images = bool(self._page_desc_options.enabled)
            opts.generate_picture_images = False
            opts.images_scale = self._page_desc_options.images_scale
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
            )
            self._ppt_pdf_converter = converter
            return converter

        def _load_ppt_page_documents(self, file_path: str, **kwargs: dict) -> "Optional[list[Document]]":
            """PPT/PPTX → PDF 변환 후 docling 경량 파싱 + 페이지 단위 image description.

        페이지별 Document(metadata['page']=0-based) 리스트를 반환한다. PDF 변환이 불가하면
        None 을 반환해 호출부가 레거시 langchain 경로로 폴백하도록 한다.
        """
            pdf_path = at_convert_to_pdf(file_path, use_pdf_sdk=kwargs.get('use_pdf_sdk', True))
            if not pdf_path or not os.path.exists(pdf_path):
                candidate = _get_pdf_path(file_path)
                pdf_path = candidate if os.path.exists(candidate) else None
            if not pdf_path:
                _log.warning(f"[ppt] PDF 변환 실패 — 레거시 경로로 폴백: {os.path.basename(file_path)}")
                return None

            converter = self._get_ppt_pdf_converter()
            document: DoclingDocument = converter.convert(pdf_path, raises_on_error=True).document

            # 페이지별 네이티브 텍스트 수집
            page_text_parts: dict[int, list[str]] = defaultdict(list)
            for item, _ in document.iterate_items():
                text = str(getattr(item, "text", "") or "").strip()
                if not text:
                    continue
                prov = getattr(item, "prov", None) or []
                page_no = prov[0].page_no if prov and getattr(prov[0], "page_no", None) else 1
                page_text_parts[page_no].append(text)
            page_texts: dict[int, str] = {
                pno: "\n".join(parts).strip() for pno, parts in page_text_parts.items()
            }

            # 페이지 단위 image description(옵션). enable=false 면 설명만 skip(파싱은 유지).
            # native text 가 있으면 프롬프트({{page_text}})에 반영해 요청한다.
            page_descs: dict[int, str] = describe_pages(
                document, self._page_desc_options, page_texts=page_texts
            )

            all_pages: set[int] = set()
            if getattr(document, "pages", None):
                all_pages |= set(document.pages.keys())
            all_pages |= set(page_texts.keys()) | set(page_descs.keys())
            if not all_pages:
                all_pages = {1}

            # 같은 페이지의 native text 와 설명을 동일 청크(=동일 Document)로 병합한다.
            documents: list[Document] = []
            for page_no in sorted(all_pages):
                native = page_texts.get(page_no, "").strip()
                desc = page_descs.get(page_no, "").strip()
                if native and desc:
                    content = f"{native}\n\n[페이지 이미지 설명]\n{desc}"
                elif desc:
                    content = desc
                else:
                    content = native
                if not content:
                    # 빈 페이지(텍스트/설명 모두 없음) → '.' 폴백으로 Empty document 예외 방지
                    content = "."
                documents.append(
                    Document(
                        page_content=content,
                        metadata={'source': file_path, 'page': page_no - 1},
                    )
                )

            _log.info(
                f"[ppt] page documents 생성: pages={len(documents)}, "
                f"described={len(page_descs)}, description_enabled={self._page_desc_options.enabled}"
            )
            return documents

        def _chunk_ppt_pages(self, documents: "list[Document]", **kwargs: dict) -> "list[Document]":
            """PPT 페이지 Document 를 청크로 구성한다.

        기본: 1 page = 1 chunk. chunk_size(kwargs, 명시된 경우만) 가 주어지면 연속 페이지를
        합친 길이가 chunk_size 이하가 되도록 greedy 병합한다. 병합 청크는 metadata['page']=시작,
        metadata['end_page']=끝(0-based) 을 갖는다.
        """
            self.page_chunk_counts = defaultdict(int)
            if not documents:
                raise Exception('Empty document')

            # 모든 페이지에 추출 가능한 텍스트/설명이 없는 경우(이미지 기반 PPT 등): 페이지별 sentinel('.')
            # 을 이어붙이지 않고, 페이지 전 범위를 span 하는 단일 빈 텍스트('') 청크로 반환한다.
            if all(doc.page_content.strip() in ("", ".") for doc in documents):
                last_page = documents[-1].metadata.get('page', 0)
                self.page_chunk_counts[0] += 1
                return [Document(
                    page_content="",
                    metadata={
                        'source': documents[0].metadata.get('source'),
                        'page': 0,
                        'end_page': last_page,
                    },
                )]

            # chunk_size 우선순위: kwargs['chunk_size'] > chunking.recursive.chunk_size(recursive_chunk_size).
            # 값이 없거나 <=0 이면 1 page = 1 chunk, 있으면 연속 페이지를 그 길이까지 결합.
            chunk_size = _parse_optional_int(kwargs.get('chunk_size'), 'chunk_size')
            if chunk_size is None:
                chunk_size = _parse_optional_int(kwargs.get('recursive_chunk_size'), 'recursive_chunk_size')

            chunks: list[Document] = []
            if chunk_size is None or chunk_size <= 0:
                # 1 page = 1 chunk
                for doc in documents:
                    page = doc.metadata.get('page', 0)
                    chunks.append(Document(
                        page_content=doc.page_content,
                        metadata={**doc.metadata, 'end_page': page},
                    ))
            else:
                # 연속 페이지 greedy 병합
                cur_parts: list[str] = []
                cur_start: Optional[int] = None
                cur_end: Optional[int] = None
                cur_source = documents[0].metadata.get('source')

                def _flush():
                    if cur_parts:
                        chunks.append(Document(
                            page_content="\n\n".join(cur_parts),
                            metadata={'source': cur_source, 'page': cur_start, 'end_page': cur_end},
                        ))

                for doc in documents:
                    page = doc.metadata.get('page', 0)
                    text = doc.page_content
                    if cur_parts and len("\n\n".join(cur_parts + [text])) > chunk_size:
                        _flush()
                        cur_parts = [text]
                        cur_start = page
                        cur_end = page
                    else:
                        cur_parts.append(text)
                        if cur_start is None:
                            cur_start = page
                        cur_end = page
                _flush()

            chunks = [c for c in chunks if c.page_content]
            if not chunks:
                raise Exception('Empty document')
            for chunk in chunks:
                self.page_chunk_counts[chunk.metadata.get('page', 0)] += 1
            return chunks

        def get_loader(
            self,
            file_path: str,
            use_pdf_sdk: bool = True,
            image_ocr_languages: Optional[list[str]] = None,
        ):
            ext = os.path.splitext(file_path)[-1].lower()
            real_type = self.get_real_file_type(file_path)

            # 확장자와 실제 파일 타입이 다를 때만 real_type 사용
            if ext != real_type and real_type == 'pdf':
                return PyMuPDFLoader(file_path)
            elif ext != real_type and real_type in ['txt', 'json', 'md']:
                return TextLoader(file_path)
            # 원래 확장자 기반 로직
            elif ext == '.pdf':
                return PyMuPDFLoader(file_path)
            elif ext == '.doc':
                at_convert_to_pdf(file_path, use_pdf_sdk=use_pdf_sdk)
                return UnstructuredWordDocumentLoader(file_path)
            elif ext in ['.ppt', '.pptx']:
                at_convert_to_pdf(file_path, use_pdf_sdk=use_pdf_sdk)
                return UnstructuredPowerPointLoader(file_path)
            elif ext in ['.jpg', '.jpeg', '.png']:
                at_convert_to_pdf(file_path, use_pdf_sdk=use_pdf_sdk)
                languages = image_ocr_languages or ["kor", "eng"]
                if not isinstance(languages, list):
                    languages = [str(languages)]
                languages = [str(lang).strip() for lang in languages if str(lang).strip()]
                if not languages:
                    languages = ["kor", "eng"]
                # 한국어 OCR 지원을 위한 언어 설정
                return UnstructuredImageLoader(
                    file_path,
                    languages=languages,  # 한국어 + 영어 OCR
                )
            elif ext in ['.txt', '.json', '.md']:
                return TextLoader(file_path)
            elif ext == '.md':
                return UnstructuredMarkdownLoader(file_path)
            else:
                return UnstructuredFileLoader(file_path)

        def get_real_file_type(self, file_path: str) -> str:
            """파일 확장자가 아닌 실제 내용으로 파일 타입 판단"""
            with open(file_path, 'rb') as f:
                header = f.read(8)
            if header.startswith(b'%PDF-'):
                return 'pdf'
            elif header.startswith(b'\x89PNG'):
                return 'png'
            elif header.startswith(b'\xff\xd8\xff'):
                return 'jpg'

            # 매직 헤더로 판단할 수 없으면 확장자 사용
            return os.path.splitext(file_path)[-1].lower()

        def convert_md_to_pdf(self, md_path):
            """Markdown 파일을 PDF로 변환"""
            install_packages(['chardet'])
            import chardet

            pdf_path = md_path.replace('.md', '.pdf')
            with open(md_path, 'rb') as f:
                raw_file = f.read()
            candidates = ['utf-8', 'utf-8-sig']
            try:
                det = (chardet.detect(raw_file) or {}).get('encoding') or ''
                # chardet가 ascii/unknown이면 무시. 그 외면 후보에 추가
                if det and det.lower() not in ('ascii', 'unknown'):
                    if det.lower() not in [c.lower() for c in candidates]:
                        candidates.append(det)
            except Exception:
                pass
            candidates += ['cp949', 'euc-kr', 'iso-8859-1', 'latin-1']
            md_content = None
            for enc in candidates:
                try:
                    md_content = raw_file.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if md_content is None:
                md_content = raw_file.decode('utf-8', errors='replace')

            html_content = markdown(md_content)
            if HTML:
                HTML(string=html_content).write_pdf(pdf_path)
            return pdf_path

        def load_documents(self, file_path: str, **kwargs: dict) -> list[Document]:
            loader = self.get_loader(
                file_path,
                use_pdf_sdk=kwargs.get('use_pdf_sdk', True),
                image_ocr_languages=kwargs.get("image_ocr_languages"),
            )
            documents = loader.load()

            # 이미지 파일의 경우 텍스트 추출 안되었을 시 기본 텍스트 제공
            ext = os.path.splitext(file_path)[-1].lower()
            if ext in ['.jpg', '.jpeg', '.png']:
                # documents가 없거나, 있어도 모든 page_content가 비어있는 경우
                if not documents or not any(doc.page_content.strip() for doc in documents):
                    documents = [Document(page_content=".", metadata={'source': file_path, 'page': 0})]

            return documents

        def split_documents(self, documents, **kwargs: dict) -> list[Document]:
            # 문자수 기반 통합 청킹 (chunking.recursive 설정 공유). chunk_size<=0 이면 문서당 1청크.
            chunk_size = kwargs.get('chunk_size')
            if chunk_size is None:
                chunk_size = kwargs.get('recursive_chunk_size', 0)
            chunk_overlap = kwargs.get('chunk_overlap')
            if chunk_overlap is None:
                chunk_overlap = kwargs.get('recursive_chunk_overlap', 100)

            chunks = [
                Document(page_content=part, metadata=dict(doc.metadata))
                for doc in documents
                for part in _char_split_text(
                    doc.page_content,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            ]
            chunks = [chunk for chunk in chunks if chunk.page_content]
            if not chunks:
                raise Exception('Empty document')

            for chunk in chunks:
                page = chunk.metadata.get('page', 0)
                self.page_chunk_counts[page] += 1
            return chunks

        def compose_vectors(self, file_path: str, chunks: list[Document], **kwargs: dict) -> list[dict]:
            _sensitive_infos: list = kwargs.get("_sensitive_infos") or []      # #315 분류 결과
            _gr_masking: bool = bool(kwargs.get("_guardrail_masking", False))   # #315 마스킹 치환 on/off
            ext = os.path.splitext(file_path)[-1].lower()
            real_type = self.get_real_file_type(file_path)

            # 확장자와 실제 파일 타입이 다를 때만 real_type 사용
            if ext != real_type and real_type == 'pdf':
                pdf_path = file_path
            elif ext != real_type and real_type in ['txt', 'json', 'md']:
                pdf_path = _get_pdf_path(file_path)
            # 원래 확장자 기반 로직
            elif file_path.endswith('.md'):
                pdf_path = self.convert_md_to_pdf(file_path)
            elif file_path.endswith(('.ppt', '.pptx')):
                pdf_path = _get_pdf_path(file_path)
            else:
                pdf_path = _get_pdf_path(file_path)

            # doc = fitz.open(pdf_path) if (pdf_path and os.path.exists(pdf_path)) else None

            if file_path.endswith(('.ppt', '.pptx')):
                if os.path.exists(pdf_path):
                    subprocess.run(["rm", pdf_path], check=True)

            global_metadata = dict(
                n_chunk_of_doc=len(chunks),
                n_page=max([chunk.metadata.get('page', 0) for chunk in chunks]),
                reg_date=datetime.now().isoformat(timespec='seconds') + 'Z'
            )
            current_page = None
            chunk_index_on_page = 0

            vectors = []
            for chunk_idx, chunk in enumerate(chunks):
                page = chunk.metadata.get('page', 1)
                # PPT 페이지 결합 청크는 end_page 로 페이지 범위를 표현(미설정 시 단일 페이지).
                end_page = chunk.metadata.get('end_page', page)
                if ext not in ['.hwpx', '.docx']:
                    page += 1
                    end_page += 1
                text = chunk.page_content
                # #315 가드레일 분류 후처리: quote 매칭 → guardrail_categories 부착(항상) + 마스킹 치환(옵션)
                text, chunk_cats = gr.apply_to_text(text, _sensitive_infos, _gr_masking)

                if page != current_page:
                    current_page = page
                    chunk_index_on_page = 0

                # 첨부용에서는 bbox 정보 추출 X
                # if doc:
                #     fitz_page = doc.load_page(page)
                #     global_metadata['chunk_bboxes'] = json.dumps(merge_overlapping_bboxes([{
                #         'page': page + 1,
                #         'type': 'text',
                #         'bbox': {
                #             'l': rect[0] / fitz_page.rect.width,
                #             't': rect[1] / fitz_page.rect.height,
                #             'r': rect[2] / fitz_page.rect.width,
                #             'b': rect[3] / fitz_page.rect.height,
                #         }
                #     } for rect in fitz_page.search_for(text)], x_tolerance=1 / fitz_page.rect.width,
                #         y_tolerance=1 / fitz_page.rect.height))

                vectors.append(ATGenOSVectorMeta.model_validate({
                    'text': text,
                    'n_char': len(text),
                    'n_word': len(text.split()),
                    'n_line': len(text.splitlines()),
                    'i_page': page,
                    'e_page': end_page,
                    'i_chunk_on_page': chunk_index_on_page,
                    'n_chunk_of_page': self.page_chunk_counts[page],
                    'i_chunk_on_doc': chunk_idx,
                    'guardrail_categories': sorted(chunk_cats) if chunk_cats else None,  # #315 민감정보 분류 라벨
                    **global_metadata
                }))
                chunk_index_on_page += 1

            return vectors

        def setup_logging(self, level_num: int):
            """
            5"DEBUG", 4"INFO", 3"WARNING", 2"ERROR", 1"CRITICAL", 0"NOLOG" 중 하나를 받아서 로깅 레벨을 설정하는 메서드
        """
            def get_level_name(level_num: int) -> str:
                level_map = {
                    5: "DEBUG",
                    4: "INFO",
                    3: "WARNING",
                    2: "ERROR",
                    1: "CRITICAL",
                    0: "NOLOG"
                }
                return level_map.get(level_num, "INFO")
            level_name = get_level_name(level_num)
            _log.info(f"Setting log level to: {level_name}")

            if level_name == "NOLOG" or not hasattr(logging, level_name):
                logging.disable(logging.CRITICAL)  # 모든 로그 비활성화
                return

            level = getattr(logging, level_name.upper())

            # root logger 설정 (핸들러는 main에서만 설정)
            logging.basicConfig(
                level=level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                handlers=[logging.StreamHandler()]   # 콘솔 출력
            )

            # root logger level 적용
            logging.getLogger().setLevel(level)

        async def __call__(self, request: Request, file_path: str, **kwargs: dict):
            kwargs = self._merge_runtime_kwargs(kwargs)
            self.setup_logging(kwargs.get('log_level', 4))

            _log.info(f"file_path: {file_path}")
            _log.info(f"kwargs: {kwargs}")

            # 비정상/암호화 파일 사전 감지(이슈 #278/#307): 지원 포맷 매직헤더에 하나도 안 맞고
            # 텍스트도 아니면(=DRM 암호화/손상 바이너리) 파싱/변환 단계의 garbage 처리를 유발하므로
            # 진입부에서 컷한다. 확장자와 무관하게 실제 헤더로 판정.
            bad_reason = _detect_unsupported_file(file_path)
            if bad_reason:
                _log.warning(f"[attachment] 비정상 파일 감지({bad_reason}) — 처리 중단: {file_path}")
                raise ATGenosServiceException(
                    "1", f"{bad_reason} 입니다. 정상 문서로 다시 업로드하세요: {os.path.basename(file_path)}"
                )

            ext = os.path.splitext(file_path)[-1].lower()
            if ext in ('.wav', '.mp3', '.m4a'):
                # TODO(#315): PII 마스킹 미적용(보류) — AudioLoader 는 자체 vector 포맷이라 별도 논의 후 적용.
                # Generate a temporal path saving audio chunks: the audio file is supposed to be splited to several chunks due to limitted length by the model
                file_stem = os.path.basename(file_path).split('.')[0]
                tmp_prefix = str(kwargs.get("whisper_tmp_dir_prefix", "./tmp_audios_"))
                if tmp_prefix.endswith("/"):
                    tmp_path = os.path.join(tmp_prefix, file_stem)
                else:
                    tmp_path = f"{tmp_prefix}{file_stem}"
                if not os.path.exists(tmp_path):
                    os.makedirs(tmp_path)

                # Use 'Whisper' model served in-house
                # [!] Modify the request parameters to change a STT model to be used
                loader = AudioLoader(
                    file_path=file_path,
                    req_url=str(kwargs.get("whisper_url", "")),
                    req_data={
                        'model': str(kwargs.get("whisper_model", "model")),
                        'language': str(kwargs.get("whisper_language", "ko")),
                        'response_format': str(kwargs.get("whisper_response_format", "json")),
                        'temperature': str(kwargs.get("whisper_temperature", "0")),
                        'stream': str(kwargs.get("whisper_stream", "false")),
                        'timestamp_granularities[]': str(
                            kwargs.get("whisper_timestamp_granularities", "word")
                        ),
                    },
                    chunk_sec=int(kwargs.get("whisper_chunk_sec", 29)),
                    chunk_overlap_ms=int(kwargs.get("whisper_chunk_overlap_ms", 300)),
                    tmp_path=tmp_path
                )
                vectors = loader.return_vectormeta_format()

                # Remove the temporal chunks
                try:
                    subprocess.run(['rm', '-r', tmp_path], check=True)
                except:
                    pass
                return vectors

            elif ext in ('.csv', '.xlsx'):
                # TODO(#315): PII 마스킹 미적용(보류) — TabularLoader 는 자체 vector 포맷이라 별도 논의 후 적용.
                loader = TabularLoader(
                    file_path,
                    ext,
                    encoding_detect_sample_bytes=int(
                        kwargs.get("tabular_encoding_detect_sample_bytes", 10000)
                    ),
                )
                vectors = loader.return_vectormeta_format()
                return vectors

            # [핵심 수정] HWP와 HWPX를 하나의 프로세서로 통합 실행
            # .hml(HWPML)은 hwp_sdk 260713+ 에서 지원되어 같은 프로세서로 라우팅 (이슈 #323)
            elif ext in ('.hwp', '.hwpx', '.hml'):
                _log.info(f"Processing Korean Document ({ext}) with Unified HwpProcessor")
                try:
                    return await self.hwp_processor(request, file_path, **kwargs)
                except Exception as hwp_err:
                    # 모든 docling 백엔드 실패 시 LibreOffice PDF 변환으로 최종 폴백
                    _log.warning(f"[DocumentProcessor] HWP/HWPX 처리기 전체 실패, PDF 변환 폴백 시도: {hwp_err}")
                    converted = at_convert_to_pdf(file_path, use_pdf_sdk=kwargs.get('use_pdf_sdk', True))
                    if converted:
                        _log.info(f"[DocumentProcessor] PDF 변환 성공: {converted}")
                        documents: list[Document] = self.load_documents(converted, **kwargs)
                        # 민감정보 분류(#315): 청킹 전, 문서 전체를 분류 워크플로우에 1회 호출.
                        sensitive_infos = (gr.classify_document(
                            gr.docs_text(documents), self._guardrail_url, self._guardrail_workflow_id,
                            self._guardrail_api_key, self._guardrail_timeout)
                            if gr.call_enabled(kwargs) else [])
                        chunks: list[Document] = self.split_documents(documents, **kwargs)
                        vectors: list[dict] = self.compose_vectors(
                            converted, chunks, _sensitive_infos=sensitive_infos, _guardrail_masking=(gr.call_enabled(kwargs) and self._guardrail_masking_enabled), **kwargs)
                        return vectors
                    else:
                        # 이슈 #286 — HWP SDK 도 실패하고 PDF 변환기마저 없으면, 원인을 명확히
                        # 안내한다 (혼란스러운 SDK 에러 대신 PDF 직접 입력/재빌드 안내).
                        if not _at_has_any_pdf_converter():
                            raise ATGenosServiceException(
                                1,
                                f"이 전처리기 이미지에는 PDF 변환기(rhwp/LibreOffice/PDF SDK)가 설치되어 "
                                f"있지 않아 '{os.path.basename(file_path)}' 처리에 실패했습니다. "
                                f"PDF 로 변환한 파일을 입력하거나, 변환기를 포함해 전처리기 이미지를 다시 "
                                f"빌드하세요 (genon/README.md 참고).",
                            ) from hwp_err
                        raise hwp_err

            elif ext == '.docx':
                return await self.docx_processor(request, file_path, **kwargs)

            elif ext in ('.ppt', '.pptx'):
                # PPT: PDF 변환 → 경량 docling 파싱 → 페이지 단위 image description(옵션) →
                # 페이지 기반 청킹(기본 1 page 1 chunk, chunk_size 지정 시 페이지 결합).
                # 변환 실패 시에만 레거시 langchain 경로로 폴백한다.
                documents: Optional[list[Document]] = self._load_ppt_page_documents(file_path, **kwargs)
                if documents is None:
                    documents = self.load_documents(file_path, **kwargs)
                    # 민감정보 분류(#315): 청킹 전 1회 호출.
                    sensitive_infos = (gr.classify_document(
                        gr.docs_text(documents), self._guardrail_url, self._guardrail_workflow_id,
                        self._guardrail_api_key, self._guardrail_timeout)
                        if gr.call_enabled(kwargs) else [])
                    chunks: list[Document] = self.split_documents(documents, **kwargs)
                else:
                    # 민감정보 분류(#315): 페이지 결합 청킹 전 1회 호출.
                    sensitive_infos = (gr.classify_document(
                        gr.docs_text(documents), self._guardrail_url, self._guardrail_workflow_id,
                        self._guardrail_api_key, self._guardrail_timeout)
                        if gr.call_enabled(kwargs) else [])
                    chunks = self._chunk_ppt_pages(documents, **kwargs)
                vectors: list[dict] = self.compose_vectors(
                    file_path, chunks, _sensitive_infos=sensitive_infos, _guardrail_masking=(gr.call_enabled(kwargs) and self._guardrail_masking_enabled), **kwargs)
                return vectors

            else:
                documents: list[Document] = self.load_documents(file_path, **kwargs)

                # 민감정보 분류(#315): 청킹 전, 문서 전체를 분류 워크플로우에 1회 호출.
                sensitive_infos = (gr.classify_document(
                    gr.docs_text(documents), self._guardrail_url, self._guardrail_workflow_id,
                    self._guardrail_api_key, self._guardrail_timeout)
                    if gr.call_enabled(kwargs) else [])

                chunks: list[Document] = self.split_documents(documents, **kwargs)

                vectors: list[dict] = self.compose_vectors(
                    file_path, chunks, _sensitive_infos=sensitive_infos, _guardrail_masking=(gr.call_enabled(kwargs) and self._guardrail_masking_enabled), **kwargs)

                return vectors

except Exception as _fp_exc:  # noqa: BLE001 - 무엇이 빠졌든 hwpx 경로는 살린다
    _FP_ATTACH_IMPORT_ERROR = _fp_exc
    _FP_ATTACH_IMPORT_TRACE = traceback.format_exc()


# ===========================================================================
# PART 2 — 지능형 (genos_files/intelligence_processor.py 원문)
# ===========================================================================
# 통째로 try 안에 있다. docling/genon 스택이 없는 환경에서도 이 파일이 import 되고
# hwpx 경로가 살아 있어야 하기 때문이다 — 무거운 의존 하나가 빠졌을 때 hwpx 적재까지
# 같이 죽으면 안 되고, 회귀 점검이 로컬(표준 라이브러리 + lxml)에서 이 파일을 태울 수
# 있어야 한다. 실패 사실은 숨기지 않는다 — 라우터가 그대로 드러낸다.
_FP_INTELLIGENT_IMPORT_ERROR = None
_FP_INTELLIGENT_IMPORT_TRACE = ""
try:
    # 적재용(지능형) 전처리기 v.2.2.4 (2026-07-30 Release)

    import json
    import os
    import logging
    import math, bisect
    import yaml
    from pathlib import Path

    from collections import defaultdict
    from datetime import datetime
    from typing import Optional, Iterable, Any, List, Dict, Tuple

    from fastapi import Request

    _log = logging.getLogger(__name__)

    # Genos 웹 UI 환경은 facade 코드를 단일 파일(preprocessor.py)로 처리하므로
    # 다른 facade 파일에서 import 가 깨진다. 따라서 convert_to_pdf 는
    # attachment_processor / convert_processor 와 동일하게 자체 정의한다.
    import shutil
    import subprocess
    import tempfile
    import unicodedata

    import httpx


    def convert_to_pdf(file_path: str, use_pdf_sdk: bool = True) -> str | None:
        """
    PDF 변환을 시도한다. 실패해도 예외를 던지지 않고 None을 반환한다.

    chain (HWP/HWPX 입력):
      use_pdf_sdk=True  → pdf_sdk → rhwp → libreoffice
      use_pdf_sdk=False → rhwp → libreoffice
    chain (그 외 입력, 예: docx/pptx):
      use_pdf_sdk=True  → pdf_sdk → libreoffice
      use_pdf_sdk=False → libreoffice

    rhwp 는 HWP/HWPX 전용이라 비-HWP 입력에는 chain 에 들어가지 않는다. HWP/HWPX
    변환은 rhwp 를 libreoffice 보다 우선한다 (pdf_sdk 가 있으면 그 다음 순위).
    내부 구현은 `genon.preprocessor.converters.hwp_to_pdf` 모듈에 통합되어 있다.
    """
        from genon.preprocessor.converters.hwp_to_pdf import convert_hwp_to_pdf
        ext = os.path.splitext(file_path)[1].lower()
        is_hwp = ext in (".hwp", ".hwpx")
        if use_pdf_sdk:
            order = ["pdf_sdk", "rhwp", "libreoffice"] if is_hwp else ["pdf_sdk", "libreoffice"]
        else:
            order = ["rhwp", "libreoffice"] if is_hwp else ["libreoffice"]
        return convert_hwp_to_pdf(file_path, order=order)

    def _is_pdf(file_path: str) -> bool:
        """파일이 PDF 매직 헤더로 시작하는지 확인 (확장자 무관)."""
        try:
            with open(file_path, "rb") as f:
                return f.read(5) == b"%PDF-"
        except Exception:
            return False


    def _has_any_pdf_converter() -> bool:
        """PDF 변환 backend(pdf_sdk / rhwp / libreoffice) 가 하나라도 가용한지 확인 (이슈 #286).

    빌드 시 INSTALL_LIBREOFFICE / INSTALL_RHWP 를 끄거나 PDF SDK 미포함(standard)이면
    변환 backend 가 0개가 될 수 있다. 이때 비-PDF 입력을 변환 시도하면 무조건 실패하므로,
    호출부에서 "PDF 로 직접 입력" 안내를 주기 위한 판별 헬퍼.
    가용성 판단 자체가 불가하면(import 실패 등) True 를 반환해 기존 동작을 유지한다.
    """
        try:
            from genon.preprocessor.converters.hwp_to_pdf.availability import (
                libreoffice_available,
                pdf_sdk_available,
                rhwp_available,
            )
            return bool(pdf_sdk_available() or rhwp_available() or libreoffice_available())
        except ImportError:
            # facade 단일 파일 실행 등으로 모듈 import 가 안 되는 경우 → 기존 동작 유지(가용 가정)
            return True
        except Exception as exc:
            # 가용성 probe 자체가 예기치 못하게 실패하면 로그만 남기고 파이프라인은 막지 않는다
            _log.warning(f"[_has_any_pdf_converter] PDF 변환기 가용성 확인 실패: {exc}")
            return True


    # ── 비정상/암호화 파일 사전 감지 (이슈 #278/#307) ─────────────────────────────
    # 이 블록은 parser/convert/attachment_processor 에도 복제되어 있다(단일 파일 배포 구조).
    # 수정 시 네 파일 동기화 필요.
    # 지원 포맷의 매직 헤더(allowlist). 각 값은 아래 공식 출처로 근거 확인 + 실제 샘플로 검증함.
    #   - 정본 매직 DB: file/file(libmagic) magic/Magdir — 실제 본 모듈이 쓰는 python-magic의 DB.
    #     (PDF=Magdir/pdf "%PDF-", PNG/GIF=Magdir/images, JPEG=Magdir/jpeg 0xffd8ff, ZIP=Magdir/msooxml "PK\3\4")
    #   - 포맷 공식 스펙: PDF=ISO 32000(%PDF-), PNG=W3C PNG/RFC2083(89 50 4E 47 0D 0A 1A 0A),
    #     ZIP=PKWARE APPNOTE(local file header 0x04034b50), OLE2/CFB=[MS-CFB] §2.2 Header(D0CF11E0A1B11AE1).
    # zip(PK)=docx/xlsx/pptx/hwpx, OLE2(d0cf..)=hwp/doc/ppt/xls(레거시).
    _KNOWN_MAGIC_PREFIXES = (
        b"%PDF-",                                # pdf
        b"\x89PNG\r\n\x1a\n",                    # png
        b"\xff\xd8\xff",                         # jpeg/jpg
        b"GIF87a", b"GIF89a",                    # gif
        b"BM",                                    # bmp
        b"II*\x00", b"MM\x00*",                  # tiff
        b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08",  # zip 계열(ooxml/hwpx)
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",     # OLE2/CFB(hwp5/doc/ppt/xls)
        b"ID3",                                   # mp3(id3v2)
        b"RIFF",                                  # wav/avi/webp
        b"OggS",                                  # ogg
        b"fLaC",                                  # flac
        b"\x1f\x8b",                             # gzip
        b"7z\xbc\xaf\x27\x1c",                  # 7z
        b"Rar!\x1a\x07",                        # rar
        b"<?xml",                                 # xml
    )

    # 텍스트로 봐줄 수 없는 제어 바이트(탭/개행/CR/FF 제외). 텍스트 파일엔 거의 없음.
    _TEXT_ALLOWED_CTRL = {0x09, 0x0A, 0x0C, 0x0D}


    def _looks_like_text(head: bytes) -> bool:
        """csv/txt/json/md/html 등 매직넘버 없는 텍스트 파일인지 휴리스틱 판정.
    NUL 이 있거나 제어문자 비율이 높으면 바이너리(=텍스트 아님)."""
        if not head:
            return False
        # UTF-16/32 텍스트는 NUL 바이트가 흔하므로 BOM 이면 먼저 텍스트로 인정.
        if head.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 LE/BE (UTF-32 BOM 도 이 prefix로 시작)
            return True
        if b"\x00" in head:
            return False
        ctrl = sum(
            1 for c in head if (c < 0x20 and c not in _TEXT_ALLOWED_CTRL) or c == 0x7F
        )
        return (ctrl / len(head)) < 0.05


    def _is_encrypted_pdf(file_path: str) -> bool:
        """PDF /Encrypt(비밀번호/DRM 암호화) 여부. ISO 32000 기준, pypdf is_encrypted 사용."""
        try:
            from pypdf import PdfReader

            return bool(PdfReader(file_path).is_encrypted)
        except Exception:
            return False  # 파싱 실패는 여기서 단정 안 함(후속 단계에서 처리)


    def _is_encrypted_office(file_path: str) -> bool:
        """암호화된 OOXML(docx/xlsx/pptx)은 OLE2 컨테이너의 'EncryptedPackage' 스트림으로
    저장된다(MS-OFFCRYPTO). olefile 로 그 스트림 존재를 확인."""
        try:
            import olefile

            if not olefile.isOleFile(file_path):
                return False
            ole = olefile.OleFileIO(file_path)
            try:
                return ole.exists("EncryptedPackage")
            finally:
                ole.close()
        except Exception:
            return False


    def _is_protected_hwp(file_path: str) -> bool:
        """암호화/배포용(DRM) HWP 감지. HWP 5.0 'FileHeader' 스트림(OLE2 내, 256B)의
    flags(offset 36, uint32 LE) bit1=password, bit2=distribution(배포용/DRM).
    이런 HWP 는 본문 스트림이 암호화돼 변환기가 정상 처리 못 함. (근거: HWP 5.0 스펙)"""
        try:
            import olefile
            import struct

            if not olefile.isOleFile(file_path):
                return False
            ole = olefile.OleFileIO(file_path)
            try:
                if not ole.exists("FileHeader"):
                    return False
                data = ole.openstream("FileHeader").read()
                if len(data) < 40 or data[:17] != b"HWP Document File":
                    return False
                flags = struct.unpack("<I", data[36:40])[0]
                return bool(flags & 0x02) or bool(flags & 0x04)  # password or distribution(DRM)
            finally:
                ole.close()
        except Exception:
            return False


    def _detect_unsupported_file(file_path: str) -> str | None:
        """입력 파일이 정상 처리 가능한지 판정(이슈 #278). 차단 사유 문자열 또는 정상이면 None.

    근거(공식):
    - 포맷 인식: 매직헤더 allowlist (file/file libmagic 정본 DB + 각 포맷 공식 스펙).
      _KNOWN_MAGIC_PREFIXES 위 주석에 출처 명시. 확장자와 무관하게 실제 바이트로 본다.
    - 암호화 자체는 바이트 패턴으로 못 본다(암호문=고엔트로피 랜덤). 포맷별 구조로 판정:
      PDF=/Encrypt(pypdf is_encrypted, ISO 32000), Office=OLE2의 EncryptedPackage(MS-OFFCRYPTO),
      HWP=FileHeader flags(HWP 5.0 스펙).
    - Fasoo 등 독점 DRM은 표준 감지법이 없다 → 알려진 매직헤더에 안 맞고 텍스트도 아닌
      바이너리(=고엔트로피 garbage)로 걸러낸다.
    """
        try:
            with open(file_path, "rb") as f:
                head = f.read(512)
        except Exception:
            return None  # 읽기 실패는 여기서 판단 안 함(후속 단계에서 처리)
        if not head:
            return "빈 파일"

        is_pdf = head.startswith(b"%PDF-")
        is_ole2 = head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        # ── Layer 1: 알려진 포맷 매직헤더인가 ──
        known = (
            is_pdf
            or is_ole2
            or head[4:8] == b"ftyp"  # mp4/mov/m4a (ISO-BMFF, offset 4)
            or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)  # mp3 frame sync
            or any(head.startswith(sig) for sig in _KNOWN_MAGIC_PREFIXES)
        )
        if not known:
            if _looks_like_text(head):
                return None  # csv/txt/json/md/html 등 텍스트 파일
            return "지원하지 않거나 손상된 파일(DRM 암호화 등)"

        # ── Layer 2: 알려진 포맷이지만 비밀번호/암호화된 경우 ──
        if is_pdf and _is_encrypted_pdf(file_path):
            return "암호화된 PDF 문서"
        if is_ole2 and _is_encrypted_office(file_path):
            return "암호화된 Office 문서"
        if is_ole2 and _is_protected_hwp(file_path):
            return "암호화/배포용(DRM) HWP 문서"
        return None


    # docling imports

    from docling.backend.docling_parse_v4_backend import DoclingParseV4DocumentBackend
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.pipeline.simple_pipeline import SimplePipeline
    # from docling.datamodel.document import ConversionStatus
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice,
        AcceleratorOptions,
        # OcrEngine,
        # PdfBackend,
        LayoutModelType,
        PdfPipelineOptions,
        TableFormerMode,
        TableStructureModelType,
        PipelineOptions,
        PaddleOcrOptions,
        UpstageOcrOptions,
    )

    from docling.document_converter import (
        DocumentConverter,
        PdfFormatOption,
        FormatOption
    )
    from docling.datamodel.pipeline_options import DataEnrichmentOptions
    from docling.prompts.prompt_manager import LLMApiError
    from docling.utils.document_enrichment import enrich_document, check_document
    from docling.utils.llm_cache import (
        classify_error as _classify_error,
        current_context as _cache_current_context,
        log_summary as _log_cache_summary,
        reset_context as _reset_cache_context,
        resolve_context as _resolve_cache_context,
        set_context as _set_cache_context,
    )
    from docling.datamodel.document import ConversionResult
    from docling_core.transforms.chunker import (
        BaseChunk,
        BaseChunker,
        DocChunk,
        DocMeta,
    )
    from docling_core.transforms.serializer.markdown import (
        MarkdownDocSerializer,
        MarkdownParams,
    )
    from docling_core.types import DoclingDocument

    from pandas import DataFrame
    import asyncio
    from docling_core.types import DoclingDocument as DLDocument
    from docling_core.types.doc.document import (
        DocumentOrigin,
        LevelNumber,
        ListItem,
        CodeItem,
        ContentLayer,
    )
    from docling_core.types.doc.labels import DocItemLabel
    from docling_core.types.doc import (
        BoundingBox,
        DocItemLabel,
        DoclingDocument,
        DocumentOrigin,
        DocItem,
        ImageRef,
        PictureItem,
        SectionHeaderItem,
        TableItem,
        TextItem,
        PageItem,
        ProvenanceItem
    )
    from docling_core.types.doc.utils import relative_path
    from docling.datamodel.settings import settings

    from collections import Counter
    import re
    import json
    import time
    import warnings
    from typing import Iterable, Iterator, Optional, Union

    from pydantic import BaseModel, ConfigDict, PositiveInt, TypeAdapter, model_validator
    from typing_extensions import Self

    try:
        from genon.preprocessor.facade.enrichment.custom_fields_enricher import CustomFieldsEnricher as _CustomFieldsEnricher
    except ImportError:
        _CustomFieldsEnricher = None  # type: ignore[assignment,misc]
    try:
        from genon.preprocessor.facade.enrichment.metadata_enricher import MetadataEnricher as _MetadataEnricher
    except ImportError:
        _MetadataEnricher = None  # type: ignore[assignment,misc]

    from genon.preprocessor.facade.enrichment.enrichment_config import EnrichmentConfig
    from genon.preprocessor.facade.enrichment.page_description import (
        PageDescriptionOptions,
        collect_page_texts,
        describe_pages,
    )
    from genon.preprocessor.facade.enrichment.image_description import (
        ImageDescriptionOptions,
        ImageDescriptionEnricher,
        resolve_runtime_image_options,
    )
    from genon.preprocessor.facade.enrichment.table_description import (
        TableDescriptionOptions,
        TableDescriptionEnricher,
        TableDescriptionExtractor,
        refined_html_to_format,
        resolve_runtime_table_options,
    )
    from genon.preprocessor.facade.enrichment.doc_summary import (
        DocSummaryOptions,
        DocSummaryEnricher,
        resolve_runtime_doc_summary_options,
    )
    from genon.preprocessor.facade.enrichment.field_transforms import (
        DEFAULT_METADATA_FIELD_TRANSFORMS,
        apply_field_transforms,
        extract_metadata_from_document,
        serialize_metadata_value_for_output,
    )

    try:
        import semchunk
        from transformers import AutoTokenizer, PreTrainedTokenizerBase
    except ImportError:
        raise RuntimeError(
            "Module requires 'chunking' extra; to install, run: "
            "`pip install 'docling-core[chunking]'`"
        )

    try:
        from genos_utils import upload_files
    except ImportError:
        upload_files = None

    # HWP/HWPX 품질 복구(선택적). 모듈 로드 실패 시 None → 복구 미적용(기존 동작 유지).
    try:
        from genon.preprocessor.converters.hwp_recovery import HwpQualityRecovery
    except ImportError:
        HwpQualityRecovery = None


    # ============================================================
    # 설정 로딩 헬퍼 (from parser_processor.py)
    # ============================================================

    def _warn_unresolved_placeholders(cfg: dict, config_path: str) -> None:
        """config 에 남아있는 미치환 플레이스홀더(<UPPER_SNAKE>)를 탐지해 경고한다.

    Site 배포 시 OCR/Layout/Enrichment endpoint·serving ID 등의 치환 누락을 조기에
    드러내기 위함. fail-fast 하지 않고(기동 보존) WARNING 로그만 남긴다.
    """
        pattern = re.compile(r"<[A-Z0-9_]+>")
        found = []

        def _scan(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    _scan(v, f"{path}.{k}" if path else str(k))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    _scan(v, f"{path}[{i}]")
            elif isinstance(node, str):
                for ph in pattern.findall(node):
                    found.append((path, ph))

        _scan(cfg, "")
        if found:
            lines = "\n".join(f"  - {path}: {ph}" for path, ph in found)
            _log.warning(
                "[DocumentProcessor] 미치환 설정 플레이스홀더가 발견되었습니다 "
                f"(config='{config_path}'). Site 배포 시 실제 값으로 변경하세요:\n{lines}"
            )


    def _load_config(config_path: str) -> dict:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if not isinstance(cfg, dict):
            raise ValueError(f"Invalid config format: expected mapping, got {type(cfg).__name__}")
        _warn_unresolved_placeholders(cfg, config_path)
        return cfg


    def _as_dict(value: Any) -> dict:
        return value if isinstance(value, dict) else {}


    def _parse_optional_bool(value: Any, key: str = "") -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "y", "on"}:
                return True
            if text in {"0", "false", "no", "n", "off"}:
                return False
        if key:
            _log.warning(f"[DocumentProcessor] Invalid bool value for '{key}': {value!r}. Fallback to default.")
        return None


    def _parse_optional_int(value: Any, key: str = "") -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            if key:
                _log.warning(f"[DocumentProcessor] Invalid int value for '{key}': {value!r}. Fallback to default.")
            return None


    _MIN_CHUNK_SIZE = 1024


    def _clamp_chunk_size(size: Optional[int]) -> Optional[int]:
        """chunk_size 가 0 초과이면서 _MIN_CHUNK_SIZE 미만이면 _MIN_CHUNK_SIZE 로 보정.
    0(=분할 안 함) 과 None 은 그대로 둔다."""
        if size is not None and 0 < size < _MIN_CHUNK_SIZE:
            _log.info(f"[chunk_size] {size} < {_MIN_CHUNK_SIZE} → {_MIN_CHUNK_SIZE} 로 보정")
            return _MIN_CHUNK_SIZE
        return size


    def _parse_optional_float(value: Any, key: str = "") -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            if key:
                _log.warning(f"[DocumentProcessor] Invalid float value for '{key}': {value!r}. Fallback to default.")
            return None


    def _as_int_flag(value: Any, default: int = 0) -> int:
        """Normalize runtime feature flags to 0 or 1."""
        if value is None:
            return default
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if int(value) == 1 else 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return 1
            if normalized in {"0", "false", "no", "n", "off"}:
                return 0
        return default


    def _resolve_chunk_mode(kwargs: dict, yaml_default: str) -> str:
        """청킹 병합 모드 결정. 우선순위: 요청 chunk_mode > yaml > 'split_only'.

    chunk_mode 는 문자열('split_only'|'resize_all') 또는 0/1 플래그를 받는다.
    0(false/no/off) → 'split_only'(구조 경계 보존, 초과 그룹만 분할),
    1(true/yes/on)  → 'resize_all'(인접 섹션을 chunk_size 한도까지 greedy 병합).
    (chunk_mode=0 은 falsy 라 `x or default` 로는 무시되므로 `is not None` 으로 판별한다.)
    """
        raw = kwargs.get("chunk_mode")
        if raw is not None:
            # 숫자 0/0.0/1/1.0 은 문자열 파싱 전에 정규화(JSON number 로 오는 경우 대응).
            # bool 은 제외 — 아래 문자열 분기의 "true"/"false" 로 처리한다(True==1 오분류 방지).
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw in (0, 1):
                return "resize_all" if raw == 1 else "split_only"
            s = str(raw).strip().lower()
            if s in {"split_only", "resize_all"}:
                return s
            if s in {"1", "true", "yes", "on"}:
                return "resize_all"
            if s in {"0", "false", "no", "off"}:
                return "split_only"
        mode = str(yaml_default or "").strip().lower()
        return mode if mode in {"split_only", "resize_all"} else "split_only"


    def _copy_enrichment_options(options, **updates):
        """DataEnrichmentOptions 를 얕게 복제하며 지정 필드를 override(원본 불변)."""
        try:
            return options.model_copy(update=updates)
        except AttributeError:
            import copy as _copy
            cloned = _copy.copy(options)
            for key, value in updates.items():
                setattr(cloned, key, value)
            return cloned


    # #329: LLM 캐시 / error_policy 컨텍스트 해석은 docling.utils.llm_cache.resolve_context
    # (3개 facade 공용, cross-facade import 회피)를 _resolve_cache_context 로 재노출해 사용한다.


    def _handle_stage_error(exc: Exception, stage: str) -> None:
        """enrichment 단계 실패 처리(#329).

    - lenient(기본): 기존처럼 warning 후 계속(soft-fail, 하위호환).
    - strict: stage/error_type 를 실어 GenosServiceException 으로 재-raise(Temporal 경로).
    error_policy 는 요청 스코프 CacheContext 에서 읽는다(단일 소스).
    """
        error_type = _classify_error(exc)
        if _cache_current_context().error_policy == "strict":
            raise GenosServiceException(
                "1", f"[{stage}] {exc}", stage=stage, error_type=error_type
            ) from exc
        _log.warning(f"[DocumentProcessor] {stage} enrichment skipped ({error_type}): {exc}")


    # pdf_pipeline.device / pdf_pipeline.table_structure_mode 의 yaml 문자열 → docling enum 매핑.
    # 키가 없거나 알 수 없는 값이면 호출부에서 경고 + 기본값으로 폴백한다 (startup 견고성).
    _ACCELERATOR_DEVICE_MAP = {
        "auto": AcceleratorDevice.AUTO,
        "cpu": AcceleratorDevice.CPU,
        "cuda": AcceleratorDevice.CUDA,
        "mps": AcceleratorDevice.MPS,
    }

    _TABLE_FORMER_MODE_MAP = {
        "accurate": TableFormerMode.ACCURATE,
        "fast": TableFormerMode.FAST,
    }


    def _resolve_default_intelligent_config_path() -> str:
        base_dir = Path(__file__).resolve().parent
        local_config = (base_dir / "../resource_dev/intelligent_processor_config.yaml").resolve()
        default_config = (base_dir / "../resource/intelligent_processor_config.yaml").resolve()

        if local_config.exists():
            return str(local_config)
        return str(default_config)


    # 청킹용 토크나이저 기본 경로 (config 미지정 시 현행 동작 유지)
    _DEFAULT_TOKENIZER_LOCAL_PATH = "/models/doc_parser_models/sentence-transformers-all-MiniLM-L6-v2"
    _DEFAULT_TOKENIZER_ID = "sentence-transformers/all-MiniLM-L6-v2"

    # PDF 변환에서 제외(직접 처리)할 엑셀 계열 포맷(이슈 #288).
    # PDF 변환 시 한 행이 페이지 경계로 쪼개지는 논리 오류가 생기므로 변환하지 않고 직접 처리한다.
    _XLSX_DIRECT_EXTS = {".xlsx", ".xlsm", ".csv"}


    def _resolve_tokenizer(chunking_cfg: dict):
        """chunking config 로부터 토크나이저를 결정한다.

    tokenizer_path 가 실제 존재하면 그 로컬 경로를, 없으면 tokenizer_id(HF) 로 폴백한다
    (외부 네트워크 차단 환경 대비). config 미지정 시 기본값은 현행 하드코딩 값과 동일.
    """
        local = chunking_cfg.get("tokenizer_path") or _DEFAULT_TOKENIZER_LOCAL_PATH
        hf_id = chunking_cfg.get("tokenizer_id") or _DEFAULT_TOKENIZER_ID
        return Path(local) if Path(local).exists() else hf_id


    # ============================================
    #
    # Copyright IBM Corp. 2024 - 2024
    # SPDX-License-Identifier: MIT
    #

    """Chunker implementation leveraging the document structure."""

    class GenosSmartChunker(BaseChunker):
        """토큰 제한을 고려하여 섹션별 청크를 분할하고 병합하는 청커 (v2)"""

        model_config = ConfigDict(arbitrary_types_allowed=True)

        tokenizer: Union[PreTrainedTokenizerBase, str, Path] = (
                Path(_DEFAULT_TOKENIZER_LOCAL_PATH)
                if Path(_DEFAULT_TOKENIZER_LOCAL_PATH).exists()
                else _DEFAULT_TOKENIZER_ID
            )
        max_tokens: int = 1024
        merge_peers: bool = True
        # 토큰 수 계산 방식. "char"(default)=문자 수 기준 | "huggingface"=HF 토크나이저 기준
        tokenizer_type: str = "char"
        # 청킹 모드. "split_only"(기본)=chunk_size 초과 청크만 분할(구조 보존) | "resize_all"=모든 청크를 chunk_size 에 맞게 병합/분할
        chunk_mode: str = "split_only"

        # _inner_chunker: BaseChunker = None
        _tokenizer: PreTrainedTokenizerBase = None
        merge_list_items: bool = True

        @model_validator(mode="after")
        def _initialize_components(self) -> Self:
            # 토크나이저 초기화
            mode = (self.tokenizer_type or "char").strip().lower()
            if mode not in {"char", "huggingface"}:
                _log.warning(f"[GenosSmartChunker] Unknown tokenizer_type '{mode}', fallback to 'char'.")
                mode = "char"
            self.tokenizer_type = mode
            if mode == "char":
                # 문자 수 기반: HF 토크나이저 로드 불필요 (외부 모델 의존 제거)
                self._tokenizer = None
            else:
                self._tokenizer = (
                    self.tokenizer
                    if isinstance(self.tokenizer, PreTrainedTokenizerBase)
                    else AutoTokenizer.from_pretrained(self.tokenizer)
                )
            return self

        def preprocess(self, dl_doc: DLDocument, **kwargs: Any) -> Iterator[BaseChunk]:
            """문서의 모든 아이템을 헤더 정보와 함께 청크로 생성

        Args:
            dl_doc: 청킹할 문서

        Yields:
            문서의 모든 아이템을 포함하는 하나의 청크
        """
            # 모든 아이템과 헤더 정보 수집
            all_items = []
            all_header_info = []  # 각 아이템의 헤더 정보
            current_heading_by_level: dict[LevelNumber, str] = {}
            all_header_short_info = []  # 각 아이템의 짧은 헤더 정보
            current_heading_short_by_level: dict[LevelNumber, str] = {}
            list_items: list[TextItem] = []

            # iterate_items()로 수집된 아이템들의 self_ref 추적
            processed_refs = set()

            # 모든 아이템 순회
            for item, level in dl_doc.iterate_items(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}, traverse_pictures=True):
                if hasattr(item, 'self_ref'):
                    processed_refs.add(item.self_ref)

                if not isinstance(item, DocItem):
                    continue

                # 리스트 아이템 병합 처리
                if self.merge_list_items:
                    if isinstance(item, ListItem) or (
                        isinstance(item, TextItem) and item.label == DocItemLabel.LIST_ITEM
                    ):
                        list_items.append(item)
                        continue
                    elif list_items:
                        # 누적된 리스트 아이템들을 추가
                        for list_item in list_items:
                            all_items.append(list_item)
                            # 리스트 아이템의 헤더 정보 저장
                            all_header_info.append({k: v for k, v in current_heading_by_level.items()})
                            all_header_short_info.append({k: v for k, v in current_heading_short_by_level.items()})
                        list_items = []

                # 섹션 헤더 처리
                if isinstance(item, SectionHeaderItem) or (
                    isinstance(item, TextItem) and
                    item.label in [DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE]
                ):
                    # 새로운 헤더 레벨 설정
                    header_level = (
                        item.level if isinstance(item, SectionHeaderItem)
                        else (0 if item.label == DocItemLabel.TITLE else 1)
                    )
                    current_heading_by_level[header_level] = item.text
                    current_heading_short_by_level[header_level] = item.orig  # 첫 단어로 짧은 헤더 정보 설정

                    # 더 깊은 레벨의 헤더들 제거
                    keys_to_del = [k for k in current_heading_by_level if k > header_level]
                    for k in keys_to_del:
                        current_heading_by_level.pop(k, None)
                    keys_to_del_short = [k for k in current_heading_short_by_level if k > header_level]
                    for k in keys_to_del_short:
                        current_heading_short_by_level.pop(k, None)

                    # 헤더 아이템도 추가 (헤더 자체도 아이템임)
                    all_items.append(item)
                    all_header_info.append({k: v for k, v in current_heading_by_level.items()})
                    all_header_short_info.append({k: v for k, v in current_heading_short_by_level.items()})
                    continue

                if (isinstance(item, TextItem) or
                    isinstance(item, ListItem) or
                    isinstance(item, CodeItem) or
                    isinstance(item, TableItem) or
                    isinstance(item, PictureItem)):
                    # if item.label in [DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER]:
                    #     item.text = ""
                    all_items.append(item)
                    # 현재 아이템의 헤더 정보 저장
                    all_header_info.append({k: v for k, v in current_heading_by_level.items()})
                    all_header_short_info.append({k: v for k, v in current_heading_short_by_level.items()})

            # 마지막 리스트 아이템들 처리
            if list_items:
                for list_item in list_items:
                    all_items.append(list_item)
                    all_header_info.append({k: v for k, v in current_heading_by_level.items()})
                    all_header_short_info.append({k: v for k, v in current_heading_short_by_level.items()})

            # iterate_items()에서 누락된 테이블들을 별도로 추가
            missing_tables = []
            for table in dl_doc.tables:
                table_ref = getattr(table, 'self_ref', None)
                if table_ref not in processed_refs:
                    missing_tables.append(table)

            # 누락된 테이블들을 문서 앞부분에 추가 (페이지 1의 테이블들일 가능성이 높음)
            if missing_tables:
                for missing_table in missing_tables:
                    # 첫 번째 위치에 삽입 (헤더 테이블일 가능성이 높음)
                    all_items.insert(0, missing_table)
                    all_header_info.insert(0, {})  # 빈 헤더 정보
                    all_header_short_info.insert(0, {})  # 빈 짧은 헤더 정보

            # 아이템이 없으면 빈 문서
            if not all_items:
                return

            # 모든 아이템을 하나의 청크로 반환 (HybridChunker에서 분할)
            # headings는 None으로 설정하고, 헤더 정보는 별도로 관리
            chunk = DocChunk(
                text="",  # 텍스트는 HybridChunker에서 생성
                meta=DocMeta(
                    doc_items=all_items,
                    headings=None,  # DocMeta의 원래 형식 유지
                    captions=None,
                    origin=dl_doc.origin,
                ),
            )
            # 헤더 정보를 별도 속성으로 저장
            chunk._header_info_list = all_header_info
            chunk._header_short_info_list = all_header_short_info  # 짧은 헤더 정보도 저장
            yield chunk

        def _count_tokens(self, text: str) -> int:
            """텍스트의 토큰 수 계산 (안전한 분할 처리)"""
            if not text:
                return 0

            if self._tokenizer is None:   # 문자 수 기반
                return len(text)

            # 텍스트를 더 작은 단위로 분할하여 계산
            max_chunk_length = 300  # 더 안전한 길이로 설정
            total_tokens = 0

            # 텍스트를 줄 단위로 먼저 분할
            lines = text.split('\n')
            current_chunk = ""

            for line in lines:
                # 현재 청크에 줄을 추가했을 때 길이 확인
                temp_chunk = current_chunk + '\n' + line if current_chunk else line

                if len(temp_chunk) <= max_chunk_length:
                    current_chunk = temp_chunk
                else:
                    # 현재 청크가 있으면 토큰 계산
                    if current_chunk:
                        try:
                            total_tokens += len(self._tokenizer.tokenize(current_chunk))
                        except Exception:
                            total_tokens += int(len(current_chunk.split()) * 1.3)  # 대략적인 계산

                    # 새로운 청크 시작
                    current_chunk = line

            # 마지막 청크 처리
            if current_chunk:
                try:
                    total_tokens += len(self._tokenizer.tokenize(current_chunk))
                except Exception:
                    total_tokens += int(len(current_chunk.split()) * 1.3)  # 대략적인 계산

            return total_tokens

        def _generate_text_from_items_with_headers(self, items: list[DocItem],
                                                  header_info_list: list[dict],
                                                  dl_doc: DoclingDocument,
                                                  **kwargs) -> str:
            """DocItem 리스트로부터 헤더 정보를 포함한 텍스트 생성"""
            text_parts = []
            current_section_headers = {}  # 현재 섹션의 헤더 정보

            for i, item in enumerate(items):
                item_headers = header_info_list[i] if i < len(header_info_list) else {}

                # 헤더 정보가 변경된 경우 (새로운 섹션 시작)
                if item_headers != current_section_headers:
                    # 변경된 헤더 레벨들만 추가
                    headers_to_add = []
                    for level in sorted(item_headers.keys()):
                        # 이전 섹션과 다른 헤더만 추가
                        if (level not in current_section_headers or
                            current_section_headers[level] != item_headers[level]):
                            # 해당 레벨까지의 모든 상위 헤더 포함
                            for l in sorted(item_headers.keys()):
                                if l < level:
                                    headers_to_add.append(item_headers[l])
                                elif l == level:
                                    headers_to_add.append('')

                            break

                    # 헤더가 있으면 추가
                    if headers_to_add:
                        header_text = ", ".join(headers_to_add)
                        if header_text not in text_parts:
                            text_parts.append(header_text)

                    current_section_headers = item_headers.copy()

                # 아이템 텍스트 추가
                if isinstance(item, TableItem):
                    table_text = self._extract_table_text(item, dl_doc, **kwargs)
                    if table_text:
                        text_parts.append(table_text)
                elif hasattr(item, 'text') and item.text:
                    # 타이틀과 섹션 헤더 처리 개선
                    # is_section_header = (
                    #     isinstance(item, SectionHeaderItem) or
                    #     (isinstance(item, TextItem) and
                    #      item.label in [DocItemLabel.SECTION_HEADER])  # TITLE은 제외
                    # )

                    # 타이틀은 항상 포함, 섹션 헤더는 중복 방지를 위해 스킵
                    # if not is_section_header:
                    # 20250909, shkim, text_parts에 없는 경우만 추가. 섹션헤더가 반복해서 추가되는 것 방지
                    if item.text not in text_parts:
                        text_parts.append(item.text)
                elif isinstance(item, PictureItem):
                    picture_text = self._extract_picture_annotation_text(item)
                    if picture_text and picture_text not in text_parts:
                        text_parts.append(picture_text)

            result_text = self.delim.join(text_parts)
            return result_text

        @staticmethod
        def _extract_picture_annotation_text(item: PictureItem) -> str:
            """PictureItem annotation의 텍스트를 단일 문자열로 추출."""
            texts: list[str] = []
            for annotation in getattr(item, "annotations", []) or []:
                text = str(getattr(annotation, "text", "") or "").strip()
                if text:
                    texts.append(text)
            if not texts:
                return ""
            # 동일 annotation 중복 주입 방지
            return "\n".join(dict.fromkeys(texts))

        @staticmethod
        def _resolve_table_format(kwargs: dict) -> str:
            """표 직렬화 형식 결정: table_format(html|markdown) 우선, 없으면 레거시 export_to_html(1/0)."""
            fmt = kwargs.get("table_format")
            if fmt is None:
                return "html" if kwargs.get("export_to_html", 1) == 1 else "markdown"
            fmt = str(fmt).strip().lower()
            return "markdown" if fmt == "markdown" else "html"

        @staticmethod
        def _resolve_compact_tables(kwargs: dict) -> bool:
            """markdown 표를 compact(컬럼 정렬 패딩 제거)로 낼지 결정. 기본 True."""
            return bool(kwargs.get("compact_tables", True))

        def _extract_table_text(self, table_item: TableItem, dl_doc: DoclingDocument, **kwargs) -> str:
            """테이블 청크 텍스트를 만든다.

        표 description(refine/요약) annotation 이 있으면 반영한다:
        - refine ON: 재구성 HTML 로 표 본체 교체
        - 요약 존재: '\\n---\\n[표 설명]\\n<요약>' 을 항상 병기
        annotation 이 없으면(기본) 기존 export 결과를 그대로 반환(회귀 없음).
        """
            refined_html = TableDescriptionExtractor.extract_refined_html(table_item)
            table_summary = TableDescriptionExtractor.extract_summary(table_item)

            # refine 은 항상 HTML 로 재구성 → output table_format 에 맞춰 변환(markdown 등).
            refined = refined_html_to_format(
                refined_html, self._resolve_table_format(kwargs), self._resolve_compact_tables(kwargs))
            base_text = refined or self._compute_table_base_text(table_item, dl_doc, **kwargs)
            if table_summary:
                if base_text:
                    return base_text + "\n---\n[표 설명]\n" + table_summary
                return "[표 설명]\n" + table_summary
            return base_text

        def _compute_table_base_text(self, table_item: TableItem, dl_doc: DoclingDocument, **kwargs) -> str:
            """테이블에서 텍스트를 추출하는 일반화된 메서드"""
            try:
                if self._resolve_table_format(kwargs) == "markdown":
                    if self._resolve_compact_tables(kwargs):
                        # TableItem.export_to_markdown() 은 compact 옵션이 없어 직접 serializer 구성
                        # (컬럼 정렬 패딩 제거 → 대형 표 markdown 크기 대폭 축소)
                        table_text = MarkdownDocSerializer(
                            doc=dl_doc,
                            params=MarkdownParams(compact_tables=True),
                        ).serialize(item=table_item).text
                    else:
                        table_text = table_item.export_to_markdown(dl_doc)
                else:
                    table_text = table_item.export_to_html(dl_doc)
                if table_text and table_text.strip():
                    return table_text
            except Exception:
                pass

            # export_to_markdown 실패 시 테이블 셀 데이터에서 직접 텍스트 추출
            try:
                if hasattr(table_item, 'data') and table_item.data:
                    cell_texts = []

                    # table_cells에서 텍스트 추출
                    if hasattr(table_item.data, 'table_cells'):
                        for cell in table_item.data.table_cells:
                            if hasattr(cell, 'text') and cell.text and cell.text.strip():
                                cell_texts.append(cell.text.strip())

                    # grid에서 텍스트 추출 (table_cells가 없는 경우)
                    elif hasattr(table_item.data, 'grid') and table_item.data.grid:
                        for row in table_item.data.grid:
                            if isinstance(row, list):
                                for cell in row:
                                    if hasattr(cell, 'text') and cell.text and cell.text.strip():
                                        cell_texts.append(cell.text.strip())

                    # 추출된 셀 텍스트들을 결합
                    if cell_texts:
                        return ' '.join(cell_texts)
            except Exception:
                pass

            # 모든 방법 실패 시 item.text 사용 (있는 경우)
            if hasattr(table_item, 'text') and table_item.text:
                return table_item.text

            return ""

        @staticmethod
        def _render_table_row_html(row: list, num_cols: int) -> str:
            """grid 한 행을 <tr>..</tr> HTML 로 렌더(docling HTMLTableSerializer 형식 모방).
        colspan 중복 셀은 제거하고 헤더 계열 셀은 <th>, 그 외는 <td> 로 낸다.
        (row_span==1 전제 — 호출부에서 세로 병합 표는 분할하지 않음)
        """
            import html as _html
            cells = []
            for j in range(num_cols):
                cell = row[j]
                if cell.start_col_offset_idx != j:  # colspan 으로 이미 렌더된 셀 스킵
                    continue
                is_header = bool(
                    getattr(cell, "column_header", False)
                    or getattr(cell, "row_header", False)
                    or getattr(cell, "row_section", False)
                )
                tag = "th" if is_header else "td"
                attrs = f' colspan="{cell.col_span}"' if cell.col_span > 1 else ""
                cells.append(f"<{tag}{attrs}>{_html.escape((cell.text or '').strip())}</{tag}>")
            return "<tr>" + "".join(cells) + "</tr>"

        @staticmethod
        def _render_table_row_md(row: list, num_cols: int) -> str:
            """grid 한 행을 markdown 표 행 `| c1 | c2 | ... |` 로 렌더(파이프는 이스케이프).
        markdown 은 colspan/rowspan 미지원이라 num_cols 전 컬럼을 그대로 낸다."""
            cells = []
            for j in range(num_cols):
                text = (row[j].text or "").strip().replace("|", "\\|").replace("\n", " ")
                cells.append(text)
            return "| " + " | ".join(cells) + " |"

        @staticmethod
        def _sheet_prefix(table_item: TableItem, dl_doc: DoclingDocument) -> str:
            """xlsx docling 표의 부모 그룹(name='sheet: X')에서 시트명을 뽑아 '시트명: X\\n' 접두 생성.
        시트 그룹이 없으면 '' 반환(PDF 등 비-xlsx 문서엔 실질 미적용)."""
            try:
                parent = table_item.parent.resolve(dl_doc) if getattr(table_item, "parent", None) else None
                name = getattr(parent, "name", None)
            except Exception:
                name = None
            if not name:
                return ""
            if name.startswith("sheet: "):
                name = name[len("sheet: "):]
            name = name.strip()
            return f"시트명: {name}\n" if name else ""

        def _table_item_to_texts(self, table_item: TableItem, dl_doc: DoclingDocument,
                                 h_short: dict, **kwargs) -> list[str]:
            """표를 청크 텍스트 목록으로 변환. chunk_size(max_tokens) 초과 시 row 단위로 분할하고
        각 분할 청크에 헤더 행(선두 column_header 행 + 다음 컬럼명 행)을 반복 포함한다.

        미초과(또는 max_tokens<=0)면 현행과 동일하게 단일 청크(docling export_to_html) 1개를 반환.
        모든 청크(단일/분할)에 시트명 접두(`시트명: X\\n`)를 붙인다.
        """
            sheet_prefix = self._sheet_prefix(table_item, dl_doc)
            single = sheet_prefix + self._generate_section_text_with_heading([table_item], [h_short], dl_doc, **kwargs)

            # 재구성 HTML(refine)이 있으면 grid/구조가 달라 row 분할이 무의미 → 단일 청크로 둔다.
            if TableDescriptionExtractor.extract_refined_html(table_item):
                return [single]
            # 요약(summary)만 있는 경우: chunk_size 초과 표는 정상적으로 row 분할하고,
            # 요약은 마지막 분할 청크에만 1회 덧붙인다(중복 방지). single 경로는 이미 요약 포함.
            table_summary = TableDescriptionExtractor.extract_summary(table_item)

            if self.max_tokens is None or self.max_tokens <= 0:
                return [single]
            if self._count_tokens(single) <= self.max_tokens:
                return [single]

            try:
                grid = table_item.data.grid
                num_cols = table_item.data.num_cols
            except Exception:
                return [single]
            if not grid or not num_cols:
                return [single]

            # 헤더 행 수: 선두의 연속된 헤더 플래그 행 + 바로 다음 행(컬럼명 추정)
            flag_n = 0
            for row in grid:
                if any(getattr(c, "column_header", False) or getattr(c, "row_header", False)
                       or getattr(c, "row_section", False) for c in row):
                    flag_n += 1
                else:
                    break
            header_n = flag_n + 1
            if header_n >= len(grid):  # 데이터 행이 없음 → 분할 불가
                return [single]

            header_rows = grid[:header_n]
            data_rows = grid[header_n:]

            # 세로 병합(row_span>1)이 데이터 행에 있으면 row 분할이 구조를 깨뜨리므로 분할하지 않는다.
            # (헤더 영역의 세로병합은 헤더 블록이 매 청크에 통째로 반복되므로 무해)
            if any(getattr(c, "row_span", 1) > 1 for r in data_rows for c in r):
                return [single]

            # heading 접두(_generate_section_text_with_heading 과 동일 규칙). xlsx 는 보통 공백.
            merged = {lvl: t for lvl, t in (h_short or {}).items() if t}
            heading = ", ".join(merged[l] for l in sorted(merged)) if merged else ""
            prefix = (heading + ", ") if heading else ""

            # table_format 에 맞춰 헤더/데이터 행을 렌더하고 버킷을 감싼다(html | markdown).
            if self._resolve_table_format(kwargs) == "markdown":
                render_row = self._render_table_row_md
                header_block = [render_row(r, num_cols) for r in header_rows]
                header_block.append("| " + " | ".join(["---"] * num_cols) + " |")

                def wrap(data_rendered: list) -> str:
                    return sheet_prefix + prefix + "\n".join(header_block + data_rendered)
            else:
                render_row = self._render_table_row_html
                header_inner = "".join(render_row(r, num_cols) for r in header_rows)

                def wrap(data_rendered: list) -> str:
                    return sheet_prefix + prefix + "<table><tbody>" + header_inner + "".join(data_rendered) + "</tbody></table>"

            texts: list[str] = []
            cur: list[str] = []
            for r in data_rows:
                rr = render_row(r, num_cols)
                if cur and self._count_tokens(wrap(cur + [rr])) > self.max_tokens:
                    texts.append(wrap(cur))
                    cur = [rr]
                else:
                    cur.append(rr)
            if cur:
                texts.append(wrap(cur))
            if not texts:
                return [single]
            if table_summary:
                texts[-1] = texts[-1] + "\n---\n[표 설명]\n" + table_summary
            return texts

        def _extract_used_headers(self, header_info_list: list[dict]) -> Optional[list[str]]:
            """헤더 정보 리스트에서 실제 사용되는 모든 헤더들을 level 순서대로 추출하고 ', '로 연결"""
            if not header_info_list:
                return None

            all_headers = [] # header 순서대로 추가
            seen_headers = set()  # 중복 방지용

            for header_info in header_info_list:
                if header_info:
                    for level in sorted(header_info.keys()):
                        header_text = header_info[level]
                        if header_text and header_text not in seen_headers:
                            all_headers.append(header_text)
                            seen_headers.add(header_text)

            return all_headers if all_headers else None

        def _split_table_text(self, table_text: str, max_tokens: int) -> list[str]:
            """테이블 텍스트를 토큰 제한에 맞게 분할 (단순 토큰 수 기준)"""
            if not table_text:
                return [table_text]

            # 전체 테이블이 토큰 제한 내인지 확인
            if self._count_tokens(table_text) <= max_tokens:
                return [table_text]

            # 단순히 토큰 수 기준으로 텍스트 분할
            # semchunk 사용하여 토큰 제한에 맞게 분할 (char 모드는 문자 수 카운터 len 사용)
            counter = len if self._tokenizer is None else self._tokenizer
            chunker = semchunk.chunkerify(counter, chunk_size=max_tokens)
            chunks = chunker(table_text)
            return chunks if chunks else [table_text]

        def _is_section_header(self, item: DocItem) -> bool:
            """아이템이 section header인지 확인"""
            return (isinstance(item, SectionHeaderItem) or
                    (isinstance(item, TextItem) and
                     item.label in [DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE]))

        def _get_section_header_level(self, item: DocItem) -> Optional[int]:
            """Section header의 level을 반환"""
            if isinstance(item, SectionHeaderItem):
                return item.level
            elif isinstance(item, TextItem):
                if item.label == DocItemLabel.TITLE:
                    return 0
                elif item.label == DocItemLabel.SECTION_HEADER:
                    return 1
            return None

        def _generate_section_text_with_heading(self, section_items: list[DocItem],
                                                section_header_infos: list[dict],
                                                dl_doc: DoclingDocument,
                                                **kwargs) -> str:
            """섹션의 텍스트를 생성하되, 앞에 heading을 붙임"""
            # 첫 번째 item의 header_info에서 heading 추출
            if section_header_infos and section_header_infos[0]:
                merged_headers = {}
                for level, header_text in section_header_infos[0].items():
                    if header_text:
                        merged_headers[level] = header_text

                # level 순서대로 정렬해서 ', '로 연결
                if merged_headers:
                    sorted_levels = sorted(merged_headers.keys())
                    headers = [merged_headers[level] for level in sorted_levels]
                    heading_text = ', '.join(headers)
                else:
                    heading_text = ""
            else:
                heading_text = ""

            # 섹션의 일반 텍스트 생성
            section_text = self._generate_text_from_items_with_headers(
                section_items, section_header_infos, dl_doc, **kwargs
            )

            # heading이 있으면 앞에 붙이기
            if heading_text:
                return heading_text + ", " + section_text
            else:
                return section_text

        def _split_document_by_tokens(self, doc_chunk: DocChunk, dl_doc: DoclingDocument, **kwargs) -> list[DocChunk]:
            """문서를 토큰 제한에 맞게 분할 (v2: 섹션 헤더 기준으로 분할 후 max_tokens로 병합)"""
            items = doc_chunk.meta.doc_items
            header_info_list = getattr(doc_chunk, '_header_info_list', [])
            header_short_info_list = getattr(doc_chunk, '_header_short_info_list', [])

            if not items:
                return []

            # ================================================================
            # 헬퍼 함수들
            # ================================================================

            def get_header_level(header_infos, *, first=False, default=-1):
                """header_infos에서 최종 레벨 계산"""
                if not header_infos:
                    return default
                info = header_infos[0] if first else header_infos[-1]
                return max(info.keys(), default=default)

            def get_current_chunk(doc_chunk: DocChunk, merged_texts: list[str], merged_header_short_infos: list[dict], merged_items: list[DocItem]):
                """현재까지 병합된 내용으로 DocChunk 생성"""
                # doc_items 가 비면 DocMeta(min_length=1) 검증에서 크래시하므로 스킵한다.
                # (chunk_size 분할 시 헤더만 남고 items 가 빈 무의미 그룹이 생길 수 있음)
                if not merged_texts or not merged_items:
                    return None
                chunk_text = "\n".join(merged_texts)
                used_headers = self._extract_used_headers(merged_header_short_infos)

                return DocChunk(
                        text=chunk_text,
                        meta=DocMeta(
                            doc_items=merged_items,
                            headings=used_headers,
                            captions=None,
                            origin=doc_chunk.meta.origin,
                        )
                    )

            def get_text_from_item(item: DocItem) -> str:
                """DocItem에서 텍스트 추출"""
                if isinstance(item, TableItem):
                    return self._extract_table_text(item, dl_doc, **kwargs)
                elif hasattr(item, 'text') and item.text:
                    return item.text
                elif isinstance(item, PictureItem):
                    text = ""
                    for annotation in item.annotations:
                        if hasattr(annotation, 'text'):
                            text += annotation.text
                    return text
                return ""

            def split_items_evenly_by_tokens(item_token_counts, max_tokens):
                n = len(item_token_counts)
                total = sum(item_token_counts)
                if n == 0:
                    return []
                if total <= max_tokens:
                    return [(0, n)]   # ✅ 항상 (a,b)

                k = math.ceil(total / max_tokens)
                target = total / k

                P = [0]
                for c in item_token_counts:
                    P.append(P[-1] + c)

                cuts = [0]
                used = {0}
                for t in range(1, k):
                    goal = t * target
                    j = bisect.bisect_left(P, goal)

                    cand = []
                    if 0 < j < len(P): cand.append(j)
                    if 0 <= j-1 < len(P): cand.append(j-1)

                    best = None
                    best_dist = float("inf")
                    for x in cand:
                        if x in used:
                            continue
                        if x <= cuts[-1]:
                            continue
                        if x >= len(P)-1:  # n
                            continue
                        dist = abs(P[x] - goal)
                        if dist < best_dist:
                            best_dist = dist
                            best = x

                    if best is None:
                        best = min(max(cuts[-1] + 1, 1), len(P)-2)

                    cuts.append(best)
                    used.add(best)

                cuts.append(n)

                # 폭 0 범위(a==b)는 빈 items 그룹을 만들어 하위에서 무의미 청크가 되므로 제외.
                return [(a, b) for a, b in zip(cuts[:-1], cuts[1:]) if a < b]

            def adjust_captions(items_group):

                b_modified = False
                for idx, group in enumerate(items_group):
                    if group is None:
                        continue
                    item = group[0][0]
                    ref_idx_list = []
                    if hasattr(item, 'captions') and item.captions:
                        for cap in item.captions:
                            cap_ref = cap.cref
                            cap_idx = -1
                            for j, it in enumerate(items_group):
                                if it is None:
                                    continue
                                if getattr(it[0][0], 'self_ref', None) == cap_ref:
                                    cap_idx = j
                                    break
                            if cap_idx != -1:
                                ref_idx_list.append(cap_idx)
                    if ref_idx_list:
                        ref_idx_list = sorted(ref_idx_list)

                    if not ref_idx_list:
                        continue

                    # caption 아이템들을 부모 아이템 바로 뒤로 이동
                    for cap_idx in ref_idx_list:
                        for g in items_group[cap_idx]:
                            items_group[idx].append(g)
                        items_group[cap_idx] = None  # 나중에 None 제거
                        b_modified = True

                if b_modified:
                    items_group = [it for it in items_group if it is not None]

                return items_group

            def adjust_pictures_in_tables(items_group):
                # picture in table 처리

                b_modified = False
                for idx, group in enumerate(items_group):
                    if group is None:
                        continue
                    item = group[0][0]
                    pic_idx_list = []
                    if isinstance(item, TableItem):
                        table_bbox = item.prov[0].bbox
                        table_page_no = item.prov[0].page_no

                        for j in range(len(items_group)):
                            if items_group[j] is None:
                                continue
                            pic_item = items_group[j][0][0]
                            if isinstance(pic_item, PictureItem):
                                # table 안의 picture인지 확인. iou 사용
                                pic_bbox = pic_item.prov[0].bbox
                                pic_page_no = pic_item.prov[0].page_no
                                if pic_page_no != table_page_no:
                                    continue
                                ios = pic_bbox.intersection_over_self(table_bbox)
                                if ios > 0.5:  # picture가 50% 이상 table 안에 포함되면 table 안의 picture로 간주
                                    pic_idx_list.append(j)
                        if pic_idx_list:
                            pic_idx_list = sorted(pic_idx_list)

                    if not pic_idx_list:
                        continue

                    for pic_idx in pic_idx_list:
                        for g in items_group[pic_idx]:
                            items_group[idx].append(g)
                        items_group[pic_idx] = None  # 나중에 None 제거
                        b_modified = True

                if b_modified:
                    items_group = [it for it in items_group if it is not None]

                return items_group

            # ================================================================
            # 표 단위 청크 분리 (xlsx docling 전용, kwargs: table_as_chunk)
            #   각 TableItem 을 독립 청크로, 사이의 연속 비표 아이템은 별도 청크로 묶는다.
            #   chunk_size(max_tokens) 와 무관하게 표가 병합되지 않도록 토큰 단계 이전에 확정 반환한다.
            # ================================================================
            if kwargs.get("table_as_chunk"):
                table_chunks: list[DocChunk] = []
                buf_items: list[DocItem] = []
                buf_short: list[dict] = []

                def _flush_buf():
                    if buf_items:
                        text = self._generate_section_text_with_heading(buf_items, buf_short, dl_doc, **kwargs)
                        # 빈 문서 방어용 "." placeholder 등 무의미한 텍스트 run 은 청크로 만들지 않는다.
                        if text and text.strip() and text.strip() != ".":
                            ch = get_current_chunk(doc_chunk, [text], list(buf_short), list(buf_items))
                            if ch:
                                table_chunks.append(ch)
                        buf_items.clear()
                        buf_short.clear()

                for i, item in enumerate(items):
                    h_short = header_short_info_list[i] if i < len(header_short_info_list) else {}
                    if isinstance(item, TableItem):
                        _flush_buf()
                        # 행이 많아 chunk_size 를 초과하는 표는 row 단위로 분할(각 청크에 헤더 반복 포함).
                        for text in self._table_item_to_texts(item, dl_doc, h_short, **kwargs):
                            ch = get_current_chunk(doc_chunk, [text], [h_short], [item])
                            if ch:
                                table_chunks.append(ch)
                    else:
                        buf_items.append(item)
                        buf_short.append(h_short)
                _flush_buf()

                if table_chunks:
                    return table_chunks

            # ================================================================
            # 1단계: 섹션 헤더 기준으로 분할
            # ================================================================

            sections = []  # [(items, header_infos, header_short_infos), ...]
            cur_items, cur_h_infos, cur_h_short = [], [], []

            for i, item in enumerate(items):
                h_info = header_info_list[i] if i < len(header_info_list) else {}
                h_short = header_short_info_list[i] if i < len(header_short_info_list) else {}

                # 섹션 헤더를 만나면
                if self._is_section_header(item):
                    # 이전 섹션이 있으면 저장
                    if cur_items:
                        sections.append((cur_items, cur_h_infos, cur_h_short))

                    # 새로운 섹션 시작
                    cur_items = [item]
                    cur_h_infos = [h_info]
                    cur_h_short = [h_short]
                else:
                    # 섹션 헤더가 아니면 현재 섹션에 추가
                    cur_items.append(item)
                    cur_h_infos.append(h_info)
                    cur_h_short.append(h_short)

            # 마지막 섹션 저장
            if cur_items:
                sections.append((cur_items, cur_h_infos, cur_h_short))

            # ================================================================
            # 2단계: 각 섹션의 텍스트에 heading 붙이기
            # ================================================================

            sections_with_text = []
            for items, header_infos, header_short_infos in sections:
                text = self._generate_section_text_with_heading(
                    items, header_short_infos, dl_doc, **kwargs
                )
                sections_with_text.append((
                    text,
                    items,
                    header_infos,
                    header_short_infos
                ))

            # ================================================================
            # 2.5단계: 너무 긴 청크는 분할 (인덱스 꼬임 방지를 위해 새 리스트 사용)
            #   resize_all 전용. split_only 는 구조 그룹핑(4단계) 후 5.5단계에서 분할한다
            #   (여기서 분할하면 같은 섹션 조각들이 4단계에서 다시 병합되어 무의미).
            # ================================================================
            if self.max_tokens > 0 and self.chunk_mode == "resize_all":
                final_sections = []  # 결과를 담을 새 리스트
                for text, items, h_infos, h_short in sections_with_text:
                    token_count = self._count_tokens(text)
                    if token_count < self.max_tokens:
                        final_sections.append((text, items, h_infos, h_short))
                        continue

                    # caption 및 table 내 그림은 같은 섹션에 있도록 조정
                    items_group=[[(item, info, short)] for item, info, short in zip(items, h_infos, h_short)]
                    items_group = adjust_captions(items_group)
                    items_group = adjust_pictures_in_tables(items_group)

                    # 너무 긴 섹션은 분할
                    # 각 아이템 별 token 수 계산
                    item_token_counts = []
                    for group in items_group:
                        cur_count = 0
                        for g in group:
                            cur_count += self._count_tokens(get_text_from_item(g[0]))
                        item_token_counts.append(cur_count)

                    # 아이템 그룹들을 토큰 기준으로 균등 분할
                    split_info = split_items_evenly_by_tokens(item_token_counts, self.max_tokens)

                    # 분할된 결과들을 새 리스트에 추가
                    for (a, b) in split_info:

                        # 각 그룹에서 items, h_infos, h_short로 분리
                        group_items = []
                        group_h_infos = []
                        group_h_short = []
                        for idx in range(a, b):
                            for g in items_group[idx]:
                                group_items.append(g[0])
                                group_h_infos.append(g[1])
                                group_h_short.append(g[2])

                        new_text = self._generate_section_text_with_heading(
                            group_items, group_h_short, dl_doc, **kwargs
                        )
                        final_sections.append((new_text, group_items, group_h_infos, group_h_short))

                sections_with_text = final_sections  # 전체 리스트 교체

            # ================================================================
            # 3단계: 단독 타이틀(1줄만) → 다음 섹션으로 병합
            # ================================================================

            for i in range(len(sections_with_text) - 2, -1, -1):
                text, items, h_infos, h_short = sections_with_text[i]

                # 아이템이 하나인 섹션 헤더만 검사
                if len(items) != 1 or not self._is_section_header(items[0]):
                    continue

                # 문단이 이미 구성된 것은 제외 (문자 수가 30자 이상이면 문단을 구성했다고 간주)
                item_text = "".join(getattr(it, "text", "") for it in items)
                if len(item_text) > 30:
                    continue

                # 현재 섹션헤더 레벨이 다음 섹션헤더 레벨보다 더 높은 경우에만 병합 (높은 레벨이 더 작은 숫자)
                n_text, n_items, n_h_infos, n_h_short = sections_with_text[i + 1]
                current_level = get_header_level(h_infos, first=False)
                next_level = get_header_level(n_h_infos, first=True)
                if 0 <= next_level < current_level:
                    continue

                # 다음 섹션과 병합
                sections_with_text[i] = (text + '\n' + n_text, items + n_items, h_infos + n_h_infos, h_short + n_h_short)
                sections_with_text.pop(i + 1)

            # ================================================================
            # 4단계: 토큰 기준 병합 (1차 — 섹션 구조 경계 기준 그룹 생성)
            # ================================================================

            groups: list[dict] = []
            merged_texts, merged_items = [], []
            merged_header_infos, merged_header_short_infos = [], []

            def flush_group():
                if merged_texts:
                    groups.append({
                        "texts": list(merged_texts),
                        "items": list(merged_items),
                        "h_infos": list(merged_header_infos),
                        "h_short": list(merged_header_short_infos),
                    })

            for text, items, header_infos, header_short_infos in sections_with_text:

                b_new_chunk = False

                #----------------------------------
                # 병합 가능 여부 판단

                # 병합 가능 토큰 수 계산
                test_tokens = self._count_tokens("\n".join(merged_texts + [text]))

                # 현재 섹션헤더 레벨과 병합된 섹션헤더 레벨
                section_level = get_header_level(header_infos, first=True)
                merged_level = get_header_level(merged_header_infos, first=False)

                # split_only: base 섹션 granularity 유지 — 구조 그룹핑 병합 없이 섹션마다 분리(장 단위 병합 방지).
                #   (1·3단계로 만든 섹션을 그대로 두고, 초과분만 5.5단계에서 분할)
                if self.chunk_mode == "split_only" and len(merged_texts) > 0:
                    b_new_chunk = True
                # 토큰 수 초과 시 새로운 청크 생성 (resize_all 전용)
                elif self.chunk_mode == "resize_all" and test_tokens > self.max_tokens and len(merged_texts) > 0:
                    b_new_chunk = True
                # 현재 섹션헤더 레벨이 더 높으면 새로운 청크 생성 (resize_all 구조 경계)
                elif 0 <= section_level < merged_level:
                    b_new_chunk = True
                #----------------------------------

                # 새로운 청크 생성
                if b_new_chunk:
                    flush_group()

                    # 새로운 병합 시작
                    merged_texts = [text]
                    merged_items = list(items)
                    merged_header_infos = list(header_infos)
                    merged_header_short_infos = list(header_short_infos)
                else:
                    # 현재 섹션 병합
                    merged_texts.append(text)
                    merged_items.extend(items)
                    merged_header_infos.extend(header_infos)
                    merged_header_short_infos.extend(header_short_infos)

            # 마지막 병합된 items 처리
            flush_group()

            # ================================================================
            # 5단계: chunk_size 한도 내 인접 그룹 greedy 병합
            #   1차 결과(구조 경계 기준 그룹)를 순서대로, 합산 크기가 chunk_size 이하인 동안
            #   인접 그룹끼리 결합한다. (크기는 HEADER 라인 포함 최종 텍스트 기준)
            # ================================================================
            def _size(g):
                text = "\n".join(g["texts"])
                headings = self._extract_used_headers(g["h_short"]) or []
                header_line = ("HEADER: " + ", ".join(headings) + "\n") if headings else ""
                # char 모드면 문자 수, huggingface 모드면 토큰 수로 산정 (max_tokens 단위와 일치)
                return self._count_tokens(header_line + text)

            if self.max_tokens > 0 and groups and self.chunk_mode == "resize_all":
                def _merge(a, b):
                    return {
                        "texts": a["texts"] + b["texts"],
                        "items": a["items"] + b["items"],
                        "h_infos": a["h_infos"] + b["h_infos"],
                        "h_short": a["h_short"] + b["h_short"],
                    }

                merged_groups = [groups[0]]
                for g in groups[1:]:
                    cand = _merge(merged_groups[-1], g)
                    if _size(cand) <= self.max_tokens:
                        merged_groups[-1] = cand
                    else:
                        merged_groups.append(g)
                groups = merged_groups

            # ================================================================
            # 5.5단계: split_only 전용 — chunk_size 초과 그룹만 토큰 기준 균등 분할
            #   (구조 기반 그룹은 유지, 작은 그룹은 병합하지 않고 그대로 둔다)
            # ================================================================
            if self.max_tokens > 0 and groups and self.chunk_mode == "split_only":
                new_groups = []
                for g in groups:
                    if _size(g) <= self.max_tokens:
                        new_groups.append(g)
                        continue

                    # caption 및 table 내 그림은 같은 조각에 있도록 조정 (2.5단계와 동일 로직)
                    items_group = [[(it, inf, sh)] for it, inf, sh in zip(g["items"], g["h_infos"], g["h_short"])]
                    items_group = adjust_captions(items_group)
                    items_group = adjust_pictures_in_tables(items_group)

                    item_token_counts = []
                    for grp in items_group:
                        item_token_counts.append(sum(self._count_tokens(get_text_from_item(x[0])) for x in grp))

                    for (a, b) in split_items_evenly_by_tokens(item_token_counts, self.max_tokens):
                        gi, gh, gs = [], [], []
                        for idx in range(a, b):
                            for x in items_group[idx]:
                                gi.append(x[0]); gh.append(x[1]); gs.append(x[2])
                        new_text = self._generate_section_text_with_heading(gi, gs, dl_doc, **kwargs)
                        new_groups.append({"texts": [new_text], "items": gi, "h_infos": gh, "h_short": gs})
                groups = new_groups

            # ================================================================
            # 6단계: 최종 DocChunk 생성
            # ================================================================
            result_chunks = []
            for g in groups:
                cur_chunk = get_current_chunk(doc_chunk, g["texts"], g["h_short"], g["items"])
                if cur_chunk:
                    result_chunks.append(cur_chunk)

            return result_chunks

        def chunk(self, dl_doc: DoclingDocument, **kwargs: Any) -> Iterator[BaseChunk]:
            """문서를 청킹하여 반환

        Args:
            dl_doc: 청킹할 문서

        Yields:
            토큰 제한에 맞게 분할된 청크들
        """
            doc_chunks = list(self.preprocess(dl_doc=dl_doc, **kwargs))

            if not doc_chunks:
                return iter([])

            doc_chunk = doc_chunks[0]  # preprocess는 하나의 청크만 반환

            final_chunks = self._split_document_by_tokens(doc_chunk, dl_doc, **kwargs)

            return iter(final_chunks)
    # 민감정보 분류/마스킹(#315)은 facade/guardrail 모듈로 분리 — gr.* 로 사용.
    from genon.preprocessor.facade import guardrail as gr


    class GenOSVectorMeta(BaseModel):
        class Config:
            extra = 'allow'

        text: str = None
        n_char: int = None
        n_word: int = None
        n_line: int = None
        e_page: int = None
        i_page: int = None
        i_chunk_on_page: int = None
        n_chunk_of_page: int = None
        i_chunk_on_doc: int = None
        n_chunk_of_doc: int = None
        n_page: int = None
        reg_date: str = None
        chunk_bboxes: str = None
        media_files: str = None
        title: str = None
        created_date: int = None
        appendix: str = None ## !! appendix feature (2025-09-30, geonhee kim) !!
        file_path: Optional[str] = None
        guardrail_categories: Optional[list] = None  # #315 민감정보 분류 라벨(부동산/인사/민감 등). 미적용 시 None


    class GenOSVectorMetaBuilder:
        def __init__(self):
            """빌더 초기화"""
            self.text: Optional[str] = None
            self.n_char: Optional[int] = None
            self.n_word: Optional[int] = None
            self.n_line: Optional[int] = None
            self.i_page: Optional[int] = None
            self.e_page: Optional[int] = None
            self.i_chunk_on_page: Optional[int] = None
            self.n_chunk_of_page: Optional[int] = None
            self.i_chunk_on_doc: Optional[int] = None
            self.n_chunk_of_doc: Optional[int] = None
            self.n_page: Optional[int] = None
            self.reg_date: Optional[str] = None
            self.chunk_bboxes: Optional[str] = None
            self.media_files: Optional[str] = None
            self.title: Optional[str] = None
            self.created_date: Optional[int] = None
            self.appendix: Optional[str] = None # !! appendix feature (2025-09-30, geonhee kim) !!
            self.file_path: Optional[str] = None
            self.guardrail_categories: Optional[list] = None  # #315 민감정보 분류 라벨
            self.extra_metadata: dict[str, Any] = {}

        def set_guardrail_categories(self, guardrail_categories: Optional[list]) -> "GenOSVectorMetaBuilder":
            """#315 청크 민감정보 분류 라벨 설정 (부동산/인사/민감 등 리스트, 미적용/없음 시 None)"""
            self.guardrail_categories = guardrail_categories or None
            return self

        def set_text(self, text: str) -> "GenOSVectorMetaBuilder":
            """텍스트와 관련된 데이터를 설정"""
            self.text = text
            self.n_char = len(text)
            self.n_word = len(text.split())
            self.n_line = len(text.splitlines())
            return self

        def set_page_info(
                self, i_page: int, i_chunk_on_page: int, n_chunk_of_page: int
        ) -> "GenOSVectorMetaBuilder":
            """페이지 정보 설정"""
            self.i_page = i_page
            self.i_chunk_on_page = i_chunk_on_page
            self.n_chunk_of_page = n_chunk_of_page
            return self

        def set_chunk_index(self, i_chunk_on_doc: int) -> "GenOSVectorMetaBuilder":
            """문서 전체의 청크 인덱스 설정"""
            self.i_chunk_on_doc = i_chunk_on_doc
            return self

        def set_global_metadata(self, **global_metadata) -> "GenOSVectorMetaBuilder":
            """글로벌 메타데이터 병합"""
            for key, value in global_metadata.items():
                if hasattr(self, key):
                    setattr(self, key, value)
                else:
                    self.extra_metadata[key] = value
            return self

        def set_chunk_bboxes(self, doc_items: list, document: DoclingDocument) -> "GenOSVectorMetaBuilder":
            chunk_bboxes = []
            for item in doc_items:
                for prov in item.prov:
                    label = item.self_ref
                    type_ = item.label
                    size = document.pages.get(prov.page_no).size
                    page_no = prov.page_no
                    bbox = prov.bbox
                    bbox_data = {'l': bbox.l / size.width,
                                 't': bbox.t / size.height,
                                 'r': bbox.r / size.width,
                                 'b': bbox.b / size.height,
                                 'coord_origin': bbox.coord_origin.value}
                    chunk_bboxes.append({'page': page_no, 'bbox': bbox_data, 'type': type_, 'ref': label})
            self.e_page = max([bbox['page'] for bbox in chunk_bboxes]) if chunk_bboxes else 0
            self.chunk_bboxes = json.dumps(chunk_bboxes)
            return self

        def set_media_files(self, doc_items: list, include_tables: bool = False) -> "GenOSVectorMetaBuilder":
            temp_list = []
            for item in doc_items:
                if isinstance(item, PictureItem) and item.image:
                    path = str(item.image.uri)
                    name = path.rsplit("/", 1)[-1]
                    temp_list.append({'name': name, 'type': 'image', 'ref': item.self_ref})
                elif include_tables and isinstance(item, TableItem) and item.image:
                    # 표 이미지는 picture 와 구분되도록 type='table_image' 로 기록한다.
                    # ref(self_ref)는 chunk_bboxes 의 table 엔트리 ref 와 동일 → 조인 가능.
                    path = str(item.image.uri)
                    name = path.rsplit("/", 1)[-1]
                    temp_list.append({'name': name, 'type': 'table_image', 'ref': item.self_ref})
            self.media_files = json.dumps(temp_list)
            return self

        def build(self) -> GenOSVectorMeta:
            """설정된 데이터를 사용해 최종적으로 GenOSVectorMeta 객체 생성"""
            payload = {
                "text": self.text,
                "n_char": self.n_char,
                "n_word": self.n_word,
                "n_line": self.n_line,
                "i_page": self.i_page,
                "e_page": self.e_page,
                "i_chunk_on_page": self.i_chunk_on_page,
                "n_chunk_of_page": self.n_chunk_of_page,
                "i_chunk_on_doc": self.i_chunk_on_doc,
                "n_chunk_of_doc": self.n_chunk_of_doc,
                "n_page": self.n_page,
                "reg_date": self.reg_date,
                "chunk_bboxes": self.chunk_bboxes,
                "media_files": self.media_files,
                "title": self.title,
                "created_date": self.created_date,
                "appendix": self.appendix or "", # !! appendix feature (2025-09-30, geonhee kim) !!
                "file_path": self.file_path,
                "guardrail_categories": self.guardrail_categories,  # #315 민감정보 분류 라벨
                **self.extra_metadata,
            }
            return GenOSVectorMeta.model_validate(payload)


    class IntelligentDocumentProcessor:

        def __init__(self, config_path: str | None = None):
            '''
        initialize Document Converter (config 기반)

        config_path 가 None 이면 resource_dev/intelligent_processor_config.yaml
        (없으면 resource/intelligent_processor_config.yaml) 을 사용한다.
        GenOS 는 DocumentProcessor() 무인자로 호출하므로 기본 경로 resolve 필수.
        '''
            if config_path is None:
                config_path = _resolve_default_intelligent_config_path()

            cfg = _load_config(config_path)
            self._config_dir = Path(config_path).resolve().parent
            # 런타임 kwargs 기본값(img_desc/chart_desc/chart_detection/doc_summary) 용도
            self._runtime_cfg = _as_dict(cfg.get("runtime"))

            defaults_cfg = _as_dict(cfg.get("defaults"))
            log_level = _parse_optional_int(defaults_cfg.get("log_level"), "defaults.log_level")
            if log_level is None:
                log_level = 4
            self._log_level = log_level

            ocr_cfg = _as_dict(cfg.get("ocr"))
            layout_cfg = _as_dict(cfg.get("layout"))
            pdf_cfg = _as_dict(cfg.get("pdf_pipeline"))
            models_cfg = _as_dict(cfg.get("models"))
            chunking_cfg = _as_dict(cfg.get("chunking"))
            ec = EnrichmentConfig.from_raw(cfg.get("enrichment"), self._config_dir, parent_cfg=cfg)

            # 청킹용 토크나이저 (chunking config 기반; 미지정 시 현행 기본값)
            self._tokenizer = _resolve_tokenizer(chunking_cfg)

            # 토큰 수 계산 방식 (chunking 섹션). "char"(default)=문자 수 기준 | "huggingface"=HF 토크나이저 기준
            self._tokenizer_type = str(chunking_cfg.get("tokenizer_type", "char")).strip().lower()
            if self._tokenizer_type not in {"char", "huggingface"}:
                _log.warning(
                    f"[DocumentProcessor] Unknown chunking.tokenizer_type '{self._tokenizer_type}', fallback to 'char'."
                )
                self._tokenizer_type = "char"

            # 청크 최대 크기(GenosSmartChunker.max_tokens) 기본값. kwargs 의 chunk_size 가 우선.
            self._chunk_size = _parse_optional_int(chunking_cfg.get("chunk_size"), "chunking.chunk_size")

            # 청킹 모드: "split_only"(기본, chunk_size 초과 청크만 분할) | "resize_all"(모든 청크를 chunk_size 에 맞게 병합/분할)
            self._chunk_mode = str(chunking_cfg.get("chunk_mode", "split_only")).strip().lower()
            if self._chunk_mode not in {"split_only", "resize_all"}:
                _log.warning(f"[DocumentProcessor] Unknown chunking.chunk_mode '{self._chunk_mode}', fallback to 'split_only'.")
                self._chunk_mode = "split_only"

            # xlsx(엑셀) 직접 처리 설정(이슈 #288). formats.xlsx 아래에 둔다(포맷별 옵션 컨테이너).
            #   processing_mode: docling(기본)=MsExcel 백엔드로 DoclingDocument 후 기존 파이프라인 /
            #                    tabular=데이터 행마다 1벡터 + 컬럼 헤더→메타(병합셀 unmerge+ffill)
            #   tabular.{header_row, multi_table}: tabular 모드 전용 세부 옵션
            formats_cfg = _as_dict(cfg.get("formats"))
            xlsx_cfg = _as_dict(formats_cfg.get("xlsx"))
            tabular_cfg = _as_dict(xlsx_cfg.get("tabular"))
            xlsx_mode = str(xlsx_cfg.get("processing_mode", "docling")).strip().lower()
            if xlsx_mode not in {"docling", "tabular"}:
                _log.warning(
                    f"[DocumentProcessor] Unknown formats.xlsx.processing_mode '{xlsx_mode}', fallback to 'docling'."
                )
                xlsx_mode = "docling"
            self._xlsx_cfg = {
                "processing_mode": xlsx_mode,
                "header_row": _parse_optional_int(tabular_cfg.get("header_row"), "formats.xlsx.tabular.header_row") or 0,
                "multi_table": bool(_parse_optional_bool(tabular_cfg.get("multi_table"), "formats.xlsx.tabular.multi_table")),
            }

            # 표 텍스트 직렬화 형식(청크 text 내 docling 표 표현). "html"(default) | "markdown".
            output_cfg = _as_dict(cfg.get("output"))
            table_format = str(output_cfg.get("table_format", "html")).strip().lower()
            if table_format not in {"html", "markdown"}:
                _log.warning(
                    f"[DocumentProcessor] Unknown output.table_format '{table_format}', fallback to 'html'."
                )
                table_format = "html"
            self._table_format = table_format
            # markdown 표 compact(컬럼 정렬 패딩 제거) 여부. 기본 True. html 포맷엔 무관.
            self._compact_tables = bool(output_cfg.get("compact_tables", True))

            # OCR 엔드포인트는 ocr.paddle.ocr_endpoint 가 정식 위치.
            # 구버전 호환: ocr.ocr_endpoint(상위) / 최상위 ocr_endpoint 도 폴백으로 인식.
            paddle_cfg = _as_dict(ocr_cfg.get("paddle"))
            ocr_ep = (
                paddle_cfg.get("ocr_endpoint")
                or ocr_cfg.get("ocr_endpoint")
                or cfg.get("ocr_endpoint", "http://192.168.73.172:48080/ocr")
            )

            # OCR 수행 모드. "auto"(default)=휴리스틱 기반 재OCR / "force"=무조건 전체 OCR / "disable"=OCR 안 함
            raw_ocr_mode = str(ocr_cfg.get("ocr_mode", cfg.get("ocr_mode", "auto"))).lower().strip()
            if raw_ocr_mode not in {"auto", "force", "disable"}:
                _log.warning(f"[DocumentProcessor] Unknown ocr_mode '{raw_ocr_mode}', fallback to 'auto'")
                raw_ocr_mode = "auto"
            self.ocr_mode = raw_ocr_mode

            # 테이블 셀 재OCR HTTP timeout (ocr_all_table_cells). 잘못된 값은 60 으로 폴백.
            table_cell_ocr_timeout = _parse_optional_int(
                ocr_cfg.get("table_cell_ocr_timeout"), "ocr.table_cell_ocr_timeout"
            )
            self._table_cell_ocr_timeout = (
                table_cell_ocr_timeout if table_cell_ocr_timeout and table_cell_ocr_timeout > 0 else 60
            )

            # 글리프 기반 auto-OCR 재트리거 임계값.
            glyph_cfg = _as_dict(ocr_cfg.get("glyph_detection"))
            glyph_cell_th = _parse_optional_int(
                glyph_cfg.get("table_cell_threshold"), "ocr.glyph_detection.table_cell_threshold"
            )
            self._glyph_table_cell_threshold = glyph_cell_th if glyph_cell_th and glyph_cell_th > 0 else 1
            glyph_doc_th = _parse_optional_int(
                glyph_cfg.get("document_threshold"), "ocr.glyph_detection.document_threshold"
            )
            self._glyph_document_threshold = glyph_doc_th if glyph_doc_th and glyph_doc_th > 0 else 10

            ocr_options = self._build_ocr_options(ocr_cfg, paddle_endpoint=ocr_ep)
            if isinstance(ocr_options, UpstageOcrOptions):
                self.ocr_endpoint = ocr_options.api_endpoint
            else:
                self.ocr_endpoint = ocr_ep

            # 민감정보 분류/마스킹(#315): GenOS 분류 워크플로우 접속 정보.
            # 기능 on/off 는 요청별 kwargs(guardrail_call), 마스킹 치환은 masking_enabled(config/kwargs).
            gm_cfg = _as_dict(cfg.get("guardrail"))
            self._guardrail_url = str(gm_cfg.get("url") or "").strip()
            self._guardrail_workflow_id = _parse_optional_int(gm_cfg.get("workflow_id"), "guardrail.workflow_id")
            self._guardrail_api_key = str(gm_cfg.get("api_key") or "").strip()
            gm_timeout = _parse_optional_int(gm_cfg.get("timeout"), "guardrail.timeout")
            self._guardrail_timeout = gm_timeout if gm_timeout and gm_timeout > 0 else 60
            self._guardrail_masking_enabled = bool(_parse_optional_bool(gm_cfg.get("masking_enabled"), "guardrail.masking_enabled"))

            self.page_chunk_counts = defaultdict(int)

            device_str = str(pdf_cfg.get("device", "auto")).lower().strip()
            device = _ACCELERATOR_DEVICE_MAP.get(device_str)
            if device is None:
                _log.warning(f"[DocumentProcessor] Unknown pdf_pipeline.device '{device_str}', fallback to 'auto'")
                device = AcceleratorDevice.AUTO

            num_threads = _parse_optional_int(pdf_cfg.get("num_threads"), "pdf_pipeline.num_threads")
            if num_threads is None or num_threads <= 0:
                num_threads = 8
            accelerator_options = AcceleratorOptions(num_threads=num_threads, device=device)

            images_scale = _parse_optional_int(pdf_cfg.get("images_scale"), "pdf_pipeline.images_scale")
            if images_scale is None or images_scale <= 0:
                images_scale = 2

            generate_page_images = _parse_optional_bool(
                pdf_cfg.get("generate_page_images"), "pdf_pipeline.generate_page_images"
            )
            generate_picture_images = _parse_optional_bool(
                pdf_cfg.get("generate_picture_images"), "pdf_pipeline.generate_picture_images"
            )

            # 표 이미지(table_image) 옵션: 표를 picture 와 동일하게 이미지로 잘라 저장하고,
            # media_files 에 type='table_image' 로 기록한다(검색=청크 텍스트 / 답변=표 이미지).
            # 기본 False 라 미설정 시 기존 동작과 동일(하위 호환).
            table_image_cfg = _as_dict(cfg.get("table_image"))
            self.table_image_enabled = bool(
                _parse_optional_bool(table_image_cfg.get("enable"), "table_image.enable")
            )

            # PPT 페이지 단위 image description(page-level) 옵션. 기존 PictureItem 단위 설명과 별개로,
            # "페이지 자체"를 렌더링해 설명한 텍스트를 페이지별 TextItem 으로 주입한다(PPT 원본 전용).
            # config 위치: formats.ppt.page_description. 공통 모듈(enrichment/page_description)로 파싱.
            ppt_fmt_cfg = _as_dict(formats_cfg.get("ppt"))
            page_img_cfg = _as_dict(ppt_fmt_cfg.get("page_description"))
            self._page_desc_options = PageDescriptionOptions.from_config(page_img_cfg, self._config_dir)

            table_mode_str = str(pdf_cfg.get("table_structure_mode", "accurate")).lower().strip()
            table_structure_mode = _TABLE_FORMER_MODE_MAP.get(table_mode_str)
            if table_structure_mode is None:
                _log.warning(
                    f"[DocumentProcessor] Unknown pdf_pipeline.table_structure_mode '{table_mode_str}', fallback to 'accurate'"
                )
                table_structure_mode = TableFormerMode.ACCURATE

            # PDF 파이프라인 옵션 설정
            self.pipe_line_options = PdfPipelineOptions()
            self.pipe_line_options.generate_page_images = (
                True if generate_page_images is None else generate_page_images
            )
            self.pipe_line_options.generate_picture_images = (
                True if generate_picture_images is None else generate_picture_images
            )
            # 표 이미지 크롭(TableItem.get_image)은 페이지 이미지를 소스로 하므로,
            # table_image 가 켜지면 generate_page_images 를 True 로 강제 보장한다.
            # 페이지 단위 image description 도 페이지 렌더 이미지를 소스로 하므로 동일하게 강제한다.
            if self.table_image_enabled or self._page_desc_options.enabled:
                self.pipe_line_options.generate_page_images = True
            self.pipe_line_options.do_ocr = False
            self.pipe_line_options.ocr_options = ocr_options
            self.pipe_line_options.images_scale = images_scale

            # layout 모델 선택. "genos_layout"(default) / "docling_layout". 잘못된 값은 경고 후 폴백.
            layout_model_type_str = str(
                layout_cfg.get("layout_model_type", cfg.get("layout_model_type", "genos_layout"))
            ).lower().strip()
            if layout_model_type_str == LayoutModelType.DOCLING_LAYOUT.value:
                layout_model_type = LayoutModelType.DOCLING_LAYOUT
            else:
                if layout_model_type_str != LayoutModelType.GENOS_LAYOUT.value:
                    _log.warning(
                        f"[DocumentProcessor] Unknown layout_model_type '{layout_model_type_str}', "
                        f"fallback to '{LayoutModelType.GENOS_LAYOUT.value}'"
                    )
                layout_model_type = LayoutModelType.GENOS_LAYOUT
            self.pipe_line_options.layout_options.layout_model_type = layout_model_type
            self.pipe_line_options.layout_options.genos_layout_options.endpoint = _as_dict(
                layout_cfg.get("genos_layout")
            ).get("endpoint", "http://192.168.75.174:26001/v1/chat/completions")
            self.pipe_line_options.layout_options.genos_layout_options.api_key = _as_dict(
                layout_cfg.get("genos_layout")
            ).get("api_key", "")

            # genos layout 모델은 batch size를 32로 설정
            page_batch_size = _parse_optional_int(
                _as_dict(layout_cfg.get("genos_layout")).get("page_batch_size"), "layout.genos_layout.page_batch_size"
            )
            if page_batch_size is None or page_batch_size <= 0:
                page_batch_size = 128
            settings.perf.page_batch_size = page_batch_size

            max_completion_tokens = _parse_optional_int(
                _as_dict(layout_cfg.get("genos_layout")).get("max_completion_tokens"),
                "layout.genos_layout.max_completion_tokens",
            )
            if max_completion_tokens is None or max_completion_tokens <= 0:
                max_completion_tokens = 16384
            self.pipe_line_options.layout_options.genos_layout_options.max_completion_tokens = max_completion_tokens

            # DotsOCR VLM 호출/생성 파라미터 (yaml 누락·무효 시 기본값 폴백)
            genos_layout_cfg = _as_dict(layout_cfg.get("genos_layout"))
            layout_model = genos_layout_cfg.get("model") or "dots-mocr"
            layout_timeout = _parse_optional_int(
                genos_layout_cfg.get("timeout"), "layout.genos_layout.timeout"
            )
            if layout_timeout is None or layout_timeout <= 0:
                layout_timeout = 1200
            layout_retry_count = _parse_optional_int(
                genos_layout_cfg.get("retry_count"), "layout.genos_layout.retry_count"
            )
            if layout_retry_count is None or layout_retry_count < 0:
                layout_retry_count = 2
            layout_temperature = _parse_optional_float(
                genos_layout_cfg.get("temperature"), "layout.genos_layout.temperature"
            )
            if layout_temperature is None or layout_temperature < 0:
                layout_temperature = 0.1
            layout_top_p = _parse_optional_float(
                genos_layout_cfg.get("top_p"), "layout.genos_layout.top_p"
            )
            if layout_top_p is None or not (0 < layout_top_p <= 1):
                layout_top_p = 0.9
            layout_repetition_penalty = _parse_optional_float(
                genos_layout_cfg.get("repetition_penalty"),
                "layout.genos_layout.repetition_penalty",
            )
            if layout_repetition_penalty is None or layout_repetition_penalty <= 0:
                layout_repetition_penalty = 1.15
            layout_length_fallback = _parse_optional_bool(
                genos_layout_cfg.get("length_fallback_enabled"),
                "layout.genos_layout.length_fallback_enabled",
            )
            if layout_length_fallback is None:
                layout_length_fallback = True
            layout_fallback_dpi = _parse_optional_int(
                genos_layout_cfg.get("fallback_dpi"), "layout.genos_layout.fallback_dpi"
            )
            if layout_fallback_dpi is None or layout_fallback_dpi <= 0:
                layout_fallback_dpi = 200
            layout_table_fallback = _parse_optional_bool(
                genos_layout_cfg.get("table_fallback_enabled"),
                "layout.genos_layout.table_fallback_enabled",
            )
            if layout_table_fallback is None:
                layout_table_fallback = True
            self.pipe_line_options.layout_options.genos_layout_options.model = layout_model
            self.pipe_line_options.layout_options.genos_layout_options.timeout = layout_timeout
            self.pipe_line_options.layout_options.genos_layout_options.retry_count = layout_retry_count
            self.pipe_line_options.layout_options.genos_layout_options.temperature = layout_temperature
            self.pipe_line_options.layout_options.genos_layout_options.top_p = layout_top_p
            self.pipe_line_options.layout_options.genos_layout_options.repetition_penalty = layout_repetition_penalty
            self.pipe_line_options.layout_options.genos_layout_options.length_fallback_enabled = layout_length_fallback
            self.pipe_line_options.layout_options.genos_layout_options.fallback_dpi = layout_fallback_dpi
            self.pipe_line_options.layout_options.genos_layout_options.table_fallback_enabled = layout_table_fallback

            self.pipe_line_options.do_table_structure = True
            self.pipe_line_options.table_structure_options.do_cell_matching = True
            self.pipe_line_options.table_structure_options.mode = table_structure_mode
            self.pipe_line_options.accelerator_options = accelerator_options

            # docling 모델(TableFormer 등) 로컬 경로. config 에 값이 있을 때만 설정하고,
            # 비어있으면 설정하지 않아 docling 기본 캐시 동작을 그대로 유지(backward compat).
            # (아래 ocr_pipe_line_options 는 pipe_line_options 의 deep copy 라 자동 전파됨)
            artifacts_path = models_cfg.get("artifacts_path")
            if artifacts_path:
                self.pipe_line_options.artifacts_path = Path(artifacts_path)

            # Simple 파이프라인 옵션을 인스턴스 변수로 저장
            self.simple_pipeline_options = PipelineOptions()
            self.simple_pipeline_options.save_images = False

            # 이미지/차트 description 옵션. chart.enable 이면 변환 단계에서 그림 분류가 필요하므로
            # 컨버터(ocr 포함) 생성 전에 옵션을 결정하고 do_picture_classification 을 켜 둔다.
            self.image_description_options = ImageDescriptionOptions.from_config(
                image_desc_cfg=ec.image_description_cfg,
                fallback_api_url=ec.api_url,
                fallback_api_key=ec.api_key,
                fallback_model=ec.model,
                config_dir=self._config_dir,
            )
            # 런타임 kwargs 오버라이드의 기준(base) 옵션 보관
            self._base_image_description_options = self.image_description_options
            # chart.enable=true 이면 그림 분류를 켠다(런타임 chart_detection=auto 전환 허용).
            # 모델(ds4sd--DocumentFigureClassifier)은 빌드 시 /models 에 포함(docling-tools models download).
            if self.image_description_options.chart_enabled:
                try:
                    self.pipe_line_options.do_picture_classification = True
                except Exception as exc:
                    _log.warning(
                        f"[DocumentProcessor] do_picture_classification 설정 실패: {exc}"
                    )

            # 표 description 옵션. VLM 이 표 영역을 crop 하려면 페이지 이미지가 필요하므로
            # base 옵션이 켜져 있으면 컨버터 생성 전에 generate_page_images 를 강제한다.
            self.table_description_options = TableDescriptionOptions.from_config(
                table_desc_cfg=ec.table_description_cfg,
                fallback_api_url=ec.api_url,
                fallback_api_key=ec.api_key,
                fallback_model=ec.model,
                config_dir=self._config_dir,
            )
            self._base_table_description_options = self.table_description_options
            if self.table_description_options.enabled:
                self.pipe_line_options.generate_page_images = True

            # 문서 본문요약(doc_summary) 옵션. image/table 이 공유하는 {{doc_summary}} 를 1회 계산.
            self.doc_summary_options = DocSummaryOptions.from_config(
                doc_summary_cfg=ec.doc_summary_cfg,
                fallback_api_url=ec.api_url,
                fallback_api_key=ec.api_key,
                fallback_model=ec.model,
                config_dir=self._config_dir,
            )
            self._base_doc_summary_options = self.doc_summary_options

            # ocr 파이프라인 옵션
            self.ocr_pipe_line_options = PdfPipelineOptions()
            self.ocr_pipe_line_options = self.pipe_line_options.model_copy(deep=True)
            self.ocr_pipe_line_options.do_ocr = True
            self.ocr_pipe_line_options.ocr_options = ocr_options.model_copy(deep=True)
            self.ocr_pipe_line_options.ocr_options.force_full_page_ocr = True

            # 기본 컨버터들 생성
            self._create_converters()

            # HWP/HWPX 품질 복구(선택적). 모듈 미로드 시 None → 복구 미적용(기존 동작).
            self._hwp_recovery = (
                HwpQualityRecovery(reload_fn=self._load_document) if HwpQualityRecovery else None
            )

            self.image_description_enricher = ImageDescriptionEnricher(
                self.image_description_options
            )
            self.table_description_enricher = TableDescriptionEnricher(
                self.table_description_options
            )
            self.doc_summary_enricher = DocSummaryEnricher(self.doc_summary_options)
            self.custom_fields_enrichers: list = (
                [_CustomFieldsEnricher(**c) for c in ec.custom_fields_cfgs]
                if _CustomFieldsEnricher is not None
                else []
            )
            self.metadata_enricher = (
                _MetadataEnricher(
                    url=ec.metadata.url,
                    api_key=ec.metadata.api_key,
                    model=ec.metadata.model,
                    system_prompt=ec.metadata.system_prompt,
                    user_prompt=ec.metadata.user_prompt,
                    output_fields=ec.metadata.output_fields,
                    parser=ec.metadata.parser,
                    pages=ec.metadata.pages,
                    max_tokens=ec.metadata.max_tokens,
                    temperature=ec.metadata.temperature,
                    timeout=ec.metadata.timeout,
                    config_dir=self._config_dir,
                    variables=ec.metadata.variables,
                    template_mode=ec.metadata.template_mode,
                    thinking=ec.metadata.thinking,
                    thinking_dialect=ec.metadata.thinking_dialect,
                )
                if _MetadataEnricher is not None and ec.metadata.do_metadata and ec.metadata.has_custom_metadata
                else None
            )
            # 추출 메타데이터 → typed 벡터 필드 매핑(설정 기반). 설정이 비어있으면
            # 기존 created_date 동작을 그대로 재현한다(하위 호환).
            self._metadata_field_transforms = (
                ec.metadata.field_transforms or DEFAULT_METADATA_FIELD_TRANSFORMS
            )

            # enrichment 옵션 설정 (yaml 의 enrichment 섹션을 EnrichmentConfig 로 파싱)
            self.enrichment_options = DataEnrichmentOptions(
                do_toc_enrichment=ec.toc.do_toc,
                toc_doc_type=ec.toc.doc_type,
                # 커스텀 MetadataEnricher가 있으면 docling 내장 metadata 추출을 비활성화한다.
                extract_metadata=ec.metadata.do_metadata and self.metadata_enricher is None,
                toc_api_provider="custom",
                metadata_api_provider="custom",
                toc_api_base_url=ec.toc.url,
                metadata_api_base_url=ec.metadata.url,
                toc_api_key=ec.toc.api_key,
                metadata_api_key=ec.metadata.api_key,
                toc_model=ec.toc.model,
                metadata_model=ec.metadata.model,
                toc_temperature=ec.toc.temperature,
                toc_top_p=ec.toc.top_p,
                toc_seed=ec.toc.seed,
                toc_max_tokens=ec.toc.max_tokens,
                toc_repetition_penalty=ec.toc.repetition_penalty,
                toc_precheck_enabled=ec.toc.precheck_enabled,
                toc_max_context_tokens=ec.toc.precheck_max_context_tokens,
                toc_completion_reserved_tokens=ec.toc.precheck_completion_reserved_tokens,
                toc_split_enabled=ec.toc.split_enabled,
                toc_pages_per_chunk=ec.toc.split_pages_per_chunk,
                toc_page_overlap=ec.toc.split_page_overlap,
                toc_carryover_max_tokens=ec.toc.split_carryover_max_tokens,
                metadata_precheck_enabled=ec.metadata.precheck_enabled,
                metadata_max_context_tokens=ec.metadata.precheck_max_context_tokens,
                metadata_completion_reserved_tokens=ec.metadata.precheck_completion_reserved_tokens,
                toc_system_prompt=ec.toc.system_prompt,
                toc_user_prompt=ec.toc.user_prompt,
                toc_thinking=ec.toc.thinking,
                toc_thinking_dialect=ec.toc.thinking_dialect,
                metadata_thinking=ec.metadata.thinking,
                metadata_thinking_dialect=ec.metadata.thinking_dialect,
            )

        @staticmethod
        def _build_ocr_options(ocr_cfg: dict, paddle_endpoint: str):
            """Build OcrOptions based on ocr.engine key in yaml.

        Returns PaddleOcrOptions or UpstageOcrOptions. Default engine is "paddle".
        For "upstage", api_key falls back to UPSTAGE_API_KEY env var when empty.
        Unknown engine values fall back to "paddle" with a warning.
        """
            ocr_cfg = ocr_cfg if isinstance(ocr_cfg, dict) else {}
            ocr_engine = str(ocr_cfg.get("engine", "paddle")).lower().strip()
            if ocr_engine not in {"paddle", "upstage"}:
                _log.warning(f"[DocumentProcessor] Unknown ocr.engine '{ocr_engine}', fallback to 'paddle'")
                ocr_engine = "paddle"

            if ocr_engine == "upstage":
                upstage_cfg = _as_dict(ocr_cfg.get("upstage"))
                upstage_api_key = upstage_cfg.get("api_key", "") or os.getenv("UPSTAGE_API_KEY", "")

                raw_timeout = upstage_cfg.get("timeout", 60)
                try:
                    upstage_timeout = int(raw_timeout)
                    if upstage_timeout <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    _log.warning(f"[DocumentProcessor] Invalid ocr.upstage.timeout '{raw_timeout}', fallback to 60")
                    upstage_timeout = 60

                raw_text_score = upstage_cfg.get("text_score", 0.5)
                try:
                    upstage_text_score = float(raw_text_score)
                except (TypeError, ValueError):
                    _log.warning(f"[DocumentProcessor] Invalid ocr.upstage.text_score '{raw_text_score}', fallback to 0.5")
                    upstage_text_score = 0.5

                return UpstageOcrOptions(
                    force_full_page_ocr=False,
                    lang=upstage_cfg.get("lang", ["ko", "en"]),
                    api_endpoint=upstage_cfg.get(
                        "api_endpoint",
                        "https://api.upstage.ai/v1/document-digitization",
                    ),
                    api_key=upstage_api_key,
                    model=upstage_cfg.get("model", "ocr"),
                    timeout=upstage_timeout,
                    text_score=upstage_text_score,
                )

            paddle_cfg = _as_dict(ocr_cfg.get("paddle"))

            raw_lang = paddle_cfg.get("lang", ["korean"])
            if isinstance(raw_lang, list) and raw_lang:
                paddle_lang = raw_lang
            else:
                if raw_lang not in (None, [], ["korean"]):
                    _log.warning(f"[DocumentProcessor] Invalid ocr.paddle.lang '{raw_lang}', fallback to ['korean']")
                paddle_lang = ["korean"]

            raw_text_score = paddle_cfg.get("text_score", 0.3)
            try:
                paddle_text_score = float(raw_text_score)
            except (TypeError, ValueError):
                _log.warning(f"[DocumentProcessor] Invalid ocr.paddle.text_score '{raw_text_score}', fallback to 0.3")
                paddle_text_score = 0.3

            return PaddleOcrOptions(
                force_full_page_ocr=False,
                lang=paddle_lang,
                ocr_endpoint=paddle_endpoint,
                text_score=paddle_text_score,
            )

        def _create_converters(self):
            """컨버터들을 생성하는 헬퍼 메서드"""
            self.converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(
                            pipeline_options=self.pipe_line_options,
                            backend=PyPdfiumDocumentBackend
                        ),
                    }
                )
            self.second_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=self.pipe_line_options,
                        backend=PyPdfiumDocumentBackend
                    ),
                },
            )
            self.ocr_converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(
                            pipeline_options=self.ocr_pipe_line_options,
                            backend=DoclingParseV4DocumentBackend
                        ),
                    }
                )
            self.ocr_second_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=self.ocr_pipe_line_options,
                        backend=PyPdfiumDocumentBackend
                    ),
                },
            )

        def load_documents_with_docling(self, file_path: str, **kwargs: dict) -> DoclingDocument:
            # kwargs에서 save_images 값을 가져와서 옵션 업데이트
            save_images = kwargs.get('save_images', True)
            include_wmf = kwargs.get('include_wmf', False)

            # save_images 옵션이 현재 설정과 다르면 컨버터 재생성
            if (self.simple_pipeline_options.save_images != save_images or
                getattr(self.simple_pipeline_options, 'include_wmf', False) != include_wmf):
                self.simple_pipeline_options.save_images = save_images
                self.simple_pipeline_options.include_wmf = include_wmf
                self._create_converters()

            try:
                conv_result: ConversionResult = self.converter.convert(file_path, raises_on_error=True)
            except Exception as e:
                conv_result: ConversionResult = self.second_converter.convert(file_path, raises_on_error=True)
            return conv_result.document

        def load_documents_with_docling_ocr(self, file_path: str, **kwargs: dict) -> DoclingDocument:
            # kwargs에서 save_images 값을 가져와서 옵션 업데이트
            save_images = kwargs.get('save_images', True)
            include_wmf = kwargs.get('include_wmf', False)

            # save_images 옵션이 현재 설정과 다르면 컨버터 재생성
            if (self.simple_pipeline_options.save_images != save_images or
                getattr(self.simple_pipeline_options, 'include_wmf', False) != include_wmf):
                self.simple_pipeline_options.save_images = save_images
                self.simple_pipeline_options.include_wmf = include_wmf
                self._create_converters()

            try:
                conv_result: ConversionResult = self.ocr_converter.convert(file_path, raises_on_error=True)
            except Exception as e:
                conv_result: ConversionResult = self.ocr_second_converter.convert(file_path, raises_on_error=True)
            return conv_result.document

        def load_documents(self, file_path: str, **kwargs: dict) -> DoclingDocument:
            return self.load_documents_with_docling(file_path, **kwargs)

        def split_documents(self, documents: DoclingDocument, **kwargs: dict) -> List[DocChunk]:
            # chunk_size 우선순위: kwargs > yaml(chunking.chunk_size) > 0
            chunk_size = _parse_optional_int(kwargs.get('chunk_size'), 'chunk_size')
            if chunk_size is None:
                chunk_size = self._chunk_size
            chunk_size = _clamp_chunk_size(chunk_size)
            # chunk_mode 우선순위: kwargs > yaml(chunking.chunk_mode) > "split_only"
            # chunk_mode(0/1 또는 'split_only'/'resize_all') > yaml > "split_only"
            chunk_mode = _resolve_chunk_mode(kwargs, self._chunk_mode)
            chunker: GenosSmartChunker = GenosSmartChunker(
                max_tokens = chunk_size if chunk_size is not None else 0,
                merge_peers = True,
                tokenizer = self._tokenizer,
                tokenizer_type = self._tokenizer_type,
                chunk_mode = chunk_mode,
            )

            # 표 직렬화 형식(html|markdown)을 청커로 전달(런타임 kwarg 가 있으면 우선).
            kwargs.setdefault("table_format", self._table_format)
            kwargs.setdefault("compact_tables", self._compact_tables)
            chunks: List[DocChunk] = list(chunker.chunk(dl_doc=documents, **kwargs))
            for chunk in chunks:
                if chunk.meta.doc_items[0].prov:
                    self.page_chunk_counts[chunk.meta.doc_items[0].prov[0].page_no] += 1
            return chunks

        def split_documents_by_page(self, documents: DoclingDocument, **kwargs: dict) -> List[DocChunk]:
            """PPT 전용 페이지 기반 청킹.

        기본 1 page = 1 chunk. chunk_size(kwargs > yaml) 가 주어지면 연속 페이지를 토큰 기준
        chunk_size 이하가 되도록 greedy 병합한다. 같은 페이지의 native text 와 주입된 page
        description TextItem 은 prov.page_no 로 동일 페이지 청크에 자연히 묶인다.
        """
            chunk_size = _parse_optional_int(kwargs.get('chunk_size'), 'chunk_size')
            if chunk_size is None:
                chunk_size = self._chunk_size
            chunk_size = _clamp_chunk_size(chunk_size)
            # chunk_mode(0/1 또는 'split_only'/'resize_all') > yaml > "split_only"
            chunk_mode = _resolve_chunk_mode(kwargs, self._chunk_mode)
            chunker: GenosSmartChunker = GenosSmartChunker(
                max_tokens=chunk_size if chunk_size is not None else 0,
                merge_peers=True,
                tokenizer=self._tokenizer,
                tokenizer_type=self._tokenizer_type,
                chunk_mode=chunk_mode,
            )
            kwargs.setdefault("table_format", self._table_format)
            kwargs.setdefault("compact_tables", self._compact_tables)

            # 전체 아이템 base chunk(정상 경로와 동일한 아이템 수집/헤더/누락표 복구 재사용)
            base = next(iter(chunker.preprocess(dl_doc=documents, **kwargs)), None)
            if base is None:
                return []
            items = base.meta.doc_items
            header_short = getattr(base, "_header_short_info_list", []) or []

            # prov page_no 로 그룹(아이템 순서 유지). prov 없으면 직전 페이지에 귀속.
            page_items: dict = {}
            page_headers: dict = {}
            last_page = 1
            for idx, it in enumerate(items):
                prov = getattr(it, "prov", None) or []
                pg = prov[0].page_no if prov and getattr(prov[0], "page_no", None) else last_page
                last_page = pg
                page_items.setdefault(pg, []).append(it)
                page_headers.setdefault(pg, []).append(
                    header_short[idx] if idx < len(header_short) else {}
                )

            # 페이지별 1 청크 직렬화
            page_chunks: List[DocChunk] = []
            for pg in sorted(page_items.keys()):
                its = page_items[pg]
                text = chunker._generate_section_text_with_heading(
                    its, page_headers[pg], documents, **kwargs
                )
                if text and text.strip() and text.strip() != ".":
                    page_chunks.append(DocChunk(
                        text=text,
                        meta=DocMeta(doc_items=its, headings=None, captions=None, origin=documents.origin),
                    ))

            # chunk_size>0 이면 연속 페이지 greedy 병합 (split_only 는 1 page = 1 chunk 유지)
            if chunk_mode == "resize_all" and chunk_size and chunk_size > 0 and page_chunks:
                merged: List[DocChunk] = [page_chunks[0]]
                for ch in page_chunks[1:]:
                    cand_text = merged[-1].text + "\n" + ch.text
                    if chunker._count_tokens(cand_text) <= chunk_size:
                        merged[-1] = DocChunk(
                            text=cand_text,
                            meta=DocMeta(
                                doc_items=merged[-1].meta.doc_items + ch.meta.doc_items,
                                headings=None, captions=None, origin=documents.origin,
                            ),
                        )
                    else:
                        merged.append(ch)
                page_chunks = merged

            for ch in page_chunks:
                if ch.meta.doc_items and ch.meta.doc_items[0].prov:
                    self.page_chunk_counts[ch.meta.doc_items[0].prov[0].page_no] += 1
            _log.info(f"[ppt] page-based chunks: {len(page_chunks)} (chunk_size={chunk_size})")
            return page_chunks

        def safe_join(self, iterable):
            if not isinstance(iterable, (list, tuple, set)):
                return ''
            return ''.join(map(str, iterable)) + '\n'

        def enrichment(self, document: DoclingDocument, is_ppt: bool = False, **kwargs: dict) -> DoclingDocument:
            options = self.enrichment_options
            # 런타임 toc(0/1) — config 기본값(do_toc_enrichment)을 요청별로 켜고/끈다.
            # 활성화(0→1)는 TOC endpoint 가 config 에 구성된 경우에만 유효(미구성 시 무시).
            cur_toc = bool(getattr(options, "do_toc_enrichment", False))
            want_toc = bool(_as_int_flag(kwargs.get("toc"), 1 if cur_toc else 0))
            if want_toc != cur_toc:
                if want_toc and not str(getattr(options, "toc_api_base_url", "") or ""):
                    _log.warning("[intelligent] toc=1 요청이지만 TOC endpoint 미구성 → 무시")
                else:
                    options = _copy_enrichment_options(options, do_toc_enrichment=want_toc)
                    _log.info("[intelligent] runtime toc override → %s", want_toc)
            # PPT 는 페이지 기반 1chunk 라 목차 계층이 무의미 → TOC 만 비활성(다른 enrichment 는 유지).
            if is_ppt and getattr(options, "do_toc_enrichment", False):
                options = _copy_enrichment_options(options, do_toc_enrichment=False)
                _log.info("[intelligent] PPT — TOC enrichment skip")
            try:
                # 새로운 enriched result 받기
                document = enrich_document(document, options, **kwargs)
                return document
            except LLMApiError as e:
                # Preserve provider error payload as-is for load status error message.
                # #329: 기존 hard-fail 동작 유지 + stage/error_type 스탬프(4xx→permanent, 5xx→transient).
                raise GenosServiceException(
                    "1", e.raw_error_message, stage="enrichment", error_type=_classify_error(e)
                ) from e

        def _normalize_runtime_kwargs(self, kwargs: dict) -> dict:
            """이미지/차트 description 런타임 토글을 정규화한다(전부 0/1 플래그).

        img_desc          : 이미지 description 사용유무          → image_description.enable
        chart_desc        : 차트 description 사용유무            → chart.enable (chart_convert alias)
        chart_detection   : 1=auto(docling 자동판별)/0=all       → chart.detection
        doc_summary       : 문서 본문요약 사용유무               → body_summary.enable
        미지정 kwarg 는 config(runtime 섹션 또는 base 옵션) 기본값을 따른다.
        """
            normalized = dict(kwargs or {})
            runtime = self._runtime_cfg
            base = getattr(self, "_base_image_description_options", None)

            img_default = _as_int_flag(
                runtime.get("img_desc"), 1 if (base and base.enabled) else 0
            )
            chart_default = _as_int_flag(
                runtime.get("chart_desc", runtime.get("chart_convert")),
                1 if (base and base.chart_enabled) else 0,
            )
            detection_default = _as_int_flag(
                runtime.get("chart_detection"),
                1 if (base and base.chart_detection == "auto") else 0,
            )
            dbase = getattr(self, "_base_doc_summary_options", None)
            summary_default = _as_int_flag(
                runtime.get("doc_summary"),
                1 if (dbase and dbase.enabled) else 0,
            )

            normalized["img_desc"] = _as_int_flag(normalized.get("img_desc"), img_default)
            normalized["chart_desc"] = _as_int_flag(
                normalized.get("chart_desc", normalized.get("chart_convert")), chart_default
            )
            normalized["chart_detection"] = _as_int_flag(
                normalized.get("chart_detection"), detection_default
            )
            normalized["doc_summary"] = _as_int_flag(
                normalized.get("doc_summary"), summary_default
            )

            # 표 description 런타임 토글(table_desc→enable, table_refine→refine.enable)
            tbase = getattr(self, "_base_table_description_options", None)
            table_default = _as_int_flag(
                runtime.get("table_desc"), 1 if (tbase and tbase.enabled) else 0
            )
            refine_default = _as_int_flag(
                runtime.get("table_refine"), 1 if (tbase and tbase.refine_enabled) else 0
            )
            normalized["table_desc"] = _as_int_flag(normalized.get("table_desc"), table_default)
            normalized["table_refine"] = _as_int_flag(normalized.get("table_refine"), refine_default)

            # TOC 런타임 토글(toc/toc_on alias) — 기본값은 config 의 do_toc_enrichment.
            toc_default = _as_int_flag(
                runtime.get("toc", runtime.get("toc_on")),
                1 if getattr(self.enrichment_options, "do_toc_enrichment", False) else 0,
            )
            normalized["toc"] = _as_int_flag(
                normalized.get("toc", normalized.get("toc_on")), toc_default
            )
            # merge_sections 별칭은 도입하지 않는다 — 기존 chunk_mode kwarg 가 동일 기능이며
            # split_documents 의 _resolve_chunk_mode() 가 chunk_mode 0/1/문자열을 직접 해석한다.
            return normalized

        def _configure_runtime_image_mode(self, kwargs: dict):
            """정규화된 kwargs 로 image_description_options/enricher 를 재구성한다.

        순수 override 계산은 enrichment.image_description.resolve_runtime_image_options 에 위임.
        """
            doc_summary = _as_int_flag(kwargs.get("doc_summary"), 0)

            # image description 런타임 재구성 (image base 옵션이 있을 때만)
            base = getattr(self, "_base_image_description_options", None)
            if base is not None:
                img_desc = _as_int_flag(kwargs.get("img_desc"), 0)
                chart_desc = _as_int_flag(kwargs.get("chart_desc"), 0)
                chart_detection = _as_int_flag(kwargs.get("chart_detection"), 0)
                self.image_description_options = resolve_runtime_image_options(
                    base,
                    img_desc=img_desc,
                    chart_desc=chart_desc,
                    chart_detection=chart_detection,
                    classification_available=getattr(
                        self.pipe_line_options, "do_picture_classification", False
                    ),
                )
                self.image_description_enricher = ImageDescriptionEnricher(
                    self.image_description_options
                )
                _log.info(
                    "[runtime_feature] image mode enabled=%s img_desc=%s chart_desc=%s detection=%s",
                    self.image_description_options.enabled,
                    img_desc,
                    chart_desc,
                    self.image_description_options.chart_detection,
                )

            # 표 description 런타임 재구성 (image base 유무와 무관하게 독립 실행)
            tbase = getattr(self, "_base_table_description_options", None)
            if tbase is not None:
                table_desc = _as_int_flag(kwargs.get("table_desc"), 0)
                table_refine = _as_int_flag(kwargs.get("table_refine"), 0)
                self.table_description_options = resolve_runtime_table_options(
                    tbase,
                    table_desc=table_desc,
                    table_refine=table_refine,
                )
                self.table_description_enricher = TableDescriptionEnricher(
                    self.table_description_options
                )
                _log.info(
                    "[runtime_feature] table mode enabled=%s table_desc=%s table_refine=%s",
                    self.table_description_options.enabled,
                    table_desc,
                    table_refine,
                )

            # doc_summary 런타임 재구성(image/table 공통 컨텍스트 제공)
            dbase = getattr(self, "_base_doc_summary_options", None)
            if dbase is not None:
                self.doc_summary_options = resolve_runtime_doc_summary_options(
                    dbase, doc_summary=doc_summary
                )
                self.doc_summary_enricher = DocSummaryEnricher(self.doc_summary_options)
                _log.info(
                    "[runtime_feature] doc_summary mode enabled=%s doc_summary=%s",
                    self.doc_summary_options.enabled,
                    doc_summary,
                )

        def _get_or_create_image_description_enricher(self):
            enricher = getattr(self, "image_description_enricher", None)
            if enricher is None:
                # 테스트 등에서 __init__ 우회 시 legacy attribute 기반으로 재구성
                legacy_options = ImageDescriptionOptions.from_legacy_processor(self)
                enricher = ImageDescriptionEnricher(legacy_options)
                self.image_description_enricher = enricher
            return enricher

        def enrich_image_descriptions(self, document: DoclingDocument, **kwargs: dict) -> DoclingDocument:
            enricher = self._get_or_create_image_description_enricher()
            if enricher is None:
                return document
            return enricher.enrich(document, **kwargs)

        def _get_or_create_doc_summary_enricher(self):
            enricher = getattr(self, "doc_summary_enricher", None)
            if enricher is None:
                base = getattr(self, "_base_doc_summary_options", None)
                enricher = DocSummaryEnricher(base or DocSummaryOptions())
                self.doc_summary_enricher = enricher
            return enricher

        def enrich_doc_summary(self, document: DoclingDocument, **kwargs: dict) -> DoclingDocument:
            enricher = self._get_or_create_doc_summary_enricher()
            if enricher is None:
                return document
            return enricher.enrich(document, **kwargs)

        def _get_or_create_table_description_enricher(self):
            enricher = getattr(self, "table_description_enricher", None)
            if enricher is None:
                base = getattr(self, "_base_table_description_options", None)
                enricher = TableDescriptionEnricher(base or TableDescriptionOptions())
                self.table_description_enricher = enricher
            return enricher

        def enrich_table_descriptions(self, document: DoclingDocument, **kwargs: dict) -> DoclingDocument:
            enricher = self._get_or_create_table_description_enricher()
            if enricher is None:
                return document
            return enricher.enrich(document, **kwargs)

        def enrich_page_descriptions(self, document: DoclingDocument, **kwargs: dict) -> DoclingDocument:
            """페이지 단위 image description: 각 페이지를 렌더링해 설명한 텍스트를 페이지별
        TextItem 으로 주입한다(기존 PictureItem 단위 설명과 별개, 옵션 default False).
        """
            if not self._page_desc_options.enabled:
                return document

            # 페이지별 native text 수집(설명 주입 전) → 프롬프트({{page_text}})에 반영해 요청
            page_texts = collect_page_texts(document)
            page_descs = describe_pages(document, self._page_desc_options, page_texts=page_texts)
            if not page_descs:
                return document

            for page_no in sorted(page_descs.keys()):
                text = page_descs[page_no].strip()
                if not text:
                    continue
                prov = ProvenanceItem(
                    page_no=page_no,
                    bbox=BoundingBox(l=0, t=0, r=1, b=1),
                    charspan=(0, len(text)),
                )
                document.add_text(label=DocItemLabel.TEXT, text=text, prov=prov)
            _log.info(f"[page_image_description] 페이지 설명 주입: pages={len(page_descs)}")
            return document

        async def enrich_metadata(self, document: DoclingDocument, **kwargs: dict) -> DoclingDocument:
            enricher = getattr(self, "metadata_enricher", None)
            if enricher is not None:
                document = await enricher.enrich(document, **kwargs)
            return document

        async def enrich_custom_fields(self, document: DoclingDocument, **kwargs: dict) -> DoclingDocument:
            for enricher in self.custom_fields_enrichers:
                document = await enricher.enrich(document, **kwargs)
            return document

        async def compose_vectors(self, document: DoclingDocument, chunks: List[DocChunk], file_path: str, request: Request, converted_pdf_path: Optional[str] = None, **kwargs: dict) -> \
                list[dict]:
            title = ""
            _sensitive_infos: list = kwargs.get("_sensitive_infos") or []      # #315 분류 결과
            _gr_masking: bool = bool(kwargs.get("_guardrail_masking", False))   # #315 마스킹 치환 on/off
            enrichment_context = kwargs.get("_enrichment_context")
            context_metadata = (
                dict(enrichment_context.get("metadata", {}))
                if isinstance(enrichment_context, dict) and isinstance(enrichment_context.get("metadata"), dict)
                else {}
            )
            document_metadata = extract_metadata_from_document(document)
            merged_metadata = dict(document_metadata)
            merged_metadata.update(context_metadata)
            # 설정 기반 typed 필드 변환 (created_date 등). source/target 키는 passthrough 에서 제외.
            typed_values, consumed_keys = apply_field_transforms(
                self._metadata_field_transforms, merged_metadata, document)

            for item, _ in document.iterate_items():
                if hasattr(item, 'label'):
                    if item.label == DocItemLabel.TITLE:
                        title = item.text.strip() if item.text else ""
                        break

            # kwargs에서 부록 정보 추출 !! appendix feature (2025-09-30, geonhee kim) !!
            appendix_info = kwargs.get('appendix', '')
            appendix_list = []
            if isinstance(appendix_info, str):
                if appendix_info:
                    try:
                        parsed = json.loads(appendix_info)
                        if isinstance(parsed, list):
                            appendix_list = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
                        elif isinstance(parsed, str):
                            appendix_list = [parsed.strip()] if parsed.strip() else []
                        else:
                            appendix_list = []
                    except json.JSONDecodeError:
                        appendix_list = [appendix_info.strip()] if appendix_info.strip() else []
                else:
                    appendix_list = []
            elif isinstance(appendix_info, list):
                appendix_list = appendix_info
            else:
                appendix_list = []

            passthrough_metadata = dict(merged_metadata)
            # GenOSVectorMeta 스키마 예약 필드 + transform 이 소비한 source/target 키는 passthrough 제외.
            reserved_keys = {
                "text", "n_char", "n_word", "n_line", "e_page", "i_page",
                "i_chunk_on_page", "n_chunk_of_page", "i_chunk_on_doc", "n_chunk_of_doc",
                "n_page", "reg_date", "chunk_bboxes", "media_files", "title",
                "created_date", "appendix", "file_path", "metadata", "guardrail_categories",
            } | consumed_keys
            for reserved_key in reserved_keys:
                passthrough_metadata.pop(reserved_key, None)
            passthrough_metadata = {
                key: serialize_metadata_value_for_output(value)
                for key, value in passthrough_metadata.items()
            }

            global_metadata = dict(
                n_chunk_of_doc=len(chunks),
                n_page=document.num_pages(),
                reg_date=datetime.now().isoformat(timespec='seconds') + 'Z',
                title=title,
            )
            global_metadata.update(typed_values)  # 설정 기반 typed 필드 (created_date 등)
            global_metadata.update(passthrough_metadata)
            # 비-PDF 입력이 변환된 경우 vector 의 file_path 를 변환 PDF 경로로 set.
            if converted_pdf_path:
                global_metadata['file_path'] = converted_pdf_path

            current_page = None
            chunk_index_on_page = 0
            vectors = []
            upload_tasks = []
            for chunk_idx, chunk in enumerate(chunks):
                chunk_page = chunk.meta.doc_items[0].prov[0].page_no if chunk.meta.doc_items[0].prov else 0
                # header 앞에 헤더 마커 추가 (HEADER: )
                headers_text = "HEADER: " + ", ".join(chunk.meta.headings) + '\n' if chunk.meta.headings else ''
                content = headers_text + chunk.text

                # appendix 추출 !! appendix feature (2025-09-30, geonhee kim) !!
                matched_appendices = self.check_appendix_keywords(content, appendix_list)
                # print(appendix_list, matched_appendices)
                chunk_global_metadata = global_metadata.copy()
                chunk_global_metadata['appendix'] = matched_appendices  # Only matched ones
                ###

                if chunk_page != current_page:
                    current_page = chunk_page
                    chunk_index_on_page = 0

                # #315 가드레일 분류 후처리: quote 매칭 → guardrail_categories 부착(항상) + 마스킹 치환(옵션)
                content, chunk_cats = gr.apply_to_text(content, _sensitive_infos, _gr_masking)

                vector = (GenOSVectorMetaBuilder()
                          .set_text(content)
                          .set_page_info(chunk_page, chunk_index_on_page, self.page_chunk_counts[chunk_page])
                          .set_chunk_index(chunk_idx)
                          .set_global_metadata(**chunk_global_metadata) #!! appendix feature (2025-09-30, geonhee kim) !!
                          .set_chunk_bboxes(chunk.meta.doc_items, document)
                          .set_media_files(chunk.meta.doc_items, include_tables=self.table_image_enabled)
                          .set_guardrail_categories(sorted(chunk_cats) if chunk_cats else None)
                          ).build()
                vectors.append(vector)

                chunk_index_on_page += 1
                if upload_files:
                    file_list = self.get_media_files(chunk.meta.doc_items, include_tables=self.table_image_enabled)
                    upload_tasks.append(asyncio.create_task(
                        upload_files(file_list, request=request)
                    ))

            if upload_tasks:
                await asyncio.gather(*upload_tasks)

            return vectors

        def _save_table_images(
            self,
            document: DoclingDocument,
            image_dir: Path,
            reference_path: Optional[Path] = None,
        ) -> None:
            """표 영역을 PNG 로 저장하고 TableItem.image.uri 를 설정한다(in-place).

        docling 의 DoclingDocument._with_pictures_refs 가 PictureItem 만 디스크에
        저장하므로, 동일 로직을 TableItem 에 대해 미러링한다. TableItem.get_image 는
        item.image 가 없으면 페이지 이미지에서 prov bbox 로 잘라 반환한다
        (generate_page_images 가 True 여야 함 — __init__ 에서 보장).
        """
            image_dir.mkdir(parents=True, exist_ok=True)
            if not image_dir.is_dir():
                return

            img_count = 0
            for item, _ in document.iterate_items(with_groups=False):
                if not isinstance(item, TableItem):
                    continue
                img = item.get_image(doc=document)
                if img is None:
                    continue
                hexhash = PictureItem._image_to_hexhash(img)
                if hexhash is None:
                    continue
                loc_path = image_dir / f"table_{img_count:06}_{hexhash}.png"
                img.save(loc_path)
                if reference_path is not None:
                    obj_path = relative_path(reference_path.resolve(), loc_path.resolve())
                else:
                    obj_path = loc_path
                # 파이프라인이 표 이미지를 미리 크롭하지 않으므로(generate_table_images 미사용)
                # item.image 는 보통 None 이다. ImageRef 를 생성하되 uri 는 반드시 저장한
                # PNG 파일 경로로 설정한다(from_pil 의 base64 data URI 가 남지 않도록).
                if item.image is None:
                    scale = img.size[0] / item.prov[0].bbox.width
                    item.image = ImageRef.from_pil(image=img, dpi=round(72 * scale))
                item.image.uri = Path(obj_path)
                img_count += 1

        def get_media_files(self, doc_items: list, include_tables: bool = False):
            temp_list = []
            for item in doc_items:
                if isinstance(item, PictureItem) and item.image:
                    path = str(item.image.uri)
                    name = path.rsplit("/", 1)[-1]
                    temp_list.append({'path': path, 'name': name})
                elif include_tables and isinstance(item, TableItem) and item.image:
                    path = str(item.image.uri)
                    name = path.rsplit("/", 1)[-1]
                    temp_list.append({'path': path, 'name': name})
            return temp_list

        def check_glyph_text(self, text: str, threshold: int = 1) -> bool:
            """텍스트에 GLYPH 항목이 있는지 확인하는 메서드"""
            if not text:
                return False

            # GLYPH 항목이 있는지 정규식으로 확인
            matches = re.findall(r'GLYPH\w*', text)
            if len(matches) >= threshold:
                # print(f"Text has glyphs. len(matches): {len(matches)}. ")
                return True

            return False

        def check_glyphs(self, document: DoclingDocument) -> bool:
            """문서에 글리프가 있는지 확인하는 메서드"""
            for item, level in document.iterate_items():
                if isinstance(item, TextItem) and hasattr(item, 'prov') and item.prov:
                    page_no = item.prov[0].page_no
                    # page_texts += item.text

                    # GLYPH 항목이 있는지 확인. 정규식사용
                    matches = re.findall(r'GLYPH\w*', item.text)
                    if len(matches) > self._glyph_document_threshold:
                        # print(f"Document has glyphs on page {page_no}. len(matches): {len(matches)}. ")
                        return True

            return False

        def check_empty_text(self, document: DoclingDocument) -> bool:
            """텍스트 클러스터(박스)는 있는데 그 텍스트가 전부 비어 있는 페이지가 있는지 확인.

        length 폴백(layout_only)이나 텍스트레이어 부재 등으로 박스만 있고 텍스트가
        안 채워진 페이지를 잡아 강제 OCR 로 보낸다(이슈 #278 B-2).
        """
            from collections import defaultdict
            page_item_count: dict = defaultdict(int)
            page_text_len: dict = defaultdict(int)
            for item, _level in document.iterate_items():
                if isinstance(item, TextItem) and hasattr(item, 'prov') and item.prov:
                    page_no = item.prov[0].page_no
                    page_item_count[page_no] += 1
                    page_text_len[page_no] += len((item.text or "").strip())
            for page_no, n_items in page_item_count.items():
                # 텍스트 아이템이 있는데 그 페이지 텍스트 총량이 0 → 비어있는 페이지
                if n_items > 0 and page_text_len[page_no] == 0:
                    _log.info(f"[intelligent] page {page_no} 텍스트가 비어있음 → 강제 OCR 필요")
                    return True
            return False

        def check_appendix_keywords(self, content: str, appendix_list: list) -> str: # !! appendix feature (2025-09-30, geonhee kim) !!
            if not content or not appendix_list:
                return ""

            matched_appendices = []

            # 1. Find appendix patterns in content first
            found_patterns = []

            # Complex patterns: 별지/별표/장부 + numbers (with hyphens, Roman numerals)
            # Updated regex to capture full patterns like "별지 제 Ⅰ -1 호 서식" by matching until closing delimiters
            content = re.sub(r"\s+", "", content)
            complex_patterns = re.findall(r'(별지|별표|장부)(?:제)?([^<>()\[\]]+?)(?=(?:호|서식)|[<>\)\]]|$)', content)
            for pattern_type, number in complex_patterns:
                found_patterns.extend([
                    f"{pattern_type} {number}",
                    f"{pattern_type} 제{number}호",
                    f"{pattern_type}{number}",
                    f"{pattern_type}제{number}호"
                ])

            # Standalone patterns: (별표), (별지), (장부)
            standalone_patterns = re.findall(r'[\(\[]+(별지|별표|장부)[\)\]]+', content)
            for pattern_type in set(standalone_patterns):
                found_patterns.extend([
                    pattern_type,
                    f"{pattern_type}",
                ])

            # 2. Check if found patterns match any appendix in the list
            for appendix in appendix_list:
                if not appendix or not isinstance(appendix, str):
                    continue

                appendix_clean = appendix.replace('.pdf', '').lower().strip()
                appendix_clean_no_space = re.sub(r"\s+", "", appendix_clean)

                # If any found pattern exists in appendix filename, it's a match
                for pattern in found_patterns:
                    pattern_no_space = re.sub(r"\s+", "", pattern).lower()
                    if pattern_no_space in appendix_clean_no_space:
                        matched_appendices.append(appendix)
                        break  # Prevent duplicates

            return ', '.join(matched_appendices) if matched_appendices else ""

        def ocr_all_table_cells(self, document: DoclingDocument, pdf_path) -> List[Dict[str, Any]]:
            """
        글리프 깨진 텍스트가 있는 테이블에 대해서만 OCR을 수행합니다.
        Args:
            document: DoclingDocument 객체
            pdf_path: PDF 파일 경로
        Returns:
            OCR이 완료된 문서의 DoclingDocument 객체
        """
            import io
            import base64
            import requests
            from PIL import Image

            def post_ocr_bytes(img_bytes: bytes, timeout=60) -> dict:
                HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
                payload = {"file": base64.b64encode(img_bytes).decode("ascii"), "fileType": 1, "visualize": False}
                r = requests.post(self.ocr_endpoint, json=payload, headers=HEADERS, timeout=timeout)
                if not r.ok:
                    # 진단에 도움되도록 본문 일부 출력
                    raise RuntimeError(f"OCR HTTP {r.status_code}: {r.text[:500]}")
                return r.json()

            def extract_ocr_fields(resp: dict):
                """
            resp: 위와 같은 OCR 응답 JSON(dict)
            return: (rec_texts, rec_scores, rec_boxes) — 모두 list
            """
                if resp is None:
                    return [], [], []

                # 최상위 상태 체크
                if resp.get("errorCode") not in (0, None):
                    return [], [], []

                ocr_results = (
                    resp.get("result", {})
                        .get("ocrResults", [])
                )
                if not ocr_results:
                    return [], [], []

                pruned = (
                    ocr_results[0]
                    .get("prunedResult", {})
                )
                if not pruned:
                    return [], [], []

                rec_texts  = pruned.get("rec_texts", [])   # list[str]
                rec_scores = pruned.get("rec_scores", [])  # list[float]
                rec_boxes  = pruned.get("rec_boxes", [])   # list[[x1,y1,x2,y2]]

                # 길이 불일치 방어: 최소 길이에 맞춰 자르기
                n = min(len(rec_texts), len(rec_scores), len(rec_boxes))
                return rec_texts[:n], rec_scores[:n], rec_boxes[:n]

            try:
                for table_idx, table_item in enumerate(document.tables):
                    if not table_item.data or not table_item.data.table_cells:
                        continue
                    if not table_item.prov:
                        continue

                    b_ocr = False
                    for cell_idx, cell in enumerate(table_item.data.table_cells):
                        if self.check_glyph_text(cell.text, threshold=self._glyph_table_cell_threshold):
                            b_ocr = True
                            break

                    if b_ocr is False:
                        # 글리프 깨진 텍스트가 없는 경우, OCR을 수행하지 않음
                        continue

                    # docling 이 이미 렌더해 둔 페이지 이미지(generate_page_images=True)를
                    # 재사용해 셀 영역을 crop 한다. PyMuPDF 재렌더(get_pixmap)는 일부 PDF 에서
                    # 네이티브 크래시(SIGSEGV, worker code 139)를 유발하므로 사용하지 않는다.
                    page_no = table_item.prov[0].page_no
                    page = document.pages.get(page_no)
                    if page is None or page.size is None or page.image is None:
                        continue
                    page_image = page.image.pil_image
                    if page_image is None:
                        continue
                    W, H = page_image.size

                    for cell_idx, cell in enumerate(table_item.data.table_cells):
                        try:
                            if cell.bbox is None:
                                continue

                            # docling 셀 bbox(BOTTOMLEFT) → 페이지 이미지 픽셀 좌표(TOPLEFT)
                            crop = (
                                cell.bbox
                                .to_top_left_origin(page_height=page.size.height)
                                .scale_to_size(old_size=page.size, new_size=page.image.size)
                            )
                            x0, y0, x1, y1 = crop.as_tuple()
                            # 정규화 + 페이지 경계 클램프 + degenerate skip
                            x0, x1 = sorted((x0, x1))
                            y0, y1 = sorted((y0, y1))
                            x0 = max(0, min(x0, W)); x1 = max(0, min(x1, W))
                            y0 = max(0, min(y0, H)); y1 = max(0, min(y1, H))
                            if (x1 - x0) < 1 or (y1 - y0) < 1:
                                continue

                            cell_img = page_image.crop((x0, y0, x1, y1))

                            # 아주 작은 셀은 OCR 가독성을 위해 확대(기존 target_height=20, ≤4x)
                            ch = y1 - y0
                            zoom = min(max(20.0 / ch, 1.0), 4.0) if ch > 0 else 1.0
                            if zoom > 1.0:
                                cell_img = cell_img.resize(
                                    (max(1, round((x1 - x0) * zoom)), max(1, round(ch * zoom))),
                                    Image.LANCZOS,
                                )

                            buf = io.BytesIO()
                            cell_img.save(buf, format="PNG")
                            img_data = buf.getvalue()

                            result = post_ocr_bytes(img_data, timeout=self._table_cell_ocr_timeout)
                            rec_texts, rec_scores, rec_boxes = extract_ocr_fields(result)

                            cell.text = ""
                            for t in rec_texts:
                                if len(cell.text) > 0:
                                    cell.text += " "
                                cell.text += t if t else ""
                        except Exception as cell_err:
                            # 한 셀 실패가 나머지 셀/표를 막지 않도록 격리
                            print(f"OCR cell processing failed (table={table_idx}, cell={cell_idx}): {cell_err}")
                            continue
            except Exception as e:
                print(f"OCR processing failed: {e}")
                pass

            return document

        def setup_logging(self, level_num: int):
            """
            5"DEBUG", 4"INFO", 3"WARNING", 2"ERROR", 1"CRITICAL", 0"NOLOG" 중 하나를 받아서 로깅 레벨을 설정하는 메서드
        """
            def get_level_name(level_num: int) -> str:
                level_map = {
                    5: "DEBUG",
                    4: "INFO",
                    3: "WARNING",
                    2: "ERROR",
                    1: "CRITICAL",
                    0: "NOLOG"
                }
                return level_map.get(level_num, "INFO")
            level_name = get_level_name(level_num)
            print(f"Setting log level to: {level_name}")

            if level_name == "NOLOG" or not hasattr(logging, level_name):
                logging.disable(logging.CRITICAL)  # 모든 로그 비활성화
                return

            level = getattr(logging, level_name.upper())

            # root logger 설정 (핸들러는 main에서만 설정)
            logging.basicConfig(
                level=level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                handlers=[logging.StreamHandler()]   # 콘솔 출력
            )

            # root logger level 적용
            logging.getLogger().setLevel(level)

        def _convert_to_pdf(self, file_path: str, **kwargs: dict) -> tuple[str, str]:
            """비-PDF 입력을 PDF SDK/LibreOffice 로 변환. (변환된 file_path, converted_pdf_path) 반환."""
            # 변환 backend(pdf_sdk/rhwp/libreoffice)가 전무하면(이슈 #286 — 빌드 시 OFF)
            # 변환 시도 자체가 무의미하므로, PDF 직접 입력을 안내하며 즉시 중단한다.
            if not _has_any_pdf_converter():
                raise GenosServiceException(
                    1,
                    f"이 전처리기 이미지에는 PDF 변환기(rhwp/LibreOffice/PDF SDK)가 설치되어 "
                    f"있지 않아 '{os.path.basename(file_path)}' 를 PDF 로 변환할 수 없습니다. "
                    f"PDF 로 변환한 파일을 입력하거나, 변환기를 포함해 전처리기 이미지를 다시 "
                    f"빌드하세요 (genon/README.md 참고).",
                )
            _log.info(f"[intelligent] Non-PDF input — auto-converting to PDF: {file_path}")
            use_sdk = kwargs.get('use_pdf_sdk', True)
            converted = convert_to_pdf(file_path, use_pdf_sdk=use_sdk)
            if (not converted or not os.path.exists(converted)) and use_sdk:
                _log.warning(f"[intelligent] SDK conversion failed → fallback to LibreOffice")
                converted = convert_to_pdf(file_path, use_pdf_sdk=False)
            if not converted or not os.path.exists(converted):
                raise GenosServiceException(1, f"PDF 변환 실패: {file_path}")
            _log.info(f"[intelligent] Converted PDF: {converted}")
            return converted, converted

        async def _process_xlsx(self, request: Request, file_path: str, **kwargs: dict):
            """xlsx/csv 직접 처리(이슈 #288): PDF 변환 없이 처리해 행 분할 버그 방지.
          - tabular: 데이터 행마다 1청크(벡터)로 만들어 즉시 반환
          - docling(기본): MsExcel 백엔드로 DoclingDocument 생성 후 공유 파이프라인으로 합류
        """
            from genon.preprocessor.converters.xlsx_processor import (
                build_docling_document,
                build_tabular_vectors,
            )
            if self._xlsx_cfg["processing_mode"] == "tabular":
                _log.info(f"[intelligent] xlsx tabular 직접 처리: {file_path}")
                vectors = build_tabular_vectors(
                    file_path,
                    header_row=self._xlsx_cfg["header_row"],
                    multi_table=self._xlsx_cfg["multi_table"],
                )
                if not vectors:
                    raise GenosServiceException(1, f"chunk length is 0")
                return vectors

            _log.info(f"[intelligent] xlsx docling 직접 처리(PDF 변환 생략): {file_path}")
            try:
                document = build_docling_document(
                    file_path, save_images=kwargs.get('save_images', False)
                )
            except Exception as e:
                raise GenosServiceException(
                    1, f"xlsx 처리 실패: {os.path.basename(file_path)} ({e})"
                )
            # openpyxl 텍스트라 글리프 깨짐이 없고 렌더 PDF 도 없으므로 테이블셀 재OCR 은 생략.
            # table_as_chunk=True: 시트/표마다 별도 청크로 분리(엑셀은 표 단위가 논리 단위).
            return await self._document_to_vectors(
                document, file_path, request,
                converted_pdf_path=None, ocr_table_cells=False, table_as_chunk=True, **kwargs
            )

        async def _process_pdf(self, request: Request, file_path: str,
                               converted_pdf_path: Optional[str], is_ppt: bool = False,
                               source_file_path: Optional[str] = None, **kwargs: dict):
            """PDF(또는 PDF 로 변환된) 입력을 docling 으로 로딩 후 공유 파이프라인으로 처리."""
            document = self._load_document(file_path, **kwargs)

            # HWP/HWPX 품질 복구(선택적): PDF 변환이 내용을 잃으면(text score 낮음) rhwp 재변환
            # 재시도 → 개선되면 교체. HWPX 는 네이티브 XML 추출로 추가 폴백. hwp_recovery 모듈이
            # 로드된 경우에만 적용하고, 없으면 로딩된 document 를 그대로 통과(기존 동작).
            # source_file_path 는 변환 전 원본(.hwp/.hwpx). 정상 문서는 score≥임계값 이라 미진입.
            if source_file_path is None:
                source_file_path = file_path
            if self._hwp_recovery is not None:
                file_path, converted_pdf_path, document = self._hwp_recovery.recover(
                    document, source_file_path, file_path, converted_pdf_path, **kwargs
                )

            return await self._document_to_vectors(
                document, file_path, request,
                converted_pdf_path=converted_pdf_path, ocr_table_cells=True, is_ppt=is_ppt, **kwargs
            )

        def _load_document(self, file_path: str, **kwargs: dict) -> DoclingDocument:
            """ocr_mode 에 따라 docling 문서를 로딩한다.
        "force"=무조건 전체 OCR / "auto"=휴리스틱 기반 재OCR / "disable"=OCR 안 함
        """
            if self.ocr_mode == "force":
                return self.load_documents_with_docling_ocr(file_path, **kwargs)
            document: DoclingDocument = self.load_documents(file_path, **kwargs)
            if self.ocr_mode == "auto":
                if not check_document(document, self.enrichment_options) or self.check_glyphs(document) or self.check_empty_text(document):
                    # OCR이 필요하다고 판단되면 OCR 수행
                    document = self.load_documents_with_docling_ocr(file_path, **kwargs)
            return document

        async def _document_to_vectors(self, document: DoclingDocument, file_path: str,
                                       request: Request, *, converted_pdf_path: Optional[str],
                                       ocr_table_cells: bool, is_ppt: bool = False, **kwargs: dict) -> list:
            """DoclingDocument → enrichment → 청킹 → 벡터 생성(공유 파이프라인).

        ocr_table_cells: 글리프 깨진 테이블 셀 재OCR 수행 여부(xlsx 직접 처리는 False).
        """
            # 글리프 깨진 텍스트가 있는 테이블에 대해서만 OCR 수행 (청크토큰 8k이상 발생 방지)
            if ocr_table_cells and self.ocr_mode != "disable" and self.ocr_endpoint:
                document = self.ocr_all_table_cells(document, file_path)

            output_path, output_file = os.path.split(file_path)
            filename, _ = os.path.splitext(output_file)
            artifacts_dir = Path(output_path) / filename  # 빈 output_path 가 절대경로(/filename)로 바뀌는 것 방지
            if artifacts_dir.is_absolute():
                reference_path = None
            else:
                reference_path = artifacts_dir.parent

            document = document._with_pictures_refs(image_dir=artifacts_dir, page_no=None, reference_path=reference_path)

            # 표 이미지 저장 옵션이 켜진 경우, picture 와 동일하게 표 영역을 PNG 로 저장하고
            # TableItem.image.uri 를 설정한다(_with_pictures_refs 미러).
            if self.table_image_enabled:
                self._save_table_images(document, image_dir=artifacts_dir, reference_path=reference_path)

            document = self.enrichment(document, is_ppt=is_ppt, **kwargs)

            enrichment_context = kwargs.get("_enrichment_context", {})
            if not isinstance(enrichment_context, dict):
                enrichment_context = {}
            enrichment_kwargs = dict(kwargs)
            enrichment_kwargs["_enrichment_context"] = enrichment_context
            # #329: error_policy=strict 이면 _handle_stage_error 가 GenosServiceException 으로
            # 재-raise(삼키지 않음). lenient(기본)은 기존처럼 warning 후 계속.
            try:
                document = self.enrich_doc_summary(document, **enrichment_kwargs)
            except Exception as exc:
                _handle_stage_error(exc, "doc_summary")
            try:
                document = self.enrich_image_descriptions(document, **enrichment_kwargs)
            except Exception as exc:
                _handle_stage_error(exc, "image_description")
            try:
                document = self.enrich_table_descriptions(document, **enrichment_kwargs)
            except Exception as exc:
                _handle_stage_error(exc, "table_description")
            # 페이지 단위 image description 은 PPT 원본에만 적용(formats.ppt.page_description).
            if is_ppt:
                try:
                    document = self.enrich_page_descriptions(document, **enrichment_kwargs)
                except Exception as exc:
                    _handle_stage_error(exc, "page_description")
            try:
                document = await self.enrich_metadata(document, **enrichment_kwargs)
            except Exception as exc:
                _handle_stage_error(exc, "metadata")
            try:
                document = await self.enrich_custom_fields(document, **enrichment_kwargs)
            except Exception as exc:
                _handle_stage_error(exc, "custom_fields")

            # 민감정보 분류(#315): 청킹 전, 문서 전체를 분류 워크플로우에 1회 호출 → sensitive_infos.
            # 실제 라벨 부착/마스킹 치환은 청킹 후 compose 에서 quote 매칭으로 수행.
            sensitive_infos: list = []
            if gr.call_enabled(kwargs):
                sensitive_infos = gr.classify_document(
                    gr.doc_text(document), self._guardrail_url, self._guardrail_workflow_id,
                    self._guardrail_api_key, self._guardrail_timeout,
                )

            has_text_items = False
            for item, _ in document.iterate_items():
                if (isinstance(item, (TextItem, ListItem, CodeItem, SectionHeaderItem)) and item.text and item.text.strip()) or (isinstance(item, TableItem) and item.data and len(item.data.table_cells) == 0):
                    has_text_items = True
                    break

            if has_text_items:
                # Extract Chunk from DoclingDocument.
                # PPT 는 페이지 기반 청킹(기본 1 page 1 chunk, chunk_size 지정 시 페이지 결합).
                if is_ppt:
                    chunks: List[DocChunk] = self.split_documents_by_page(document, **kwargs)
                else:
                    chunks: List[DocChunk] = self.split_documents(document, **kwargs)
            else:
                # text가 있는 item이 없을 때 document에 임의의 text item 추가
                # 첫 번째 페이지의 기본 정보 사용 (1-based indexing)
                page_no = 1

                # ProvenanceItem 생성
                prov = ProvenanceItem(
                    page_no=page_no,
                    bbox=BoundingBox(l=0, t=0, r=1, b=1),  # 최소 bbox
                    charspan=(0, 1)
                )

                # document에 temp text item 추가
                document.add_text(
                    label=DocItemLabel.TEXT,
                    text=".",
                    prov=prov
                )

                # split_documents 호출
                if is_ppt:
                    chunks: List[DocChunk] = self.split_documents_by_page(document, **kwargs)
                else:
                    chunks: List[DocChunk] = self.split_documents(document, **kwargs)
            # await assert_cancelled(request)

            vectors = []
            if len(chunks) >= 1:
                vectors: list[dict] = await self.compose_vectors(
                    document, chunks, file_path, request,
                    converted_pdf_path=converted_pdf_path,
                    _sensitive_infos=sensitive_infos,
                    _guardrail_masking=(gr.call_enabled(kwargs) and self._guardrail_masking_enabled),
                    **enrichment_kwargs,
                )
            else:
                raise GenosServiceException(1, f"chunk length is 0")

            # 변환된 PDF 를 minio 에 업로드. object key 는 원본 파일명의 stem + ".pdf".
            # (예: 원본 file_name='sample.hwp' → minio key='<doc_id>/sample.pdf')
            # upload_files 가 finally 에서 org_path 를 os.remove 하는데, 변환 PDF 의
            # NFS 원본은 GenOS UI 의 PDF preview 가 직접 참조하므로 보존 필요.
            # → 임시 사본을 만들어 그것만 업로드시키고 NFS 원본은 그대로 둔다.
            if converted_pdf_path and upload_files:
                original_name = kwargs.get('file_name') or os.path.basename(converted_pdf_path)
                pdf_object_name = os.path.splitext(original_name)[0] + '.pdf'
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as _tmp:
                    shutil.copy(converted_pdf_path, _tmp.name)
                    _tmp_upload_path = _tmp.name
                await upload_files(
                    [{'path': _tmp_upload_path, 'name': pdf_object_name}],
                    request=request,
                )

            """
        # 미디어 파일 업로드 방법
        media_files = [
            { 'path': '/tmp/graph.jpg', 'name': 'graph.jpg', 'type': 'image' },
            { 'path': '/result/1/graph.jpg', 'name': '1/graph.jpg', 'type': 'image' },
        ]

        # 업로드 요청 시에는 path, name 필요
        file_list = [{k: v for k, v in file.items() if k != 'type'} for file in media_files]
        await upload_files(file_list, request=request)

        # 메타에 저장시에는 name, type 필요
        meta = [{k: v for k, v in file.items() if k != 'path'} for file in media_files]
        vectors[0].media_files = meta
        """

            return vectors

        async def __call__(self, request: Request, file_path: str, **kwargs: dict):
            runtime_level = kwargs.get('log_level')
            self.setup_logging(runtime_level if runtime_level is not None else self._log_level)

            # 런타임 토글(img_desc/chart_desc/chart_detection/doc_summary)로 이미지·차트 description 재구성
            kwargs = self._normalize_runtime_kwargs(kwargs)
            self._configure_runtime_image_mode(kwargs)

            # #329: LLM 캐시 / error_policy 컨텍스트를 요청 스코프로 설정.
            # ThreadPool 워커 스레드로는 in_current_context 로 전파된다(docling/utils/llm_cache).
            _cache_token = _set_cache_context(_resolve_cache_context(kwargs))
            try:
                _log.info(f"file_path: {file_path}")
                _log.info(f"kwargs: {kwargs}")

                # 비정상 파일 사전 감지(이슈 #278): 지원 포맷 매직헤더에 하나도 안 맞고 텍스트도
                # 아니면(=DRM 암호화/손상 바이너리) 변환 시 garbage PDF → VLM 무한 출력/행을
                # 유발하므로 변환 전에 컷한다. 확장자와 무관하게 실제 헤더로 판정.
                bad_reason = _detect_unsupported_file(file_path)
                if bad_reason:
                    _log.warning(
                        f"[intelligent] 비정상 파일 감지({bad_reason}) — 처리 중단: {file_path}"
                    )
                    raise GenosServiceException(
                        "1", f"{bad_reason} 입니다. 정상 문서로 다시 업로드하세요: {os.path.basename(file_path)}"
                    )

                ext = os.path.splitext(file_path)[1].lower()

                # 직접 처리(PDF 변환 없이) 가능한 포맷(이슈 #288): 엑셀 계열(xlsx/xlsm) + csv.
                # csv 는 본질적으로 tabular 이므로 항상 직접 처리한다(PDF 변환 시 행 분할 문제 방지).
                # (.xls/.xlsb 는 openpyxl/docling 미지원 → 아래 PDF 변환 경로로 처리)
                # 이 집합을 변환 가드와 디스패치 양쪽에서 동일하게 써서 "직접 처리 포맷 == 변환 제외 포맷"
                # 불변식을 유지한다.

                # 직접 처리 포맷이 아니고 PDF 도 아니면 PDF 로 변환한다.
                # - auto_convert_to_pdf=True (default): PDF SDK/LibreOffice 로 자동 변환 후 진입
                # - auto_convert_to_pdf=False: 변환 없이 그대로 진행 (변경 전 동작; PDF 가정)
                converted_pdf_path: Optional[str] = None
                # HWP/HWPX 품질 복구가 참조할 변환 전 원본 경로(rhwp 재변환/네이티브 추출용).
                source_file_path = file_path
                if ext not in _XLSX_DIRECT_EXTS and kwargs.get('auto_convert_to_pdf', True) and not _is_pdf(file_path):
                    file_path, converted_pdf_path = self._convert_to_pdf(file_path, **kwargs)

                # 포맷별 처리: 직접 처리 가능 포맷은 xlsx 핸들러, 그 외는 PDF(docling) 처리.
                if ext in _XLSX_DIRECT_EXTS:
                    return await self._process_xlsx(request, file_path, **kwargs)
                # 원본이 PPT 였는지(변환 전 ext)를 명시 전달 — 페이지 기반 청킹/page description 게이팅용.
                is_ppt = ext in ('.ppt', '.pptx')
                return await self._process_pdf(
                    request, file_path, converted_pdf_path, is_ppt=is_ppt,
                    source_file_path=source_file_path, **kwargs
                )
            finally:
                _log_cache_summary()
                _reset_cache_context(_cache_token)


    class GenosServiceException(Exception):
        # GenOS 와의 의존성 부분 제거를 위해 추가
        def __init__(self, error_code: str, error_msg: Optional[str] = None, msg_params: Optional[dict] = None,
                     *, stage: Optional[str] = None, error_type: Optional[str] = None) -> None:
            self.code = 1
            self.error_code = error_code
            self.error_msg = error_msg or "GenOS Service Exception"
            self.msg_params = msg_params or {}
            # #329: 실패 단계(stage)와 성격(error_type: transient/permanent/timeout).
            self.stage = stage
            self.error_type = error_type

        def __repr__(self) -> str:
            class_name = self.__class__.__name__
            return f"{class_name}(code={self.code!r}, errMsg={self.error_msg!r})"


    # GenOS 와의 의존성 제거를 위해 추가
    async def assert_cancelled(request: Request):
        if await request.is_disconnected():
            raise GenosServiceException(1, f"Cancelled")

except Exception as _fp_exc:  # noqa: BLE001 - 무엇이 빠졌든 hwpx 경로는 살린다
    _FP_INTELLIGENT_IMPORT_ERROR = _fp_exc
    _FP_INTELLIGENT_IMPORT_TRACE = traceback.format_exc()


# ===========================================================================
# PART 3 — hwpx 전용 파서 (onprem/preprocessor/hwpx_preprocessor.py 원문)
# ===========================================================================
"""GenOS 전처리기(area 05) — hwpx 전용. **이 파일 하나가 등록 단위다.**

## 왜 파일이 하나인가

GenOS 전처리기는 MCP 와 같은 방식으로 등록한다 — 생성·수정 화면에 소스 **파일 하나**를
그대로 올리고, 그 파일이 정의하는 `DocumentProcessor` 를 런타임이 그대로 실행한다
(`onprem/mcp/README.md` 의 MCP 등록 방식과 동일한 제약. `docs/GENOS_RULES.md` §C 의
"전처리기 | 생성·수정 화면의 환경 변수" 항목도 코드서빙의 Git 저장소 방식과는 다른
파일 단위 등록임을 가리킨다). 그래서 이 파일은 **다른 파일을 import 하지 않는다**
(표준 라이브러리 + `lxml` 만) — 패키지로 쪼개면 등록 시점에 나머지 파일이 따라가지
않는다.

## 계약 (`docs/GENOS_RULES.md` §A.4, §F)

- 인자 없이 생성 가능한 `DocumentProcessor`, 비동기 `__call__(request, file_path, **kwargs)`
- 반환은 `list[dict]`. 각 항목에 **`text` 키 필수**(임베딩이 직접 읽는다), 빈 문자열 불가
- `page`·`bbox` 등 **실제로 못 채우는 필드는 지어내지 않고 `None`** 으로 둔다
- 오류는 오류 dict 를 반환하지 않고 **예외를 던진다** (로그에 오류코드 남긴 뒤)

## 지능형 전처리기와 다른 점 — 왜 새로 만들었나

`genos_files/intelligence_processor.py` 의 `DocumentProcessor` 는 hwpx 를 포함한
비-PDF 입력을 **무조건 PDF 로 변환한 뒤** docling 으로 읽는다. 그 변환에서 표 안의
`rowSpan`/`colSpan` 이 깨지고 셀 좌표가 다시 계산되며, 수치가 어느 항목의 값인지가
사라진다(`onprem/preprocessor/README.md` "왜 만들었나" 절, 요구사항 §5). 이 파일은
hwpx 를 PDF 로 바꾸지 않고 **ZIP 안의 `Contents/sectionN.xml` 을 직접 읽어** 문단과
표를 판정한다 — 표는 **언제나 한 줄짜리 HTML** 로 낸다(`_render_table` 이 이유를 적는다:
검색 결과가 LLM 에게 갈 때 개행이 뭉개져 마크다운 표는 표가 아니게 된다).
그 대가로 **페이지 번호가 없다**(hwpx 는 흐름 문서라 렌더링 전에는 페이지가 정해지지
않는다) — 지어내지 않고 `None` 으로 둔다. 페이지가 꼭 필요하면 지능형 전처리기(PDF
경로)를 써야 하고, 그건 표가 깨지는 쪽이다. 둘 중 하나를 고르는 것이지 이 파일이
흉내 낼 일이 아니다.

**다른 파일 형식은 다루지 않는다.** hwpx 가 아닌 확장자는 명시적으로 거부한다 —
지능형/첨부용 전처리기가 이미 그 형식들을 처리하고 있으므로 여기서 다시 구현할
이유가 없다.

## 글자는 하나도 버리지 않는다 (2026-08-19)

표를 지키려고 만든 파서였는데, 정작 **표가 아닌 글자를 여러 자리에서 잃고 있었다.**
전부 예외 없이 조용히 사라지는 종류라 — 남은 문장이 멀쩡해 보여서 — 그 문장을 물어봤을
때 검색이 아무것도 못 찾을 때까지 드러나지 않았다. 네 자리다:

| 잃던 것 | 왜 | 지금 |
|---|---|---|
| 탭·강제 줄바꿈 **뒤** 글자 | `hp:t` 는 혼합 내용이라 그 글자가 자식의 `tail` 에 있는데 `node.text` 만 읽었다 | `_inline_text` 가 `tail` 까지 훑는다 |
| 글상자·도형·각주·머리말·캡션·메모 안 글 | 중첩 문단(`hp:subList > hp:p`)을 "본문 흐름이 아니다" 로 통째로 건너뛰었다 | `_emit_paragraph` 가 상자로 재귀한다 |
| 개요 번호(`1.`·`가.`)와 글머리표(`-`) | 문단 텍스트가 아니라 `Contents/header.xml` 의 정의에서 나온다 | `_Markers` 가 복원한다 |
| 수식 | `hp:equation > hp:script` 에 있어 `hp:t` 만 보면 안 잡힌다 | `_own_text` 가 함께 읽는다 |

**상자인지는 이름 목록이 아니라 생김새(`hp:subList` 를 자식으로 두는가)로 판정한다** —
목록으로 두면 거기 안 적힌 상자가 예전처럼 조용히 버려지고, 빠뜨렸다는 사실을 아무도
모른 채로 남는다.

## GenOS 등록 시 넘기는 값 (`__call__` 의 `**kwargs`)

| 키 | 기본값 | 의미 |
|---|---|---|
| `chunk_size` | 1000 | 청크 최대 문자 수 |
| `chunk_overlap` | 100 | 문단 청크 사이 겹침 문자 수 (표 조각에는 적용 안 됨) |
| `outline_mode` | `auto` | 위계 판정 — `auto`/`statute`(법령)/`document`(공문서)/`off` |
| `file_name` | `file_path` 의 basename | 검색 결과 출처 표시용 |
| `extra_metadata` | 없음 | 모든 레코드에 병합할 dict (`security_level` 등 배포별 필드) |

값이 없거나 잘못된 타입/범위면 **에러를 내지 않고 기본값으로 떨어진다** — 등록 화면의
파라미터 입력 실수가 전체 재적재를 막으면 안 되기 때문이다. 대신 로그에 남긴다.
"""


import html as _html
import io
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from lxml import etree

_log = logging.getLogger(__name__)

# 3.8절 기록 허용 필드. **선언만 해 두고 강제하지 않으면 없는 것과 같다** — 2026-08-30
# 까지 이 상수는 참조가 0건이었고, 일곱 개 호출부가 `extra={...}` 를 손으로 적고 있었다.
# 지금은 `_emit_log` 하나를 지나므로 새 필드를 무심코 실을 자리가 없다 (다른 여덟 단위의
# `logging_utils` 와 같은 모양이다).
#
# **`id_ref` 가 여기 있는 것은 의도다.** 문서 안 번호 정의를 가리키는 값이지 본문 내용이
# 아니고, 없으면 "폴백을 밟았다" 는 사실은 남는데 **어느 정의에서인지가 사라져** 진단이
# 안 된다 (번역·FAQ 사본은 화이트리스트가 달라 같은 값을 `resource_id` 로 싣는다 —
# 루트 `CLAUDE.md` "그 층을 사본 넷으로 옮겼다" 절).
_ALLOWED_LOG_FIELDS = (
    "event",
    "trace_id",
    "request_id",
    "resource_id",
    "status",
    "duration_ms",
    "item_count",
    "upstream_status",
    "error_code",
    "error_type",
    "id_ref",
)


def _emit_log(level: int, message: str, *, event: str, **fields: Any) -> None:
    """허용 필드만 `extra` 로 넘긴다. 나머지는 **버리고 이름만** 메시지에 남긴다.

    문서 원문·파일 경로가 로그로 새는 경로를 만들지 않는 것이 목적이다. 버린 사실을
    메시지에 남기는 이유: 조용히 버리면 "로그에 그 값이 왜 없나" 를 추적할 수 없다.
    """
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in _ALLOWED_LOG_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    _log.log(level, message, extra=extra)


def _log_info(message: str, *, event: str, **fields: Any) -> None:
    _emit_log(logging.INFO, message, event=event, **fields)


def _log_warning(message: str, *, event: str, **fields: Any) -> None:
    _emit_log(logging.WARNING, message, event=event, **fields)

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"

_PARA = f"{{{HP_NS}}}p"
_TEXT = f"{{{HP_NS}}}t"
_TBL = f"{{{HP_NS}}}tbl"
_TR = f"{{{HP_NS}}}tr"
_TC = f"{{{HP_NS}}}tc"
_CELL_ADDR = f"{{{HP_NS}}}cellAddr"
_CELL_SPAN = f"{{{HP_NS}}}cellSpan"
_POS = f"{{{HP_NS}}}pos"

_SECTION_ENTRY_RE = re.compile(r"^Contents/section(\d+)\.xml$")
_HEADER_ENTRY = "Contents/header.xml"

# ── 문단을 품는 상자들 ────────────────────────────────────────────────────────
#
# **글자를 담는 곳은 표 셀만이 아니다.** 글상자·도형(`hp:drawText`), 캡션, 각주·미주,
# 머리말·꼬리말, 숨은 설명, 메모가 전부 자기 안에 `hp:subList > hp:p` 를 갖는다.
# 예전에는 "본문 흐름이 아니다" 는 이유로 **중첩 문단을 통째로 버렸는데**, 버린 것이
# 곧 문서에 보이는 글자라 적재된 문서에서 그만큼이 조용히 사라졌다 — 표가 깨지는 것과
# 달리 **없어진 자리가 아무 흔적도 남기지 않아** 검색에서 안 나올 때까지 드러나지 않는다.
#
# 지금은 전부 낸다. 어디서 온 글인지 헷갈리지 않게 라벨만 붙이되, **글상자·캡션은
# 본문과 같은 글이라 라벨이 없다** — 라벨은 본문에 없던 글자를 더하는 것이므로 그 글이
# 본문 흐름 밖에 있을 때만 붙인다.
_DRAW_TEXT = f"{{{HP_NS}}}drawText"
_CAPTION = f"{{{HP_NS}}}caption"
_FOOT_NOTE = f"{{{HP_NS}}}footNote"
_END_NOTE = f"{{{HP_NS}}}endNote"
_PAGE_HEADER = f"{{{HP_NS}}}header"
_PAGE_FOOTER = f"{{{HP_NS}}}footer"
_HIDDEN_COMMENT = f"{{{HP_NS}}}hiddenComment"
_MEMO = f"{{{HP_NS}}}memo"

_BOX_LABELS = {
    _DRAW_TEXT: "",
    _CAPTION: "",
    _FOOT_NOTE: "[각주] ",
    _END_NOTE: "[미주] ",
    _PAGE_HEADER: "[머리말] ",
    _PAGE_FOOTER: "[꼬리말] ",
    _HIDDEN_COMMENT: "[숨은 설명] ",
    _MEMO: "[메모] ",
}
# **상자인지는 이름표가 아니라 생김새로 판정한다.** 위 표는 "뭐라고 부를까" 만 정한다 —
# 목록으로 판정하면 여기 안 적힌 상자(덧말 등 hwpx 가 나중에 늘릴 수 있는 것)가 예전처럼
# 조용히 버려지고, 그 손실은 이름을 빠뜨렸다는 사실을 아무도 모르는 채로 남는다.
# hwpx 에서 문단을 담는 것은 예외 없이 **`hp:subList` 를 직접 자식으로 두는 원소**다
# (표 셀도 그렇다). 그 모양을 기준으로 본다.
_SUBLIST = f"{{{HP_NS}}}subList"

# 수식은 `hp:equation > hp:script` 안에 원본 문자열로 들어 있다. `hp:t` 가 아니라서
# 예전 파서에는 아예 안 잡혔다 — 수식 하나가 통째로 빠지면 그 문단의 뜻이 바뀐다.
_EQUATION = f"{{{HP_NS}}}equation"
_SCRIPT = f"{{{HP_NS}}}script"

# `hp:t` 는 **혼합 내용**이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
# 들어가고, **그 뒤에 오는 글자는 자식의 `tail` 에 담긴다.** `node.text` 만 읽으면
# 첫 조판 문자 뒤의 글자를 전부 잃는다 — `가.<hp:tab/>지원 대상` 이 `가.` 만 남는 식이다.
_INLINE_CHARS = {
    f"{{{HP_NS}}}tab": "\t",
    f"{{{HP_NS}}}lineBreak": "\n",
    f"{{{HP_NS}}}hyphen": "-",
    f"{{{HP_NS}}}nbSpace": " ",
    f"{{{HP_NS}}}fwSpace": "　",
}

# <hp:t> 안의 \n 은 문단 분리가 아니다 — 그대로 두면 마크다운에서 문단이 갈린다
_NEWLINE_REPLACEMENT = " "
# 셀 안 줄바꿈은 표 한 칸을 여러 줄로 만든다 — 표에서만 <br> 로 바꾼다
_CELL_LINE_BREAK = "<br>"

# 문장 경계 — **구분자를 소비하지 않는 lookbehind 만** 쓴다. `(?<=[다요])\.\s+` 를
# 함께 뒀다가 테스트에 걸렸다: 그쪽은 마침표를 소비해 "완료하였습니다. 본 사업은" 이
# "완료하였습니다 본 사업은" 으로 바뀌었다 — 청킹이 본문 글자를 지운 것이다.
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")

# ── 조문 위계 (편/장/절/관/조/항/호/목) ────────────────────────────────────────
#
# **이 사다리는 추측이 아니라 문법이다.** 법령·행정규칙의 조문 구조는 발행처가 정한
# 표기(조 → 항 `①` → 호 `1.` → 목 `가.`)를 따르므로, 마크다운 표 문법이나 hwpx 슬롯
# 문법과 같은 성격의 결정적 규칙으로 적는다. LLM 에 물을 이유가 없고, 물으면 같은
# 문서가 적재할 때마다 다른 청크로 갈릴 수 있다(청크 경계는 결정적이어야 한다).
#
# **다만 "어느 사다리인가" 는 결정적이지 않다.** 같은 `1.` 이 법령에서는 호(조 아래
# 3단계)이고 공문서에서는 최상위 항목이다. 그래서 사다리를 문서에 무조건 적용하지 않고
# `outline_mode="auto"` 가 조문 표기를 실제로 세어 본 뒤에만 켠다 — 아래 참고.
_OUTLINE_OFF = "off"
_OUTLINE_AUTO = "auto"
_OUTLINE_STATUTE = "statute"
# 공문서 사다리. **`auto` 는 이 값을 절대 내지 않는다** — 같은 `1.` 이 법령에서는
# 호(레벨 7)이고 공문서에서는 최상위라, 자동으로 고르면 어느 쪽이든 문서 절반이 틀린다.
_OUTLINE_DOCUMENT = "document"
_OUTLINE_MODES = (_OUTLINE_AUTO, _OUTLINE_STATUTE, _OUTLINE_DOCUMENT, _OUTLINE_OFF)

# 조 = 5. 청킹은 **이 레벨 이하(편·장·절·관·조)에서만 끊는다** — 항·호·목에서 끊으면
# 조문 하나가 여러 청크로 흩어져 "제5조가 무엇을 정하는가" 에 답할 수 없게 된다.
_LEVEL_ARTICLE = 5

# 제목 줄기(`outline_path`)에는 **구조 제목까지만** 담는다. 항·호·목은 제목이 아니라
# 조문의 **내용**이라, 줄기에 넣으면 머리말이 본문 문장을 통째로 되풀이한다
# (`제5조(목적) > ① 직원은 성실히 근무하여야 한다. > 1. 근무시간을 준수할 것 > …`).
_LEVEL_PATH_MAX = _LEVEL_ARTICLE

# 목(目) 기호는 가나다 순서다. `[가-힣]\.` 로 넓게 잡으면 "완료.", "사업." 같은 본문
# 문단이 목으로 승격된다.
_MOK_LETTERS = "가나다라마바사아자차카타파하"

# 인용과 제목을 가르는 것은 **뒤에 오는 글자**다. `제5조(목적)` 은 제목이고
# `제5조에 따라` 는 본문 인용이다 — 조사(가-힣)가 붙으면 제목이 아니다.
_NOT_CITED = r"(?![가-힣])"

_STATUTE_RULES = (
    (1, re.compile(rf"^제\s*\d+\s*편{_NOT_CITED}")),
    (2, re.compile(rf"^제\s*\d+\s*장{_NOT_CITED}")),
    (2, re.compile(r"^부\s*칙(?=[\s(<[]|$)")),
    (3, re.compile(rf"^제\s*\d+\s*절{_NOT_CITED}")),
    (4, re.compile(rf"^제\s*\d+\s*관{_NOT_CITED}")),
    # 가지조문(`제5조의2`)까지 한 조로 본다. `제5조의무` 는 `의` 뒤에 숫자가 없어
    # 그룹이 안 붙고 `_NOT_CITED` 가 막는다.
    (_LEVEL_ARTICLE, re.compile(rf"^제\s*\d+\s*조(?:\s*의\s*\d+)?{_NOT_CITED}")),
    (6, re.compile(r"^[①-⑳]")),          # 항 ①~⑳
    # 호는 한두 자리로 제한한다 — `2026. 8. 13.` 같은 날짜 문단이 1호로 잡히지 않게.
    (7, re.compile(r"^\d{1,2}\.(?=\s)")),
    (8, re.compile(rf"^[{_MOK_LETTERS}]\.(?=\s)")),
)

_ARTICLE_RE = next(pattern for level, pattern in _STATUTE_RULES if level == _LEVEL_ARTICLE)

# auto 판정 문턱. 1개면 본문에 조문을 한 번 인용한 일반 문서일 수 있다 — 2개부터
# 조문 문서로 본다. **못 미치면 위계를 아예 끄고** 기존 동작 그대로 간다: 일반 문서에
# 사다리를 걸면 `1.` 목록이 전부 제목으로 승격돼 청킹이 지금보다 나빠진다.
_AUTO_ARTICLE_MIN = 2

# ---------------------------------------------------------------------------
# 공문서 사다리 (`outline_mode="document"`) — 법령 표와 **레벨이 정면으로 어긋나므로**
# 별도 표다. 법령의 `1.` 은 호(조 아래 3단계)이고 공문서의 `1.` 은 최상위다.
# 한 표에 합치면 두 문서 종류 중 하나가 반드시 틀린다.
_ROMAN_UPPER = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"

_DOCUMENT_RULES = (
    (1, re.compile(rf"^[{_ROMAN_UPPER}][.．](?=\s|$)")),
    (1, re.compile(rf"^제\s*\d+\s*장{_NOT_CITED}")),
    # 뒤가 공백일 것을 요구하면 `1.지원대상` 을 놓치고, 아무것도 요구하지 않으면
    # `1.5배` 가 걸린다. **뒤가 숫자가 아닐 것**으로 가른다.
    (2, re.compile(r"^\d{1,2}[.．](?=\s|[가-힣A-Za-z])")),
    (3, re.compile(rf"^[{_MOK_LETTERS}][.．](?=\s|[가-힣A-Za-z])")),
    (4, re.compile(r"^\d{1,2}[)）](?=\s|[가-힣A-Za-z])")),
    (5, re.compile(rf"^[{_MOK_LETTERS}][)）](?=\s|[가-힣A-Za-z])")),
    (6, re.compile(r"^[(（]\d{1,2}[)）](?=\s|[가-힣A-Za-z])")),
    (7, re.compile(r"^[①-⑳]")),
)

# **오탐의 대가가 법령 쪽과 다르다.** 법령에서 `1.` 은 레벨 7 이라 청크 경계도 제목
# 줄기도 건드리지 않아 틀려도 표기만 어긋났다. 공문서에서 `1.` 은 최상위라 오탐 하나가
# 곧 **잘못된 청크 경계 + 본문을 되풀이하는 머리말**이다. 그래서 표기가 맞아도 아래
# 넷을 통과할 때만 제목으로 올린다.
_DOC_HEADING_MAX_CHARS = 40          # 제목은 짧다. 넘으면 번호 붙은 본문 문단이다.
_DOC_SENTENCE_END = ("다.", "요.", "다)", "요)", "임.", "함.")
_DOC_MIN_HITS = 2                    # 한 번만 나오는 표기는 본문 인용일 수 있다
_DOC_FIRST_ORDINAL = 1               # 3번부터 시작하는 표기는 목록이 아니다

# 청크 경계·제목 줄기 깊이. 법령의 5(조)는 **조문 사다리 전용 값**이라 여기 쓸 수 없다.
# `annotate_outline` 이 문서형 레벨을 관측 순서대로 1..N 으로 다시 매기므로(문서마다
# 최상위가 `Ⅰ.` 인지 `1.` 인지 다르다) 이 두 값은 고정 숫자로 둘 수 있다.
_DOC_BREAK_LEVEL = 2
_DOC_PATH_MAX = 3

# 위계 이름표가 이보다 길면 표기 + 괄호 제목까지만 남긴다. 조문 제목은 본문과 한 문단에
# 붙어 오는 일이 흔하다 (`제5조(목적) 이 규칙은 …`).
_LABEL_MAX_CHARS = 40

# 청크 머리말 구분자. 쉼표로 이으면 본문 문장과 구분이 안 된다.
_OUTLINE_SEPARATOR = " > "


class HwpxParseError(ValueError):
    """hwpx 해석/처리 실패 — ZIP·XML 손상, 미지원 확장자, 빈 문서 포함.

    계약: 메시지는 이 파일 안에서 작성한 고정 한국어 안내문만 담는다(문서 원문을
    담지 않는다). `docs/GENOS_RULES.md` §A.4 — 전처리기는 오류 dict 를 반환하지 않고
    이 예외를 던진다.
    """


# ---------------------------------------------------------------------------
# 파싱 — hwpx → 구조 블록. **표 규칙의 정본**
#
# 마크다운 한 덩어리로 뭉치지 않는 이유는 청킹이 블록 경계를 알아야 하기 때문이다 —
# 표 한가운데를 자르면 머리행을 잃어 그 청크가 통째로 쓸모없어진다.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """문서를 이루는 한 덩어리. **청킹이 이 경계를 지킨다.**

    Attributes:
        kind: `"paragraph"` 또는 `"table"`.
        text: 렌더된 내용. 표는 **한 줄짜리 HTML 표**다 (`_render_table` 이 이유를 적는다).
        section: 몇 번째 `Contents/sectionN.xml` 에서 왔나 (0-based).
        outline_level: 위계 (법령: 1 편 … 5 조 … 8 목). **0 이면 제목이 아니라 본문**이다.
            `outline_mode="document"` 에서는 **문서에 실제로 쓰인 표기를 1..N 으로 다시
            매긴 값**이다 — 최상위가 `Ⅰ.` 인 문서와 `1.` 인 문서가 같은 레벨을 갖는다.
        outline_path: 이 블록을 감싸는 제목 줄기 (`("제2장 총칙", "제5조(목적)")`).
            제목 블록이면 자기 이름표가 마지막 원소다. 표 블록도 줄기를 물려받는다 —
            표만 검색돼 나왔을 때 어느 조의 표인지 알아야 한다.

    `parse()` 는 이 둘을 채우지 않는다(XML 에 없는 정보다). `annotate_outline()` 이
    채운다 — 파싱과 위계 판정을 갈라 둬야 위계를 꺼도 파싱 결과가 같다.
    """

    kind: str
    text: str
    section: int
    outline_level: int = 0
    outline_path: tuple = ()

    @property
    def is_table(self) -> bool:
        return self.kind == "table"


@dataclass(frozen=True)
class HwpxDocument:
    """파싱 결과.

    문단·표 개수를 함께 내는 이유는 호출부가 **파싱 품질을 로그에 남기기** 위해서다 —
    0개면 파서가 문서를 못 읽은 것이고, 그 상태로 빈 결과가 정상처럼 흘러가면 안 된다.
    """

    blocks: list = field(default_factory=list)
    section_count: int = 0

    @property
    def paragraph_count(self) -> int:
        return sum(1 for block in self.blocks if block.kind == "paragraph")

    @property
    def table_count(self) -> int:
        return sum(1 for block in self.blocks if block.is_table)

    def to_markdown(self, max_chars: int = 0) -> str:
        """블록 사이 빈 줄로 이은 문자열 (디버깅/미리보기용).

        `max_chars` 가 0 보다 크면 그 길이에서 자른다. **잘렸다는 사실은 여기서 알려주지
        않는다** — 호출부가 길이를 비교해 판단한다.
        """
        markdown = "\n\n".join(block.text for block in self.blocks)
        if max_chars > 0 and len(markdown) > max_chars:
            markdown = markdown[:max_chars].rstrip()
        return markdown


def _open(hwpx_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(hwpx_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise HwpxParseError("hwpx 파일이 아니거나 손상된 파일입니다.") from exc


def _section_order(entry_name: str):
    """본문 섹션이면 섹션 번호, 아니면 None.

    문자열 정렬을 쓰지 않는 이유: `section10` 이 `section2` 앞에 온다. 문단 순서가
    밀리면 청크 순서와 원본 대조가 어긋난다.
    """
    match = _SECTION_ENTRY_RE.match(entry_name)
    return int(match.group(1)) if match else None


def _iter_section_xml(hwpx_bytes: bytes):
    with _open(hwpx_bytes) as archive:
        names = [n for n in archive.namelist() if _section_order(n) is not None]
        for name in sorted(names, key=_section_order):
            yield name, archive.read(name)


def _read_entry(hwpx_bytes: bytes, name: str) -> bytes:
    """ZIP 안의 항목 하나. **없으면 빈 바이트** — 있어야만 좋아지는 것에 쓴다."""
    with _open(hwpx_bytes) as archive:
        try:
            return archive.read(name)
        except KeyError:
            return b""


def _parse_xml(xml_bytes: bytes):
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise HwpxParseError("hwpx 본문 XML 을 해석하지 못했습니다.") from exc


def _nearest_para(node):
    """이 노드를 직접 담고 있는 문단. 표 안(hp:tc→hp:subList→hp:p)까지 따라간다."""
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _PARA:
            return parent
        parent = parent.getparent()
    return None


def _inline_text(node) -> str:
    """`hp:t` 한 개가 가진 글자 전부 — **자식 원소의 `tail` 까지.**

    `hp:t` 는 혼합 내용이다. 탭·강제 줄바꿈·묶음 빈칸 같은 조판 문자가 자식 원소로
    들어가고, **그 뒤에 오는 글자는 자식의 `tail`** 에 담긴다. `node.text` 만 읽던 예전
    코드는 조판 문자가 한 번이라도 나오면 **그 뒤 글자를 전부 잃었다** — 남은 앞부분이
    멀쩡한 문장처럼 보여서 무엇이 사라졌는지 드러나지 않는 종류의 손실이다.

    조판 문자 자체도 글자로 되살린다(탭·줄바꿈은 뒤에서 공백으로 정규화된다) — 없애면
    `1.지원대상` 처럼 이름표와 내용이 붙는다.
    """
    pieces = [_INLINE_CHARS.get(node.tag, ""), node.text or ""]
    for child in node:
        pieces.append(_inline_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)


def _own_text(para) -> str:
    """이 문단이 **직접** 가진 텍스트.

    hwpx 표는 hp:p → hp:run → hp:tbl → … → hp:p 로 중첩된다. `para.iter()` 를 그대로
    쓰면 표 전체가 한 문단으로 붙어 표가 통째로 깨진다.

    글자의 출처는 `hp:t` **와 `hp:equation`** 둘이다 — 수식은 `hp:script` 에 원본
    문자열로 들어 있어 `hp:t` 만 보면 수식 하나가 통째로 빠진다.
    """
    parts = []
    for node in para.iter():
        # 태그를 먼저 거른다 — 조상 추적(`_nearest_para`)을 모든 노드에 걸면 큰 표
        # 하나가 문단 하나의 글자를 뽑는 데 문서 전체를 훑는 비용이 된다.
        if node.tag == _TEXT:
            if _nearest_para(node) is para:
                parts.append(_inline_text(node))
        elif node.tag == _EQUATION and _nearest_para(node) is para:
            parts.extend(script.text or "" for script in node.iter(_SCRIPT))
    text = "".join(parts).replace("\r\n", "\n")
    text = text.replace("\n", _NEWLINE_REPLACEMENT)
    text = text.replace("\t", _NEWLINE_REPLACEMENT)
    return text.strip()


def _children(elem, tag: str) -> list:
    """직접 자식만 (중첩 표의 tr/tc 가 섞이지 않게)."""
    return [child for child in elem if child.tag == tag]


def _int_attr(elem, name: str, default: int) -> int:
    if elem is None:
        return default
    try:
        return int((elem.get(name) or "").strip())
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 자동 번호·글머리표 — **문서에 보이는데 본문 XML 에는 없는 글자**
#
# 한/글의 개요 번호(`1.`, `가.`, `1)`)와 글머리표(`-`, `●`)는 문단 텍스트가 아니라
# **문단 모양(`hh:paraPr > hh:heading`)이 가리키는 번호 매기기 정의**에서 나온다.
# 그래서 `hp:t` 만 읽으면 그 표시가 통째로 사라진다 — 화면에서
#
#     - 사용자가 문서를 업로드한다
#     - 시스템이 문서보안을 해제한다
#
# 이던 것이 적재된 뒤에는 앞의 `-` 가 없는 두 문장이 되고, **목록이라는 사실과 항목의
# 층위가 함께 없어진다.** 조문 위계 판정(`_match_statute`)도 그 표시를 보고 하는 일이라
# 번호가 없으면 항·호가 본문 문단으로 떨어진다.
#
# **왜 지어내는 것이 아닌가.** 번호는 문서가 자기 안에 정의(`Contents/header.xml`)와
# 참조(`hp:p/@paraPrIDRef`)를 둘 다 갖고 있어 **결정적으로 복원된다.** 한/글이 화면에
# 그리는 계산을 그대로 다시 하는 것이지 추측이 아니다. 다만 복원할 수 없는 형식
# (정의에 표시 문자열이 없는 단계 등)은 **비워 둔다** — 틀린 번호를 붙이는 것보다 낫다.
#
# **`@idRef` 는 id 로도 인덱스로도 온다** (2026-08-20). 실물 한/글은 개요 번호 문단에
# `<hh:heading type="OUTLINE" idRef="0">` 을 쓰는데 `<hh:numbering id=…>` 은 **1 부터**
# 시작한다 — id 로만 찾으면 `get("0")` 이 `None` 이라 **개요 번호가 붙은 모든 문단에서
# 번호만 사라진다.** 저장소 실물 4벌이 전부 그 모양이었다(`idRef="0"` × 7단계).
# 텍스트는 `_own_text` 가 따로 뽑으므로 문장은 멀쩡히 남고 번호만 없어져, 표가 깨지는
# 것과 달리 **없어진 자리에 흔적이 남지 않는다.**
#
# 그래서 **id 로 먼저 찾고, 없으면 문서 순서 0-based 인덱스로 본다.** 순서가 이렇게 된
# 이유는 `type="NUMBER"`(문단 번호)가 id 를 그대로 참조하는 경우를 앞의 매치가 지키기
# 때문이다. 한/글이 `idRef` 를 언제나 0-based 로 쓴다면 인덱스만으로도 되지만, 그것을
# 확정할 실물(번호 정의가 2개 이상이면서 둘 다 참조되는 문서)이 아직 없다.
#
# **어긋남의 대가는 크지 않다.** 자동 번호가 만드는 표기는 `_STATUTE_RULES` 에서 항·호·
# 목(레벨 6·7·8)에만 걸리고, 그 레벨은 `outline_break_level`(기본 5)에서 청크를 끊지도
# `_LEVEL_PATH_MAX`(5) 로 제목 줄기에 들지도 않는다. 청킹까지 흔드는 레벨 1~5(`제5조`)는
# 본문 글자에서 나온다. 그래서 **번호가 없는 것이 어긋난 번호보다 나쁘다** — 적재 경로는
# 아무도 눈으로 보지 않으므로, 유실은 그 문장을 물어봤을 때까지 드러나지 않는다.
HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"

_HEADING = f"{{{HH_NS}}}heading"
_PARA_PR = f"{{{HH_NS}}}paraPr"
_NUMBERING = f"{{{HH_NS}}}numbering"
_PARA_HEAD = f"{{{HH_NS}}}paraHead"
_BULLET = f"{{{HH_NS}}}bullet"

# 번호 매기기를 쓰는 문단 모양 종류. `NONE` 은 번호가 없는 보통 문단이다.
_HEADING_NUMBERED = ("OUTLINE", "NUMBER")
_HEADING_BULLET = "BULLET"

# 한/글이 "없음" 을 뜻하는 32비트 sentinel. 실물 header.xml 이 `charPrIDRef` 에 쓰는
# 그 값이다. 인덱스 폴백이 이것을 번호로 읽으면 **그리지 않는 자리에 번호가 생긴다.**
_ID_NONE = "4294967295"

# 정의를 못 찾은 글머리표에 쓸 글자. **글머리표는 정의를 못 찾아도 화면에는 그려진다** —
# 이미지 글머리표(`@char` 없음)가 그렇다. 비워 두면 목록이라는 사실이 통째로 사라지고,
# `-` 는 `_STATUTE_RULES` 의 어느 규칙에도 걸리지 않아 위계를 흔들지 않는다.
_BULLET_FALLBACK = "-"

# 번호 정의 자체를 못 찾았을 때 쓸 표시 서식. `^N` 은 `_expand_head` 가 채운다.
# **표시 문자열이 빈 단계와 다른 경우다** — 그쪽은 한/글도 아무것도 그리지 않으므로
# 비워 두는 것이 원문에 맞고, 이쪽은 무언가 그려지는데 무엇인지 모르는 것이다.
_NUMBER_FALLBACK_TEMPLATE = "^{depth}."

# 표시 문자열 안의 `^N` = N 단계의 번호. `(^5)` → `(3)`.
_HEAD_TOKEN_RE = re.compile(r"\^(\d+)")

# 번호 서식. hwpx 가 쓰는 이름 그대로 둔다 — 옮겨 적으면 원문 대조가 안 된다.
_HANGUL_SYLLABLES = "가나다라마바사아자차카타파하"
_HANGUL_JAMO = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
_ROMAN_UNITS = (
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
    (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
)


def _cycle(alphabet: str, number: int) -> str:
    """`가`…`하` 다음은 `가가` — 한/글이 도는 방식 그대로."""
    if number < 1:
        return ""
    index, repeat = (number - 1) % len(alphabet), (number - 1) // len(alphabet) + 1
    return alphabet[index] * repeat


def _roman(number: int) -> str:
    if number < 1:
        return ""
    out = []
    for value, letters in _ROMAN_UNITS:
        while number >= value:
            out.append(letters)
            number -= value
    return "".join(out)


def _format_number(number: int, num_format: str) -> str:
    """번호 하나를 서식에 맞춰 글자로. 모르는 서식은 숫자로 떨어진다."""
    if num_format == "HANGUL_SYLLABLE":
        return _cycle(_HANGUL_SYLLABLES, number)
    if num_format == "HANGUL_JAMO":
        return _cycle(_HANGUL_JAMO, number)
    if num_format == "CIRCLED_DIGIT":
        return chr(0x2460 + number - 1) if 1 <= number <= 20 else str(number)
    if num_format == "CIRCLED_HANGUL_SYLLABLE":
        return chr(0x326E + number - 1) if 1 <= number <= 14 else _cycle(_HANGUL_SYLLABLES, number)
    if num_format == "CIRCLED_HANGUL_JAMO":
        return chr(0x3260 + number - 1) if 1 <= number <= 14 else _cycle(_HANGUL_JAMO, number)
    if num_format == "LATIN_CAPITAL":
        return _cycle("ABCDEFGHIJKLMNOPQRSTUVWXYZ", number)
    if num_format == "LATIN_SMALL":
        return _cycle("abcdefghijklmnopqrstuvwxyz", number)
    if num_format == "ROMAN_CAPITAL":
        return _roman(number).upper()
    if num_format == "ROMAN_SMALL":
        return _roman(number)
    return str(number)


class _Markers:
    """자동 번호·글머리표 복원기. `Contents/header.xml` 을 한 번 읽어 상태를 든다.

    `advance()` 는 **문단마다 정확히 한 번** 불러야 한다 — 번호는 누적 상태라 건너뛰면
    그 뒤 번호가 전부 밀린다. 그래서 글자가 없는 문단에서도 부르고(한/글도 빈 문단에
    번호를 매긴다), 붙이는 것만 글자가 있을 때 한다.
    """

    def __init__(self, header_xml: bytes = b"") -> None:
        self._para_pr: dict = {}
        self._numbering: dict = {}
        self._bullets: dict = {}
        self._counters: dict = {}
        # 폴백을 밟았다는 사실은 **문서마다 한 번만** 남긴다 — 문단마다 남기면 정상
        # 문서 하나가 로그를 수천 줄 채우고, 정작 봐야 할 줄이 그 사이에 묻힌다.
        self._reported: set = set()
        if header_xml:
            try:
                self._load(_parse_xml(header_xml))
            except HwpxParseError:
                # 머리 정의를 못 읽는 것으로 본문 적재를 막지 않는다 — 번호만 빠진다.
                _log_warning(
                    "hwpx header.xml unreadable; numbering markers are skipped",
                    event="hwpx_header_unreadable",
                )

    def _load(self, root) -> None:
        for para_pr in root.iter(_PARA_PR):
            heading = para_pr.find(_HEADING)
            if para_pr.get("id") is None or heading is None:
                continue
            self._para_pr[para_pr.get("id")] = (
                heading.get("type") or "NONE",
                heading.get("idRef") or "",
                _int_attr(heading, "level", 0),
            )
        for numbering in root.iter(_NUMBERING):
            levels = {}
            for head in numbering.iter(_PARA_HEAD):
                levels[_int_attr(head, "level", 0)] = (
                    head.text or "",
                    head.get("numFormat") or "DIGIT",
                    _int_attr(head, "start", 1),
                )
            self._numbering[numbering.get("id")] = levels
        for bullet in root.iter(_BULLET):
            self._bullets[bullet.get("id")] = bullet.get("char") or ""

    def _report_once(self, event: str, ref: str) -> None:
        if (event, ref) in self._reported:
            return
        self._reported.add((event, ref))
        _log_warning(
            "hwpx marker definition resolved by fallback", event=event, id_ref=ref
        )

    def _resolve(self, table: dict, ref: str, event: str):
        """`@idRef` → 정의. **id 로 먼저, 없으면 문서 순서 0-based 인덱스로.**

        Returns:
            `(키, 정의)`. 어느 쪽으로도 못 찾으면 `(ref, None)`.

        근거는 이 절 머리말에 적었다 — 실물 한/글은 `idRef="0"` 을 쓰는데 `@id` 는 1 부터
        시작한다. **키를 함께 돌려주는 이유**는 누적 카운터를 그 키로 들기 때문이다:
        원본 ref 로 들면 `idRef="0"` 과 `idRef="1"` 이 같은 정의를 가리키는데도 번호가
        따로 세어져 한 목록이 `1. 1. 2. 2.` 로 나온다.
        """
        if ref in table:
            return ref, table[ref]
        # sentinel 은 "정의 없음" 이다. 인덱스로 읽으면 안 그리는 자리에 표시가 생긴다.
        if ref == _ID_NONE or not ref.isdigit():
            return ref, None
        order = list(table)
        index = int(ref)
        if index < len(order):
            self._report_once(event, ref)
            return order[index], table[order[index]]
        return ref, None

    def advance(self, para) -> str:
        """이 문단 앞에 놓일 표시. 없으면 빈 문자열. **상태를 진행시킨다.**"""
        kind, ref, level = self._para_pr.get(para.get("paraPrIDRef"), ("NONE", "", 0))
        if ref == _ID_NONE:
            return ""
        if kind == _HEADING_BULLET:
            _key, char = self._resolve(self._bullets, ref, "hwpx_bullet_ref_by_index")
            # 글머리표는 정의를 못 찾아도 화면에는 그려진다 — 글자만 모른다.
            return f"{char or _BULLET_FALLBACK} "
        if kind not in _HEADING_NUMBERED:
            return ""
        num_id, levels = self._resolve(self._numbering, ref, "hwpx_numbering_ref_by_index")
        depth, defined = _head_depth(level, levels)
        counters = self._counters.setdefault(num_id, {})
        _text, _fmt, start = defined.get(depth, ("", "DIGIT", 1))
        counters[depth] = counters.get(depth, start - 1) + 1
        # 더 깊은 단계는 되돌린다 — 새 상위 항목이 열리면 하위 번호는 1부터다.
        for deeper in [key for key in counters if key > depth]:
            del counters[deeper]

        if depth in defined:
            # 정의된 단계다. **표시 문자열이 비었으면 비워 두는 것이 원문에 맞다** —
            # 한/글도 그 단계에는 아무것도 그리지 않는다. `strip()` 은 헤더가
            # 줄바꿈·들여쓰기와 함께 저장된 문서 때문이다(그대로 쓰면 번호 앞에 개행이
            # 붙어 문단이 두 줄로 보인다).
            template = defined[depth][0].strip()
        else:
            # **번호는 그려지는데**(heading 이 OUTLINE/NUMBER 다) 그 단계 서식을 모른다.
            # 여기서 빈 문자열을 돌려주던 것이 "번호가 통째로 사라지는데 로그에도 남지
            # 않는" 상태였다 — 정의를 찾았고 폴백도 밟지 않으므로 아무 흔적이 없다.
            # 숫자로 낸다: 층위가 사라지는 것보다 표기가 어긋나는 편이 낫다.
            self._report_once(
                "hwpx_numbering_definition_missing" if levels is None
                else "hwpx_numbering_level_missing",
                ref,
            )
            template = _NUMBER_FALLBACK_TEMPLATE.format(depth=depth)
        if not template:
            return ""
        return f"{_HEAD_TOKEN_RE.sub(lambda m: _expand_head(m, defined, counters), template)} "


def _head_depth(level: int, levels) -> tuple:
    """`hh:heading/@level` → 번호 정의(`hh:paraHead`)의 단계 키. → `(키, 정의 표)`.

    `@level` 은 0-based, `hh:paraHead/@level` 은 1-based 라 보통 `level + 1` 이다.
    그 키가 정의에 없으면 **정의된 단계를 순서대로 늘어놓고 `@level` 을 인덱스로** 본다
    (`@idRef` 를 id → 인덱스 순으로 보는 것과 같은 방식이다).

    폴백이 필요한 이유: 그 키가 없을 때 예전 코드는 표시 문자열을 못 찾아 빈 문자열을
    돌려줬고, 그러면 **개요 번호가 붙은 문단 전부에서 번호만 조용히 사라진다** — 정의는
    찾았고 `_resolve` 폴백도 밟지 않으므로 로그에도 흔적이 남지 않는다.

    **축을 뒤집어 보지는 않는다.** 표시 문자열의 `^N` 토큰이 정의의 레벨 키를 그대로
    참조하므로(`_expand_head`), 0-based 정의를 가정해 키를 옮기면 `^N` 해석과 어긋나
    번호가 나오는데 다른 단계의 서식·카운터를 쓴다. 그 모양의 실물을 아직 못 봤다.
    """
    defined = levels or {}
    if not defined:
        return level + 1, {}
    if level + 1 in defined:
        return level + 1, defined
    keys = sorted(defined)
    if 0 <= level < len(keys):
        return keys[level], defined
    return level + 1, defined


def _expand_head(match, levels: dict, counters: dict) -> str:
    depth = int(match.group(1))
    _text, num_format, start = levels.get(depth, ("", "DIGIT", 1))
    return _format_number(counters.get(depth, start), num_format)


def _marker_of(markers, para) -> str:
    """`markers` 가 없으면(표만 따로 렌더링할 때) 표시도 없다."""
    return markers.advance(para) if markers is not None else ""


def _is_box(elem) -> bool:
    """문단을 담는 상자인가 — `hp:subList` 를 직접 자식으로 두는가로 본다.

    표 셀(`hp:tc`)·글상자(`hp:drawText`)·캡션·각주·머리말이 전부 이 모양이다.
    **이름 목록이 아니라 모양으로 보는 이유**는 `_BOX_LABELS` 주석에 적었다.
    """
    return elem.find(_SUBLIST) is not None


def _owning_box(node):
    """이 노드를 담고 있는 **가장 가까운 상자**(표 셀 포함). 중첩을 가르는 기준이다.

    예전에는 셀(`hp:tc`)만 봤다. 그러면 셀 안 글상자·캡션·각주의 문단이 "이 셀 것이
    아니다" 로 떨어져 **어디에서도 안 나온다** — 셀 렌더링은 자기 것이 아니라고 건너뛰고,
    본문 렌더링은 중첩 문단이라고 건너뛴다.
    """
    parent = node.getparent()
    while parent is not None:
        if _is_box(parent):
            return parent
        parent = parent.getparent()
    return None


def _owning_object(node):
    """이 노드를 담고 있는 가장 가까운 **개체**(표·상자·셀). 없으면 `None`.

    `_owned_objects` 가 "한 겹만" 고를 때 쓴다 — 표에 달린 캡션은 표가 낼 몫이지
    문단이 따로 낼 몫이 아니다(따로 내면 캡션이 표에서 떨어져 나온다).
    """
    parent = node.getparent()
    while parent is not None:
        if parent.tag == _TBL or _is_box(parent):
            return parent
        parent = parent.getparent()
    return None


def _paras_of(box) -> list:
    """이 상자가 **직접** 가진 문단들. 안쪽 표·상자의 문단은 뺀다."""
    return [para for para in box.iter(_PARA) if _owning_box(para) is box]


def _owned_objects(para) -> list:
    """이 문단에 매달린 개체들 — 표와 상자. **문서 순서대로, 한 겹만.**

    안쪽 것을 함께 고르면 같은 글자가 두 번 나온다(표 → 그 표의 캡션, 도형 → 그 안의
    글상자). "한 겹" 의 기준은 **이 문단과 같은 상자에 들어 있는가** 다 — 문단이 본문에
    있으면 개체도 본문에 있어야 하고, 문단이 글상자 안이면 개체도 그 글상자 것이라야
    한다. `None` 고정으로 두면 글상자 안 표가 통째로 빠진다(실제로 밟았다).
    """
    box = _owning_box(para)
    return [
        node
        for node in para.iter()
        if (node.tag == _TBL or _is_box(node))
        and _nearest_para(node) is para
        and _owning_object(node) is box
    ]


def _captions_of(obj) -> list:
    """이 개체에 **직접** 달린 캡션(표제)."""
    return [node for node in obj.iter(_CAPTION) if _owning_object(node) is obj]


def _box_parts(box, markers=None, inherited: str = "") -> list:
    """상자 안 내용을 `("text", str)`/`("table", elem)` 으로 **문서 순서대로**.

    셀 안에 들어 있는 상자를 셀 글자로 펴는 자리다. 상자 안 표는 표로 남긴다 —
    글자로 펴면 그 수치가 무엇의 값인지 사라진다(이 전처리기를 만든 이유 그대로다).
    """
    label = _BOX_LABELS.get(box.tag, "") or inherited
    parts = []
    for para in _paras_of(box):
        text = _own_text(para)
        if text:
            parts.append(("text", f"{label}{_marker_of(markers, para)}{text}"))
        for obj in _owned_objects(para):
            if obj.tag == _TBL:
                for caption in _captions_of(obj):
                    parts.extend(_box_parts(caption, markers, label))
                parts.append(("table", obj))
            else:
                parts.extend(_box_parts(obj, markers, label))
    return parts


def _cell_parts(tc, markers=None) -> list:
    """셀 내용을 `("text", str)` 과 `("table", elem)` 으로 **문서 순서대로** 나눈다.

    `tc.iter(hp:p)` 를 그대로 쓰면 **중첩 표 안의 문단까지 딸려온다.** 소유 개체를 따져
    자기 것만 고른다. 셀 안 글상자·캡션·각주는 그 상자를 펴서 셀 글자에 잇는다.

    **`_owning_box` 가 아니라 `_owning_object` 로 보는 이유**: 표(`hp:tbl`)는 상자가
    아니라서, 중첩 표의 셀에서 위로 올라가면 표를 지나쳐 **바깥 셀이 소유자로 잡힌다.**
    그러면 그 셀이 중첩 표를 `("table", …)` 로 한 번 내고, 이어서 그 표의 셀들을
    상자로 또 펴서 **같은 글자가 두 번 실린다**(`구분 | 세부<table>…</table>소분류<br>값`).
    표가 깨지는 것이 아니라 값이 중복되는 것이라 눈으로는 정상처럼 보인다.
    """
    parts = []
    for node in tc.iter():
        # 관심 있는 태그인지 **먼저** 본다. 소유 개체 추적을 모든 노드에 걸면 셀 하나에
        # 문서 깊이만큼의 조상 추적이 노드 수만큼 붙는다.
        if node.tag != _PARA and node.tag != _TBL and not _is_box(node):
            continue
        if _owning_object(node) is not tc:
            continue
        if node.tag == _PARA:
            text = _own_text(node)
            if text:
                parts.append(("text", f"{_marker_of(markers, node)}{text}"))
        elif node.tag == _TBL:
            for caption in _captions_of(node):
                parts.extend(_box_parts(caption, markers))
            parts.append(("table", node))
        else:
            parts.extend(_box_parts(node, markers))
    return parts


def _cell_html(tc, markers=None) -> str:
    """HTML 표용 셀 내용. 중첩 표는 `<table>` 로 그대로 살린다."""
    pieces = []
    previous_was_text = False
    for kind, value in _cell_parts(tc, markers):
        if kind == "text":
            if previous_was_text:
                pieces.append(_CELL_LINE_BREAK)
            pieces.append(_html.escape(value, quote=False))
            previous_was_text = True
        else:
            pieces.append("".join(_table_html(value, markers)))
            previous_was_text = False
    return "".join(pieces)


def _table_grid(tbl) -> tuple:
    """hp:tbl → `(anchors, covered, height, width)`.

    `anchors[(row, col)] = (tc, row_span, col_span)` — 셀이 **시작하는** 자리.
    `covered` 는 병합으로 덮인 자리(앵커 제외).
    """
    anchors: dict = {}
    occupied: set = set()
    height = 0
    width = 0

    for row_index, tr in enumerate(_children(tbl, _TR)):
        cursor = 0
        for tc in _children(tr, _TC):
            addr = tc.find(_CELL_ADDR)
            span = tc.find(_CELL_SPAN)
            col_span = _int_attr(span, "colSpan", 1)
            row_span = _int_attr(span, "rowSpan", 1)
            if addr is not None:
                row = _int_attr(addr, "rowAddr", row_index)
                col = _int_attr(addr, "colAddr", cursor)
            else:
                # 좌표가 없는 문서 — 앞 셀 다음 빈 자리를 쓴다
                row, col = row_index, cursor
                while (row, col) in occupied:
                    col += 1
            anchors[(row, col)] = (tc, row_span, col_span)
            for d_row in range(row_span):
                for d_col in range(col_span):
                    occupied.add((row + d_row, col + d_col))
            cursor = col + col_span
            height = max(height, row + row_span)
            width = max(width, col + col_span)

    covered = occupied - set(anchors)
    return anchors, covered, height, width


def _table_html(tbl, markers=None) -> list:
    """hp:tbl → HTML 표 줄 목록. `rowspan`/`colspan`/중첩을 그대로 살린다.

    형태는 지능형 전처리기가 내는 것과 맞춘다(`<table><tbody><tr><th>…`) — 새 형식을
    만드는 것이 아니라 이미 지원되는 형식으로 내는 것이다.

    **첫 행은 `<th>` 다.** 마크다운 표에서 그 일을 하던 구분선(`|---|`)이 없어졌으므로
    (→ `_render_table`) 머리행 표시를 태그가 맡는다. 조각마다 머리행을 반복하는 것이
    이 분할의 요점인데, 표시가 없으면 그 반복이 데이터 행처럼 읽힌다.
    """
    anchors, covered, height, width = _table_grid(tbl)
    if not width or not height:
        return []

    lines = ["<table><tbody>"]
    for row in range(height):
        # hwpx 는 머리행 표시가 없다 — 첫 행을 머리행으로 본다(구조를 지어내지 않는
        # 최소 가정. 마크다운 표에서 구분선을 첫 행 뒤에 넣던 것과 같은 판정이다).
        tag = "th" if row == 0 else "td"
        cells = []
        for col in range(width):
            if (row, col) in covered:
                continue  # 병합으로 덮인 자리 — 칸을 내면 열이 하나 늘어난다
            anchor = anchors.get((row, col))
            if anchor is None:
                cells.append(f"<{tag}></{tag}>")  # 빈 칸도 자리를 지켜야 한다
                continue
            tc, row_span, col_span = anchor
            attrs = ""
            if row_span > 1:
                attrs += f' rowspan="{row_span}"'
            if col_span > 1:
                attrs += f' colspan="{col_span}"'
            cells.append(f"<{tag}{attrs}>{_cell_html(tc, markers)}</{tag}>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</tbody></table>")
    return lines


def _render_table(tbl, markers=None) -> list:
    """hp:tbl → 표 줄 목록. **언제나 HTML 이다.**

    ## 왜 마크다운을 안 쓰나 (2026-08-13 변경)

    예전에는 병합·중첩이 있는 표만 HTML 로 내고 나머지는 마크다운으로 냈다 — 잃을 게
    없는 표까지 바꾸면 토큰만 늘고 사람이 읽기 나쁘다는 이유였다. 실제 검색 결과를 받아
    보고 뒤집었다: **검색 결과가 LLM 에게 갈 때 개행이 공백으로 뭉개진다.**

        | 순번 | … | 수용<br>여부 | |---|---|---| | 3 | 차기 변제금 …

    마크다운 표는 **행 경계가 개행뿐**이라 이 한 줄에서 표가 아니게 된다 — 구분선이 본문
    줄에 붙고 7열이 뒤섞인다. 수치는 남지만 그 수치가 무엇의 값인지 사라지는 것이고,
    그건 애초에 이 전처리기를 만든 이유(요구사항 §5 "표 깨짐")와 같은 실패다.

    HTML 표는 **행·칸 경계가 태그**라 개행이 없어도 구조가 그대로다. 새 형식도 아니다 —
    지능형 전처리기가 이미 한 줄 HTML 표를 내고 있어 검색·프롬프트 경로가 그 형태를
    이미 받는다. 대가는 토큰 증가(이 문서에서 약 10%)이고, 표가 아니게 되는 것보다
    낫다는 판단이다.
    """
    return _table_html(tbl, markers)


def _vertical_key(tbl):
    """같은 문단에 매달린 개체의 **세로 위치**. 비교할 수 없으면 `None`.

    hwpx 의 표·상자는 문단에 매달리고(anchor), **XML 순서가 곧 화면 순서는 아니다.**
    실물에서 드러났다: 제목상자(1칸 표, `treatAsChar="1"`)와 본문 표
    (`treatAsChar="0"`, `vertOffset="5940"`)가 **같은 문단**에 매달려 있는데 XML 에는
    본문 표가 먼저 있어, 문서 제목이 표 **뒤로** 밀렸다. 그러면 표 조각 어디에도
    제목이 없고, 마지막 청크에서 제목·날짜·서명이 한 덩어리가 된다.

    - `hp:pos` 가 없으면 흐름 그대로 → 0
    - `treatAsChar="1"`(글자처럼 취급)은 문단 자리에 그대로 온다 → 0
    - 그 외에는 `vertOffset`. 단 **기준이 문단(`vertRelTo="PARA"`)일 때만** 쓴다 —
      페이지·단 기준 오프셋은 문단 기준 값과 크기를 비교할 수 없다(0 으로 뭉개면
      순서를 지어내는 셈이라 `None` 을 돌려 정렬 자체를 포기한다).
    """
    found = _children(tbl, _POS)
    if not found:
        return 0
    pos = found[0]
    if pos.get("treatAsChar") == "1":
        return 0
    if (pos.get("vertRelTo") or "PARA") != "PARA":
        return None
    return _int_attr(pos, "vertOffset", 0)


def _in_visual_order(tables: list) -> list:
    """한 문단에 매달린 개체들을 화면에 놓이는 순서로. **판정 불가면 문서 순서 그대로.**

    개체가 하나뿐이면(대부분의 문서) 손대지 않는다 — 이 정렬은 한 문단이 둘 이상을
    물고 있을 때만 의미가 있다.
    """
    if len(tables) < 2:
        return tables
    keys = [_vertical_key(tbl) for tbl in tables]
    if any(key is None for key in keys):
        return tables
    # 색인을 두 번째 키로 둬서 **동점이면 문서 순서**를 지킨다(그리고 lxml 프록시끼리
    # 비교되는 일이 없다 — 색인이 유일하므로 튜플 비교가 거기서 끝난다).
    order = sorted(zip(keys, range(len(tables)), tables), key=lambda item: item[:2])
    return [tbl for _key, _index, tbl in order]


def _boxed_text(tbl, markers=None):
    """칸이 하나뿐인 표는 **표가 아니라 제목·강조 상자다** → 그 안의 글을 돌려준다.

    hwpx 는 제목상자·박스형 강조를 1칸 표로 만드는 일이 흔한데, 그대로 표로 내면 본문
    행이 0개인 퇴화된 표가 된다:

        | 『…』 사업 기술협상서 |
        |---|

    글자를 잃지는 않지만(머리행에 남는다) 표가 아닌 것이 표로 검색되고, 구분선이
    노이즈로 임베딩되며, 조문 위계 판정도 지나쳐 간다. 문단으로 내면 셋 다 해소된다.

    Returns:
        문단 텍스트. 칸이 하나가 아니거나 **중첩 표가 들어 있으면 `None`** — 후자는
        문단으로 펴면 안쪽 표를 통째로 잃는다.
    """
    anchors, _covered, _height, _width = _table_grid(tbl)
    if len(anchors) != 1:
        return None

    # 중첩 표가 들어 있으면 문단으로 펼 수 없다 — 안쪽 표를 통째로 잃는다.
    # **`_cell_parts` 결과로 확인하지 않는 이유**(2026-08-23): 그 함수는 자동 번호
    # 카운터를 진행시킨다. 여기서 부르고 나서 표로 되돌아가면 렌더링이 같은 셀을 다시
    # 훑어 **그 셀의 번호가 두 번 세어지고, 그 뒤 문서의 번호가 전부 밀린다.**
    # 번호가 있는데 틀린 상태라 빠진 것보다 알아채기 어렵다.
    if any(node is not tbl for node in tbl.iter(_TBL)):
        return None

    (tc, _row_span, _col_span), = anchors.values()
    parts = _cell_parts(tc, markers)
    # 셀 안 여러 문단은 진짜 줄바꿈으로 잇는다 — `<br>` 은 표 한 칸을 지키려고
    # 쓰는 것이라, 표를 벗어난 이 경로에서는 글자로 보일 뿐이다.
    return "\n".join(value for kind, value in parts if kind == "text").strip()


def parse(hwpx_bytes: bytes) -> HwpxDocument:
    """hwpx 본문을 블록 목록으로 판다.

    Args:
        hwpx_bytes: hwpx 파일 바이트.

    Returns:
        Document — 문단과 표가 **문서 순서대로** 담긴다.

    Raises:
        HwpxParseError: ZIP/XML 손상.
    """
    blocks: list = []
    section_count = 0
    markers = _Markers(_read_entry(hwpx_bytes, _HEADER_ENTRY))

    for section_index, (_name, xml_bytes) in enumerate(_iter_section_xml(hwpx_bytes)):
        section_count += 1
        root = _parse_xml(xml_bytes)

        # lxml 프록시는 참조가 끊기면 회수된다. 순회 결과를 리스트로 붙들어 둔 뒤에 쓴다.
        for para in list(root.iter(_PARA)):
            # 상자(표 셀·글상자·각주·머리말…) 안 문단은 상위 hp:p 안에 중첩된다.
            # 그 상자를 낼 때 함께 내므로 여기서 건너뛴다 — **버리는 것이 아니다.**
            if _nearest_para(para) is not None:
                continue
            _emit_paragraph(para, section_index, blocks, markers)

    return HwpxDocument(blocks=blocks, section_count=section_count)


def _emit_paragraph(para, section_index: int, blocks: list, markers, label: str = "") -> None:
    """문단 하나와 거기 매달린 개체들을 블록으로 낸다. 상자 안에서는 재귀한다.

    `label` 은 본문 흐름 **밖에서** 온 글에만 붙는다(각주·머리말 등). 글상자·캡션은
    본문과 같은 글이라 빈 문자열이다 — 라벨은 원문에 없던 글자를 더하는 것이므로,
    출처를 모르면 뜻이 달라지는 자리에만 쓴다.
    """
    # 번호는 누적 상태다 — 글자가 없는 문단에서도 진행시켜야 뒤 번호가 안 밀린다.
    marker = _marker_of(markers, para)
    text = _own_text(para)
    if text:
        blocks.append(
            Block(kind="paragraph", text=f"{label}{marker}{text}", section=section_index)
        )

    # XML 순서가 아니라 **화면 순서**로 낸다 — 같은 문단에 제목상자와 본문 표가 함께
    # 매달려 있으면 XML 에서는 표가 먼저 나오는 일이 있다(`_in_visual_order`).
    for obj in _in_visual_order(_owned_objects(para)):
        if obj.tag == _TBL:
            _emit_table(obj, section_index, blocks, markers, label)
            continue
        # 자기 라벨이 없는 상자(글상자·캡션)는 **바깥 라벨을 물려받는다** — 각주 안
        # 글상자가 "[각주]" 를 잃으면 그 글이 본문 문장으로 읽힌다.
        for inner in _paras_of(obj):
            _emit_paragraph(
                inner, section_index, blocks, markers, _BOX_LABELS.get(obj.tag, "") or label
            )


def _emit_table(tbl, section_index: int, blocks: list, markers, label: str = "") -> None:
    """표 하나를 블록으로. **캡션이 먼저다.**

    캡션을 표 앞에 두면 `_table_title_of` 가 그것을 표 제목으로 집어 조각마다 앞에
    """
    for caption in _captions_of(tbl):
        for inner in _paras_of(caption):
            _emit_paragraph(
                inner, section_index, blocks, markers, _BOX_LABELS[_CAPTION] or label
            )

    boxed = _boxed_text(tbl, markers)
    if boxed is not None:
        # 빈 상자는 아예 내지 않는다 — 표로 내면 글자 없는 청크가 생긴다.
        if boxed:
            blocks.append(
                Block(kind="paragraph", text=f"{label}{boxed}", section=section_index)
            )
        return

    lines = _render_table(tbl, markers)
    if lines:
        blocks.append(Block(kind="table", text="\n".join(lines), section=section_index))


# ---------------------------------------------------------------------------
# 조문 위계 판정 — 블록 → 블록(+`outline_level`/`outline_path`)
#
# **왜 파싱과 갈라 두나.** hwpx XML 에는 "이 문단이 제5조다" 라는 정보가 없다. 조문
# 위계는 텍스트 표기에서 읽어내는 별개의 층이고, 껐을 때 파싱 결과가 그대로여야
# 위계 규칙을 고쳐도 표·문단 경계는 흔들리지 않는다.
#
# **왜 레이아웃 모델을 쓰지 않나.** 지능형 전처리기는 PDF 로 변환한 뒤 레이아웃(비전)
# 모델이 매긴 `SECTION_HEADER`/`TITLE` 라벨로 구조를 잡는데, 그 라벨은 깊이가 0/1 로
# 평탄화돼 편–장–조–항 4단 위계를 표현하지 못한다. 이 경로는 hwpx 를 직접 읽어 문단
# 텍스트가 그대로 있으므로 표기에서 위계를 바로 읽을 수 있다.
# ---------------------------------------------------------------------------


def _match_statute(text: str) -> tuple:
    """문단 첫머리에서 조문 표기를 찾는다. → `(레벨, 이름표)`. 못 찾으면 `(0, "")`.

    **첫머리에서만** 본다. 본문 가운데의 `… 제5조에 따라 …` 는 인용이지 제목이 아니고,
    문단 전체를 훑으면 그 인용이 새 조를 여는 것처럼 보여 청크가 엉뚱하게 끊긴다.
    """
    stripped = text.strip()
    if not stripped:
        return 0, ""
    for level, pattern in _STATUTE_RULES:
        match = pattern.match(stripped)
        if match:
            return level, _outline_label(stripped, match)
    return 0, ""


def _outline_label(stripped: str, match) -> str:
    """제목 줄기에 실을 짧은 이름표.

    조문 제목은 본문과 한 문단에 붙어 오는 일이 흔하다(`제5조(목적) 이 규칙은 …`).
    그대로 쓰면 청크 머리말이 본문을 통째로 되풀이한다. 그래서 순서가 이렇다:

    1. **괄호 제목이 있으면 길이와 무관하게 거기까지** — `제5조(목적)`. 조문 제목의
       정식 표기라, 짧다는 이유로 본문까지 이름표에 넣으면 조마다 이름표 모양이 달라진다.
    2. 괄호가 없고 문단이 짧으면 그대로 (`제2장 총칙` — 제목 줄 하나가 곧 이름표다).
    3. 둘 다 아니면 표기만 (`제5조`).
    """
    marker = match.group(0).strip()
    rest = stripped[match.end():].lstrip()
    if rest.startswith("("):
        close = rest.find(")")
        if close != -1:
            return f"{marker}{rest[:close + 1]}"
    if len(stripped) <= _LABEL_MAX_CHARS:
        return stripped
    return marker or stripped[:_LABEL_MAX_CHARS].rstrip()


def _doc_candidate(stripped: str) -> bool:
    """공문서 제목 후보인가 — 표기를 보기 **전에** 문단 모양으로 먼저 거른다."""
    if not stripped or len(stripped) > _DOC_HEADING_MAX_CHARS:
        return False
    return not stripped.endswith(_DOC_SENTENCE_END)


def _doc_ordinal(marker: str) -> int:
    """표기에서 순서값 하나. 못 읽으면 0.

    **표기 문자열만 넘길 것.** 문단 전체를 넘기면 `가. 2025년 계획` 에서 `20` 을
    집어 "1번부터 시작하는가" 판정이 뒤집힌다.
    """
    digits = re.search(r"\d{1,2}", marker)
    if digits:
        return int(digits.group())
    for char in marker:
        if char in _MOK_LETTERS:
            return _MOK_LETTERS.index(char) + 1
        if char in _ROMAN_UPPER:
            return _ROMAN_UPPER.index(char) + 1
        if "①" <= char <= "⑳":
            return ord(char) - 0x2460 + 1
    return 0


def _document_levels(blocks: list) -> frozenset:
    """이 문서가 **실제로 쓰는** 공문서 레벨. 사다리를 문서마다 확정한다.

    문단 하나만 봐서는 `_DOC_MIN_HITS`·`_DOC_FIRST_ORDINAL` 을 판정할 수 없어
    `annotate_outline` 이 이 함수로 한 번 먼저 훑는다.
    """
    seen: dict = {}
    for block in blocks:
        if block.kind != "paragraph":
            continue
        stripped = block.text.strip()
        if not _doc_candidate(stripped):
            continue
        for level, pattern in _DOCUMENT_RULES:
            match = pattern.match(stripped)
            if match:
                seen.setdefault(level, []).append(_doc_ordinal(match.group(0)))
                break
    return frozenset(
        level for level, ordinals in seen.items()
        if len(ordinals) >= _DOC_MIN_HITS and ordinals[0] == _DOC_FIRST_ORDINAL
    )


def _match_document(text: str, levels: frozenset) -> tuple:
    """공문서 표기 판정. `levels` 에 없는 레벨은 제목으로 올리지 않는다."""
    stripped = text.strip()
    if not _doc_candidate(stripped):
        return 0, ""
    for level, pattern in _DOCUMENT_RULES:
        match = pattern.match(stripped)
        if match:
            if level not in levels:
                return 0, ""
            return level, _outline_label(stripped, match)
    return 0, ""


def _detect_outline_mode(blocks: list) -> str:
    """`auto` 판정 — 조문 표기를 실제로 세어 본다.

    **일반 문서에 사다리를 걸면 지금보다 나빠진다.** `1.`·`가.` 로 시작하는 평범한
    목록이 전부 제목으로 승격돼 청크가 잘게 부서지기 때문이다. 그래서 조 표기가
    `_AUTO_ARTICLE_MIN` 개 이상일 때만 켠다 — `제N조` 는 목록 기호로 쓰이지 않으므로
    이 판정은 오탐이 사실상 없다.
    """
    hits = 0
    for block in blocks:
        if block.kind != "paragraph":
            continue
        if _ARTICLE_RE.match(block.text.strip()):
            hits += 1
            if hits >= _AUTO_ARTICLE_MIN:
                return _OUTLINE_STATUTE
    return _OUTLINE_OFF


def annotate_outline(blocks: list, mode: str = _OUTLINE_AUTO) -> list:
    """블록에 조문 위계를 매긴다. 원본은 건드리지 않고 새 목록을 돌려준다.

    Args:
        blocks: `parse()` 산출물.
        mode: `"auto"`(기본 — 조문 문서로 보일 때만 켠다) / `"statute"`(무조건 켠다) /
            `"document"`(공문서 사다리 — **`auto` 는 절대 이걸 고르지 않는다**) /
            `"off"`(끈다). 알 수 없는 값은 경고 후 `"auto"` 로 떨어진다 — 등록 화면
            오타가 재적재를 막으면 안 된다.

    Returns:
        `outline_level`/`outline_path` 가 채워진 블록 목록. `mode` 가 꺼지면 입력과
        같은 내용(위계 필드는 기본값)이다.
    """
    if mode not in _OUTLINE_MODES:
        _log_warning(
            "invalid preprocessor parameter, using default",
            event="hwpx_preprocess_param_invalid",
            error_code="05-00020003",
        )
        mode = _OUTLINE_AUTO
    if mode == _OUTLINE_AUTO:
        mode = _detect_outline_mode(blocks)
    if mode == _OUTLINE_OFF:
        return list(blocks)

    # 문서형은 사다리를 문서에서 확정하고, **관측 순서대로 1..N 으로 다시 매긴다.**
    # 최상위가 `Ⅰ.` 인 문서와 `1.` 인 문서의 레벨이 같아야 청크 경계·머리말 깊이를
    # 고정 숫자로 둘 수 있다. 쓸 만한 사다리가 없으면 위계를 안 매긴다(끈 것과 같다).
    doc_rank: dict = {}
    if mode == _OUTLINE_DOCUMENT:
        levels = _document_levels(blocks)
        if not levels:
            return list(blocks)
        doc_rank = {level: rank for rank, level in enumerate(sorted(levels), start=1)}
    path_max = _DOC_PATH_MAX if doc_rank else _LEVEL_PATH_MAX

    trail: dict = {}
    annotated: list = []
    for block in blocks:
        if block.kind != "paragraph":
            level, label = 0, ""
        elif doc_rank:
            level, label = _match_document(block.text, frozenset(doc_rank))
            level = doc_rank.get(level, 0)
        else:
            level, label = _match_statute(block.text)
        if level:
            # 같은 레벨이거나 더 깊은 줄기는 여기서 닫힌다. 안 닫으면 제3조의 항이
            # 제5조 청크의 머리말에 남는다.
            trail = {depth: name for depth, name in trail.items() if depth < level}
            if level <= path_max:
                trail[level] = label
        annotated.append(
            replace(
                block,
                outline_level=level,
                outline_path=tuple(trail[depth] for depth in sorted(trail)),
            )
        )
    return annotated


# ---------------------------------------------------------------------------
# 청킹 — 블록 → 청크. **표를 쪼개지 않는 것**이 이 부분의 존재 이유다.
#
# 문자 수만 보고 자르는 청커에 문서를 통째로 넣으면 표 한가운데가 잘린다. 뒤 조각은
# 머리행이 없어 검색돼도 쓸모가 없다. 그래서:
#   1. 표는 통째로 한 청크. 상한을 넘으면 머리행을 반복하며 행 단위로 나눈다.
#   2. 문단은 이어 붙이되 문단 중간을 자르지 않는다 — 상한을 넘을 때만 문장 경계로,
#      그래도 안 되면 문자로 자른다.
#   3. 겹침(overlap)은 문단 경계에서만. 표 조각에는 주지 않는다(머리행이 이미 반복된다).
# ---------------------------------------------------------------------------

_DEFAULT_MAX_CHARS = 1000
_DEFAULT_OVERLAP_CHARS = 100
_DEFAULT_MIN_CHARS = 40

# 표 바로 앞 문단을 그 표의 제목으로 볼 수 있는 최대 길이. 넘으면 제목이 아니라 본문
# 문단이라고 본다 — 본문을 표 조각마다 반복하면 임베딩이 본문 쪽으로 끌려간다.
_TABLE_TITLE_MAX_CHARS = 60
# 상한을 넘는 행을 쪼갤 때, 이 길이 이하의 셀은 **조각마다 통째로 반복**한다.
# 순번·담당·수용여부처럼 짧은 칸이 여기 해당하고, 그게 있어야 조각이 혼자 해석된다.
_ROW_ANCHOR_MAX_CHARS = 80
# `<tr>` 한 줄에서 칸을 뜯어낼 때. 속성을 **그대로 보존**해야 하므로 따로 잡는다.
_HTML_CELL_RE = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
# 병합 선언. 이게 걸린 행은 조각마다 되풀이하면 없던 격자를 지어낸다.
_SPAN_ATTR_RE = re.compile(r"\b(?:row|col)span\s*=", re.IGNORECASE)
# 행을 쪼갠 조각에서 "이 칸의 내용은 다른 조각에 있다" 는 표시. 빈칸과 구분돼야 한다.
_ELLIPSIS = "…"


@dataclass(frozen=True)
class Chunk:
    """VDB 에 실릴 한 조각.

    Attributes:
        text: 본문.
        section: 원본 섹션 번호.
        kind: `"paragraph"` / `"table"` — 표 조각인지 알아야 검색 결과 표시가 달라진다.
        table_part: 표를 나눴을 때 `(몇 번째, 총 몇 개)`. 안 나눴으면 `None`.
            **몇 번째는 0-based 다** — 레코드의 `i_table_part` 와 같은 값이고, 사람이
            읽는 본문 머리말(`(표 1/16)`)만 `_table_prefix_for` 가 +1 해서 낸다.
        table_title: 표 바로 앞 문단(= 표 제목). 표 청크에만, 없으면 빈 값.
        outline_path: 이 청크가 속한 조문 줄기. 위계를 껐거나 조문 문서가 아니면 빈 값.
    """

    text: str
    section: int
    kind: str
    table_part: tuple | None = None
    table_title: str = ""
    outline_path: tuple = ()


@dataclass
class ChunkOptions:
    """청킹 설정.

    `max_chars` 기본값 1000 은 임베딩 모델 컨텍스트에 맞춰 호출부가 조정한다.
    `length` 는 문자 수 기본값 — 폐쇄망에 토크나이저 파일이 없을 수 있어서다. 토큰
    기준이 필요하면 콜러블을 주입한다.
    """

    max_chars: int = _DEFAULT_MAX_CHARS
    overlap_chars: int = _DEFAULT_OVERLAP_CHARS
    # 이보다 짧은 청크는 앞 청크에 붙인다. 한두 단어짜리 청크는 검색 노이즈만 된다.
    min_chars: int = _DEFAULT_MIN_CHARS
    length: object = len
    # 이 레벨 이하의 제목에서 청크를 끊는다. 기본은 조(5) — 조가 검색 단위다.
    # 0 이면 위계로 끊지 않는다(길이 기준만 쓰는 옛 동작).
    outline_break_level: int = _LEVEL_ARTICLE
    # 청크 본문 앞에 `제2장 총칙 > 제5조(목적)` 머리말을 붙일지. 붙이는 이유는 조각이
    # **혼자서도 해석 가능**해야 하기 때문이다 — 표 조각에 머리행을 반복하는 것과 같은
    # 이유이고, 임베딩되는 문자열 자체에 들어가야 검색에 걸린다.
    outline_prefix: bool = True

    def __post_init__(self) -> None:
        # 문자 분할 예외 경로(`_split_long_text`)는 매 반복마다 `max_chars - overlap_chars`
        # 만큼 전진한다. `overlap_chars >= max_chars` 면 그 값이 0 이하가 되어 같은
        # 조각을 무한히 반복한다 — GenOS 등록 화면에서 파라미터를 잘못 입력해도
        # 재적재가 멈추지 않게 여기서 막는다(`docs/GENOS_RULES.md` §F 의 "파라미터
        # 최소·최대/범위 밖" 테스트 요건).
        if self.max_chars < 1:
            self.max_chars = _DEFAULT_MAX_CHARS
        if self.overlap_chars < 0 or self.overlap_chars >= self.max_chars:
            self.overlap_chars = max(0, self.max_chars // 4)
        if self.min_chars < 0:
            self.min_chars = 0
        if self.outline_break_level < 0:
            self.outline_break_level = _LEVEL_ARTICLE


def _length(options: ChunkOptions, text: str) -> int:
    return options.length(text)


def _cell_segments(cell: str, options: ChunkOptions) -> list:
    """셀 내용을 이어붙일 수 있는 조각으로. → `[(앞에 붙일 이음쇠, 글자)]`.

    1차 경계는 셀 안 줄바꿈(`<br>`)이다. 그 한 줄이 혼자 상한을 넘으면 문장 경계로 한 번
    더 나눈다 — 그때 이음쇠는 **공백**이다. `<br>` 로 다시 이으면 원문에 없던 줄바꿈을
    만들어 내는 셈이고, 그 줄바꿈은 되돌릴 수 없다.
    """
    segments: list = []
    for index, line in enumerate(cell.split(_CELL_LINE_BREAK)):
        separator = _CELL_LINE_BREAK if index else ""
        if _length(options, line) <= options.max_chars:
            segments.append((separator, line))
            continue
        for order, sentence in enumerate(s for s in _SENTENCE_END.split(line) if s):
            segments.append((separator if order == 0 else " ", sentence))
    return segments


def _row_cells(row: str) -> list:
    """`<tr>` 한 줄 → `[(태그, 속성, 내용)]`. 모양이 예상과 다르면 빈 목록.

    되돌려 렌더한 것이 원래 줄과 **글자까지 같을 때만** 쪼갠다. 정규식으로 훑는 것이라
    모르는 모양(속성에 `>` 가 들어간 경우 등)에서 조용히 글자를 잃을 수 있는데, 그 손실은
    검색 결과에 아무 흔적도 남기지 않는다.
    """
    cells = _HTML_CELL_RE.findall(row)
    if len(cells) < 2 or _render_row(cells, [inner for _t, _a, inner in cells], ()) != row:
        return []
    return cells


def _render_row(cells: list, values: list, long_columns) -> str:
    """셀 목록 + 값 목록 → `<tr>` 한 줄.

    `long_columns` 에 든 칸이 비어 있으면 생략 표시를 넣는다 — 이 조각에 안 실렸다는
    뜻이지 값이 없다는 뜻이 아니다. 앵커로 반복되는 **진짜 빈칸**과 구분돼야 한다.
    """
    pieces = []
    for index, ((tag, attrs, _inner), value) in enumerate(zip(cells, values)):
        if not value and index in long_columns:
            value = _ELLIPSIS
        pieces.append(f"<{tag}{attrs}>{value}</{tag}>")
    return "<tr>" + "".join(pieces) + "</tr>"


def _split_wide_row(row: str, prefix: list, suffix: list, options: ChunkOptions) -> list:
    """행 **하나**가 상한을 넘을 때 셀 안에서 나눈다. → `<tr>` 줄 목록.

    행 단위로만 쪼개던 때는 여기서 멈췄고, 그 조각은 상한을 넘긴 채 임베딩으로 갔다
    (실물에서 1,929자). 임베딩 컨텍스트가 그보다 짧으면 **뒤쪽이 조용히 잘린다** —
    레코드에는 글자가 그대로 남아 있어서 검색이 왜 실패했는지 아무 데도 안 드러난다.

    나누는 규칙:
    - 짧은 셀(`_ROW_ANCHOR_MAX_CHARS` 이하)은 **조각마다 통째로 반복**한다. 순번·담당·
      수용여부가 그것이고, 그게 있어야 조각만 봐도 몇 번 항목인지 안다(머리행을 반복하는
      것과 같은 이유다).
    - 긴 셀은 `<br>`(그래도 길면 문장) 경계로 나눠 채운다. **열 수는 그대로**라 조각도
      여전히 올바른 표다.
    - 글자는 하나도 버리지 않고 겹치지도 않는다 — 표 안에서 겹치면 같은 수치가 두 번
      나와 합계가 틀린다.

    **손대지 않는 행 셋**(그대로 돌려준다):
    - 중첩 표가 든 행 — 안쪽 표가 조각 사이에서 갈린다.
    - `rowspan`/`colspan` 이 걸린 행 — 조각마다 되풀이하면 **없던 격자를 지어낸다.**
      병합은 "이 칸이 몇 행·몇 열을 덮는다" 는 선언이라 복제되면 뜻이 달라진다.
    - 쪼갤 데가 없는 행 (칸이 하나뿐이거나 긴 칸이 없는 행).
    """
    if "<table" in row.lower():
        return [row]
    cells = _row_cells(row)
    if not cells or any(_SPAN_ATTR_RE.search(attrs) for _tag, attrs, _inner in cells):
        return [row]

    inners = [inner for _tag, _attrs, inner in cells]
    anchors = [
        inner if _length(options, inner) <= _ROW_ANCHOR_MAX_CHARS else "" for inner in inners
    ]
    long_columns = [index for index, value in enumerate(anchors) if not value]
    if not long_columns:
        return [row]

    def fits(values: list) -> bool:
        candidate = prefix + [_render_row(cells, values, long_columns)] + suffix
        return _length(options, "\n".join(candidate)) <= options.max_chars

    rows: list = []
    current = list(anchors)
    filled = False
    for column in long_columns:
        for separator, segment in _cell_segments(inners[column], options):
            candidate = list(current)
            candidate[column] = (
                f"{candidate[column]}{separator}{segment}" if candidate[column] else segment
            )
            if filled and not fits(candidate):
                rows.append(_render_row(cells, current, long_columns))
                current = list(anchors)
                # 새 조각의 첫 글자다 — 앞의 이음쇠는 버린다(칸이 이음쇠로 시작하면
                # 그 조각만 읽었을 때 앞이 잘린 것처럼 보인다).
                current[column] = segment
            else:
                current = candidate
            filled = True
    rows.append(_render_row(cells, current, long_columns))
    return rows


def _split_html_table(text: str, options: ChunkOptions) -> list:
    """HTML 표를 `<tr>` 단위로 나눈다. 첫 행을 머리행으로 보고 반복한다.

    행 하나가 그것만으로 상한을 넘으면 `_split_wide_row` 가 셀 안에서 한 번 더 나눈다.
    """
    lines = text.splitlines()
    rows = [line for line in lines if line.startswith("<tr>")]
    if len(rows) <= 1:
        return [text]

    header_row = rows[0]
    open_tag, close_tag = "<table><tbody>", "</tbody></table>"

    widened: list = []
    for row in rows[1:]:
        if _length(options, "\n".join([open_tag, header_row, row, close_tag])) > options.max_chars:
            widened.extend(_split_wide_row(row, [open_tag, header_row], [close_tag], options))
        else:
            widened.append(row)

    parts: list = []
    current: list = []
    for row in widened:
        candidate = "\n".join([open_tag, header_row] + current + [row, close_tag])
        if current and _length(options, candidate) > options.max_chars:
            parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
            current = [row]
        else:
            current.append(row)
    if current:
        parts.append("\n".join([open_tag, header_row] + current + [close_tag]))
    return parts or [text]


def _table_prefix_reserve(
    block: Block, options: ChunkOptions, title: str, *, part: bool
) -> int:
    """조각에 붙을 머리말이 차지할 자리. **쪼개기 전에 미리 빼 둔다.**

    조문 머리말은 일부러 길이 계산 **뒤**에 붙인다(조가 깊을수록 본문이 밀려 청크
    크기가 들쭉날쭉해지므로). 표는 사정이 다르다 — 제목이 표 전체에 하나뿐이라 예약이
    균일하고, 예약하지 않으면 **모든 조각이 상한을 조금씩 넘는다.** 상한을 넘기지
    않으려고 행을 쪼갠 직후에 머리말로 다시 넘기면 앞의 노력이 무의미해진다.

    `(표 99/99)` 로 재는 것은 조각 수를 아직 모르기 때문이다 — 실제보다 넉넉하게
    잡을지언정 모자라게 잡지 않는다.
    """
    pieces = []
    if title and not block.outline_path:
        pieces.append(title)
    if part:
        pieces.append("(표 99/99)")
    sample = " ".join(pieces)
    sample = f"{sample}\n" if sample else ""
    if options.outline_prefix and block.outline_path:
        sample = f"{_OUTLINE_SEPARATOR.join(block.outline_path)}\n\n{sample}"
    return _length(options, sample) if sample else 0


def _table_chunks(block: Block, options: ChunkOptions, title: str = "") -> list:
    if _length(options, block.text) + _table_prefix_reserve(
        block, options, title, part=False
    ) <= options.max_chars:
        return [
            Chunk(
                text=block.text,
                section=block.section,
                kind="table",
                table_title=title,
                outline_path=block.outline_path,
            )
        ]

    budget = options.max_chars - _table_prefix_reserve(block, options, title, part=True)
    if budget >= options.max_chars // 2:
        # 머리말이 상한의 절반을 먹을 만큼 길면 예약을 포기한다 — 그 지경이면 본문이
        # 밀려 조각이 표 몇 줄짜리가 되고, 그게 상한을 지키는 것보다 나쁘다.
        options = replace(options, max_chars=budget)

    parts = _split_html_table(block.text, options)

    total = len(parts)
    return [
        Chunk(
            text=part,
            section=block.section,
            kind="table",
            table_part=(index, total),
            table_title=title,
            outline_path=block.outline_path,
        )
        for index, part in enumerate(parts)
    ]


def _table_title_of(block: Block, options: ChunkOptions) -> str:
    """이 문단을 뒤따르는 표의 제목으로 볼 수 있나. 아니면 빈 문자열.

    제목은 **한 줄짜리 짧은 문단**만 인정한다. 본문 문단을 제목으로 삼으면 표 조각마다
    본문이 통째로 반복돼 임베딩이 표가 아니라 그 본문 쪽으로 끌려간다.
    """
    text = block.text.strip()
    if not text or "\n" in text or _length(options, text) > _TABLE_TITLE_MAX_CHARS:
        return ""
    return text


def _split_long_text(text: str, options: ChunkOptions) -> list:
    """한 문단이 상한을 넘을 때만 쓰는 예외 경로. 문장 → 문자 순으로 내려간다."""
    sentences = [s for s in _SENTENCE_END.split(text) if s.strip()]
    pieces: list = []
    current = ""
    for sentence in sentences or [text]:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and _length(options, candidate) > options.max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)

    # 문장으로도 안 잘리는 경우(한 문장이 통째로 길다) — 마지막 수단으로 문자 분할
    out: list = []
    for piece in pieces:
        while _length(options, piece) > options.max_chars:
            out.append(piece[: options.max_chars])
            piece = piece[options.max_chars - options.overlap_chars:]
        if piece:
            out.append(piece)
    return out


def _overlap_tail(text: str, options: ChunkOptions) -> str:
    """다음 청크 앞에 붙일 꼬리. 문장 경계를 넘지 않게 자른다."""
    if options.overlap_chars <= 0:
        return ""
    tail = text[-options.overlap_chars:]
    match = _SENTENCE_END.search(tail)
    return tail[match.end():] if match else tail


def chunk_blocks(blocks: list, options: ChunkOptions | None = None) -> list:
    """블록 목록 → 청크 목록.

    표는 블록 경계를 넘지 않고, 문단은 상한까지 이어 붙인다. 표를 만나면 쌓아 둔 문단을
    **먼저 끊는다** — 문단과 표를 한 청크에 섞으면 표가 문단 꼬리에 붙어 검색 결과가
    읽기 어려워진다. 구역(section)이 바뀔 때도 끊는다 — 청크가 두 구역에 걸치면
    `i_section` 이 둘 중 하나만 가리켜 출처가 틀린다.

    블록에 조문 위계가 매겨져 있으면(`annotate_outline`) **조 이상의 제목에서도 끊는다.**
    한 조가 여러 청크에 흩어지면 "제5조가 무엇을 정하는가" 에 답할 수 없고, 두 조가 한
    청크에 붙으면 검색이 엉뚱한 조를 근거로 든다. 항·호·목에서는 끊지 않는다 — 그 단위로
    쪼개면 조문 하나가 문장 조각들로 부서진다. 조가 상한을 넘을 때만 기존 길이 기준이
    안에서 작동하고, 그때 경계는 자연히 항(`①`) 문단 머리에 떨어진다.
    """
    options = options or ChunkOptions()
    chunks: list = []
    buffer = ""
    buffer_section = 0
    buffer_path: tuple = ()
    # 바로 앞 문단 = 다음 표의 제목 후보. 표를 지나면 비운다(표 뒤의 표는 앞 표를
    # 제목으로 삼으면 안 된다).
    table_title = ""

    def flush():
        nonlocal buffer
        if buffer.strip():
            chunks.append(
                Chunk(
                    text=buffer.strip(),
                    section=buffer_section,
                    kind="paragraph",
                    outline_path=buffer_path,
                )
            )
        buffer = ""

    def start(block: Block):
        """버퍼가 비었을 때 그 청크의 출처(섹션·조문 줄기)를 첫 블록에서 가져온다."""
        nonlocal buffer_section, buffer_path
        buffer_section = block.section
        buffer_path = block.outline_path

    for block in blocks:
        if block.is_table:
            flush()
            chunks.extend(_table_chunks(block, options, title=table_title))
            table_title = ""
            continue

        table_title = _table_title_of(block, options)

        if buffer and block.section != buffer_section:
            # 구역(`Contents/sectionN.xml`)이 바뀌면 끊는다. 안 끊으면 뒤 구역의 첫
            # 문단이 앞 구역 청크 꼬리에 붙고, 그 청크의 `i_section` 은 앞 구역을
            # 가리켜 **출처가 틀린다.** 예전에는 구역 경계에 표가 있어 우연히 끊겼을
            # 뿐이라 드러나지 않았다.
            flush()

        if (
            options.outline_break_level
            and block.outline_level
            and block.outline_level <= options.outline_break_level
        ):
            # 조 이상의 제목 = 하드 경계. 겹침도 넘기지 않는다 — 앞 조의 꼬리가 다음 조
            # 청크 머리에 붙으면 그 청크가 어느 조의 내용인지 흐려진다.
            flush()

        pieces = (
            [block.text]
            if _length(options, block.text) <= options.max_chars
            else _split_long_text(block.text, options)
        )
        for piece in pieces:
            candidate = f"{buffer}\n\n{piece}" if buffer else piece
            if buffer and _length(options, candidate) > options.max_chars:
                flush()
                tail = _overlap_tail(chunks[-1].text, options) if chunks else ""
                buffer = f"{tail}\n\n{piece}".strip() if tail else piece
                start(block)
            else:
                if not buffer:
                    # 옛 코드는 `not chunks and not buffer_section` 으로 첫 청크에서만
                    # 섹션을 잡았다 — 두 번째 청크부터 `i_section` 이 앞 청크 값에
                    # 얼어붙어, 섹션이 여럿인 문서에서 출처가 틀리게 실렸다.
                    start(block)
                buffer = candidate

    flush()
    return _apply_outline_prefix(
        _apply_table_prefix(_drop_heading_only_chunks(_merge_tiny(chunks, options))),
        options,
    )


def _merge_tiny(chunks: list, options: ChunkOptions) -> list:
    """너무 짧은 **문단** 청크를 앞에 붙인다.

    표 청크는 건드리지 않는다 — 짧아도 그 자체가 의미 단위이고, 문단에 붙이면 표가
    문단 꼬리에 섞여 버린다. **조문 줄기나 구역이 다르면 붙이지 않는다** — 붙이면 방금
    끊은 경계가 되돌려져 두 조(또는 두 구역)가 한 청크에 섞인다. 짧은 쪽이 앞 청크에
    흡수되는 모양이라, 경계를 세워 둔 코드만 읽어서는 왜 안 끊기는지 알 수 없다.
    """
    merged: list = []
    for chunk in chunks:
        if (
            chunk.kind == "paragraph"
            and merged
            and merged[-1].kind == "paragraph"
            and merged[-1].outline_path == chunk.outline_path
            # 구역·조 경계에서 끊어 놓고 여기서 도로 붙이면 경계가 없던 것이 된다.
            and merged[-1].section == chunk.section
            and _length(options, chunk.text) < options.min_chars
        ):
            previous = merged.pop()
            merged.append(
                Chunk(
                    text=f"{previous.text}\n\n{chunk.text}",
                    section=previous.section,
                    kind="paragraph",
                    outline_path=previous.outline_path,
                )
            )
        else:
            merged.append(chunk)
    return merged


def _drop_heading_only_chunks(chunks: list) -> list:
    """제목 하나뿐인 청크를 버린다 — **뒤 청크가 그 제목을 머리말로 이고 갈 때만.**

    `제2장 총칙` 처럼 제목만 있는 문단은 조 경계에서 끊기고 나면 홀로 남는데, 그 여섯
    글자로는 검색에서 아무것도 답하지 못하면서 자리만 차지한다. 그렇다고 무조건 버리면
    본문이 사라질 수 있으므로, **본문이 자기 이름표와 글자까지 같고**(= 제목 외에 아무
    내용이 없고) **다음 청크의 줄기가 그 제목을 포함**할 때만 버린다. 그 두 조건이면
    글자가 다음 청크의 머리말로 그대로 살아남으므로 무손실이다.
    """
    kept: list = []
    for index, chunk in enumerate(chunks):
        following = chunks[index + 1] if index + 1 < len(chunks) else None
        if (
            chunk.kind == "paragraph"
            
            and chunk.outline_path
            and chunk.text == chunk.outline_path[-1]
            and following is not None
            and following.outline_path[: len(chunk.outline_path)] == chunk.outline_path
        ):
            continue
        kept.append(chunk)
    return kept


def _table_prefix_for(chunk: Chunk) -> str:
    """표 청크 앞에 붙일 머리말. 붙일 게 없으면 빈 문자열.

    **왜 메타데이터가 아니라 본문에 넣나.** `i_table_part`·`table_title` 은 레코드에도
    싣지만, 검색 결과가 LLM 에게 갈 때의 봉투(`<doc file_name=… security_level=…>`)에는
    그 필드가 실리지 않는다 — 실물 결과에서 확인했다. 그래서 3번째 조각이 "3번 항목부터
    시작하는 표" 로 보이고, 앞의 1~2번이 어디 있는지도, 이게 표의 일부라는 것도 알 수
    없다. **조각이 혼자서도 해석 가능해야** 하므로 조문 머리말과 같은 이유로 본문에 넣는다.

    제목은 조문 줄기가 있을 때는 붙이지 않는다 — 그쪽은 `_apply_outline_prefix` 가
    이미 `제2장 총칙 > 제5조(목적)` 을 붙이고 있어 머리말이 두 겹이 된다.
    """
    if chunk.kind != "table":
        return ""
    pieces = []
    if chunk.table_title and not chunk.outline_path:
        pieces.append(chunk.table_title)
    if chunk.table_part is not None:
        # 저장값은 0-based(`i_table_part`), 사람이 읽는 자리에서만 1-based 로 낸다.
        index, total = chunk.table_part
        pieces.append(f"(표 {index + 1}/{total})")
    return " ".join(pieces)


def _apply_table_prefix(chunks: list) -> list:
    """표 청크 본문 앞에 `제목 (표 2/10)` 한 줄을 붙인다.

    조문 머리말과 마찬가지로 **길이 계산이 끝난 뒤에** 붙는다 — 머리말까지 상한 안에
    넣으려 하면 제목 길이에 따라 조각 크기가 들쭉날쭉해진다.
    """
    prefixed: list = []
    for chunk in chunks:
        prefix = _table_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n{chunk.text}") if prefix else chunk)
    return prefixed


def _outline_prefix_for(chunk: Chunk) -> str:
    """청크 앞에 붙일 위계 머리말. 붙일 게 없으면 빈 문자열.

    **이미 본문이 이고 있는 제목은 빼고 붙인다.** 조 제목 문단으로 시작하는 청크에
    `제5조(목적) > 제5조(목적) …` 처럼 겹쳐 붙으면 임베딩에 같은 문구가 두 번 실린다.
    """
    path = chunk.outline_path
    if path and chunk.text.startswith(path[-1]):
        path = path[:-1]
    return _OUTLINE_SEPARATOR.join(path)


def _apply_outline_prefix(chunks: list, options: ChunkOptions) -> list:
    """청크 본문 앞에 조문 줄기를 붙인다 (`outline_path` 자체는 그대로 남긴다).

    길이 계산이 끝난 뒤에 붙는다 — 머리말까지 `max_chars` 안에 넣으려 하면 조가 깊을수록
    본문이 밀려나고, 같은 문서에서 조마다 청크 크기가 들쭉날쭉해진다. 머리말은 조문
    위계가 있을 때만 붙으므로 일반 문서는 옛 동작 그대로다.
    """
    if not options.outline_prefix:
        return chunks

    prefixed: list = []
    for chunk in chunks:
        prefix = _outline_prefix_for(chunk)
        prefixed.append(replace(chunk, text=f"{prefix}\n\n{chunk.text}") if prefix else chunk)
    return prefixed


# ---------------------------------------------------------------------------
# VDB 레코드 — 청크 → GenOS 임베딩 입력.
#
# `pydantic` 모델을 만들지 않고 **dict 를 낸다** — `docs/GENOS_RULES.md` §I 가 요구하는
# "JSON 직렬화 가능한 값만 반환" 을 자연히 만족한다.
#
# hwpx 직접 파싱에는 페이지도 bbox 도 없다. 흐름 문서라 렌더링 전에는 페이지가 정해지지
# 않기 때문이다. **틀린 페이지 번호는 없는 것보다 나쁘다** — 0 으로 채우면 1페이지처럼
# 읽힌다. 대신 `i_section`/`n_section`/`source_kind`/`i_table_part` 를 추가로 싣는다.
# ---------------------------------------------------------------------------


def _counts(text: str) -> dict:
    """`n_char`/`n_word`/`n_line`. 지능형 전처리기의 `GenOSVectorMeta` 와 같은 이름·같은
    세는 법 — 검색 쪽이 그 이름으로 읽으므로 어긋나면 안 된다."""
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
    extra: dict | None = None,
) -> list:
    """청크 목록 → VDB 레코드(dict) 목록.

    Args:
        chunks: `chunk_blocks` 산출물.
        file_name: 원본 파일명 (검색 결과 출처 표시에 쓰인다).
        file_path: 원본 경로.
        section_count: 문서의 섹션 수 (`n_section`).
        reg_date: 적재 일시. 비우면 지금 시각(로컬 타임존)을 쓴다.
        extra: 모든 레코드에 함께 실을 값 (`security_level` 등 배포별 필드).

    Returns:
        `text` 키를 포함한 dict 목록. `i_chunk_on_doc`/`n_chunk_of_doc` 는 여기서
        매긴다 — 호출부가 매기면 문서를 나눠 처리할 때 번호가 겹친다.
    """
    stamp = reg_date or datetime.now(timezone.utc).astimezone().isoformat()
    total = len(chunks)
    records = []

    for index, chunk in enumerate(chunks):
        record = {
            "text": chunk.text,
            **_counts(chunk.text),
            # 페이지 관련은 전부 None — 위 모듈 docstring 참고
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
            # ── 이 경로에만 있는 것 ──
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
            #
            # **이름이 `i_` 로 시작하는 이유가 값의 규약이다.** `i_page`/`i_section` 과
            # 같은 0-based 이고, 본문 머리말(`(표 1/16)`)만 사람이 읽는 값이라 +1 한다.
            # 옛 이름은 `table_part` 였는데, 그 이름으로는 UI 가 `표 {값}/{총}` 을 그대로
            # 찍어 **첫 조각이 "표 0/16" 이 되고 16/16 은 영영 안 나온다** — 본문과 레코드가
            # 다른 번호를 말하는데 어느 쪽도 틀린 티가 안 난다.
            record["i_table_part"] = part_index
            record["n_table_part"] = part_total
        if chunk.table_title:
            # 본문 머리말과 **따로** 싣는다(조문 줄기와 같은 규약) — 머리말은 임베딩되라고
            # 있는 것이고, 이 값은 검색 결과에 "무슨 표인가" 를 표시하는 데 쓴다.
            record["table_title"] = chunk.table_title
        if chunk.outline_path:
            # 본문 머리말과 **따로** 싣는다. 머리말은 임베딩되라고 있는 것이고, 이 둘은
            # 검색 결과에 출처를 표시하거나 조 단위로 거르는 데 쓴다.
            record["outline_path"] = list(chunk.outline_path)
            record["outline_title"] = chunk.outline_path[-1]
        if extra:
            record.update(extra)
        records.append(record)

    return records


# ---------------------------------------------------------------------------
# GenOS 등록 단위 진입점
# ---------------------------------------------------------------------------


def _int_kwarg(value: Any, default: int, name: str) -> int:
    """kwargs 로 들어온 값을 int 로. 실패해도 예외를 내지 않고 기본값으로 떨어진다.

    등록 화면 파라미터 입력 실수(빈 문자열, 문자열 숫자, 범위 밖)가 재적재 전체를
    막으면 안 된다 — `ChunkOptions.__post_init__` 이 마지막 안전망으로 한 번 더
    범위를 강제한다.
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        _log_warning(
            "invalid preprocessor parameter, using default",
            event="hwpx_preprocess_param_invalid",
            error_code="05-00020003",
        )
        return default


class HwpxDocumentProcessor:
    """hwpx 전용 GenOS 전처리기(area 05).

    `docs/GENOS_RULES.md` §F 계약: 인자 없이 생성 가능해야 하고, `__call__` 은
    비동기이며 `text` 키를 가진 dict 목록을 돌려주거나 예외를 던진다.
    """

    SUPPORTED_EXTENSIONS = (".hwpx",)

    def __init__(self, config_path: str | None = None) -> None:
        # GenOS 는 `DocumentProcessor()` 를 무인자로 호출한다. `config_path` 는 다른
        # 전처리기(`genos_files/intelligence_processor.py` 등)와 생성자 시그니처를
        # 맞추기 위해 받아 두지만, 이 처리기는 설정 파일이 필요 없다 — 조정 가능한
        # 값은 전부 요청 시점의 `__call__(**kwargs)` 로 받는다.
        self._config_path = config_path

    async def __call__(self, request: Any, file_path: str, **kwargs: Any) -> list:
        start = time.monotonic()
        try:
            records = self._process(file_path, **kwargs)
        except HwpxParseError as exc:
            _log_warning(
                "hwpx preprocessing rejected input",
                event="hwpx_preprocess_failed",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            raise
        except Exception as exc:
            # 예상 못한 실패도 오류 dict 가 아니라 예외로 올린다(§A.4) — 여기서 삼키면
            # 반환값이 `list[dict]` 계약을 지키지 못한 채 조용히 빈 결과로 보일 수 있다.
            _log_warning(
                "hwpx preprocessing failed unexpectedly",
                event="hwpx_preprocess_failed",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            raise HwpxParseError(f"hwpx 처리 중 예기치 못한 오류가 발생했습니다: {exc}") from exc

        _log_info(
            "hwpx preprocessed",
            event="hwpx_preprocess_done",
            item_count=len(records),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return records

    def _process(self, file_path: str, **kwargs: Any) -> list:
        base_name = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise HwpxParseError(
                f"hwpx 전용 전처리기입니다 — 지원하지 않는 확장자입니다: '{ext or base_name}'"
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

        mode = str(kwargs.get("outline_mode") or _OUTLINE_AUTO).strip().lower()
        options = ChunkOptions(
            max_chars=_int_kwarg(kwargs.get("chunk_size"), _DEFAULT_MAX_CHARS, "chunk_size"),
            overlap_chars=_int_kwarg(
                kwargs.get("chunk_overlap"), _DEFAULT_OVERLAP_CHARS, "chunk_overlap"
            ),
            # 기본값 5(조)는 조문 사다리 전용이다. 공문서 사다리에 그대로 쓰면 다섯
            # 단계에서 전부 끊겨 항목 하나가 청크 하나가 된다.
            outline_break_level=(
                _DOC_BREAK_LEVEL if mode == _OUTLINE_DOCUMENT else _LEVEL_ARTICLE
            ),
        )
        blocks = annotate_outline(document.blocks, mode)
        chunks = chunk_blocks(blocks, options)
        if not chunks:
            raise HwpxParseError(f"청크를 만들지 못했습니다: {base_name}")

        extra = kwargs.get("extra_metadata")
        records = to_records(
            chunks,
            file_name=kwargs.get("file_name") or base_name,
            file_path=file_path,
            section_count=document.section_count,
            extra=extra if isinstance(extra, dict) else None,
        )

        for record in records:
            if not record.get("text"):
                # 여기까지 오면 chunk_blocks/to_records 의 불변식이 깨진 것이다 — 조용히
                # 넘기지 않는다(§F: text 키는 필수이며 빈 문자열이면 안 된다).
                raise HwpxParseError("빈 텍스트 청크가 생성되었습니다(내부 오류).")

        return records


# ===========================================================================
# PART 4 — 라우터 (onprem/preprocessor/router_template.py 원문)
# ===========================================================================
class FinalPreprocessorError(Exception):
    """라우터 자신이 내는 오류.

    hwpx 파싱 실패는 `HwpxParseError` 로, 벤더 경로의 실패는 그쪽 예외 그대로 올린다 —
    여기서 한 종류로 뭉치면 **어느 경로가 죽었는지가 로그에서 사라진다.**
    """


_FP_HWPX = "hwpx"
_FP_INTELLIGENT = "intelligent"
_FP_ATTACH = "attach"
_FP_ENGINES = (_FP_HWPX, _FP_INTELLIGENT, _FP_ATTACH)

_FP_ENGINE_AUTO = "auto"
_FP_ENGINE_NATIVE = "native"
_FP_HWPX_ENGINES = (_FP_ENGINE_AUTO, _FP_ENGINE_NATIVE, _FP_ATTACH, _FP_INTELLIGENT)

_FP_HWPX_EXTENSIONS = (".hwpx",)
_FP_ZIP_MAGIC = b"PK\x03\x04"
_FP_HWPX_MIMETYPE = b"application/hwp+zip"
_FP_SECTION_PREFIX = "Contents/section"

# ---------------------------------------------------------------------------
# 확장자 → 엔진. **형식마다 덜 잃는 쪽**으로 보낸다.
#
# 근거는 두 벤더 원본의 실제 경로다(모듈 docstring 의 표에 정리해 뒀다). 요약하면:
# 첨부용은 docx·hwp 를 **네이티브 백엔드**로 읽어 PDF 변환을 거치지 않고, 지능형은
# pdf 를 **docling layout + TableFormer + OCR** 로 읽는다. 서로의 약한 쪽이 정확히
# 반대라서 한 엔진만 고르면 어느 형식이든 손해가 난다.
#
# 여기 없는 확장자는 `_FP_DEFAULT_ENGINE` 으로 간다.
# ---------------------------------------------------------------------------
_FP_ROUTES = {
    # 우리 파서 — 표 병합·조문 위계를 지킨다
    ".hwpx": _FP_HWPX,
    # 첨부용: GenosHwp SDK / GenosMsWord 네이티브. 지능형은 이것들을 PDF 로 바꾼다
    ".hwp": _FP_ATTACH,
    ".hml": _FP_ATTACH,
    ".docx": _FP_ATTACH,
    # 첨부용: Whisper STT. 지능형에는 이 경로가 아예 없다
    ".wav": _FP_ATTACH,
    ".mp3": _FP_ATTACH,
    ".m4a": _FP_ATTACH,
    # 첨부용: TextLoader. 지능형은 텍스트 파일도 PDF 로 바꾼다
    ".txt": _FP_ATTACH,
    ".md": _FP_ATTACH,
    ".json": _FP_ATTACH,
    # 지능형: 첨부용 pdf 경로는 PyMuPDF 평문 + 문자 수 분할이라 표가 통째로 사라진다
    ".pdf": _FP_INTELLIGENT,
    # 지능형: 둘 다 PDF 변환이지만 enrichment 가 더 많다
    ".ppt": _FP_INTELLIGENT,
    ".pptx": _FP_INTELLIGENT,
    # 지능형: PDF 변환 없이 직접 처리 + tabular 모드
    ".xlsx": _FP_INTELLIGENT,
    ".xlsm": _FP_INTELLIGENT,
    ".csv": _FP_INTELLIGENT,
    # 지능형: docling OCR
    ".jpg": _FP_INTELLIGENT,
    ".jpeg": _FP_INTELLIGENT,
    ".png": _FP_INTELLIGENT,
    ".gif": _FP_INTELLIGENT,
    ".bmp": _FP_INTELLIGENT,
    ".tiff": _FP_INTELLIGENT,
    # 구버전 Word — 둘 다 PDF 변환을 거친다. 지능형 파이프라인이 낫다
    ".doc": _FP_INTELLIGENT,
}
_FP_DEFAULT_ENGINE = _FP_INTELLIGENT

# 라우터가 자기 몫으로 받는 값. 벤더 처리기로 **넘기기 전에 뺀다** — 그대로 넘기면
# 벤더가 `kwargs: {...}` 로 통째로 로그에 찍고, 언젠가 같은 이름을 쓰면 조용히 겹친다.
_FP_ROUTER_KWARGS = (
    "hwpx_engine",
    "route_overrides",
    "align_vector_schema",
    "intelligent_config_path",
    "attachment_config_path",
)

_FP_CONFIG_ENV = {
    _FP_INTELLIGENT: "GENOS_INTELLIGENT_CONFIG_PATH",
    _FP_ATTACH: "GENOS_ATTACHMENT_CONFIG_PATH",
}
_FP_CONFIG_BASENAMES = {
    _FP_INTELLIGENT: ("intelligent_processor_config.yaml",),
    _FP_ATTACH: ("attachment_processor_config.yaml", "attach_processor_config.yaml"),
}
_FP_CONFIG_KWARG = {
    _FP_INTELLIGENT: "intelligent_config_path",
    _FP_ATTACH: "attachment_config_path",
}

# 벤더 레코드에는 늘 있고 hwpx 레코드에는 없던 예약 필드. **한 등록이 한 컬렉션에 두
# 모양의 메타를 넣으면** 그 필드로 거르는 검색이 한쪽을 통째로 놓치는데, 그 상태는
# 오류가 아니라 "결과가 좀 적네" 로만 보인다. 값은 벤더가 못 채웠을 때 내는 것과 같은
# 것을 쓴다 — **지어내지 않는다.**
_FP_SCHEMA_DEFAULTS = {
    "title": "",
    "created_date": None,
    "appendix": "",
    "guardrail_categories": None,
}


def _fp_engine_error(engine: str):
    """그 엔진을 쓸 수 없게 만든 예외. 쓸 수 있으면 `None`.

    **첨부용은 지능형에도 의존한다.** 병합할 때 본문이 같은 정의 14개를 첨부용 쪽에서
    지웠고(죽은 코드였다) 그 자리를 지능형 판본이 채우기 때문이다. 지능형 절반이
    적재되지 않았으면 첨부용 코드가 `NameError` 로 죽으므로, 여기서 미리 갈라
    **어느 절반이 문제인지**를 알려 준다.
    """
    if engine == _FP_INTELLIGENT:
        return _FP_INTELLIGENT_IMPORT_ERROR
    if engine == _FP_ATTACH:
        return _FP_ATTACH_IMPORT_ERROR or _FP_INTELLIGENT_IMPORT_ERROR
    return None


def _fp_choice_kwarg(value, default: str, allowed: tuple, key: str) -> str:
    """선택지 kwargs. 잘못된 값은 **세우지 않고** 기본값으로 떨어지되 로그에 남긴다.

    GenOS 는 값이 비었을 때 `None` 이 아니라 **빈 문자열**을 주기도 한다(MCP 규약과 같다).
    """
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text in allowed:
        return text
    _log_warning(f"unknown {key} - falling back to '{default}'", event="final_preprocess_bad_kwarg")
    return default


def _fp_bool_kwarg(value, default: bool, key: str) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    _log_warning(f"unknown {key} - falling back to '{default}'", event="final_preprocess_bad_kwarg")
    return default


def _fp_overrides_kwarg(value) -> dict:
    """`{".pdf": "attach"}` 꼴 라우팅 덮어쓰기. 문자열(JSON)로 와도 받는다."""
    if not value:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:  # noqa: BLE001 - 형식 오류로 재적재를 막지 않는다
            _log_warning("route_overrides is not valid JSON - ignored",
                         event="final_preprocess_bad_kwarg")
            return {}
    if not isinstance(value, dict):
        _log_warning("route_overrides is not a mapping - ignored",
                     event="final_preprocess_bad_kwarg")
        return {}
    clean = {}
    for key, engine in value.items():
        ext = str(key).strip().lower()
        target = str(engine).strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        if target not in _FP_ENGINES:
            _log_warning("route_overrides names an unknown engine - that entry is ignored",
                         event="final_preprocess_bad_kwarg")
            continue
        clean[ext] = target
    return clean


def _fp_is_hwpx_container(file_path: str):
    """내용이 hwpx 인가. `(판정, 사유)`.

    확장자만 믿지 않는 이유: `.hwpx` 라는 이름을 달았을 뿐 실제로는 PDF·hwp 인 파일이
    우리 파서에 들어가면 예외가 나고 **그 문서는 검색에서 통째로 사라진다.** 여기서
    갈라 벤더로 보내면 표는 덜 정확해도 적재는 된다.
    """
    try:
        with open(file_path, "rb") as handle:
            head = handle.read(4)
    except OSError:
        return False, "read_failed"
    if head != _FP_ZIP_MAGIC:
        return False, "not_a_zip"
    try:
        with zipfile.ZipFile(file_path) as archive:
            names = archive.namelist()
            mimetype = b""
            if "mimetype" in names:
                try:
                    mimetype = archive.read("mimetype").strip()
                except (KeyError, OSError, zipfile.BadZipFile):
                    mimetype = b""
    except (OSError, zipfile.BadZipFile):
        return False, "broken_zip"
    if mimetype == _FP_HWPX_MIMETYPE:
        return True, "mimetype"
    for name in names:
        if name.startswith(_FP_SECTION_PREFIX) and name.endswith(".xml"):
            return True, "section_xml"
    # zip 이긴 한데 hwpx 가 아니다 — docx/pptx/xlsx 가 `.hwpx` 이름을 달고 온 경우다.
    return False, "zip_without_hwpx_contents"


def _fp_route(file_path: str, hwpx_engine: str, overrides: dict):
    """`(엔진, 사유)`. 사유는 고정 문자열이라 로그에 그대로 실어도 된다(3.8절)."""
    extension = os.path.splitext(file_path)[1].lower()
    engine = overrides.get(extension) or _FP_ROUTES.get(extension, _FP_DEFAULT_ENGINE)
    reason = "override" if extension in overrides else "extension"

    if engine != _FP_HWPX:
        return engine, reason

    # 여기부터는 hwpx 확장자다.
    if hwpx_engine in (_FP_ATTACH, _FP_INTELLIGENT):
        return hwpx_engine, "hwpx_engine"

    is_hwpx, why = _fp_is_hwpx_container(file_path)
    if is_hwpx:
        return _FP_HWPX, why
    if hwpx_engine == _FP_ENGINE_NATIVE:
        # 네이티브를 강제했으면 넘기지 않는다 — 확장자와 내용이 어긋났다는 사실이
        # 폴백에 묻히면 안 된다는 뜻으로 고른 값이다.
        return _FP_HWPX, why
    # 이름만 hwpx 인 파일은 첨부용으로 — 실제로 hwp 계열이면 그쪽이 네이티브로 읽는다.
    return _FP_ATTACH, why


def _fp_align_records(records: list) -> list:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in _FP_SCHEMA_DEFAULTS.items():
            record.setdefault(key, value)
    return records


def _fp_forward_kwargs(kwargs: dict) -> dict:
    return {key: value for key, value in kwargs.items() if key not in _FP_ROUTER_KWARGS}


def _fp_resolve_config_path(engine: str, explicit):
    """벤더 설정 yaml 을 찾는다. 못 찾으면 `None`(벤더 기본 해석에 맡긴다).

    벤더 함수는 `Path(__file__).parent/../resource/…` 를 본다. 등록 파일이 어디에 놓이는지
    실물로 확인하지 못했으므로 **한 자리만 보고 죽지 않게** 후보를 넷 둔다.
    """
    for candidate in (explicit, os.environ.get(_FP_CONFIG_ENV[engine], "")):
        text = str(candidate or "").strip()
        if not text:
            continue
        if os.path.isfile(text):
            return text
        _log_warning("configured vendor config path does not exist - trying the next candidate",
                     event="final_preprocess_config_missing")
    vendor_resolver = globals().get(
        "_resolve_default_intelligent_config_path" if engine == _FP_INTELLIGENT
        else "_resolve_default_attachment_config_path"
    )
    if vendor_resolver is not None:
        try:
            vendor_path = vendor_resolver()
        except Exception:  # noqa: BLE001 - 경로 해석 실패는 다음 후보로 넘어갈 뿐이다
            vendor_path = ""
        if vendor_path and os.path.isfile(vendor_path):
            return vendor_path
    node = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        for sub in ("resource_dev", "resource"):
            for basename in _FP_CONFIG_BASENAMES[engine]:
                candidate = os.path.join(node, sub, basename)
                if os.path.isfile(candidate):
                    return candidate
        parent = os.path.dirname(node)
        if parent == node:
            break
        node = parent
    return None


class DocumentProcessor:
    """GenOS 가 실행하는 진입점 — 확장자와 **내용**을 보고 세 처리기 중 하나로 보낸다.

    `docs/GENOS_RULES.md` §F 계약 그대로다: 인자 없이 생성 가능하고, `__call__` 은
    비동기이며 `text` 키를 가진 dict 목록을 돌려주거나 예외를 던진다.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        # hwpx 처리기는 지금 만든다 — 표준 라이브러리 + lxml 뿐이라 비용이 없다.
        self._hwpx = HwpxDocumentProcessor()
        # 벤더 둘은 **그 엔진으로 갈 파일이 처음 들어올 때** 만든다. 생성자가 yaml 을
        # 읽고 토크나이저·docling 변환기를 올리기 때문에, 여기서 만들면 hwpx 만 넣는
        # 배포도 그 비용과 실패 가능성을 함께 진다.
        self._vendor: dict = {}
        self._vendor_lock = None
        for engine in (_FP_INTELLIGENT, _FP_ATTACH):
            failure = _fp_engine_error(engine)
            if failure is not None:
                _log_warning(
                    f"{engine} preprocessing path unavailable",
                    event="final_preprocess_engine_unavailable",
                    error_type=type(failure).__name__,
                )

    async def __call__(self, request, file_path: str, **kwargs) -> list:
        started = time.monotonic()
        hwpx_engine = _fp_choice_kwarg(
            kwargs.get("hwpx_engine"), _FP_ENGINE_AUTO, _FP_HWPX_ENGINES, "hwpx_engine"
        )
        overrides = _fp_overrides_kwarg(kwargs.get("route_overrides"))
        engine, reason = _fp_route(file_path, hwpx_engine, overrides)
        _log_info(f"routed to {engine} ({reason})", event="final_preprocess_routed", status=engine)

        if engine != _FP_HWPX:
            return await self._run_vendor(engine, request, file_path, **kwargs)

        try:
            records = await self._hwpx(request, file_path, **_fp_forward_kwargs(kwargs))
        except Exception as exc:  # noqa: BLE001 - 분류는 아래 두 줄이 한다
            if hwpx_engine == _FP_ENGINE_NATIVE or _fp_engine_error(_FP_ATTACH) is not None:
                raise
            # 적재가 통째로 실패하는 것보다 표가 덜 정확한 적재가 낫다는 판단이다.
            # **폴백은 첨부용으로 간다** — GenosHwp SDK 네이티브라 hwpx 를 PDF 로 바꾸는
            # 지능형보다 덜 잃는다. **다만 조용히 넘기지 않는다**: 이 로그가 없으면
            # 사용자는 표 병합이 보존됐다고 믿는다.
            _log_warning(
                "hwpx native path failed - falling back to the attachment path "
                "(표 병합/조문 위계는 보존되지 않는다)",
                event="final_preprocess_fallback",
                error_code="05-00020003",
                error_type=type(exc).__name__,
            )
            return await self._run_vendor(_FP_ATTACH, request, file_path, **kwargs)

        if _fp_bool_kwarg(kwargs.get("align_vector_schema"), True, "align_vector_schema"):
            records = _fp_align_records(records)
        _log_info(
            "hwpx native path done",
            event="final_preprocess_done",
            status=_FP_HWPX,
            item_count=len(records),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return records

    async def _run_vendor(self, engine: str, request, file_path: str, **kwargs) -> list:
        processor = await self._acquire(engine, kwargs.get(_FP_CONFIG_KWARG[engine]))
        return await processor(request, file_path, **_fp_forward_kwargs(kwargs))

    async def _acquire(self, engine: str, config_path_kwarg=None):
        existing = self._vendor.get(engine)
        if existing is not None:
            return existing

        failure = _fp_engine_error(engine)
        if failure is not None:
            # 빈 목록을 돌려주지 않는다 — 그러면 "내용이 없는 문서" 와 구별되지 않는다.
            detail = ""
            if engine == _FP_ATTACH and _FP_ATTACH_IMPORT_ERROR is None:
                # 첨부용 코드는 멀쩡한데 지능형 절반이 없어서 못 쓰는 경우다. 그렇게
                # 말하지 않으면 엉뚱한 곳(첨부용 의존성)을 뒤지게 된다.
                detail = " (첨부용 코드는 적재됐지만 그것이 쓰는 지능형 쪽 공통 정의가 없습니다)"
            raise FinalPreprocessorError(
                f"'{engine}' 전처리 경로를 사용할 수 없어 이 형식은 처리할 수 없습니다"
                f"{detail} ({type(failure).__name__}: {failure})"
            )

        if self._vendor_lock is None:
            # 이 판정과 대입 사이에 await 가 없으므로 이벤트 루프에서 갈리지 않는다.
            self._vendor_lock = asyncio.Lock()
        async with self._vendor_lock:
            if self._vendor.get(engine) is None:
                started = time.monotonic()
                # 생성이 blocking 이다(yaml·토크나이저·docling 변환기). 이벤트 루프에서
                # 그대로 돌리면 같은 워커의 다른 요청이 그 시간만큼 멈춘다.
                self._vendor[engine] = await asyncio.to_thread(
                    self._build, engine, config_path_kwarg
                )
                _log_info(
                    f"{engine} processor initialised",
                    event="final_preprocess_engine_ready",
                    status=engine,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
        return self._vendor[engine]

    def _build(self, engine: str, config_path_kwarg):
        resolved = _fp_resolve_config_path(engine, config_path_kwarg or self._config_path)
        factory = (
            IntelligentDocumentProcessor if engine == _FP_INTELLIGENT else AttachDocumentProcessor
        )
        try:
            return factory(resolved) if resolved else factory()
        except Exception as exc:  # noqa: BLE001
            # 설정 파일 부재는 **재시도로 풀리지 않는 배포 문제**다. 원래 예외
            # (FileNotFoundError 등)만 올리면 어느 파일이 없다는 건지 드러나지 않아
            # 몇 번을 다시 눌러도 같은 자리에서 실패한다.
            raise FinalPreprocessorError(
                f"'{engine}' 전처리기를 초기화하지 못했습니다({type(exc).__name__}): {exc}"
            ) from exc
