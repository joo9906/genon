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
  SFR-018_faq/            # FAQ 생성 (워크플로우 02 + 코드서빙 03) — 2026-08-07 신규
  prompt/                 # jinja 프롬프트 (배포 단위 **바깥** — 이미지에 함께 넣을 것)
    <배포 단위 이름>/       # 네 단위 전부. 디렉토리 이름 = 배포 단위 이름
  eval/                   # 평가지표 MCP 서버 — 배포 단위 아님, 위 네 기능 채점용
  README.md               # 배포 단위·환경변수·로깅 규약 + **이관 순서** (먼저 읽을 것)

data/                     # 요구사항 문서 (커밋 대상 — FAQ_rule.md, translation_rule.md)

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

### 저장소 구조 개편 검토 (2026-08-07) — 방향 확정, 이관은 아직 착수 안 함

- **방향**: `onprem/` 을 유일한 실행 코드로 두고, `SFR-006/`·`SFR-018/` 은 앞으로
  **테스트 코드만** 남긴다. 지금처럼 구현을 통째로 복사한 사본을 유지하는 게 아니라,
  onprem 모듈을 import 해서 검증하는 형태로 바꾼다. 위 "두 사본은 자동 동기화되지
  않는다 — 어긋난 부분은 onprem 을 정답으로 본다" 는 드리프트를 전제한 규칙인데,
  이 개편은 그 드리프트 가능성 자체를 없애는 쪽이다.
- **선결 조건 (미확인, 착수 전 확인 필요)**:
  1. `onprem/` 이 테스트에서 import 가능한 패키지 구조인지 — 지금은 폐쇄망 이관 단위로만
     구성돼 있어 경로/패키징 정리가 필요할 수 있다.
  2. `onprem/README.md` 규칙상 `tests/`·PDF 모의 변환 경로는 onprem 에 두지 않고,
     구조 검증용 mock 은 `SFR-006/`·`SFR-018/` 사본에만 남겨두게 돼 있다(4-5줄).
     이 개편과 충돌하지는 않지만, 테스트 전용 사본으로 축소된 뒤에도 전처리기 **경계
     스텁 주입** 같은 검증 방식을 그대로 유지할 수 있는지는 옮길 때 확인해야 한다.
- **범위**: 마이그레이션 자체는 전부 나중 작업이다. 착수 시 SFR-006 먼저 시범 적용 후
  SFR-018 로 확장하는 순서를 제안 상태로 남겨둔다. 이 절은 결정 기록이지 실행 계획이 아니다.

---

## SFR-006 설계 결정 (요약 — 상세는 onprem/README.md)

- **슬롯 문법이 기본이다** (2026-08-07, `origin/feat/sfr006-slot-syntax` 이식).
  관리자는 본문에 중괄호로 자리를 명시한다: `제 목  : {'제목', 16pt, 함초롬돋움, 볼드}`.
  **첫 인자는 따옴표로 감싼 필수값**이고 그것이 항목명이자 AI 안내문이다. 뒤따르는
  인자 0~3개(크기·글꼴·굵게)는 **순서와 개수가 자유롭고**, 지정하지 않으면 그 자리 run 의
  `charPrIDRef` 를 그대로 따른다.
  - **중괄호 안만 채울 자리다.** 중괄호 밖 텍스트(`제 목  : `)는 들여쓰기·줄맞춤 공백까지
    원문 그대로 남는다. 라벨 방식이 `prefix` 를 따로 보존해야 했던 문제가 사라졌다.
  - **따옴표 없는 `{…}` 는 채울 자리가 아니다.** `{소속} {성명}`,
    `{YYYY.MM.DD. (요일)}` 같은 값 안내는 **문서에 그대로 남기고** 경고로만 알린다
    (`bare_braces`). 지우면 안내 문구가 사라지고, 등록을 거부하면 본문에 중괄호를 쓴
    정상 문서를 막는다. 오타인지 의도인지는 사람만 안다.
  - 값이 없는 슬롯은 **표기를 지운다**(작성 지시문이므로). 라벨은 남아 `제 목  : ` 상태가
    된다 — 부분 초안 계약 유지.
  - 한/글 자동 고침의 **굽은 따옴표**(`‘제목’`)도 받는다. 한쪽만 바뀐 문서도 열어 주되,
    짝이 어긋나면(`‘제목"`) 슬롯으로 보지 않는다.
  - **한 문단에 슬롯 여러 개**가 올 수 있다(`{'소속'} {'성명'}`). 라벨의 문단당 1개
    제약이 없어졌다. run 에 걸쳐 쪼개진 슬롯도 문단 텍스트를 이어 붙여 잡는다.
  - `TEMPLATE_FILL_SLOTS=0` 으로 끌 수 있다.
  - **라벨 방식(`항목명: {서식}`)은 제거됐다.** 옛 문법으로 만든 템플릿은 항목이 0개로
    잡히고 중괄호가 전부 "따옴표 없음" 경고로 나온다 — 슬롯 문법으로 다시 써야 한다.
- **누름틀(CLICK_HERE)은 폴백으로 유지**한다. 관리자가 한/글에서 필드를 심은 템플릿을
  올려도 그대로 동작한다. 필드 식별은 `fieldBegin` 의 `name`, 안내문은 첫 `stringParam`.
  begin/end 짝은 **문서 순서 스택 매칭** (문단/필드 id 는 신뢰 불가 — 규칙 문서 §3.2).
  `{{token}}` 은 프로토타입 호환용.
- **채워짐 판정은 코드가 결정적으로** 한다: **슬롯은 언제나 미입력**이다(채우면 `{…}` 가
  사라지므로, 문서에 남아 있다는 것이 곧 아직 안 채웠다는 뜻이다). 누름틀은 begin~end
  텍스트가 비어 있지 않고 안내문과 다르면 채워진 것. LLM 의 역할은 사용자 발화 →
  `{항목명: 값}` 추출까지.
- **서식은 LLM 없이 코드가 적용한다**: `charPr` 을 복제해 `height`(1pt=100)·폰트·굵게만
  바꾸고 그 id 를 슬롯 run 의 `charPrIDRef` 에 건다. 같은 서식은 `charPr` 을
  재사용하고, `itemCnt`/`fontCnt` 는 반드시 다시 센다 (틀리면 한/글이 문서를 못 연다).
- **서식 적용이 채우기보다 먼저 돈다** (`main.py` `_build_document`). 슬롯은 채우는 순간
  `{…}` 가 사라져 어디에 무슨 서식을 걸지 알 수 없게 된다. 그래서 서식 단계가 슬롯을
  **전용 run 으로 떼어내 charPr 을 걸어 두고**, 채우기가 그 run 안 글자만 갈아 끼운다.
  **순서를 뒤집으면 서식이 통째로 유실된다.**
- **슬롯 인자에는 글꼴 어휘 근거를 요구하지 않는다.** 따옴표가 경계를 이미 정했으므로
  사내 전용 글꼴을 목록에 없다고 버릴 이유가 없다. 근거를 요구하는 것은 **누름틀
  안내문 경로뿐**이다 — 거기엔 따옴표 경계가 없어 값 안내(`{소속}`)와 구분할 수단이
  그것뿐이다.
- **자리 표시어를 효과 판정보다 먼저 거른다** (2026-08-07 수정). 효과 판정이 부분 문자열
  매칭이라, 문법 설명을 그대로 복사한 `{'제목', 글씨크기, 폰트, 볼드여부}` 에서
  `볼드여부` 가 `볼드` 에 걸려 실제로 굵어졌다. 자리 표시어는 완전 일치로 거르므로
  진짜 지시(`볼드`)를 삼키지 않는다.
- **lxml 프록시 id 는 붙들어야 유효하다**: `{id(elem): 위치}` 맵을 만들 때 순회 결과를
  리스트로 살려두지 않으면 프록시가 회수되며 id 가 재사용돼 엉뚱한 노드를 가리킨다
  (항목 순서가 뒤섞이는 버그로 실제 드러났다).
- 멀티턴 상태는 **Redis 세션 저장소** (`session_store.py`) — GenOS 는 이전 대화를
  자동 주입하지 않는다. 워크플로우 pod ↔ 코드 서빙 pod 가 같은 `REDIS_URL` 을 보면 되고
  세션 전용 공유 볼륨은 필요 없다(템플릿 파일 볼륨은 여전히 공유해야 한다).
  Redis 클라이언트는 `redis_client.py` 하나를 공유한다 — 모듈마다 `from_url` 을 부르면
  연결 풀이 그만큼 늘어난다.
- **템플릿 파싱은 `template_index.py` 캐시를 경유한다** (등록 시점 1회 파싱).
  무효화는 캐시 값 대조로 한다 — 내용 해시·`SCHEMA_VERSION`·`SLOTS`.
  **슬롯 인식 규칙이나 `FieldSpec` 을 고치면 `SCHEMA_VERSION` 을 올려야 한다** (슬롯 이식으로 3 이 됐다).
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
- **hwpx 다운로드는 템플릿 기반이고, 기본 템플릿을 배포 단위에 싣는다**
  (`faq/assets/faq_template.hwpx`, 2026-08-07 번들). 백지 조립은 `header.xml` 의
  `charPr`/`itemCnt` 한 글자 차이로 한/글이 문서를 못 여는데 확인할 한/글이 없어서
  안 한다 — 대신 실제 한/글이 만든 파일을 뼈대로 재사용한다.
  **관리자 등록을 전제로 두지 않는다**: 요구사항 §2 는 Q/A/근거를 보여주면 된다고만
  하지 사내 서식을 요구하지 않는다. `FAQ_HWPX_TEMPLATE_PATH` 는 덮어쓰기용이고,
  501 은 번들 템플릿까지 없는 배포(이미지 빌드 누락)에서만 난다.
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
- **`render()` 에는 확장자 없는 논리 이름만 넘긴다** (`render("system")`, 2026-08-07).
  파일명(`"system.j2"`)을 넘기면 "프롬프트가 파일로 존재한다"는 사실이 호출부 10곳에
  박힌다. 가이드 §10.5 는 프롬프트를 GenOS Prompt 리소스에 등록하고 **ID 로 참조**
  하라고 하므로(`GET /prompt/template/{id}`), 그때 갈아 끼울 자리가 `prompt_loader`
  한 곳이 아니라 전 호출부가 된다. 확장자는 각 `prompt_loader._TEMPLATE_SUFFIX` 가 붙인다.
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
# SFR-006 (샘플 hwpx 불필요 — 합성 픽스처)
cd SFR-006 && python -m unittest discover -s template_fill/tests -t .

# SFR-018 번역 (마크다운 구조 보존 계약 포함)
cd SFR-018/translation_refactored && python -m unittest discover -s tests -t .

# SFR-018 글다듬이 (구조 훼손 점검)
cd SFR-018 && python -m unittest discover -s text_polish/tests -t .
```

**위 테스트는 `SFR-006/`·`SFR-018/` 사본을 검증한다. `onprem/` 은 규칙상 `tests/` 를
두지 않아 자동 회귀 테스트가 없다** — 슬롯 모드처럼 `onprem/` 에만 있는 기능은
합성 hwpx 픽스처 스모크로 확인했고(슬롯 24항목, 누름틀 폴백, 서식·표기제거·라운드트립,
eval 라운드트립/무결성), 정식 테스트는 아직 없다. 기능을 고칠 때
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
- ~~루트 경로~~ — **맞췄다 (2026-08-07).** 코드서빙 세 단위 모두 `@app.get("")` 를 둔다
  (게이트웨이가 경로 없이 베이스를 때리는 배포 대비). `/health` 는 원래 전부 있었다.
- 코드서빙 호출 경로 — 참고는 `POST /json` 하나로 통일했고 게이트웨이 URL 도
  `.../code_serving/{id}/json` 이다. 서빙 id 뒤 경로가 컨테이너로 전달되는 구조라
  우리 `/generate`·`/translate` 도 도달하지만, **다운로드 버튼 배선은 실물로 확인 필요.**
- 인증 — 참고 `app.py` 는 액세스 토큰을 **JSON 바디**(`payload["Authorization"]`)로 받는다.
  우리 코드서빙은 호출자 인증이 없다(관리자 토큰 제외). 폐쇄망 전제이나 토큰은 실제로 온다.

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

**GenOS Prompt 리소스 전환 — 미착수, 선행 조사 완료(2026-08-07)**
- 가이드 **§10.5 Prompt 로딩**이 표준 경로다. Gateway 가 아니라 **admin-api** 다:
  `GET /prompt/template/{prompt_id}` — 내부 `http://llmops-admin-api-service:8080`,
  외부 `https://<host>/api/admin`. **`/api/gateway/prompt/...` 는 없다.**
  응답은 `{code, data, errMsg}` 이고 **`code != 0` 이면 HTTP 200 이어도 실패**다.
  코드서빙은 `GENOS_ADMIN_API_URL` 환경변수를 리비전 환경설정에 등록한다.
- **준비된 것**: 호출부가 논리 이름만 넘기므로 소스 교체는 `prompt_loader.render`
  안에서 끝난다 (위 컨벤션).
- **API 는 본문 문자열만 돌려준다** (`return payload["data"]`). 템플릿 엔진이 딸려
  오지 않으므로 **jinja 원문을 그대로 등록해 두고 문자열로 받아 우리가 렌더하면 된다** —
  `FileSystemLoader` 대신 `Environment.from_string(fetched)`. `{% for %}`·`{% if %}` 를
  포함한 지금 템플릿을 **한 글자도 안 고치고** 쓸 수 있다.
  - `{question}`·`{context}` 를 `PromptTemplate` 입력 변수로 묶는 것은 **Flowise
    MNC Prompt 노드의 동작**이지 API 계약이 아니다. 이 둘을 붙여 읽으면 "제어문을 못
    쓴다"는 잘못된 결론이 나온다 (실제로 한 번 그렇게 적었다가 고쳤다).
  - 다만 **그 노드로는 우리 프롬프트를 못 쓴다.** 단일 중괄호 치환이라 프롬프트 안의
    JSON 예시(`{"updates": {...}}`)를 변수로 읽는다. 코드에서 API 로 받아 쓰는 경로만
    성립한다.
- **남은 불일치 두 가지**:
  1. `render()` 는 동기, `load_prompt` 는 async HTTP. **다만 구조 문제가 아니라
     기계적 변경이다** — AST 로 확인한 결과 `render` 호출 체인이 **전부 async 함수에서
     끝난다**(`run_chat.run`, `tone_apply.apply_tone`, `generator.generate_faqs`,
     `text_polish.run`, `translation_modes._translate_batch/_single`). 중간의
     `prompts.py`·`prompt_builder.py`·`_build_system_prompt` 는 얇은 조립 함수뿐이라
     `async def` + `await` 만 붙이면 된다. `to_thread` 도 이벤트 루프 위험도 없다.
     실제 결정이 필요한 건 **캐시 정책**이다 — 캐시하면 프롬프트 리비전을 운영 반영해도
     pod 재시작 전까지 옛 본문을 쓴다. §10.5 가 내세우는 "코드 수정 없이 문구 변경"
     이점이 그만큼 깎이므로 TTL 로 절충할지 정해야 한다.
  2. §10.5 가 프롬프트 ID 하드코딩을 금지한다 → 환경변수가 j2 파일 수만큼(현재 12개) 생긴다.
- **워크플로우(02)는 HTTP 직접 호출이 아니라 Flowise `Prompts > MNC Prompt` 노드**를
  쓰라고 돼 있다. 위 이유로 그 노드는 우리 프롬프트에 못 쓰므로, 02 세 단위는 코드에서
  admin-api 를 부르게 된다 — 가이드 권고와 어긋나는 선택이라 근거를 남겨야 한다
  (플랫폼 팀 확인 사항).
- **착수 조건 (이게 갖춰지기 전에는 만들지 않는다)**: 지금 만들면 **한 번도 실행해
  보지 못한 HTTP 경로**가 생기고, 파일 폴백이 멀쩡히 도니 아무도 그 경로를 안 밟다가
  운영에서 환경변수를 바꾸는 순간 처음 돌게 된다 (전처리기 모의 변환 경로를 두지 않는
  것과 같은 판단). 게다가 아래 셋이 클라이언트 모양을 바꾼다:
  1. **§10.5 샘플에 `Authorization` 헤더가 없다.** admin-api 가 실제로 무인증인지,
     샘플이 생략한 것인지 확인해야 한다 — 다르면 클라이언트가 통째로 틀린다.
  2. `prompt_id` 를 누가 어떤 형식으로 발급하는지 (샘플은 `int`).
  3. 코드서빙·워크플로우 pod 에서 admin-api 에 네트워크가 닿는지
     (Gateway 경유가 아니라 내부 서비스 직통이다).
  셋이 확인되면 착수한다. 호출부 seam 은 이미 준비돼 있어 `prompt_loader` 안쪽 작업만
  남는다 — 그때 만들어도 비용이 늘지 않는다.

**가이드 준수 점검 — 네 단위 전수 대조 완료(2026-08-07)**
- 결과표는 `onprem/README.md` "가이드 준수 점검" 절. 고친 것 두 건:
  번역 `_startup` 의 blocking 파일 읽기(→`to_thread`), 번역 `glossary_reload` 의
  Union 반환 주석 제거. 006 에 `@app.get("")` 도 추가해 세 코드서빙 규약을 맞췄다.
- **로컬에 `fastapi` 가 없어 앱 구성 단계를 실행해 보지 못했다.** 위 Union 건은
  FastAPI 의 알려진 동작을 근거로 고친 것이고 크래시를 재현한 것은 아니다.

**저장소 구조 개편 — 방향 확정(2026-08-07), 이관 미착수**
- 상세는 위 "저장소 구조 개편 검토" 절 참고. onprem 단일 소스화 + SFR-006/018 테스트 전용화.
  지금은 문서화만 했고 실제 이관 작업은 시작하지 않았다.

**SFR-006 — 슬롯 문법 이식 완료(2026-08-07), 실물 템플릿 재작성 필요**
- `origin/feat/sfr006-slot-syntax` 의 `hwpx_fields.py`·`hwpx_style.py` 만 골라 이식했다
  (그 브랜치의 나머지 리팩토링 — `hwpx_blocks`·`document`·`template_store`·`session_view`·
  `chat_state` 등 — 은 **가져오지 않았다**. 아래 "미이식" 참고).
- 합성 픽스처 스모크 24항목 통과: 4인자 파싱, 인자 순서 자유, 굽은 따옴표, 한 문단 다중
  슬롯, run 걸친 슬롯, 중괄호 밖 줄맞춤 공백 보존, 따옴표 없는 `{…}` 원문 유지,
  값 없는 슬롯 표기 제거, 레거시 `{{token}}` 공존, charPr 복제, 자리표시어 무시.
- **이식 중 브랜치 코드의 결함 1건을 고쳤다**: `parse_style_args` 가 효과 판정(부분 문자열)을
  자리 표시어 판정보다 먼저 해서 `볼드여부` 가 `볼드` 에 걸려 굵어졌다. 순서를 뒤집었다.
- **`data/파워.hwpx` 는 옛 라벨 문법이라 이제 항목 0개다.** 중괄호 6개가 전부 "따옴표 없음"
  경고로 나온다(`{제목, HY헤드라인M, 16pt}` 등). 의도된 동작이지만 **실물 템플릿을 슬롯
  문법으로 다시 써야** 현장 검증을 이어갈 수 있다. 그 전까지 실물 확인은 공백이다.
- **미이식 (필요해지면 그 브랜치에서 가져온다)**: `hwpx_blocks.py`(본문 반복 블록),
  `document.py`(채우기·서식·블록 조립 단일 진입), `template_store.py`, `session_view.py`,
  `chat_state.py`/`chat_reply.py`(run_chat 분해), `api_errors.py`, `onprem/test/` 검증
  스크립트 7종, `onprem/docs/SFR-006_architecture.md`. 그 브랜치는 `0f82676` 에서 갈라져
  나와 **오늘 작업(프롬프트 jinja 이관·FAQ 단위·번역 고도화)이 전부 빠져 있고**,
  `genos-project/docs/GENOS_RULES.md`(봉인 번들) 94줄 수정까지 들어 있다 —
  **그대로 머지하면 안 된다.**
- `onprem/` 슬롯 모드의 **회귀 테스트 부재** — 붙일 때는 `SFR-006/template_fill/tests`
  규약(`python -m unittest discover`)을 따르고, 슬롯 파서를 그 사본에도 이식해야 한다.
  사본에는 `hwpx_style.py`·`hwpx_markdown.py`·`template_index.py`·`prompt_loader.py` 가
  아예 없고, 사본의 `prompts.py`·`hwpx_fields.py` 는 이식 전 버전이다.
- **PDF 는 코드서빙 이미지에 전처리기 패키지(`genon.preprocessor`)가 들어가야 동작한다.**
  코드는 끝났고 호출 규약은 경계 스텁으로 검증했다 — 실제 변환기로 돌려보는 것만 남았다
  (인프라에 패키지 포함 여부 확인 필요).
- 값 수정 경로는 **둘 다 `feat/sfr006-template-pipeline` 에 병합했다** (2026-08-05).
  대화 수정(`clears`)과 화면 직접 수정(`PATCH/DELETE /values`)은 서로 다른 층이고
  보완재라, 어느 쪽을 노출할지는 UI 가 정한다 — 백엔드를 나누면 사본 드리프트만 늘어난다.
  `feat/sfr006-direct-edit`·`feat/sfr006-chat-edit` 은 병합 이력용으로만 남아 있다.
- 반복 블록(contents 배열)이 필요해지면 `hwpx.py` → `hwpx_fields.py` 이식.

**SFR-018 내보내기 — 브랜치 폐기(2026-08-07), 태그로만 보존**
- **글다듬이(`onprem/SFR-018_text_polish`)는 main 에서 기능적으로 완결**돼 있다. 입력 정규화 →
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
- `glossary_exact.py` 를 `onprem/SFR-018_translation` 에 병합했고, 적재는 볼륨 파일
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
  (run 분할 토큰 포함)·mimetype STORED·템플릿 파일 부재 시 501.
- **미검증**: LLM 실호출, Redis 실연결, FastAPI 엔드포인트 HTTP 실행(로컬 미설치),
  **생성한 hwpx 를 한/글에서 열어보기**, weasyprint PDF(한글 폰트 포함).
- ~~선결 과제: FAQ hwpx 템플릿 실물이 없다~~ — **해소(2026-08-07).** 기본 템플릿을
  배포 단위에 번들했고(`faq/assets/faq_template.hwpx`), 그걸로 3건짜리 문서를 만들어
  `data/FAQ_결과.hwpx` 와 대조했다: 본문 문자열 일치, 잔존 토큰 0, XML escape 정상
  (`&`·`<b>`), mimetype STORED, zip 엔트리 13/13, 생성 XML 재파싱 통과.
  **한/글에서 실제로 열어본 것은 여전히 아니다** — 뼈대가 한/글이 만든 파일이라
  header.xml 은 진짜지만, 최종 확인은 남아 있다.
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
