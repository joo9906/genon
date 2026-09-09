# `not/` — `lxml` 없이 올리는 판본 (코드 서빙 **네 단위 전부**)

> **왜 있나**: 코드 서빙 이미지 빌드에서 **사내 PyPI mirror 에 `lxml` 이 없어** 배포가
> 막혀 있다. 그래서 네 단위를 `lxml` 없이 도는 판본으로 다시 만들었다.
>
> **정본은 계속 `onprem/` 이다.** 여기는 mirror 에 `lxml` 이 들어오면 **통째로 버린다.**
> 기능을 여기서 고치지 않는다 — 고치면 두 벌이 갈리고, 그 어긋남은 오류가 아니라
> 결과물로만 드러난다.

## 두 판본을 가르는 기준

| | **`onprem/codeserving/` — lxml 판본 (정본)** | **`not/` — lxml 없는 판본** |
|---|---|---|
| 무엇 | 지금까지 만든 것 전부. 기능·산출물의 기준 | 배포가 막혀 급히 깎아낸 한시 판본 |
| hwpx **읽기** | `lxml` | 표준 `xml.etree.ElementTree` (006) / 안 읽는다 (나머지 셋) |
| hwpx **되쓰기** | 006 이 한다 (`.hwpx` 다운로드) | **안 한다** → 006 산출물이 `.txt` |
| hwpx **직접 업로드** | FAQ·번역·006 셋 다 있다 | **006 만** 남는다 (읽기는 되므로) |
| 언제 쓰나 | mirror 에 `lxml` 이 들어온 뒤 | **지금** |
| 고치는 곳 | ✅ 여기서 고친다 | ❌ 고치지 않는다 |

```
not/
  SFR-006_template_fill/    lxml 없음 — 읽기를 표준 라이브러리로. **산출물이 txt**
  SFR-018_translation/      lxml 없음 — hwpx 직접 업로드 라우트 제거
  SFR-018_faq/              lxml 없음 — hwpx 직접 업로드 라우트 제거
  SFR-018_text_polish/      **정본과 코드가 같다** — 원래부터 lxml 을 안 썼다
  prompt/                   네 단위의 프롬프트 (onprem/prompt/ 의 사본)
  minio.py                  📖 **GenOS 참조 샘플** — 등록하지 않는다 (아래)
  check_not_units.py        이 판본 점검 — **91건**
  PROGRESS.md               작업 진행 기록
```

> ⚠ **`minio.py` 는 우리 코드가 아니다.** GenOS 에서 받은 **동작하는 MCP 예제**이고,
> 내려받기 링크(presigned URL)를 어떻게 얻는지 확인하려고 옮겨 둔 참조본이다.
> **등록하지 말 것** — `mcp` 전역을 shim 없이 쓰고, import 하는 순간
> `ensure_packages()` 가 **`pip install python-docx` 를 실행한다**(가이드 p.19 금지사항).
>
> 이 파일로 확인한 것: 업로드 URL `http://llmops-cdn-api-service:8080/minio/upload/temp`,
> 멀티파트 필드 `hostname` + `file`, 응답에서 링크를 꺼내는 경로
> `data.presigned_url`. **우리 `file_store.py` 가 이 넷과 정확히 같다** — 즉
> `download_url` 의 모양은 이제 추측이 아니다(실서비스 호출은 여전히 미검증).

---

## 1. 무엇을 어떻게 뺐나

| 단위 | 뺀 것 | 기능에 미치는 영향 |
|---|---|---|
| **FAQ** | `faq/hwpx_text.py`·`hwpx_xml.py`, `POST /generate/upload` | **없다** — 원문은 어차피 전처리기 산출물로 온다 |
| **번역** | `office/hwpx_text.py`, `POST /translate/hwpx` | **없다** — 같은 이유 |
| **글다듬이** | **없다** | 원래부터 `lxml` 을 안 쓴다 (마크다운 텍스트만 다룬다) |
| **006** | `hwpx_style.py`, hwpx **되쓰기**(`serialize_part`·`fill_template`·`append_blocks`) | **산출물이 hwpx → txt**, 서식(글꼴·크기·굵게) 미적용. `download_url` 도 **txt 링크**다 |

**세 단위(FAQ·번역·글다듬이)는 잃는 것이 없다.** 006 만 대가를 치른다 — 그 단위만
hwpx 를 **되쓰기** 때문이다.

### FAQ·번역은 잃는 것이 없다

두 단위 모두 `lxml` 에 닿는 경로가 **hwpx 직접 업로드 라우트 하나**였다
(`POST /generate/upload` · `POST /translate/hwpx`). 그 라우트는 hwpx 파일을 곧장 서빙에
올려 직접 파싱하던 자리인데, **캔버스 흐름은 그 길로 가지 않는다** — 워크플로우 스텝 1 이
2026-09-07 부터 첨부를 `genosUploaded`(전처리기 산출물)로만 받는다. pdf·docx 는 원래도
전처리기를 지나 `POST /generate`·`/translate/markdown` 으로 왔다.

**표 병합이 보존되는지는 이제 전처리기가 정한다**(`onprem/preprocessor/`). 그쪽은
`cellAddr` 좌표로 격자를 만드는 **같은 코드**이고, 오히려 병합이 없는 표도 HTML 로 낸다.

덤으로 **`python-multipart` 도 빠졌다.** FastAPI 는 `File(...)`/`Form(...)` 을 쓴 라우트를
등록하는 순간 그 패키지를 요구하고 없으면 **import 단계에서** 죽는데, 그 라우트가 없으면
요구 자체가 없다. 즉 두 단위는 mirror 의존이 둘씩 줄었다.

### 글다듬이는 사본만 뜬다

`lxml` 도 hwpx 도 쓰지 않는다. 그런데도 `not/` 에 두는 이유는 **네 단위를 한 자리에서
올리기 위해서다** — 셋만 여기 있고 글다듬이만 `onprem/` 에서 올리면 등록 화면에서 어느
단위가 어느 판본인지가 사람 머릿속에만 남는다. 점검이 이 사본을 정본과 **바이트까지**
대조하므로(판본 표시 docstring 만 예외) 여기서 뭘 고치면 그 자리에서 FAIL 한다.

### 006 은 **읽기만** 표준 라이브러리로 옮겼다

hwpx 는 ZIP + XML 이고, 이 패키지가 실제로 쓰던 lxml API 는 다섯뿐이다 —
`fromstring` · `SubElement` · `XMLSyntaxError` · `tostring` · `getparent()`.
앞의 셋은 표준 `xml.etree.ElementTree` 에 그대로 있고, 없는 것은 **`getparent()` 하나**다.
`template_fill/xml_compat.py` 가 그 자리를 부모 맵으로 메운다.

**`tostring`(되쓰기)만은 흉내 내지 않았다.** 표준 ElementTree 로 hwpx 파트를 다시 봉하려면
문서가 쓰는 네임스페이스 접두어를 **전부** `register_namespace` 로 되살려야 하고, 하나라도
놓치면 `ns0:` 로 나가 **한/글이 열지 못하는 파일**이 된다 — 예외가 나지 않고 산출물만 깨지는
형태라 만들어 놓고도 한참 모른다. 그래서 그 문을 아예 열지 않고 **txt** 를 낸다.

> 덤: 정본 주석의 "**lxml 프록시 id 는 붙들어야 유효하다**"는 함정이 여기서는 **없어졌다.**
> 표준 ElementTree 는 트리가 요소를 직접 들고 있어 요소를 그대로 dict 키로 쓸 수 있다.

---

## 2. 006 에서 실제로 달라지는 것

| | 정본 (`onprem/`) | `not/` 판본 |
|---|---|---|
| 다운로드 | `초안.hwpx` (`X-Document-Format: hwpx`) | **`초안.txt`** (`X-Document-Format: txt`, BOM+CRLF) |
| 대화 중 `download_url` | 굳힌 **hwpx** 링크 | 굳힌 **txt** 링크 (2026-09-08) |
| 서식(`16pt`·글꼴·볼드) | `charPr` 로 실제 적용 | **미적용.** `X-Styled-Fields` 는 언제나 빈 값 |
| 항목 스캔·채우기 판정 | — | **완전히 같다** (아래 대조 결과) |
| 미리보기(`GET /preview`) | — | **완전히 같다** |
| 대화 흐름·세션·자동 채움 | — | 손대지 않았다 |
| 템플릿 등록(`POST /templates`) | — | 그대로 (hwpx **읽기**는 되므로) |

- **`format=hwpx` 로 와도 400 을 내지 않는다.** 캔버스가 그 값을 보내므로 막으면
  다운로드 버튼이 통째로 죽는다. 옛 형식 이름을 400 으로 막는 규약(006 의 `format=pdf`,
  FAQ 의 `format=hwpx`)은 "화면은 A 를 받았다고 믿는데 파일은 B" 를 막으려는 것인데,
  여기서는 그 오해가 성립하지 않는다 — 내려가는 파일이 **확장자와 헤더로 스스로를 밝힌다.**
- **txt 규약은 018 세 단위와 같다** (`txt_output.py` 를 006 으로 들여왔다 — 네 번째 사본).
  BOM + CRLF 로 낸다: 폐쇄망 사내 PC 의 메모장이 BOM 없이는 cp949 로 읽어 한글이 깨지고,
  LF 만 있으면 전체가 한 줄로 붙어 보인다.

---

## 3. 검증 — 정본과 출력이 같은가

이 포팅의 유일한 진짜 질문이다. 파서를 옮기면서 글자가 하나라도 달라지면 사용자가 받는
문서가 달라지고, **예외는 나지 않는다.**

```
export PYTHONIOENCODING=utf-8
python not/check_not_units.py        # OK 91 / FAIL 0 / SKIP 0
```

무엇을 보나:

1. **금지 패키지(`lxml`·`jinja2`·`openai`)를 import 단계에서 막고** 네 단위를 실제로
   띄운다. 로컬에는 `lxml` 이 깔려 있어서 그냥 돌리면 잘 도는 것처럼 보인다.
   라우트 목록도 함께 본다 — 빠져야 할 것(hwpx 업로드)이 없고 남아야 할 것이 있는가.
2. `requirements.txt` 에 그 패키지들이 선언돼 있지 않은가 — **코드가 안 쓰는 선언 하나가
   `pip install -r` 을 세우면 배포가 통째로 막힌다.**
3. `not/prompt/` 가 `onprem/prompt/` 와 **바이트까지 같은가** (사본 드리프트).
   **글다듬이 사본도 정본과 바이트까지** 대조한다 — 고칠 것이 없었다는 사실 자체를 지킨다.
4. **정본과 출력 대조** — 실물 hwpx 5벌(`data/*.hwpx`)의 문단 텍스트·항목 스캔·
   따옴표 없는 중괄호, 그리고 슬롯 픽스처 2벌로 채운 본문·채우기 메타·블록 서식 이름·
   미리보기. 두 구현에 **같은 입력을 태워** 결과를 대조한다(정적 diff 가 아니다).
5. 다운로드가 실제로 txt 인가 (확장자·헤더·BOM·CRLF·본문).

**로컬에 `lxml` 이 없으면 4번을 못 한다. 그때는 조용히 통과시키지 않고 SKIP 으로 세어
출력에 남긴다** — 미측정을 통과로 보이게 하지 않는다(`onprem/eval` 규약).

### 되돌려 FAIL 을 확인한 갈래 일곱

- 슬롯 치환에서 **뒤 텍스트 노드를 안 비운다** → 3건 FAIL
- 본문 블록을 맨 끝에 **안 붙인다**(사용자가 쓴 글이 사라진다) → 3건 FAIL
- `requirements.txt` 에 `lxml` 부활 → 1건 FAIL
- 다운로드를 `X-Document-Format: hwpx` 로 표기 → 1건 FAIL
- 번역 `requirements.txt` 에 `lxml` 부활 → 1건 FAIL
- 글다듬이 사본을 몰래 고침 → 1건 FAIL
- 번역 프롬프트 사본을 몰래 고침 → 1건 FAIL

> **첫 번째는 처음에 안 잡혔다.** 실물 `파워.hwpx` 는 슬롯 글자가 `hp:t` **하나**에 다
> 들어 있어서 "첫 노드에 값을 넣고 나머지를 비운다"의 뒷부분이 한 번도 실행되지 않았다.
> 그 줄을 지워도 점검이 통과하는 것을 보고 **슬롯이 노드 경계를 걸치는 픽스처**를 따로
> 만들었다(`_split_slot_text_nodes`). 실물에서 흔한 모양이다 — 슬롯 가운데에서 글꼴이
> 바뀌거나 한/글 자동 고침이 들어가면 `hp:t` 가 갈린다. 지금은 되돌리면
> `제 목 : 2026년 사업 계획HY헤드라인M, 16pt}` 가 나오며 FAIL 한다.

---

## 4. 등록할 때

> **반입 절차 전체의 정본은 꾸러미 안내서다** — 저장소에서는 `submit/README.md`,
> 폐쇄망에서 압축을 푼 자리에서는 맨 위 `README.md`(이 파일의 `../README.md`).
> 등록 10번의 순서·환경변수·점검 실행이 거기 있고, 여기는 **이 판본이 정본과 무엇이
> 다른가**만 말한다. 꾸러미는 저장소 루트에서 `python make_submit.py` 로 다시 만든다.

정본과 **저장소·빌드 커맨드가 같고 시작 커맨드의 경로만 다르다.** 네 단위 전부
`onprem/codeserving/<단위>` → `not/<단위>` 로 바꾸면 된다.

| 단위 | 시작 커맨드 |
|---|---|
| 006 | `uvicorn template_fill.main:app --app-dir not/SFR-006_template_fill --host 0.0.0.0 --port $PORT` |
| 글다듬이 | `uvicorn main:app --app-dir not/SFR-018_text_polish --host 0.0.0.0 --port $PORT` |
| 번역 | `uvicorn main:app --app-dir not/SFR-018_translation --host 0.0.0.0 --port $PORT` |
| FAQ | `uvicorn faq.main:app --app-dir not/SFR-018_faq --host 0.0.0.0 --port $PORT` |

빌드 커맨드는 `pip install -r not/<단위>/requirements.txt`, **환경변수는 정본과 같다**
(`onprem/ONPREM.md` §5).

- **프롬프트 디렉토리를 이미지에 함께 넣어야 한다.** `not/prompt/` 가 그 자리다
  (`onprem/prompt/` 는 이 판본의 로더가 찾지 못한다 — 상위 탐색이 `not/` 에서 멈춘다).
  못 찾으면 기동·헬스체크는 통과하고 **첫 LLM 호출에서** 기능이 죽는다.
- **MCP 넷·전처리기·워크플로우 스텝 9개는 이 판본과 무관하다** — 그쪽은 2026-09-07 부터
  표준 라이브러리만 쓴다. 바꾸는 것은 **코드 서빙 네 단위의 시작 커맨드뿐**이다.

---

## 5. 버릴 때 (mirror 에 `lxml` 이 들어오면)

1. 네 서빙의 시작 커맨드를 `onprem/codeserving/<단위>` 로 되돌린다.
2. `not/` 디렉토리를 지운다.
3. **`onprem/` 에는 아무것도 되돌릴 것이 없다** — 이 작업은 `onprem/` 을 건드리지 않았다.

`not/` 에서 고친 것을 정본으로 옮길 일이 생기면 **옮겨 적을 것이 아니라 다시 판단할
것**이다. 여기 코드는 "hwpx 를 못 쓴다"는 전제 위에 서 있어서, 그 전제가 사라지면
근거가 없어지는 결정이 여럿 있다(서식 미적용·`format=hwpx` 허용·run 미분할).
