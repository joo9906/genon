# WORK — 어떤 파일부터 쓰나 (폐쇄망 작성 순서)

> **이 문서는 손을 움직이는 순서만 담는다.** 무엇을 등록하는지는
> [`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md), 환경변수·운영 규약의 정본은
> [`README.md`](README.md), 지금 무엇이 막혀 있는지는 [`HANDOFF.md`](HANDOFF.md) 다.
> 여기서 같은 사실을 반복하지 않고 **차례와 그 차례인 이유**만 적는다.
>
> 작성 대상 총량: **파일 103개 / 25,545줄** — 코드서빙 70 + MCP 4 + 워크플로우 9 +
> 전처리기 1 + 프롬프트 10, 여기에 `requirements.txt` 4개와 `__init__.py` 5개.
> (2026-08-18: 글다듬이에 `policy_store.py` 가 생겨 코드서빙이 69 → 70 이 됐다.
> **파일 수는 그대로이고 줄 수만 22,396 → 25,545 로 늘었다** — 2026-08-23 에 hwpx
> 누락 방지 층을 파싱 코어 사본 다섯 벌로 옮긴 분량이 대부분이다.)
>
> **아래 줄 수는 전부 `wc -l` 값이다** — 옮겨 적은 파일이 여기 적힌 줄 수와 크게 다르면
> 빠뜨린 것이 있다는 뜻이라 **이 숫자가 그 자체로 점검**이다. 그래서 코드를 고치면 여기도
> 같이 고친다. 확인은 아래 한 줄이면 된다 (2026-08-27 에 다시 세서 표를 맞췄다 —
> 이번에는 **단위별 합계까지 어긋나 있었다.** 가장 크게 벌어진 다섯: MCP
> `genon_hwpx_text` 620→1,171 · 번역 `office/hwpx_text` 376→950 · FAQ `faq/hwpx_text`
> 360→825 · 006 `hwpx_markdown` 219→819 · 전처리기 1,493→2,123. 2026-08-23 작업이
> 코드만 커밋되고 이 표가 안 따라온 결과다):
>
> ```bash
> wc -l onprem/mcp/*.py onprem/workflow/*.py onprem/preprocessor/hwpx_preprocessor.py \
>       onprem/prompt/*/*.j2
> find onprem/codeserving/<단위> -name '*.py' | xargs wc -l
> ```

---

## 이번 변경 — 긴 문서 커버·안내문·번역 문맥 (2026-08-29) + eval 강화 (2026-08-30)

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** 의 세 절 — "긴 문서에서 뒷부분이 통째로
> 빠지고 있었다" · "미준수는 알리고, 다시 할지는 사용자가 정한다" · "가드레일이
> 검증되지 않은 채 있었다". 아래는 **옮겨 적을 때 필요한 것만** 추린 것이다.
>
> **등록 단위 수·시작 커맨드는 바뀌지 않았다** — 재등록이 아니라 리비전 갱신이다.

**새로 만드는 파일 (배포 단위 안 3개)**

| 파일 | 단위 | 무엇 |
|---|---|---|
| `codeserving/SFR-018_faq/faq/chunking.py` | FAQ | 문서를 LLM 예산 크기로 나누고 생성 개수를 배분 |
| `codeserving/SFR-018_text_polish/text_polish/chunking.py` | 글다듬이 | 조각 분해 + **원문 복원**(꼬리 공백을 따로 든다) |
| `codeserving/SFR-018_text_polish/text_polish/polisher.py` | 글다듬이 | 조각을 함께 돌리고 실패를 조각 단위로 센다 |

> **두 `chunking.py` 는 사본이 아니다.** 계약이 다르다 — FAQ 는 버리는 글자만 없으면
> 되고, 글다듬이는 **이어붙이면 원문과 문자 단위로 같아야** 한다. 맞추려 하지 말 것.

**배포 단위 밖 2개** (옮겨 적을 필요 없음 — 폐쇄망에 안 올라간다):
`eval/eval_mcp/pairs.py` · `test/check_eval_metrics.py`.

**다시 옮겨 적을 파일**

| 파일 | 왜 |
|---|---|
| `faq/generator.py` · `faq/config.py` | 조각 생성. `FAQ_MAX_CONTEXT_CHARS` 의 **뜻이 바뀌었다**(문서 상한 → 호출 1회 예산) |
| `SFR-018_text_polish/main.py` · `text_polish/config.py` | 라우트가 `polisher.polish_document` 를 부른다 (`polish_text_async` 직접 호출 아님) |
| `translation_pipeline/common/prompt_builder.py` · `office/markdown_units.py` · `office/translation_modes.py` | 배치 항목에 절 제목(`c`)을 싣는다 |
| `prompt/SFR-018_translation/system_batch.j2` · `system_single.j2` · `user_single.j2` | CONTEXT 규칙 (번역·출력 금지) |
| `workflow/sfr018_{faq_02_generate,polish_02_polish,translate_02_translate}.py` | payload `notice` + 죽은 `_stream_chunks` 제거 |
| `preprocessor/hwpx_preprocessor.py` | 로그 화이트리스트를 **실제로 강제**한다(`_emit_log`) |

**새 환경변수 셋 — 전부 기본값이 있어 안 넣어도 뜬다**

| 변수 | 기본 | 뜻 |
|---|---|---|
| `FAQ_MAX_CONTEXT_CHUNKS` | 40 | 조각 수 상한 (≈96만 자). **여기 걸린 문서만** 뒤가 잘린다 |
| `POLISH_MAX_CHUNK_CHARS` | 6000 | 글다듬이 조각 크기 = LLM 호출 1회 예산 |
| `POLISH_LLM_CONCURRENCY` | 4 | 동시에 도는 조각 수 (번역은 15 — 그쪽은 조각이 작다) |

**옮긴 뒤 확인**: `check_unit_endpoints`(74) · `check_workflow_run`(84) ·
`check_eval_metrics`(68) · SFR-018 unittest(290).

---

## 이번 변경 — 변경·용어 표시를 **본문 하이라이트**로 (2026-08-27)

> **정본은 [`docs/change_0827.md`](docs/change_0827.md)** — 파일별·함수별 줄 번호,
> 안 고치는 것, 부분 이관 시 어디가 FAIL 하는지가 거기 있다. 아래는 그 요약이다.
>
> **이미 옮겨 적은 뒤라면 아래 6개 파일만 다시 옮긴다.** 새로 만드는 파일도 지우는 파일도
> 없고, 등록 단위 수·시작 커맨드·환경변수는 **하나도 바뀌지 않았다** — 재등록이 아니라
> 리비전 갱신이다.

무엇이 바뀌었나 한 줄로: 글다듬이는 변경 내역을 **답변 끝 목록**으로 붙이던 것을 떼고
**바뀐 낱말에 `<mark>`** 를 입힌다. 번역은 용어사전 하이라이트가 payload 에만 실려
**화면에 한 번도 안 나오고 있었는데** 이제 `text` 가 사본을 담는다. 태그는 두 기능 다
`<strong>` → **`<mark>`** 다. 근거는 루트 `CLAUDE.md` "변경·용어 표시는 …" 절.

| # | 파일 | 줄 수 | 고치는 것 |
|---|---|---|---|
| 1 | `mcp/genon_text_guard.py` | 584 → **760** | 신규 함수 4 · **`_TGsplit_units` → `_TGsplit_units_with_spans`**(반환형 변경) · `tgbuild_change_list`·`_TGdiff_changes`·`TGChangeItem` · 새 상수 4 · 도구 독스트링 |
| 2 | `workflow/sfr018_polish_02_polish.py` | 458 → **487** | **`_format_changes` 삭제** · `run` 5곳 · 모듈 독스트링 |
| 3 | `workflow/sfr018_translate_02_translate.py` | 499 → **504** | `run` **1줄** (`display_text` 를 정본 → 사본) |
| 4 | `.../office/glossary_report.py` | 234 → **240** | `_OPEN_TAG`·`_CLOSE_TAG` 값 (로직 불변) |
| 5 | `.../api_contract.py` | 176 → **177** | 주석만 |
| 6 | `.../office/types.py` | **114** | 주석만 |

**순서: ① MCP(1) → ② 번역 코드서빙(4·5·6 — 한 단위라 같이) → ③ 워크플로우(2·3).**
1을 먼저 올려야 한다 — 2가 `diff_changes` 의 새 응답 필드를 읽는다. 뒤집으면 스텝이
정본을 화면에 흘리고, **그 상태는 오류 없이 "하이라이트가 안 보이는" 모양**이다.

```bash
export PYTHONIOENCODING=utf-8
python onprem/test/check_mcp_tools.py       # 68 → 75건
python onprem/test/check_workflow_run.py    # 74 → 80건
cd SFR-018 && python -m unittest discover -s tests -t .   # 218 → 235건
```

**부분 이관은 조용히 통과하지 않는다** — 1을 빼면 `check_mcp_tools`, 2·3을 빼면
`check_workflow_run` 의 "화면은 하이라이트 사본", 4를 빼면 unittest 의
`GlossaryMarkTagTest` 가 FAIL 한다. 갈래별 대응표는 `docs/change_0827.md` 끝에 있다.

---

## 0. 시작 전 — 이게 없으면 순서가 무의미하다

| 전제 | 없으면 | 어디까지 진행되나 |
|---|---|---|
| 폐쇄망 Git 저장소 | 코드서빙 등록 자체가 불가 | MCP·워크플로우·전처리기는 파일 붙여넣기라 **진행된다** |
| 사내 PyPI mirror | 빌드 커맨드가 그 자리에서 멈춘다 | 파일 작성은 다 되고 기동만 안 된다 |
| Gateway 4종(`GENOS_URL` `LLM_SERVING_ID` `LLM_MODEL_ID` `GENOS_TOKEN`) | 기동은 되고 첫 LLM 호출에서 실패 | LLM 없는 경로(파싱·미리보기)까지 확인 가능 |
| Redis(`REDIS_URL`) — 006·FAQ | 대화는 되는데 다운로드가 빈 문서 | 글다듬이·번역은 **무상태라 무관** |
| 템플릿 볼륨(`TEMPLATE_FILL_TEMPLATE_DIR`) — 006 | 템플릿을 못 찾는다 | 006 외 전부 무관 |
| 관리자 정책 프롬프트(`GENOS_ADMIN_API_URL` + 프롬프트 ID) — 글다듬이·MCP `lang_policy` | **막지 않는다** — 내장 톤 3종으로 정상 동작 | 전부 진행된다. 고객사가 톤을 직접 추가할 때만 필요하다 (`docs/SERVING_REGISTRY.md` §2-2) |

**막힌 전제가 있어도 순서를 바꾸지 않는다.** 아래 1~3단계는 위 전제 중 앞의 둘만
요구하고, Redis·볼륨은 마지막 단위(006)에서만 필요하다 — 그래서 006 을 뒤에 둔다.

---

## 1. 큰 순서 — 왜 이 차례인가

의존 방향이 한 방향이다. **워크플로우가 코드서빙·MCP 를 부르고, 반대는 없다.**
그래서 부르는 쪽을 나중에 쓴다 — 반대로 하면 스텝을 붙여도 부를 상대가 없어
`CONFIG_MISSING` 만 보게 되고, 그게 배선 실수인지 아직 안 올린 것인지 구분되지 않는다.

| 단계 | 대상 | 파일 | 줄 수 | 선행 | 끝났다는 증거 |
|---|---|---|---|---|---|
| **1** | `mcp/` 4파일 | 4 | 3,934 | 없음 | `tools/list` 에 **14개**가 다 나온다 |
| **2** | `codeserving/` 4단위 | 70 | 15,426 | Git·mirror | 단위마다 `GET /health` 200 |
| **3** | `prompt/` 10파일 | 10 | 337 | 2단계 | 기동 로그 `prompt_dir_loaded` |
| **4** | `workflow/` 9스텝 | 9 | 3,587 | 1~3단계 **전부** | 끝단 한 바퀴 통과 |
| **5** | `preprocessor/` 1파일 | 1 | 2,123 | **없음 — 독립 트랙** | hwpx 적재 후 검색 결과의 표가 살아 있다 |

**5단계는 언제 해도 된다.** hwpx 전용 전처리기는 RAG 적재 경로이고 위 네 기능 어디에도
배선돼 있지 않다. 파일 하나뿐이라 대기 시간이 생겼을 때 끼워 넣기 좋다.

**단계 안에서는 잎(leaf)부터.** `config.py` → `logging_utils.py` → `error_codes.py` 가
어느 단위든 맨 앞이고 진입점(`main.py`)이 맨 뒤다. 진입점을 먼저 올리면 아직 없는
모듈을 import 하다 죽어서 **진짜 문제가 어디인지 가려진다.**

---

## 2. 1단계 — MCP 도구 파일 4개

**서로 완전히 독립이다** (파일 하나가 등록 단위이고 import 이 없다). 그래도 이 차례를
권한다:

| # | 파일 | 줄 | 먼저 쓰는 이유 |
|---|---|---|---|
| 1 | `mcp/genon_hwpx_text.py` | 1,171 | **유일하게 `lxml` 이 필요하다.** `requirements.txt` 를 쓸 수 없어 파일 안에서 설치하는데, mirror 접근이 없으면 여기서만 실패한다 — 그 사실을 제일 먼저 알아야 나머지 계획이 선다 |
| 2 | `mcp/genon_lang_policy.py` | 1,153 | 워크플로우 첫 스텝 둘(다듬-1·번역-1)이 이걸 부른다. **넷 중 유일하게 환경변수를 볼 수 있다** — 관리자 정책 프롬프트를 쓸 때만 (`GENOS_ADMIN_API_URL`·`LANG_POLICY_PROMPT_ID`, 없으면 내장값) |
| 3 | `mcp/genon_text_guard.py` | 760 | 마지막 스텝 둘이 부른다. 표준 라이브러리만 쓴다. **낱말 변경 좌표·`<mark>` 사본이 여기 있다** (2026-08-27) |
| 4 | `mcp/genon_glossary.py` | 850 | **지금 어느 스텝도 부르지 않는다** — 번역 코드서빙이 자체 `glossary_exact.py` 로 처리한다. 뒤로 미뤄도 아무것도 막히지 않는다 |

**확인**: 넷을 다 올린 뒤 `tools/list` 에 **14개**(`TG` 4 + `LP` 6 + `GL` 3 + `HX` 1).
**하나라도 비면 이름이 겹쳐 덮인 것이다** — 최상위 심볼 접두어(`TG`/`LP`/`GL`/`HX`)를
옮겨 적다 빠뜨렸는지 본다.

> `TG` 가 5 → 4 다 (2026-08-18). 호출부가 하나도 없던 `evidence_check` 를 뺐다 —
> 근거 대조는 FAQ 코드서빙 `faq/evidence.py` 가 한다. **옛 문서를 보고 15 를 세면
> "하나가 덮였다" 고 오판한다.**

---

## 3. 2단계 — 코드서빙 4단위

### 단위 순서: 작고 전제 없는 것부터

| 순 | 단위 | 파일 | 줄 | 상태 저장 | 왜 이 자리인가 |
|---|---|---|---|---|---|
| 1 | `SFR-018_text_polish` | 9 | 1,501 | 무상태 | **가장 작다.** 빌드·시작 커맨드·환경변수·게이트웨이 왕복이라는 배포 절차 전체를 최소 분량으로 한 번 통과시킨다 |
| 2 | `SFR-018_translation` | 22 | 4,645 | 무상태 | 루트 `main.py` 라 시작 커맨드가 1번과 같다. LLM 없는 경로(`/translate/hwpx` 파싱)가 있어 게이트웨이 전에도 확인된다 |
| 3 | `SFR-018_faq` | 15 | 2,917 | **Redis** | Redis 전제가 여기서 처음 붙는다. 시작 커맨드가 `faq.main:app` 로 달라지는 첫 단위이기도 하다 |
| 4 | `SFR-006_template_fill` | 24 | 6,363 | Redis + 볼륨 | **가장 크고 전제가 가장 많다.** 앞의 셋에서 배포 절차가 검증된 뒤에 붙는 것이 낫다 |

빌드 커맨드는 넷 다 `pip install -r requirements.txt`. **시작 커맨드만 다르다** —
006 과 FAQ 에 `main:app` 을 쓰면 기동 실패한다(진입점이 패키지 안이다). 값은
`docs/SERVING_REGISTRY.md` §1.

> **패키지 디렉토리를 만들 때 `__init__.py` 를 빼먹지 말 것.** 파일 목록에 안 잡히는데
> 없으면 import 가 안 된다. 006 `template_fill/`(9줄) · FAQ `faq/`(11줄) ·
> 번역 `translation_pipeline/`·`common/`·`office/`(**셋 다 빈 파일**).

### 3-1. SFR-018_text_polish (12파일)

```
1  text_polish/config.py            90    ┐ 잎 셋. 나머지 전부가 이걸 본다
2  text_polish/logging_utils.py     82    │
3  text_polish/error_codes.py      102    ┘ ErrorCode 가 http_status 를 들고 있다
4  text_polish/policy_store.py     231    ★ 관리자 정책(프롬프트 라이브러리) 적재 — 5 가 이걸 쓴다
5  text_polish/tone_presets.py     256      내장 톤 + 4 의 병합. MCP lang_policy 의 사본
6  text_polish/txt_output.py       153      잎. 018 세 단위에 같은 사본 (BOM+CRLF)
7  text_polish/prompt_loader.py     94
8  text_polish/llm.py              196      CONFIG_MISSING 상수가 여기 있다
9  main.py                         297      진입점 (루트)
   ──────────────────────────────────────
   합계 1,501
   requirements.txt                 25
```

**`policy_store.py` 가 `tone_presets.py` 보다 먼저다** (2026-08-18 신규). 뒤엣것이
`from text_polish import policy_store` 로 앞엣것을 끌어온다 — 순서를 바꾸면 잎부터
올리는 원칙이 깨져 `tone_presets` 를 올리는 자리에서 `ImportError` 가 난다.

`markdown_guard.py`·`fact_guard.py`·`diff_report.py` 를 찾지 말 것 — **이 단위에 없다.**
2026-08-11 에 `mcp/genon_text_guard.py` 로 갔다.

### 3-2. SFR-018_translation (26파일)

```
 1  config.py                                   117   ┐ 잎
 2  translation_pipeline/common/logging_utils.py 71   │
 3  translation_pipeline/common/error_codes.py   65   │
 4  api_contract.py                             177   ┘ main.py 가 최상위에서 직접 끌어온다
 5  translation_pipeline/common/txt_output.py   153     잎. POST /download (2026-08-12)
 6  translation_pipeline/office/languages.py    334     한국어 축 검증(+원문 언어 교차검증) + 용어사전 적용 언어
 7  translation_pipeline/office/registers.py     86
 8  translation_pipeline/office/types.py        114     아래 전부가 쓰는 값 객체
 9  common/glossary_store.py                    284   ┐ 적재 → 매칭. 순서 고정
10  common/glossary_exact.py                    324   ┘
11  common/prompt_loader.py                     109   ┐ 순서 고정
12  common/prompt_builder.py                     69   ┘
13  common/llm.py                               196     _base_url() 이 /api/gateway 를 붙인다
14  common/validation.py                         68
15  office/markdown_units.py                    233   ┐ 분해/재조립. 구조 보존 계약의 몸통
16  office/hwpx_text.py                         950   │ lxml — 모듈 최상단 import. 누락 방지 층 포함(2026-08-23)
17  office/units.py                              47   ┘
18  office/numeric_guard.py                      73   ┐ 사후 검증
19  office/glossary_report.py                   240   ┘ term_map·hits[].spans·`<mark>` 사본
20  office/translation_modes.py                 317   ┐ 실행 → 오케스트레이션
21  office/pipeline.py                          234   ┘ DirectionVerdict 를 받는다
22  main.py                                     384     진입점 (루트)
    ─────────────────────────────────────────────
    합계 4,645 (빈 __init__.py 3개 포함)
    requirements.txt                             21
    translation_pipeline/{,common/,office/}__init__.py  ← 빈 파일 3개
```

### 3-3. SFR-018_faq (18파일)

```
 1  faq/config.py            85   ┐ 잎
 2  faq/logging_utils.py     66   │
 3  faq/error_codes.py      189   │ 실패 4갈래(504/422/500/502)가 이 표에 있다
 4  faq/api_contract.py     115   ┘
 5  faq/txt_output.py       153     잎. 세 018 단위에 같은 사본
 6  faq/redis_client.py      33   ┐ from_url 을 부르는 유일한 곳
 7  faq/session_store.py    128   ┘
 8  faq/hwpx_xml.py         163   ┐ hwpx 직접 파싱 (입력 전용)
 9  faq/hwpx_text.py        825   ┘ 표 격자 + 누락 방지 — MCP 사본과 같아야 한다
10  faq/evidence.py          84     근거 대조 — 이 단위의 핵심 계약
11  faq/prompt_loader.py     93
12  faq/llm.py              199     CONFIG_MISSING → FAILURE_CONFIG
13  faq/generator.py        316     10·11·12 를 묶는다
14  faq/formatting.py       145     화면 마크다운 + 파일 평문 (항목 목록 공유)
15  faq/main.py             323     진입점
    ─────────────────────────────────────
    합계 2,917 (빈 __init__.py 11줄 별도)
    requirements.txt         38
    faq/__init__.py          11
```

### 3-4. SFR-006_template_fill (25파일)

```
 1  template_fill/config.py         122   ┐ 잎 셋
 2  template_fill/logging_utils.py   71   │
 3  template_fill/error_codes.py    162   ┘
 4  template_fill/hwpx_fields.py    890     ★ hwpx 판정의 정본 (슬롯·누름틀·채움 판정)
 5  template_fill/redis_client.py    35
 6  template_fill/api_errors.py      60   ┐ 4 위에 얹히는 보조
 7  template_fill/template_store.py 159   │
 8  template_fill/api_requests.py   147   ┘
 9  template_fill/hwpx_style.py     549   ┐ 4 의 파서를 재사용
10  template_fill/hwpx_blocks.py    422   │
11  template_fill/chat_reply.py     142   ┘
12  template_fill/field_judge.py    229     10 의 BodyBlock 을 쓴다
13  template_fill/document.py       171     조립점 — 서식→채우기→블록 순서가 여기 한 곳
14  template_fill/hwpx_markdown.py  819     **13 을 import 한다** (4 만 본다는 착각 주의).
                                            누락 방지 층 포함(2026-08-23)
15  template_fill/session_store.py  221   ┐ SCHEMA_VERSION 4 / _STATE_VERSION 2
16  template_fill/template_index.py 341   ┘
17  template_fill/prompt_loader.py   99   ┐ 순서 고정
18  template_fill/prompts.py         90   ┘
19  template_fill/llm.py            191     _chat_url()
20  template_fill/chat_state.py     188
21  template_fill/session_view.py   237
22  template_fill/api_download.py   114     hwpx 응답 조립 (형식이 하나라 분기가 없다)
23  template_fill/chat_api.py       353     /chat/context·extract·commit
24  template_fill/main.py           551     진입점 (21·22·23 을 전부 끌어온다)
    ────────────────────────────────────────────
    합계 6,363 (__init__.py 9줄 별도)
    requirements.txt                 34
    template_fill/__init__.py         9
```

`tone_presets.py`·`value_guard.py`·`tone_apply.py`·`overflow.py`·`hwpx_verify.py`·
`_vendor/`·**`pdf_convert.py`** 는 **찾지 말 것.** 앞의 다섯과 `_vendor/` 는 2026-08-12
(`archive/sfr006-tone`·`archive/hwpx-genon-vendor`), `pdf_convert.py` 는 2026-08-14 에
지웠다(`archive/sfr006-pdf` — 산출 형식이 hwpx 하나가 됐다).

### 단위마다 끝에 확인

1. `GET /health` 200 → 2. 기동 로그(`prompt_dir_loaded`, 006 은 `admin_token_missing`
경고 유무) → 3. 설정 조회(`GET /config`·`/templates`·`/languages`) → 4. LLM 없는 경로
→ 5. LLM 경로. 실패하면 로그 `event` 로 갈린다: `prompt_render_failed`(3단계 누락) /
`upstream_status`(게이트웨이) / 그 외.

---

## 4. 3단계 — 프롬프트 10파일

**배포 단위 밖이라 파일 목록에 안 잡힌다.** 빠뜨리면 기동은 되고 첫 LLM 호출에서
`PromptRenderError` 로 죽는다.

```
prompt/SFR-006_template_fill/extract_system.j2   65
                            /extract_user.j2     45
prompt/SFR-018_text_polish/system.j2             44
prompt/SFR-018_translation/system_batch.j2       47
                          /user_batch.j2          9
                          /system_single.j2      33
                          /user_single.j2         5
prompt/SFR-018_faq/system.j2                     50
                  /user.j2                       15
                  /retry_shortfall.j2            24
```

**필요한 이미지는 코드서빙 4개뿐이다.** 워크플로우 스텝은 `jinja2` 를 쓸 수 없어
(§D.3) 프롬프트를 렌더하지 않는다 — 재배치 전 "006·FAQ 는 02·03 두 이미지 모두" 라는
서술은 지금 해당 없다.

`*.j2` 머리말의 한/영 분리 근거 주석을 **함께 옮긴다.** 문구를 고칠 사람이 파일만 열어도
어느 블록을 어느 언어로 둘지 알아야 한다.

---

## 5. 4단계 — 워크플로우 스텝 9개

**파일을 통째로 캔버스에 붙여 넣는다.** 파일 간 import 이 하나도 없어 순서 제약은
없지만, 기능 단위로 묶어 **그 기능을 끝까지 통과시키고 다음으로 간다** — 스텝만 아홉 개
붙여 놓고 한꺼번에 눌러 보면 어느 층에서 어긋났는지 갈라내기 어렵다.

| 순 | 기능 | 스텝 | 필요한 ID |
|---|---|---|---|
| 1 | 글다듬이 | `sfr018_polish_01_policy`(333) → `sfr018_polish_02_polish`(**487**) | `LANG_POLICY_MCP_ID` · `TEXT_POLISH_SERVING_ID` · `TEXT_GUARD_MCP_ID` |
| 2 | 번역 | `sfr018_translate_01_detect`(471) → `sfr018_translate_02_translate`(**504**) | `LANG_POLICY_MCP_ID` · **`HWPX_TEXT_MCP_ID`** · `TRANSLATION_SERVING_ID` · `TEXT_GUARD_MCP_ID` |
| 3 | FAQ | `sfr018_faq_01_source`(430) → `sfr018_faq_02_generate`(381) | `HWPX_TEXT_MCP_ID` · `FAQ_SERVING_ID` |
| 4 | 006 | `sfr006_01_context`(347) → `sfr006_02_extract`(303) → `sfr006_03_commit`(331) | `TEMPLATE_FILL_SERVING_ID` |

여기에 `GENOS_URL`·`GENOS_TOKEN` 이 전 스텝 공통이다. **시크릿 기본값이 없으므로**
하나라도 빠지면 그 스텝이 `CONFIG_MISSING`(`02-00020003`)으로 즉시 끝난다.

**번역-1 이 `HWPX_TEXT_MCP_ID` 를 쓴다.** 캔버스가 `translate_hwpx_path` 를 채워 줄 때
hwpx 전용 파서를 태우는 경로이고, 없으면 전처리기 산출물로 떨어진다(그 폴백은 로그에
사유를 남긴다). 예전 표에 이 줄이 빠져 있었다.

캔버스 변수: `template_fill_template_id`(006 필수) · `polish_doc_type`·`polish_tone`(선택)
· `faq_max_count` · `faq_hwpx_path` · `translate_target_lang`(**번역 필수**) ·
`translate_source_lang`·`translate_register`(선택) · `translate_hwpx_path`.

**`translate_source_lang` 은 선택이지만 화면에 드롭다운이 있다.** 비우면 문서에서
감지하고, 채우면 그 값이 정본이 되되 **문서와 대조한다**(2026-08-18) — 선언이 한국어인데
문서에 한글이 없고 대상도 비한국어면 거부된다(실제로는 `en→ru` 이므로). 통과한 불일치는
`translate_source_mismatch`·`translate_detected_lang` 으로 다음 스텝에 넘어간다.

---

## 6. 5단계 — hwpx 전처리기 (독립)

```
preprocessor/hwpx_preprocessor.py   2,123   ⭐ 등록 단위 — 이 파일 하나만 올린다
preprocessor/__init__.py                    로컬 테스트용 재노출. **등록 대상이 아니다**
```

MCP 와 같은 방식(소스 파일 한 개)으로 등록한다. 등록 화면에서 **받을 확장자를 고를 수
있으므로**(2026-08-14 확인) 이 전처리기에는 **`hwpx` 만** 걸고 나머지는 종전 지능형·첨부용에
그대로 둔다 — **`hwp`(구버전 바이너리)는 넣지 말 것.** 우리 파서는 zip 기반 hwpx 전용이다.
코드 쪽에서 할 일은 없다(확장자 분기를 우리가 구현하지 않는다 — 지능형을 이 파일에
이식하지 않는 이유는 `preprocessor/README.md`).

붙일 때 정할 값 둘: `chunk_size`/`chunk_overlap`(기본 1000/100 은 임시값 — 임베딩 모델
컨텍스트에 맞춘다), `security_level`(배포별 필드면 `extra_metadata`).
**확장자·본문·파라미터를 바꾸면 `needs_reingest` 이고 자동 재적재가 아니다** — 매핑을
확정한 뒤에 hwpx 를 올린다.

---

## 6-1. 선택 트랙 — 관리자 정책 프롬프트 (파일을 쓰는 일이 아니다)

**이건 옮겨 적는 대상이 아니라 GenOS 화면에서 만드는 리소스다.** 그래서 위 총량
103개에 없다. **안 만들어도 네 기능이 전부 정상 동작한다** — 내장 톤 3종·문서유형 8종으로
돈다. 고객사가 **톤을 직접 추가·수정**하겠다고 할 때만 만든다.

| 순 | 할 일 | 어디서 |
|---|---|---|
| 1 | `도구 > 프롬프트 라이브러리` 에 정책 프롬프트 생성 (본문 = JSON) | GenOS 화면 |
| 2 | 리비전을 **운영 반영** | GenOS 화면 |
| 3 | 글다듬이 코드서빙에 `GENOS_ADMIN_API_URL` + `POLISH_POLICY_PROMPT_ID` | 리비전 상세 > 환경 설정 |
| 4 | MCP `genon_lang_policy` 에 `GENOS_ADMIN_API_URL` + `LANG_POLICY_PROMPT_ID` (**같은 ID**) | MCP 등록 화면 |
| 5 | `GET {글다듬이}/policies` 에서 `policy.source == "prompt_library"` 확인 | curl |

JSON 형식·필드표·`reason` 진단표는 [`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md)
§2-2 에 있다. 여기서 반복하지 않는다.

**3·4 를 반드시 같이 한다.** 화면 드롭다운은 글다듬이가 그리고 **강제 톤 판정은 MCP 가**
한다 — 한쪽에만 넣으면 사용자가 화면에서 고른 톤을 워크플로우가 "알 수 없는 톤" 으로
되돌린다. 예외도 오류 코드도 없다.

**언제 해도 된다.** 2단계(코드서빙)·1단계(MCP)가 올라간 뒤라면 순서 제약이 없고, 나중에
붙여도 그때부터 반영된다(재배포 불필요 — 그게 이 기능의 목적이다).

---

## 7. 옮겨 적을 때 반복해서 나는 실수

| 실수 | 어떻게 드러나나 |
|---|---|
| 프롬프트 디렉토리를 안 넣음 | 기동·헬스체크 정상, **첫 LLM 호출에서만** `PromptRenderError` |
| 006·FAQ 에 `main:app` 등록 | 기동 실패 (진입점이 패키지 안이다) |
| 빈 `__init__.py` 누락 | 진입점 올리는 마지막 단계에서 `ImportError` — 앞 단계는 전부 통과한 뒤다 |
| MCP 접두어(`TG`/`LP`/`GL`/`HX`) 누락 | 도구가 **덮인다.** 예외 없이 "값이 이상하다" 로만 보인다 |
| 006·FAQ 가 서로 다른 Redis | 대화는 정상, 다운로드가 빈 문서 |
| 사본을 한쪽만 고침 (hwpx 파싱 코어 **5벌**·톤 3벌·`txt_output` 3벌·**언어 방향 2벌**·**정책 파서 2벌**·용어사전 적재 2벌·**하이라이트 태그 2벌**) | 그 기능에서 받은 파일만 깨진다. 사용자 제보로만 드러난다 |
| 관리자 정책 프롬프트 ID 를 **한쪽에만** 넣음 (글다듬이 ○ / MCP `lang_policy` ×) | 화면 드롭다운에는 추가한 톤이 뜨는데 **고르면 기본 톤으로 되돌아간다.** 오류가 아니라 "고른 톤이 조용히 무시되는" 모양이다 |

**올리기 전에 로컬에서 한 번 돌린다** (전부 서버·LLM·Redis 불필요):

```bash
export PYTHONIOENCODING=utf-8
python onprem/test/check_deploy_contract.py   # 여기서 FAIL 이면 배치가 어긋난 것이다
python onprem/test/check_service_boot.py
python onprem/test/check_mcp_tools.py
python onprem/test/check_tone_policy.py       # 사본 대조 — 옮겨 적다 한쪽만 고쳤는지
```

전체 목록·건수는 루트 `CLAUDE.md` "검증 명령".

---

## 8. 다 옮긴 뒤 남는 일

**여기부터는 파일을 쓰는 일이 아니라 실물로 확인하는 일이다.** 목록과 우선순위는
[`HANDOFF.md`](HANDOFF.md) §4 — LLM 실호출, 게이트웨이의 JSON-RPC 통과 여부,
빌드·시작 커맨드의 셸 통과 여부, 스텝 간 `data` 크기 한도, 메모장에서 `.txt` 열기,
한/글에서 006 산출물 열기.
