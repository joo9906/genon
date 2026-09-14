# ONPREM — 폐쇄망에 올리는 것 전부

> **이 문서 하나로 이관이 된다.** 무엇을 몇 개 등록하는가 · 각 등록의 **핵심 파일** ·
> **필요한 환경변수** · 그리고 **지금 상태가 검증됐는가**.
>
> **코드 서빙 네 단위(#1~#4)는 판본이 둘이고 기능은 같다** (2026-09-14 기준).
> `onprem/codeserving/` 이 정본(`httpx` 로 게이트웨이를 직접 부른다)이고, `not/` 은
> 거기에 **`openai` SDK 전송**만 얹은 반입본이다 — 갈리는 자리는 목록으로 못박혀
> 있다(`not/check_not_units.py` 의 `EXPECTED_DIFF` **12** + `EXPECTED_EXTRA` **0**).
> **어느 쪽을 쳐도 기능이 같다** — 스트리밍 셋·hwpx 직접 업로드가 2026-09-11·09-14 에
> 정본으로 올라갔다. **고르는 기준은 사내 mirror 에 `openai` 패키지가 있느냐 하나다**
> (없으면 `pip install -r` 이 그 자리에서 서므로 정본을 친다).
> 설명은 `not/README.md`, 진행 기록은 `not/PROGRESS.md`.
> **기능별로 갈라 놓은 읽기용 배치가 `final/` 에 있다** (`python make_final.py` 가
> 만든다) — `final/<기능>/request` 에 `open_ai` 를 덮으면 SDK 판이 된다.
> 나머지 여섯(#5~#10, MCP 4 + 전처리기 2)은 `onprem/` 것 그대로다 — 그쪽은 표준
> 라이브러리만 쓰므로 판본이 갈리지 않는다.
>
> 저장소 다른 곳(`SFR-006/`·`SFR-018/`·`genos-project/`·`data/`)은 테스트·참조·
> 샘플이고 **올리지 않는다.**
>
> 최신 확인: **2026-09-14** — 점검 15개 **967건** + unittest **439건**, 전부 통과.
> (반입 판본 `not/` 의 그물 **92건**은 별도 집계다 — `onprem/` 회귀 기준이 아니라
>  그 판본이 정본과 갈리는 자리를 보는 것이다.)

---

## 1. 등록은 **10번**이다

| # | 영역 | 무엇 | 등록 형태 |
|---|---|---|---|
| 1 | 03 | `codeserving/SFR-006_template_fill/` | 코드 서빙 |
| 2 | 03 | `codeserving/SFR-018_text_polish/` | 코드 서빙 |
| 3 | 03 | `codeserving/SFR-018_translation/` | 코드 서빙 |
| 4 | 03 | `codeserving/SFR-018_faq/` | 코드 서빙 |
| 5 | 01 | `mcp/genon_text_guard.py` | MCP 도구 (**파일 1개 = 등록 1개**) |
| 6 | 01 | `mcp/genon_lang_policy.py` | MCP 도구 |
| 7 | 01 | `mcp/genon_glossary.py` | MCP 도구 |
| 8 | 01 | `mcp/genon_pii_audit.py` | MCP 도구 |
| 9 | 05 | `preprocessor/final_preprocessor.py` **또는** `smart_preprocessor.py` | 전처리기 — **적재(검색)용. 둘 중 하나만** (아래) |
| 10 | 05 | `preprocessor/only_me.py` | 전처리기 — **질의 시 첨부용** |

### 9번은 **둘 중 하나**다 — 벤더 절반이 다르다 (2026-09-08)

`final_preprocessor.py` 와 `smart_preprocessor.py` 는 같은 자리를 두고 겨루는 판본이다.
**hwpx 절반(PART 2)은 같은 코드**이고 갈리는 것은 벤더 절반뿐이다.

| | `final_preprocessor.py` | `smart_preprocessor.py` |
|---|---|---|
| 벤더 절반 | 첨부용 | **지능형** |
| **pdf** | 평문 + 문자 수 분할 — **표가 사라진다** | **docling + TableFormer + OCR** |
| **`.hwp`·`.hml`·오디오** | **네이티브** (GenosHwp SDK·Whisper) | 없다 |
| 조/항/호 위계 (pdf·docx) | 있다 | 아직 없다 |

**pdf 안의 표**가 중요하면 지능형, **`.hwp` 구버전·음성 파일**이 섞여 있으면 첨부용이다.
**같은 컬렉션에 둘을 걸지 않는다** — 같은 pdf 가 등록 시점에 따라 다른 청크로 들어가고
그 어긋남은 검색 품질로만 드러난다. 상세는 `preprocessor/README.md`.

그리고 **캔버스에 붙여 넣는 워크플로우 스텝 9개**(`workflow/*.py`). 서버가 뜨지 않으므로
등록 수에 들어가지 않지만 **이것이 없으면 아무 기능도 동작하지 않는다.**

올리지 않는 것: `eval/`(채점용 stdio MCP — 필요할 때 따로 띄운다) · `test/`(점검
스크립트) · `docs/`·`*.md`. `prompt/` 는 등록 단위가 아니지만 **코드서빙 이미지에 함께
들어가야 한다**(§5).

> 절차·화면 입력값의 정본은 [`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md).
> 이 문서는 **무엇이 어디서 돌고 무엇이 필요한가**를 담는다.

---

## 2. 기능 넷과 **핵심 파일**

네 기능 모두 같은 모양이다 — **캔버스 스텝(02)이 흐름을 쥐고, 무거운 일은 코드
서빙(03)이 하고, 결정적 판정은 MCP(01)가 한다.**

### 2-1. SFR-006 템플릿 채우기 (hwpx 양식을 대화로 채운다)

```
[02] sfr006_01_context  → POST /chat/context   템플릿 항목 목록 확보
                        → POST /chat/prefill   첨부 문서로 빈 항목 자동 채움
[02] sfr006_02_extract  → POST /chat/extract   이번 턴 발화에서 값 추출
[02] sfr006_03_commit   → POST /chat/commit    세션에 반영 + 답변 조립   ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `template_fill/chat_api.py` | 대화 세 라우트. **턴 하나의 계약이 여기 있다** |
| `template_fill/hwpx_fields.py` | 슬롯(`{'제목', 16pt}`) 인식·되쓰기 — **쓰기 경로의 정본** |
| `template_fill/hwpx_blocks.py` | 본문 문단 복제·추가 |
| `template_fill/doc_prefill.py` | 첨부 문서 자동 채움 (조각 분할·앞 조각 우선) |
| `template_fill/session_store.py` | Redis 턴 상태 (**전역 dict 금지** — 레플리카 2개면 깨진다) |
| `template_fill/prompts.py` | 프롬프트 조립 — 목록 이어붙이기·구획 넣고 빼기 |
| `template_fill/hwpx_markdown.py` | 채팅 미리보기용 마크다운 (표는 마크다운 유지) |

**전용 UI 가 없어 채팅이 곧 화면이다** — payload 는 `text`·`download_url` 이고
(+ 다운로드 버튼이 쓰는 `session_id`·`template_id`) 토큰 스트리밍을 유지한다.
**미리보기는 `text` 안에** 들어 있다 — 별도 필드(`document_markdown`)일 때는 그릴 창이
없어 아무 데도 안 그려졌다. `ready_for_download` 플래그는 없다: `download_url` 의 유무가
같은 것을 말하고, 둘을 두면 **버튼을 켜 놓고 받을 수 없는** 상태가 생긴다.
**다운로드는 넷 다 링크다** (2026-09-08) — 006 도 다 채웠을 때 hwpx 를 굳혀 올리고
`download_url` 만 싣는다. 옛 `POST /generate`(hwpx 직접 반환)는 CDN 업로드가 폐쇄망에서
되는지 미검증이라 **폴백으로 남겼다.**

### 2-2. SFR-018 글다듬이

```
[02] sfr018_polish_01_policy  → MCP resolve_tone        문서유형 → 톤 확정
[02] sfr018_polish_02_polish  → POST /polish            다듬기
                              → MCP ×3 (구조·사실·숫자)  점검과 겹쳐 돌린다   ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `main.py` | `/polish` 라우트 + 프롬프트 조립 (톤·문서유형 지시문 주입) |
| `text_polish/chunking.py` | 조각 분할 — **코드펜스·여러 줄 HTML 표 안에서 끊지 않는다** |
| `text_polish/polisher.py` | 조각을 동시에 돌리고 부분 실패는 **원문 유지** |
| `text_polish/tone_presets.py` | 톤 4종·문서유형 5종 표 (**사본 3벌 중 하나**) |
| `text_polish/file_store.py` | 결과 txt 를 CDN 에 굳혀 `download_url` 만 낸다 |

**무상태다** (Redis 없음) — 파일을 CDN 이 들고 있다.

### 2-3. SFR-018 번역

```
[02] sfr018_translate_01_detect    → genosUploaded 에서 원문 확보
                                   → MCP validate_direction  §6(한국어 축) 집행
[02] sfr018_translate_02_translate → POST /translate/markdown
                                   → MCP numeric_issues                      ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `translation_pipeline/office/markdown_units.py` | **스켈레톤 분해** — 구조는 코드가 쥐고 LLM 에는 문장만 준다 |
| `translation_pipeline/office/pipeline.py` | 배치 번역·단건 폴백·재조립 |
| `translation_pipeline/office/languages.py` | 언어 표·감지·방향 판정 (**MCP 사본과 짝**) |
| `translation_pipeline/common/glossary_exact.py` | 사내 용어 정확 매칭 (한국어 조사 폴백 포함) |
| `translation_pipeline/common/glossary_store.py` | 용어사전 API 적재 |
| `translation_pipeline/office/glossary_report.py` | 원문·번역문 **양쪽** `<mark>` 하이라이트 |
| `translation_pipeline/office/numeric_guard.py` | 숫자 지문 대조 |

### 2-4. SFR-018 FAQ

```
[02] sfr018_faq_01_source    → genosUploaded 에서 원문 확보 → GET /config
[02] sfr018_faq_02_generate  → POST /generate                              ※ 마지막
```

| 파일 | 하는 일 |
|---|---|
| `faq/chunking.py` | 긴 문서를 조각으로 + **총 개수를 조각에 고르게 배분**(`plan_quota`) |
| `faq/generator.py` | 생성·기각(스키마/근거/중복)·부족분 재요청 |
| `faq/evidence.py` | 근거 대조 — **문서 전체로** 한다 (조각 경계가 문장을 가르면 오탐) |
| `faq/session_store.py` | Redis (다운로드가 찾아온다) |
| `faq/txt_output.py` | 산출물 txt (BOM·CRLF — 메모장) |

**흘리지 않는다** — 산출물이 문답 목록이라 흘릴 것이 없다.

---

## 3. 첨부 문서는 **전처리기 산출물 하나**로 받는다 ⭐

> **요구 확정 (2026-09-07): MCP 로 문서를 파싱하지 않는다.**
> 네 기능의 파일 첨부는 **전부** 첨부용 전처리기 산출물을 쓴다.

### 지금 상태 — **전환 완료, 검증됨**

| 확인 항목 | 결과 |
|---|---|
| MCP `genon_hwpx_text.py` (hwpx 파싱 도구) | **파일째 삭제** — 등록 5개 → **4개** |
| `HWPX_TEXT_MCP_ID` 환경변수 | 참조 **0건** (스텝·문서 전부) |
| 캔버스 변수 `faq_hwpx_path`·`translate_hwpx_path` | 참조 **0건** |
| 첨부를 받는 스텝 넷 | **넷 다 `genosUploaded`** 하나만 읽는다 |
| 추출기 `_extract_uploaded_markdown` 사본 4벌 | 본문 **동일** |
| 남은 MCP 호출 | `resolve_tone` · `validate_direction` · `text_guard` ×4 — **파싱 아님** |

```
첨부 파일  →  [전처리기 #10 only_me.py]  →  genosUploaded  →  스텝 넷
                    (파싱만, 청킹 없음)      <doc …>본문</doc>
```

네 스텝이 읽는 자리:

| 기능 | 스텝 | 함수 |
|---|---|---|
| 006 | `sfr006_01_context.py` | `_uploaded_markdown` |
| 글다듬이 | `sfr018_polish_01_policy.py` | `_extract_uploaded_markdown` |
| 번역 | `sfr018_translate_01_detect.py` | `_extract_uploaded_markdown` |
| FAQ | `sfr018_faq_01_source.py` | `_extract_uploaded_markdown` |

넷 다 **태그가 없으면 통째로 본문으로 본다** — 배선에 따라 태그 없이 오는 경우가 있고,
그때 빈 문자열을 돌려주면 "문서를 올렸는데 아무 일도 안 일어난다" 가 된다.

### 왜 MCP 를 걷어냈나 (셋 다 실제로 밟았다)

1. **닿지 않았다.** 실환경에서 그 호출이 전부 `406`(Accept 헤더). 실패가 조용히
   전처리기 산출물로 폴백해서 **"표가 깨진 결과" 로만** 드러났다.
2. **미확인 가정 위에 있었다.** 캔버스 변수가 업로드 원본 경로를 담아 준다는 전제.
3. **같은 문서를 두 번 파싱했다.**

### 적재용(#9)과 첨부용(#10)은 **본문에 들어갈 것이 반대다**

| | #9 적재용 `final_preprocessor.py` | #10 첨부용 `only_me.py` |
|---|---|---|
| 소비자 | 임베딩·검색(RAG) | **네 기능이 LLM 에 그대로 던지는 원문** |
| 조문 머리말 `제2장 총칙 > 제5조(목적)` | **넣는다** (임베딩되는 문자열에 있어야 걸린다) | **넣지 않는다** |
| 표 조각 머리말·겹침 | 넣는다 | 넣지 않는다 |
| 청킹 | 한다 | **하지 않는다** — 레코드 크기 상한(20만 자)에서만 자른다 |
| 계약 | 검색이 걸리는가 | **무손실** — 레코드를 이어붙이면 원문이다 |
| 줄 수 | 5,958 | 1,670 |

**첨부에 #9 를 걸면** 번역이 원문에 없던 머리말을 **번역해서 결과물에 싣고**, FAQ 는
그것을 원문 문장으로 보고 근거 대조를 하며, 006 자동 채움은 문서 내용으로 읽는다.
셋 다 오류가 아니라 **결과물의 내용으로만** 드러난다. 실측 — 기술협상서 한 벌이
적재용 18레코드 13,460자 / 첨부용 1레코드 9,901자로, **3,559자가 검색용 장식**이었다.

- **둘을 같은 서버에 함께 올리지 않는다** — 진입점 이름이 둘 다 `DocumentProcessor` 라
  나중에 로드된 것이 앞엣것을 덮는다.
- **받을 확장자는 둘 다 `hwpx` 만** 건다. 나머지(pdf·docx·txt·오디오…)는 사이트의
  기존 첨부용 등록이 이미 맡는다. `.hwp`(구버전 바이너리)도 그쪽이다 — 우리 파서는
  zip 기반 hwpx 전용이고, 잘못 걸린 매핑은 `SUPPORTED_EXTENSIONS` 가 즉시 세운다.

### 그래도 남는 hwpx 파서 — **직접 업로드 경로**

캔버스를 지나지 않는 HTTP 경로가 셋 있고, 그쪽은 전처리기 산출물이 없어 **자기
파서로 읽는다**: `POST /translate/hwpx` · `POST /generate/upload`(FAQ) ·
`POST /generate/upload`(006). 그래서 파싱 코어 사본이 **5벌**로 남는다 —
전처리기 2벌(#9 정본 + #10) + 번역·FAQ·006. `test/check_table_grid.py`(34건)가
**출력으로** 대조한다.

### 미검증 (폐쇄망에서 확인할 것)

- 첨부용 등록의 산출물이 실제로 `genosUploaded` 로 실려 오는지, 그 형태가
  `<doc …>본문</doc>` 인지. **아니면 원문이 비어 `NO_INPUT` 으로 드러난다.**
- hwpx 적재 결과가 GenOS 적재 결과 화면에 뜨는지(페이지 자리에 구역을 넣었다).

---

## 4. MCP 도구 4개 — **확인 결과**

**MCP 는 서빙이 아니라 파일이다.** GenOS 가 소스 파일 한 개를 실행하고 `mcp` 객체를
전역으로 주입한다. FastAPI 앱도 `/health` 도 `$PORT` 도 `requirements.txt` 도 없다.

| 파일 | 접두어 | 도구 | 누가 부르나 |
|---|---|---|---|
| `genon_text_guard.py` | `TG` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` | 글다듬이-2 · 번역-2 |
| `genon_lang_policy.py` | `LP` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 글다듬이-1 · 번역-1 |
| `genon_glossary.py` | `GL` | `glossary_lookup` `glossary_status` `glossary_reload` | **스텝은 안 부른다** (번역 코드서빙이 자체 처리) |
| `genon_pii_audit.py` | `PA` | `pii_audit` `pii_scan_text` `pii_detectors` | **사람이 직접** (야간·주간 감사) |

**도구 16개**(`TG` 4 + `LP` 6 + `GL` 3 + `PA` 3). 등록 뒤 `tools/list` 로 센다 —
**하나라도 비면 이름이 겹쳐 덮인 것이고**, 그 실패는 "도구가 이상한 값을 낸다" 로만
드러난다. 그래서 도구 함수를 뺀 모든 최상위 심볼에 접두어가 붙어 있다.

### 검증됨 (`test/check_mcp_tools.py` **86건**)

- **네 파일을 한 네임스페이스에 넣어** 덮이는지 본다 (한 서버에 같이 로드될 수 있다)
- 도구를 직접 불러 **결정적 판정**을 확인한다 (호출 성공만 보면 빈 결과도 통과한다)
- **빈 문자열 주입**을 견딘다 — GenOS 는 값이 없을 때 `None` 이 아니라 `""` 를 준다.
  선택 인자를 `int`/`float` 로만 선언하면 **본문에 닿기 전에 타입 검증에서 죽는다**
- 선택지(언어·문체·문서유형·톤)가 **도구 스키마 enum 에 실리는가** ↔ 표와 대조
- PII 판정부가 `eval/eval_mcp/pii_metrics.py` 사본과 **같은 입력에 같은 판정**인가

`test/check_deploy_contract.py` 가 정적으로: 접두어 · `async … -> str` · `mcp` shim ·
상대 import 금지 · **`print` 금지**(stdout 은 MCP 전송 채널이라 한 줄만 섞여도
프로토콜이 깨진다) · stderr 로깅.

### 넷 다 **표준 라이브러리만 쓴다** ⭐

`lxml` 을 파일 안에서 설치하던 `genon_hwpx_text.py` 가 빠지면서, **폐쇄망 mirror
접근이 없어도 MCP 등록 넷이 다 뜬다.** `requirements.txt` 라는 개념이 없으므로 이건
사소한 이득이 아니다.

### 전송 규약 — 여기서 한 번 크게 물렸다

```
{GENOS_URL}/api/gateway/mcp/{serving_id}/mcp     JSON-RPC  tools/call
Accept: application/json, text/event-stream       ← 둘 다 열거해야 한다
```

MCP 스트리머블 HTTP 서버는 **POST 본문을 읽기 전에** Accept 를 본다. httpx 기본값
(`*/*`)은 그 검사를 통과하지 못해 `406` 이고, **도구를 아무리 고쳐도 닿지 않는다.**
응답은 SSE 프레임으로 올 수 있으므로 `response.json()` 만 쓰면 도구는 돌았는데
결과만 사라진다. `_decode_body` 가 두 모양을 다 받고, `result`/`error` 를 든 프레임이
응답이다(앞쪽 `method` 프레임은 진행 알림이다).

`test/check_workflow_run.py` 의 `_check_mcp_transport` 가 **HTTP 경계에 대역을 꽂아**
스텝이 실제로 내보내는 헤더를 받아 본다 — 그전에는 `_mcp_call` 을 통째로 대역으로
바꿔서 **이 층이 검사된 적이 없었다.**

**다음에 나올 수 있는 실패**: `400 Missing session ID`. 서버가 상태 유지 모드면
`initialize` → `Mcp-Session-Id` 핸드셰이크가 필요하다. 지금은 상태 없는 모드를
전제한다 — **미검증**이고 고칠 자리는 `_mcp_call` 하나다.

---

## 5. 환경변수

### 5-1. 워크플로우 스텝 9개 (캔버스 Python 스텝 환경 설정)

| 이름 | 필요한 스텝 | 없으면 |
|---|---|---|
| `GENOS_URL` | **전부** | 게이트웨이를 못 찾는다 (`CONFIG_MISSING`) |
| `GENOS_TOKEN` | **전부** | 인증 실패 |
| `TEMPLATE_FILL_SERVING_ID` | 006-1·2·3 | |
| `TEXT_POLISH_SERVING_ID` | 다듬-2 | |
| `TRANSLATION_SERVING_ID` | 번역-2 | |
| `FAQ_SERVING_ID` | FAQ-1·2 | |
| `LANG_POLICY_MCP_ID` | 다듬-1, 번역-1 | 톤 확정·방향 검증이 안 된다 |
| `TEXT_GUARD_MCP_ID` | 다듬-2, 번역-2 | 구조·사실·숫자 점검이 안 된다 |
| `GENON_DEBUG` | (선택) | `0` 으로 끈다. **기본은 켜짐** — §6 |

`HWPX_TEXT_MCP_ID` 는 **없다** (2026-09-07). 첨부는 전처리기 산출물만 쓴다.
`GLOSSARY_MCP_ID`·PII 감사 ID 도 스텝이 쓰지 않는다.

### 5-2. 코드 서빙 4개 — **게이트웨이 3종이 필수다**

| 이름 | 단위 | 없으면 |
|---|---|---|
| `GENOS_URL` | 넷 다 | **`CONFIG_MISSING`** — 재시도 불가로 갈라 낸다 |
| `LLM_SERVING_ID` | 넷 다 | 같음. **모델도 이 값이 정한다** (`LLM_MODEL_ID` 는 없앴다) |
| `GENOS_TOKEN` | 넷 다 | 인증 실패 |

> **셋은 호출 시점에 읽는다** (`Config.genos_url()` 꼴 정적 메서드) — 프로세스가 뜬
> 뒤 환경이 채워지는 경로가 있다. **나머지 값은 import 시점에 굳으므로 운영에서
> 바꾸려면 서빙을 재기동해야 한다** (`LLM_RETRY_COUNT` 가 그 예다).

**Redis** — 006·FAQ 만 필요하다(`REDIS_URL`). 글다듬이·번역은 무상태다.

**CDN(내려받기 링크)** — `GENOS_CDN_UPLOAD_URL`·`GENOS_CDN_HOSTNAME`. 기본값이
있으므로 안 넣어도 뜨지만, 틀리면 **결과는 나오는데 파일만 못 받는다**(fail-open —
업로드 실패로 결과를 통째로 버리지 않는다). 등록 뒤 한 번은 링크를 눌러 볼 것.

> **기본값은 GenOS 참조 샘플과 대조해 확인했다** (2026-09-08, `not/minio.py`) —
> 업로드 URL `http://llmops-cdn-api-service:8080/minio/upload/temp`, 멀티파트 필드
> `hostname`+`file`, 응답에서 링크를 꺼내는 경로 `data.presigned_url`. 넷이 우리
> `file_store.py` 와 같다. **네 기능이 모두 이 경로를 쓴다**(006 은 2026-09-08 부터).

**용어사전** (번역·`genon_glossary` 공용, 쓸 때만):
`TRANSLATE_GLOSSARY_API_URL` · `_DRIVE_ID` · `_WORKSPACE_ID` (+ 토큰이 다르면 `_TOKEN`).
셋 중 하나라도 없으면 **용어사전 없이 동작**하고 그 사실이 `glossary_status` 의
`reason` 으로 드러난다 — 조용히 "적재됨" 으로 보이지 않는 것이 요점이다.

**프롬프트 라이브러리** (선택): `GENOS_ADMIN_API_URL` + `<단위>_PROMPT_IDS`
(`TEMPLATE_FILL_PROMPT_IDS`·`POLISH_PROMPT_IDS`·`TRANSLATE_PROMPT_IDS`·`FAQ_PROMPT_IDS`).
`이름=ID` 꼴이고 **이름은 프롬프트 파일 이름에서 확장자를 뗀 것**이다. 안 넣으면
이미지에 든 `.txt` 파일로 돈다 — `GET /prompts` 가 어느 쪽을 썼는지 말한다.

**GenOS 가 주입한다** (다른 목적으로 쓰지 않는다): `PORT` · `OPENAPI_PATH` ·
`LANGUAGE` · `BUILD_COMMAND` · `START_COMMAND`.

### 5-3. 손잡이 — 기본값으로 두어도 되지만 알아 둘 것

| 이름 | 기본 | 단위 | 뜻 |
|---|---|---|---|
| `RES_TIMEOUT` | 90 | 넷 다 | LLM 응답 대기(초) |
| `LLM_RETRY_COUNT` | — | 넷 다 | **4xx 는 재시도하지 않는다** (2026-09-07) |
| `LLM_CONCURRENCY` | 15 | 번역 | 배치 동시 실행 |
| `POLISH_MAX_CHUNK_CHARS` | 6000 | 다듬 | 조각 하나 = 호출 하나의 예산 |
| `POLISH_MAX_INPUT_CHARS` | 200000 | 다듬 | 넘으면 **자르지 않고 요청을 세운다** |
| `FAQ_MAX_COUNT` | 30 | FAQ | 사용자가 고를 수 있는 **총** 개수 |
| `FAQ_MAX_CHUNK_CALLS` | 6 | FAQ | **비용 손잡이** — 태울 구간 수 |
| `FAQ_MAX_CONTEXT_CHARS` | 12000 | FAQ | 호출 **한 번**의 예산 (문서 상한이 아니다) |
| `FAQ_MAX_CONTEXT_CHUNKS` | 80 | FAQ | 조각 수 상한 (80 × 12,000 ≈ 96만 자) |
| `FAQ_LLM_CONCURRENCY` | 6 | FAQ | **동시에 도는 구간 수** — 429 면 여기부터 내린다 |
| `TEMPLATE_FILL_DOC_PREFILL` | 1 | 006 | `0` 이면 첨부 자동 채움을 끈다 |
| `TEMPLATE_FILL_DOC_CHUNK_CHARS` | 12000 | 006 | 자동 채움 조각 크기 |
| `TRANSLATE_MAX_TOTAL_CHARS` | 500000 | 번역 | 넘으면 **자르지 않고 오류다** |

> **개수는 사용자가, 비용은 배포가 정한다.** 한 손잡이에 묶으면 둘 중 하나를 못 지킨다.

### 5-4. 프롬프트 파일은 **이미지에 함께 들어가야 한다**

`prompt/{SFR-006_template_fill, SFR-018_text_polish, SFR-018_translation, SFR-018_faq}/`
— 배포 단위 **바깥**이지만 없으면 **템플릿 부재로 요청이 선다**(빈 프롬프트로 넘어가지
않는다 — 지시문 없는 프롬프트의 결과는 정상 응답처럼 내려간다). 위치가 다르면
`<단위>_PROMPT_DIR` 로 통째 지정한다.

**확장자는 `.txt` 다** (2026-09-07 jinja 제거). 로더는 `{{ name }}` 치환만 하므로
**목록을 이어붙이는 것과 절을 넣고 빼는 판단은 조립 함수의 몫이다** —
`test/check_prompt_render.py`(71건)가 네 단위의 실제 빌더를 불러 그 계약을 본다.

---

## 6. 디버그 에코 — **테스트 기간 한정**

3.8절 화이트리스트가 값을 버리기 때문에(허용 목록 밖은 **이름만** 남는다) 로그만으로는
무엇이 왜 실패했는지 알 수 없다. 위 `406` 이 그 증거다 — 사유가 응답 본문에만 있었고
로그에는 상태코드만 남았다.

- **`GENON_DEBUG=0` 으로 끈다. 기본은 켜짐** — 지금은 원인 추적이 목적이다.
- `print` 가 아니라 **`sys.stderr.write`** 다. stdout 은 MCP·스트리밍의 전송 채널이다.
- 값은 **300자에서 자르고** 인자는 **키만** 싣는다 — 문서 원문·프롬프트가 통째로
  실리면 이 에코 자체가 유출 경로가 된다.
- **걷어낼 때는 각 파일의 `디버그 에코` 블록과 그 호출만 지운다** — 로그 경로는
  손대지 않았으므로 지우면 원래 규약으로 정확히 돌아온다.

오류 코드에는 **`ERR-` 접두어**가 붙는다(`ERR-02-00020003`). 분류 판정은 그대로 **뒤
8자리**로 한다.

---

## 7. 이관은 **파일이 아니라 사람이 건넌다**

폐쇄망에 파일을 넣을 수 없다 — **화면에 띄워 놓고 타이핑한다.**

| 조각 | 줄 | 실제로 치는 양 |
|---|---|---|
| `final_preprocessor.py` PART 1 첨부용 (벤더) | 2,587 | **1줄 수정** (`class DocumentProcessor:` → `AttachDocumentProcessor`) |
| PART 2 hwpx 파서 | 2,360 | 2,360 |
| PART 3 라우터 | 891 | 891 |

**벤더 절반은 이미 그쪽에 있다** — `genos_files/attach_processor.py` 는 온프레미스에서
긁어온 참조 사본이고 원본이 첨부용 전처리기로 등록돼 있다. 그 사본을 떠서 우리 코드를
이어 붙이면 되므로 에어갭을 건너는 것은 **PART 2·3 뿐**이다.

- **PART 1 은 되도록 손대지 않는다.** 2026-09-03 에 빌드 스크립트를 걷어내면서
  "생성물이 원본과 같은가"(AST 대조) 판정이 없어졌다 — 그 판정이 벤더 참조 사본의
  오타(`split_docuㄱments`)를 실제로 잡은 적이 있다. 고쳐야 하면
  `genos_files/attach_processor.py` 와 **눈으로 대조한다.**
- **가드 한 자리가 외부와 다르다.** 이 파일은 PART 1 을 `try:` 안에 넣는데 그건 우리
  사정이다(로컬에 docling 이 없어도 점검이 돌아야 한다). 온프레미스에서는
  `_FP_ATTACH_IMPORT_ERROR = None` 두 줄이 그 자리를 메운다.

---

## 8. 검증 — 지금 상태

```bash
export PYTHONIOENCODING=utf-8   # Windows 콘솔 필수 (cp949 가 '—' 에서 죽는다)
export SSL_CERT_FILE=           # conda 기본값이 없는 경로를 가리키면 두 단위가 실패한다
```

| 점검 | 건수 | 무엇을 보나 |
|---|---|---|
| `check_deploy_contract.py` | **64** (WARN 3) | 배포 계약을 소스만 읽고 (코드서빙 4 + MCP **4** + eval + 스텝 9) |
| `check_service_boot.py` | 16 | 실제로 띄운다 — lifespan·`/health`·`/` |
| `check_api_contract.py` | **53** | 006 엔드포인트 |
| `check_unit_endpoints.py` | **119** | 018 세 단위 엔드포인트 경계 |
| `check_chat_turn.py` | **47** | 대화 한 턴 계약·상태 전이 (02 스텝 3개 ↔ 03) |
| `check_workflow_run.py` | **118** | 스텝 9개 실행 + **MCP 전송 규약** + 무엇을 흘렸는가 + **스트리밍 전송 규약 셋**(글다듬이·번역·FAQ) |
| `check_mcp_tools.py` | **86** | MCP 파일 4개 공존·결정적 판정·빈 문자열 주입 |
| `check_final_preprocessor.py` | 171 | 전처리기(첨부용 + hwpx) — 라우팅·조문 위계·무손실 |
| `check_smart_preprocessor.py` | **52** ⭐신규 | 전처리기(**지능형** + hwpx) — 합치기·개명·라우팅·**스키마 정렬** |
| `check_table_grid.py` | **34** | 파싱 코어 사본 대조 (**출력으로**, 텍스트가 아니다) |
| `check_prompt_render.py` | **77** | 프롬프트가 실제로 렌더되는가 |
| `check_eval_metrics.py` | 88 | **가드레일 자체** 점검 |
| `check_tone_policy.py` | 20 | 톤 사본 3벌 대조 |
| `check_body_blocks.py` | 17 | 문단 복제 안전장치 |
| `check_output_safety.py` | 5 | 파트 선언·누름틀 안내문 |
| **합계** | **967** | + unittest **439** (SFR-006 64 · SFR-018 375) = **1,406** |

**전부 종료 코드 0** (2026-09-14 실측). 이 숫자가 곧 회귀 감지 기준이므로 점검을
고칠 때 여기를 같이 고친다 — 낡으면 판정이 사라져도 알 수 없다.

### 이번에 함께 고친 것 — 프롬프트 조립이 깨져 있었다

jinja 를 걷어내면서 **템플릿은 새 규약으로 다시 썼는데 조립 함수는 옛 변수 이름을
그대로 넘기고 있었다.** 실측으로 넷이 렌더에서 죽었다:

| 자리 | 템플릿이 요구 | 빌더가 주던 것 |
|---|---|---|
| 006 문서 자동 채움 | `chunk_note` | `chunk_index`·`chunk_total` |
| 번역 배치·단건 | `glossary_block` · `context_line` | `glossary`(list) · `scope` |
| FAQ 부족분 재요청 | `existing_block` | `existing_questions`(list) |
| 글다듬이 | `doc_type_block` | `doc_type_instruction` |

**넷 다 fail-open 이라 조용했다** — 006 은 `prefill_failed` 한 줄만 남기고(문서를
올렸는데 아무 일도 일어나지 않는다), FAQ 는 1차 결과를 그대로 쓰고 포기하며, 번역은
사유가 `prompt_render_failed` 라 "LLM 이 안 된다" 와 **로그에서만** 갈린다.
**이 층을 보는 점검이 하나도 없어서** 넉 달을 살아남았다.

리스트를 그대로 넘기면 **렌더가 죽지 않는 경우**도 있다 — 로더가 `str(value)` 로
떨어뜨려 `['- 제목 (미입력)']` 이라는 파이썬 repr 이 프롬프트에 실린다. 오류가 아니라
결과물 품질로만 드러나므로 새 점검이 그것도 따로 본다. **여섯 갈래를 각각 되돌려
FAIL 을 확인했다.**

---

## 9. 남은 미검증 — 폐쇄망에서 확인할 것

| # | 무엇 | 아니면 어떻게 드러나나 |
|---|---|---|
| 1 | **첨부용 전처리기 산출물이 `genosUploaded` 로 오는지**, 형태가 `<doc …>본문</doc>` 인지 | 원문이 비어 `NO_INPUT` — "첨부를 안 했다" 로 보인다 |
| 2 | MCP 서버가 **상태 없는 모드**인지 | `400 Missing session ID`. 고칠 자리는 `_mcp_call` 하나 |
| 3 | 내려받기 링크(MinIO/CDN)가 **실제로 되는지** — 모양은 참조 샘플(`not/minio.py`)과 대조해 맞췄다 | **결과는 나오는데 파일만 못 받는다.** 옛 `POST /download`(018) · `POST /generate`(006)를 폴백으로 남겼다 |
| 4 | 게이트웨이가 `model` 없는 요청을 받는지 | 400/422. 되살릴 자리는 **여덟** (네 `config.py` + 네 `llm.py`) |
| 5 | hwpx 적재 결과가 **적재 결과 화면**에 뜨는지 | 빈 목록 — 오류가 아니다. 되돌릴 자리는 `_page_fields` 하나 |
| 6 | 빌드·시작 커맨드가 **셸을 거치는지** (`cd A && B`) | 안 먹으면 `uvicorn --app-dir <경로>` 로 바꾼다 |
| 7 | LLM 실호출 품질 (프롬프트가 전부 한국어가 됐다) | 한국어가 섞여 나오면 각 `*.txt` 의 출력 언어 고정 문장을 먼저 볼 것 |
| 8 | 내려준 `.txt` 를 **윈도우 메모장**에서 열어보기 | BOM·CRLF 는 응답 바이트로만 확인했다 |
| 9 | pdf 표 품질 (첨부용 pdf 는 평문 + 문자 수 분할) | "표를 물어봤는데 답이 이상하다" — 설계는 `docs/WIP_pdf_tables.md` |

---

## 10. 더 읽을 곳

| 문서 | 무엇 |
|---|---|
| [`docs/SERVING_REGISTRY.md`](docs/SERVING_REGISTRY.md) | **등록 작업지시서** — 화면 각 칸에 무엇을 적나 |
| [`README.md`](README.md) | 환경변수의 **의미**·기능별 운영 규약 (정본) |
| [`docs/FEATURES.md`](docs/FEATURES.md) | 무엇이 구현돼 있고 어느 경로로 부르나 |
| [`preprocessor/README.md`](preprocessor/README.md) | 전처리기 — 조문 위계·표 HTML·첨부용 |
| [`mcp/README.md`](mcp/README.md) | MCP 규율 (접두어·shim·빈 문자열) |
| [`workflow/README.md`](workflow/README.md) | 스텝 9개·순서·스트리밍 규약 |
| [`test/README.md`](test/README.md) | 점검이 무엇을 보고 무엇을 못 보나 |
| [`eval/README.md`](eval/README.md) | 평가지표·합불 기준 |
| `../CLAUDE.md` | **왜 그렇게 했나** — 되돌리면 안 되는 근거 |
