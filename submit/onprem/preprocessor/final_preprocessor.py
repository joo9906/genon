"""GenOS 통합 전처리기 — hwpx 는 우리 파서, 나머지는 첨부용 벤더 처리기로.

**이 파일이 정본이다. 여기서 직접 고친다.** (2026-09-03 — 그전에는 조각 셋을 합쳐
만드는 생성물이었고 빌드 스크립트가 있었다. 폐쇄망에는 이 파일을 보고 손으로 옮겨
적으므로, 정본과 옮겨 적는 대상이 다르면 한 겹이 더 생길 뿐이다.)

## 이 파일의 구조 — PART 세 덩어리

`# PART ` 로 검색하면 경계가 나온다. **순서가 계약이다 — 뒤엣것이 앞엣것을 덮는다.**

| PART | 무엇 | 고칠 일 |
|---|---|---|
| 1 | 첨부용 (벤더) — hwpx 아닌 전 형식 | GenOS 참조 사본이라 거의 없다. 갱신은 `genos_files/attach_processor.py` 와 대조 |
| 2 | hwpx 파서 — 파싱·위계·청킹·레코드 | 표·조문 위계·청크 경계·레코드 필드 |
| 3 | 라우터 — 라우팅·폴백·스키마 정렬·pdf/docx 위계 | 확장자 매핑·폴백 정책·등록 화면 kwargs |

어느 함수가 어느 층에 있는지는 `onprem/preprocessor/README.md` 최상단 표에 있다.

## 왜 한 파일인가

GenOS 전처리기 등록은 **소스 파일 하나**를 받아 그 파일이 정의하는 `DocumentProcessor`
를 실행한다. 서로 import 할 수 없으므로(벤더 원본도 같은 이유로 `convert_to_pdf` 를
자기 안에 복제해 두고 있다) 한 등록에서 두 처리기를 쓰려면 한 파일에 있어야 한다.

## 지능형은 2026-09-01 에 뺐다

그전에는 `intelligence_processor.py`(적재용·지능형)가 함께 들어가 pdf·ppt·엑셀·이미지를
받았다. **그 경로가 실환경에서 동작하지 않아 통째로 걷어냈다.** 그 형식들은 이제 전부
첨부용으로 간다.

**pdf 는 계속 처리되고 조/항/호 위계도 그대로 걸린다** — 첨부용 pdf 는 langchain
`Document` 목록으로 오므로 라우터에 어댑터를 하나 더 뒀다(`_fp_langchain_blocks`).
잃은 것은 **표 격자 하나**다: 첨부용 pdf 는 `PyMuPDFLoader` 평문이라 표가 문장으로
풀린다(지능형은 TableFormer 로 격자를 복원했다). 오류는 나지 않고 적재도 되므로 그
사실은 "표를 물어봤는데 답이 이상하다" 로만 드러난다.

## 라우팅

| 입력 | 어디로 | 근거 |
|---|---|---|
| `.hwpx` (내용도 hwpx 컨테이너) | **hwpx 파서** | 표 병합(rowSpan/colSpan)·조문 위계를 지킨다 |
| 그 밖의 전 형식 | 첨부용 | `.hwp`·`.hml`·`.docx` 는 GenosHwp/GenosMsWord **네이티브**, 오디오는 Whisper STT, `.csv`·`.xlsx` 는 TabularLoader, `.ppt(x)` 는 PDF 변환 후 docling, 나머지는 langchain 로더 |

**확장자만 보고 보내지 않는다** — `.hwpx` 는 zip 을 열어 실제로 hwpx 컨테이너인지 본다.
이름만 `.hwpx` 인 파일을 우리 파서에 넣으면 예외가 나고 **그 문서는 검색에서 통째로
사라진다.** 벤더로 보내면 표는 덜 정확해도 적재는 된다.

## 합친 순서가 계약이다 — 뒤엣것이 앞엣것을 덮는다

PART 1 첨부용 → PART 2 hwpx → PART 3 라우터.

셋 다 `DocumentProcessor` 를 정의하는데 GenOS 가 실행하는 것은 **마지막에 남는 하나**
이므로 앞의 둘을 `AttachDocumentProcessor`·`HwpxDocumentProcessor` 로 비켰다. `Document`
도 겹친다 — 첨부용은 langchain 것을 import 하고 hwpx 는 같은 이름의 데이터클래스를
정의한다. hwpx 가 뒤라 그대로 두면 첨부용의 20개 호출부가 **호출 시점에** 터지므로
(import 는 통과한다) hwpx 쪽을 `HwpxDocument` 로 바꿨다. 개명한 자리에 `[병합 개명]`
표식 주석이 있다.

## 벤더 절반이 없는 환경에서도 이 파일은 import 된다

PART 1 은 `try:` 안에 있다. docling·`genon.preprocessor.*` 가 없으면 그 절반만 비활성이
되고 **hwpx 경로는 그대로 돈다.** 비활성 사실은 숨기지 않는다 — 그 엔진으로 가야 할
파일이 들어오면 **사유를 담아 예외를 던진다**(조용히 빈 결과를 내지 않는다).

## 등록 화면에서 더 받는 값

hwpx 경로는 `hwpx_preprocessor.py` 의 값(`chunk_size`·`chunk_overlap`·`outline_mode`·
`file_name`·`extra_metadata`)을, 첨부용 경로는 원본의 값을 그대로 받는다. 라우터 몫:

| 키 | 기본값 | 의미 |
|---|---|---|
| `hwpx_engine` | `auto` | `auto`=hwpx 파서, 실패하면 첨부용으로 폴백(GenosHwp SDK 네이티브라 덜 잃는다) / `native`=폴백 없음 / `attach`=hwpx 도 첨부용으로 |
| `route_overrides` | 없음 | `{".pdf": "attach"}` 꼴로 확장자별 라우팅을 덮어쓴다 |
| `align_vector_schema` | `true` | hwpx 레코드에 벤더 예약 필드(`title`·`created_date`·`appendix`·`guardrail_categories`)를 채워 **한 컬렉션 안 메타 스키마를 맞춘다** |
| `outline_mode` | `auto` | **hwpx·pdf·docx 에 걸린다.** `제N조` 를 2개 이상 세면 조/항/호 위계로 청킹하고 `제2장 총칙 > 제5조(목적)` 머리말을 붙인다. 조문 문서가 아니면 벤더 청커 그대로다 |
| `attachment_config_path` | 없음 | 벤더 설정 yaml. 없으면 환경변수 → 벤더 기본 경로 → 이 파일 주변 순으로 찾는다 |

값이 잘못된 타입/범위면 에러를 내지 않고 기본값으로 떨어지되 로그에 남긴다.

## 페이지 자리에는 **구역(section)** 이 들어간다 (2026-09-03)

hwpx 는 흐름 문서라 렌더링 전에는 페이지가 정해지지 않는다. 그렇다고 `None` 으로 두면
**GenOS 적재 결과 화면이 청크를 묶지 못해 아무것도 안 뜬다** — 오류가 아니라 빈 목록이라
로그 어디에도 안 남고, 사람이 API 를 직접 쳐서 확인하게 된다. 그래서 hwpx 가 실제로 갖는
경계인 **구역**을 그 자리에 넣는다.

| 필드 | 값 |
|---|---|
| `i_page`·`e_page` | 구역 번호 + 1 (**1-based** — 벤더 pdf 경로의 `page_no` 와 같은 기준) |
| `n_page` | 구역 수 |
| `i_chunk_on_page` | 그 구역 안에서의 순번 (**0-based** — 벤더 `chunk_index_on_page` 와 같은 기준) |
| `n_chunk_of_page` | 그 구역의 청크 수 |
| `page_basis` | `"section"` — **값의 출처를 레코드가 말한다** |
| `chunk_bboxes`·`media_files` | `"[]"` · `""` (벤더가 못 찾았을 때 내는 값과 같다) |

**지어내는 것과 다른 점은 `page_basis` 다** — 나중에 "페이지 수가 실물과 다르다" 를
추적할 수 있고, 렌더링된 페이지라고 주장하지 않는다. 되돌릴 자리는 `_page_fields`
하나이며 `i_section`/`n_section` 은 그대로라 이 매핑이 사라져도 구역 정보는 안 잃는다.

진짜 페이지·bbox 가 필요하면 `hwpx_engine="attach"` 로 그 문서만 벤더 경로에 태울 수
있고, 그건 표가 깨지는 쪽이다.
"""

from __future__ import annotations

import asyncio
import json
import traceback

# ===========================================================================
# PART 1 — 첨부용 (벤더). 참조 원본: genos_files/attach_processor.py
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

    _log = logging.getLogger(__name__)


    # ── 비정상/암호화 파일 사전 감지 (이슈 #278/#307) ─────────────────────────────
    # intelligent_processor.py 의 동일 블록을 복제한 것. facade 는 단일 파일로 배포되므로
    # import 공유 대신 복제한다. 수정 시 네 파일(intelligent/parser/convert/attachment) 동기화 필요.
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
    try:
        from genon.preprocessor.facade.enrichment.page_description import (
            PageDescriptionOptions,
            describe_pages,
        )
    except ImportError:
        class PageDescriptionOptions:
            # 모듈이 없는 설치본에서는 `enabled=False` 로 둔다 — 호출부가 이 값으로
            # `generate_page_images`(`:2009`)와 로그(`:2084`)를 정하므로 속성이 있어야 한다.
            enabled = False
            images_scale = 1.0

            @classmethod
            def from_config(cls, *_args, **_kwargs):
                return cls()


        def describe_pages(_document, _options, page_texts=None, **_kwargs):
            # 빈 dict = 설명 0건. 호출부(`:2063`)가 native text 만으로 페이지 청크를 만든다.
            return {}
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


    def _warn_unresolved_placeholders(cfg: dict, config_path: str) -> None:
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


    def _load_config(config_path: str) -> dict:
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


    def _parse_optional_float(value: Any, key: str = "") -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            if key:
                _log.warning(f"[DocumentProcessor] Invalid float value for '{key}': {value!r}. Fallback to default.")
            return None


    def _resolve_default_attachment_config_path() -> str:
        base_dir = Path(__file__).resolve().parent
        local_config = (base_dir / "../resource_dev/attachment_processor_config.yaml").resolve()
        default_config = (base_dir / "../resource/attachment_processor_config.yaml").resolve()

        if local_config.exists():
            return str(local_config)
        return str(default_config)


    def _resolve_tokenizer(chunking_cfg: dict):
        """chunking config 로부터 토크나이저를 결정한다.

    tokenizer_path 가 실제 존재하면 그 로컬 경로를, 없으면 tokenizer_id(HF) 로 폴백한다
    (외부 네트워크 차단 환경 대비). config 미지정 시 기본값은 현행 하드코딩 값과 동일.
    """
        local = chunking_cfg.get("tokenizer_path") or _DEFAULT_TOKENIZER_LOCAL_PATH
        hf_id = chunking_cfg.get("tokenizer_id") or _DEFAULT_TOKENIZER_ID
        return Path(local) if Path(local).exists() else hf_id


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
        # 이슈 #286 — 변환 backend(pdf_sdk/rhwp/libreoffice)가 전무하면(빌드 시 OFF) 변환 시도가
        # 무의미하므로, PDF 직접 입력을 안내하는 warning 한 번만 남기고 None 을 반환한다.
        if not _has_any_pdf_converter():
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


    def _has_any_pdf_converter() -> bool:
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


    class GenOSVectorMeta(BaseModel):
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

        def build(self) -> GenOSVectorMeta:
            """설정된 데이터를 사용해 최종적으로 GenOSVectorMeta 객체 생성"""
            return GenOSVectorMeta(
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
            vectors = [GenOSVectorMeta.model_validate({
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
            res = [GenOSVectorMeta.model_validate({
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

                vector = (GenOSVectorMetaBuilder()
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
                raise GenosServiceException(1, "chunk length is 0")
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

                builder = GenOSVectorMetaBuilder()
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
                raise GenosServiceException(1, "chunk length is 0")
            return await self.compose_vectors(
                document, chunks, page_chunk_counts, request, _sensitive_infos=sensitive_infos, _guardrail_masking=(gr.call_enabled(kwargs) and self._guardrail_masking_enabled), **kwargs
            )

    class GenosServiceException(Exception):
        """GenOS 와의 의존성 부분 제거를 위해 추가"""

        def __init__(self, error_code: str, error_msg: Optional[str] = None, msg_params: Optional[dict] = None) -> None:
            self.code = 1
            self.error_code = error_code
            self.error_msg = error_msg or "GenOS Service Exception"
            self.msg_params = msg_params or {}

        def __repr__(self) -> str:
            class_name = self.__class__.__name__
            return f"{class_name}(code={self.code!r}, errMsg={self.error_msg!r})"


    # [병합 개명] `DocumentProcessor` → `AttachDocumentProcessor` — 세 조각이 다 `DocumentProcessor` 를 정의한다.
    #             GenOS 가 실행하는 것은 마지막에 남는 하나라 라우터 것에 자리를 내준다.
    class AttachDocumentProcessor:
        def __init__(self, config_path: str | None = None):
            if config_path is None:
                config_path = _resolve_default_attachment_config_path()
            cfg = _load_config(config_path)
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
            pdf_path = convert_to_pdf(file_path, use_pdf_sdk=kwargs.get('use_pdf_sdk', True))
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
                convert_to_pdf(file_path, use_pdf_sdk=use_pdf_sdk)
                return UnstructuredWordDocumentLoader(file_path)
            elif ext in ['.ppt', '.pptx']:
                convert_to_pdf(file_path, use_pdf_sdk=use_pdf_sdk)
                return UnstructuredPowerPointLoader(file_path)
            elif ext in ['.jpg', '.jpeg', '.png']:
                convert_to_pdf(file_path, use_pdf_sdk=use_pdf_sdk)
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

                vectors.append(GenOSVectorMeta.model_validate({
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
                raise GenosServiceException(
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
                    converted = convert_to_pdf(file_path, use_pdf_sdk=kwargs.get('use_pdf_sdk', True))
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
                        if not _has_any_pdf_converter():
                            raise GenosServiceException(
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
# PART 2 — hwpx 전용 파서 (우리 코드)
# ===========================================================================
# hwpx 를 PDF 로 바꾸지 않고 ZIP 안의 `Contents/sectionN.xml` 을 직접 읽어 문단과 표를
# 판정한다. 표는 **언제나 한 줄짜리 HTML** 로 낸다 — 검색 결과가 LLM 에게 갈 때 개행이
# 뭉개져 마크다운 표는 표가 아니게 된다(`_render_table` 이 이유를 적는다).
#
# 계약(`docs/GENOS_RULES.md` §A.4, §F): 인자 없이 생성 가능한 처리기, 비동기
# `__call__(request, file_path, **kwargs)`, 반환은 `list[dict]` 이고 각 항목에 **`text`
# 키 필수**(빈 문자열 불가). 오류는 오류 dict 가 아니라 **예외**로 낸다.
#
# **이 덩어리는 다른 파일을 import 하지 않는다** (표준 라이브러리 + `lxml` 만).
# 여기 클래스 이름이 `HwpxDocument`·`HwpxDocumentProcessor` 인 것은 PART 1·3 과 겹치기
# 때문이다 — 파일 맨 위 "합친 순서가 계약이다" 절.
#
# 페이지는 hwpx 가 흐름 문서라 렌더링 전에 정해지지 않는다. **구역(section)을 그 자리에
# 넣고 `page_basis` 가 출처를 말한다** — 파일 맨 위 "페이지 자리에는 구역이 들어간다".


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
        origin: **이 파일 밖에서 온 블록의 출처 표식.** hwpx 경로는 채우지 않는다(빈 값).
            벤더 문서(docling)를 블록으로 옮겨 이 청커를 태우는 경로가 쓴다 — 청크가
            어느 원본 항목에서 나왔는지를 잃으면 벤더의 `compose_vectors` 가 bbox·
            이미지 업로드·민감정보 마스킹을 붙일 자리를 못 찾는다. **불투명한 값**이고
            여기서는 실어 나르기만 한다(해석은 넣은 쪽이 한다).

    `parse()` 는 위계 둘을 채우지 않는다(XML 에 없는 정보다). `annotate_outline()` 이
    채운다 — 파싱과 위계 판정을 갈라 둬야 위계를 꺼도 파싱 결과가 같다.
    """

    kind: str
    text: str
    section: int
    outline_level: int = 0
    outline_path: tuple = ()
    origin: tuple = ()

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
#h
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
        origin: 이 청크가 덮는 블록들의 `Block.origin` 을 **순서대로 이어 붙인 것**
            (중복 제거). hwpx 경로는 언제나 빈 값이다. 이 값이 없으면 벤더 경로가
            청크를 원본 항목에 되짚지 못한다 — `Block.origin` 설명 참고.
    """

    text: str
    section: int
    kind: str
    table_part: tuple | None = None
    table_title: str = ""
    outline_path: tuple = ()
    origin: tuple = ()


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


def _extend_origin(base: tuple, extra: tuple) -> tuple:
    """출처를 순서대로 잇되 이미 있는 것은 다시 넣지 않는다.

    **동일성(`is`)으로 본다.** 이 값은 이 파일 밖에서 온 불투명한 물건이라 해시
    가능한지도, `==` 가 값 비교인지도 알 수 없다 — 벤더 모델이 무거운 `__eq__` 를
    가지면 청킹이 조용히 느려진다. 길이가 한 청크 몫이라 선형 검색으로 충분하다.
    """
    if not extra:
        return base
    merged = list(base)
    for item in extra:
        if not any(item is seen for seen in merged):
            merged.append(item)
    return tuple(merged)


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
                origin=block.origin,
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
            # 표를 쪼개도 조각마다 **같은 출처**다 — 원본 항목은 그 표 하나이고, 쪼갠
            # 것은 우리 사정이다. 조각마다 나눠 주면 bbox·이미지가 한 조각에만 붙는다.
            origin=block.origin,
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
    buffer_origin: tuple = ()
    # 바로 앞 문단 = 다음 표의 제목 후보. 표를 지나면 비운다(표 뒤의 표는 앞 표를
    # 제목으로 삼으면 안 된다).
    table_title = ""

    def flush():
        nonlocal buffer, buffer_origin
        if buffer.strip():
            chunks.append(
                Chunk(
                    text=buffer.strip(),
                    section=buffer_section,
                    kind="paragraph",
                    outline_path=buffer_path,
                    origin=buffer_origin,
                )
            )
        buffer = ""
        buffer_origin = ()

    def start(block: Block):
        """버퍼가 비었을 때 그 청크의 출처(섹션·조문 줄기)를 첫 블록에서 가져온다."""
        nonlocal buffer_section, buffer_path, buffer_origin
        buffer_section = block.section
        buffer_path = block.outline_path
        buffer_origin = ()

    def note(block: Block):
        """이 블록의 글자가 지금 버퍼에 들어갔다 — 출처를 잇는다.

        `_split_long_text` 가 한 블록을 여러 조각으로 내면 여기가 여러 번 불리므로
        **중복을 없앤다.** 값이 해시 가능하다고 가정하지 않는다(벤더 경로가 무엇을
        넣을지는 이 파일의 소관이 아니다) — 동일성으로만 본다.
        """
        nonlocal buffer_origin
        buffer_origin = _extend_origin(buffer_origin, block.origin)

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
                note(block)
            else:
                if not buffer:
                    # 옛 코드는 `not chunks and not buffer_section` 으로 첫 청크에서만
                    # 섹션을 잡았다 — 두 번째 청크부터 `i_section` 이 앞 청크 값에
                    # 얼어붙어, 섹션이 여럿인 문서에서 출처가 틀리게 실렸다.
                    start(block)
                buffer = candidate
                note(block)

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
                    origin=_extend_origin(previous.origin, chunk.origin),
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

    **출처는 다음 청크로 넘긴다.** 글자는 머리말로 살아남는데 출처만 버리면, 벤더
    경로에서 그 제목 항목의 bbox·이미지가 어느 청크에도 안 붙는다 — 화면에는 제목이
    보이는데 그 자리를 짚어 주는 값이 없는 상태가 되고, 오류로는 드러나지 않는다.
    """
    kept: list = []
    carried: tuple = ()
    for index, chunk in enumerate(chunks):
        following = chunks[index + 1] if index + 1 < len(chunks) else None
        if (
            chunk.kind == "paragraph"
            and chunk.outline_path
            and chunk.text == chunk.outline_path[-1]
            and following is not None
            and following.outline_path[: len(chunk.outline_path)] == chunk.outline_path
        ):
            carried = _extend_origin(carried, chunk.origin)
            continue
        if carried:
            chunk = replace(chunk, origin=_extend_origin(carried, chunk.origin))
            carried = ()
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
# 않기 때문이다. 그래서 `i_section`/`n_section`/`source_kind`/`i_table_part` 를 추가로 싣는다.
#
# ## 페이지 자리를 **비워 두면 GenOS 화면에 안 뜬다** (2026-09-03)
#
# 그전에는 페이지 관련 다섯 필드와 `chunk_bboxes`·`media_files` 를 전부 `None` 으로 뒀다
# ("틀린 페이지 번호는 없는 것보다 나쁘다"). 그런데 적재 결과 화면은 **벤더 레코드 모양을
# 전제로** 청크를 페이지로 묶어 그린다 — 그 값이 비면 hwpx 로 넣은 문서만 목록에 뜨지
# 않아서, 확인하려면 사람이 API 를 직접 쳐야 했다. 오류가 아니라 **빈 화면**이라 어디에도
# 안 드러난다.
#
# 지금은 **구역(section)을 페이지 자리에 넣는다.** 지어내는 것과 다르다:
#
# - 값의 출처를 `page_basis="section"` 이 말한다. 렌더링된 페이지라고 주장하지 않는다.
# - 구역은 hwpx 가 실제로 갖는 경계이고(`i_section` 과 같은 값 + 1), 청크 묶음이
#   화면에서도 문서 구조와 일치한다. 0 이나 1 로 뭉개면 그 성질이 사라진다.
# - `chunk_bboxes`·`media_files` 는 **벤더가 좌표·미디어를 못 찾았을 때 내는 값**과 같은
#   것을 쓴다(`"[]"`·`""`). 새 규약이 아니라 벤더의 빈 값이다.
#
# 되돌리려면 `_page_fields` 하나만 보면 된다. `i_section`/`n_section` 은 그대로 남아
# 있으므로 이 매핑이 사라져도 구역 정보는 잃지 않는다.
# ---------------------------------------------------------------------------


# 페이지 숫자의 출처. 렌더링된 페이지가 아니라 hwpx 구역이라는 뜻이고, 이 문자열이
# 레코드에 실려야 나중에 "페이지 수가 실물과 다르다" 를 추적할 수 있다.
_PAGE_BASIS_SECTION = "section"


def _counts(text: str) -> dict:
    """`n_char`/`n_word`/`n_line`. 지능형 전처리기의 `GenOSVectorMeta` 와 같은 이름·같은
    세는 법 — 검색 쪽이 그 이름으로 읽으므로 어긋나면 안 된다."""
    return {
        "n_char": len(text),
        "n_word": len(text.split()),
        "n_line": len(text.splitlines()) or 1,
    }


# 레코드 필드의 **타입 계약**. Weaviate 는 프로퍼티 타입을 처음 본 값으로 굳히므로,
# 같은 키가 문서마다 다른 타입으로 나가면 **나중 문서가 통째로 안 들어간다.** 그 실패는
# 적재 단계에서 `not a string, but float64` 처럼 뜨는데 — Go 가 JSON 숫자를 전부
# `float64` 로 읽는다 — **어느 레코드의 어느 키인지가 메시지에 없다.** 그래서 여기서
# 먼저 잡고 키 이름을 말한다.
#
# 페이지 관련 다섯은 2026-09-03 부터 **구역으로 채운다** — `None` 을 허용하지 않는다.
# 비워 두면 GenOS 적재 결과 화면이 청크를 묶지 못해 **아무것도 안 뜨는데 오류도 없다**
# (`_page_fields` 주석). 출처는 `page_basis` 가 말한다.
_RECORD_TYPES = {
    "text": (str,),
    "file_name": (str,),
    "file_path": (str,),
    "reg_date": (str,),
    "source_kind": (str,),
    "table_title": (str,),
    "outline_title": (str,),
    "n_char": (int,),
    "n_word": (int,),
    "n_line": (int,),
    "i_chunk_on_doc": (int,),
    "n_chunk_of_doc": (int,),
    "i_section": (int,),
    "n_section": (int,),
    "i_table_part": (int,),
    "n_table_part": (int,),
    "i_page": (int,),
    "e_page": (int,),
    "n_page": (int,),
    "i_chunk_on_page": (int,),
    "n_chunk_of_page": (int,),
    "chunk_bboxes": (str,),
    "media_files": (str,),
    "page_basis": (str,),
    "outline_path": (list,),
}



def _check_record_types(records: list) -> None:
    """우리가 만든 필드의 타입이 계약과 같은지. 어긋나면 **키 이름을 말하고 세운다.**

    §F 규약대로 오류 객체를 청크 목록에 섞지 않고 예외를 던진다 — 여기까지 오면
    `to_records` 의 불변식이 깨진 것이라 재적재로 풀리지 않는다.

    **`extra_metadata` 는 세우지 않는다.** 그쪽은 등록 화면 입력이고, 이 모듈의 규약이
    "파라미터 입력 실수가 전체 재적재를 막지 않는다" 이기 때문이다. 대신 **키 이름과
    타입 이름을 로그로 낸다** — 값은 남기지 않는다(§3.8). 적재가 그 값 때문에 거절되면
    컨테이너 로그에 어느 키인지가 남아 있어야 손을 쓸 수 있다.
    """
    reported: set = set()
    for index, record in enumerate(records):
        for key, value in record.items():
            allowed = _RECORD_TYPES.get(key)
            if allowed is None:
                # `extra_metadata` 에서 온 키. **문자열과 `None` 만 조용히 통과시킨다** —
                # 숫자·불리언은 컬렉션이 그 프로퍼티를 `text` 로 잡고 있으면 거절되고
                # (`not a string, but float64`), 그 메시지에는 키 이름이 없다.
                if value is not None and not isinstance(value, str):
                    if key not in reported:
                        reported.add(key)
                        _log_warning(
                            "extra_metadata value is not a string - the vector DB will "
                            "reject it if the property is text (key=%s type=%s)"
                            % (key, type(value).__name__),
                            event="preprocess_extra_metadata_type",
                        )
                continue
            # `bool` 은 `int` 의 하위형이라 그냥 두면 int 자리를 통과한다.
            if isinstance(value, bool) and bool not in allowed:
                raise HwpxParseError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=bool (레코드 %d)" % (key, index)
                )
            if not isinstance(value, allowed):
                raise HwpxParseError(
                    "레코드 필드 타입이 계약과 다릅니다(내부 오류): "
                    "%s=%s (레코드 %d)" % (key, type(value).__name__, index)
                )


def _page_fields(chunks: list, section_count: int) -> list:
    """청크별 페이지 필드. **구역(section)을 페이지 자리에 넣는다** (2026-09-03).

    Args:
        chunks: `chunk_blocks` 산출물.
        section_count: 문서의 구역 수. 0 이면 청크에서 센다.

    Returns:
        청크와 같은 길이의 dict 목록 —
        `i_page`·`e_page`·`n_page`·`i_chunk_on_page`·`n_chunk_of_page`·`page_basis`.

    hwpx 는 흐름 문서라 렌더링 전에는 페이지가 없다. 그래도 이 필드를 채우는 이유는
    **적재 결과 화면이 이 값으로 청크를 묶어 그리기 때문**이다 — 비워 두면 hwpx 로 넣은
    문서만 화면에 안 뜬다(오류가 아니라 빈 목록이라 아무 데도 안 드러난다).

    - **1-based** 다. 벤더 pdf 경로의 `page_no` 와 같은 기준이라 화면이 "1페이지" 로
      그린다. 0 을 섞으면 같은 컬렉션에서 두 모양이 된다.
    - `i_chunk_on_page` 는 **0-based** 다 — 벤더 `chunk_index_on_page` 가 0 부터 센다.
    - `page_basis` 가 "이 숫자는 렌더링된 페이지가 아니라 구역이다" 를 말한다. 이 값이
      없으면 나중에 누가 페이지 수로 분량을 재고 실물과 안 맞아 원인을 못 찾는다.
    """
    sections = [max(0, int(getattr(chunk, "section", 0) or 0)) for chunk in chunks]
    per_section: dict = {}
    for section in sections:
        per_section[section] = per_section.get(section, 0) + 1

    # 구역 수는 파서가 준 값이 정본이다. 청크에 더 큰 번호가 있으면(부분 처리 등) 그쪽을
    # 쓴다 — `i_page > n_page` 인 레코드는 화면에서 페이지 밖을 가리킨다.
    total_pages = max([section_count] + [value + 1 for value in sections] + [1])

    seen: dict = {}
    fields = []
    for section in sections:
        order = seen.get(section, 0)
        seen[section] = order + 1
        fields.append({
            "i_page": section + 1,
            "e_page": section + 1,
            "n_page": total_pages,
            "i_chunk_on_page": order,
            "n_chunk_of_page": per_section[section],
            "page_basis": _PAGE_BASIS_SECTION,
        })
    return fields


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
    pages = _page_fields(chunks, section_count)

    for index, chunk in enumerate(chunks):
        record = {
            "text": chunk.text,
            **_counts(chunk.text),
            # 페이지 자리에는 **구역**이 들어간다 — 값의 출처는 `page_basis` 가 말한다.
            # 비워 두면 GenOS 적재 결과 화면에 이 문서가 뜨지 않는다(위 docstring).
            **pages[index],
            "i_chunk_on_doc": index,
            "n_chunk_of_doc": total,
            "reg_date": stamp,
            # 벤더가 좌표·미디어를 못 찾았을 때 내는 값과 **같은 것**을 쓴다
            # (`GenOSVectorMetaBuilder`: 빈 bbox 는 `"[]"`, 미디어 없음은 `""`).
            # `None` 으로 두면 화면이 그 필드를 읽다 멈춘다.
            "chunk_bboxes": "[]",
            "media_files": "",
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
        _debug_dump(file_path, records)  # [임시 · 확인용] 파일 맨 아래 블록과 함께 지운다
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

        # 타입이 어긋난 채 내보내면 실패가 **Weaviate 에서** 나고, 그 메시지에는 어느
        # 키인지가 없다. 여기서 먼저 이름을 말한다.
        _check_record_types(records)

        return records


# ===========================================================================
# [임시 · 확인용] 컨테이너 로그 덤프 — 확인이 끝나면 **이 블록과 호출 두 줄**을 지운다
# ===========================================================================
#
# 지울 자리는 셋이다(전부 `_DEBUG_TAG` 로 찾을 수 있다):
#
#   1. 이 블록
#   2. `DocumentProcessor.__call__` 안의 `_debug_dump(...)` 한 줄  (hwpx 경로)
#   3. `router_template.py` 의 `_run_vendor` 안의 `_debug_dump(...)` 한 줄  (벤더 경로)
#
# **`_log_info` 가 아니라 `print` 다.** 플랫폼 로거 설정에 관계없이 컨테이너 stdout 에
# 그대로 뜨는 것이 목적이고, 이 저장소의 로깅 화이트리스트(`_ALLOWED_LOG_FIELDS`)는
# 문서 내용을 통과시키지 않아 `_log_info` 로는 본문 200자를 낼 수 없다.
#
# **문서 본문이 컨테이너 로그에 남는다** — 규약(§3.8)이 금지하는 것이고, 확인용으로
# 일부러 넣은 것이다. 운영에 그대로 두지 말 것.
#
# 벤더 경로에서는 라우터가 부른다. **hwpx 경로를 라우터에서 또 부르지 않는다** — 라우터가
# hwpx 를 처리할 때 아래 `__call__` 을 지나므로 양쪽에서 부르면 한 문서가 두 번 찍힌다.

_DEBUG_TAG = "[GENON-DEBUG]"
_DEBUG_DUMP_CHARS = 200


def _debug_dump(file_path: str, records: Any, *, engine: str = "hwpx") -> None:
    """파일명 · 청크 개수 · 첫 청크 앞 200자를 stdout 에 찍는다.

    **무슨 일이 있어도 적재를 막지 않는다.** 확인용 코드가 문서 적재를 실패시키면
    안 되므로 통째로 감싼다(레코드 모양이 기대와 달라도 그냥 지나간다).
    """
    try:
        rows = records if isinstance(records, list) else []
        head = rows[0] if rows and isinstance(rows[0], dict) else {}
        name = str(head.get("file_name") or "") or os.path.basename(str(file_path or ""))
        first = str(head.get("text") or "")
        print(
            f"{_DEBUG_TAG} engine={engine} file={name} chunks={len(rows)}",
            flush=True,
        )
        print(f"{_DEBUG_TAG} first{_DEBUG_DUMP_CHARS}>>>", flush=True)
        print(first[:_DEBUG_DUMP_CHARS], flush=True)
        print(f"{_DEBUG_TAG} <<<", flush=True)
    except Exception:  # noqa: BLE001 - 확인용 출력이 적재를 실패시키면 안 된다
        pass


# ===========================================================================
# PART 3 — 라우터 (우리 코드). 진입점 `DocumentProcessor` 가 여기 있다
# ===========================================================================
class FinalPreprocessorError(Exception):
    """라우터 자신이 내는 오류.

    hwpx 파싱 실패는 `HwpxParseError` 로, 벤더 경로의 실패는 그쪽 예외 그대로 올린다 —
    여기서 한 종류로 뭉치면 **어느 경로가 죽었는지가 로그에서 사라진다.**
    """


_FP_HWPX = "hwpx"
_FP_ATTACH = "attach"
_FP_ENGINES = (_FP_HWPX, _FP_ATTACH)

_FP_ENGINE_AUTO = "auto"
_FP_ENGINE_NATIVE = "native"
_FP_HWPX_ENGINES = (_FP_ENGINE_AUTO, _FP_ENGINE_NATIVE, _FP_ATTACH)

_FP_HWPX_EXTENSIONS = (".hwpx",)
_FP_ZIP_MAGIC = b"PK\x03\x04"
_FP_HWPX_MIMETYPE = b"application/hwp+zip"
_FP_SECTION_PREFIX = "Contents/section"

# ---------------------------------------------------------------------------
# 확장자 → 엔진.
#
# **2026-09-01 에 지능형이 빠지면서 이 표가 한 줄이 됐다.** 그전에는 pdf·ppt·엑셀·
# 이미지가 지능형으로 갔다(docling layout + TableFormer + OCR). 그 경로가 실환경에서
# 동작하지 않아 걷어냈고, 지금은 hwpx 가 아닌 것이 **전부 첨부용**으로 간다.
#
# **대가를 알고 있어야 한다**: 첨부용 pdf 경로는 `PyMuPDFLoader` 평문 + 문자 수 분할
# 이라 **표 구조가 남지 않는다.** 오류는 나지 않고 적재도 되므로, 그 사실은 "표를
# 물어봤는데 답이 이상하다" 로만 드러난다. 지능형이 고쳐지면 되살릴 자리는
# `build_final_preprocessor.py` 와 이 표다.
#
# 여기 없는 확장자는 `_FP_DEFAULT_ENGINE` 으로 간다.
# ---------------------------------------------------------------------------
_FP_ROUTES = {
    # 우리 파서 — 표 병합·조문 위계를 지킨다
    ".hwpx": _FP_HWPX,
}
# 나머지 전부. 첨부용 `__call__` 이 확장자별로 갈라 받는다 — `.hwp`·`.hml` 은 GenosHwp
# SDK, `.docx` 는 GenosMsWord 네이티브, 오디오는 Whisper STT, `.csv`·`.xlsx` 는
# TabularLoader, `.ppt(x)` 는 PDF 변환 후 docling, 나머지는 langchain 로더다.
_FP_DEFAULT_ENGINE = _FP_ATTACH

# 라우터가 자기 몫으로 받는 값. 벤더 처리기로 **넘기기 전에 뺀다** — 그대로 넘기면
# 벤더가 `kwargs: {...}` 로 통째로 로그에 찍고, 언젠가 같은 이름을 쓰면 조용히 겹친다.
_FP_ROUTER_KWARGS = (
    "hwpx_engine",
    "route_overrides",
    "align_vector_schema",
    "attachment_config_path",
)

_FP_CONFIG_ENV = {_FP_ATTACH: "GENOS_ATTACHMENT_CONFIG_PATH"}
_FP_CONFIG_BASENAMES = {
    _FP_ATTACH: ("attachment_processor_config.yaml", "attach_processor_config.yaml"),
}
_FP_CONFIG_KWARG = {_FP_ATTACH: "attachment_config_path"}

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

    **2026-09-01 이전에는 여기가 두 갈래였다** — 지능형이 함께 있던 시절 첨부용은 본문이
    같아 지운 정의 13개를 지능형 판본에서 빌려 썼고, 그래서 지능형 절반이 없으면 첨부용
    코드가 `NameError` 로 죽었다. 지금은 첨부용이 자기 정의를 전부 들고 있어 그 얽힘이
    없다 — 첨부용의 가부는 첨부용 적재 결과 하나로 정해진다.
    """
    if engine == _FP_ATTACH:
        return _FP_ATTACH_IMPORT_ERROR
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
    if hwpx_engine == _FP_ATTACH:
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


# ---------------------------------------------------------------------------
# 조/항/호 위계를 **벤더 경로(pdf·docx)에도** 태운다
#
# ## 원본 문서 모양이 **둘**이다 (2026-09-01)
#
# 지능형이 있던 시절에는 pdf 도 `DoclingDocument` 였다. 지능형을 걷어내면서 pdf 가
# 첨부용으로 갔고, 그쪽 최상위 경로는 **langchain `Document` 목록**을 주고받는다
# (`attach_processor.py:2254-2296`, `PyMuPDFLoader` 산출물). 그래서 어댑터가 둘이다:
#
# | 자리 | 들어오는 것 | 나가는 것 | 어댑터 |
# |---|---|---|---|
# | 첨부용 최상위 (pdf·이미지·txt·md) | `list[Document]` | `list[Document]` | `_fp_langchain_blocks` |
# | 첨부용 `docx_processor` | `DoclingDocument` | dict 또는 `DocChunk` | `_fp_docling_blocks` |
#
# **가운데(위계 판정·조 경계 청킹)는 하나다.** `Block` 으로 옮기고 나면 어느 쪽에서
# 왔는지 알 필요가 없다 — 갈라지는 것은 입구의 어댑터와 출구의 payload 조립뿐이다.
#
# ## 왜 여기서 되는가
#
# 위계 층은 hwpx 를 모른다 — `annotate_outline`·`chunk_blocks` 는 `Block(kind, text,
# section)` 만 본다. hwpx 전용인 것은 `parse()` 하나다. 그래서 **벤더 문서를 블록으로
# 옮기기만 하면** 조 경계 청킹·`제2장 총칙 > 제5조(목적)` 머리말·표 분할이 그대로 돈다.
#
# ## 어디에 끼우나 — 벤더의 **청커만** 갈아 끼운다
#
# 두 벤더가 같은 3단이다: `load_documents() → split_documents() → compose_vectors()`.
# 우리는 가운데만 바꾼다. `compose_vectors` 를 그대로 두는 것이 요점이다 — 그쪽이
# bbox·이미지 업로드·**민감정보 마스킹(#315)**·페이지 카운트를 붙인다. 우회하면 그
# 값들이 조용히 사라지고, 레코드는 멀쩡해 보인다.
#
# 그래서 청크가 **어느 원본 항목에서 나왔는지**를 잃으면 안 된다. `Block.origin` /
# `Chunk.origin` 이 그 값을 실어 나른다(hwpx 경로에서는 언제나 비어 있다).
#
# ## 언제 켜지나
#
# `outline_mode` 하나로 hwpx 와 같이 움직인다. 기본 `auto` 는 `제N조` 표기를 **2개 이상**
# 세었을 때만 켜므로, **조문 문서가 아닌 pdf·docx 의 산출물은 벤더 청커 그대로다.**
# 일반 문서에 사다리를 걸면 `1.`·`가.` 목록이 전부 제목으로 승격돼 지금보다 나빠진다.
#
# 판정은 **kwargs 와 문서 내용만** 본다. 처리기 인스턴스는 요청 사이에 공유되므로,
# "이번 요청에는 켜라" 를 인스턴스 속성에 적으면 동시 요청끼리 서로의 설정을 본다.
#
# ## 되짚을 수 없으면 **벤더 청커로 돌아간다**
#
# 어댑터가 실패하든 출처가 비든, 이 경로는 예외를 올리지 않는다. 조문 위계는 있으면
# 좋은 것이고 적재는 되어야 하는 것이다 — 여기서 죽으면 그 문서가 검색에서 통째로
# 사라진다(hwpx 폴백 규약과 같다). 다만 **조용히 넘기지 않는다.**
# ---------------------------------------------------------------------------

# 벤더 표는 머리행 표시가 있다(`column_header`). 없으면 hwpx 와 같은 최소 가정 —
# 첫 행을 머리행으로 본다. 조각마다 머리행을 반복하는 것이 표 분할의 요점인데,
# 표시가 없으면 그 반복이 데이터 행으로 읽힌다.
_FP_TABLE_OPEN = "<table><tbody>"
_FP_TABLE_CLOSE = "</tbody></table>"

# 어느 어댑터를 태울지. **처리기마다 고정**이고 요청마다 바뀌지 않는다 — 설치할 때 정한다.
_FP_SRC_DOCLING = "docling"
_FP_SRC_LANGCHAIN = "langchain"


class _FPPageCounts(dict):
    """`compose_vectors` 가 `counts[page]` 로 바로 읽는다 — 없는 키에서 죽지 않는다.

    벤더는 `defaultdict(int)` 를 쓰지만 그 이름은 벤더 조각 **안**에서 import 되므로
    (그 조각은 실패할 수 있다) 라우터가 기댈 수 없다. 키가 하나라도 어긋나면
    `KeyError` 로 적재 전체가 죽는데, 그건 우리가 만들어 낸 실패다.
    """

    def __missing__(self, key):
        return 0


def _fp_table_html(item) -> str:
    """docling `TableItem` → **한 줄 HTML 표**. 못 만들면 빈 문자열.

    형태는 hwpx `_table_html` 과 같다(`<table><tbody><tr><th>…`). 마크다운으로 내지
    않는 이유도 같다 — 검색 결과가 프롬프트로 조립될 때 개행이 뭉개지면 마크다운 표는
    **행 경계가 개행뿐**이라 표가 아니게 된다.

    **덮인 자리에는 칸을 내지 않는다.** 내면 그 행만 열이 하나 늘어난다.
    """
    data = getattr(item, "data", None)
    cells = list(getattr(data, "table_cells", None) or ())
    if not cells:
        return ""

    anchors: dict = {}
    occupied: set = set()
    header_rows: set = set()
    height = 0
    width = 0
    for cell in cells:
        row = _fp_cell_int(cell, "start_row_offset_idx", 0)
        col = _fp_cell_int(cell, "start_col_offset_idx", 0)
        row_span = max(1, _fp_cell_int(cell, "end_row_offset_idx", row + 1) - row)
        col_span = max(1, _fp_cell_int(cell, "end_col_offset_idx", col + 1) - col)
        if (row, col) in anchors:
            # 같은 앵커가 두 번 오면 **뒤엣것을 버린다.** 격자를 늘리면 없던 열이 생긴다.
            continue
        text = getattr(cell, "text", "")
        anchors[(row, col)] = (text if isinstance(text, str) else "", row_span, col_span)
        if getattr(cell, "column_header", False):
            header_rows.add(row)
        for d_row in range(row_span):
            for d_col in range(col_span):
                occupied.add((row + d_row, col + d_col))
        height = max(height, row + row_span)
        width = max(width, col + col_span)

    if not width or not height:
        return ""
    if not header_rows:
        header_rows = {0}
    covered = occupied - set(anchors)

    lines = [_FP_TABLE_OPEN]
    for row in range(height):
        tag = "th" if row in header_rows else "td"
        rendered = []
        for col in range(width):
            if (row, col) in covered:
                continue
            anchor = anchors.get((row, col))
            if anchor is None:
                rendered.append(f"<{tag}></{tag}>")  # 빈 칸도 자리를 지켜야 한다
                continue
            text, row_span, col_span = anchor
            attrs = ""
            if row_span > 1:
                attrs += f' rowspan="{row_span}"'
            if col_span > 1:
                attrs += f' colspan="{col_span}"'
            rendered.append(f"<{tag}{attrs}>{_fp_cell_html(text)}</{tag}>")
        lines.append("<tr>" + "".join(rendered) + "</tr>")
    lines.append(_FP_TABLE_CLOSE)
    return "".join(lines)


def _fp_cell_int(cell, name: str, default: int) -> int:
    value = getattr(cell, name, None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fp_cell_html(text: str) -> str:
    """셀 안 개행은 `<br>` 로. 개행을 그대로 두면 표가 한 줄이라는 규약이 깨진다."""
    escaped = _html.escape(text.strip(), quote=False)
    for raw in ("\r\n", "\r", "\n"):
        escaped = escaped.replace(raw, _CELL_LINE_BREAK)
    return escaped


def _fp_docling_blocks(document) -> list:
    """`DoclingDocument` → `Block` 목록. `origin` 에 **원본 항목 그 자체**를 담는다.

    ## 구역(`section`)은 전부 0 이다

    페이지를 구역으로 쓰면 안 된다 — `chunk_blocks` 가 구역이 바뀔 때 끊으므로 **페이지를
    걸친 조가 반으로 갈린다.** 조가 검색 단위라는 이 기능의 전제와 정면으로 어긋난다.

    ## 글자 없는 항목(그림 등)은 버리지 않고 **다음 블록에 얹는다**

    그 항목을 그냥 빼면 어느 청크에도 안 실리고, 벤더가 `doc_items` 로 붙이는
    **이미지 업로드가 통째로 빠진다.** 오류는 나지 않는다 — 그림이 없는 문서로 보일 뿐이다.
    """
    blocks: list = []
    pending: list = []

    def push(kind: str, text: str, item) -> None:
        blocks.append(
            Block(kind=kind, text=text, section=0, origin=tuple(pending) + (item,))
        )
        pending.clear()

    for entry in document.iterate_items():
        item = entry[0] if isinstance(entry, tuple) else entry
        if getattr(getattr(item, "data", None), "table_cells", None) is not None:
            html = _fp_table_html(item)
            if html:
                push("table", html, item)
            else:
                pending.append(item)
            continue
        text = getattr(item, "text", "")
        text = text.strip() if isinstance(text, str) else ""
        if text:
            push("paragraph", text, item)
        else:
            pending.append(item)

    if pending and blocks:
        # 문서 끝에 남은 것은 앞으로 얹는다 — 뒤에 실을 블록이 없다.
        blocks[-1] = replace(
            blocks[-1], origin=_extend_origin(blocks[-1].origin, tuple(pending))
        )
    return blocks


def _fp_langchain_blocks(documents) -> list:
    """langchain `Document` 목록 → `Block` 목록. `origin` 에 원본 Document 를 담는다.

    첨부용 최상위 경로(pdf·이미지·txt·md)가 이 모양이다. `PyMuPDFLoader` 는 **페이지마다
    Document 하나**를 내고 본문은 개행이 든 평문이다 — 표 격자는 이 단계에 이미 없다
    (그것이 첨부용 pdf 의 한계이고 위계 청킹이 되돌릴 수 있는 것이 아니다).

    ## 줄 단위로 가른다

    `_match_statute` 가 `제5조(목적)`·`①`·`1.` 을 **줄 머리에서** 읽는다. 페이지를
    통째로 한 블록에 넣으면 조 표기가 문장 가운데 파묻혀 위계가 하나도 안 잡히고,
    그러면 이 경로는 벤더 청커를 이유 없이 갈아치우는 것이 된다.

    ## 구역(`section`)은 전부 0 이다

    페이지를 구역으로 쓰면 `chunk_blocks` 가 페이지 경계에서 끊어 **한 조가 반으로
    갈린다.** 조가 검색 단위라는 이 기능의 전제와 정면으로 어긋난다.
    """
    blocks: list = []
    pending: list = []
    for document in documents:
        text = getattr(document, "page_content", "")
        lines = [line.strip() for line in text.splitlines()] if isinstance(text, str) else []
        lines = [line for line in lines if line]
        if not lines:
            # 글자 없는 페이지도 버리지 않는다 — 그 Document 의 metadata(페이지 번호)가
            # 어느 청크엔가 실려야 `compose_vectors` 의 페이지 집계가 어긋나지 않는다.
            pending.append(document)
            continue
        for line in lines:
            blocks.append(
                Block(
                    kind="paragraph",
                    text=line,
                    section=0,
                    origin=tuple(pending) + (document,),
                )
            )
            pending = []
    if pending and blocks:
        blocks[-1] = replace(
            blocks[-1], origin=_extend_origin(blocks[-1].origin, tuple(pending))
        )
    return blocks


def _fp_langchain_payload(chunks: list):
    """첨부용 최상위 경로가 내는 모양 — langchain `Document` 목록. 못 만들면 `None`.

    **클래스를 이름으로 찾지 않고 원본에서 가져온다**(`type(source)`). 이 라우터는 벤더
    가드 **밖**이라 `Document` 라는 전역이 있다는 보장이 없고, 있어도 그것이 이 문서를
    만든 로더의 클래스라는 보장이 없다.

    metadata 는 **첫 원본의 사본**이다. 벤더가 `dict(doc.metadata)` 로 복사하는 것과
    같다 — 원본을 그대로 물리면 여러 청크가 한 dict 를 공유해 뒤에서 고친 값이 앞
    청크에도 보인다.
    """
    payload = []
    for chunk in chunks:
        # 첫 원본을 쓴다 — `_fp_chunk_page` 가 페이지를 고르는 식과 같다. 여러 페이지를
        # 걸친 청크는 **시작한 페이지**에 달린다.
        source = chunk.origin[0] if chunk.origin else None
        if source is None or not hasattr(source, "metadata"):
            return None
        try:
            payload.append(type(source)(page_content=chunk.text, metadata=dict(source.metadata)))
        except Exception:  # noqa: BLE001 - 모양이 다르면 벤더 청커로 돌아간다
            return None
    return payload


def _fp_outline_chunks(document, kwargs: dict, source: str = _FP_SRC_DOCLING):
    """위계로 다시 청킹한 `Chunk` 목록. **벤더 청커를 써야 하면 `None`.**"""
    mode = _fp_choice_kwarg(
        kwargs.get("outline_mode"), _OUTLINE_AUTO, _OUTLINE_MODES, "outline_mode"
    )
    if mode == _OUTLINE_OFF:
        return None

    try:
        blocks = (
            _fp_langchain_blocks(document)
            if source == _FP_SRC_LANGCHAIN
            else _fp_docling_blocks(document)
        )
    except Exception as exc:  # noqa: BLE001 - 위계는 있으면 좋은 것이고 적재는 되어야 한다
        _log_warning(
            "outline adapter failed - using the vendor chunker",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
            error_type=type(exc).__name__,
        )
        return None
    if not blocks:
        return None

    resolved = _detect_outline_mode(blocks) if mode == _OUTLINE_AUTO else mode
    if resolved == _OUTLINE_OFF:
        return None

    annotated = annotate_outline(blocks, resolved)
    if not any(block.outline_level for block in annotated):
        # 사다리를 못 찾았다(`document` 모드가 이렇게 끝날 수 있다). 위계가 하나도 없으면
        # 우리 청커는 길이 기준만 남아 **벤더 청킹을 이유 없이 갈아치우는 것**이 된다.
        return None

    options = ChunkOptions(
        max_chars=_int_kwarg(kwargs.get("chunk_size"), _DEFAULT_MAX_CHARS, "chunk_size"),
        overlap_chars=_int_kwarg(
            kwargs.get("chunk_overlap"), _DEFAULT_OVERLAP_CHARS, "chunk_overlap"
        ),
        outline_break_level=(
            _DOC_BREAK_LEVEL if resolved == _OUTLINE_DOCUMENT else _LEVEL_ARTICLE
        ),
    )
    chunks = chunk_blocks(annotated, options)
    if not chunks:
        return None
    if any(not chunk.origin for chunk in chunks):
        # 여기까지 오면 origin 전파가 깨진 것이다. 그대로 내보내면 `compose_vectors` 가
        # `doc_items[0]` 에서 IndexError 로 죽어 **적재가 통째로 실패한다.**
        _log_warning(
            "outline chunks lost their source items - using the vendor chunker",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
        )
        return None
    return chunks


def _fp_chunk_page(items) -> int:
    """이 청크의 페이지. 벤더 `compose_vectors` 와 **같은 식으로** 고른다(첫 항목)."""
    for item in items:
        prov = getattr(item, "prov", None)
        if prov:
            return getattr(prov[0], "page_no", 0) or 0
    return 0


def _fp_recursive_payload(chunks: list) -> list:
    """첨부용 `chunker_type="recursive"` 가 내는 모양 — 평범한 dict."""
    return [
        {
            "text": chunk.text,
            "page_no": _fp_chunk_page(chunk.origin),
            "doc_items": list(chunk.origin),
        }
        for chunk in chunks
    ]


def _fp_docchunk_payload(chunks: list, document):
    """`DocChunk` 목록. docling 이 없으면 `None`(벤더 청커로 돌아간다).

    **`headings` 를 채우지 않는다.** 두 벤더의 `compose_vectors` 가 그 값을 본문 앞에
    다시 붙이는데, 우리 청크 본문에는 조문 머리말이 **이미 들어 있다** — 채우면 같은
    제목이 두 번 실린다.
    """
    doc_chunk = globals().get("DocChunk")
    doc_meta = globals().get("DocMeta")
    if doc_chunk is None or doc_meta is None:
        _log_warning(
            "docling chunk types are unavailable - using the vendor chunker",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
        )
        return None

    origin = getattr(document, "origin", None)
    payload = []
    for chunk in chunks:
        items = list(chunk.origin)
        try:
            meta = doc_meta(doc_items=items, origin=origin)
        except Exception:  # noqa: BLE001 - 릴리스마다 선택 필드가 다르다
            meta = doc_meta(doc_items=items)
        payload.append(doc_chunk(text=chunk.text, meta=meta))
    return payload


def _fp_count_pages(owner, payload: list, reset: bool) -> None:
    """`compose_vectors` 가 읽는 페이지별 청크 수. **벤더의 초기화 습관을 그대로 따른다.**

    첨부용은 호출마다 새로 만들고 지능형은 생성자에서 한 번만 만든다(요청 사이에
    누적된다). 여기서 임의로 맞추면 우리가 안 건드린 경로와 값이 달라진다 — 이 코드가
    바꾸는 것은 **청크 경계뿐**이어야 한다.
    """
    if reset or not isinstance(getattr(owner, "page_chunk_counts", None), _FPPageCounts):
        owner.page_chunk_counts = _FPPageCounts(
            () if reset else (getattr(owner, "page_chunk_counts", None) or {})
        )
    counts = owner.page_chunk_counts
    for entry in payload:
        if isinstance(entry, dict):
            page = entry["page_no"]
        elif hasattr(entry, "metadata"):
            # langchain `Document` — 벤더가 `chunk.metadata.get('page', 0)` 로 읽는
            # 그 값이다(`attach_processor.py:2294`).
            page = entry.metadata.get("page", 0)
        else:
            page = _fp_chunk_page(entry.meta.doc_items)
        counts[page] = counts[page] + 1


def _fp_install_outline_chunker(owner, label: str, *, reset_page_counts: bool,
                                honor_chunker_type: bool,
                                source: str = _FP_SRC_DOCLING) -> None:
    """벤더 처리기의 `split_documents` 를 위계 청커로 감싼다(원본은 폴백으로 남는다).

    Args:
        honor_chunker_type: `DocxProcessor` 는 `chunker_type` 에 따라 청크 모양이
            **dict 이거나 `DocChunk`** 이고 `compose_vectors` 가 같은 분기로 읽는다.
        source: 그 `split_documents` 가 **무엇을 받는가**. `_FP_SRC_LANGCHAIN` 이면
            `list[Document]` 를 받고 같은 모양으로 돌려줘야 한다 — 첨부용 최상위
            경로(pdf·이미지·txt·md)가 그쪽이다.
    """
    if owner is None or getattr(owner, "_fp_outline_installed", False):
        return
    original = getattr(owner, "split_documents", None)
    if original is None:
        # 벤더가 그 이름을 안 쓰면 걸 자리가 없다. **적재를 막지 않는다** — 위계가 안
        # 붙을 뿐이고, 그 사실은 로그에 남는다(조용히 넘기면 왜 안 붙는지 알 수 없다).
        _log_warning(
            "vendor processor has no split_documents - outline chunking is off",
            event="final_preprocess_outline_skipped",
            error_code="05-00020003",
            status=label,
        )
        return

    def split_documents(document, **kwargs):
        chunks = _fp_outline_chunks(document, kwargs, source)
        if chunks is None:
            return original(document, **kwargs)
        if source == _FP_SRC_LANGCHAIN:
            payload = _fp_langchain_payload(chunks)
        elif honor_chunker_type and kwargs.get("chunker_type", "recursive") == "recursive":
            payload = _fp_recursive_payload(chunks)
        else:
            payload = _fp_docchunk_payload(chunks, document)
        if not payload:
            return original(document, **kwargs)
        _fp_count_pages(owner, payload, reset=reset_page_counts)
        _log_info(
            "statute outline chunking applied",
            event="final_preprocess_outline",
            status=label,
            item_count=len(payload),
        )
        return payload

    owner.split_documents = split_documents
    owner._fp_outline_installed = True


def _fp_enable_outline(processor) -> None:
    """만들어진 첨부용 처리기에 위계 청커를 건다 — **pdf 와 docx 두 자리다.**

    ## pdf 는 최상위 `split_documents` 를 지난다

    첨부용 `__call__` 은 확장자로 갈라 `.docx` 는 `docx_processor` 로, `.hwp` 계열은
    `hwp_processor` 로 보내고 **나머지(pdf·이미지·txt·md·json)는 자기 안에서**
    `load_documents → split_documents → compose_vectors` 를 돈다
    (`attach_processor.py:2544-2552`). 그래서 pdf 에 위계를 걸 자리가 최상위다.

    지능형이 있던 시절 pdf 는 `DoclingDocument` 였고 지금은 langchain `Document` 목록
    이라, **어댑터만 갈아 끼운다**(`source=_FP_SRC_LANGCHAIN`). 조 경계 청킹·머리말은
    같은 코드가 그대로 돈다.

    ## 최상위에 걸면 pdf 말고도 몇 갈래가 함께 지난다

    이미지·txt·md·json, 그리고 hwp/ppt 가 실패해 PDF 변환으로 폴백한 경로가 같은
    `split_documents` 를 쓴다. **`outline_mode="auto"` 가 `제N조` 를 2개 이상 세었을
    때만 켜지므로** 조문 문서가 아닌 그 갈래들은 벤더 청커 그대로다. 지능형에 걸 때와
    같은 근거이고, `statute` 를 명시하면 전부에 걸린다(그 선택은 등록자가 한 것이다).

    ## `hwp_processor` 에는 걸지 않는다

    요구 범위가 pdf·docx 다 — 닿는 자리를 넓히면 검증하지 않은 경로의 청킹까지 바뀐다.
    넣으려면 같은 줄을 하나 더 걸면 된다(그쪽도 `DoclingDocument` 를 받고
    `chunker_type` 분기가 있다).
    """
    _fp_install_outline_chunker(
        processor,
        "pdf",
        # 첨부용 최상위 `page_chunk_counts` 는 생성자에서 한 번만 만들어져 요청 사이에
        # 누적된다(`attach_processor.py:1979`). 여기서 임의로 비우면 우리가 안 건드린
        # 경로와 값이 달라진다.
        reset_page_counts=False,
        honor_chunker_type=False,
        source=_FP_SRC_LANGCHAIN,
    )
    _fp_install_outline_chunker(
        getattr(processor, "docx_processor", None),
        "docx",
        reset_page_counts=True,
        honor_chunker_type=True,
    )


def _fp_resolve_config_path(engine: str, explicit):
    """벤더 설정 yaml 을 찾는다. 못 찾으면 `None`(벤더 기본 해석에 맡긴다).

    ## 첨부용도 yaml 을 쓴다 — 지능형 잔재가 아니다 (2026-09-01 정정)

    `AttachDocumentProcessor.__init__` 이 `_resolve_default_attachment_config_path()` →
    `_load_config()` 를 타고, 그 값에서 guardrail·whisper·tokenizer 설정을 꺼낸다
    (`attach_processor.py:1809`·`:1971`).

    **없으면 죽지 않는다.** `_load_config` 가 경고를 찍고 `{}` 를 돌려준다(`:293`) —
    그래서 "yaml 을 안 올려도 돈다" 는 사실이다. 그런데 그때 이렇게 떨어진다:

        guardrail.url            → ""      민감정보 마스킹(#315)이 **빠진다**
        guardrail.masking_enabled → False   〃
        whisper.url              → 하드코딩 IP
        chunking.tokenizer_path  → 기본값   청크 경계가 달라진다

    **그것이 이 탐색이 있는 이유다.** 벤더 resolver 는 `Path(__file__)/../resource/…` 를
    보는데 우리 합친 파일은 벤더 파일과 **다른 자리에 놓일 수 있다.** 그러면 이미지에
    yaml 이 있는데도 못 찾고 위 표대로 조용히 떨어진다 — 오류가 나지 않아 "마스킹이 왜
    안 되나" 로만 드러난다.

    옛 주석은 "**한 자리만 보고 죽지 않게**" 라고 적어 뒀는데 **그건 지능형 판본 기준**
    이었다(그쪽 `_load_config` 는 예외를 던졌다). 첨부용은 죽는 것이 아니라 **조용히
    기본값으로 간다** — 더 나쁜 실패 형태이고, 탐색을 지울 이유가 아니라 남길 이유다.

    등록 파일이 어디에 놓이는지 실물로 확인하지 못했으므로 후보를 넷 둔다.
    """
    for candidate in (explicit, os.environ.get(_FP_CONFIG_ENV[engine], "")):
        text = str(candidate or "").strip()
        if not text:
            continue
        if os.path.isfile(text):
            return text
        _log_warning("configured vendor config path does not exist - trying the next candidate",
                     event="final_preprocess_config_missing")
    vendor_resolver = globals().get("_resolve_default_attachment_config_path")
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
    """GenOS 가 실행하는 진입점 — 확장자와 **내용**을 보고 두 처리기 중 하나로 보낸다.

    `docs/GENOS_RULES.md` §F 계약 그대로다: 인자 없이 생성 가능하고, `__call__` 은
    비동기이며 `text` 키를 가진 dict 목록을 돌려주거나 예외를 던진다.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        # hwpx 처리기는 지금 만든다 — 표준 라이브러리 + lxml 뿐이라 비용이 없다.
        self._hwpx = HwpxDocumentProcessor()
        # 첨부용은 **그 엔진으로 갈 파일이 처음 들어올 때** 만든다. 생성자가 yaml 을
        # 읽고 토크나이저·docling 변환기를 올리기 때문에, 여기서 만들면 hwpx 만 넣는
        # 배포도 그 비용과 실패 가능성을 함께 진다.
        self._vendor: dict = {}
        self._vendor_lock = None
        failure = _fp_engine_error(_FP_ATTACH)
        if failure is not None:
            _log_warning(
                f"{_FP_ATTACH} preprocessing path unavailable",
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
        records = await processor(request, file_path, **_fp_forward_kwargs(kwargs))
        # [임시 · 확인용] hwpx_preprocessor.py 맨 아래 `_debug_dump` 블록과 함께 지운다.
        # **hwpx 경로에는 걸지 않는다** — 그쪽은 `HwpxDocumentProcessor.__call__` 이
        # 이미 찍으므로 여기서 또 부르면 한 문서가 두 번 나온다.
        _debug_dump(file_path, records, engine=engine)
        return records

    async def _acquire(self, engine: str, config_path_kwarg=None):
        existing = self._vendor.get(engine)
        if existing is not None:
            return existing

        failure = _fp_engine_error(engine)
        if failure is not None:
            # 빈 목록을 돌려주지 않는다 — 그러면 "내용이 없는 문서" 와 구별되지 않는다.
            raise FinalPreprocessorError(
                f"'{engine}' 전처리 경로를 사용할 수 없어 이 형식은 처리할 수 없습니다"
                f" ({type(failure).__name__}: {failure})"
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
        factory = AttachDocumentProcessor
        try:
            processor = factory(resolved) if resolved else factory()
        except Exception as exc:  # noqa: BLE001
            # 설정 파일 부재는 **재시도로 풀리지 않는 배포 문제**다. 원래 예외
            # (FileNotFoundError 등)만 올리면 어느 파일이 없다는 건지 드러나지 않아
            # 몇 번을 다시 눌러도 같은 자리에서 실패한다.
            raise FinalPreprocessorError(
                f"'{engine}' 전처리기를 초기화하지 못했습니다({type(exc).__name__}): {exc}"
            ) from exc
        # 조문 위계 청커는 **만들어진 뒤에** 건다. 생성에 실패하면 걸 대상이 없다.
        _fp_enable_outline(processor)
        return processor
