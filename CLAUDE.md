# CLAUDE.md — genon 저장소 (SFR 기능별 작업 공간)

> 이 저장소에서 코드를 쓰거나 고칠 때의 진입 문서.
> **개발 규칙의 원본은 `genos-project/CLAUDE.md` 와 `genos-project/docs/GENOS_RULES.md` 다** —
> 영역(area)별 시그니처, 오류 코드 체계, HWP/HWPX 도메인 지식, GenOS 런타임 데이터 위치가
> 전부 거기 있다. 먼저 읽고 이 파일로 돌아올 것.
> `genos-project/` 는 CHECKSUMS.txt 로 봉인된 참조 번들이므로 **수정하지 않는다.**

---

## 저장소 구성 (2026-08-05 기준)

```
onprem/                   # ⭐ 폐쇄망 이관용 프로덕션 코드 — 여기가 현행이다
  SFR-006_template_fill/  # HWPX 템플릿 채우기 (워크플로우 02 + 코드서빙 03)
  SFR-018_text_polish/    # 글다듬이 (워크플로우 02)
  SFR-018_translation/    # 번역 (코드서빙 03)
  eval/                   # 평가지표 MCP 서버 — 배포 단위 아님, 위 세 기능 채점용
  test/                   # 배포 계약 점검 스크립트 — 배포 단위 아님
  docs/                   # 기능별 설계 심화 문서 (SFR-006 아키텍처 등)
  README.md               # 배포 단위·환경변수·로깅 규약 (먼저 읽을 것)

SFR-006/                  # 원본 개발 사본 — tests/ 와 mock 모드가 남아 있는 곳
  template_fill/          # 회귀 테스트 보유 (onprem 은 tests 를 두지 않는 규칙)
  hwpx.py                 # 레거시 {{token}} 로컬 검증 CLI (반복 블록 복제 포함)

SFR-018/                  # 원본 개발 사본 — SFR-018/README.md 참고
  text_polish/            # 글다듬이 워크플로우 + tests
  translation_refactored/ # 번역 코드 서빙 + tests
  genos-glossary/         # 용어집 적용 실험 (1단계만 병합 대상 — 아래 결정 참고)

genos-project/            # 📖 읽기 전용 규칙/참조 번들 (개발가이드 PDF, 원본 소스 스냅샷)
genos_files/              # 개발가이드 PDF + hwpx_report.py PoC 사본
archive/                  # zip 백업 (건드리지 않음)
```

같은 이름의 파일이 여러 곳에 있다. 우선순위는 **`onprem/` > `SFR-0xx/` > `genos-project/source/`**:
- `onprem/` 이 폐쇄망에 올라가는 **현행 코드**다. 기능 수정은 여기서 한다.
- `SFR-006/`, `SFR-018/` 은 같은 기능의 **테스트 보유 사본**이다. `onprem/` 은 규칙상
  `tests/` 와 mock 경로를 두지 않으므로, 회귀 테스트를 붙일 때만 여기를 고친다.
  두 사본은 자동 동기화되지 않는다 — 어긋난 부분은 `onprem/` 을 정답으로 본다.
- `genos-project/source/` 는 **과거 스냅샷**이다. 참조만 하고 수정하지 않는다.

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
  `own_nodes`(문단이 직접 가진 텍스트)·`collect_label_occurrences`(라벨인가)를 다른
  모듈이 다시 구현하지 않는다. 두 벌이 되면 채우는 자리와 서식 거는 자리가 어긋난다.
- **도메인 계층은 `Config` 를 읽지 않는다.** 배포 스위치는 `document.py` 가 한 번만 읽는다.
- **조립 순서는 `document.build` 한 곳에만 있다.** 예전엔 코드서빙·미리보기·점검 스크립트가
  각자 적고 있었고, 점검이 자기가 검증할 순서를 스스로 복제해 무의미했다.
- **오류는 `ApiError` 예외 하나로 올린다.** `(값, 오류응답)` 튜플 반환은 폐기했다 —
  `if error: return` 을 한 번 빠뜨리면 조용히 엉뚱한 곳에서 터졌다.
- **영역코드를 섞지 않는다.** 대화가 `template_store`(03 코드)를 쓸 때
  `chat_state.load_context` 가 02 코드로 바꿔 던진다.

## SFR-006 설계 결정 (요약 — 상세는 onprem/docs/SFR-006_architecture.md)

- **라벨 항목 기반이 기본이다** (2026-08-05 변경). 현장 템플릿은 누름틀이 아니라
  본문에 그냥 텍스트로 `제목: {볼드체, 고딕, 16pt}` 처럼 적혀 있다. 콜론 앞이 항목명,
  뒤 `{…}` 가 서식 명세다. 값은 **라벨을 남기고 뒤에 이어 쓰고**(`제목: 실적 보고`),
  명세 표기는 작성 지시문이므로 산출물에서 **지운다**.
  - 라벨 인정 규칙은 결정적이다: 콜론 앞 20자 이내·3단어 이내, `.!?` 없음.
    누름틀이 있는 문단과 `{{token}}` 문단은 각자 경로가 처리하므로 제외.
  - 표(hp:tbl)는 hp:p 안에 hp:p 가 중첩되므로 **문단 소유 텍스트 노드만** 모아
    라벨을 판정한다. `para.iter()` 를 그대로 쓰면 표 전체가 한 줄로 붙어 깨진다.
  - `TEMPLATE_FILL_LABEL_FIELDS=0` 으로 끌 수 있다.
- **누름틀(CLICK_HERE)은 폴백으로 유지**한다. 관리자가 한/글에서 필드를 심은 템플릿을
  올려도 그대로 동작한다. 필드 식별은 `fieldBegin` 의 `name`, 안내문은 첫 `stringParam`.
  begin/end 짝은 **문서 순서 스택 매칭** (문단/필드 id 는 신뢰 불가 — 규칙 문서 §3.2).
  `{{token}}` 은 프로토타입 호환용.
- **채워짐 판정은 코드가 결정적으로** 한다: 라벨 항목은 콜론 뒤 텍스트가 있으면 채워진 것,
  누름틀은 begin~end 텍스트가 비어 있지 않고 안내문과 다르면 채워진 것.
  LLM 의 역할은 사용자 발화 → `{항목명: 값}` 추출까지.
- **서식은 LLM 없이 코드가 적용한다**: `charPr` 을 복제해 `height`(1pt=100)·폰트·굵게만
  바꾸고 그 id 를 라벨 문단 run 의 `charPrIDRef` 에 건다. 같은 서식은 `charPr` 을
  재사용하고, `itemCnt`/`fontCnt` 는 반드시 다시 센다 (틀리면 한/글이 문서를 못 연다).
- **`{…}` 가 전부 서식 명세는 아니다** (2026-08-05, 실 템플릿에서 확인). 현장 템플릿에는
  `담당자 : {소속} {성명}`, `배포일 : {YYYY.MM.DD. (요일)}` 처럼 **값 안내**가 들어 있다.
  그래서 서식으로 인정하려면 근거(크기·효과·글꼴 어휘)를 요구하고, 후보 중 항목명과 같은
  토큰은 제외한다 (`{제목, HY헤드라인M, 16pt}` → 글꼴은 'HY헤드라인M', '제목' 아님).
- **라벨 표기는 원문 그대로 다시 쓴다** — 현장 템플릿은 `제 목 : ` 처럼 콜론을 세로로
  맞춘다. `항목명: ` 으로 재조립하면 줄맞춤이 무너지므로 `LabelOccurrence.prefix` 로 보존한다.
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
  - 서식 원본(`style_ref`)은 **최상위 문단만**. 표 셀 안 라벨은 제외한다(셀 폭 기준 서식이
    본문에 나온다). 표 안 라벨은 **채울 항목으로는 그대로 인식**된다 — LLM 이 표도 채운다.
  - 이름을 못 찾으면 **내용을 버리지 않고** 기본 서식으로 넣고 사유를 남긴다. 기본 서식은
    빈 문단을 쓰지 않는다 — 현장 템플릿의 빈 줄은 `여백: (5pt)` 같은 간격용이다.
  - 순서는 **채우기 → 서식 적용 → 블록**. 앞뒤가 바뀌면 명세 반영 전 모양을 물려받는다.
  - 검증 규율이 값과 다르다: **내용에는 화이트리스트가 없고**(그게 기능이다) 개수·길이
    상한만, **서식 이름에만** 화이트리스트. 대화는 `blocks`/`block_clears`, 화면은
    `PUT /blocks`(배열 통째 교체 — 인덱스 어긋남으로 엉뚱한 문단을 지우지 않게).
  - **세션 저장은 덮어쓰기라** 값만 저장하면 블록이 지워진다 → `_save_edited_values` 가
    항상 블록을 함께 넘긴다.
  - `FieldSpec`/색인 구조가 바뀌어 `SCHEMA_VERSION` 3, 세션 `_STATE_VERSION` 2 (옛 세션은
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
  무효화는 캐시 값 대조로 한다 — 내용 해시·`SCHEMA_VERSION`·`LABEL_FIELDS`.
  **라벨 인식 규칙이나 `FieldSpec` 을 고치면 `SCHEMA_VERSION` 을 올려야 한다.**
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
  그래서 라벨 항목 인식 규칙 같은 도메인 규칙은 양쪽에 각각 구현돼 있다 —
  운영 규칙을 바꾸면 `eval_mcp/structure_metrics.py` 도 같이 봐야 한다.
- eval 의 오류 규약만 다르다: 워크플로우/코드서빙은 오류 **객체 반환**, eval 은
  **로그 남긴 뒤 예외**(`error_codes.fail()`), 로그는 stdout 오염 방지로 stderr 전용.

## 검증 명령

```
# SFR-006 (샘플 hwpx 불필요 — 합성 픽스처)
cd SFR-006 && python -m unittest discover -s template_fill/tests -t .

# SFR-018 번역 (마크다운 구조 보존 계약 포함)
cd SFR-018/translation_refactored && python -m unittest discover -s tests -t .

# SFR-018 글다듬이 (구조 훼손 점검)
cd SFR-018 && python -m unittest discover -s text_polish/tests -t .

# onprem 배포 계약 점검 (서버·포트 불필요, 소스만 읽는다)
python onprem/test/check_deploy_contract.py

# onprem SFR-006 점검 (전부 서버·Redis·LLM 불필요 — 가짜를 배포 단위 밖에서 주입한다)
python onprem/test/check_api_contract.py    # 40건 — 코드 서빙 12개 엔드포인트
python onprem/test/check_chat_turn.py       # 23건 — 대화 한 턴 계약·상태 전이
python onprem/test/check_body_blocks.py     # 17건 — 문단 복제 안전장치
python onprem/test/check_tone_policy.py     # 10건 — 톤 사본 3벌 대조
```

Windows 콘솔에서는 `PYTHONIOENCODING=utf-8` 을 준다 (cp949 가 `—` 에서 죽는다).

**`onprem/SFR-006_template_fill` 을 고치면 위 4개를 돌린다.** 앞의 둘은 특성화 점검이라
"동작이 바뀌지 않았다" 를 보증한다 — main.py·run_chat.py 분리를 이 그물 위에서 했다.

**위 unittest 는 `SFR-006/`·`SFR-018/` 사본을 검증한다. `onprem/` 은 규칙상 `tests/` 를
두지 않아 자동 회귀 테스트가 없다** — 라벨 항목 모드처럼 `onprem/` 에만 있는 기능은
합성 hwpx 픽스처 스모크로 확인했고(누름틀 0개 템플릿 채움·서식·명세제거·라운드트립,
누름틀 폴백, eval 라운드트립/무결성), 정식 테스트는 아직 없다. 기능을 고칠 때
이 공백을 전제하고 움직일 것.

**대신 `onprem/test/` 에 점검 4개(90건)를 커밋해 뒀다** (위 "검증 명령"). 정식 유닛테스트가
아닌 이유는 사본에 라벨 파서가 없어서일 뿐이고, 파서를 이식하면 `tests/` 로 옮긴다.

스모크를 쓸 때는 **픽스처를 위험하게 만들 것** — `check_body_blocks` 첫 판은 안전한
모양이라 안전장치를 꺼도 통과했다. 실제 템플릿처럼 secPr 과 라벨을 한 문단에 두고 표 run 을
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
- 루트 경로 — 참고는 `@app.get("")` 를 둔다(게이트웨이가 경로 없이 베이스를 때리는 경우).
  우리 코드서빙 둘 다 거기서 404 다. `/health` 는 양쪽 다 있어 헬스체크는 통과한다.
- 코드서빙 호출 경로 — **해소됨 (2026-08-06, 가이드 6.4·6.9 확인).** `/json`·`/multipart` 는
  Python `service(config, data)` **호환 방식에서만 자동 제공되는 경로**이고, 업무 API 경로는
  사용자 앱이 정한다. 가이드 6.9 는 호환용 경로를 필수로 가정하는 것을 잘못된 예로 든다 —
  우리 `/generate`·`/translate` 가 정상이고 참고 코드를 따라갈 이유가 없다.
  **다운로드 버튼 배선만 실물로 확인 필요.**
- 인증 — 참고 `app.py` 는 액세스 토큰을 **JSON 바디**(`payload["Authorization"]`)로 받는다.
  우리 코드서빙은 호출자 인증이 없다(관리자 토큰 제외). 폐쇄망 전제이나 토큰은 실제로 온다.

## 개발가이드 6장 대조 (2026-08-06)

개발가이드 PDF 6장(코드 서빙)·11.5 를 원문에서 다시 읽어 `genos-project/docs/GENOS_RULES.md`
§E 를 재작성했다. **코드 서빙은 Git 저장소가 배포 단위**이며 GenOS 가 저장소를 가져와
언어별 기본 이미지에서 빌드·실행한다. 여기서 나온 정합성 수정:

- 코드서빙 두 단위에 **`requirements.txt` 를 추가**했다 (빌드 커맨드가 `pip install -r` 을
  실행하는데 파일이 없었다). 006 은 `python-multipart` 가 빠져 있어 `POST /templates`·
  `/generate/upload` 가 런타임에 실패할 상태였다.
- `SFR-018_translation/main.py` 에 **`if __name__ == "__main__"` uvicorn 기동 블록**을 넣었다.
  가이드 6.2 는 저장소 루트의 `main.py` 가 있으면 그 파일을 먼저 실행한다 — 블록이 없으면
  모듈만 로드되고 서버가 뜨지 않는다. 006 은 진입점이 패키지 안이라 이 자동 경로에 걸리지
  않으므로 **시작(Run) 커맨드 등록이 필수**다.
- **사용자 Dockerfile 은 코드 서빙의 표준 등록 단위가 아니다** (6.3). PDF 의 `genon.preprocessor`
  와 워크플로우의 `lxml`·`redis` 는 둘 다 의존성 파일로 해결되지 않고 **기본 이미지 변경
  절차**를 거쳐야 한다 (11.5.6).
- `PORT`(기본 8080)·`OPENAPI_PATH`·`LANGUAGE`·`BUILD_COMMAND`·`START_COMMAND` 는 GenOS 가
  주입한다 — 이 이름들을 다른 목적으로 쓰지 않는다. 우리 코드에 충돌 없음을 확인했다.

점검은 `onprem/test/` 에 모았다 — 배포 단위 **바깥**이라 이미지에 흘러가지 않는다
(`check_deploy_contract.py` 는 소스만 읽고, `verify_serving.py` 는 배포된 서빙에 요청만
보낸다).

**`check_deploy_contract.py` 첫 실행 완료 (2026-08-06): FAIL 2 / WARN 1 / OK 17.**
FAIL 둘 다 기존·의도된 사항이라 그대로 뒀다 — SFR-006 의 `genon`(전처리기)·
`main_socketio`(GenOS 런타임)은 requirements 가 아니라 **이미지·pod 가 줘야 하는 것**이고
(11.5.6), 평가지표 MCP 는 배포 단위가 아니다. 스크립트를 고쳐 예외 처리할지는 미결이며,
**종료 코드가 1이라 지금 상태로 CI 에 걸면 막힌다.** `verify_serving.py` 는 미실행.

**미결(실물 서버 확인 후)**: 한 저장소 안에 배포 단위 3개가 하위 디렉토리로 있는 구조를
빌드·시작 커맨드로 흡수할지 저장소를 분리할지. 선택지는 `onprem/README.md` 에 적어 뒀고
그때까지 구조는 바꾸지 않는다.

## 남은 일 (2026-08-05 갱신)

**SFR-006**
- 실제 현장 템플릿 스팟체크 **완료** (2026-08-05, `data/파워.hwpx` — 커밋되지 않은 샘플).
  라벨 5개 전부 인식(여러 run 분할·콜론 앞 공백 포함). 거기서 나온 두 결함은 고쳤다
  (값 안내를 글꼴로 오인 / 콜론 줄맞춤 손실). 아직 확인 못 한 것: **표 안 라벨과 전각 콜론은
  합성 픽스처로만 검증**했고 실물 사례가 없다. 20자 초과 항목명도 실물 사례 미확인.
- `onprem/` 라벨 항목 모드의 **회귀 테스트 부재** — 붙일 때는 `SFR-006/template_fill/tests`
  규약(`python -m unittest discover`)을 따르고, 라벨 파서를 그 사본에도 이식해야 한다.
  사본에는 `hwpx_style.py`·`hwpx_markdown.py`·`template_index.py` 가 아예 없다.
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

**SFR-018 용어집 — 결정 완료(2026-08-05), 구현 미착수**
- `genos-glossary` 는 **1단계(`glossary_exact.py`, 222줄)만 병합**한다. 임베딩·Weaviate
  의존이 없는 결정적 문자열 매칭이고, "결정적 도구가 1차 방어선" 원칙에 그대로 맞는다.
- **2단계(`glossary.py`, Weaviate + 임베딩 게이트웨이)는 보류**한다. 폐쇄망 임베딩·벡터DB
  가용성이 확인되지 않았고, eval 의 임베딩 스크리닝 공백과 같은 차단 요인이다.
- 지금 상태의 문제: `onprem/SFR-018_translation` 에는 용어집 적용이 **전혀 없는데**
  eval 은 `glossary_compliance > 0.95` 를 번역 합불 기준으로 두고 있다 → 참조를 주지 않으면
  측정 불가로 처리되지만, 운영 기능이 없다는 사실이 지표에서 드러나지 않는다.

**평가 (onprem/eval)**
- 임베딩 유사도 스크리닝·BERTScore, LLM Judge 실제 판정 호출: 온프레미스 서빙 가용성
  확인 후 착수 (미구현 사실은 `metric_catalog` 의 `not_implemented` 에 노출돼 있음).
