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

## SFR-006 설계 결정 (요약 — 상세는 onprem/README.md)

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
```

**위 테스트는 `SFR-006/`·`SFR-018/` 사본을 검증한다. `onprem/` 은 규칙상 `tests/` 를
두지 않아 자동 회귀 테스트가 없다** — 라벨 항목 모드처럼 `onprem/` 에만 있는 기능은
합성 hwpx 픽스처 스모크로 확인했고(누름틀 0개 템플릿 채움·서식·명세제거·라운드트립,
누름틀 폴백, eval 라운드트립/무결성), 정식 테스트는 아직 없다. 기능을 고칠 때
이 공백을 전제하고 움직일 것.

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
- 코드서빙 호출 경로 — 참고는 `POST /json` 하나로 통일했고 게이트웨이 URL 도
  `.../code_serving/{id}/json` 이다. 서빙 id 뒤 경로가 컨테이너로 전달되는 구조라
  우리 `/generate`·`/translate` 도 도달하지만, **다운로드 버튼 배선은 실물로 확인 필요.**
- 인증 — 참고 `app.py` 는 액세스 토큰을 **JSON 바디**(`payload["Authorization"]`)로 받는다.
  우리 코드서빙은 호출자 인증이 없다(관리자 토큰 제외). 폐쇄망 전제이나 토큰은 실제로 온다.

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
