# CLAUDE.md — genon 저장소 (SFR 기능별 작업 공간)

> 이 저장소에서 코드를 쓰거나 고칠 때의 진입 문서.
> **개발 규칙의 원본은 `genos-project/CLAUDE.md` 와 `genos-project/docs/GENOS_RULES.md` 다** —
> 영역(area)별 시그니처, 오류 코드 체계, HWP/HWPX 도메인 지식, GenOS 런타임 데이터 위치가
> 전부 거기 있다. 먼저 읽고 이 파일로 돌아올 것.
> `genos-project/` 는 CHECKSUMS.txt 로 봉인된 참조 번들이므로 **수정하지 않는다.**

---

## 저장소 구성 (2026-08-11 영역 재배치 반영)

```
onprem/                   # ⭐ 폐쇄망 이관용 프로덕션 코드 — 여기가 현행이다
  workflow/               # area 02 — 캔버스 파이썬 스텝 9개. 파일 1개 = 스텝 1개
  mcp/                    # area 01 — MCP 도구 **파일** 4개 (파일 1개 = 등록 단위)
  codeserving/            # area 03 — HTTP 배포 단위 4개. LLM·프롬프트·Redis·lxml·볼륨
    SFR-006_template_fill/  # HWPX 템플릿 채우기
    SFR-018_text_polish/    # 글다듬이 (재배치로 02 → 03 이 됐다)
    SFR-018_translation/    # 번역
    SFR-018_faq/            # FAQ 생성
  prompt/                 # jinja 프롬프트 (배포 단위 **바깥** — 이미지에 함께 넣을 것)
    <배포 단위 이름>/       # 네 단위 전부. 디렉토리 이름 = 배포 단위 이름
  eval/                   # 평가지표 MCP 서버 — 배포 단위 아님, 네 기능 채점용
  test/                   # 배포 계약 점검 스크립트 — 배포 단위 아님
  docs/                   # 기능별 설계 심화 문서 (SFR-006 아키텍처 등)
  ARCHITECTURE_SPLIT.md   # 이 재배치의 설계·근거
  README.md               # 배포 단위·환경변수·로깅 규약 + **이관 순서** (먼저 읽을 것)

data/                     # 요구사항 문서 (커밋 대상 — FAQ_rule.md, translation_rule.md)

SFR-006/                  # ⭐ **테스트 전용** (2026-08-11 개편 — 구현 사본 없음)
  tests/                  # onprem 을 직접 import 한다. onprem_path.py 가 경로를 아는 유일한 자리
  hwpx.py                 # 레거시 {{token}} 로컬 검증 CLI (onprem 에 대응물 없어 남겨 둠)

SFR-018/                  # ⭐ **테스트 전용** (2026-08-11 개편)
  tests/                  # 번역 코드서빙 + MCP genon_text_guard 를 직접 태운다
  genos-glossary/         # 용어집 실험 스냅샷. **2단계 glossary.py 의 유일한 사본**이라 남겼다

genos-project/            # 📖 읽기 전용 규칙/참조 번들 (개발가이드 PDF, 원본 소스 스냅샷)
genos_files/              # 개발가이드 PDF + hwpx_report.py PoC 사본
archive/                  # zip 백업 (건드리지 않음)
```

**`onprem/` 이 유일한 구현이다** (2026-08-11 개편 완료). 우선순위는
**`onprem/` > `genos-project/source/`**:
- `onprem/` 이 폐쇄망에 올라가는 **현행 코드**다. 기능 수정은 여기서 한다.
- `SFR-006/`, `SFR-018/` 에는 **테스트만** 있다. 그 테스트는 `onprem/` 을 직접 import
  하므로 드리프트가 생길 수 없다. 회귀 테스트를 붙일 때만 여기를 고친다.
- `genos-project/source/` 는 **과거 스냅샷**이다. 참조만 하고 수정하지 않는다.

### 저장소 구조 개편 — **실행 완료 (2026-08-11)**

방향은 2026-08-07 에 정했고 이제 실행했다. `onprem/` 이 유일한 구현이고,
`SFR-006/`·`SFR-018/` 은 테스트만 남는다. 테스트는 `onprem_path.py` 한 곳에서 경로를
세우고 **onprem 모듈을 직접 import 한다.**

**왜 했나 — 사본은 이미 갈려 있었다.** "어긋난 부분은 onprem 을 정답으로 본다" 는
드리프트를 전제한 규칙이었는데, 그 드리프트가 회귀 테스트를 무력화하고 있었다:

| 사본에만 있던 것 | 실제 |
|---|---|
| `field_judge.mock_extract` | onprem 에 없다 — **운영에 없는 코드를 지키는 테스트였다** |
| `hwpx_fields.scan_tokens` | 슬롯 문법 전환으로 없어졌다 |
| `parse_updates -> (dict, list)` | 지금은 `ParsedIntent` (수정·삭제·본문 추가가 한 응답에 섞여 온다) |
| 파일 세션(`Config.SESSION_DIR`) | Redis 로 옮겼다 |
| `run_chat.run` | 워크플로우 스텝 3개 + `chat_api` 로 갈렸다 |
| `translator_mode="mock"` | onprem 에 그 인자가 없다 (배포 단위에 mock 경로 금지) |

**옮기며 한 것**:
- 006: `test_field_judge`(ParsedIntent 로), `test_hwpx_fields`(+ **슬롯 모드 테스트 신규** —
  기본 방식인데 사본에 파서가 없어 회귀 테스트가 없던 공백), `test_session_store`
  (가짜 Redis. `test_run_chat` 을 대체한다 — 그쪽이 검증하던 셋이 전부 사라졌다).
- 018: `test_markdown_guard`(→ MCP 파일을 태운다), `test_markdown_units`
  (모드 인자 대신 **번역 경계 `pipeline._run` 에 대역**을 꽂는다. 주입은 배포 단위
  **바깥**에서만 하므로 운영 코드에 테스트용 분기가 생기지 않는다).
- **28건 + 22건.** 이관 전 43건보다 늘었다.

**지운 것**: 구현 사본 전부(`SFR-006/template_fill/`, `SFR-018/text_polish/`,
`SFR-018/translation_refactored/`)와 `SFR-006/smoke/` 6개. 스모크는 재배치 이후
**전부 `ModuleNotFoundError` 로 죽어 있었고**(경로가 옛 `onprem/SFR-006_template_fill`),
살려도 옛 설계(라벨 방식·`run_chat`·`collect_style_specs`)를 전제해 통과하지 못한다.
각각의 자리는 `onprem/test/` 가 이미 덮고 있다 — 대응표는 `SFR-006/README.md`.

**남긴 것**: `SFR-006/hwpx.py`(레거시 CLI, onprem 에 대응물 없음),
`SFR-018/genos-glossary/`(2단계 `glossary.py` 의 **유일한 사본** — 폐쇄망 벡터DB 보류분).

되살릴 일이 생기면 `git show HEAD:SFR-006/template_fill/field_judge.py` 처럼 꺼낸다.

### hwpx 표 — 병합·중첩은 HTML 로 낸다 (2026-08-11)

**마크다운 표에는 병합 문법이 없다.** 그래서 `rowSpan`/`colSpan` 이 빈 칸이 되고 중첩 표는
한 덩어리 텍스트로 뭉개졌다. 재현한 실제 출력:

```
| 구분 | 2025년 실적 |   | 비고 |   ← colSpan 사라짐 → 3열이 빈칸
|   | 상반기 | 하반기 | - |        ← rowSpan 사라짐 → 1열이 빈칸
| 세부 | 소분류<br>값 |   |   |     ← 중첩표가 텍스트로 뭉개짐
```

**수치는 남는데 그 수치가 무엇의 값인지가 사라진다.** 요구사항 §5 의 "표 깨짐" 이 이것이고,
렌더러 버그가 아니라 **형식의 한계**라 마크다운으로는 못 고친다.

- **손실이 있을 때만 HTML.** 병합·중첩이 있으면 `<table><tbody><tr><td rowspan="2">…`,
  없으면 마크다운 그대로. 잃을 게 없는 표까지 바꾸면 토큰만 늘고 읽기 나빠진다.
- **새 형식이 아니다.** 지능형 전처리기가 이미 한 줄 HTML 표를 내고, 번역 스켈레톤
  분해기(`markdown_units`)에 그 경로(`_HTML_TABLE_REGION_RE`·`_split_html_table`)가
  이미 있다. 즉 **이미 지원하는 형식**으로 내는 것이라 하위 경로를 안 건드렸다.
- **적용 범위는 LLM 입력 경로 셋**: MCP `genon_hwpx_text.py`(정본) · 번역
  `office/hwpx_text.py` · FAQ `faq/hwpx_text.py`. **006 `hwpx_markdown.py` 는 제외** —
  그쪽 출력은 채팅 화면 미리보기용이라 마크다운이 맞다.
- **원인은 `tc.iter(hp:p)`** 였다. 셀 텍스트를 뽑을 때 중첩 표 안 문단까지 딸려왔다.
  `_owning_cell` 로 소유 셀을 따져 자기 것만 고른다.
- **덮인 자리에 `<td>` 를 내지 않는다.** 내면 그 행만 열이 하나 늘어난다.

**검증**: 무손실 왕복(항등 번역 시 문자 단위 동일)·태그열 불변·숫자 셀이 번역 단위가
되지 않음·엔티티 왕복을 `SFR-018/tests/test_hwpx_tables.py`(10건)가 지킨다.
`check_table_grid.py` 는 **두 층**이 됐다 — 단순표 4벌 대조, 병합표 3벌 대조.

### MCP 를 서빙이 아니라 **파일**로 다시 만들었다 (2026-08-11 정정)

재배치할 때 MCP 를 **코드서빙처럼 만들었다** — 디렉토리마다 FastAPI 앱, `/health`,
`$PORT`, `requirements.txt`, 손으로 구현한 `/mcp` JSON-RPC 라우트. **전부 틀렸다.**

GenOS MCP 등록은 **소스 파일 한 개**를 받아 실행하고 `mcp` 객체를 런타임이 전역으로
주입한다. 도구는 `@mcp.tool()` 로 등록하고 **JSON 문자열**을 돌려주며, 엔벨로프는
런타임이 씌운다. 앱도 포트도 우리 몫이 아니다.

- **디렉토리 4개 → 파일 4개.** `mcp/genon_{text_guard,lang_policy,glossary,hwpx_text}.py`.
- **모든 최상위 심볼에 파일별 접두어**(`TG`/`LP`/`GL`/`HX`). 한 서버에 여러 도구 파일이
  함께 로드될 수 있고, 겹치면 나중 것이 앞엣것을 덮는다 — 그 실패는 "도구가 이상한 값을
  낸다" 로만 드러난다. **도구 함수 이름만 예외**(LLM 에 노출되는 계약이라 못 붙인다).
- **`""` 주입 대비.** GenOS 는 값이 없을 때 `None` 이 아니라 빈 문자열을 준다. 선택
  인자를 `int`/`float` 로만 선언하면 **본문에 닿기 전에 타입 검증에서 죽는다.**
- **`mcp` 미주입 대비 shim** 이 없으면 로컬에서 파일을 열어 볼 수조차 없다.
- **`requirements.txt` 가 없으므로** 비표준 패키지는 파일 안에서 설치한다
  (`genon_hwpx_text.py` 의 `lxml` 하나).
- **기동 훅이 없다.** 용어사전 적재는 첫 도구 호출로 미뤘다 — import 가 느리면 서빙이
  왜 안 뜨는지 드러나지 않지만, 첫 호출로 미루면 그 지연이 그 호출의 지연으로 보인다.

**합치면서 밟은 함정 셋** (같은 작업을 다시 할 사람이 같은 자리에서 또 헛걸음하지 않게):

1. **정규식으로 이름을 바꾸면 문자열 리터럴까지 바뀐다.** `resolve_tone` 이 함수 이름이자
   도구 이름 문자열이라 `_HANDLERS` 의 키가 바뀌었고, 그 도구가 통째로 `UNKNOWN_TOOL`
   이 됐다. → 토큰 단위로 바꾸고 문자열은 건드리지 않는다.
2. **별칭 import 를 놓치면 호출부만 옛 이름으로 남는다.**
   `from .languages import supported_payload as supported_languages` — 정의부는 접두어가
   붙는데 호출부는 그대로라 `NameError`. **import 는 통과하므로 도구를 실제로 불러야**
   드러난다.
3. **다른 파일이 같은 이름을 정의하면 뒤엣것이 앞엣것을 덮는다.** `languages.py` 와
   `registers.py` 가 둘 다 `supported_payload` 를 가져서, 합친 뒤 `list_languages` 가
   **문체 목록**을 돌려줬다.

**그물**: `check_mcp_tools.py`(36건)가 네 파일을 **한 네임스페이스에 넣어** 덮이는지
보고, 도구를 직접 불러 결정적 판정과 빈 문자열 주입을 확인한다.
`check_deploy_contract.check_mcp_files()` 가 접두어·`async … -> str`·shim·상대 import
금지·부팅 설치 절차를 정적으로 본다. 상세는 `onprem/mcp/README.md`.

**덤으로 찾은 기존 버그 하나**: `resolve_register` 가 `getattr(code, "code", str(code))`
로 값을 꺼냈는데 `Register` 의 필드는 `key` 다. 항상 `str(code)` 로 떨어져 **파이썬 repr
이 응답에 통째로 실렸고**(영문 지시문 포함), `fell_back`(기본값으로 떨어졌다는 사실)은
계산해 놓고 버렸다. 둘 다 고쳤다 — 후자가 없으면 사용자가 고른 문체가 조용히 무시된다.

### 영역 재배치 (2026-08-11) — **실행 완료**

위 절과 **다른 건이다.** 저 개편은 `onprem/` ↔ 테스트 사본 관계에 대한 것이고(여전히
미착수), 이건 `onprem/` **안**을 영역(area)별로 가른 것이다. 정본은
`onprem/ARCHITECTURE_SPLIT.md`.

- **왜**: 워크플로우 노드(`run_chat.py` ×2, `text_polish/main.py`)가 게이트웨이를 부르지
  않고 같은 패키지를 로컬 import 해 `lxml`·`redis`·`jinja2` 를 끌어쓰고 있었다.
  **GENOS_RULES §D.3 위반**이고, 그 셋이 기본 이미지 변경 요청(11.5.6)에 묶여 **배포를
  막고 있었다.** 미관 문제가 아니었다.
- **결과**: `workflow/`(스텝 9) · `mcp/`(서빙 4) · `codeserving/`(단위 4).
  **워크플로우 이미지에 추가되는 패키지가 0개**가 됐다 — 스텝이 쓰는 외부 패키지는
  `httpx` 뿐이다. 글다듬이는 02 → **03** 이 됐다.
- **스트리밍은 걸림돌이 아니었다.** 옮기기 전에도 실시간 토큰 스트리밍이 아니라 LLM
  응답을 다 받은 뒤 32자씩 잘라 emit 했다. 그래서 LLM 호출을 코드서빙으로 내려도 UI
  동작이 같다.
- **옮기며 드러난 결함 둘** (둘 다 조용히 죽는 종류라 기록해 둔다):
  1. 네 `prompt_loader.py` 가 **고정 깊이**로 프롬프트 디렉토리를 찾고 있어 단위가 한 겹
     내려가자 **네 단위의 프롬프트가 동시에 사라졌다.** 상위 탐색으로 바꿨다.
  2. 톤 LLM 실패 사실(`llm_error_type`)이 `chat_api` ↔ 스텝 3 경계에서 유실돼 답변
     조립이 죽었다. `tone_llm_error_fields`/`_blocks` 를 계약에 넣었다.
- **점검**: 경로 하드코딩 6개를 고쳤고, `check_deploy_contract.py` 에
  **`check_workflow_steps()`** 를 넣었다(스텝의 `run` 시그니처·허용 패키지·자기완결).
  세 번째가 없으면 공용 모듈로 빼려는 시도가 조용히 통과한다 — 그러면 캔버스에 못 붙인다.

---

## SFR-006 모듈 배치 (2026-08-06 리팩토링)

**설계·흐름의 정본은 `onprem/docs/SFR-006_architecture.md` 다.** 여기는 어느 파일을
고쳐야 하는지 찾는 지도다. 계층이 셋이고, 위층은 아래층을 알지만 아래는 위를 모른다.

```
진입   run_chat.py(02 대화) · main.py(03 HTTP 라우팅만)
조립   chat_state.py  한 턴의 상태 전이       session_view.py  세션+색인→화면 payload
       chat_reply.py  채팅 답변 문구          document.py      ★채우기→서식→블록
       template_store.py 템플릿 볼륨 I/O      api_errors.py    ApiError→HTTP
도메인 hwpx_fields.py(hwpx 판정의 정본) · hwpx_style.py · hwpx_blocks.py
       hwpx_markdown.py · field_judge.py · value_guard.py · tone_apply.py
인프라 session_store.py · template_index.py · redis_client.py · llm.py · pdf_convert.py
```

지켜야 할 경계:
- **`hwpx_fields.py` 가 hwpx 판정의 정본이다.** `section_order`(무엇이 본문인가)·
  `own_nodes`(문단이 직접 가진 텍스트)·`slot_occurrences`(중괄호 슬롯인가)를 다른
  모듈이 다시 구현하지 않는다. 두 벌이 되면 채우는 자리와 서식 거는 자리가 어긋난다.
- **도메인 계층은 `Config` 를 읽지 않는다.** 배포 스위치는 `document.py` 가 한 번만 읽는다.
- **조립 순서는 `document.build` 한 곳에만 있다.** 예전엔 코드서빙·미리보기·점검 스크립트가
  각자 적고 있었고, 점검이 자기가 검증할 순서를 스스로 복제해 무의미했다.
- **오류는 `ApiError` 예외 하나로 올린다.** `(값, 오류응답)` 튜플 반환은 폐기했다 —
  `if error: return` 을 한 번 빠뜨리면 조용히 엉뚱한 곳에서 터졌다.
- **영역코드를 섞지 않는다.** 대화가 `template_store`(03 코드)를 쓸 때
  `chat_state.load_context` 가 02 코드로 바꿔 던진다.

## SFR-006 설계 결정 (요약 — 상세는 onprem/docs/SFR-006_architecture.md)

- **슬롯 기반이 기본이다** (2026-08-06 변경 — 그 전에는 콜론 앞을 항목명으로 추측하는
  라벨 항목 방식이었다). 현장 템플릿은 누름틀이 아니라 본문에 그냥 텍스트로 적혀 있고,
  **채울 자리는 중괄호 안뿐이다.**

  ```
  제 목 : {'제목', 16pt, 맑은 고딕, 볼드}   →   제 목 : hwpx 만들기 문서
  작성자 : {'작성자'}                        →   작성자 : 왕주영
  ```

  - **첫 인자는 따옴표 필수**이고, 그 문자열이 곧 항목명이자 "여기에 무엇을 쓰라"는
    LLM 안내문이다. 뒤 인자(0~3개)는 크기·글꼴·굵게이며 **순서·개수가 자유롭다** —
    토큰을 생김새로 판정한다(`16pt`=크기, `볼드`=굵게, 남은 것이 글꼴). 위치를 고정하면
    가운데를 건너뛸 때 `{'제목', , 고딕}` 처럼 빈 자리를 남겨야 한다.
  - **지정하지 않은 인자는 건드리지 않는다.** `{'작성자'}` 는 그 자리 run 의
    `charPrIDRef` 를 그대로 물려받는다 — 서식을 지어내지 않는 것이 원칙이다.
  - **중괄호 밖은 무조건 원문 그대로 남는다.** 라벨 방식은 `항목명: 값` 으로 줄을
    재조립하느라 `제 목  : ` 의 줄맞춤 공백을 잃었고 `prefix` 를 따로 보존해야 했다.
    자리를 중괄호로 명시하니 그 문제가 아예 생기지 않는다.
  - 한 문단에 여러 개가 올 수 있다 (`담당자 : {'소속'} {'성명'}`). 라벨 방식의
    "문단당 1개" 제약이 없다.
  - 한/글 자동 고침이 `'제목'` 을 `‘제목’` 으로 바꿔 저장하므로 **굽은 따옴표도 받는다.**
    한쪽만 바뀐 문서(`‘제목'`)도 열어 준다 — 관리자가 눈으로 구분할 수 없는 차이로
    항목이 통째로 사라지는 편이 훨씬 나쁘다.
  - 표(hp:tbl)는 hp:p 안에 hp:p 가 중첩되므로 **문단 소유 텍스트 노드만** 모아
    판정한다. `para.iter()` 를 그대로 쓰면 표 전체가 한 줄로 붙어 깨진다.
  - `TEMPLATE_FILL_SLOT_FIELDS=0` 으로 끌 수 있다 (옛 이름 `..._LABEL_FIELDS` 도 읽는다 —
    라벨 방식을 쓰던 배포가 꺼 뒀다면 이름이 바뀌었다는 이유로 켜져서는 안 된다).
- **누름틀(CLICK_HERE)은 폴백으로 유지**한다. 관리자가 한/글에서 필드를 심은 템플릿을
  올려도 그대로 동작한다. 필드 식별은 `fieldBegin` 의 `name`, 안내문은 첫 `stringParam`.
  begin/end 짝은 **문서 순서 스택 매칭** (문단/필드 id 는 신뢰 불가 — 규칙 문서 §3.2).
  `{{token}}` 은 프로토타입 호환용.
- **채워짐 판정은 코드가 결정적으로** 한다: 슬롯은 **언제나 미입력**이다 — 채우고 나면
  `{…}` 자체가 사라지므로, 문서에 남아 있다는 것이 곧 아직 안 채웠다는 뜻이다.
  누름틀은 begin~end 텍스트가 비어 있지 않고 안내문과 다르면 채워진 것.
  LLM 의 역할은 사용자 발화 → `{항목명: 값}` 추출까지.
- **서식은 LLM 없이 코드가 적용한다**: `charPr` 을 복제해 `height`(1pt=100)·폰트·굵게만
  바꾸고 그 id 를 **슬롯 run** 의 `charPrIDRef` 에 건다 (`STYLE_SCOPE` 기본 `slot`).
  문단 전체에 걸면 중괄호 밖 라벨까지 같이 커지고, 한 문단에 슬롯이 둘이면 뒤엣것이
  앞엣것을 덮는다. 같은 서식은 `charPr` 을 재사용하고, `itemCnt`/`fontCnt` 는 반드시
  다시 센다 (틀리면 한/글이 문서를 못 연다).
- **따옴표 없는 `{…}` 는 채울 자리가 아니다** (2026-08-05, 실 템플릿에서 확인).
  현장 템플릿에는 `담당자 : {소속} {성명}`, `배포일 : {YYYY.MM.DD. (요일)}` 처럼
  **값 안내**가 들어 있다. 원문 그대로 두고 등록 시 경고로만 노출한다 — 지우면 값 안내가
  조용히 사라지고, 등록을 거부하면 본문에 중괄호를 쓴 정상 문서를 막는다.
  따옴표 경계가 생겨 **슬롯에서는 "글꼴 어휘로 근거를 따지는" 휴리스틱이 불필요해졌다.**
  그 판정(`require_evidence`)은 경계가 없는 **누름틀 안내문 경로에만** 남아 있다.
  다만 자리 표시어(`글씨크기`·`폰트`·`볼드여부`)는 슬롯에서도 삼킨다 — 문법 설명을
  그대로 복사해 붙인 템플릿에서 '폰트' 라는 없는 글꼴을 거는 일을 막는다.
- **lxml 프록시 id 는 붙들어야 유효하다**: `{id(elem): 위치}` 맵을 만들 때 순회 결과를
  리스트로 살려두지 않으면 프록시가 회수되며 id 가 재사용돼 엉뚱한 노드를 가리킨다
  (항목 순서가 뒤섞이는 버그로 실제 드러났다).
- **본문 블록 — 템플릿 항목을 다 채운 뒤 내용을 더 이어 쓰는 경로** (`hwpx_blocks.py`,
  2026-08-06 추가). 항목은 개수가 고정이라 다 채우면 더 쓸 자리가 없었다.
  - **서식 명세를 다시 해석하지 않고 템플릿 문단을 통째로 `deepcopy` 한다.** 명세를 파싱해
    문단을 조립하면 charPr 만 재현되고 **paraPr(여백·줄간격·정렬)은 재현되지 않는다** —
    이 패키지엔 paraPr 을 만드는 코드가 없다. 복제하면 둘 다 따라오고 **새 서식 정의가
    0개**라 header.xml 을 건드리지 않는다 (= 이 경로는 문서를 깨뜨릴 수 없다).
  - 복제 시 **`hp:t` 만 남기는 화이트리스트**로 secPr·ctrl·tbl·그림을 버린다. 현장 템플릿은
    **첫 문단이 secPr 과 `제 목 :` 라벨을 함께 담고 있어** 이 방어가 실제로 필요하다.
    블랙리스트로 하면 모르는 제어 요소에서 뚫린다.
  - 서식 원본(`style_ref`)은 **최상위 문단만**. 표 셀 안 슬롯은 제외한다(셀 폭 기준 서식이
    본문에 나온다). 표 안 슬롯은 **채울 항목으로는 그대로 인식**된다 — LLM 이 표도 채운다.
  - 이름을 못 찾으면 **내용을 버리지 않고** 기본 서식으로 넣고 사유를 남긴다. 기본 서식은
    빈 문단을 쓰지 않는다 — 현장 템플릿의 빈 줄은 `여백: (5pt)` 같은 간격용이다.
  - 순서는 **서식 적용 → 채우기 → 블록** (`document.build` 한 곳에만 있다). 슬롯 방식이
    되면서 앞의 둘이 뒤집혔다 — 채우면 `{…}` 가 사라져 어디에 무슨 서식을 걸지 알 수
    없기 때문이다. 라벨 방식일 때는 `제 목 :` 이 문서에 남아 이름으로 다시 찾을 수 있었다.
  - 검증 규율이 값과 다르다: **내용에는 화이트리스트가 없고**(그게 기능이다) 개수·길이
    상한만, **서식 이름에만** 화이트리스트. 대화는 `blocks`/`block_clears`, 화면은
    `PUT /blocks`(배열 통째 교체 — 인덱스 어긋남으로 엉뚱한 문단을 지우지 않게).
  - **세션 저장은 덮어쓰기라** 값만 저장하면 블록이 지워진다 → `_save_edited_values` 가
    항상 블록을 함께 넘긴다.
  - `FieldSpec`/색인 구조가 바뀌어 `SCHEMA_VERSION` 4(슬롯 문법 전환으로 한 번 더 올렸다 —
    항목 목록 자체가 달라진다), 세션 `_STATE_VERSION` 2 (옛 세션은
    버리지 않고 기본값으로 흡수한다 — 버리면 배포 시점 진행 중인 대화가 초기화된다).
- **글다듬이(톤)는 006 안에서 한다** (2026-08-06 결정). 018 `text_polish` 는 **HTTP 진입점이
  없는 워크플로우(02) 노드**라 호출할 대상이 아니고 배포 단위 간 import 도 금지다.
  - 018 과 **입력 단위가 다르다**: 018 은 문서 전체 마크다운 + `markdown_guard`,
    006 은 항목 값·본문 블록 **조각** + `value_guard`. 006 에서 조각이 맞는 이유는
    완성된 hwpx 를 통째로 다듬으면 결과를 **다시 문단에 써넣어야** 하고 대응이 어긋나면
    문서가 엉키기 때문이다. 조각은 어느 문단인지 이미 안다.
  - **톤 프리셋 사본이 셋**(018 원본 / 006 / eval)이고 실제로 갈려 있었다 —
    006 `friendly` 에서 한 문장 누락. **`onprem/test/check_tone_policy.py` 가 대조**한다.
    톤 문구는 **018 을 고치고** 이 스크립트를 돌린다.
  - **문서유형 정책은 006 에 가져오지 않는다** — 018 은 사용자가 글 종류를 고르지만
    006 은 템플릿이 문서 종류를 정한다. 필요해지면 템플릿 등록 시 지정하는 쪽이 맞다.
  - 본문 블록도 같은 톤을 탄다(`apply_tone_to_blocks`, 이름표 `본문 N`). 항목 값과 **호출을
    나눈다** — 이름표 충돌 방지 + "이번 턴 신규만" 규칙을 두 목록에서 각각 지키기 위해.
    원문은 블록 안 `raw_text` 에 둔다(목록이라 별도 dict 면 인덱스가 어긋난다).
  - `is_narrative` 는 종결어미를 볼 때 **문장부호를 뗀다**. 안 그러면 `…달성하였습니다.`
    처럼 마침표로 끝나는 짧은 문장이 조용히 톤 대상에서 빠진다 (2026-08-06 수정).
- 멀티턴 상태는 **Redis 세션 저장소** (`session_store.py`) — GenOS 는 이전 대화를
  자동 주입하지 않는다. 워크플로우 pod ↔ 코드 서빙 pod 가 같은 `REDIS_URL` 을 보면 되고
  세션 전용 공유 볼륨은 필요 없다(템플릿 파일 볼륨은 여전히 공유해야 한다).
  Redis 클라이언트는 `redis_client.py` 하나를 공유한다 — 모듈마다 `from_url` 을 부르면
  연결 풀이 그만큼 늘어난다.
- **템플릿 파싱은 `template_index.py` 캐시를 경유한다** (등록 시점 1회 파싱).
  무효화는 캐시 값 대조로 한다 — 내용 해시·`SCHEMA_VERSION`·`SLOT_FIELDS`.
  **슬롯 인식 규칙이나 `FieldSpec` 을 고치면 `SCHEMA_VERSION` 을 올려야 한다.**
  Redis 장애 시엔 직접 파싱으로 degrade 한다 (캐시는 성능 장치일 뿐이다).
- **미리보기(`hwpx_markdown.py`, `GET /preview`)는 다운로드와 같은 채우기 경로**를 탄다.
  별도 렌더러를 두면 화면과 파일이 어긋난다. 표는 `cellAddr` 좌표로 격자를 만든다
  (병합 셀은 앵커만 존재 — 순서대로 채우면 열이 밀린다).
- **PDF 는 전처리기 변환기를 호출만 한다** (`pdf_convert.py`,
  `genon.preprocessor.converters.hwp_to_pdf`). 전처리기 코드는 수정하지 않고,
  **모의 변환 경로도 두지 않는다** (`onprem/` 규칙 — 가짜 PDF 를 만들 수 있게 열어 두면
  운영에 흘러간다). 그 패키지는 이 저장소에 없다 — **코드서빙 이미지에 포함돼야 동작한다.**
  변환기는 실패해도 `None` 을 돌려주므로 오류로 승격하고, "수단 없음"(501)과
  "변환 실패"(500)를 구분한다. 변환 실패 시 세션을 종료하지 않는다.
  검증은 전처리기 **경계에 스텁 모듈을 주입**해 호출 규약(`order`·hwpx 전달·출력 검증)을
  확인한다 — 운영 코드에 테스트용 분기를 만들지 않는다.
- 대화(area 02, `run_chat.py`)와 파일 생성(area 03, `main.py` `/generate`)은
  별개 영역이다. 다운로드 버튼은 코드 서빙을 호출한다.
- 관리자 등록(`POST /templates`)은 **파싱을 먼저, 파일 쓰기를 나중에** 한다 —
  순서를 바꾸면 해석 불가 파일이 볼륨에 남는다. `TEMPLATE_FILL_ADMIN_TOKEN` 미설정 시
  등록·삭제가 인증 없이 열리며, 그 사실을 기동 로그 경고로 노출한다.

## SFR-018 번역 고도화 (2026-08-07 — 요구사항 `data/translation_rule.md`)

상세는 `onprem/README.md` 의 `SFR-018_translation` 절. 결정만 여기 남긴다.

- **지원 언어 6개 + 한국어 축 제약.** `en→ru` 같은 비한국어 쌍은 400 이다 (요구사항 §6).
  방향 검증은 **거부 판정**이라 LLM 에 맡기지 않고 스크립트 기반으로 결정적으로 감지한다
  (`languages.py`). 감지 불가(숫자·기호뿐)는 거부하지 않고 방향 검증만 건너뛴다.
- **용어사전은 1단계(`glossary_exact.py`)만 병합했다** — 보류 결정 그대로다.
  **2단계 폴백이 없으므로** 사전이 없거나 상한을 넘으면 그 언어는 용어사전 없이
  번역되고 그 사실을 응답 `glossary.source` 로 노출한다. 원본 실험의 주석은
  "1단계가 꺼지면 2단계가 받는다"였는데 여기선 사실이 아니라 고쳐 적었다.
- **준수율을 코드가 다시 센다.** 프롬프트 지시로 끝내지 않는다 —
  `glossary_report.build_report` 가 번역 후 대조해 `compliance` 와 하이라이트 데이터
  (`term_map` = `{"원문":"번역"}`, `hits`)를 낸다. eval 의 `glossary_compliance` 가
  드디어 측정 가능해졌다(운영 기능 부재가 지표에 안 드러나던 공백이 메워졌다).
- **숫자 보존 검사 추가** (`numeric_guard.py`). 006 엔 `value_guard`, 글다듬이엔
  `markdown_guard` 가 있는데 번역만 코드 검증이 없었다. 자릿수 구분 기호를 제거하고
  비교하므로 `1,000` ↔ `1.000` 은 오탐이 아니다. 기본은 경고(`warn`), `revert` 도 있다.
- **표 셀 파이프 이스케이프** — 번역문에 `|` 가 섞이면 그 행부터 열이 밀렸다.
  분해 때는 파이프가 곧 셀 경계라 보장이 있었지만 번역문에는 없다. 무손실 계약은
  유지된다(원문 셀에 파이프가 없으므로 항등 번역이면 이스케이프할 대상이 없다).
- **같은 원문은 한 번만 호출한다.** 호출 수가 줄 뿐 아니라 반복 머리글이 자리마다
  다르게 번역되는 흔들림도 사라진다.
- **`stats.fallback_rate` 를 응답에 싣는다** — 루트 README 의 fallback 발생률 지표에
  분모·분자가 없어 계산이 불가능했다.
- **hwpx 는 직접 파싱**한다(`hwpx_text.py`, `POST /translate/hwpx`). 전처리기를 태우면
  표 안 수치가 깨진다(요구사항 §5). 산출 마크다운은 `/translate/markdown` 과 **같은**
  스켈레톤 분해를 탄다 — 전용 경로를 두면 구조 보존 계약이 두 벌이 된다.
- **문서 출력은 하지 않는다**(요구사항 §3). 원본은 `source_markdown` 으로 함께 낸다.
- `style_options` 는 받아만 두고 파이프라인에 안 넘기던 죽은 파라미터였다 →
  실제 의미가 있는 `register`(문어체/구어체)로 대체했다.

## SFR-018 FAQ (2026-08-07 신규 — 요구사항 `data/FAQ_rule.md`)

상세는 `onprem/README.md` 의 `SFR-018_faq` 절. 초안은 `archive/FAQ.py`.

- **근거 검증이 이 기능의 핵심 계약이다.** LLM 이 준 `evidence` 가 실제로 문서에 있는지
  `evidence.py` 가 결정적으로 대조하고, 통과 못하면 기각한다. 검증 없이 표시만 하면
  근거란이 장식이 되고 지어낸 답변에 그럴듯한 출처가 붙어 더 위험해진다.
  루트 README 018 지표 4절의 1차 스크리닝과 **같은 판정**이다.
- **기각 건수를 전부 노출한다**(schema/ungrounded/duplicate). 조용히 버리면 왜 5개
  요청에 3개만 나왔는지 알 수 없다.
- **개수 상한은 두 층이다**: 배포 상한(`FAQ_MAX_COUNT`) 안에서만 캔버스 변수
  (`faq_max_count`)로 낮출 수 있다. 캔버스가 상한을 넘길 수 있으면 LLM 예산 상한이
  설정 하나로 무력해진다.
- **hwpx 다운로드는 템플릿 기반이다.** 백지에서 hwpx 를 조립하면 `header.xml` 의
  `charPr`/`itemCnt` 한 글자 차이로 한/글이 문서를 못 여는데, 확인할 한/글이 없다.
  관리자 템플릿의 반복 블록(`{{question}}`/`{{answer}}`/`{{evidence}}`)을 복제한다.
  템플릿 미등록 시 **501**(가짜 문서를 만들지 않는다 — 006 PDF 규약과 같다).
- **다운로드는 저장된 것을 내려준다. 다시 생성하지 않는다** — LLM 을 다시 부르면
  화면에서 본 FAQ 와 파일이 달라진다. Redis 세션이고, 다운로드가 세션을 지우지 않는다
  (형식만 바꿔 여러 번 받는 흐름이 정상이라 006 과 다르다).
- xlsx·pdf 내보내기는 태그 `archive/sfr018-export` 의 코드를 가져왔다. 그 브랜치는
  FAQ 호출부가 없어 계약만 준비돼 있었다(HANDOFF §3). hwpx 되쓰기(`hwpx_rewrite.py`)는
  **원본 문서를 되쓰는** 코어라 FAQ 에는 해당 없어 가져오지 않았다.

## 공통 코딩 컨벤션 (규칙 문서 §5 + 이 저장소에서 정착된 것)

- LLM 호출 결과는 **`LlmResult`(content, error_type, is_transport_error) 값 객체**로
  반환한다. 전역 오류 상태 금지 (asyncio 레이스). 통신/실행 실패는 예외 타입으로 분류.
- LLM 응답은 화이트리스트/스키마 검증 후 정상 항목만 채택하고,
  기각 건수를 로그·응답으로 노출한다 (침묵 처리 금지).
- `mock`/`noop` 모드를 항상 유지 — 폐쇄망에서 LLM 없이 구조 검증.
- 오류 문자열 하드코딩 금지 → 각 패키지 `error_codes.py` 상수만.
- 사용자 노출 예외(TemplateError, TranslationRequestError 등)의 메시지는
  해당 파일 안에서 작성한 **고정 한국어 안내문만** 담는다.
- **LLM 호출 URL 은 `llm.py` 의 `_base_url()`(006 은 `_chat_url()`) 한 곳에서만 만든다.**
  `/api/gateway` prefix 를 코드가 붙이고, `GENOS_URL` 이 이미 그걸로 끝나면 중복시키지
  않는다. f-string 으로 base_url 을 직접 조립하면 prefix 를 빠뜨린다 (실제로 018 두 단위가
  그래서 게이트웨이를 지나지 않고 있었다 — 2026-08-05 수정).
- **프롬프트는 배포 단위 밖 jinja 파일로 관리한다** — **네 단위 전부 이관 완료**
  (2026-08-07). 디렉토리 이름은 배포 단위 이름과 같다:
  `onprem/prompt/{SFR-006_template_fill, SFR-018_text_polish, SFR-018_translation,
  SFR-018_faq}/`. 각 단위의 `prompt_loader.py` 가 `StrictUndefined` 로 렌더하고,
  템플릿이 없으면 **빈 프롬프트로 넘어가지 않고 요청을 세운다** — 지시문 없는 프롬프트로
  LLM 을 돌리면 그 결과가 정상 응답처럼 내려간다. 렌더 실패는 LLM 실패와 **따로**
  로그를 남긴다(`event=prompt_render_failed`) — 전자는 이미지에 디렉토리를 안 넣은
  배포 실수라 구분돼야 손을 쓸 수 있다. 예외는 006 톤 변환 하나로, 거기서는 문서
  생성을 막지 않고 원본 값을 유지한다(톤은 부가 기능이다).
- **프롬프트 지시문 언어는 나눠 쓴다.** 기준은 그 문장이 통제하는 대상이다 —
  **구조·형식·금지 조항은 영어**(JSON 스키마, 코드펜스 금지, 날조 금지),
  **산출물의 언어·어투·표기 규칙은 한국어**(존댓말, 개조식, `2026. 8. 3.` 표기).
  번역 단위만 **전부 영어**다 — 대상 언어가 요청마다 바뀌어서 지시문 언어가 섞이면
  모델이 출력 언어를 헷갈린다. 글다듬이는 한국어 원문을 되쓰는 단위라 영어 지시가
  번역을 유발할 수 있어(그 결과는 형식상 정상 응답으로 내려간다) 영어 블록 안에
  "출력은 한국어, 번역 금지"를 한 줄 더 못박았다. 근거는 각 `*.j2` 머리말에 있다.
- **프롬프트 조립 함수는 `(system, user)` 튜플을 돌려준다.** 시스템 프롬프트를 모듈
  상수로 두지 않는 이유: 렌더는 실패할 수 있고(템플릿 부재·변수 누락), 두 프롬프트를
  한 함수에서 만들면 템플릿 변수를 늘릴 때 한쪽만 고치는 실수가 막힌다.
- **성공/오류로 반환형이 갈리는 FastAPI 라우트에는 반환 타입 주석을 붙이지 않는다.**
  FastAPI 는 `Response` 서브클래스가 **아닌** 반환 주석을 `response_model` 로 삼는데,
  `JSONResponse | dict` 같은 Union 은 응답 모델을 만들지 못해 라우트 등록 단계에서
  앱이 죽는다. 가이드 §I 의 타입힌트 권고보다 기동 실패를 피하는 쪽이 우선이다
  (번역 `glossary_reload` 가 그 형태였고 2026-08-07 에 떼어냈다).
- **워크플로우(02) 토큰 스트리밍**: `sio_server.emit` 뒤에 `await asyncio.sleep(0)`,
  전송 단위는 글자가 아니라 청크(`_STREAM_CHUNK_CHARS`). 근거는 `onprem/README.md`
  "워크플로우 스트리밍 규약". 함수명 `run` 은 GenOS 고정 계약이라 변경 불가.

## 평가지표 (onprem/eval — 상세는 onprem/eval/README.md)

- 지표 정의의 원본은 **루트 `README.md`**, 실행 가능한 구현은 `onprem/eval/eval_mcp/` 다.
  기능별 지표 묶음과 합불 기준은 `suites.py` 선언 표 한 곳에서 고친다.
- **결정적 도구(Text/Numeric/Structure)가 운영 지표**다. `LLM Judge` 는 게이트드 —
  스크리닝 미통과분 + 해시 표본 + opt-in 이어야 열리고, 실제 판정 호출은 아직 없다.
- **미측정을 통과로 보이게 하지 않는다**: `verdict` 에 `pass_but_incomplete`,
  `skipped_metrics` 에 건너뛴 지표와 이유를 담아 돌려준다.
- eval 은 세 배포 단위를 **import 하지 않는다** (파서를 공유하면 파서 버그를 함께 놓친다).
  그래서 슬롯 인식 규칙 같은 도메인 규칙은 양쪽에 각각 구현돼 있다 —
  운영 규칙을 바꾸면 `eval_mcp/structure_metrics.py` 도 같이 봐야 한다.
- eval 의 오류 규약만 다르다: 워크플로우/코드서빙은 오류 **객체 반환**, eval 은
  **로그 남긴 뒤 예외**(`error_codes.fail()`), 로그는 stdout 오염 방지로 stderr 전용.

## 검증 명령

```
export PYTHONIOENCODING=utf-8   # Windows 콘솔 필수 (cp949 가 '—' 에서 죽는다)

# 함수 단위 회귀 테스트 — **사본이 아니라 onprem 을 직접 태운다** (2026-08-11 개편)
cd SFR-006 && python -m unittest discover -s tests -t .   # 28건
cd SFR-018 && python -m unittest discover -s tests -t .   # 49건 (표 HTML 전환·preprocessor 추가분 포함)

# 배포 계약 (서버·포트 불필요, 소스만 읽는다)
# 코드서빙 4 + eval + 워크플로우 스텝 9 + **MCP 파일 4**. FAIL 0 / 종료 코드 0.
python onprem/test/check_deploy_contract.py # FAIL 0 / WARN 5 / OK 53

# 실행 점검 (정적 점검이 못 잡는 층 — 실제로 띄우고 돌려 본다)
python onprem/test/check_service_boot.py    # 16건 — 코드서빙 4단위 기동·lifespan·/health·/
python onprem/test/check_workflow_run.py    # 35건 — 워크플로우 스텝 9개 실행·반환형·result 1회
python onprem/test/check_mcp_tools.py       # 37건 — MCP 파일 4개 공존·결정적 판정·빈 문자열 주입

# 엔드포인트·기능 (전부 서버·Redis·LLM 불필요 — 가짜를 배포 단위 밖에서 주입한다)
python onprem/test/check_api_contract.py    # 42건 — 006 코드 서빙 엔드포인트
python onprem/test/check_unit_endpoints.py  # 11건 — 번역·FAQ 엔드포인트 경계
python onprem/test/check_chat_turn.py       # 25건 — 대화 한 턴 계약·상태 전이
                                            #        (02 스텝 3개 ↔ 03 chat_api 를 함께 태운다)
python onprem/test/check_body_blocks.py     # 17건 — 문단 복제 안전장치
python onprem/test/check_output_safety.py   #  5건 — 파트 선언·누름틀 안내문
                                            #        (개봉 게이트·넘침·check_vendor_closure.py 는
                                            #        2026-08-12 에 뺐다 — 아래 "python-hwpx 벤더 사본" 절)

# 사본 대조 (배포 단위 간 import 금지로 강제된 중복이 갈렸는지 — 동작으로 본다)
python onprem/test/check_table_grid.py      # 18건 — 006↔번역↔FAQ↔MCP 표 격자 규칙 (단순표 + 병합표 2층)
python onprem/test/check_tone_policy.py     # 26건 — 톤 사본 4벌 대조
```

**11개 + unittest 2벌.** `check_vendor_closure.py` 삭제 + `check_output_safety.py` 축소
(2026-08-12, "python-hwpx 벤더 사본" 절 참고)로 개수·건수가 바뀌어 위 총계는 재확인 전이다.
경로가 `onprem/codeserving/…` 로 바뀌었으니 새 점검을 붙일 때 옛 `onprem/SFR-*` 를
하드코딩하지 말 것.

**기능 명세는 `onprem/docs/FEATURES.md` 에 있다** — 무엇이 구현돼 있고 어느 경로로
부르며 무엇을 보장하는지. 이 파일(CLAUDE.md)은 "왜 그렇게 했나" 를 맡는다.

**python-hwpx 벤더 사본 — 도입(2026-08-10) 후 철회(2026-08-12).** 006 은 한동안
개봉 안전 게이트·넘침 측정을 위해 python-hwpx 일부를
`onprem/codeserving/SFR-006_template_fill/template_fill/_vendor/` 에 벤더 사본으로 두고
있었다(Apache-2.0, 상류 rev `caeb9cf`, ≈1,670줄) — pip 의존으로 두면 폐쇄망 registry 에
wheel 이 있는지에 따라 두 검사가 켜졌다 꺼졌다 했기 때문이다.

**지금은 뺐다.** 실제 배포 템플릿이 3개뿐이고 전부 표 없는 1~2쪽짜리라, 넘침 측정(표 셀
슬롯만 잰다)과 개봉 안전 게이트 둘 다 실질적으로 아무 판정도 하지 않는 코드였다 — 유지
비용(벤더 사본 약 2,000줄 + `overflow.py`·`hwpx_verify.py` 약 800줄, 전부 폐쇄망 이관 시
손으로 옮겨 적어야 하는 분량)에 값하는 실익이 없었다. `_vendor/` 전체와
`overflow.py`·`hwpx_verify.py`, 그리고 `document.py`의 `verify` 매개변수 및
`TEMPLATE_FILL_VERIFY_OUTPUT`·`TEMPLATE_FILL_CHECK_OVERFLOW` 설정을 지웠다.

**되살릴 일이 생기면 `archive/hwpx-genon-vendor` 브랜치에 그대로 있다** — 도입 판단 근거는
`onprem/docs/hwpx_library_adoption.md`(그 브랜치 시점 기준, 지금은 미적용), 재동기화
절차는 `git show archive/hwpx-genon-vendor:onprem/codeserving/SFR-006_template_fill/template_fill/_vendor/README.md`.
표가 있는 템플릿이 실제로 들어오거나, 한/글 없이 산출물 개봉 여부를 판정해야 할 필요가
다시 생기면 그 브랜치에서 세 파일(`_vendor/`, `overflow.py`, `hwpx_verify.py`)만 가져와
`document.py`에 다시 연결하면 된다.

Windows 콘솔에서는 `PYTHONIOENCODING=utf-8` 을 준다 (cp949 가 `—` 에서 죽는다).

**`onprem/codeserving/SFR-006_template_fill` 을 고치면 위 4개를 돌린다.** 앞의 둘은 특성화 점검이라
"동작이 바뀌지 않았다" 를 보증한다 — main.py·run_chat.py 분리를 이 그물 위에서 했다.

**위 unittest 는 `SFR-006/`·`SFR-018/` 사본을 검증한다. `onprem/` 은 규칙상 `tests/` 를
두지 않아 자동 회귀 테스트가 없다** — 슬롯 모드처럼 `onprem/` 에만 있는 기능은
합성 hwpx 픽스처 스모크로 확인했고(누름틀 0개 템플릿 채움·서식·표기제거·라운드트립,
누름틀 폴백, eval 라운드트립/무결성), 정식 테스트는 아직 없다. 기능을 고칠 때
이 공백을 전제하고 움직일 것.

**대신 `onprem/test/` 에 점검 4개(90건)를 커밋해 뒀다** (위 "검증 명령"). 정식 유닛테스트가
아닌 이유는 사본에 슬롯 파서가 없어서일 뿐이고, 파서를 이식하면 `tests/` 로 옮긴다.

스모크를 쓸 때는 **픽스처를 위험하게 만들 것** — `check_body_blocks` 첫 판은 안전한
모양이라 안전장치를 꺼도 통과했다. 실제 템플릿처럼 secPr 과 슬롯을 한 문단에 두고 표 run 을
텍스트 run 앞에 둬야 잡힌다. 그리고 **가짜 Redis 는 import 보다 먼저 꽂을 것** —
`session_store`·`template_index` 가 `from .redis_client import resolve_client` 로 이름을
복사하므로, 나중에 갈아 끼우면 원본이 계속 쓰여 점검이 통째로 무의미해진다.

## 전처리기 입력 원칙 (SFR-018) — 매번 다시 알아내지 말 것

docx/pdf/hwpx 는 전처리기가 변환해 들어오며 **표 형식이 유형별로 다르다**
(`genos_files/attach_processor.py`, `intelligence_processor.py` 확인 결과):
- 첨부용: 마크다운 표 + `<!-- PB -->` 페이지 마커
- 지능형: 마크다운 표 또는 **한 줄 HTML 표**(`<table><tbody>…`, 셀 html.escape,
  colspan, 같은 줄 제목 접두 가능) + `[표 설명]` 요약

**표 등 구조는 건드리지 않고 내용만 바꾼다** — 번역은 `/translate/markdown` 의
스켈레톤 분리(마크다운+HTML 모두)로 구조를 코드가 보장하고, 글다듬이는
`markdown_guard.py` 지문 대조로 훼손을 감지한다.
프롬프트 지시("표를 유지하라")만으로 구조 보존을 처리하지 않는다.

## 실제 운영 코드 대조 (2026-08-05)

`genos_files/app.py`(코드서빙 진입점)·`bridge.py`(워크플로우 노드)는 **다른 팀이 실제
운영 중인 GenOS 배포에서 긁어온 사본**이다. 우리 4개 진입점과 대조해 두 가지를 고쳤다:
`/api/gateway` prefix 누락(018 x2)과 emit 뒤 `sleep(0)`·청크 전송 부재(02 x2).

**이 참고 코드는 작동하는 샘플이지 규칙 준수 모델이 아니다.** 그대로 베끼지 말 것:
- `app.py` 가 `print()` 로 **액세스 토큰을 로그에 찍는다** (§C 이중 위반).
- `bridge.py` 의 `_session_states` 는 전역 dict — 규칙 D.2 가 금지했고 레플리카 2개면
  세션이 깨진다. 우리가 Redis(`session_store.py`)로 뺀 쪽이 맞다.
- 고객명 하드코딩, 파일 첫 줄에 오타(`ge"""`)가 섞여 있어 그 파일은 import 도 안 된다.

대조에서 확인했지만 **아직 안 맞춘 것**(동작에 지장 없다고 판단, 필요해지면 착수):
- `sid` 폴백 — 참고는 `socketIOClientId → sessionId → session_id`, 우리는 첫 번째만.
- 질문 alias — 참고는 `question/message/query` + 중첩 `request_payload`, 우리는
  `question/text` 만.
- ~~루트 경로~~ — **2026-08-07 에 맞췄다고 적었지만 실제로는 동작하지 않았고,
  2026-08-11 에 진짜로 고쳤다.** `@app.get("")` **만으로는 아무 경로에도 매칭되지 않는다**
  — ASGI 요청의 path 는 최소 `/` 라서 빈 문자열 라우트에는 영영 닿지 않고, `/` 라우트는
  등록된 적이 없으니 둘 다 404 다. 세 코드서빙 단위 전부 그 상태였다. 지금은
  `@app.get("/")` 를 함께 등록한다. `check_api_contract` 가 루트를 아예 안 봐서 40/40
  통과 상태로 넉 달을 살아남았고, 그래서 그 점검에 2건을 추가했다.
- 코드서빙 호출 경로 — **해소됨 (2026-08-06, 가이드 6.4·6.9 확인).** 참고 코드의
  `POST /json`·`/multipart` 는 Python `service(config, data)` **호환 방식에서만 자동
  제공되는 경로**이고, 업무 API 경로는 사용자 앱이 정한다. 가이드 6.9 는 호환용 경로를
  필수로 가정하는 것을 잘못된 예로 든다 — 우리 `/generate`·`/translate` 가 정상이고
  참고 코드를 따라갈 이유가 없다. **다운로드 버튼 배선만 실물로 확인 필요.**
- 인증 — 참고 `app.py` 는 액세스 토큰을 **JSON 바디**(`payload["Authorization"]`)로 받는다.
  우리 코드서빙은 호출자 인증이 없다(관리자 토큰 제외). 폐쇄망 전제이나 토큰은 실제로 온다.

## 개발가이드 6장에서 나온 배포 계약 (2026-08-06 확인, 지금도 유효)

원문 재정리는 `genos-project/docs/GENOS_RULES.md` §E 에 있다. 여기서는 코드에 계속
영향을 주는 것만 남긴다.

- **코드 서빙은 Git 저장소가 배포 단위**다. GenOS 가 저장소를 가져와 언어별 기본 이미지에서
  빌드·실행한다. **사용자 Dockerfile 은 표준 등록 단위가 아니다**(6.3) — PDF 전처리기
  (`genon.preprocessor`)처럼 pip 로 안 되는 것은 **기본 이미지 변경 절차**(11.5.6)를 탄다.
- **저장소 루트에 `main.py` 가 있으면 그 파일이 먼저 실행된다**(6.2). 그래서 루트 `main.py`
  에는 `if __name__ == "__main__"` uvicorn 기동 블록이 있어야 하고, 진입점이 패키지 안인
  단위(006·FAQ)는 그 자동 경로에 안 걸리므로 **시작(Run) 커맨드 등록이 필수**다.
  `check_deploy_contract.py` 가 이 둘을 갈라서 본다.
- `PORT`(기본 8080)·`OPENAPI_PATH`·`LANGUAGE`·`BUILD_COMMAND`·`START_COMMAND` 는 GenOS 가
  주입한다 — 다른 목적으로 쓰지 않는다(점검이 매 단위 확인한다).

## onprem 전수 점검 (2026-08-11)

네 배포 단위 + eval 을 훑어 **기동·배포를 막는 결함 넷**을 고쳤다. 상세는
`onprem/test/README.md` "상태" 절.

1. **`SFR-018_faq` 에 `requirements.txt` 가 없었다.** 2026-08-07 에 배포 단위로 들어왔는데
   의존성 파일 없이 왔고 `check_deploy_contract.py` 의 단위 목록에도 빠져 있었다 —
   빌드 커맨드(`pip install -r`)가 그 자리에서 실패한다. 파일을 만들고 단위로 등록했다.
2. **번역 단위가 `python-multipart`·`lxml` 을 선언하지 않고 있었다.** 둘 다 **기동 자체를
   막는다** — 전자는 `File(...)`/`Form(...)` 라우트를 등록하는 순간 FastAPI 가 RuntimeError
   를 내고(실측 확인), 후자는 `office/hwpx_text.py` 가 모듈 최상단에서 import 한다.
   `jinja2` 는 006·번역·FAQ 셋 다 빠져 있었다(지연 import 라 기동은 되고 첫 요청에서 죽는다).
3. **루트 경로 `@app.get("")` 가 세 단위 전부 404 였다** (위 "실제 운영 코드 대조" 절).
4. **개봉 안전 게이트가 항상 돌게 되면서 `/generate` 가 막히고 있었다** — 점검 픽스처가
   온전한 OPC 패키지가 아니었다. `onprem/test/hwpx_package.py` 로 통일했다.

**`check_deploy_contract.py` 가 FAIL 0 이 됐다.** 그전까지 영구히 빨간색이었고, 그 빨간색에
1번이 묻혀 있었다. FAIL(기동 불가)과 WARN(이미지 제공 / 코드가 `try/except ImportError` 로
방어)을 나눴다 — 후자는 이름 하드코딩이 아니라 **AST 로 방어 여부를 보고** 판정한다.

확인만 하고 **고치지 않은 것**:
- `@app.on_event("startup")` 은 deprecated 다(세 단위 사용). 지금은 돌지만 FastAPI 가
  제거하면 import 단계에서 죽는다 — requirements 에 상한이 없어 시점을 통제할 수 없다.
- 업로드 세 경로 모두 `await document.read()` 로 **전량을 읽은 뒤** 크기를 검사한다.
  `UploadFile` 이 디스크로 spool 하므로 OOM 은 아니지만 상한 밖 디스크를 쓴다.
- 번역 `TranslateRequest.register` 가 `BaseModel.register` 를 가린다는 pydantic 경고 —
  값은 정상 왕복하고 `resolve_register` 까지 도달한다(실측). 경고일 뿐이다.

### 미사용 함수 전수 점검 (2026-08-11) — 운영 코드에 죽은 함수는 없다

함수 **703개 / 파일 115개**를 두 가지 방식으로 걸렀고, **운영 코드 미사용은 0건**이다.
후보는 두 번 다 나왔지만 전부 오탐이었다 — 그 오탐의 정체를 적어 두는 것이 이 절의 목적이다.
같은 점검을 다시 할 사람이 같은 자리에서 또 헛걸음하지 않게.

1. **참조 0건 검색** → 후보 21개. 전부 정상이다:
   - **FastAPI 라우트 핸들러 11개** (006 `register_template`·`delete_template`·
     `patch_values`·`delete_values`·`put_blocks`·`generate_upload`, FAQ `service_config`·
     `generate_upload`·`get_faqs`, 번역 `glossary_status`·`translate_hwpx`).
     데코레이터로 등록되므로 **이름으로 부르는 코드가 없는 것이 정상**이다.
   - 던더(`__str__`·`__bool__`)와 `_vendor`.
2. **엔트리포인트 도달 가능성(호출 그래프)** → 운영 코드 후보 6개. **전부 별칭
   import(`as`)** 라 이름 기반 그래프가 연결을 놓친 것이었다. 여섯 건 다 호출 지점까지 열어
   확인했다:

   | 후보 | 실제 사용처 |
   |---|---|
   | `api_errors.install` | `main.py:50` `as install_error_handler` → `:72` |
   | `hwpx_verify.enforce` | `document.py:54` `as enforce_open_safety` → `:135` |
   | `pdf_convert.available` | `session_view.py:27` `as pdf_available` → `:149` |
   | `text_polish.prompt_loader.render` | `main.py:31` `as render_prompt` → `:72` |
   | `languages.supported_payload` | 번역 `main.py:45` `as supported_languages` |
   | `registers.supported_payload` | 번역 `main.py:51` `as supported_registers` |

   FAQ(90개)·eval(92개)은 두 방식 모두 후보 0건이었다.

**`_vendor/` 안 15개는 실제로 안 쓰인다. 그대로 둔다.** `tag_local_name`·`tag_in_family`·
`element_qn_like`·`register_owpml_namespaces`·`SlotMetrics.height_lines*`·`_children_by_local`
등이다. 상류(python-hwpx) 사본이라 미사용이 정상이고, **지우면 재동기화 절차가 어긋난다**
(`template_fill/_vendor/README.md`). 벤더 사본을 줄이는 기준은 미사용 여부가 아니라
`check_vendor_closure.py` 가 재는 **절연**이다.

> 위 두 절(참조 0건 검색의 `hwpx_verify.enforce` 행, `_vendor/` 미사용 15개)은 2026-08-11
> 시점 기록이다. `_vendor/`·`overflow.py`·`hwpx_verify.py`·`check_vendor_closure.py` 는
> 2026-08-12 에 전부 지웠다 — "python-hwpx 벤더 사본" 절 참고. 지금 저장소에는 존재하지
> 않는 코드를 가리키므로, 이 감사 기록은 **당시 상태의 역사적 기록**으로만 읽을 것.

**한계 — 이 점검이 보증하지 않는 것**: 호출 그래프가 이름 단위 매칭이라 **살아 있는 함수와
이름이 겹치는 죽은 함수는 숨을 수 있다**(`render`·`available` 처럼 흔한 이름). 즉 "죽었다고
나온 것은 확실히 죽었다"는 보증만 있고 그 역은 없다. 그 구멍까지 막으려면 import 심볼
테이블로 참조를 해석해야 하는데 **돌리지 않았다.** 점검 스크립트도 세션 임시 디렉토리에
있어 저장소에 남지 않는다 — 다시 필요하면 새로 짜야 한다.

## 남은 일 (2026-08-07 갱신)

**프롬프트 파일 이관 — 네 단위 완료(2026-08-07)**
- 006(`prompts.py`)·글다듬이(`main.py` 의 `_BASE_SYSTEM_PROMPT`)에 문자열로 있던
  프롬프트를 `onprem/prompt/<단위>/*.j2` 로 뺐다. 프롬프트 디렉토리 이름도 배포 단위
  이름과 맞췄다 (`SFR_018_translation`→`SFR-018_translation`, `SFR-018-FAQ`→`SFR-018_faq`).
- 006 의 `EXTRACT_SYSTEM_PROMPT`/`TONE_SYSTEM_PROMPT` 모듈 상수는 없어졌고
  `build_extract_prompts` / `build_tone_prompts` 가 `(system, user)` 를 돌려준다.
- **새 배포 의존**: 글다듬이(02) 이미지에 `jinja2` 가 필요해졌다. 이 단위는
  `lxml`·`redis` 를 안 쓰므로 워크플로우 이미지에 추가되는 유일한 패키지다.
  막히면 이 단위만 코드 문자열로 되돌리는 선택지가 있다(규약이 갈리는 대가는 있다).
- 네 단위 렌더는 로컬 스모크로 확인했다(경로 해석·StrictUndefined·디렉토리 부재 시
  `PromptRenderError`). **LLM 실호출로 품질을 본 것은 아니다** — 한/영 분리가 실제
  출력에 어떻게 작용하는지는 게이트웨이가 열린 뒤 확인할 일이다.
- 테스트 사본(`SFR-006/`, `SFR-018/`)은 **이관 대상이 아니었다.** 사본은 여전히 코드
  문자열 프롬프트를 들고 있고, 사본 tests 가 프롬프트를 참조하지 않아 깨지지는 않는다.
  드리프트가 한 겹 늘어난 셈이라, 구조 개편 때 함께 정리한다.

**hwpx 전용 전처리기 — 추후 과제(2026-08-07 논의, 착수 보류)**
- **할 일**: hwpx 전용 전처리기를 만들어, **지금 지능형 전처리기가 뽑는 값과 대조해
  수치를 교정**할 수 있게 한다. 요구사항 `data/translation_rule.md` §5 가 이미
  "직접 파싱하거나 **마크다운 변환 후 xml 로 이중 검증**" 을 열어둔 그 선택지다.
- 지금은 세 단위가 각자 hwpx 를 판다. `SFR-018_translation/office/hwpx_text.py`(243줄)와
  `SFR-018_faq/faq/hwpx_text.py`(227줄)는 **로직이 사실상 동일한 사본**이고(diff 확인,
  다른 건 머리말과 FAQ 쪽 `hwpx_xml.py` 분리뿐), 006 `hwpx_markdown.py` 도 표 격자
  규칙(`cellAddr` 좌표·병합 앵커)이 같다. 착수하면 이 중복이 정리 대상이다.
- **착수 전 확인 (미해결)**: 전처리기 커스터마이즈 지점이 어디까지인가.
  - (ㄱ) **등록하는 단일 파일**(`attach_processor.py` 형태 — `DocumentProcessor(config_path)`
    가 config 를 읽어 도는 2,400줄짜리 한 파일)만 우리 것인가 →
    그러면 산출물 자체를 고치는 쪽이고, 적재 경로는 직접 파싱이 필요 없어진다.
  - (ㄴ) **설치 패키지 `genon.preprocessor` 안**(facade/converters)에도 손댈 수 있는가 →
    그러면 파싱 모듈을 `converters/` 에 넣고 네 단위가 `hwp_to_pdf` 처럼 import 한다.
    **이 방식은 이미 쓰고 있다** — `pdf_convert.py`·`faq/exporters/pdf_export.py` 가
    `from genon.preprocessor.converters.hwp_to_pdf import convert_hwp_to_pdf` 로
    코드서빙에서 요청 시점에 부른다. 즉 전처리기 코드를 따로 부르는 건 가능하다.
- **어느 쪽이어도 남는 것 둘**:
  1. 직접 업로드 경로(`POST /translate/hwpx`, `POST /generate/upload`)는 전처리기를
     지나지 않는다. 그 경로를 유지하는 한 파서는 어딘가 한 벌 필요하다.
  2. 006 은 읽기가 아니라 **되쓰기**(`fill_template`·`charPr`)라 어느 쪽으로도 안 빠진다.
- **선행 검증**: 표가 든 실물 hwpx 를 **첨부용**(`HwpProcessor` — GenosHwp SDK + docling
  네이티브, PDF 는 최후 폴백)으로 태워 수치가 보존되는지 본다. 요구사항의 "표 깨짐" 은
  **지능형**(무조건 PDF 변환) 이야기일 가능성이 있다. 첨부용으로 충분하면 이 과제 자체가
  작아진다.

**가이드 준수 점검 — 네 단위 전수 대조 완료(2026-08-07)**
- 결과표는 `onprem/README.md` "가이드 준수 점검" 절. 고친 것 두 건:
  번역 `_startup` 의 blocking 파일 읽기(→`to_thread`), 번역 `glossary_reload` 의
  Union 반환 주석 제거. 006 에 `@app.get("")` 도 추가해 세 코드서빙 규약을 맞췄다.
- **로컬에 `fastapi` 가 없어 앱 구성 단계를 실행해 보지 못했다.** 위 Union 건은
  FastAPI 의 알려진 동작을 근거로 고친 것이고 크래시를 재현한 것은 아니다.

**저장소 구조 개편 — 실행 완료(2026-08-11)**
- 상세는 위 "저장소 구조 개편" 절. onprem 단일 소스화 + SFR-006/018 테스트 전용화가
  **끝났다.** 사본 드리프트라는 위험 자체가 없어졌다.
- **영역 재배치(2026-08-11)와 헷갈리지 말 것.** 그쪽은 `onprem/` 안을 area 별로 가른
  것이고, 이건 `onprem/` ↔ 테스트 사본 관계였다. 둘 다 이제 완료다.

**서빙 등록 단위 — 저장소는 1개, 서빙은 8개로 간다 (2026-08-11 결정)**
- 코드 서빙 하나 = 컨테이너 하나 = URL 하나다. **등록은 단위마다 반드시 따로** 한다
  (코드서빙 4 + MCP 4 = 8번). 저장소를 어떻게 두든 이 숫자는 줄지 않는다.
- **저장소는 하나로 둔다.** 여러 서빙이 같은 저장소·같은 커밋을 가리켜도 되고, 디렉토리
  구분은 빌드·시작 커맨드가 흡수한다(가이드에 하위 디렉토리 지정 항목이 없다).
- **근거는 사본 대조다.** 배포 단위 간 import 금지 때문에 표 격자 4벌·톤 프리셋 4벌 같은
  **의도된 중복**이 있고, 갈렸는지는 한 커밋 안에서 동시에 읽어야 확인된다. 저장소를
  쪼개면 `onprem/test/` 의 대조 점검이 경계를 넘어야 해서 **성립하지 않는다.**
- **실물에서 확인할 것 하나**: 빌드·시작 커맨드가 셸을 거치는지(`cd A && B` 가 먹는지).
  안 먹으면 `uvicorn --app-dir <경로> …` 로 바꾼다. 그 전까지 저장소를 쪼개지 않는다.
  상세는 `onprem/README.md` "저장소 구조" 절.

**SFR-006**
- 실제 현장 템플릿 스팟체크 **완료** (2026-08-05, `data/파워.hwpx` — 커밋되지 않은 샘플).
  라벨 5개 전부 인식(여러 run 분할·콜론 앞 공백 포함). 거기서 나온 두 결함은 고쳤다
  (값 안내를 글꼴로 오인 / 콜론 줄맞춤 손실). 아직 확인 못 한 것: **표 안 라벨과 전각 콜론은
  합성 픽스처로만 검증**했고 실물 사례가 없다. 20자 초과 항목명도 실물 사례 미확인.
- `onprem/` 라벨 항목 모드의 **회귀 테스트 부재** — 붙일 때는 `SFR-006/template_fill/tests`
  규약(`python -m unittest discover`)을 따르고, 라벨 파서를 그 사본에도 이식해야 한다.
  사본에는 `hwpx_style.py`·`hwpx_markdown.py`·`template_index.py`·`prompt_loader.py` 가
  아예 없고, 사본의 `prompts.py` 는 이관 전 코드 문자열 버전이다.
- **PDF 는 코드서빙 이미지에 전처리기 패키지(`genon.preprocessor`)가 들어가야 동작한다.**
  코드는 끝났고 호출 규약은 경계 스텁으로 검증했다 — 실제 변환기로 돌려보는 것만 남았다
  (인프라에 패키지 포함 여부 확인 필요).
- 값 수정 경로는 **둘 다 `feat/sfr006-template-pipeline` 에 병합했다** (2026-08-05).
  대화 수정(`clears`)과 화면 직접 수정(`PATCH/DELETE /values`)은 서로 다른 층이고
  보완재라, 어느 쪽을 노출할지는 UI 가 정한다 — 백엔드를 나누면 사본 드리프트만 늘어난다.
  `feat/sfr006-direct-edit`·`feat/sfr006-chat-edit` 은 병합 이력용으로만 남아 있다.
- 반복 블록(contents 배열)이 필요해지면 `hwpx.py` → `hwpx_fields.py` 이식.
  **본문 블록(`hwpx_blocks.py`)과 다른 것이다** — 반복 블록은 템플릿에 미리 표시해 둔
  구간(`{{main}}`/`{{detail}}`)을 항목 개수만큼 늘리는 것이고, 본문 블록은 템플릿에 없던
  내용을 뒤에 이어 쓰는 것이다. 반복 블록이 필요해지면 본문 블록의 문단 복제 로직
  (`_clone_for_text`)을 재사용할 수 있다.
- **본문 블록 미확인 사항**: 실물 대화로 LLM 이 `blocks` 를 제대로 뽑는지는 아직 못 봤다
  (프롬프트 규칙 11~17). 파이프라인은 합성 픽스처와 `data/파워.hwpx` 로 검증했다.
  삽입 위치 기본값이 문서 끝이라, **서명란·붙임 문단이 마지막에 있는 템플릿**을 만나면
  `TEMPLATE_FILL_BLOCK_ANCHOR` 로 위치를 지정해야 한다 — 그런 템플릿 실물은 아직 없다.

**SFR-018 내보내기 — 브랜치 폐기(2026-08-07), 태그로만 보존**
- **글다듬이(`onprem/codeserving/SFR-018_text_polish` + 워크플로우 스텝 2개)는 기능적으로 완결**돼 있다. 입력 정규화 →
  문서유형·톤 정책 → LLM → difflib 변경내역 → 마크다운 구조 점검 → 청크 스트리밍 → `result`
  까지 전 경로가 있다. **글다듬이는 문서 출력(hwpx/PDF)이 필요 없다** — 채팅 응답으로 끝난다.
- `feat/sfr018-export` 브랜치는 **삭제했다**(로컬·origin 모두). 내용은 태그
  **`archive/sfr018-export`** (커밋 `224bd5d`) 에 박제돼 있고 origin 에도 푸시했다.
  거기 들어 있던 것: `onprem/SFR-018_export/` 배포 단위 11개 파일(`hwpx_rewrite.py`,
  `pdf_export.py`, `xlsx_export.py`, `session_store.py`, `HANDOFF.md` 등) + 글다듬이·번역
  양쪽 호출부 배선(`export_client.py`, `paragraph_units.py`).
- **되살릴 일이 생기면 그대로 머지하면 안 된다.** 그 브랜치는 `8e29e91` 에서 갈라져 나와
  **`7aa967c` 의 스트리밍 정합 수정을 되돌린 상태**다 — `_stream_chunks` 청크 전송과 emit 뒤
  `await asyncio.sleep(0)` 이 없는 옛 코드다(글자 단위 emit). main 을 먼저 리베이스하고
  위 "워크플로우(02) 토큰 스트리밍" 규약이 살아 있는지 확인한 뒤 가져올 것.
- 되살릴 때 참고: `git show archive/sfr018-export:onprem/SFR-018_export/HANDOFF.md`

**SFR-018 용어집 — 1단계 병합 완료(2026-08-07)**
- `glossary_exact.py` 를 `onprem/codeserving/SFR-018_translation` 에 병합했고, 적재는 볼륨 파일
  (`TRANSLATE_GLOSSARY_PATH`, JSON/CSV)로 한다. Weaviate 에 묶지 않았으므로 나중에
  벡터DB 가 열리면 적재 경로만 갈아 끼우면 된다(매칭 코드는 그대로).
- **2단계(`glossary.py`, Weaviate + 임베딩 게이트웨이)는 보류 유지.** 폐쇄망 임베딩·
  벡터DB 가용성이 확인되지 않았고, eval 의 임베딩 스크리닝 공백과 같은 차단 요인이다.
- 예전에 적어둔 문제("운영 기능이 없다는 사실이 지표에서 안 드러난다")는 해소됐다 —
  번역 응답이 `glossary.compliance` 와 `glossary.source`(적재 상태)를 직접 낸다.
- **남은 것**: 실제 사내 용어사전 파일을 받아 형식·규모 확인. `_MAX_TERM_WORDS=6`,
  캐시 상한 30만 건이 실물에 맞는지 미검증이다. 태국어·중국어는 띄어쓰기가 없어
  토큰이 길게 잡히므로 그 언어 사전은 사실상 완전 일치만 걸린다(한계로 문서화).

**SFR-018 번역 고도화 — 구현 완료(2026-08-07), 실환경 미검증**
- 결정적 경로는 로컬 스모크로 확인했다: 마크다운 무손실 왕복, 표 셀 파이프 이스케이프,
  6개 언어 감지, 한국어 축 거부, 용어사전 매칭·활용형 준수 판정, 숫자 지문 대조,
  jinja 프롬프트 렌더.
- **미검증**: LLM 실호출 경로 전체(로컬에 게이트웨이 없음), 실제 hwpx 로 `/translate/hwpx`,
  실제 용어사전 파일 적재. `openai` SDK 도 로컬 미설치라 `llm.py` 는 import 조차 안 돌렸다.
- **회귀 테스트 부재**: `SFR-018/translation_refactored/tests` 사본은 옛 시그니처
  (`translate_units(sem, units, target_lang, ...)`)를 전제한다. 지금 코드는
  `options` 를 받으므로 **그 사본은 현행과 어긋나 있다.** 테스트를 붙일 때 사본에
  `languages`·`registers`·`glossary_*`·`numeric_guard` 를 함께 이식해야 한다.

**SFR-018 FAQ — 구현 완료(2026-08-07), 실환경 미검증**
- 결정적 경로는 로컬 스모크로 확인했다: hwpx 표 격자 파싱, 근거 대조(완전 포함·표기
  차이·부분 일치·지어낸 근거), 스키마/중복/근거 기각, 개수 상한 두 층, 부족분 재요청,
  마크다운 조립(채팅=파일 동일), xlsx 수식 인젝션 방지, hwpx 템플릿 반복 블록 복제
  (run 분할 토큰 포함)·mimetype STORED·템플릿 미등록 시 501.
- **미검증**: LLM 실호출, Redis 실연결, FastAPI 엔드포인트 HTTP 실행(로컬 미설치),
  **생성한 hwpx 를 한/글에서 열어보기**, weasyprint PDF(한글 폰트 포함).
- **선결 과제**: 관리자용 **FAQ hwpx 템플릿 실물**이 없다. 반복 블록 규약
  (`{{question}}` 앵커 + `{{answer}}`/`{{evidence}}` + 빈 문단 간격)에 맞는 사내 서식
  파일을 받아야 hwpx 다운로드를 실제로 확인할 수 있다.
- **미해결(플랫폼 팀 확인)**: 워크플로우(02)가 업로드 원본 hwpx 바이트에 접근할 수
  있는지. 지금은 캔버스 변수 `faq_hwpx_path`(공유 볼륨 경로)를 전제로 뒀고, 없으면
  전처리기 마크다운으로 떨어진다 — 그 경우 표 안 수치가 깨질 수 있다는 요구사항 §5 의
  우려가 그대로 남는다. `archive/sfr018-export` HANDOFF §2 의 `temp_doc_id` 질문과 같은 건이다.
- 회귀 테스트 없음. 붙일 때는 `SFR-006/template_fill/tests` 규약
  (`python -m unittest discover`)을 따르고, 위 스모크 항목을 그대로 옮기면 된다
  (스모크 스크립트는 세션 임시 디렉토리에 있어 저장소에 남지 않는다).

**평가 (onprem/eval)**
- 임베딩 유사도 스크리닝·BERTScore, LLM Judge 실제 판정 호출: 온프레미스 서빙 가용성
  확인 후 착수 (미구현 사실은 `metric_catalog` 의 `not_implemented` 에 노출돼 있음).
- **FAQ 지표(루트 README §4)는 eval 에 아직 도구가 없다.** 운영 쪽(`faq/evidence.py`)은
  n-gram 스크리닝을 구현했으므로, eval 에 붙일 때 같은 판정을 쓰되 **import 하지 말고
  각자 구현**한다(파서를 공유하면 파서 버그를 함께 놓친다 — eval 의 기존 규칙).
- `suites.py` 에 FAQ 스위트가 없다. 번역 스위트는 이제 서비스 응답에서
  `glossary.compliance`·`stats.fallback_rate` 를 직접 받을 수 있으므로 재계산할 필요가 없다.
