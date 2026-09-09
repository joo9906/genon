# 서빙 등록 목록 — onprem 에서 **무엇을 등록하는가**

> 이 문서는 **등록 작업지시서**다. GenOS 화면에 무엇을 몇 번 만들고 각 칸에 무엇을 적는지만
> 담는다. 환경변수의 **의미**와 기능별 운영 규약은 [`../README.md`](../README.md) 가
> 정본이고 여기서 복사하지 않는다 (`docs/README.md` 중복 금지 규칙).

## 결론 — 등록은 **10번**이다

| 영역 | 무엇을 등록하나 | 개수 | 등록 형태 |
|---|---|---|---|
| 03 | `codeserving/` 의 디렉토리 | **4** | 코드 서빙 (컨테이너 1개 = URL 1개) |
| 01 | `mcp/` 의 **소스 파일** | **4** | MCP 도구 (파일 1개 = 등록 단위) |
| 05 | `preprocessor/` 의 **소스 파일** | **2** | 전처리기 (적재용 + 첨부용. 아래 §2-1) |

**코드 서빙 하나 = 컨테이너 하나 = URL 하나**이고 리비전·환경변수·복제본이 전부 서빙
단위로 붙는다. 저장소를 어떻게 두든 이 숫자는 줄지 않는다.

**리소스 하나가 선택적으로 붙는다** — 고객사 관리자가 톤·문서유형을 직접 관리하려면
프롬프트 라이브러리에 **톤·문서유형 프롬프트**를 만든다(§2-2). 등록 10번에는 안 들어간다 —
안 만들어도 이미지에 든 `.j2` 와 내장 표로 정상 동작한다.

**저장소는 1개로 둔다.** 여러 서빙이 같은 저장소·같은 커밋을 가리켜도 되고, 디렉토리
구분은 빌드·시작 커맨드가 흡수한다. 근거(사본 대조 점검이 한 커밋 안에서만 성립한다)는
`../README.md` "저장소 구조" 절.

---

## onprem 최상위 — 서빙 대상 판정

등록 대상이 아닌 것을 먼저 확실히 해 둔다. **"코드니까 올려야 하나" 를 매번 다시
따지지 않기 위한 표다.**

| 디렉토리 | 서빙? | 어떻게 다루나 |
|---|---|---|
| `codeserving/` | ✅ **4개** | 코드 서빙으로 등록 (아래 §1) |
| `mcp/` | ✅ **4개** | MCP 도구 파일로 등록 (아래 §2) |
| `workflow/` | ❌ | **캔버스 Python 스텝에 파일을 통째로 붙여 넣는다.** 서버가 뜨지 않는다. 9개 |
| `prompt/` | ❌ | 배포 단위 **바깥**이지만 **이미지에 함께 들어가야 한다** (아래 §4) |
| `eval/` | ❌ | 배포 단위 아님. 채점이 필요할 때 **stdio MCP** 로 따로 띄운다 (`eval/README.md`) |
| `test/` | ❌ | 배포 계약 점검 스크립트. 배포 단위 어디서도 import 하지 않는다 |
| `preprocessor/` | ✅ **2개** | **전처리기로 등록한다** (2026-08-13 — MCP 와 같은 파일 단위). 코드 서빙이 아니라 URL 도 `/health` 도 없다. 아래 §2-1 |
| `docs/`, `*.md` | ❌ | 문서 |

---

## §1. 코드 서빙 4개 (area 03)

네 칸 모두 리비전 상세 > **환경 설정** 에 넣는다. `LANGUAGE` 는 `python`,
빌드 커맨드는 **네 단위 모두 같다**.

```
BUILD : pip install -r requirements.txt
```

시작 커맨드만 다르다 — **단위마다 진입점 위치가 다르기 때문이다.**

> ⭐ **2026-09-09 — 코드 서빙 네 단위는 `not/` 을 올린다.** 아래 표의 경로에서
> `onprem/codeserving/` 를 **`not/`** 로 바꿔 읽는다(`not/SFR-018_faq/` 꼴). 시작
> 커맨드·환경변수·포트는 **그대로**다. 그 판본은 정본에 `openai` SDK 전송과 스트리밍
> 셋(`/polish/stream`·`/translate/stream`+`/finalize`·`/generate/stream`)이 얹힌 것이고,
> 근거는 `not/README.md` 다. **`openai>=1.30` 이 네 `requirements.txt` 에 추가되고
> `LLM_MODEL_ID`(기본 `default`)를 다시 쓴다** — SDK 가 `model` 없이 요청을 만들지
> 않는다. MCP 넷·전처리기 2벌·워크플로우 스텝은 `onprem/` 그대로다.

| # | 저장소 경로 | 기능 | 시작 커맨드 |
|---|---|---|---|
| 1 | `onprem/codeserving/SFR-006_template_fill/` | HWPX 템플릿 채우기 | `uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT` |
| 2 | `onprem/codeserving/SFR-018_text_polish/` | 글다듬이 | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| 3 | `onprem/codeserving/SFR-018_translation/` | 번역 | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| 4 | `onprem/codeserving/SFR-018_faq/` | FAQ 생성 | `uvicorn faq.main:app --host 0.0.0.0 --port $PORT` |

> **006 과 FAQ 는 시작 커맨드 등록이 필수다.** 가이드 6.2 의 자동 실행 경로는 저장소 루트의
> `main.py` 를 찾는데 이 둘의 진입점은 패키지 안(`template_fill/main.py`·`faq/main.py`)이라
> 걸리지 않는다. **`main:app` 을 이 둘에 쓰면 기동 실패한다.**
> 글다듬이·번역은 루트에 `main.py` 가 있어 자동 경로를 탄다.

저장소를 하나로 두고 하위 디렉토리를 쓰면 가이드에 "이 디렉토리를 루트로 본다" 항목이
**없으므로** 커맨드가 흡수해야 한다:

```
BUILD : pip install -r onprem/codeserving/SFR-006_template_fill/requirements.txt
RUN   : cd onprem/codeserving/SFR-006_template_fill && \
        uvicorn template_fill.main:app --host 0.0.0.0 --port $PORT
```

⚠️ **실물에서 확인할 것 하나**: 빌드·시작 커맨드가 셸을 거치는지(`cd A && B` 가 먹는지).
안 먹으면 `uvicorn --app-dir <경로> …` 로 바꾼다. 그 전까지 저장소를 쪼개지 않는다.

### 단위별 필수 환경변수

**공통(네 단위 전부)**: `GENOS_URL` `LLM_SERVING_ID` `GENOS_TOKEN`.
**`LLM_MODEL_ID` 는 2026-09-07 에 없어졌다** — 서빙 경로가 이미 모델을 결정한다.
mock 경로를 제거했으므로 빠지면 첫 LLM 호출에서 오류가 난다. 선택 변수 전체 목록과
의미는 `../README.md` "기능별 추가 설정".

| 단위 | 공통 외 **필수** | 상태 저장 |
|---|---|---|
| 006 | `TEMPLATE_FILL_TEMPLATE_DIR`(공유 볼륨) · `REDIS_URL` | Redis |
| 글다듬이 | 없음 | **무상태** (Redis·볼륨 불필요) |
| 번역 | 용어사전을 쓸 때만: `TRANSLATE_GLOSSARY_API_URL` · `TRANSLATE_GLOSSARY_DRIVE_ID` · `TRANSLATE_GLOSSARY_WORKSPACE_ID` (+ 토큰이 다르면 `TRANSLATE_GLOSSARY_TOKEN`) | 무상태 |
| FAQ | `REDIS_URL` | Redis |

> **006·FAQ 는 워크플로우 pod 와 코드서빙 pod 가 같은 Redis 를 봐야 한다.** 다운로드가
> 대화에서 모은 값을 읽는 유일한 통로다. 006 은 `TEMPLATE_DIR` 볼륨도 양쪽에 **같은
> 경로로** 마운트돼야 한다.

**018 세 단위 공통 선택 변수 — 결과 파일 업로드** (2026-08-28)

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `GENOS_CDN_UPLOAD_URL` | `http://llmops-cdn-api-service:8080/minio/upload/temp` | 결과 txt 를 올릴 곳 |
| `GENOS_CDN_HOSTNAME` | `https://genos.genon.ai` | presigned URL 에 박힐 외부 호스트 (업로드 폼의 `hostname` 필드) |

둘 다 기본값이 있어 **안 넣어도 뜬다.** 다만 배포마다 호스트가 다를 수 있고, 잘못 잡히면
`download_url` 이 계속 `None` 으로 나간다 — 그때도 결과는 정상 전달되므로(fail-open)
**증상이 "파일만 못 받는다" 로만 드러난다.** 등록 뒤 한 번은 링크를 눌러 볼 것.

**긴 문서 처리 — 선택 변수 셋** (2026-08-29)

| 변수 | 기본값 | 단위 | 뜻 |
|---|---|---|---|
| `FAQ_MAX_CONTEXT_CHARS` | `12000` | FAQ | 조각 하나 = LLM 호출 한 번의 예산 |
| `FAQ_MAX_CONTEXT_CHUNKS` | `80` | FAQ | 조각 수 상한(80 × 12,000 ≈ 96만 자). 문서 길이가 곧 LLM 비용이 되지 않게 막는 최후 방어선이고, **여기 걸린 문서만** 뒤가 잘린다 |
| `FAQ_LLM_CONCURRENCY` | `6` | FAQ | 동시에 도는 구간 수 (2026-09-09) |
| `POLISH_MAX_CHUNK_CHARS` | `6000` | 글다듬이 | 조각 하나 = LLM 호출 한 번의 예산 |
| `POLISH_LLM_CONCURRENCY` | `4` | 글다듬이 | 동시에 도는 조각 수 |

셋 다 기본값이 있어 **안 넣어도 뜬다.** 다만 **실물 LLM 없이 정한 값**이라, 게이트웨이
대기시간을 보고 조정해야 할 수 있다 — 글다듬이 조각은 `RES_TIMEOUT`(90초) 안에 끝나야
하고, 429 가 나면 `POLISH_LLM_CONCURRENCY`·`FAQ_LLM_CONCURRENCY` 부터 내린다.

> 이 호출은 게이트웨이를 지나지 않는다. 가이드 11.5.8 이 막는 것은 **LLM·MCP·코드서빙**
> 호출이고 CDN 은 게이트웨이 경로가 없다. **글다듬이는 이 변경 뒤에도 무상태다** —
> 파일을 CDN 이 들고 있어서 Redis 를 새로 붙이지 않았다.

### 확인

`GET /health` → 200. 네 단위 모두 `GET /` 와 `GET ""` 도 등록돼 있다(게이트웨이가 경로
없이 베이스를 때리는 배포 대비).

**health 200 만으로 배포 완료로 보지 않는다** — 가이드 11.3 이 정상 입력·입력 오류(422)·
외부 timeout(504)을 각각 실행하라고 요구한다. `test/verify_serving.py` 가 앞의 셋을
자동으로 때린다(timeout 은 수동). 올리기 **전에** `test/check_deploy_contract.py`.

주요 업무 경로 (전체 표는 `../README.md`):

| 단위 | 경로 |
|---|---|
| 006 | `/chat/context` `/chat/extract` `/chat/commit` · `/templates` `/fields` `/status` `/preview` `/values` `/blocks` `/generate` `/generate/upload` |
| 글다듬이 | `/policies` `/polish` |
| 번역 | `/languages` `/translate` `/translate/markdown` `/translate/hwpx` `/glossary` `/glossary/reload` |
| FAQ | `/config` `/generate` `/generate/upload` `/faqs` `/download` |

---

## §2. MCP 도구 4개 (area 01)

**⚠️ MCP 는 서빙이 아니라 파일이다.** GenOS 가 **소스 파일 한 개**를 받아 실행하고 `mcp`
객체를 런타임이 전역으로 주입한다. **FastAPI 앱도 `/health` 도 `$PORT` 도 시작 커맨드도
`requirements.txt` 도 없다.** 디렉토리를 올리는 것이 아니라 파일 네 개를 **각각** 등록한다.

| # | 파일 | 접두어 | 도구 | 개수 |
|---|---|---|---|---|
| 5 | `onprem/mcp/genon_text_guard.py` | `TG` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` | 4 |
| 6 | `onprem/mcp/genon_lang_policy.py` | `LP` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 6 |
| 7 | `onprem/mcp/genon_glossary.py` | `GL` | `glossary_lookup` `glossary_status` `glossary_reload` | 3 |
| 8 | `onprem/mcp/genon_pii_audit.py` | `PA` | `pii_audit` `pii_scan_text` `pii_detectors` | 3 |

**도구 카탈로그를 손으로 적지 않는다.** `@mcp.tool()` 이 시그니처·타입힌트·독스트링에서
카탈로그를 만든다. 2026-08-14 까지 네 파일에 JSON-Schema 목록(`*TOOL_SPECS`, 합계 196줄)이
남아 있었는데 **아무 데서도 읽히지 않았고**, 고쳐도 노출되는 스키마가 바뀌지 않았다 —
고친 사람은 바뀐 줄 안다. 지웠다. 도구 설명을 고칠 곳은 각 도구 함수의 독스트링이다.

**파일 하나에 `@mcp.tool()` 이 여러 번 나오는 것이 정상이다.** 등록(카탈로그)과
호출(`tools/call` 은 이름 하나)이 다른 층이다 — 서버 하나가 도구 여러 개를 노출하고,
LLM 이 매 호출마다 그중 하나를 고른다.

### 환경변수

| 파일 | 환경변수 |
|---|---|
| `genon_glossary.py` | `TRANSLATE_GLOSSARY_API_URL` · `_DRIVE_ID` · `_WORKSPACE_ID` (+ `_TOKEN`). 셋 중 하나라도 없으면 **용어사전 없이 동작**하고 그 사실이 `glossary_status` 의 `reason` 으로 드러난다 |
| 나머지 셋 | **없다** — 전부 결정적 도구고 LLM 도 부르지 않는다. `genon_lang_policy` 는 2026-09-07 부터 admin-api 도 부르지 않는다(§2-2) |

**네 파일 모두 stdlib 만 쓴다** (2026-09-07). `lxml` 을 파일 안에서 설치하던
`genon_hwpx_text.py` 가 빠졌으므로 **폐쇄망 mirror 접근이 없어도 MCP 넷은 다 뜬다.**

### 확인 — **도구 16개가 다 나오는지 센다**

등록 뒤 `tools/list` 에 **16개**(`TG` 4 + `LP` 6 + `GL` 3 + `PA` 3)가 다 있어야 한다.
(`TG` 는 2026-08-18 에 5 → 4 가 됐다 — 호출부 0건이던 `evidence_check` 를 뺐다.
`HX` 1 은 2026-09-07 에 파일째 빠졌다 — 캔버스 첨부가 전처리기 산출물만 쓰게 되면서
`hwpx_to_markdown` 의 운영 호출부가 0건이 됐고, **아무도 안 부르는 파싱 사본은
갈리기만 한다.** 되살릴 코드는 `git show HEAD:onprem/mcp/genon_hwpx_text.py`.)
**하나라도 비면 이름이 겹쳐 덮인 것이다** — 한 서버에 여러 도구 파일이 함께 로드될 수
있고, 그 실패는 "도구가 이상한 값을 낸다" 로만 드러난다. 그래서 도구 함수를 뺀 모든
최상위 심볼에 접두어가 붙어 있다. 규율은 [`../mcp/README.md`](../mcp/README.md),
기계적 확인은 `test/check_mcp_tools.py`.

---

## §2-1. hwpx 전처리기 1개 (area 05)

| # | 파일 | 등록 형태 | 확인 |
|---|---|---|---|
| 9 | `onprem/preprocessor/final_preprocessor.py` | 전처리기(**적재용**) — 소스 파일 한 개 | hwpx 적재 후 검색 결과에서 **표가 살아 있는지** |
| 10 | `onprem/preprocessor/only_me.py` | 전처리기(**질의 시 첨부용**) — 소스 파일 한 개 | 첨부 후 `genosUploaded` 에 **조문·표 머리말이 없는지** |

- **둘은 소비자가 다르다** (2026-09-07 추가). #10 은 임베딩·검색용이라 본문에 조문
  머리말·표 조각 머리말·겹침을 넣고, #11 은 네 기능이 **LLM 에 그대로 던지는** 원문이라
  그 가공을 하지 않는다(청킹 자체가 없다). 첨부에 #10 을 걸면 번역이 원문에 없던 머리말을
  번역해 결과물에 싣고 FAQ 는 그것을 근거로 대조한다 — 오류가 아니라 **결과물의 내용으로만**
  드러난다. 근거는 `../preprocessor/README.md` "첨부용은 청킹하지 않는다".
- **같은 서버에 둘을 함께 올리지 않는다.** 진입점 이름이 둘 다 `DocumentProcessor` 라
  나중에 로드된 것이 앞엣것을 덮는다.

- **`__init__.py` 는 올리지 않는다.** 로컬 테스트가 `import preprocessor` 로 쓰라고 둔
  얇은 재노출 파일이고, 등록 단위는 `final_preprocessor.py` 하나다(그래서 이 파일은 다른
  파일을 import 하지 않는다).
- **연결(매핑)이 등록만큼 중요하다.** 등록 화면에서 **받을 확장자를 고를 수 있다**
  (2026-08-14 확인). 이 전처리기에는 **`hwpx` 만** 건다:

  | 전처리기 | 확장자 | 비고 |
  |---|---|---|
  | **적재용(#9)** | `hwpx` | 표를 살려 청킹한다 |
  | 지능형·첨부용 (기존, 그대로 둔다) | `pdf` `docx` `xlsx` `hwp` … | **`hwp` 는 이쪽이다** — 우리 파서는 zip 기반 hwpx 전용이라 구버전 바이너리를 못 연다 |

  매핑을 안 하면 예전대로 지능형(PDF 변환)이 hwpx 를 받고 **표 안 수치가 깨진다** —
  이 전처리기를 만든 이유가 그것이다. 반대로 `hwpx` 아닌 확장자가 이쪽으로 오면 즉시
  예외를 던진다(`SUPPORTED_EXTENSIONS`) — 잘못 건 매핑이 조용히 이상한 결과를 내지
  않게 남겨 둔 그물이다.
- **확장자 설정을 바꾸면 `needs_reingest` 다**(§F, 자동 재적재 아님). 매핑을 확정한 뒤
  hwpx 를 올린다.
- **지능형 전처리기를 이 파일에 이식하지 않는다.** 확장자를 고를 수 있으므로 이유가
  없고 대가만 크다 — 근거는 `../preprocessor/README.md`.
- **등록 화면에서 정하는 값**: `chunk_size`/`chunk_overlap`(기본 1000/100 은 **임시값** —
  임베딩 모델 컨텍스트에 맞춘다), `security_level`(배포별 필드면 `extra_metadata`).
- **#9(적재용)는 네 기능과 배선이 없다.** 워크플로우 스텝이 부르지 않으므로 §3 의 ID 표에
  들어가지 않는다 — 검색(RAG) 쪽에서만 쓰인다.
- **#10(첨부용)은 네 기능 전부의 입력이다** (2026-09-07). 스텝이 부르는 것이 아니라
  플랫폼이 첨부를 이 전처리기로 지나게 하고, 그 산출물이 캔버스 변수 `genosUploaded`
  로 스텝에 들어온다. 그래서 여기에도 ID 를 꽂을 자리가 없지만 **매핑을 안 하면 네
  기능의 파일 첨부가 통째로 동작하지 않는다**(원문이 비어 `NO_INPUT`).

---

## §2-2. 톤·문서유형 프롬프트 (선택 — 문구를 재배포 없이 고칠 때)

**등록 개수에 포함되지 않는다.** 코드 서빙·MCP·전처리기 10개와 달리 이건 **리소스**이고,
안 만들어도 네 단위는 이미지에 든 `.j2` 와 내장 표로 정상 동작한다.

> **2026-09-07 에 방식이 바뀌었다 — JSON 문서 한 건 → 이름=ID 매칭.**
>
> 그전에는 프롬프트 **한 건**의 본문에 `{"tones": [...], "doc_types": [...]}` 를 담고
> 글다듬이 코드서빙과 MCP 가 각각 `json.loads` 로 읽었다
> (`POLISH_POLICY_PROMPT_ID`·`LANG_POLICY_PROMPT_ID`). 요구가 **"프롬프트는 전부
> 라이브러리에서 당겨 쓰되 코드서빙 안에서 JSON 을 해석하지 않는다"** 로 바뀌어
> 그 경로를 걷어냈다. **옛 환경변수 둘은 읽지 않는다** — 남아 있으면 글다듬이가
> `event=policy_legacy_env_ignored` 로 알린다.
>
> **MCP `genon_lang_policy` 는 이제 admin-api 를 아예 부르지 않는다.** 톤 프롬프트를
> 받는 것은 글다듬이 코드서빙이고, MCP 가 하는 일은 표로 하는 **강제 톤 판정**뿐이다.

### 이름 규약 — §2-3 과 **같은 매핑**에 담는다

톤·문서유형이라고 따로 환경변수를 두지 않는다. `POLISH_PROMPT_IDS` 하나에 이름=ID 로
넣으면 된다 — 그래야 `GET /prompts` 하나가 모든 문장의 출처를 답하고,
`POST /prompts/reload` 하나가 전부 비운다.

| 이름 | 본문 | 무엇을 덮나 |
|---|---|---|
| `system` | 시스템 프롬프트 골격 | `system.j2` |
| `system_<톤코드>` | **그 톤 전용 시스템 프롬프트** | 있으면 골격 대신 이것을 쓴다 |
| `doc_type_<문서유형코드>` | 문서유형 추가 지시문 | 내장 표의 `extra_instruction` |

```
POLISH_PROMPT_IDS=system=43,system_polite=51,system_objective=54,doc_type_debt_reason=62
```

톤 코드는 `polite` `friendly` `clear` `objective`, 문서유형 코드는 `email` `post`
`customer_notice` `debt_reason` `reviewer_opinion` 이다 (`GET /policies` 가 그대로 낸다).

> **프로토타입 시연분은 코드에 적혀 있다** (2026-09-07). 온프레미스에서 만든 톤 프롬프트
> 번호 넷을 `config.TONE_PROMPT_IDS` 에 적어 뒀다 — `objective=100` · `clear=97` ·
> `friendly=94` · `polite=91`. **등록 화면에 같은 이름을 넣으면 그쪽이 이기므로**
> 최종적으로는 환경변수로 옮기면 되고(§10.5), 그때 코드 표를 비우지 않아도 된다.
> `DOC_TYPE_PROMPT_IDS` 는 문서유형 5종이 **빈 값**으로 자리만 잡혀 있다 —
> **빈 값은 매핑에서 통째로 빠지므로**(`prompt_ids_raw` 가 거른다) 프롬프트를 만든 뒤
> 번호만 채우면 된다.

- **본문은 JSON 이 아니라 문장 그대로**다. `system_<톤>` 은 `{{ doc_type_label }}`·
  `{{ doc_type_instruction }}` 을 쓸 수 있고, 변수 이름은 `onprem/prompt/
  SFR-018_text_polish/system.j2` 머리말에 적혀 있다.
- **안 적은 이름은 그냥 안 덮인다** — 톤 넷 중 하나만 등록해도 나머지 셋은 `system.j2` +
  내장 톤 지시문으로 돈다. **폴백이 살아 있는 것이 요점이다**: 이름만 보고 골랐다가
  `system_objective.j2` 파일이 없어 요청이 서면 **톤 하나를 안 만들었다는 이유로
  글다듬이가 통째로 죽는다.**
- **지시문은 한국어로 쓴다** (2026-09-03 요구 확정).

### 못 하게 된 것 둘 — 대체 수단과 함께

ID 하나는 **본문 하나**를 가리킨다. 문장이 아닌 값은 담을 수 없다(담으려면 본문에 형식을
만들어야 하고, 그것이 방금 걷어낸 JSON 이다).

| 못 하는 것 | 그전(JSON) | 지금 |
|---|---|---|
| **톤·문서유형 추가** | `{"code": "legal", "label": "법무체", …}` | 개발자가 `text_polish/tone_presets.py` 표에 넣는다 (+ eval `TONE_RULES`) |
| **내장 톤 감추기** | `{"code": "friendly", "disabled": true}` | 없다. 필요해지면 환경변수로 받는다(본문에 형식을 만들지 않는다) |
| **새 문서유형의 강제 톤** | `"forced_tone": "legal"` | 표에만 있다 |

**내장 항목의 문구를 고치는 것**(요구의 본체)은 그대로 된다.

### 환경변수

| 어디 | 변수 | 값 |
|---|---|---|
| 글다듬이 코드서빙 (#2) | `GENOS_ADMIN_API_URL` | 내부 `http://llmops-admin-api-service:8080` / 외부 `https://<host>/api/admin` |
| | `POLISH_PROMPT_IDS` | 위 이름=ID 목록 |
| MCP `genon_lang_policy` (#6) | **없다** | admin-api 를 부르지 않는다 |

### 확인

```
GET  {글다듬이}/prompts          → 이름마다 source: "prompt_library" | "file" + reason
POST {글다듬이}/prompts/reload   → 리비전을 운영 반영한 뒤 즉시 반영 (안 부르면 최대 60초)
GET  {글다듬이}/policies         → 톤 4 · 문서유형 5 (이 목록은 **표에서** 온다)
```

`source` 가 `file` 이면 그 이름은 아직 안 덮였다. `reason` 을 본다 —
`not_configured`(ID 를 안 적었다) · `fetch_failed_404`(ID 오기입) · `empty_body` ·
`api_error` · `fetch_failed`. 이 구분이 없으면 "안 넣었다" 와 "못 읽었다" 가 화면에서
똑같이 옛 문구로 보인다. **`/prompts` 는 본문을 싣지 않는다** (3.8절).

`POST /policies/reload` 는 **`/prompts/reload` 의 별칭**으로 남겨 뒀다 — 화면·운영 문서가
그 경로를 쥐고 있어 없애면 404 가 "리로드했는데 안 바뀐다" 로 보인다.

### 한계 — **평가 채점은 따라오지 않는다**

`eval` 은 배포 단위를 import 하지 않으므로(파서를 공유하면 파서 버그를 함께 놓친다)
표에 없는 톤의 종결어미·금지표현 규칙을 알 수 없다. 그 톤으로 만든 결과물은
`tone_pass_rate` 의 **`skipped`** 에 담기고 합격률 분모에서 빠진다. 채점하려면
`onprem/eval/eval_mcp/tone_metrics.py` 의 `TONE_RULES` 에 규칙을 함께 넣어야 한다.

## §2-3. 프롬프트 **본문**을 라이브러리에 올린다 (선택 — 2026-09-03)

§2-2 가 **톤·문서유형 목록**을 라이브러리에서 받는 경로라면, 이쪽은 **프롬프트 문장
자체**다. 자주 손보는 지시문(006 항목 매핑, FAQ 생성 지시, 번역·글다듬이 문체 지시)을
재배포 없이 고치기 위한 것이고, **고정 골격(시스템 프롬프트)은 파일로 둬도 된다.**

### 1) 프롬프트를 만든다

`도구 > 프롬프트 라이브러리` 에서 프롬프트를 만들고 본문에 **jinja 템플릿 문장**을 넣는다
(§2-2 와 달리 JSON 이 아니다). 변수 이름은 지금 `.j2` 파일이 쓰는 것과 같아야 한다 —
`onprem/prompt/<단위>/*.j2` 의 머리말에 변수 목록이 적혀 있다.

- **문서유형·톤 지시문은 한국어**로 쓴다. 산출물의 어투를 통제하는 문장이라 지시 언어가
  섞이면 모델이 어휘를 헷갈린다 (요구 확정 2026-09-03).
- **시스템 프롬프트도 한국어로 쓴다** (2026-09-03 요구 확정). 예전에는 구조·형식·금지
  조항을 영어로 두는 규약이었다 — 라이브러리에 올릴 때도 한국어로 적는다.
- 변수 이름을 잘못 쓰면 **그 이름만 파일로 폴백**한다(요청은 죽지 않는다). 그 사실은
  `GET /prompts` 의 `source: "file"` 과 `event=prompt_library_render_failed` 로 드러난다.

### 2) 환경변수 — 이름=ID 로 꽂는다

| 어디 | 변수 | 값 |
|---|---|---|
| 네 코드서빙 공통 | `GENOS_ADMIN_API_URL` | §2-2 와 **같은 값** |
| 006 (#1) | `TEMPLATE_FILL_PROMPT_IDS` | `extract_user=41,document_user=42` |
| 글다듬이 (#2) | `POLISH_PROMPT_IDS` | `system=43` |
| 번역 (#3) | `TRANSLATE_PROMPT_IDS` | `system_batch=44,user_batch=45` |
| FAQ (#4) | `FAQ_PROMPT_IDS` | `system=46,user=47` |

**이름은 `.j2` 파일 이름에서 확장자를 뗀 것**이다(`extract_user.j2` → `extract_user`).
JSON 표기(`{"extract_user": "41"}`)도 받는다. 안 적은 이름은 파일을 쓴다 — **미설정은
오류가 아니라 정상 경로다.**

### 3) 확인

```
GET  {서빙}/prompts         → 이름마다 source: "prompt_library" | "file" + reason
POST {서빙}/prompts/reload  → 리비전을 운영 반영한 뒤 즉시 반영 (안 부르면 최대 60초)
```

`source` 가 `file` 이면 그 이름은 **아직 파일로 돌고 있다.** `reason` 을 본다 —
`not_configured`(ID 를 안 적었다) · `fetch_failed_404`(ID 오기입) · `empty_body`(본문이
비었다) · `api_error` · `fetch_failed`. 이 구분이 없으면 "안 넣었다" 와 "못 읽었다" 가
화면에서 똑같이 옛 문구로 보인다.

**`/prompts` 는 본문을 싣지 않는다** (3.8절) — 이름·ID·사유뿐이다.

**관리자 토큰**: `/prompts/reload` 는 006·번역·FAQ 에서 `X-Admin-Token` 을 요구한다
(그 단위들이 이미 토큰을 갖고 있다). 글다듬이는 토큰 자체가 없는 단위라 열려 있다 —
`POST /policies/reload` 와 같은 규약이다.

## §3. 등록해서 얻은 ID 를 어디에 넣나

**10번의 등록 중 코드서빙 4 + MCP 4 는 ID 를 워크플로우 스텝 환경변수에 꽂아야** 캔버스가
이쪽을 부른다 (전처리기는 스텝이 부르지 않아 여기 없다). 이 배선이 빠지면 그 스텝은 `CONFIG_MISSING` 으로 즉시 끝난다 (시크릿 기본값 없음).

| 환경변수 | 가리키는 등록 | 필요한 스텝 |
|---|---|---|
| `TEMPLATE_FILL_SERVING_ID` | 코드서빙 #1 | 006-1·2·3 |
| `TEXT_POLISH_SERVING_ID` | 코드서빙 #2 | 다듬-2 |
| `TRANSLATION_SERVING_ID` | 코드서빙 #3 | 번역-2 |
| `FAQ_SERVING_ID` | 코드서빙 #4 | FAQ-1·2 |
| `TEXT_GUARD_MCP_ID` | MCP #5 | 다듬-2, 번역-2 |
| `LANG_POLICY_MCP_ID` | MCP #6 | 다듬-1, 번역-1 |

**스텝이 찾는 MCP ID 는 이 둘뿐이다.** `GL`(MCP #7, 용어사전)은 어느 스텝도 부르지
않는다 — 번역 코드서빙이 자체 `glossary_exact.py` 로 처리한다. 등록해 두면 다른
워크플로우에서 쓸 수 있다. `PA`(MCP #8, PII 감사)도 스텝이 부르지 않는다 —
**사람이 직접 부르는 집계 도구**다(야간·주간 단위. 스케줄러를 넣지 않는 것이 결정이다).

`HWPX_TEXT_MCP_ID` 는 **없어졌다** (2026-09-07) — 첨부 문서는 전처리기 산출물
`genosUploaded` 로만 받는다.

스텝 9개 목록·순서는 [`../workflow/README.md`](../workflow/README.md).

---

## §4. 등록만으로는 안 되는 것 — 빠뜨리면 **조용히 반쪽이 된다**

| 전제 | 빠지면 | 조달 방법 |
|---|---|---|
| `onprem/prompt/<단위>/` 가 **이미지에** 들어가야 한다 | 기동은 되고 첫 LLM 호출에서 `PromptRenderError` | 배포 단위 밖이라 파일 목록에 안 잡힌다. 마지막에 따로 챙긴다. **코드서빙 4개 이미지에만 넣는다** — 워크플로우 스텝은 `jinja2` 를 쓸 수 없어 프롬프트를 렌더하지 않는다(재배치 전에는 006·FAQ 가 02·03 양쪽이었다) |
| 사내 PyPI registry/mirror | 빌드 커맨드가 그 자리에서 멈춘다 | 운영팀 확인 (가이드 11.5.6) |
| 006·FAQ 가 **같은 Redis** | 대화는 되는데 다운로드가 빈 문서를 만든다 | `REDIS_URL` 을 양쪽 pod 에 같게 |
| 006 `TEMPLATE_DIR` **같은 경로 마운트** | 템플릿을 못 찾는다 | 공유 볼륨 |
| ~~`genon.preprocessor` (코드서빙 이미지)~~ | **전제가 아니게 됐다** (2026-08-14) | 006 의 PDF 다운로드를 걷어내며 마지막 사용처가 사라졌다. **이미지가 제공해야 하는 패키지를 요구하는 코드서빙 단위는 이제 없다** |
| ~~FAQ hwpx 템플릿 실물~~ | **전제가 아니게 됐다** (2026-08-12) | 018 세 기능의 산출 형식이 txt 로 통일돼 hwpx·pdf·xlsx 내보내기를 걷어냈다. 파일을 내기 위해 환경에 무언가를 요구하는 018 단위는 없다 |

워크플로우 pod 기본 이미지는 **더 이상 전제가 아니다** — 2026-08-11 재배치로 스텝이 쓰는
외부 패키지가 `httpx` 하나가 됐고 그것은 기본 이미지에 있다. **워크플로우 이미지에
추가되는 패키지가 0개**다.

---

## §5. 순서

코드서빙 → 템플릿 등록·확인 → MCP → 워크플로우 → 끝단 통과. **워크플로우를 먼저 올리면
대화는 되는데 다운로드가 죽은 상태로 시작한다.** 전처리기(#9)는 이 사슬 **밖**이라 아무
때나 끼운다. 각 단계에서 무엇을 눈으로 확인하는지는 `../README.md` "옮기는 순서" 가
정본이고, **무엇을 올리고 무엇이 필요한지는 [`../ONPREM.md`](../ONPREM.md)** 다.

올리기 전에 로컬에서:

```
python onprem/test/check_deploy_contract.py   # 빌드·기동 계약 (코드서빙 4 + eval + 스텝 9 + MCP 5)
python onprem/test/check_service_boot.py      # 코드서빙 4단위 실제 기동
python onprem/test/check_mcp_tools.py         # MCP 파일 5개 공존·도구 판정
```
