# 2026-08-28 변경 — 파일별·함수별

세 갈래다. 셋 다 **화면이 원문과 결과를 좌우로 놓고 비교한다**는 요구에서 나왔다.

| # | 무엇 | 왜 |
|---|---|---|
| ⓪ | **한국어 조사 정규화** | `가맹점을` 이 한 토큰이라 사전과 매칭되지 않았다 — **프롬프트·준수율·하이라이트가 함께 틀리고 있었다** |
| ① | 변경 하이라이트 **건수 상한 제거** | 잘린 목록으로 사본을 만들어 **상한이 곧 하이라이트 상한**이었다 — 51번째 변경부터 `<mark>` 가 안 붙었다 |
| ② | **원문·결과 양쪽** 하이라이트 | 좌우 비교인데 한쪽만 칠하면 **삭제된 낱말이 어디에도 안 보인다** |
| ③ | 내려받기를 **MinIO 링크**로 | 프론트가 정본 텍스트를 되돌려 보낼 이유가 사라졌다 |

**등록 단위 수·시작 커맨드는 바뀌지 않았다** — 재등록이 아니라 리비전 갱신이다.
환경변수는 둘 늘었다(`GENOS_CDN_UPLOAD_URL`·`GENOS_CDN_HOSTNAME`, 둘 다 기본값 있음).

---

## ⓪ 한국어 조사 정규화 — 하이라이트보다 앞단이 깨져 있었다

| 방향 | 어디서 | 증상 |
|---|---|---|
| ko→en | `match_occurrences` 0건 | **그 용어가 프롬프트에 실리지 않는다.** 준수율은 `matched_count=0` 이라 **1.0** |
| en→ko | `contains_phrase` False | `신용회복위원회를` 로 제대로 옮겼는데 **준수율 0.0**, 양쪽 형광 없음 |

두 증상이 반대 방향(1.0 / 0.0)이라 **지표만 보면 서로를 가린다.**

| 파일 | 함수 | 변경 |
|---|---|---|
| `common/glossary_exact.py` | `strip_ko_particle` **(신규)** | 닫힌 조사 목록으로 절단. 떼고 2자 미만이면 적용 안 함 |
| | `_token_eq` **(신규)** | 문서 토큰 == 사전 토큰 **또는** 조사를 뗀 형태가 같은가. **방향이 한쪽이다** — 조사는 문서 쪽에만 붙는다 |
| | `match_occurrences` | 색인 조회에 폴백(정확 일치 먼저), 여러 낱말 용어는 **낱말마다** 본다 |
| | `contains_phrase` · `phrase_positions` | 같은 규칙으로 맞췄다 — 갈리면 "썼다는데 위치는 못 찾는" 상태가 된다 |
| `mcp/genon_glossary.py` | 같은 것 (`GL` 접두어) | 사본 2벌. 한쪽만 고치면 워크플로우/직접 업로드가 **다른 용어 목록**을 쓴다 |

- **형태소 분석기는 필요 없다.** 사전 용어는 대부분 명사이고 뒤에 붙는 조사는 닫힌
  목록이라 영어 `_EN_SUFFIX_RULES` 와 같은 구조로 끝난다.
- **색인이 아니라 조회할 때 뗀다.** 색인 키를 깎으면 `신용도` 가 `신용` 으로 굳어
  표제어가 사라진다. 사전에 둘 다 있으면 **정확 일치가 먼저 이긴다.**
- **칠하는 구간은 문서에 실제로 적힌 글자** — `<mark>신용회복위원회를</mark>` 처럼
  조사까지 덮는다(`invoice` 가 `invoices` 를 덮는 기존 규약과 같다).
- **한계**: 3자 이상이면서 조사 글자로 끝나는 표제어가 사전에 없고 절단형만 있으면
  그쪽으로 걸린다. 과절단은 2자 가드가 막는다(`추가`→`추` 금지).

---

## ① 하이라이트 건수 상한 제거

| 파일 | 함수 | 변경 |
|---|---|---|
| `onprem/mcp/genon_text_guard.py` | `tgbuild_change_list` | `max_items` 인자·조기 반환 제거. `changes.extend(...)` 로 전량 산출 |
| | `_TGdiff_changes` | `max_items` 검증(`INVALID_TYPE`/`OUT_OF_RANGE`) 제거, 응답에서 **`truncated` 제거** |
| | `diff_changes` (도구) | 시그니처에서 `max_items` 제거 |
| `onprem/workflow/sfr018_polish_02_polish.py` | `run` | `changes_truncated` 수집·안내문(`⚠ 변경이 많아 앞쪽 N건만…`) 제거 |

- **`truncated` 를 남기지 않은 이유**: 상한이 사라져 **언제나 false 인 필드**가 된다.
  그런 필드는 읽는 쪽이 "확인했다" 고 믿게 만든다.
- 크기의 실제 상한은 **입력 길이**(`_TGMAX_TEXT_CHARS` = 400,000자)가 잡는다. 그쪽은
  넘으면 자르지 않고 `TOO_LONG_*` 로 요청을 세우므로 조용히 빠지는 경로가 아니다.

## ② 원문·결과 양쪽 하이라이트

### 글다듬이 (diff 기반) — 좌표를 **계산해 놓고 버리고 있었다**

`_TGwords` 가 before·after 양쪽을 이미 문서 절대 좌표로 펴고 있었는데 `after` 쪽만 썼다.

| 파일 | 함수 | 변경 |
|---|---|---|
| `onprem/mcp/genon_text_guard.py` | `_TGspan` **(신규)** | 낱말 구간 → 문서 절대 좌표. 빈 구간은 `None`(0 을 넣으면 문서 맨 앞이 칠해진다) |
| | `_TGchange` **(신규)** | 변경 항목 조립 — `{before, after, source_span, target_span}`. **옛 이름 `span` 은 내지 않는다** |
| | `_TGword_changes` | 세 갈래(삭제만·삽입만·일반) 전부 양쪽 좌표를 낸다 |
| | `tgbuild_highlighted` | `key` 인자 추가 — `source_span`/`target_span` 으로 **같은 함수를 두 번** 부른다 |
| | `_TGdiff_changes` | 응답에 **`source_highlighted`** 추가 |
| `onprem/workflow/sfr018_polish_02_polish.py` | `run` | `source_highlighted` 수집 → payload `original_text` |

| 변경 | `source_span` | `target_span` | 화면 |
|---|---|---|---|
| 치환 | 있음 | 있음 | 양쪽 형광 |
| **삭제** | **있음** | `null` | **왼쪽만** — 예전에는 어디에도 안 보였다 |
| 삽입 | `null` | 있음 | 오른쪽만 |

- **조립기는 하나다.** 원문 전용 경로를 두면 겹침 병합·보호 구간 규칙이 두 벌이 되고,
  한쪽만 고치는 실수는 **표가 깨지는 형태로만** 드러난다.
- **보호 구간은 각 텍스트에서 따로 계산한다.** 코드펜스·HTML 태그 위치가 원문과 결과에서
  다르므로 한쪽 좌표를 다른 쪽에 쓰면 `<td rowspan="2">` 한가운데를 가른다.

### 번역 (용어사전 기반) — 좌표는 원래 양쪽 다 있었다

`hits[].spans`(원문 유닛 기준)와 `hits[].target_spans`(번역문 유닛 기준). 뒤엣것만 썼다.

| 파일 | 함수 | 변경 |
|---|---|---|
| `office/glossary_report.py` | `highlight_units` **(개명·일반화)** | `span_key`·`applied_only` 인자. 옛 `highlight_translations` 는 얇은 진입점으로 유지 |
| | `highlight_sources` **(신규)** | 원문 사본 — `span_key="spans"`, `applied_only=True` |
| `office/types.py` | `MarkdownTranslationArtifacts` | `source_markdown_highlighted` 필드 추가 |
| `office/pipeline.py` | `run_markdown_translation_job` | 원문 사본도 **같은 `rebuild_markdown`** 을 태운다 |
| `api_contract.py` | `markdown_payload` | `source_markdown_highlighted` 노출 |
| `onprem/workflow/sfr018_translate_02_translate.py` | `run` | 수집 → payload `original_text` |

- **판정 기준은 양쪽이 같다** — **실제로 참고한 것만**. 요구사항 §2 가 하이라이트에
  요구하는 것이 "어떤 단어가 용어사전의 어떤 단어를 참고하였는지" 라서, 참고하지 않은
  자리는 그 관계가 없어 칠할 것이 없다. 원문에 나오기만 하면 칠하는 방식도 가능하지만
  (미준수가 화면에 드러난다) **형광이 두 가지를 뜻하게 된다.** 미준수는
  `term_map_unapplied` 와 준수율이 맡는 **검수용** 값이고, `term_map` 이 미적용을 담지
  않는 것과 같은 기준이다.
- **사전에 걸린 낱말만 감싼다** — 문장·유닛 단위가 아니다. `I love ccrs` 에서 `ccrs` 만
  사전에 있으면 `I love` 는 그대로 남는다(`hits[].spans` 가 낱말의 문자 위치다).
  `applied_only` 인자를 남긴 것은 **판정을 인자로 드러내기 위해서**다 — 두 호출이 같은
  값을 넘기더라도 코드에 보이면 나중에 한쪽만 바꾸는 것이 눈에 띈다.

## ③ 내려받기 — MinIO 링크

| 파일 | 변경 |
|---|---|
| `{text_polish,translation_pipeline/common,faq}/file_store.py` **(신규 3벌)** | `upload_bytes(data, filename, media_type) -> str`. 실패하면 `""`(fail-open) |
| `*/txt_output.py` (3벌) | `download_filename(stem)` 추가 — `content_disposition` 은 RFC 5987 이라 업로드 폼에 못 쓴다 |
| 글다듬이 `main.py` | `PolishRequest.title` 추가, `/polish` 응답에 `download_url` |
| 번역 `main.py` | `_upload_result` 헬퍼 + 두 라우트(`/translate/markdown`·`/translate/hwpx`)에 배선. hwpx 는 `title` 폼 필드 추가 |
| 번역 `api_contract.py` | `TranslateMarkdownRequest.title`, `markdown_payload(artifacts, download_url)` |
| FAQ `faq/main.py` | `_generate_and_store` 가 채택분을 올리고 `download_url` |
| 워크플로우 스텝 3개 | `download_url` 전달. FAQ 는 `faq_download_ready` → `download_url` |

**참고 코드(운영 MCP 예제)를 그대로 옮기지 않은 세 가지**:

1. **동기 `urllib` → `httpx.AsyncClient`.** async 라우트에서 동기 HTTP 는 그 워커의
   이벤트 루프를 업로드 내내 멈춘다 (가이드 3.4).
2. **예외 원문을 반환하지 않는다.** 예제는 `f"오류 발생: {e}"` 를 돌려주는데 그 문자열에
   내부 URL 과 스택이 실린다 (§3.8). 사유는 분류값으로만 로그에 남긴다.
3. **임시 파일을 만들지 않는다.** 산출물이 메모리 위 바이트라 디스크를 거칠 이유가 없다.
   예제는 `delete=False` 로 만들고 예외 경로에서 지우지 않아 파일이 남는다.

## ④ payload 정리 — F12 에 나와야 할 값만

**내부 판정·검증·진단은 우리가 로그로 갖는다.** 프론트에 실어 보내면 화면이 그 값을
어떻게 쓸지 각자 정하게 되고, 쓰지 않는 값은 아무도 안 읽는 채로 계약에 남는다.

| 기능 | 최종 payload (정상) |
|---|---|
| 글다듬이 | `original_text` · `polished_text` · `download_url` |
| 번역 | `original_text` · `translated_text` · `download_url` |
| FAQ | `faq_items` · `download_url` |

`error` 는 **오류일 때만** 실린다 — 정상 응답에 `error: null` 을 넣지 않는다(있으나
없으나 같은 뜻이라 읽는 쪽이 분기를 두 벌 갖게 된다). FAQ 오류 응답에는 `faq_items` 도
싣지 않는다: 빈 목록을 함께 내면 **"0건 생성" 과 "실패" 가 화면에서 같아 보인다.**

뺀 것은 셋으로 갈린다:

| 갈래 | 무엇 | 어디로 |
|---|---|---|
| 파일이 됐다 | `polished_text`(정본) · `translated_markdown` | 서빙이 굳혀 올린다. 접미어를 뗀 이름은 **사본**이 물려받았다 |
| **disclaimer 로 간다** | `structure_warnings` · `fact_warnings` · `numeric_warnings` · `tone_overridden` · `tone_notice` · 부분 실패 건수 · FAQ 기각/다운로드 불가 안내 | 스텝은 **판정만** 하고 문구를 조립하지 않는다. 전송은 MCP 확정 후 |
| 로그가 갖는다 | `faq_stats` · `glossary` · `translate_stats` · `translate_source_kind` | `event=faq_done`·`translate_done` 의 `status=` |
| 필요 없어졌다 | `text`(018 만) | 전용 UI 가 한 번에 그린다 |

**`{**data}` 를 쓰지 않는다 — 이게 없으면 위 표가 겉모양만 지켜진다.** 마지막 스텝이
`{**data, ...}` 로 result 를 내면 앞 스텝이 넣은 값과 캔버스 입력이 **전부 프론트로
간다.** 실측으로 006 payload 에 21개 키가 실려 있었다(`field_names`·`block_styles`·
`fields_updated`·`question`·`overrideConfig` …). 그래서 마지막 스텝 넷이 payload 뼈대를
새로 만든다(`_base_payload()`):

| 스텝 | 남기는 화면 밖 값 | 근거 |
|---|---|---|
| 018 셋 | `genos_state` | 플랫폼 추적(`trace_id`). 잃으면 로그가 요청 간에 안 이어진다 |
| 006 | `genos_state` · `session_id` · `template_id` | 뒤의 둘은 **다운로드 버튼이 `POST /generate` 를 부를 때** 쓴다 |

`check_workflow_run`·`check_chat_turn` 이 **허용 키 밖의 값이 실리면 FAIL** 한다.
네 스텝을 각각 `{**data}` 로 되돌려 FAIL 을 확인했다.

그 밖에 `changes`(사본을 만드는 **입력**, 운영 소비자 0건)와 `translate_pairs`(좌우
비교가 문서 전체 단위라 유닛을 되짚을 일이 없다)를 뺐다.

- **사본 이름에서 `_highlighted` 를 뗐다.** 그 접미어는 정본과 사본이 둘 다 payload 에
  있던 시절의 구분이다. 정본이 빠진 지금은 한 벌뿐이라, 접미어가 붙은 쪽만 사본처럼
  읽혀 `original_text` 와 어긋난다.
- **토큰 스트리밍을 없앴다.** 화면이 결과를 한 번에 그린다. 가이드 D.1 의 async
  generator 형태는 유지하고(등록 형태를 바꾸지 않는다) `result` 만 1회 낸다.
- **경고 판정은 지우지 않았다.** disclaimer 전송을 붙일 때 다시 만들지 않기 위해서다 —
  지금은 payload 로도 화면으로도 안 나가는 **의도한 공백**이고, 코드에 그렇게 적어 뒀다.
- **04(템플릿 채우기)도 줄였다 — 방향이 반대다.** 처음 근거("턴 상태가 payload 로
  흐른다")는 **틀렸다**(가이드 D.1 의 규칙은 같은 실행 안의 다음 스텝이고, 턴 간 상태는
  Redis 에 있다). 이 기능은 **전용 UI 가 없어 채팅이 곧 화면**이라 `text` 가 필수이고
  스트리밍도 유지한다. 뺀 것은 안내문이 이미 말하는 값이다 — payload 는 `text` ·
  `ready_for_download` · `document_markdown`.
  **다운로드는 `POST /generate` 직접 유지** — 대화 중간에 바로 받는 흐름이라 미리 굳혀
  올릴 시점이 없다.
  `check_chat_turn` 의 값 누적·블록 순서 판정은 **세션을 직접 읽도록** 옮겼다 — 원래
  보려던 것이 화면 표시가 아니라 상태 전이였다.

---

## 그물

| 점검 | 그전 → 지금 | 무엇을 보나 |
|---|---|---|
| `check_mcp_tools` | 75 → **80** | 양쪽 좌표가 각 텍스트의 그 낱말을 가리키는가 · **삭제가 원문 사본에 보이는가** · **한국어 조사 폴백 3갈래 + 과절단 가드** |
| `check_workflow_run` | 80 → **80** | 판정 교체 — 검수값 미노출(세 스텝) · 다운로드 링크 전달 · **원문 사본 전달**(글다듬이·번역) · **FAQ 기각 건수를 로그에서 대조** |
| `check_unit_endpoints` | 66 → **68** | 원문 사본을 함께 내는가 · **업로드 실패가 결과를 버리지 않는가** |
| SFR-018 unittest | 236 → **249** | `test_diff_highlight` +3(양쪽 좌표·양쪽 사본·삭제 가시성) · `test_glossary_policy` +10(원문 사본·미적용은 안 칠함·**낱말만 감싼다**·정본 불변 · **조사 6건**: 방향별 증상·과절단·정확 일치 우선·여러 낱말 용어) |

**FAQ 기각 건수 그물을 로그로 옮겼다.** `faq_stats` 가 payload 에서 빠지면서, "스텝이
응답에 없는 키를 읽어 기각 건수가 영원히 0" 이라는 결함(2026-08-13 실제 발생)을 보던
판정이 갈 곳을 잃는다. 그대로 지웠으면 **그 결함을 보는 점검이 0건**이 된다. 스텝
로거(`faq_generate`)에 핸들러를 붙여 `event=faq_done` 의 `status=` 를 대조한다 —
그때 **로거 레벨을 INFO 로 낮춰야 한다**(스텝은 `configure_logging` 을 부르지 않아
기본 WARNING 이고, 안 낮추면 판정이 조용히 통과한다).

**조사 폴백은 두 방향을 각각 되돌려 FAIL 을 봤다** — ko→en 색인 폴백을 빼면 1건,
en→ko `contains_phrase` 를 되돌리면 2건 실패한다.

**되돌려 FAIL 을 본 갈래 둘** (양쪽 하이라이트):

1. **MCP 원문 사본 제거** → `check_mcp_tools` 75/76 · `check_workflow_run` FAIL 1 (**동시**)
2. **번역 원문 사본을 번역문 쪽 규칙(`target_spans`+`applied_only=True`)으로 되돌림**
   → `test_glossary_policy` 2건 FAIL

**2번은 엔드포인트 점검이 못 잡는다.** 게이트웨이가 없는 점검 환경에서는 번역이 전량
폴백되고, 그러면 사본이 정본과 같아져 `source_markdown_highlighted == source_markdown` 이
어느 쪽이든 성립한다. 그래서 그 그물을 **유닛 테스트로 옮겼다** — 처음에는 엔드포인트에
두었다가 되돌려도 통과하는 것을 보고 옮긴 것이다.

## 남은 미확인

| 항목 | 안 되면 |
|---|---|
| 좌우 비교 뷰가 `text` 를 대체하나 | 같은 내용이 두 번 보일 수 있다. 프론트 확인 후 `text` 를 안내문만 담게 줄이거나 그대로 둔다 |

> CDN 업로드 가용성과 presigned URL 수명은 **추적 대상에서 뺐다**(2026-08-28 결정).
> 업로드는 fail-open 이라 안 되면 `download_url` 이 `None` 이고 결과는 그대로 나간다.
