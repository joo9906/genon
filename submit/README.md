# 폐쇄망 반입 꾸러미 — 무엇을 어디에 넣고 어떻게 돌리나

> 이 폴더를 통째로 압축해 온프레미스로 보낸다. **압축을 푼 자리에서 점검이 그대로 돈다** —
> 저장소 배치를 그대로 옮겼기 때문이다. 무엇이 빠졌는지는 §7 의 점검이 말해 준다.
>
> 다시 만들려면 저장소 루트에서 `python make_submit.py`.
>
> **입출력 JSON 은 [`IO_FORMAT.md`](IO_FORMAT.md) 에 단계별로 있다** — 캔버스 변수 →
> 스텝 사이 `data` → 서빙 요청/응답 → 소켓 `result` 네 경계 전부.

---

## 0. 이 꾸러미가 담고 있는 것

| 폴더 | 무엇 | 등록하나 |
|---|---|---|
| **`not/`** | ⭐ **지금 올릴 코드 서빙 4단위** (`lxml` 없는 판본) | ⭕ 4번 |
| `onprem/mcp/` | MCP 도구 **파일 4개** | ⭕ 4번 (파일 1개 = 등록 1개) |
| `onprem/preprocessor/` | 전처리기 — 적재용 **하나**(둘 중 고른다) + 첨부용 `only_me.py` | ⭕ 2번 |
| `onprem/codeserving/` | 코드 서빙 4단위 **정본**(`lxml` 판본) | ❌ **지금은 안 올린다** (아래) |
| `onprem/workflow/` | 캔버스 파이썬 스텝 9개 | ❌ 등록이 아니라 **캔버스에 붙여 넣는다** |
| `not/prompt/` | 프롬프트 (`onprem/prompt/` 의 사본) | ❌ **코드서빙 이미지에 함께 넣는다** |
| `onprem/eval/` | 평가지표 MCP 서버 | ❌ 배포 단위가 아니다 (채점용, §8) |
| `onprem/test/` | 점검 스크립트 **15개** | ❌ 배포 대상 아님 (§7) |
| `SFR-006/tests`, `SFR-018/tests` | 단위 테스트 **394건** | ❌ 배포 대상 아님 |
| `data/` | 실물 hwpx 5벌 | ❌ 점검이 쓰는 표본 |
| `genos_files/*.py` | GenOS 벤더 참조 사본 2개 | ❌ 점검이 대조에 쓴다 |
| `not/minio.py` | 📖 GenOS 참조 샘플 | ❌ **등록하지 말 것** — import 하면 `pip install` 이 돈다 |
| `onprem/docs/`, 루트 `*.md` | 설계·이관 문서 | ❌ 읽는 것 (§10) |

**등록은 모두 10번이다** — 코드 서빙 4 + MCP 4 + 전처리기 2.

### ⚠ 코드 서빙은 **`not/` 을 올린다** (2026-09-08)

사내 PyPI mirror 에 **`lxml` 이 없어** 정본(`onprem/codeserving/`)이 빌드되지 않는다.
`not/` 은 그 판본에서 `lxml` 을 걷어낸 것이고 **네 단위가 전부 들어 있다.**

| | 잃는 것 |
|---|---|
| 글다듬이 | 없다 (원래부터 `lxml` 을 안 썼다 — 코드가 정본과 같다) |
| 번역 · FAQ | 없다. hwpx 직접 업로드 라우트 하나씩만 빠졌고 캔버스는 전처리기를 지난다 |
| **템플릿 채우기** | 산출물이 **hwpx → txt**, 글꼴·크기 서식 미적용 |

**mirror 에 `lxml` 이 들어오면** 시작 커맨드의 경로만 `onprem/codeserving/<단위>` 로
되돌리면 된다. 자세한 것은 [`not/README.md`](not/README.md).

---

## 1. 초기 세팅 — 등록보다 **점검을 먼저** 돌린다

반입 중에 파일이 빠지거나 깨졌는지를 여기서 잡는다. 서버·LLM·Redis 가 필요 없다.

```bash
python -V                    # 3.10 이상

# 점검이 쓰는 것만 설치한다 (운영 설치와 별개다).
# **`lxml` 은 점검용이다** — 올릴 코드(`not/`)는 쓰지 않지만, 정본과 출력이 같은지
# 대조하는 판정이 정본을 태우므로 여기서는 있으면 좋다(없으면 그 판정만 SKIP 된다).
pip install fastapi "uvicorn[standard]" httpx lxml pydantic

export PYTHONIOENCODING=utf-8      # Windows 콘솔이면 필수 (cp949 가 em dash 에서 죽는다)
cd <압축 푼 자리>
python onprem/test/check_deploy_contract.py
python not/check_not_units.py      # 올릴 판본이 온전한가 (92건)
```

`FAIL 0 / WARN 3 / OK 64` 와 `OK 91 / FAIL 0` 이 나오면 배치가 온전한 것이다. **WARN 3 은 의도된 것**이고
이유는 `onprem/test/README.md` 에 적혀 있다.

> **pip 이 안 되는 환경이면** 점검 대부분이 못 돈다(fastapi·lxml 이 필요하다).
> 그때는 `check_table_grid`·`check_final_preprocessor` 처럼 lxml 만 쓰는 것부터 돌린다.

---

## 2. 코드 서빙 4단위

GenOS 코드 서빙은 **Git 저장소가 배포 단위**다. 사내 Git 에 이 꾸러미를 올리고 단위마다
등록한다 — 같은 저장소·같은 커밋을 4번 가리켜도 되고, 디렉토리 구분은 커맨드가 흡수한다.

### 2-1. 빌드·시작 커맨드

`LANGUAGE` 는 python. **빌드 커맨드는 네 단위가 같고 시작 커맨드만 다르다.**

**경로는 `not/` 이다** (§0 참고 — mirror 에 `lxml` 이 없다). 정본으로 돌아갈 때는
`not/<단위>` 를 `onprem/codeserving/<단위>` 로 바꾸기만 하면 된다.

| # | 저장소 경로 | 기능 | 시작 커맨드의 app |
|---|---|---|---|
| 1 | `not/SFR-006_template_fill/` | 템플릿 채우기 | `template_fill.main:app` |
| 2 | `not/SFR-018_text_polish/` | 글다듬이 | `main:app` |
| 3 | `not/SFR-018_translation/` | 번역 | `main:app` |
| 4 | `not/SFR-018_faq/` | FAQ 생성 | `faq.main:app` |

```
BUILD : pip install -r not/<단위>/requirements.txt
RUN   : cd not/<단위> && uvicorn <위 표의 app> --host 0.0.0.0 --port $PORT
```

- **006 과 FAQ 는 시작 커맨드를 반드시 등록한다.** 자동 실행 경로는 저장소 루트의
  `main.py` 를 찾는데 이 둘의 진입점은 패키지 안이라 안 걸린다.
  **`main:app` 을 이 둘에 쓰면 기동 실패한다.**
- ⚠️ **`cd A && B` 가 먹는지 실물에서 확인할 것.** 셸을 안 거치면
  `uvicorn --app-dir onprem/codeserving/<단위> <app>` 으로 바꾼다.

### 2-2. 프롬프트 디렉토리를 **이미지에 함께 넣는다**

**`not/` 을 올리면 `not/prompt/<단위 이름>/`** 이 이미지 안에 있어야 한다(정본을 올릴
때는 `onprem/prompt/`). 없으면 **기동·헬스체크는 정상인데 첫 LLM 호출에서만**
`PromptRenderError` 가 난다. 꾸러미를 통째로 올리면 자동으로 들어간다.

> 로더는 위로 올라가며 `prompt/<단위 이름>/` 을 찾는데 **`not/` 에서 멈춘다** — 그래서
> `onprem/prompt/` 가 이미지에 있어도 `not/` 판본은 못 찾는다. 사본을 따로 둔 이유다.

### 2-3. 환경변수

**공통 (네 단위 전부 · 필수)**

| 변수 | 뜻 |
|---|---|
| `GENOS_URL` | 게이트웨이 베이스 URL |
| `LLM_SERVING_ID` | LLM 서빙 ID (**모델도 이 값이 정한다**) |
| `GENOS_TOKEN` | 액세스 토큰 |

> **`LLM_MODEL_ID` 는 2026-09-07 에 없앴다** — 게이트웨이의 서빙 경로가 이미 모델을
> 정하므로 본문의 `model` 은 그 위에 얹히는 중복이었다. 게이트웨이가 OpenAI 규격대로
> `model` 을 필수로 검증하면 400/422 로 드러난다(되살릴 자리는 네 `config.py`·`llm.py`).

mock 경로를 없앴으므로 빠지면 첫 LLM 호출에서 오류가 난다. 그 오류는 **재시도 불가**로
분류돼 나가므로 캔버스가 헛되게 재시도하지 않는다.

**단위별 추가 필수**

| 단위 | 공통 외 필수 | 상태 |
|---|---|---|
| 006 | `TEMPLATE_FILL_TEMPLATE_DIR`(공유 볼륨) · `REDIS_URL` | Redis |
| 글다듬이 | 없음 | 무상태 |
| 번역 | 용어사전을 쓸 때만 `TRANSLATE_GLOSSARY_API_URL` · `_DRIVE_ID` · `_WORKSPACE_ID` | 무상태 |
| FAQ | `REDIS_URL` | Redis |

> **006·FAQ 는 워크플로우 pod 와 코드서빙 pod 가 같은 Redis 를 봐야 한다.** 다운로드가
> 대화에서 모은 값을 읽는 유일한 통로다. 006 은 템플릿 볼륨도 **같은 경로로** 양쪽에
> 마운트한다.

**선택 — 결과 파일 링크 (네 단위 전부. 006 은 2026-09-08 부터)**: `GENOS_CDN_UPLOAD_URL`(기본
`http://llmops-cdn-api-service:8080/minio/upload/temp`) · `GENOS_CDN_HOSTNAME`(기본
`https://genos.genon.ai`). 안 넣어도 뜨지만 잘못 잡히면 `download_url` 이 계속 비고,
**결과는 정상 전달되므로(fail-open) "파일만 못 받는다" 로만 드러난다.** 등록 뒤 링크를
한 번 눌러 볼 것.

**선택 — 긴 문서**: `FAQ_MAX_CONTEXT_CHUNKS`(40) · `POLISH_MAX_CHUNK_CHARS`(6000) ·
`POLISH_LLM_CONCURRENCY`(4). 셋 다 기본값이 있고 **실물 LLM 없이 정한 값**이다 —
429 가 나면 `POLISH_LLM_CONCURRENCY` 부터 내린다.

변수의 **의미와 전체 목록**은 `onprem/README.md` "기능별 추가 설정".

### 2-4. 확인

```
GET  {단위}/health          → 200
GET  {단위}/                → 200   (게이트웨이가 경로 없이 베이스를 때리는 배포 대비)
GET  {글다듬이}/policies    → 톤 4종 · 문서유형 5종
GET  {단위}/prompts         → 프롬프트를 어디서 받았는지 (§4)
```

**health 200 만으로 완료로 보지 않는다** — 정상 입력 한 번, 입력 오류 한 번을 눌러 본다.

---

## 3. MCP 도구 4개 — **파일을 각각** 등록한다

**MCP 는 서빙이 아니다.** GenOS 가 소스 파일 한 개를 받아 실행하고 `mcp` 객체를 전역으로
주입한다. FastAPI 앱도 `/health` 도 `$PORT` 도 시작 커맨드도 `requirements.txt` 도 **없다.**
디렉토리를 올리는 것이 아니라 **파일 네 개를 각각** 등록한다.

| # | 파일 | 도구 | 개수 |
|---|---|---|---|
| 5 | `onprem/mcp/genon_text_guard.py` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` | 4 |
| 6 | `onprem/mcp/genon_lang_policy.py` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 6 |
| 7 | `onprem/mcp/genon_glossary.py` | `glossary_lookup` `glossary_status` `glossary_reload` | 3 |
| 8 | `onprem/mcp/genon_hwpx_text.py` | `hwpx_to_markdown` | 1 |

**환경변수는 `genon_glossary.py` 만** 필요하다 — `TRANSLATE_GLOSSARY_API_URL` ·
`_DRIVE_ID` · `_WORKSPACE_ID`(+ 토큰이 다르면 `_TOKEN`). 셋 중 하나라도 없으면
**용어사전 없이 동작**하고 그 사실이 `glossary_status` 의 `reason` 으로 드러난다.
나머지 셋은 환경변수가 없다(결정적 도구이고 LLM 도 안 부른다).

### 확인 — **도구 14개가 다 나오는지 센다**

`tools/list` 에 **14개**(4+6+3+1)가 다 있어야 한다. **하나라도 비면 이름이 겹쳐 덮인
것**이고, 그 실패는 "도구가 이상한 값을 낸다" 로만 드러난다. 그래서 도구 함수를 뺀 모든
최상위 심볼에 접두어(`TG`/`LP`/`GL`/`HX`)가 붙어 있다.

> `genon_hwpx_text.py` 는 `lxml` 이 필요한데 `requirements.txt` 를 쓸 수 없어 **파일
> 안에서 직접 설치**한다. 폐쇄망 mirror 접근이 없으면 이 파일만 실패한다.

---

## 4. 프롬프트 라이브러리 (선택 — 안 해도 전부 정상 동작한다)

프롬프트 문장은 **이미지에 든 `.j2` 파일**로 돈다. 관리자가 문구를 직접 고치게 하려면
GenOS `도구 > 프롬프트 라이브러리` 에 올리고 **ID 로 덮어쓴다.**

```
GENOS_ADMIN_API_URL=http://llmops-admin-api-service:8080     # 네 단위 공통
TEMPLATE_FILL_PROMPT_IDS=extract_user=41,document_user=42
POLISH_PROMPT_IDS=system=43
TRANSLATE_PROMPT_IDS=system_batch=44,user_batch=45
FAQ_PROMPT_IDS=system=46,user=47
```

- **이름은 파일 이름에서 확장자를 뗀 것**이다 (`extract_user.j2` → `extract_user`).
  다르게 적으면 그 이름만 **조용히 옛 문구로 돈다.**
- 미설정 · 조회 실패 · 본문 렌더 실패는 **전부 `.j2` 로 떨어진다.** 파일도 없을 때만
  요청을 세운다 — 지시문 없는 프롬프트의 결과는 정상 응답처럼 내려가기 때문이다.
- `GET {단위}/prompts` 가 이름마다 `source`(`prompt_library`/`file`)와 `reason` 을 낸다.
  이게 없으면 "ID 를 안 넣었다" 와 "넣었는데 못 읽었다" 가 화면에서 **똑같이 옛 문구**로
  보인다. **본문은 싣지 않는다.**
- 리비전을 운영 반영한 뒤 `POST {단위}/prompts/reload` 로 TTL(60초)을 건너뛴다.
- **프롬프트는 전부 한국어로 쓴다** (2026-09-03). 근거는 `onprem/prompt/README.md`.

### 4-1. 톤별 프롬프트 (선택)

톤마다 다른 시스템 프롬프트를 쓰려면 **`system_<톤코드>`** 라는 이름으로 만든다.
톤 코드는 넷이다 — `polite`(격식·정중) `friendly`(친절·안내) `clear`(명확·간결)
`objective`(사실·객관).

```
POLISH_PROMPT_IDS=system_polite=51,system_friendly=52,system_clear=53,system_objective=54
```

**등록하지 않은 톤은 `system.j2` + 톤 지시문으로 떨어진다** — 관리자가 톤을 추가해도
기능이 죽지 않게 한 폴백이다. 코드에 적어 두려면
`onprem/codeserving/SFR-018_text_polish/text_polish/config.py` 의 `TONE_PROMPT_IDS`
(환경변수가 이긴다). 코드 없이 붙이는 안은 `onprem/docs/WIP_prompt_dynamic.md`.

### 4-2. 톤·문서유형을 **추가**하는 경로는 없다 (2026-09-07 폐기)

그전에는 정책 JSON 을 프롬프트 라이브러리에 올려 톤을 늘릴 수 있었는데, "코드서빙 안에서
JSON 을 해석하지 않는다" 가 요구로 붙으면서 걷어냈다. **지금 목록·라벨·강제 톤의 출처는
표 하나**이고 관리자가 바꿀 수 있는 것은 **톤별 지시문 문장**뿐이다(§4-1).

- **옛 환경변수 `POLISH_POLICY_PROMPT_ID`·`LANG_POLICY_PROMPT_ID` 는 읽지 않는다.**
  남아 있으면 글다듬이가 `event=policy_legacy_env_ignored` 로 알린다 — 안 알리면
  관리자에게는 "설정했는데 아무 일도 일어나지 않는" 상태가 된다.
- 톤을 늘리는 것은 개발자 일이다. 표 2벌(글다듬이 `tone_presets.py` · MCP
  `genon_lang_policy.py`) + eval `TONE_RULES` 를 **함께** 고친다.

---

## 5. 전처리기 2개 (독립 트랙)

**적재(검색)용 하나 + 질의 시 첨부용 하나**를 각각 등록한다. 적재용은 **둘 중 고른다** —
`final_preprocessor.py`(벤더 절반 = 첨부용)와 `smart_preprocessor.py`(벤더 절반 =
**지능형**)는 같은 자리를 두고 겨루는 판본이고 hwpx 절반은 같은 코드다.

| 적재용 판본 | pdf | `.hwp`·`.hml`·오디오 |
|---|---|---|
| `final_preprocessor.py` | 평문 + 문자 수 분할 — **표가 사라진다** | **네이티브** (GenosHwp SDK·Whisper) |
| `smart_preprocessor.py` | **docling + TableFormer + OCR** | 없다 |

**pdf 안의 표**가 중요하면 지능형, **`.hwp` 구버전·음성 파일**이 섞여 있으면 첨부용이다.
**같은 컬렉션에 둘을 함께 걸지 않는다** — 같은 pdf 가 등록 시점에 따라 다른 청크로
들어가고 그 어긋남은 검색 품질로만 드러난다.

**질의 시 첨부용은 `only_me.py`** 다 — 청킹·조문 머리말 없이 원문 하나로 낸다.
네 기능이 첨부 문서를 그 산출물로 받으므로 **이 등록이 없으면 첨부가 통째로 안 된다.**
적재용 머리말(`제2장 총칙 > 제5조(목적)`)이 LLM 입력에 섞이면 안 되기 때문에 갈랐다.

아래 설명은 **적재용** 기준이다.
`__init__.py` 는 올리지 않는다 — 로컬 테스트가 `import preprocessor` 로 쓰라고 둔 재노출
파일이고, 등록 단위는 그 한 파일이다.

파일 안은 세 덩어리다. `# PART ` 로 검색하면 경계가 나온다:

| PART | 무엇 |
|---|---|
| 1 | 벤더 절반 — hwpx 아닌 전 형식 (`final_preprocessor` = 첨부용 / `smart_preprocessor` = **지능형**) |
| 2 | hwpx 파서 — 표 병합·조문 위계를 지킨다 |
| 3 | 라우터 — GenOS 가 실행하는 `DocumentProcessor` 가 여기 있다 |

### 받을 확장자는 **hwpx 만** 건다

나머지는 사이트의 **기존 첨부용 등록**이 그대로 맡는다.

- **전 확장자를 걸지 않는 이유**: PART 1 은 벤더 참조 사본이라 사이트 설치본 판본과
  어긋날 수 있고, 그러면 **PART 1 이 통째로 가드에 걸려 hwpx 아닌 전 형식을 거부한다**
  (2026-09-02 에 실제로 밟았다 — `facade.guardrail` 이 없었다). hwpx 는 가드 밖이라
  그대로 돌아 **"pdf 만 안 되는"** 얼굴로 나타난다.
- **hwp(구버전 바이너리)를 걸지 말 것** — zip 기반 hwpx 전용이라 못 연다. 그쪽은
  첨부용(GenosHwp SDK 네이티브)이 우수하다.
- **매핑을 안 하면 예전 경로가 hwpx 를 받아 표가 깨진다** — 이 전처리기를 만든 이유가
  그것이다. 반대로 hwpx 아닌 확장자가 이쪽으로 오면 즉시 예외를 던진다
  (`SUPPORTED_EXTENSIONS`) — 잘못 건 매핑이 조용히 이상한 결과를 내지 않게 남긴 그물이다.
- **확장자 설정을 바꾸면 그 전처리기로 적재한 파일이 `needs_reingest`** 다(자동 재적재
  아님). 매핑을 확정한 뒤 hwpx 를 올린다.

**등록 화면에서 정하는 값**: `chunk_size` / `chunk_overlap`(기본 1000/100 은 **임시값**
이라 임베딩 모델 컨텍스트에 맞춘다), 배포별 필드가 있으면 `extra_metadata`.

> ⚠️ **GENON-DEBUG 임시 로그가 아직 들어 있다.** 문서 본문 200자를 컨테이너 stdout 에
> 찍는다 — 적재 결과를 눈으로 보려고 넣은 것이고 **확인이 끝나면 지운다.**
> `GENON-DEBUG` 로 검색하면 자리 셋이 다 나온다.

---

## 6. 워크플로우 스텝 9개 — 캔버스에 붙여 넣는다

등록이 아니다. 캔버스 파이썬 노드에 **파일 내용을 그대로** 붙인다.
함수 이름 `run` 은 GenOS 고정 계약이라 바꿀 수 없다.

| 기능 | 파일 |
|---|---|
| 템플릿 채우기 | `sfr006_01_context.py` · `sfr006_02_extract.py` · `sfr006_03_commit.py` |
| 글다듬이 | `sfr018_polish_01_policy.py` · `sfr018_polish_02_polish.py` |
| 번역 | `sfr018_translate_01_detect.py` · `sfr018_translate_02_translate.py` |
| FAQ | `sfr018_faq_01_source.py` · `sfr018_faq_02_generate.py` |

- **스텝이 쓰는 외부 패키지는 httpx 뿐이다** — 워크플로우 이미지에 추가로 넣을 것이 없다.
- **등록해서 얻은 서빙 ID·MCP ID 를 스텝 안에 꽂는다.** 어느 스텝에 무엇을 넣는지는
  `onprem/docs/SERVING_REGISTRY.md` §3 의 표.

---

## 7. 점검 — 서버·LLM·Redis 없이 전부 돈다

```bash
export PYTHONIOENCODING=utf-8

python onprem/test/check_deploy_contract.py     # 빌드·기동 계약   FAIL 0 / WARN 3 / OK 64
python onprem/test/check_service_boot.py        # 코드서빙 4단위 기동            16
python onprem/test/check_workflow_run.py        # 워크플로우 스텝 9개 실행      118
python onprem/test/check_mcp_tools.py           # MCP 파일 4개 공존·판정         86
python onprem/test/check_api_contract.py        # 006 엔드포인트                 53
python onprem/test/check_chat_turn.py           # 대화 한 턴 (02 스텝 ↔ 03)      47
python onprem/test/check_unit_endpoints.py      # 018 세 단위 엔드포인트        113
python onprem/test/check_body_blocks.py         # 문단 복제 안전장치             17
python onprem/test/check_output_safety.py       # 파트 선언·누름틀 안내문         5
python onprem/test/check_table_grid.py          # hwpx 파싱 코어 사본 5벌        34
python onprem/test/check_tone_policy.py         # 톤 사본 3벌 + 별칭 2벌         20
python onprem/test/check_eval_metrics.py        # 평가지표 자체 검증             88
python onprem/test/check_final_preprocessor.py  # 전처리기 (실물 hwpx 5벌)      155

python onprem/test/check_smart_preprocessor.py  # 전처리기 (지능형 + hwpx)       52
python onprem/test/check_prompt_render.py       # 프롬프트가 실제로 렌더되는가   71
python not/check_not_units.py                   # **올릴 판본**이 온전한가       92

cd SFR-006 && python -m unittest discover -s tests -t . && cd ..    #  64건
cd SFR-018 && python -m unittest discover -s tests -t . && cd ..    # 349건
```

**합계 점검 934 + unittest 394 = 1,328. 전부 종료 코드 0 이어야 한다.**
(`not/` 91건은 별도 집계 — `onprem/` 회귀 기준이 아니라 한시 판본의 것이다.)

- **가짜(Redis·LLM·게이트웨이)는 배포 단위 밖에서 주입한다** — 운영 코드에 테스트용
  분기를 만들지 않기 위해서다.
- `check_final_preprocessor` 가 **155 가 아니라 134** 이면 `data/` 의 실물 hwpx 5벌을 못
  찾은 것이다(있는 것만 태운다).
- `check_unit_endpoints` 가 2건 실패하면 `SSL_CERT_FILE` 이 없는 경로를 가리키는 것이다
  (conda 기본값이 그럴 수 있다). `SSL_CERT_FILE=` 로 비우면 통과한다 — 코드 결함이 아니다.
- **건수가 위와 다르면 파일이 빠졌거나 반입 중에 깨진 것**이다. 어느 판정이 FAIL 인지가
  곧 어느 파일인지다.

---

## 8. 평가지표 (`onprem/eval/`) — 배포 단위가 아니다

네 기능의 산출물을 **채점**하는 MCP 서버다. 등록 10번에 들어가지 않고, 품질 기준을 재려
할 때만 올린다.

- 운영 지표는 **결정적 도구**(Text · Numeric · Structure)다. LLM Judge 는 게이트드이고
  실제 판정 호출은 아직 없다.
- **미측정을 통과로 보이게 하지 않는다** — `verdict` 에 `pass_but_incomplete`,
  `skipped_metrics` 에 건너뛴 지표와 이유를 담아 돌려준다.
- **PII 마스킹 누락을 네 기능 출구에서 본다**(`pii_leak_count`). 비율이 아니라 **절대
  건수**다 — 허용치가 0인 값에 비율 기준을 걸면 200문장 문서의 1건이 0.5% 라 통과한다.
- **eval 은 배포 단위를 import 하지 않는다** (파서를 공유하면 파서 버그를 함께 놓친다).
  그래서 톤 규칙 같은 도메인 규칙이 양쪽에 각각 있다 — **운영 규칙을 바꾸면
  `eval_mcp/tone_metrics.py` 도 같이 봐야 한다.**
- **관리자가 톤을 추가하면 채점 규칙은 따라오지 않는다.** 그 톤은 `skipped` 로 드러나고
  합격률 분모에서 빠진다(통과로 세면 지표가 부풀고, 불합격으로 세면 톤을 추가했다는
  이유로 지표가 떨어진다).
- 지표 정의·합불 기준은 `onprem/eval/README.md`, 자체 검증은
  `python onprem/test/check_eval_metrics.py`(88건).

---

## 9. 다 올린 뒤 남는 일 — **실물로만 확인되는 것들**

여기까지는 코드가 스스로 증명할 수 있는 범위다. 아래는 게이트웨이·실물 문서가 있어야 한다.

| 확인할 것 | 왜 |
|---|---|
| LLM 실호출 경로 전체 | 로컬에 게이트웨이가 없어 한 번도 못 태웠다 |
| **프롬프트를 전부 한국어로 바꾼 뒤의 번역 품질** | 번역 결과에 한국어가 섞이면 **형식상 정상 응답으로 내려간다**(구조는 코드가 지킨다). `system_batch.j2` 의 출력 언어 고정 두 자리를 먼저 볼 것 |
| 빌드·시작 커맨드의 `cd A && B` 통과 여부 | 안 먹으면 `--app-dir` 로 바꾼다 |
| **hwpx 적재 결과가 화면에 뜨는지** | 페이지 자리에 구역을 채웠다(2026-09-03). 화면이 페이지가 아니라 **원본 미리보기**를 요구하는 것이면 이 값으로는 안 풀린다 |
| `download_url` 링크가 실제로 열리는지 (**네 기능 전부**) | 모양은 GenOS 참조 샘플(`not/minio.py`)과 대조해 맞췄다. 실패해도 결과는 정상 전달돼(fail-open) **파일만 못 받는 얼굴**이다 |
| 메모장에서 .txt 열기 (BOM·CRLF) | 응답 바이트로만 확인했다 |
| ~~한/글에서 006 산출물 열기~~ | **`not/` 판본은 txt 를 낸다** — 한/글로 열 일이 없다. 정본으로 돌아갈 때 확인한다 |
| **006 다운로드 확장자를 화면이 아는지** | `not/` 판본은 `.txt` 다. 프론트가 `.hwpx` 를 하드코딩해 붙이면 `초안.txt.hwpx` 가 된다 |
| **지능형 전처리기 경로 실행** | `smart_preprocessor.py` 를 고르면. 로컬에 docling 이 없어 대역으로만 태웠다 |
| 워크플로우가 업로드 원본 hwpx 경로를 채워 주는지 | 못 채우면 전처리기 산출물로 폴백한다(로그에 사유가 남는다) |
| pdf 표 품질 | **`final_preprocessor` 를 고르면** pdf 가 평문이라 격자가 문장으로 풀린다. `smart_preprocessor`(지능형)를 고르면 해결된다(§5) |

남은 일 전체는 `onprem/ONPREM.md` §9.

---

## 10. 문서 — 무엇을 언제 읽나

| 문서 | 언제 |
|---|---|
| `onprem/docs/SERVING_REGISTRY.md` | **등록 작업지시서** — 이 README 의 원본. 칸에 넣을 값이 더 필요할 때 |
| **`onprem/ONPREM.md`** | **이관 문서 하나** — 등록 10번·핵심 파일·환경변수·검증 상태·남은 미검증 |
| `onprem/README.md` | 환경변수의 **의미**, 로깅 규약, 이관 순서, 코드서빙 실행 |
| **`not/README.md`** | **지금 올리는 판본** — 무엇을 왜 뺐나, 되돌리는 법 |
| `onprem/docs/FRONT.md` | **화면 개발자에게 주는 계약** — 캔버스 변수, `result.data`, 오류 분기 |
| `onprem/docs/FEATURES.md` | 무엇이 구현돼 있고 무엇이 계약인가 (엔드포인트·도구·변수 지도) |
| `onprem/prompt/README.md` | 프롬프트를 고치려면 어디를 여나 (**`not/` 을 올렸으면 `not/prompt/` 도 함께 고친다**) |
| `onprem/preprocessor/README.md` | 전처리기에서 **어느 함수**를 고치나 |
| `IO_FORMAT.md` (이 폴더) | **단계별 입출력 JSON** — 네 경계 전부 |
| `onprem/docs/SFR-006_architecture.md` | 템플릿 채우기 설계·흐름의 정본 |
| `CLAUDE.md` | 왜 그렇게 만들었나 (결정 근거의 정본) |
