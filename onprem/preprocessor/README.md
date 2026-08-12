# onprem/preprocessor — hwpx 전용 GenOS 전처리기(area 05)

> **등록 단위는 `hwpx_preprocessor.py` 한 파일이다.** GenOS 전처리기는 MCP 와 같은
> 방식으로 소스 파일 하나를 그대로 받아 실행한다(`docs/GENOS_RULES.md` §C — "전처리기 |
> 생성·수정 화면의 환경 변수" 는 코드서빙의 Git 저장소 방식이 아니라 파일 단위 등록임을
> 가리킨다). 그래서 `hwpx_preprocessor.py` 는 **다른 파일을 import 하지 않는다**
> (표준 라이브러리 + `lxml` 만) — 등록 화면에는 이 파일 하나만 올리면 된다.

```
preprocessor/
  hwpx_preprocessor.py   ⭐ 등록 단위 — 파싱 + 청킹 + VDB 레코드 + DocumentProcessor
  __init__.py             로컬 테스트가 `import preprocessor` 로 쓰기 위한 얇은 재노출
                          (등록 시 올리는 파일이 아니다)
```

```python
from preprocessor import DocumentProcessor, chunk_blocks, parse, to_records

# 부품만 쓰고 싶을 때
document = parse(hwpx_bytes)
chunks = chunk_blocks(document.blocks)
records = to_records(chunks, file_name="사업계획서.hwpx",
                     section_count=document.section_count)

# GenOS 가 실제로 부르는 모양
processor = DocumentProcessor()
records = await processor(request, file_path, chunk_size=1000, chunk_overlap=100)
```

---

## 왜 만들었나 — 기존 경로로는 표가 깨진다

지금 hwpx 가 RAG 로 들어가려면 전처리기를 지나는데, **지능형 전처리기는 무조건 PDF 로
변환**한다. 그 과정에서 표 안 수치가 깨진다(요구사항 §5). 반대로 hwpx 를 직접 파싱하면
수치는 살지만 지금까지는 **마크다운 표로 내느라 병합·중첩이 사라졌다.**

```
| 구분 | 2025년 실적 |   | 비고 |   ← colSpan 사라짐 → 3열이 빈칸
|   | 상반기 | 하반기 | - |        ← rowSpan 사라짐 → 1열이 빈칸
| 세부 | 소분류<br>값 |   |   |     ← 중첩표가 텍스트로 뭉개짐
```

**수치는 남는데 그 수치가 무엇의 값인지가 사라진다.** RAG 에서는 이게 치명적이다 —
검색은 되는데 답이 틀린다. 그래서 병합·중첩이 있으면 HTML 표로 낸다.

---

## 네 가지 설계 결정

### 0. 파일 하나로 끝낸다 — 등록 방식이 그렇게 정해져 있다

`onprem/mcp/*.py` 와 같은 이유다: GenOS 전처리기는 코드서빙(Git 저장소)이 아니라
**소스 파일 한 개**를 생성·수정 화면에 올려 실행한다. 그래서 예전에 `hwpx.py`
(파싱) / `chunking.py`(청킹) / `vector_meta.py`(레코드)로 나눠 뒀던 것을
`hwpx_preprocessor.py` 하나로 합쳤다 — 등록 화면에 셋 중 하나만 올리면 나머지가
빠진 채로 배포되는 실수를 구조적으로 없앤다. 로컬에서 부품 단위로 테스트하고
싶을 때만 `__init__.py` 가 같은 코드를 패키지처럼 재노출한다.

### 1. 표는 쪼개지 않는다

문자 수만 보는 청커에 넣으면 표 한가운데가 잘리고, **뒤 조각은 머리행이 없어 검색돼도
쓸모가 없다.** 그래서:

- 표가 상한을 넘으면 **머리행을 반복하며** 행 단위로 나눈다 — 조각마다 스스로 해석
  가능해야 한다.
- 표를 만나면 쌓아 둔 문단을 **먼저 끊는다.** 표가 문단 꼬리에 붙으면 검색 결과가
  읽기 어렵다.
- 쪼갰다는 사실을 `table_part = (몇 번째, 총 몇 개)` 로 **노출한다.** 조각만 보고
  "표가 이게 전부" 로 읽으면 안 된다.

### 2. 페이지를 지어내지 않는다

hwpx 는 **흐름 문서**라 렌더링 전에는 페이지가 없다. 기존 전처리기는 docling/PDF 를
거치며 `i_page` 와 bbox 를 얻지만 이 경로에는 그 정보가 없다.

| 필드 | 값 |
|---|---|
| `i_page`·`e_page`·`n_page`·`i_chunk_on_page`·`n_chunk_of_page` | **`None`** |
| `chunk_bboxes`·`media_files` | **`None`** |
| `i_section`·`n_section` | 섹션 번호로 대신 (추가 필드) |

**0 으로 채우면 1페이지처럼 읽힌다.** 틀린 페이지 번호는 없는 것보다 나쁘다.
페이지가 꼭 필요하면 PDF 변환 경로를 써야 하고, 그건 표가 깨지는 쪽이다 — 둘 중
하나를 고르는 것이지 이 모듈이 흉내 낼 일이 아니다.

### 3. VDB 필드 이름을 기존 것에 맞춘다

`genos_files/attach_processor.py` 의 `GenOSVectorMeta` 와 같은 이름을 쓴다. 검색 쪽
(`quick_search` MCP 도구)이 `file_name`·`file_path`·`i_page`·`i_chunk_on_doc` 를 읽어
출처를 표시하므로, **이름이 어긋나면 같은 컬렉션에 못 넣는다.**

`pydantic` 모델을 만들지 않고 **dict 를 낸다** — 붙일 곳이 정해지지 않은 부품이라
의존을 늘리지 않는 편이 합칠 때 자유롭다. 합치는 쪽에서 `GenOSVectorMeta(**record)` 로
감싸면 된다 (`extra='allow'` 라 추가 필드도 통과한다).

---

## 지능형 전처리기와 합치지 않고 **따로 등록한다**

루트 `CLAUDE.md` 의 "hwpx 전용 전처리기" 절이 남겨 둔 질문은 "전처리기 커스터마이즈
지점이 등록하는 단일 파일뿐인가, 설치 패키지 `genon.preprocessor` 안에도 손댈 수
있는가" 였다. `genos_files/intelligence_processor.py`(지능형)·`attach_processor.py`
(첨부용) 는 **읽기 전용 참조 사본**이라 이 저장소에서 그 안을 고칠 수 없고, 고칠 수
있다 해도 설치 패키지 쪽은 다른 파일 형식(pdf/docx/xlsx/…)이 걸린 코드라 손대면
회귀 범위가 그쪽까지 넓어진다.

그래서 답을 (ㄱ) 으로 확정했다 — **hwpx 전용 전처리기를 새 등록 단위로 따로 올린다.**
지능형/첨부용 전처리기는 그대로 두고 손대지 않는다. GenOS 관리 화면에서 hwpx 업로드가
이 전처리기로 가도록 **연결(매핑)을 지정하는 것**이 붙이는 절차의 전부다 — 코드
쪽에서 더 할 일이 없다:

```python
from preprocessor import DocumentProcessor

processor = DocumentProcessor()          # 인자 없이 생성 가능 — GenOS 가 이렇게 부른다
records = await processor(request, file_path)   # file_path 가 .hwpx 가 아니면 즉시 예외
```

붙이는 시점에 확인할 것:

- **청크 크기** — 기본 `chunk_size=1000`/`chunk_overlap=100` 은 임시값이다(`__call__`
  의 `**kwargs` 로 등록 화면에서 조정한다). 임베딩 모델 컨텍스트에 맞춰야 한다.
- **토크나이저** — `ChunkOptions.length` 에 콜러블을 주입하면 문자 대신 토큰으로 잰다.
  기본이 문자인 이유는 **폐쇄망에 토크나이저 파일이 없을 수 있어서**이고, 없을 때
  청킹이 통째로 실패하는 것보다 대략적인 길이로라도 도는 편이 낫다. `DocumentProcessor`
  는 이 주입 경로를 아직 kwargs 로 노출하지 않는다 — 필요해지면 추가한다.
- **`security_level`** — 배포별 필드면 `extra_metadata` kwarg 로 넣는다
  (`to_records(extra=...)` 로 전달된다).
- **다른 파일 형식은 여전히 지능형/첨부용이 처리한다.** 이 전처리기는 `.hwpx` 가
  아닌 확장자를 만나면 즉시 예외를 던진다 — 등록 화면에서 확장자별로 어느 전처리기를
  탈지 갈라 줘야 한다(GenOS 쪽 설정, 이 코드가 할 수 있는 일이 아니다).

---

## 사본 관계 — `hwpx_preprocessor.py` 가 표 규칙의 정본이다

같은 표 규칙이 배포된 곳에 **세 벌 더** 있다. 배포 단위 간 import 이 금지돼 있어
생긴 의도된 중복이다:

| 위치 | 왜 있나 |
|---|---|
| `mcp/genon_hwpx_text.py` | MCP 는 **파일 하나가 등록 단위**라 자기 안에 다 있어야 한다 |
| `codeserving/SFR-018_translation/.../office/hwpx_text.py` | `POST /translate/hwpx` 직접 업로드 경로 |
| `codeserving/SFR-018_faq/faq/hwpx_text.py` | `POST /generate/upload` 직접 업로드 경로 |

**표 규칙을 고칠 때는 이 파일부터 고치고 셋을 맞춘다.** 갈렸는지는
`onprem/test/check_table_grid.py` 가 출력으로 대조한다 (단순표 4벌 / 병합표 3벌).

006 `template_fill/hwpx_markdown.py` 는 **다른 물건**이다 — 채팅 화면 미리보기용이라
마크다운을 유지한다.

---

## 검증

```bash
export PYTHONIOENCODING=utf-8
cd SFR-018 && python -m unittest tests.test_preprocessor_chunking   # 24건
```

지키는 것: 블록 순서, 표 형식 판정, **표를 쪼개도 행이 새지 않음**, 조각마다 머리행
반복, 표가 문단과 안 섞임, 긴 문단은 문장 경계로 분할, VDB 필드 존재, 페이지 필드가
`None`(0 이 아님), 그리고 `docs/GENOS_RULES.md` §F 가 요구하는 `DocumentProcessor`
필수 케이스(정상/빈 파일/손상 파일/미지원 확장자/파라미터 경계).

만들면서 테스트가 잡은 실제 버그 둘:

1. 문장 분리 정규식이 `(?<=[다요])\.\s+` 로 **마침표를 소비**해, 쪼개진 문단에서 `.`
   가 조용히 사라지고 있었다. 청킹이 본문 글자를 지우면 검색 결과에 원문과 다른
   문장이 뜬다.
2. `ChunkOptions` 에 `overlap_chars >= max_chars` 를 넣으면 문자 분할 예외 경로
   (`_split_long_text`)가 **같은 조각을 무한히 반복**했다 — 매 반복 전진폭이
   `max_chars - overlap_chars` 인데 그 값이 0 이하가 되기 때문이다. GenOS 등록
   화면에 파라미터를 잘못 입력해도 재적재가 멈추면 안 되므로
   `ChunkOptions.__post_init__` 에서 항상 `overlap_chars < max_chars` 로 clamp 한다.

## 아직 안 한 것

- **실물 hwpx 로 확인** — 전부 합성 픽스처다. 실제 문서는 `hp:tc` 구조가 더 복잡할 수
  있다(빈 `subList`, 글상자 안 표, 각주).
- **페이지 구분 인식** — hwpx 의 페이지 나눔 컨트롤을 읽으면 `<!-- PB -->` 마커를 낼 수
  있을지 모른다. 확인하지 않았다.
- **이미지·수식** — 뽑지 않는다. `media_files` 가 늘 `None` 인 이유다.
- **표 요약(`[표 설명]`)** — 지능형 전처리기는 표마다 요약을 붙인다. 그건 LLM 호출이라
  이 패키지 밖의 일이다.
