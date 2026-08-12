# 인수인계 — 영역 재배치 마무리 (2026-08-11)

> **이 문서를 먼저 읽고, 그다음 `ARCHITECTURE_SPLIT.md`(설계·실행 기록) → `README.md`(운영
> 규약) 순으로 본다.** 저장소 전체의 진입 문서는 루트 `CLAUDE.md` 다.
>
> 이 문서의 목적은 하나다 — **다음 사람이 어디서부터 이어서 하면 되는지.**
> 끝난 것을 다시 확인하느라 시간을 쓰지 않게, "무엇이 어디까지 검증됐는지" 를 그 검증
> **방법과 함께** 적는다. "통과했다" 만 적으면 무엇을 통과한 것인지 알 수 없다.

---

## 1. 지금 상태 한 줄

**영역 재배치가 끝났고, 서버·LLM 없이 확인 가능한 범위는 전부 통과한다.**
남은 것은 전부 **실물(게이트웨이·Redis·한/글)이 있어야 확인되는 것**이다.

```
onprem/
  workflow/      area 02 — 캔버스 파이썬 스텝 9개 (파일 1개 = 스텝 1개)
  mcp/           area 01 — MCP 도구 파일 4개 (LLM 없는 결정적 도구, 파일 1개 = 등록 단위)
  codeserving/   area 03 — HTTP 배포 단위 4개 (LLM·프롬프트·Redis·lxml·볼륨)
  prompt/ eval/ test/ docs/
```

**등록 단위는 8개**(코드서빙 4 + MCP 4), **저장소는 1개**로 간다. 근거는 §5.

---

## 2. 이번에 한 일

### 2-1. 재배치의 잔여 작업을 끝냈다

디렉토리 이동은 이미 돼 있었고, **이동 명세의 뒷부분이 남아 있었다.** 지운 것:

| 지운 파일 | 이유 |
|---|---|
| `codeserving/SFR-006_template_fill/template_fill/run_chat.py` | 역할이 `workflow/sfr006_0*.py` 로 갔다 |
| `codeserving/SFR-018_faq/faq/run_chat.py` | 역할이 `workflow/sfr018_faq_0*.py` 로 갔다 |
| `codeserving/SFR-018_text_polish/text_polish/main.py` | 02 진입점이었다. 이 단위는 03 이 됐다 |
| 같은 단위의 `markdown_guard.py`·`fact_guard.py`·`diff_report.py` | `mcp/genon_text_guard/` 로 갔다 |

**지웠다는 증거**: `check_deploy_contract.py` 에서 `main_socketio`(워크플로우 런타임)
WARN 이 세 단위 모두에서 사라졌다. 코드서빙이 워크플로우 런타임과 끊겼다는 뜻이다.

되살릴 일이 생기면 `git show HEAD:onprem/SFR-006_template_fill/template_fill/run_chat.py`
처럼 **이동 전 경로**로 꺼낸다.

### 2-2. 배포를 막는 결함 둘을 고쳤다 — 둘 다 조용히 죽는 종류였다

**(1) 프롬프트가 네 단위에서 동시에 사라져 있었다.**

네 `prompt_loader.py` 가 `dirname(unit_root)/prompt/<단위>` 라는 **고정 깊이**로 디렉토리를
찾고 있었다. 단위가 `onprem/codeserving/` 아래로 한 겹 내려가자 넷 다 빗나갔다.
증상은 "프롬프트 생성 실패" 라는 요청 실패 하나뿐이라 **디렉토리 이동이 원인이라는 것이
드러나지 않는다.**

→ **상위로 훑어 찾는 방식**으로 바꿨다(`_search_upward`, 깊이 6). 단위가 어느 깊이에 있든,
이미지에서 프롬프트를 단위 옆에 두든 같은 코드로 걸린다. 고친 파일 넷:

```
codeserving/SFR-006_template_fill/template_fill/prompt_loader.py
codeserving/SFR-018_text_polish/text_polish/prompt_loader.py
codeserving/SFR-018_faq/faq/prompt_loader.py
codeserving/SFR-018_translation/translation_pipeline/common/prompt_loader.py
```

**교훈**: 프롬프트 디렉토리는 배포 단위 **밖**이라 단위를 옮기면 같이 깨진다. 앞으로 단위를
옮길 때 이 넷을 먼저 확인할 것.

**(2) 톤 LLM 실패 사실이 HTTP 경계에서 유실됐다.**

`/chat/extract` 가 톤 적용·기각 **이름 목록만** 넘기고 `llm_error_type` 을 빠뜨려,
스텝 3 의 답변 조립(`chat_reply._tone_notices`)이 `AttributeError` 로 죽었다.

→ `tone_llm_error_fields` / `tone_llm_error_blocks` 를 계약에 추가했다. 손댄 곳 넷:
`chat_api.py` 의 `CommitRequest`·`_ToneView`·extract 응답·`_empty_extraction`,
그리고 워크플로우 `sfr006_02_extract.py`(전달) · `sfr006_03_commit.py`(전달).

**왜 필드를 늘렸나**: 이게 없으면 톤 실패가 **"적용 0건" 과 구분되지 않는다.**
문체가 그대로인 이유를 사용자가 알 수 없고, 로그에도 성공처럼 보인다.

### 2-3. 점검을 새 배치로 옮기고, 계약 점검을 하나 새로 만들었다

경로를 하드코딩하던 6개(`check_api_contract`·`check_body_blocks`·`check_output_safety`·
`check_vendor_closure`·`check_table_grid`·`check_tone_policy`)를 `codeserving/` 기준으로
고쳤다. 그 외에:

- **`check_deploy_contract.py` 에 `check_workflow_steps()` 신규.** 스텝 9개가
  (ㄱ) `run(data)` 단일 정의인지, (ㄴ) **외부 패키지가 `httpx` 뿐인지**,
  (ㄷ) 서로 import 하지 않는지를 AST 로 본다.
  **(ㄴ)가 이 재배치의 계약 자체**다 — 그물이 없으면 `lxml`·`redis` 가 슬그머니 돌아오고,
  그러면 기본 이미지 변경 요청에 다시 묶인다. (ㄷ)는 공용 모듈로 빼려는 시도를 잡는다.
  로컬에서는 잘 돌아 보이지만 **캔버스에 붙일 수 없게** 된다.
- 단위 목록에 MCP 를 등록했다가 **되돌렸다** (2026-08-11 정정). MCP 는 디렉토리가 아니라
  **소스 파일 한 개**가 등록 단위라 `requirements.txt`·`/health`·`$PORT`·진입점이라는
  개념이 없다. 대신 `check_mcp_files()` 가 그쪽 계약(접두어·`-> str`·shim·상대 import
  금지·부팅 설치 절차)을 따로 본다.
- `/health`·진입점 점검 대상을 `area == "03"` 이 아니라 **진입점 유무**로 바꿨다.
- `check_table_grid.py`: 표 격자 대조가 3벌 → **4벌**(MCP `genon_hwpx_text` 추가).
- `check_tone_policy.py`: 톤 프리셋 **원본이 글다듬이 → MCP `lang_policy`** 로 바뀌었다.
  판정(`resolve_tone`)을 하는 쪽이 원본을 갖는 것이 맞다. 글다듬이 사본도 대조에 넣었다 —
  안 그러면 원본이 옮겨간 뒤 **다듬기 프롬프트만 옛 문구로 남는 경로**가 그물 밖에 놓인다.

### 2-4. 문서 병합 충돌을 해소하고 새 배치를 반영했다

`CLAUDE.md`(2블록)·`onprem/README.md`(5블록, 일부는 마커가 `> > > > >` 로 깨져 있었다)를
최신 기준으로 정리했다. 구버전에만 있던 것 중 아직 유효한 둘은 살렸다:
**코드서빙 호출 경로 해소 근거**(가이드 6.9)와 **개발가이드 6장 배포 계약** 절.

---

## 3. 검증 — 무엇을 어떻게 확인했나

### 3-1. 점검 스크립트 11개 (전부 종료 코드 0 — 2026-08-12 기준)

```bash
export PYTHONIOENCODING=utf-8   # Windows 콘솔에서 필수 (cp949 가 '—' 에서 죽는다)

python onprem/test/check_deploy_contract.py  # FAIL 0 / WARN 4 / OK 53
python onprem/test/check_service_boot.py     # 16/16
python onprem/test/check_workflow_run.py     # 35/35
python onprem/test/check_mcp_tools.py        # 37/37
python onprem/test/check_api_contract.py     # 42/42
python onprem/test/check_chat_turn.py        # 20/20
python onprem/test/check_unit_endpoints.py   # 31/31   ← 018 세 단위 + txt 규약 대조
python onprem/test/check_body_blocks.py      # 17/17
python onprem/test/check_output_safety.py    #  5/5
python onprem/test/check_table_grid.py       # 18/18
python onprem/test/check_tone_policy.py      # 18/18
```

남은 WARN 4 는 전부 의도된 것이다(이미지가 제공하는 006 의 `genon`,
`try/except ImportError` 로 방어된 `fastmcp`, 루트 `main.py` 없는 006·FAQ → 시작 커맨드 필수).

**2026-08-12 에 세 번 걷어냈고 그때마다 이 표가 움직였다.** `check_vendor_closure.py` 는
없어졌고(개봉 안전 게이트·넘침 측정과 함께), `check_tone_policy`·`check_chat_turn` 은 006
톤 제거로 줄었고, `check_unit_endpoints` 는 **FAQ 내보내기 폐기 + 018 txt 통일**로
11→31 로 늘었다. 상세는 루트 `README.md` "검증" 절.

### 3-2. 실행 스모크 4종 — **스크립트는 저장소에 없다**

세션 임시 디렉토리에서 돌렸고 커밋하지 않았다. **다시 필요하면 새로 짜야 한다.**
아래는 무엇을 어떻게 확인했는지의 기록이다(같은 것을 다시 만들 수 있게).

| 스모크 | 결과 | 방법 |
|---|---|---|
| 배포 단위 기동 | **8/8** | 단위 경로를 `sys.path` 에 넣고 `app` 을 import 해 라우트 수 확인 |
| 워크플로우 스텝 실행 | **9/9** | 환경변수를 **비우고** 호출 → `CONFIG_MISSING`(`02-00020003`) 경로를 태운다. 중간 5개는 `dict`, 마지막 4개는 token 스트리밍 후 `result` **정확히 1회** |
| MCP 도구 호출 | **4/4 서빙** | `TestClient` 로 `POST /mcp/list` 와 JSON-RPC `tools/call`. 표 훼손·숫자 누락·언어 감지·방향 거부 판정을 실제로 받았다 |
| 스텝 ↔ MCP 연결 | **6/6** | 글다듬이 스텝 2 의 `httpx.AsyncClient` 를 가짜로 바꿔 **실제 `genon_text_guard` 앱**으로 보냈다. `/polish` 자리만 고정 응답(LLM 대역) |

**네 번째가 제일 값어치 있다.** `workflow/README.md` 가 "미확인" 으로 적어 둔 MCP 호출
형식(`result.content[].text` 를 JSON 으로 파싱)이 이 범위에서 확인됐다.
다만 확인한 것은 **우리 MCP 앱과의 계약**이고, **게이트웨이가 JSON-RPC 를 그대로
통과시키는지는 여전히 실물 확인 대상**이다. 형식이 다르면 각 스텝 파일의 `_mcp_call`
한 곳만 고치면 된다.

---

## 4. 이어서 할 일 — 우선순위 순

### A. 실물이 있어야 하는 것 (지금 막혀 있는 것들)

1. **LLM 실호출 경로 전체.** 게이트웨이가 없어 `/chat/extract`·`/polish`·`/generate`·
   `/translate` 의 LLM 왕복을 **한 번도 본 적이 없다.** 프롬프트 한/영 분리가 실제 출력에
   어떻게 작용하는지도 여기서 처음 드러난다.
2. **게이트웨이의 JSON-RPC 통과 여부** (§3-2). 안 되면 `_mcp_call` 을 스텝 9개에서 각각
   고쳐야 한다 — 자기완결 규율상 공용 모듈로 뺄 수 없으므로 **9번 고치는 것이 정상이다.**
3. **빌드·시작 커맨드가 셸을 거치는지** (§5). `cd A && B` 가 안 먹으면
   `uvicorn --app-dir <경로> …` 로 바꾼다.
4. **워크플로우 스텝 간 `data` 크기 한도.** 문서 본문(`polish_source_text` 등)을 스텝
   사이로 넘긴다. 한도에 걸리면 본문 대신 **핸들(세션 키)** 만 넘기고 코드서빙이 다시 읽는
   형태로 바꿔야 한다.
5. **번역 02 스텝 2개는 캔버스에 등록된 적이 없다.** 코드는 있고 실행도 되지만 신규다.
6. Redis 실연결, 생성한 hwpx 를 **한/글에서 열어보기**(이제 006 하나뿐이다 — FAQ 는
   2026-08-12 부터 txt 만 낸다), 그리고 **내려준 .txt 를 사내 PC 메모장에서 열어보기**
   (BOM·CRLF 는 바이트로 확인했지만 실제 메모장 버전에서 본 것은 아니다).
   ~~FAQ hwpx 템플릿 실물 확보~~ — 필요 없어졌다.

### B. 코드로 지금 할 수 있는 것

1. ~~테스트 사본 정리~~ — **끝났다** (2026-08-11 후반). `SFR-006/`·`SFR-018/` 은 이제
   **테스트 전용**이고 `onprem_path.py` 를 통해 `onprem/` 을 직접 import 한다. 구현 사본이
   없으므로 드리프트가 생길 자리 자체가 없어졌다. 근거는 `CLAUDE.md` "저장소 구조 개편" 절.
2. ~~스모크 스크립트를 `onprem/test/` 로 승격~~ — **끝났다.** `check_service_boot.py`(16) ·
   `check_workflow_run.py`(35) · `check_mcp_tools.py`(37) 가 그 셋이다.
3. ~~`@app.on_event("startup")` → `lifespan`~~ · ~~업로드 전량 읽기~~ — **둘 다 2026-08-11 에
   했다.** 번역·FAQ 는 `lifespan` 을 쓰고, 업로드는 `read_upload_capped` 가 상한에서 읽기를
   멈춘다.

### C. 건드리지 말 것 (의도된 것)

- **워크플로우 스텝 파일들의 중복**(로깅·오류표·게이트웨이 클라이언트). 공용 모듈로 빼면
  스텝이 자기완결이 아니게 되어 **캔버스에 붙일 수 없다.** `check_workflow_steps()` 가 막는다.
- **표 격자 4벌·톤 프리셋 3벌·`txt_output.py` 3벌 등의 사본.** 배포 단위 간 import 금지로
  강제된 것이고, 갈렸는지는 `check_table_grid`·`check_tone_policy`·`check_unit_endpoints` 가
  **출력으로** 본다 (마지막 것은 응답 바이트를 대조한다).
- ~~`_vendor/` 안의 미사용 함수 15개~~ — **`_vendor/` 자체가 2026-08-12 에 없어졌다.**
  `archive/hwpx-genon-vendor` 브랜치에 있다.

---

## 5. 저장소 구조 결정 (2026-08-11)

**서빙 등록은 8번, 저장소는 1개.**

- 코드 서빙 1개 = 컨테이너 1개 = URL 1개다. 리비전·환경변수·복제본이 전부 서빙 단위로
  붙으므로 **등록은 단위마다 반드시 따로** 한다. 저장소를 어떻게 두든 이 숫자는 안 줄어든다.
- 여러 서빙이 **같은 저장소·같은 커밋**을 가리켜도 된다. 가이드에 하위 디렉토리 지정
  항목이 없으므로 디렉토리 구분은 빌드·시작 커맨드가 흡수한다.
- **한 저장소로 가는 근거는 사본 대조다.** 위 §4-C 의 의도된 중복이 갈렸는지는 **한 커밋
  안에서 동시에 읽어야** 확인된다. 저장소를 8개로 쪼개면 `onprem/test/` 의 대조 점검이
  경계를 넘어야 해서 **성립하지 않는다.**
- 대가: 서빙 8개가 각각 저장소 전체를 받고, 한 단위만 고쳐도 커밋 해시가 같이 움직인다
  (리비전을 안 올리면 배포가 강제되지는 않는다).

상세는 `README.md` "저장소 구조" 절.

---

## 6. 다시 시작할 때 30초 안에 상태 확인하는 법

```bash
export PYTHONIOENCODING=utf-8
python onprem/test/check_deploy_contract.py    # 여기서 FAIL 이 나면 배치가 어긋난 것이다
git status --porcelain | head                  # 재배치 커밋이 안 됐으면 R/D 가 대량으로 보인다
```

`check_deploy_contract` 가 FAIL 0 이면 배포 계약은 온전하다. 그다음 나머지 7개를 돌린다
(루트 `CLAUDE.md` "검증 명령" 절에 전부 있다).
