# 서빙 등록 목록 — onprem 에서 **무엇을 등록하는가**

> 이 문서는 **등록 작업지시서**다. GenOS 화면에 무엇을 몇 번 만들고 각 칸에 무엇을 적는지만
> 담는다. 환경변수의 **의미**와 기능별 운영 규약은 [`../README.md`](../README.md) 가
> 정본이고 여기서 복사하지 않는다 (`docs/README.md` 중복 금지 규칙).

## 결론 — 등록은 **8번**이다

| 영역 | 무엇을 등록하나 | 개수 | 등록 형태 |
|---|---|---|---|
| 03 | `codeserving/` 의 디렉토리 | **4** | 코드 서빙 (컨테이너 1개 = URL 1개) |
| 01 | `mcp/` 의 **소스 파일** | **4** | MCP 도구 (파일 1개 = 등록 단위) |

**코드 서빙 하나 = 컨테이너 하나 = URL 하나**이고 리비전·환경변수·복제본이 전부 서빙
단위로 붙는다. 저장소를 어떻게 두든 이 숫자는 줄지 않는다.

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
| `preprocessor/` | ❌ | **아직 어디에도 배선돼 있지 않다.** VDB 적재용 미래 부품 (`preprocessor/README.md`) |
| `docs/`, `*.md` | ❌ | 문서 |

---

## §1. 코드 서빙 4개 (area 03)

네 칸 모두 리비전 상세 > **환경 설정** 에 넣는다. `LANGUAGE` 는 `python`,
빌드 커맨드는 **네 단위 모두 같다**.

```
BUILD : pip install -r requirements.txt
```

시작 커맨드만 다르다 — **단위마다 진입점 위치가 다르기 때문이다.**

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

**공통(네 단위 전부)**: `GENOS_URL` `LLM_SERVING_ID` `LLM_MODEL_ID` `GENOS_TOKEN`.
mock 경로를 제거했으므로 빠지면 첫 LLM 호출에서 오류가 난다. 선택 변수 전체 목록과
의미는 `../README.md` "기능별 추가 설정".

| 단위 | 공통 외 **필수** | 상태 저장 |
|---|---|---|
| 006 | `TEMPLATE_FILL_TEMPLATE_DIR`(공유 볼륨) · `REDIS_URL` | Redis |
| 글다듬이 | 없음 | **무상태** (Redis·볼륨 불필요) |
| 번역 | 없음 (`TRANSLATE_GLOSSARY_PATH` 는 용어사전 쓸 때만) | 무상태 |
| FAQ | `REDIS_URL` (`FAQ_HWPX_TEMPLATE_PATH` 는 hwpx 다운로드 쓸 때만) | Redis |

> **006·FAQ 는 워크플로우 pod 와 코드서빙 pod 가 같은 Redis 를 봐야 한다.** 다운로드가
> 대화에서 모은 값을 읽는 유일한 통로다. 006 은 `TEMPLATE_DIR` 볼륨도 양쪽에 **같은
> 경로로** 마운트돼야 한다.

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
| 5 | `onprem/mcp/genon_text_guard.py` | `TG` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` `evidence_check` | 5 |
| 6 | `onprem/mcp/genon_lang_policy.py` | `LP` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 6 |
| 7 | `onprem/mcp/genon_glossary.py` | `GL` | `glossary_lookup` `glossary_status` `glossary_reload` | 3 |
| 8 | `onprem/mcp/genon_hwpx_text.py` | `HX` | `hwpx_to_markdown` | 1 |

**파일 하나에 `@mcp.tool()` 이 여러 번 나오는 것이 정상이다.** 등록(카탈로그)과
호출(`tools/call` 은 이름 하나)이 다른 층이다 — 서버 하나가 도구 여러 개를 노출하고,
LLM 이 매 호출마다 그중 하나를 고른다.

### 환경변수

| 파일 | 환경변수 |
|---|---|
| `genon_glossary.py` | `TRANSLATE_GLOSSARY_PATH` (없으면 **용어사전 없이 동작**하고 그 사실이 `glossary_status` 로 드러난다) |
| 나머지 셋 | **없다** — 전부 결정적 도구고 LLM 도 부르지 않는다 |

`lxml` 이 필요한 `genon_hwpx_text.py` 는 `requirements.txt` 를 쓸 수 없으므로 **파일 안에서
직접 설치한다.** 폐쇄망 mirror 접근이 없으면 이 파일만 실패한다.

### 확인 — **도구 15개가 다 나오는지 센다**

등록 뒤 `tools/list` 에 **15개**(`TG` 5 + `LP` 6 + `GL` 3 + `HX` 1)가 다 있어야 한다.
**하나라도 비면 이름이 겹쳐 덮인 것이다** — 한 서버에 여러 도구 파일이 함께 로드될 수
있고, 그 실패는 "도구가 이상한 값을 낸다" 로만 드러난다. 그래서 도구 함수를 뺀 모든
최상위 심볼에 접두어가 붙어 있다. 규율은 [`../mcp/README.md`](../mcp/README.md),
기계적 확인은 `test/check_mcp_tools.py`.

---

## §3. 등록해서 얻은 ID 를 어디에 넣나

**8번의 등록이 끝나면 각 서빙 ID 를 워크플로우 스텝 환경변수에 꽂아야** 캔버스가 이쪽을
부른다. 이 배선이 빠지면 그 스텝은 `CONFIG_MISSING` 으로 즉시 끝난다 (시크릿 기본값 없음).

| 환경변수 | 가리키는 등록 | 필요한 스텝 |
|---|---|---|
| `TEMPLATE_FILL_SERVING_ID` | 코드서빙 #1 | 006-1·2·3 |
| `TEXT_POLISH_SERVING_ID` | 코드서빙 #2 | 다듬-2 |
| `TRANSLATION_SERVING_ID` | 코드서빙 #3 | 번역-2 |
| `FAQ_SERVING_ID` | 코드서빙 #4 | FAQ-1·2 |
| `TEXT_GUARD_MCP_ID` | MCP #5 | 다듬-2, 번역-2 |
| `LANG_POLICY_MCP_ID` | MCP #6 | 다듬-1, 번역-1 |
| `HWPX_TEXT_MCP_ID` | MCP #8 | FAQ-1 |

`GL`(MCP #7, 용어사전)은 **지금 어느 스텝도 부르지 않는다** — 번역 코드서빙이 자체
`glossary_exact.py` 로 처리한다. 등록해 두면 다른 워크플로우에서 쓸 수 있다.

스텝 9개 목록·순서는 [`../workflow/README.md`](../workflow/README.md).

---

## §4. 등록만으로는 안 되는 것 — 빠뜨리면 **조용히 반쪽이 된다**

| 전제 | 빠지면 | 조달 방법 |
|---|---|---|
| `onprem/prompt/<단위>/` 가 **이미지에** 들어가야 한다 | 기동은 되고 첫 LLM 호출에서 `PromptRenderError` | 배포 단위 밖이라 파일 목록에 안 잡힌다. 마지막에 따로 챙긴다. **006·FAQ 는 02·03 두 이미지 모두** |
| 사내 PyPI registry/mirror | 빌드 커맨드가 그 자리에서 멈춘다 | 운영팀 확인 (가이드 11.5.6) |
| 006·FAQ 가 **같은 Redis** | 대화는 되는데 다운로드가 빈 문서를 만든다 | `REDIS_URL` 을 양쪽 pod 에 같게 |
| 006 `TEMPLATE_DIR` **같은 경로 마운트** | 템플릿을 못 찾는다 | 공유 볼륨 |
| `genon.preprocessor` (코드서빙 이미지) | PDF 다운로드만 **501**. hwpx 는 정상 | pip 불가·사용자 Dockerfile 도 표준 등록 단위 아님(6.3) → **기본 이미지 변경 절차**(11.5.6) |
| FAQ hwpx 템플릿 실물 | hwpx 다운로드만 **501** (가짜 문서를 만들지 않는다) | 사내 서식 파일 + `FAQ_HWPX_TEMPLATE_PATH` |

워크플로우 pod 기본 이미지는 **더 이상 전제가 아니다** — 2026-08-11 재배치로 스텝이 쓰는
외부 패키지가 `httpx` 하나가 됐고 그것은 기본 이미지에 있다. **워크플로우 이미지에
추가되는 패키지가 0개**다.

---

## §5. 순서

코드서빙 → 템플릿 등록·확인 → MCP → 워크플로우 → 끝단 통과. **워크플로우를 먼저 올리면
대화는 되는데 다운로드가 죽은 상태로 시작한다.** 각 단계에서 무엇을 눈으로 확인하는지는
`../README.md` "옮기는 순서" 가 정본이다.

올리기 전에 로컬에서:

```
python onprem/test/check_deploy_contract.py   # 빌드·기동 계약 (코드서빙 4 + eval + 스텝 9 + MCP 4)
python onprem/test/check_service_boot.py      # 코드서빙 4단위 실제 기동
python onprem/test/check_mcp_tools.py         # MCP 파일 4개 공존·도구 판정
```
