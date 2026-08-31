# WORK — 어떤 파일부터 쓰나 (폐쇄망 작성 순서)

> **이 문서는 손을 움직이는 순서만 담는다.** 무엇을 등록하는지는
> [`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md), 환경변수·운영 규약의 정본은
> [`README.md`](README.md), 지금 무엇이 막혀 있는지는 [`HANDOFF.md`](HANDOFF.md) 다.
> 여기서 같은 사실을 반복하지 않고 **차례와 그 차례인 이유**만 적는다.
>
> 작성 대상 총량: **파일 109개 / 27,170줄** — 코드서빙 76 + MCP 4 + 워크플로우 9 +
> 전처리기 **1** + 프롬프트 10, 여기에 `requirements.txt` 4개와 `__init__.py` 5개.
> **전처리기는 두 파일 중 하나만 올린다** — 위 총량은 단독 `hwpx_preprocessor.py`(2,156)
> 기준이고, 합친 `final_preprocessor.py`(8,675)를 고르면 **33,689줄**이 된다 (§6).
> (2026-08-31 재계수. 103 → 109 는 2026-08-28·29 에 생긴 여섯 — `file_store.py` 3벌 ·
> `chunking.py` 2벌 · `polisher.py`. 줄 수는 25,545 → 27,170.)
>
> **아래 줄 수는 전부 `wc -l` 값이다** — 옮겨 적은 파일이 여기 적힌 줄 수와 크게 다르면
> 빠뜨린 것이 있다는 뜻이라 **이 숫자가 그 자체로 점검**이다. 그래서 코드를 고치면 여기도
> 같이 고친다. 확인은 아래 한 줄이면 된다.
>
> ```bash
> wc -l onprem/mcp/*.py onprem/workflow/*.py onprem/preprocessor/hwpx_preprocessor.py \
>       onprem/prompt/*/*.j2
> find onprem/codeserving/<단위> -name '*.py' -not -path '*__pycache__*' | xargs wc -l
> ```
>
> **표가 코드보다 늦는 일이 반복됐다.** 2026-08-27 에 한 번 맞췄는데 08-28·29 작업이
> 또 코드만 커밋됐다 — 2026-08-31 재계수에서 **신규 파일 여섯이 이 문서에 통째로 없었고**
> (`file_store.py`·`chunking.py`·`polisher.py`) 줄 수는 스물여섯 자리가 어긋나 있었다.
> 가장 크게 벌어진 넷: 번역 `glossary_exact` 324→414 · FAQ `generator` 316→444 ·
> 워크플로우 `polish_02` 487→532 · MCP `genon_glossary` 850→925.
> **없는 파일은 "빠뜨렸다" 로도 안 드러난다** — 목록에 없으니 찾지도 않는다.

---

## 최근 변경 — **이미 옮겨 적은 뒤라면 여기만 다시 본다**

아래 넷은 전부 **리비전 갱신**이다 — 등록 단위 수도 시작 커맨드도 안 바뀌었다.
처음 옮기는 것이라면 이 절을 건너뛰고 §0 부터 읽으면 된다. 신규 파일은 §3 의 단위별
목록에 이미 들어가 있다.

| 날짜 | 무엇 | 다시 옮길 것 |
|---|---|---|
| **08-31** | 전처리기 **등록 단위가 둘**이 됐다 | 5단계만 — 올릴 파일을 고른다 (§6) |
| **08-30 / 08-29** | 긴 문서 커버·안내문·번역 문맥 | 신규 3 + 다시 옮길 6 |
| **08-28** | 양쪽 하이라이트·**내려받기 링크** | 신규 `file_store.py` **3벌** |
| **08-27** | 변경·용어 표시를 본문 하이라이트로 | 6개 파일 (순서 있음) |

### 2026-08-31 — 전처리기 **등록 단위가 둘**이 됐다

> **정본은 루트 [`CLAUDE.md`](../CLAUDE.md)** "등록 단위가 둘이 됐다" 절과
> [`preprocessor/README.md`](preprocessor/README.md).
>
> **코드서빙·MCP·워크플로우는 하나도 안 바뀌었다.** 5단계(전처리기)만 갈린다.

5단계에서 **올리는 파일을 고르게 됐다.** 둘 다 유효하고 **하나만** 올린다:

| 올리는 파일 | 줄 | 언제 |
|---|---|---|
| `preprocessor/hwpx_preprocessor.py` | 2,156 | 등록 화면에서 **확장자별로 매핑을 나눌 수 있을 때.** 더 단순하다 — 기존 지능형·첨부용은 그대로 두고 `hwpx` 만 우리 것으로 건다 |
| `preprocessor/final_preprocessor.py` | **8,675** | **한 등록이 모든 확장자를 받아야 할 때.** 벤더 둘(첨부용·지능형)을 함께 담고 형식마다 덜 잃는 쪽으로 보낸다 |

> **`final_preprocessor.py` 는 손으로 옮겨 적는 파일이 아니라 생성물이다.**
> `build_final_preprocessor.py`(688)가 네 조각을 붙여 만들고 **AST 로 원본과 대조**한다.
> 폐쇄망에서 고칠 일이 생기면 `hwpx_preprocessor.py`·`router_template.py`(424)·빌드
> 스크립트 셋 중 하나를 고치고 **빌드를 다시 돌린다** — 생성물을 직접 고치면 다음
> 빌드에 지워지고, 그 사이 원본과 갈린 상태도 **정상으로 돈다.**

**옮겨 적는 대상은 여전히 파일 하나다.** 위 셋(빌드 스크립트·라우터 조각·단독 파서)은
배포 단위가 아니다 — 다만 **합친 쪽을 고를 거면 저장소 쪽에 셋도 있어야** 다음에 고칠 수
있다. 폐쇄망에 저장소를 못 두면 단독 파서를 고르는 편이 낫다.

**확인**: `python onprem/test/check_final_preprocessor.py` — **119건**.
119 가 아니면 실물 hwpx(`data/` 5벌)를 못 찾은 것이다(있는 것만 태우므로 **조용히**
113 으로 준다). docling 이 반쯤 설치된 환경에서는 `벤더 부재…` 1건이 FAIL 하는데
코드 결함이 아니다.

---

### 2026-08-30 / 08-29 — 긴 문서 커버·안내문·번역 문맥

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

### 2026-08-28 — 양쪽 하이라이트·**내려받기 링크**

> **정본은 [`docs/change_0828.md`](docs/change_0828.md)** — 이 절이 WORK.MD 에 통째로
> 빠져 있었다(2026-08-31 에 채웠다). 그래서 아래 `file_store.py` 3벌이 파일 목록에
> 없었고, **없는 파일은 "빠뜨렸다" 로도 안 드러난다.**

**새로 만드는 파일 (배포 단위 안 3개 — 같은 규약의 사본이다)**

| 파일 | 단위 | 줄 |
|---|---|---|
| `SFR-018_text_polish/text_polish/file_store.py` | 글다듬이 | 125 |
| `SFR-018_translation/translation_pipeline/common/file_store.py` | 번역 | 125 |
| `SFR-018_faq/faq/file_store.py` | FAQ | 125 |

결과 txt 를 서빙이 미리 굳혀 **GenOS MinIO 에 올리고 `download_url` 만 싣는다.**
`txt_output.py` 와 같은 사본 규약이라 **한쪽만 고치면 그 단위에서 받은 파일만 깨진다.**

> **운영 MCP 예제를 그대로 옮기면 안 되는 것 셋**: 동기 `urllib`(async 라우트의 이벤트
> 루프를 멈춘다) · 예외 원문 반환(내부 URL 이 실린다, §3.8) · 임시 파일 `delete=False`
> (예외 경로에서 남는다). 우리 사본은 셋 다 피해 있다 — **줄여 적지 말 것.**

**업로드 실패는 fail-open 이다.** `download_url` 을 비우고 결과는 그대로 낸다 — 예외를
올리면 잘 만들어진 다듬기·번역 결과가 통째로 사라진다.
**폐쇄망에서 MinIO 가 되는지는 미검증**이라 옛 `POST /download` 를 폴백으로 남겼다.

**새 환경변수 둘 — 기본값이 있어 안 넣어도 뜬다** (`docs/SERVING_REGISTRY.md` §1):
`GENOS_CDN_UPLOAD_URL`(기본 `http://llmops-cdn-api-service:8080/minio/upload/temp`) ·
`GENOS_CDN_HOSTNAME`(기본 `https://genos.genon.ai` — presigned URL 에 박힐 외부 호스트).
클러스터 안 이름이 다르면 `download_url` 이 계속 비어 나가는데 **오류가 아니라 버튼만
안 생기는 모양**이다.

---

### 2026-08-27 — 변경·용어 표시를 **본문 하이라이트**로

> **정본은 [`docs/change_0827.md`](docs/change_0827.md)** — 파일별·함수별 줄 번호,
> 안 고치는 것, 부분 이관 시 어디가 FAIL 하는지가 거기 있다. 아래는 그 요약이다.
>
> **이미 옮겨 적은 뒤라면 아래 6개 파일만 다시 옮긴다.** 새로 만드는 파일도 지우는 파일도
> 없고, 등록 단위 수·시작 커맨드·환경변수는 **하나도 바뀌지 않았다** — 재등록이 아니라
> 리비전 갱신이다.
>
> **아래 "→ 줄 수" 와 점검 건수는 이 변경 직후 값이다.** 08-28·29 가 같은 파일을 또
> 건드려 지금은 더 크다(예: `genon_text_guard` 760 → **826**, `check_mcp_tools` 75 →
> **80**). **지금 값은 §2·§3·§5 의 표**를 볼 것 — 여기 숫자로 대조하면 멀쩡한 파일이
> 어긋난 것처럼 보인다.

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
| **1** | `mcp/` 4파일 | 4 | 4,075 | 없음 | `tools/list` 에 **14개**가 다 나온다 |
| **2** | `codeserving/` 4단위 | 76 | 16,707 | Git·mirror | 단위마다 `GET /health` 200 |
| **3** | `prompt/` 10파일 | 10 | 358 | 2단계 | 기동 로그 `prompt_dir_loaded` |
| **4** | `workflow/` 9스텝 | 9 | 3,756 | 1~3단계 **전부** | 끝단 한 바퀴 통과 |
| **5** | `preprocessor/` 1파일 | 1 | 2,156 **또는 8,675** | **없음 — 독립 트랙** | hwpx 적재 후 검색 결과의 표가 살아 있다 |

**5단계는 언제 해도 된다.** hwpx 전용 전처리기는 RAG 적재 경로이고 위 네 기능 어디에도
배선돼 있지 않다. 파일 하나뿐이라 대기 시간이 생겼을 때 끼워 넣기 좋다.
**어느 파일을 올릴지는 §6 에서 고른다** — 줄 수가 두 개인 이유가 그것이다.

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
| 3 | `mcp/genon_text_guard.py` | 826 | 마지막 스텝 둘이 부른다. 표준 라이브러리만 쓴다. **낱말 변경 좌표·`<mark>` 사본이 여기 있다** (2026-08-27) — 좌표는 원문·결과 **양쪽**이다(2026-08-28) |
| 4 | `mcp/genon_glossary.py` | 925 | **지금 어느 스텝도 부르지 않는다** — 번역 코드서빙이 자체 `glossary_exact.py` 로 처리한다. 뒤로 미뤄도 아무것도 막히지 않는다 |

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
| 1 | `SFR-018_text_polish` | 12 | 2,000 | 무상태 | **가장 작다.** 빌드·시작 커맨드·환경변수·게이트웨이 왕복이라는 배포 절차 전체를 최소 분량으로 한 번 통과시킨다 |
| 2 | `SFR-018_translation` | 23 | 4,990 | 무상태 | 루트 `main.py` 라 시작 커맨드가 1번과 같다. LLM 없는 경로(`/translate/hwpx` 파싱)가 있어 게이트웨이 전에도 확인된다 |
| 3 | `SFR-018_faq` | 17 | 3,340 | **Redis** | Redis 전제가 여기서 처음 붙는다. 시작 커맨드가 `faq.main:app` 로 달라지는 첫 단위이기도 하다 |
| 4 | `SFR-006_template_fill` | 24 | 6,377 | Redis + 볼륨 | **가장 크고 전제가 가장 많다.** 앞의 셋에서 배포 절차가 검증된 뒤에 붙는 것이 낫다 |

빌드 커맨드는 넷 다 `pip install -r requirements.txt`. **시작 커맨드만 다르다** —
006 과 FAQ 에 `main:app` 을 쓰면 기동 실패한다(진입점이 패키지 안이다). 값은
`docs/SERVING_REGISTRY.md` §1.

> **패키지 디렉토리를 만들 때 `__init__.py` 를 빼먹지 말 것.** 파일 목록에 안 잡히는데
> 없으면 import 가 안 된다. 006 `template_fill/`(9줄) · FAQ `faq/`(11줄) ·
> 번역 `translation_pipeline/`·`common/`·`office/`(**셋 다 빈 파일**).

### 3-1. SFR-018_text_polish (13파일)

```
 1  text_polish/config.py           103    ┐ 잎 셋. 나머지 전부가 이걸 본다
 2  text_polish/logging_utils.py     82    │
 3  text_polish/error_codes.py      102    ┘ ErrorCode 가 http_status 를 들고 있다
 4  text_polish/policy_store.py     231    ★ 관리자 정책(프롬프트 라이브러리) 적재 — 5 가 이걸 쓴다
 5  text_polish/tone_presets.py     256      내장 톤 + 4 의 병합. MCP lang_policy 의 사본
 6  text_polish/txt_output.py       162      잎. 018 세 단위에 같은 사본 (BOM+CRLF)
 7  text_polish/file_store.py       125    ★ 잎. 결과 txt 를 CDN 에 올린다 — 018 세 단위 사본 (08-28)
 8  text_polish/prompt_loader.py     94
 9  text_polish/llm.py              196      CONFIG_MISSING 상수가 여기 있다
10  text_polish/chunking.py         200    ★ 조각 분해 + 원문 복원 (꼬리 공백을 따로 든다)
11  text_polish/polisher.py         126    ★ 10·9 를 묶는다 — 조각을 함께 돌리고 실패를 조각으로 센다
12  main.py                         323      진입점 (루트). 11 을 부른다
    ──────────────────────────────────────
    합계 2,000
    requirements.txt                 25
```

**10 → 11 → 12 순서를 지킨다.** `polisher.py` 가 `chunking`·`llm` 을 끌어오고 `main.py`
가 `polisher.polish_document` 를 부른다 — `polish_text_async` 를 직접 부르던 옛 배선을
그대로 두면 **긴 문서가 90초 타임아웃으로 돌아간다**(오류는 재시도 가능으로 분류돼
같은 자리에서 반복된다).

**`policy_store.py` 가 `tone_presets.py` 보다 먼저다** (2026-08-18 신규). 뒤엣것이
`from text_polish import policy_store` 로 앞엣것을 끌어온다 — 순서를 바꾸면 잎부터
올리는 원칙이 깨져 `tone_presets` 를 올리는 자리에서 `ImportError` 가 난다.

`markdown_guard.py`·`fact_guard.py`·`diff_report.py` 를 찾지 말 것 — **이 단위에 없다.**
2026-08-11 에 `mcp/genon_text_guard.py` 로 갔다.

### 3-2. SFR-018_translation (27파일)

```
 1  config.py                                   117   ┐ 잎
 2  translation_pipeline/common/logging_utils.py 71   │
 3  translation_pipeline/common/error_codes.py   65   │
 4  api_contract.py                             188   ┘ main.py 가 최상위에서 직접 끌어온다
 5  translation_pipeline/common/txt_output.py   162     잎. POST /download (2026-08-12)
 6  translation_pipeline/common/file_store.py   125   ★ 잎. 결과 txt 를 CDN 에 (08-28). 사본 3벌
 7  translation_pipeline/office/languages.py    334     한국어 축 검증(+원문 언어 교차검증) + 용어사전 적용 언어
 8  translation_pipeline/office/registers.py     86
 9  translation_pipeline/office/types.py        118     아래 전부가 쓰는 값 객체
10  common/glossary_store.py                    284   ┐ 적재 → 매칭. 순서 고정
11  common/glossary_exact.py                    414   ┘ 한국어 조사 폴백이 여기 있다(08-28)
12  common/prompt_loader.py                     109   ┐ 순서 고정
13  common/prompt_builder.py                     91   ┘ 배치 항목에 절 제목(`c`)을 싣는다
14  common/llm.py                               196     _base_url() 이 /api/gateway 를 붙인다
15  common/validation.py                         68
16  office/markdown_units.py                    242   ┐ 분해/재조립. 구조 보존 계약의 몸통
17  office/hwpx_text.py                         950   │ lxml — 모듈 최상단 import. 누락 방지 층 포함(2026-08-23)
18  office/units.py                              47   ┘
19  office/numeric_guard.py                      73   ┐ 사후 검증
20  office/glossary_report.py                   285   ┘ term_map·hits[].spans·**target_spans**·`<mark>` 사본
21  office/translation_modes.py                 325   ┐ 실행 → 오케스트레이션
22  office/pipeline.py                          241   ┘ DirectionVerdict 를 받는다
23  main.py                                     399     진입점 (루트)
    ─────────────────────────────────────────────
    합계 4,990 (빈 __init__.py 3개 포함)
    requirements.txt                             21
    translation_pipeline/{,common/,office/}__init__.py  ← 빈 파일 3개
```

### 3-3. SFR-018_faq (19파일)

```
 1  faq/config.py            96   ┐ 잎
 2  faq/logging_utils.py     66   │
 3  faq/error_codes.py      189   │ 실패 4갈래(504/422/500/502)가 이 표에 있다
 4  faq/api_contract.py     115   ┘
 5  faq/txt_output.py       162     잎. 세 018 단위에 같은 사본
 6  faq/file_store.py       125   ★ 잎. 결과 txt 를 CDN 에 (08-28). 사본 3벌
 7  faq/redis_client.py      33   ┐ from_url 을 부르는 유일한 곳
 8  faq/session_store.py    128   ┘
 9  faq/hwpx_xml.py         163   ┐ hwpx 직접 파싱 (입력 전용)
10  faq/hwpx_text.py        825   ┘ 표 격자 + 누락 방지 — MCP 사본과 같아야 한다
11  faq/evidence.py          84     근거 대조 — 이 단위의 핵심 계약. **문서 전체로** 대조한다
12  faq/chunking.py         129   ★ 문서를 호출 1회 예산으로 나누고 **생성 개수를 배분**한다
13  faq/prompt_loader.py     93
14  faq/llm.py              199     CONFIG_MISSING → FAILURE_CONFIG
15  faq/generator.py        444     11·12·13·14 를 묶는다
16  faq/formatting.py       145     화면 마크다운 + 파일 평문 (항목 목록 공유)
17  faq/main.py             333     진입점
    ─────────────────────────────────────
    합계 3,340 (빈 __init__.py 11줄 포함)
    requirements.txt         38
    faq/__init__.py          11
```

**12 가 11 보다 뒤인 것에 이유가 있다.** 조각을 나눠도 **근거 대조와 중복 판정은
문서 전체·조각 전체로** 한다 — 조각별로 따로 하면 경계에 걸친 문장이 오탐 기각되고,
같은 주제가 여러 절에 나올 때 같은 질문이 조각마다 통과한다.

### 3-4. SFR-006_template_fill (26파일)

```
 1  template_fill/config.py         122   ┐ 잎 셋
 2  template_fill/logging_utils.py   71   │
 3  template_fill/error_codes.py    162   ┘
 4  template_fill/hwpx_fields.py    890     ★ hwpx 판정의 정본 (슬롯·누름틀·채움 판정)
 5  template_fill/redis_client.py    35
 6  template_fill/api_errors.py      60   ┐ 4 위에 얹히는 보조
 7  template_fill/template_store.py 159   │
 8  template_fill/api_requests.py   147   ┘
 9  template_fill/hwpx_style.py     548   ┐ 4 의 파서를 재사용
10  template_fill/hwpx_blocks.py    422   │
11  template_fill/chat_reply.py     148   ┘ 기각 **항목 이름**까지 문장에 담는다 (08-28)
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
    합계 6,377 (__init__.py 9줄 포함)
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
prompt/SFR-018_translation/system_batch.j2       58   ← CONTEXT 규칙 (번역·출력 금지)
                          /user_batch.j2          9
                          /system_single.j2      37   ← 같은 규칙. 단건 폴백에도 싣는다
                          /user_single.j2        11
prompt/SFR-018_faq/system.j2                     50
                  /user.j2                       15
                  /retry_shortfall.j2            24
                                              ─────
                                                358
```

**번역 셋의 CONTEXT 규칙을 빼먹지 말 것** (2026-08-29). 유닛에 절 제목을 문맥으로 다는데
"`c` 는 배경이며 번역하지도 출력하지도 말라" 가 없으면 **모델이 문맥을 번역문에 섞고,
구조는 코드가 지키므로 그 결과가 정상 응답으로 내려간다.** 단건 폴백(`system_single`)에만
빠뜨리면 **배치가 실패했을 때만** 드러나 더 어렵다.

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
| 1 | 글다듬이 | `sfr018_polish_01_policy`(333) → `sfr018_polish_02_polish`(**532**) | `LANG_POLICY_MCP_ID` · `TEXT_POLISH_SERVING_ID` · `TEXT_GUARD_MCP_ID` |
| 2 | 번역 | `sfr018_translate_01_detect`(471) → `sfr018_translate_02_translate`(**544**) | `LANG_POLICY_MCP_ID` · **`HWPX_TEXT_MCP_ID`** · `TRANSLATION_SERVING_ID` · `TEXT_GUARD_MCP_ID` |
| 3 | FAQ | `sfr018_faq_01_source`(430) → `sfr018_faq_02_generate`(**430**) | `HWPX_TEXT_MCP_ID` · `FAQ_SERVING_ID` |
| 4 | 006 | `sfr006_01_context`(347) → `sfr006_02_extract`(303) → `sfr006_03_commit`(**366**) | `TEMPLATE_FILL_SERVING_ID` |

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

## 6. 5단계 — 전처리기 (독립 트랙, **파일 하나를 고른다**)

**올리는 파일은 하나인데, 그 하나를 고른다** (2026-08-31). 둘 다 유효하다:

```
preprocessor/hwpx_preprocessor.py   2,156   ⭐ (ㄱ) hwpx 전용 — 확장자를 나눌 수 있을 때
preprocessor/final_preprocessor.py  8,675   ⭐ (ㄴ) 합친 것 — 한 등록이 전 확장자를 받을 때
──────────────────────────────────────────  아래 셋은 **등록 대상이 아니다**
preprocessor/router_template.py       424      (ㄴ)의 라우팅·폴백 조각 (빌드 입력)
preprocessor/build_final_preprocessor.py 688   (ㄴ)를 만드는 스크립트
preprocessor/__init__.py               48      로컬 테스트용 재노출
```

### 어느 쪽을 고르나

**등록 화면에서 받을 확장자를 고를 수 있으면 (ㄱ)이다** (2026-08-14 확인). 더 단순하고,
지능형·첨부용은 종전 그대로 두고 **`hwpx` 만** 우리 것에 건다. **`hwp`(구버전
바이너리)는 넣지 말 것** — 우리 파서는 zip 기반 hwpx 전용이다.

**한 등록이 모든 확장자를 받아야 하면 (ㄴ)이다.** 벤더 둘을 함께 담고 형식마다 덜 잃는
쪽으로 보낸다 — hwpx는 우리 파서, `.docx`·`.hwp`·오디오·텍스트는 첨부용(네이티브로
읽는다), `.pdf`·`.ppt(x)`·엑셀·이미지는 지능형(첨부용 pdf 는 평문이라 **표가 통째로
사라진다**). 대가가 둘 있다:

- **hwpx 청킹만 고쳐도 이 등록으로 적재한 pdf·docx 까지 `needs_reingest`** 다.
  재적재 비용이 큰 컬렉션이면 (ㄱ)이 낫다.
- **`final_preprocessor.py` 는 생성물이라 폐쇄망에서 직접 고치면 안 된다.** 고칠 일이
  생기면 빌드 입력 셋 중 하나를 고치고 `build_final_preprocessor.py` 를 다시 돌린다 —
  생성물을 직접 고치면 다음 빌드에 지워지고, **그 사이 원본과 갈린 상태도 정상으로
  돈다.** 그래서 (ㄴ)를 고를 거면 폐쇄망 쪽에도 빌드 입력 셋이 있어야 한다.

**둘 다 코드 쪽에서 할 일은 없다.** (ㄱ)은 확장자 분기를 구현하지 않고, (ㄴ)은 이미
들어 있다. 지능형을 (ㄱ)에 이식하지 않는 이유는 `preprocessor/README.md`.

붙일 때 정할 값 둘: `chunk_size`/`chunk_overlap`(기본 1000/100 은 임시값 — 임베딩 모델
컨텍스트에 맞춘다), `security_level`(배포별 필드면 `extra_metadata`).
**확장자·본문·파라미터를 바꾸면 `needs_reingest` 이고 자동 재적재가 아니다** — 매핑을
확정한 뒤에 hwpx 를 올린다.

(ㄴ)를 고르면 값 둘이 더 있다 — 둘 다 기본값이 안전한 쪽이다:
`hwpx_engine`(기본 `auto`. hwpx 파싱이 실패하면 **첨부용으로 폴백**한다 — 적재가 통째로
실패하면 그 문서가 **검색에서 사라지기** 때문이다. 폴백은 로그에 남으므로 표 병합이
보존됐다고 오해하지 않는다. `native` 면 폴백을 끈다) · `align_vector_schema`(기본 켬.
한 등록이 한 컬렉션에 **두 모양의 메타**를 넣으면 그 필드로 거르는 검색이 한쪽을 통째로
놓치는데, 그 상태는 오류가 아니라 "결과가 좀 적네" 로만 보인다).

**(ㄴ)의 미검증 둘**: 지능형 설정 yaml 을 찾는 벤더 함수가 `Path(__file__)/../resource/…`
를 보는데 **등록 파일이 실제로 어디에 놓이는지 모른다**(후보를 넷 뒀다). 그리고 지능형
경로 실행 자체 — 로컬에 docling 이 없어 **대역으로만** 태웠다.

---

## 6-1. 선택 트랙 — 관리자 정책 프롬프트 (파일을 쓰는 일이 아니다)

**이건 옮겨 적는 대상이 아니라 GenOS 화면에서 만드는 리소스다.** 그래서 위 총량
109개에 없다. **안 만들어도 네 기능이 전부 정상 동작한다** — 내장 톤 3종·문서유형 8종으로
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
| 사본을 한쪽만 고침 (hwpx 파싱 코어 **5벌**·톤 3벌·`txt_output` 3벌·**`file_store` 3벌**·**언어 방향 2벌**·**정책 파서 2벌**·용어사전 적재 2벌·**하이라이트 태그 2벌**) | 그 기능에서 받은 파일만 깨진다. 사용자 제보로만 드러난다 |
| 목록에 **없는 파일**을 안 옮김 (`file_store`·`chunking`·`polisher`) | 이 문서가 08-28·29 작업을 놓쳐 실제로 생겼던 구멍이다. 없으면 `ImportError` 로 죽지만 **어느 파일인지는 진입점을 올릴 때까지 안 보인다** |
| `final_preprocessor.py` 를 폐쇄망에서 **직접 고침** | 다음 빌드에 지워진다. 그 사이 원본과 갈린 상태도 **정상으로 돈다** — §6 |
| 관리자 정책 프롬프트 ID 를 **한쪽에만** 넣음 (글다듬이 ○ / MCP `lang_policy` ×) | 화면 드롭다운에는 추가한 톤이 뜨는데 **고르면 기본 톤으로 되돌아간다.** 오류가 아니라 "고른 톤이 조용히 무시되는" 모양이다 |

**올리기 전에 로컬에서 한 번 돌린다** (전부 서버·LLM·Redis 불필요):

```bash
export PYTHONIOENCODING=utf-8
python onprem/test/check_deploy_contract.py   # FAIL 0 / WARN 3 / OK 63 — 배치가 어긋났는지
python onprem/test/check_service_boot.py      # 16건
python onprem/test/check_mcp_tools.py         # 80건
python onprem/test/check_tone_policy.py       # 22건 — 사본 대조. 옮겨 적다 한쪽만 고쳤는지
python onprem/test/check_table_grid.py        # 33건 — hwpx 파싱 코어 5벌
python onprem/test/check_final_preprocessor.py  # 119건 — §6 (ㄴ)를 고를 때만 필요
```

전체 목록·건수는 루트 `CLAUDE.md` "검증 명령".

---

## 8. 다 옮긴 뒤 남는 일

**여기부터는 파일을 쓰는 일이 아니라 실물로 확인하는 일이다.** 목록과 우선순위는
[`HANDOFF.md`](HANDOFF.md) §4 — LLM 실호출, 게이트웨이의 JSON-RPC 통과 여부,
빌드·시작 커맨드의 셸 통과 여부, 스텝 간 `data` 크기 한도, 메모장에서 `.txt` 열기,
한/글에서 006 산출물 열기.
