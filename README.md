# genon — GenOS 폐쇄망 문서 자동화

사내 **GenOS** 플랫폼에 올리는 문서 자동화 기능 **4종**의 프로덕션 코드와, 그것을 실제로
배포·검증하기 위한 계약 점검 도구를 담은 저장소.

| | |
|---|---|
| **현행 구현** | 018 세 기능 코드서빙 [`no_pythonstep/`](no_pythonstep/) (젠포탈 `POST /chat` 직접 호출) · 나머지 [`final/`](final/) (006 코드서빙·MCP·워크플로우·전처리기) |
| **등록** | 코드 서빙 4 + MCP 2(+선택) + 전처리기 + 006 캔버스 스텝 3 — [ONPREM §1](final/docs/ONPREM.md) |
| **자동 검증** | 점검 17개 **1,168건** + unittest **521건** — `python Test/run_all.py` |
| **이관 문서** | [`final/docs/ONPREM.md`](final/docs/ONPREM.md) — **이 하나로 이관이 된다** (무엇을 등록하나·핵심 파일·환경변수·검증 상태) |
| **막힌 것** | 젠포탈 화면·LLM 게이트웨이·Redis·한/글 **실물이 있어야 확인되는 것** ([ONPREM §9](final/docs/ONPREM.md)) |

---

## 기능 4종

| SFR | 기능 | 하는 일 | 핵심 계약 |
|---|---|---|---|
| **006** | HWPX 템플릿 채우기 | 대화로 값을 모아 사내 hwpx 양식의 **중괄호 슬롯**을 채우고 **hwpx** 로 내려준다 | 중괄호 **밖은 원문 그대로**. 서식은 LLM 없이 코드가 적용 |
| **018** | 글다듬이 | 문서유형·톤 정책에 맞춰 한국어 원문을 다듬고 변경내역을 함께 낸다 | 마크다운·표 구조 **지문 대조**로 훼손 감지 |
| **018** | 번역 | 한국어 축 6개 언어. 구조를 분리해 내용만 번역하고 용어사전 준수율을 재계산한다 | **무손실 왕복** + 숫자 보존 검사 |
| **018** | FAQ 생성 | 문서에서 Q&A 를 뽑고 **근거 문장**을 함께 낸다 | 근거가 실제로 문서에 있는지 **코드가 대조**해 기각 |

네 기능 모두 공통점이 하나 있다 — **판정을 LLM 에 맡기지 않는다.** LLM 은 값 추출·문장
생성만 하고, 채워졌는가·구조가 깨졌는가·근거가 있는가는 코드가 결정적으로 판정한다.

### 018 세 기능의 산출물은 **md 하나**다

글다듬이·번역·FAQ 는 채팅에 결과를 흘리고 **md 파일** 링크(`download_url`, 폴백
`POST /download`)를 준다. 사용자가 화면에 보인 마크다운을 그대로 받아 이어 편집한다.

- **입력은 그대로다.** hwpx 직접 파싱·전처리기 마크다운·업로드 상한 전부 유지.
- **화면과 파일이 같은 마크다운이다.** 강조·표·목록·코드펜스를 떼지 않는다. FAQ 파일은
  화면과 같은 조립기로 만든다(`# 제목` + `**Q1. 질문**` / 답변 / `> 근거: …`).
- **006 은 hwpx 로 낸다.** 사내 양식을 채우는 것이 기능 자체다.
- md 는 **UTF-8 BOM + CRLF** 로 낸다. 마크다운 뷰어가 없는 윈도우 PC 에서는 메모장으로
  열리는데, 옛 메모장이 BOM 없는 UTF-8 을 cp949 로 읽어 한글을 깨뜨리고, LF 만 있는 파일을
  한 줄로 붙여 보여주기 때문이다.

## 부르는 길 (GenOS 등록 방식이 영역마다 다르다)

```
018 셋:  젠포탈 ── POST /chat ───────────────────────── 코드 서빙(03) ── LLM
                                                          │  SSE 를 직접 낸다
                                                          └─ MCP text_guard (글다듬이)

006:     사용자 ── 캔버스 워크플로우(02) ── 게이트웨이 ─┬─ 코드 서빙(03) ── LLM
                     스텝 3개 · httpx 만               └─ MCP ocr (스캔 첨부)
```

| | 02 워크플로우 | 03 코드 서빙 | 01 MCP |
|---|---|---|---|
| 등록 단위 | **파일 1개 = 스텝 1개** (006 은 3개) | 디렉토리 = 서빙 (4) | **파일 1개 = 도구 묶음** |
| 진입점 | `run(data)` | FastAPI 앱 + `$PORT` (단위 루트 `main.py`) | `@mcp.tool()` — 앱도 포트도 없다 |
| 외부 패키지 | **`httpx` 뿐** | fastapi·httpx·lxml·redis | **stdlib 만** |
| LLM 호출 | ❌ | ✅ | ❌ |

- **018 세 기능은 코드서빙 하나가 흐름을 다 쥔다** — `POST /chat` 이 `{question, stream}` 을 받아 입력
  해석(머리말 옵션·`[입력된 문서]`) · 판정 · LLM · 점검 · 업로드를 하고 SSE(`token`·`complete`·`end`)를
  직접 낸다. 계약은 [`final/docs/FRONT.md`](final/docs/FRONT.md) §1.0.
- **006 은 캔버스 스텝 3개가 흐름을 쥐고** 코드서빙이 무거운 일을 한다. `/chat` 직접 호출 판
  (`no_pythonstep/SFR-006/`)이 함께 있고, 세션 id 가 실제로 오는지 확인되면 그쪽으로 옮긴다.
- **area 05 전처리기**는 위 그림 밖이다 — 파일 단위 등록이고, hwpx 를 직접 파싱해 표가 깨지지 않게
  한다. 적재(검색)용과 첨부용은 **본문에 넣는 것이 반대**다(검색용 머리말이 LLM 입력에 섞이면 안 된다).
  후보·선택은 [`final/preprocessor/CLAUDE.md`](final/preprocessor/CLAUDE.md).

---

## 저장소 구조

| 경로 | 성격 |
|---|---|
| [**`no_pythonstep/`**](no_pythonstep/) | ⭐ **018 코드서빙 등록 대상** — `<기능>/` 이 단위 루트(`main.py`·`prompt/` 포함). 006 `/chat` 판도 여기 |
| [**`final/`**](final/) | ⭐ 006 코드서빙(`SFR-006/request` + `prompt`) · `mcp/` · `workflow/` · `preprocessor/` · `docs/`. `SFR-018-*/` 는 018 의 워크플로우 경로 판 |
| [**`Test/`**](Test/) | ⭐ **그물 전부.** `check/` 점검 17개 · `SFR-006/`·`SFR-018/` unittest · `eval/` 평가지표 MCP. **등록 코드를 직접 import 한다** (구현 사본 없음) |
| [`archive/`](archive/) | 뗀 것. `data/`(실물 hwpx — 점검이 읽는다) · `genos_files/`(벤더 참조 사본 — 점검이 읽는다) · `genos-project/`(규칙 번들) · `docs/` |

**어느 코드가 현행인가는 [`Test/check/paths.py`](Test/check/paths.py) 의 `SOURCE` 표가 정본이다** —
점검과 unittest 가 그 표를 따라 등록 코드를 태운다.

## 먼저 읽을 것

| 문서 | 답하는 질문 |
|---|---|
| [`final/docs/ONPREM.md`](final/docs/ONPREM.md) | **이관 문서 하나** — 무엇을 등록하나·핵심 파일·환경변수·무엇이 막혀 있나 |
| [`final/docs/SERVING_REGISTRY.md`](final/docs/SERVING_REGISTRY.md) | **등록 작업지시서** — 칸마다 적을 값 |
| [`final/docs/FRONT.md`](final/docs/FRONT.md) | **프론트와 주고받는 값** — 018 `/chat` · 006 캔버스 |
| [`final/docs/README.md`](final/docs/README.md) | 환경변수·로깅 규약·이관 순서의 **의미** |
| [`final/docs/FEATURES.md`](final/docs/FEATURES.md) | **무엇이 구현돼 있나** — 엔드포인트·MCP 도구·보장 |
| [`no_pythonstep/README.md`](no_pythonstep/README.md) | 018 `/chat` 작업 기록 — 단위별 확인·할 일 |
| [`CLAUDE.md`](CLAUDE.md) | **왜 그렇게 했나** — 설계 결정과 그 근거 (작업 진입 문서) |
| [`GENOS_RULES.md`](archive/genos-project/docs/GENOS_RULES.md) | GenOS 개발가이드 **강제 규칙** |

---

## 배포

```
코드 서빙 4      final/SFR-006/request/  (+ 이미지에 final/SFR-006/prompt/)
                 no_pythonstep/SFR-018-polish/ · SFR-018-translate/ · SFR-018-faq/
MCP              final/mcp/genon_text_guard.py (글다듬이 서빙) · genon_ocr.py (006 스텝 1)
                 + 선택: template_draft · pii_audit · glossary
전처리기         final/preprocessor/ — 적재용 · 첨부용 (final_preprocessor.py / high_preprocessor.py)
워크플로우 3     final/workflow/sfr006_*.py — 서빙이 아니다. 캔버스에 파일을 붙여 넣는다
018 연계         젠포탈 "워크플로우로 사용" → 코드 서빙의 POST /chat
```

- **코드 서빙 1개 = 컨테이너 1개 = URL 1개.** 빌드 `pip install -r requirements.txt`, 시작
  `uvicorn main:app --host 0.0.0.0 --port $PORT` — 네 단위 같다.
- **저장소는 1개로 간다.** 배포 단위 간 import 금지로 **의도된 사본**(hwpx 파싱 코어·`prompt_library`·
  톤 프리셋·`md_output`·로깅 유틸)이 있고, 갈렸는지는 한 커밋 안에서 동시에 읽어야 확인된다.
- **MCP 는 서빙이 아니라 파일이다.** GenOS 가 소스 파일 하나를 실행하고 `mcp` 객체를 전역
  주입한다 — FastAPI 앱·`/health`·`$PORT`·`requirements.txt` 가 전부 없다.
- **018 화면은 고른 값을 `question` 머리말(`target_lang: en` 꼴)로 붙여 보낸다.** 자연어("영어로")는
  읽지 않는다. 안 붙으면 배포 기본값 환경변수(`TRANSLATE_DEFAULT_*` 등)만 쓴다.
- 등록만으로는 안 되는 전제(006 프롬프트 동봉·Redis 공유·`TEXT_GUARD_MCP_ID`)는
  [SERVING_REGISTRY §4](final/docs/SERVING_REGISTRY.md) 에 표로 있다.

## 검증

서버·Redis·LLM 없이 전부 돈다. 가짜는 **배포 단위 밖에서** 주입한다 — 운영 코드에
테스트용 분기를 만들지 않기 위해서다.

```bash
export PYTHONIOENCODING=utf-8                # Windows 콘솔 필수 (cp949 가 '—' 에서 죽는다)
python Test/run_all.py                       # 점검 17개 + unittest 2벌 — 요약·FAIL 만 (006 = final)
python Test/run_all.py --006=no_pythonstep   # 006 도 /chat 판으로 (+ /chat 입력 해석 unittest)
python Test/run_all.py chat_direct SFR-018   # 이름 일부로 골라서
python final/verify_final.py SFR-006         # 단위 하나를 실제로 띄워 본다 (합계 밖)
```

점검별 건수와 무엇을 보는지는 [ONPREM §8](final/docs/ONPREM.md), 기준 건수는 `Test/run_all.py` 의
`EXPECTED`. **건수가 줄면 FAIL** 이다 — 실물 경로가 어긋나면 FAIL 없이 건수만 조용히 준다.
`check_high_preprocessor` 는 `docling_core` 가 없는 환경에서 hwp 17건이 빠져 FAIL 로 보인다(환경 문제).

**사본 대조 점검이 왜 있나**: 배포 단위 간 import 가 금지돼 있어 같은 규칙이 여러 벌
존재한다. 그 사본들이 실제로 갈려 있었기 때문에, 문서가 아니라 **출력으로** 대조한다.

## 알려진 공백

정직하게 적어 둔다 — [`final/docs/ONPREM.md`](final/docs/ONPREM.md) §9 가 상세하다.

- **젠포탈 화면에서 `/chat` 을 끝까지 본 적이 없다** — 머리말을 붙여 보내는지, 첨부가 `[입력된 문서]`
  뒤에 어떤 모양으로 오는지, `heartbeat`·`complete` 를 어떻게 그리는지.
- **LLM 실호출 경로 전체를 한 번도 본 적이 없다.**
- **006 `/chat` 판으로 옮기려면 대화마다 같은 세션 id 가 와야 한다** — 미확인.
- **018 `/chat` 은 스캔 쪽 OCR 표식을 받지 않는다** — 첨부 전처리기가 직접 OCR 하게 등록해야 한다.
- **빌드·시작 커맨드가 셸을 거치는지 미확인** (`cd A && B`). 안 먹으면 `--app-dir` 로 바꾼다.
- 생성한 hwpx 를 **한/글에서 열어본 적이 없다** — `check_output_safety.py` 가 파트 선언·누름틀
  안내문만 본다.
- 임베딩·LLM Judge 평가 도구는 온프레미스 서빙 가용성 확인 후 착수 — 미구현 사실이
  `metric_catalog` 의 `not_implemented` 로 노출된다.

---

# 평가지표

아래는 **지표 정의의 정본**이다. 실행 가능한 구현은 [`Test/eval/`](Test/eval/) 의
평가지표 MCP 서버이고, 기능별 묶음과 합불 기준은 `eval_mcp/suites.py` 선언 표에 있다.
eval 은 배포 단위가 아니며, **네 배포 단위를 import 하지 않는다** — 파서를 공유하면 파서
버그를 함께 놓친다.

## 평가지표 공통 원칙

평가는 **도구(evaluator) 노드의 조합**으로 구성한다 — Flowise 의 평가기처럼, 각 지표는
"무엇으로 재는가"에 해당하는 도구 타입 하나에 매핑된다. LLM 은 생성 경로에서도, 평가
경로에서도 **기본값이 아니다.**

**평가기 도구 타입**

| 태그 | 도구 | 성격 | 켜는 조건 |
| --- | --- | --- | --- |
| `Text` | 정규화 후 exact / contains / 정규식 매칭 | 결정적 | 상시 |
| `Numeric` | 수치 추출 후 임계 비교(`<`,`>`,`=`,`between`) | 결정적 | 상시 |
| `Structure` | XML·마크다운·JSON 트리/개수/지문 대조 | 결정적 | 상시 |
| `Embedding` | 고정 모델의 벡터 유사도 | 결정적(비생성) | 상시 |
| `LLM Judge` | 생성형 판정 | **비결정** | **게이트드** — 아래 규칙 |

- **결정적(`Text`/`Numeric`/`Structure`) 도구가 1차 방어선이자 운영 지표다.**
  `Embedding` 은 고정 모델의 결정적 벡터 연산이라 여기서 줄이려는 '생성 LLM 호출'과
  구분하며, 결정적 도구가 못 잡는 재서술·의미 편차의 **스크리닝** 용도로만 쓴다.
- **`LLM Judge` 는 게이트드 도구다.** 결정적·임베딩 스크리닝을 통과 못한 건에 한해,
  그것도 샘플링/opt-in 으로만 호출한다. **전건(全件) 상시 호출 금지.** 어떤 운영 지표도
  LLM Judge 를 기본 경로에 두지 않는다. `LLM Judge`·임베딩 모델을 실제로 켤 때는
  온프레미스 서빙 가용성을 먼저 확인한다.
- **참조(정답) 데이터가 필요한 지표와 아닌 지표를 구분**해 적는다 — 참조가 없으면
  측정 불가능한 지표를 운영 지표로 잡지 않는다.

## 006 평가지표 (HWPX 템플릿 채우기)

> 006 은 문서 변환이 아니라 **항목 텍스트 치환**이다. lxml 로 해당 문단·필드의 run 만
> 수정하므로 레이아웃·표 구조는 설계상 불변 → 렌더링 기반 지표(BBox IOU, TEDS)는 측정
> 수단(HWPX 렌더러)도 없고 측정할 대상도 아니라 제외. 대신 XML 레벨에서 무결성을 검증한다.
>
> 채울 자리는 두 방식이다 — 본문에 텍스트로 적힌 **슬롯**(`제 목 : {'제목', 16pt}`,
> 현장 템플릿의 실제 방식)과 **누름틀**(CLICK_HERE, 폴백). 지표는 양쪽을 같은 이름 공간의
> 항목으로 보고 계산한다. 무결성 지표에서는 **중괄호 밖이 문서 골격, 슬롯 자리가 값**이다 —
> 이렇게 나누지 않으면 채워 넣은 값이 골격 훼손으로 오판된다.

1. **필드 추출 정확도** (파이프라인의 유일한 비결정 구간 — 추출 자체는 LLM 이 하되,
   채점은 결정적 도구로 한다)
   - `Text`: 사용자 발화 → `{필드명: 값}` 추출의 필드별 precision / recall / F1
   - `Text`: 값 정확도 — 정답 값과 정규화 후 exact match, 부분 일치는 별도 집계
   - `Structure`: 환각률 — 템플릿에 없는 필드명 생성 비율(화이트리스트 기각 건수로 측정,
     이미 로그 노출됨)
2. **채움·판정 정확성** (결정적 구간 — 회귀 테스트로 검증)
   - `Structure`: 라운드트립 — 채움 → 재스캔 시 채워짐/부족 판정 일치율 100% 유지
   - `Structure`: 값이 없는 필드는 안내문 상태로 남는지(부분 초안 계약)
3. **문서 무결성**
   - `Structure`: Text recall — 원본 텍스트 누락 없음 + 원본에 없는 텍스트 추가 없음
     (필드 값 제외 영역은 XML 트리 비교로 판정)
   - `Structure`: 개체 수 일치 — 이미지·표 등 타입별 개수(XML 요소 카운트)
   - 수동: 산출 hwpx 가 한/글에서 정상 열림 — 실제 한/글 템플릿 확보 후 스팟체크
4. **E2E 멀티턴 시나리오**
   - `Numeric`: 시나리오별 최종 완성 성공률, 완성까지 턴 수
   - `Structure`: 세션 누적 정확성 — 이전 턴 값 유실·덮어쓰기 오류 없음

## 018 평가지표 (글다듬이 / 번역 / FAQ)

### 공통 — 구조 보존 (이 저장소의 핵심 계약)

- **번역** `Structure`: 스켈레톤 분리·재조립이 구조를 보장하므로, 지표는 **재조립 실패·
  세그먼트 수 불일치로 인한 fallback 발생률**(0 에 수렴해야 함).
  분모·분자는 번역 응답의 `stats.fallback_rate` 로 직접 나온다
- **글다듬이** `Structure`: `markdown_structure_issues`(MCP `genon_text_guard`) 지문 대조
  **통과율** (마크다운/HTML 표 행·셀, 제목, 코드펜스 훼손 감지)

### 1. 톤 적합성 (글다듬이) — LLM 미사용

- `Text`: 어미·조사 처리, 축약·관용 표현(문서유형×톤 프리셋 대비) — 규칙 기반 검사
- `Text`: 어미(~다/~했습니다) 문서 초반·후반 일관성 검사
- `Numeric`(참고용): 문장 길이·품사 비율(PosTagging) — 문서별 편차가 커서 합불 기준
  아님, 추세 관찰용으로만
- 톤은 위 결정적 도구로 합불한다. 주관적 편차가 커서 `LLM Judge` 를 상시로 붙일 실익이
  낮다 — 필요 시 수동 스팟체크로 대체하고, 자동 LLM 판정은 붙이지 않는다.

### 2. 의미·사실 보존성 (글다듬이·번역 공통)

- `Text`/`Numeric`(1차 방어선·운영 지표): 숫자·날짜·단위·고유명사(NER) 추출 후
  원문·결과 교차 대조, 불일치 시 감점
- **이 지표는 운영에도 같은 정의로 들어가 있다** — MCP `fact_issues`·`numeric_issues`,
  번역 `numeric_guard`, 006 `value_guard`. 지표만 재고 운영이 안 재면 "평가는 통과인데
  운영은 깨진" 상태가 생긴다. 다만 운영 가드는 **숫자·날짜만** 본다: 단위·고유명사는
  띄어쓰기 교정(`1,250만원`→`1,250만 원`)과 조사 변화에 흔들려, 매 결과에 붙는 경고로는
  오탐 비용이 크다. 지표는 넷 다 재고, 운영은 결정적으로 안전한 둘만 막는다.
- `Embedding`(스크리닝): 결정적 검사로 못 거르는 재서술 수준 누락·왜곡을 유사도로 1차
  스크리닝
- `LLM Judge`(게이트드): 임베딩 임계 미달 건만 NLI 판정으로 샘플링 확인 — 전건 아님, opt-in
- 역번역 검증은 제외 — 오류 원인(번역 vs 역번역) 분리 불가, 비용 2배 대비 판별력 낮음

### 3. 번역 품질

- **참조 번역이 있는 테스트셋** `Numeric`: chrF(우선, 한국어에 BLEU 보다 안정적) + BERTScore
- **참조가 없는 운영 입력** `Embedding`: 다국어 임베딩 원문·번역본 유사도를 기본 운영
  지표로 사용
- `LLM Judge`(게이트드): 위 유사도 하위 구간만 샘플링 확인 — 전건 아님, opt-in
- **용어집 준수율** `Text`: 용어집 원문 용어 등장 시 지정 번역어 사용 비율(결정적 검사).
  번역 응답의 `glossary.compliance` 로 직접 나오므로 eval 이 다시 계산하지 않아도 된다

### 4. FAQ 원천 정합성 (근거성)

- `Text`(1차 스크리닝): 답변 문장별 원천 문서와의 n-gram 중복·자카드
- `Embedding`(1차 스크리닝): 답변 문장 ↔ 원천 문서 임베딩 유사도
- `LLM Judge`(게이트드): 위 두 스크리닝 점수가 낮은(근거 없어 보이는) 문장에만 확인.
  전체 답변을 매번 LLM 으로 채점하지 않는다.
- 주의: 어휘 중복·임베딩 유사도가 낮다고 곧장 오답은 아니다(재서술 가능성) — 그래서
  LLM 확인을 게이트로 붙이되, 스크리닝 통과분에는 생략한다.
- **운영 쪽(`faq/evidence.py`)은 이 1차 스크리닝을 이미 구현했다.** eval 에 붙일 때 같은
  판정을 쓰되 **import 하지 말고 각자 구현한다** — eval 이 배포 단위를 import 하지 않는
  규칙과 같은 이유다. `suites.py` 에 FAQ 스위트는 아직 없다.
