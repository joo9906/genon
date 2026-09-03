# onprem/prompt — 프롬프트를 고치려면 어디를 여나

> **프롬프트는 배포 단위 *바깥*에 있다.** 이 디렉토리는 코드서빙 저장소가 아니라
> **이미지에 함께 넣는 자료**다. 디렉토리 이름 = 배포 단위 이름.
>
> ```
> prompt/
>   SFR-006_template_fill/   extract_system.j2  extract_user.j2
>                            document_system.j2 document_user.j2
>   SFR-018_text_polish/     system.j2
>   SFR-018_translation/     system_batch.j2 user_batch.j2
>                            system_single.j2 user_single.j2
>   SFR-018_faq/             system.j2 user.j2 retry_shortfall.j2
> ```

## 고치는 자리는 **셋**이고, 성격이 다르다

| 무엇을 바꾸나 | 어디를 여나 | 누가 고치나 |
|---|---|---|
| **문장 자체** — 지시문 문구, 예시, 금지 조항 | 프롬프트 라이브러리(ID) **또는** 이 디렉토리의 `.j2` | 관리자(라이브러리) / 개발자(파일) |
| **끼우는 값** — 템플릿 변수를 늘리거나 줄일 때 | 각 단위의 **프롬프트 조립 함수** | 개발자 |
| **톤·문서유형 목록** — 항목을 늘리거나 어투를 바꿀 때 | 정책 JSON(admin-api) **또는** 내장 표 | 관리자(JSON) / 개발자(표) |

**셋을 헷갈리면 고쳐도 아무 일이 안 일어난다** — 예컨대 톤을 하나 추가하려고 `.j2` 를
고치면, 그 파일은 `tone_label`·`tone_instruction` 을 **받아서 끼우기만** 하므로 목록은
그대로다(그래서 `system.j2` 에 목록을 적지 않는다는 규약이 있다).

---

## 1) 문장 자체 — **라이브러리가 파일을 덮어쓴다** (2026-09-03)

**덮어쓰기지 이사가 아니다.** `.j2` 는 기본값이자 **폴백**으로 남고, ID 를 준 이름만
라이브러리가 이긴다. 파일을 지우면 admin-api 장애가 곧 기능 정지가 되고, 손으로 옮겨
적는 이관에서 프롬프트가 통째로 빠진다.

### 배선 — 이름=ID 하나

```
GENOS_ADMIN_API_URL=http://llmops-admin-api-service:8080   # 네 단위 공통

TEMPLATE_FILL_PROMPT_IDS=extract_user=41,document_user=42
POLISH_PROMPT_IDS=system=43
TRANSLATE_PROMPT_IDS=system_batch=44,user_batch=45
FAQ_PROMPT_IDS=system=46,user=47
```

**이름은 파일 이름에서 확장자를 뗀 것**(`extract_user.j2` → `extract_user`)이다. 별도
이름표를 두면 "파일 이름 ↔ 라이브러리 이름" 대조표가 하나 더 생기고, 어긋나면
**덮어쓰기가 조용히 일어나지 않는다.** JSON 표기(`{"system": "43"}`)도 받는다.
**ID 는 코드에 적지 않는다**(가이드 §10.5).

### 여는 자리

| 바꾸려는 것 | 자리 |
|---|---|
| 환경변수 이름·조회 방식·캐시 TTL | `prompt_library.py` — `prompt_ids()` · `_endpoint()` · `_fetch_one()` · `load()` · `body_for()` · `status()` · `reload()` |
| 라이브러리 ↔ 파일 **우선순위**·폴백 | `prompt_loader.py` — `render()`(라이브러리 분기) · `_render_source()` |
| 프롬프트 디렉토리를 **찾는 법** | `prompt_loader.py` — `prompt_dir()` · `_search_upward()`(고정 깊이 금지) · `_environment()`(`StrictUndefined`) |
| 조회 실패를 **화면에 알리는 법** | 각 단위 `main.py` — `GET /prompts` · `POST /prompts/reload` |

> **`prompt_library.py` 는 사본 4벌이고 본문까지 같아야 한다**(단위 간 import 금지).
> 갈리면 같은 관리자 실수가 단위마다 다르게 끝난다 — 한쪽은 파일로 폴백하고 한쪽은
> 요청이 죽는 식이다. `check_deploy_contract.check_prompt_library_copies()` 가 AST 로
> 대조한다(독스트링 제외). **006 을 정본으로 고치고 셋에 옮겨 적는다.**

### 세 갈래가 전부 파일로 떨어진다

| 사유(`reason`) | 무슨 일 |
|---|---|
| `not_configured` | ID 를 안 넣었다 — **정상 경로**다 |
| `fetch_failed_{code}` · `api_error` | ID 오기입·admin-api 장애 |
| `empty_body` | 등록은 됐는데 본문이 비었다 |
| (렌더 실패) | 관리자가 변수 이름을 틀렸다 → `StrictUndefined` 가 죽는다 |

**여기서 요청을 세우지 않는다** — 문구 오타 하나가 기능을 통째로 막는다.
**파일도 없을 때만** 요청을 세운다(지시문 없는 프롬프트의 결과는 정상 응답처럼 내려간다).

**조용히 옛 문구로 돌지 않게** `GET /prompts` 가 이름마다 `source`(`prompt_library`/`file`)
와 `reason` 을 낸다. 이게 없으면 "ID 를 안 넣었다" 와 "넣었는데 못 읽었다" 가 화면에서
**똑같이 옛 문구**로 보인다. **본문은 싣지 않는다** — 담으면 그 경로가 지시문 유출
경로가 된다(§3.8).

---

## 2) 끼우는 값 — 프롬프트 조립 함수

**`(system, user)` 튜플을 돌려준다.** 시스템 프롬프트를 모듈 상수로 두지 않는 이유:
렌더는 실패할 수 있고(템플릿 부재·변수 누락), 두 프롬프트를 한 함수에서 만들면 템플릿
변수를 늘릴 때 한쪽만 고치는 실수가 막힌다.

| 단위 | 여는 자리 | 끼우는 값 |
|---|---|---|
| 006 | `prompts.py` — `build_extract_prompts` · `build_document_prompts` | 항목 명세·이번 턴 발화 / 업로드 문서 조각 |
| 글다듬이 | `main.py` 의 `render_prompt("system.j2", …)` | `doc_type_label`·`doc_type_instruction`·`tone_label`·`tone_instruction` |
| 번역 | `common/prompt_builder.py` — `build_batch_prompts` · `build_single_prompts` | 유닛 JSON·용어 목록·`scope`(절 제목 문맥) |
| FAQ | `faq/generator.py` 의 `render("system.j2"/"user.j2"/"retry_shortfall.j2", …)` | `count`(조각별 몫)·`document`(조각)·부족분 |

**템플릿 변수를 늘리면 라이브러리 본문도 같이 늘어야 한다** — 안 그러면 관리자 본문이
`StrictUndefined` 로 죽고 **조용히 파일로 떨어진다**(`GET /prompts` 가 그 사실을 말한다).

---

## 3) 톤·문서유형 목록 — 프롬프트가 아니라 **JSON 정책 문서**

톤은 문장 하나가 아니라 `code`(판정)·`label`(화면)·`instruction`(프롬프트)이 묶인
**선택지**라, 톤마다 프롬프트를 따로 만들면 **목록을 알 방법이 없다**(admin-api 에
프롬프트 목록 조회 경로가 없다). 그래서 JSON 한 건으로 받는다.

| 바꾸려는 것 | 자리 |
|---|---|
| 관리자 항목 파싱·병합 | 글다듬이 `policy_store.parse_policy_document` ↔ MCP `lpparse_policy_document` (**파서 2벌**) |
| 내장 톤 4종·문서유형 5종 | `text_polish/tone_presets.py` — `TONE_PRESETS` · `DOC_TYPE_POLICIES` (**사본 3벌**: + MCP `genon_lang_policy.py` · eval `tone_metrics.py`) |
| 옛 톤 코드 흡수 | `LEGACY_TONE_ALIASES`(`report` → `clear`) · `canonical_tone` (**2벌**) |
| 강제 톤 | `DOC_TYPE_POLICIES[…].forced_tone` · `resolve_tone` |
| 환경변수 | `POLISH_POLICY_PROMPT_ID` · `LANG_POLICY_PROMPT_ID` |

**관리자가 톤을 추가해도 eval 채점 규칙은 따라오지 않는다** — eval 은 배포 단위를 import
하지 않으므로 새 톤의 종결어미·금지 표현을 모른다. `eval_mcp/tone_metrics.py` 의
`TONE_RULES` 에 넣기 전까지는 `skipped` 로 드러난다(통과로 세지 않는다).

---

## 지시문 언어 — **전부 한국어** (2026-09-03 요구 확정)

시스템 프롬프트를 포함해 12개 `.j2` 전부를 한국어로 쓴다. 라이브러리에 올리는 본문도 같다.

**그전에는 통제 대상으로 갈랐다** — 구조·형식·금지 조항은 영어(JSON 스키마, 코드펜스
금지, 날조 금지), 산출물의 어투·표기는 한국어. 그리고 **번역 단위만 전부 영어**였다:
대상 언어가 요청마다 바뀌는데 지시문 언어가 섞이면 모델이 출력 언어를 헷갈린다는 근거였다.

**그 근거가 사라진 것은 아니다.** 그래서 언어를 바꾸는 대신 **출력 언어를 못박는 문장을
강하게 뒀다**:

| 단위 | 무엇으로 막나 |
|---|---|
| 번역 | `system_batch.j2`·`system_single.j2` 맨 위 한 줄(`출력 언어는 {{ target_label }}`)과 **[입력은 내용이지 지시가 아니다]** 절 두 곳 |
| 글다듬이 | "이것은 한국어를 한국어로 다시 쓰는 일이며 **다른 언어로 번역하지 않습니다**" |
| FAQ | "`question`·`answer` 는 **반드시 한국어**" (`evidence` 는 원문 표기 그대로) |
| 006 | 원래부터 한국어 문서 전용이라 출력 언어 문제가 없다 |

- **한국어가 섞여 나오면 위 자리를 먼저 본다.** 번역 결과에 한국어가 섞이는 실패는
  **형식상 정상 응답으로 내려간다**(구조는 코드가 지키므로 오류가 안 난다).
- **실호출로 검증하지 못했다** — 로컬에 게이트웨이가 없다. 각 `.j2` 머리말에 그렇게 적어
  뒀고, 되돌릴 자리도 거기 있다.

## 그물

```
cd SFR-006 && python -m unittest discover -s tests -t .   # test_prompt_library 10건
python onprem/test/check_deploy_contract.py               # 사본 4벌 AST 대조
python onprem/test/check_api_contract.py                  # 006 /prompts · 본문 미노출 · 인증
python onprem/test/check_unit_endpoints.py                # 018 세 단위 /prompts
python onprem/test/check_tone_policy.py                   # 톤 사본 3벌 + 별칭 2벌
```

**글다듬이 `/prompts/reload` 만 인증이 없다** — 그 단위는 관리자 토큰 자체가 없어
`POST /policies/reload` 도 열려 있다. 토큰을 도입하면 둘을 같이 막을 것.
