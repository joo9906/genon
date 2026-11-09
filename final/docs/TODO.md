# 앞으로 할 일

## 0. 이어받기 — 2026-11-06 세션 끝 상태 (먼저 읽는다)

**번역(SFR-018-translate) + 용어사전 MCP 는 동결 해제**(2026-11-06 사용자). 나머지 기능은 동결 그대로.
**전부 커밋 전이다** — `git status` 의 번역·용어사전·문서·Test 변경 + 새 `cos/` · `1106.zip` · 이 파일.

### 이번 세션에 한 것
- 코드(번역 서빙 `glossary_exact.py` · `prompt_builder.py` · `glossary_report.py` + MCP `genon_glossary.py` 같이):
  다중 후보(11-06 오전) · 숫자 독립 토큰 · 영어 `-ed/-ing` 어간 · 한국어 `-하다/-되다` 활용 어미 목록 · 조사 `나` ·
  대소문자만 다른 원문 한 묶음. 세 판정 함수는 `_seq_eq` 하나. 그물 SFR-018 **427** · `check_mcp_tools` **109**,
  `run_all.py` 20/21(남은 FAIL `check_high_preprocessor` = 이 PC 에 docling_core 없음, 기준선과 같음)
- 데이터 `한영_금융용어집_업로드_축소.xlsx`(루트, **GenOS 에 아직 안 올림**): 213 → 미국 제도 53 제외 160 →
  `제외 내역`에서 되살려 **600 대표어**(`되살림 내역` 시트 등급 1·2) → 실측 후 손질(`원금` 제외, 금리 표기, `자동이체` 영어 등).
  대표어 중복 0, 자기 매칭 누락 0. 바꾼 것 `표기 변경` 시트, 뺀 것 `제외 내역` 시트
- 실측(LLM 대역): 영→한 준수율 0.62 → 0.90, 한→영 0.88 → 0.89, 오매칭 없음
- `cos/` — 코드스페이스용 실측 실행기(`run_translation_glossary.py`) + 데이터셋 10건(`dataset/`, `expect.json`) + README.
  번역 서빙을 사본 없이 import, 실제 LLM · 용어사전 API 직접 호출, 사전 적용/미적용 두 회차, `<mark>` 번역문 · 준수율 출력.
  가짜 LLM · 죽은 주소로 배선 확인함. **실제 LLM 으로는 아직 안 돌렸다**
- `1106.zip`(루트) = `cos/` + `final/SFR-018-translate/` + 번역 스텝 2 + MCP 4(glossary · lang_policy · text_guard · ocr).
  빈 폴더에 풀어 실행 확인. `10.168.31.100` 은 저장소 어디에도 없다(주소는 전부 환경변수 또는 `genos.genon.ai` 기본값)

- `cos/load/load_test.py` — 젠포탈 `/api/genportal/chat` 부하 테스트(**번역 · 글다듬이**, 26명 동시, 합격 = 모든 요청
  첫 토큰 10초 이내 + 성공). payload 는 `cos/load/scenarios.json` 템플릿, 입력은 `cos/load/messages/*.txt` + `cos/dataset`.
  가짜 SSE 서버로 동작 확인(ping 제외 · 11초 FAIL · error 본문 감지). **실제 젠포탈 응답 형식은 모른다** —
  첫 실행 뒤 `summary.md` 의 "첫 토큰으로 센 조각" 을 보고 필요하면 `--token-pattern`. FAQ · 템플릿은 나중에(사용자)

### 다음에 할 것 (순서대로)
1. **600개 용어집을 GenOS `데이터 > 용어사전` 에 올린다** → `;` 동의어 저장 모양 확인(`GET /terms` 하나)
2. **코드스페이스에서 `python cos/run_translation_glossary.py`** → 실제 LLM 준수율 · 사전 효과(적용 − 미적용) · 동형어 함정 확인
3. 결과로 사전 손질 — 이미 보이는 것: `Transfer`→양도(잔액 이체에 걸림) · `Settlement`→채무 합의(결제 뜻) ·
   `약정서`→Commitment letter · `계좌 입금`→Direct deposit · `채무조정` 영문(신용회복위원회 공식 표기 확인)
4. ~~쉼표를 건너 매칭~~ — 2026-11-09 끝: 문서의 부호는 경계, 표제어의 부호는 자리마다 선택(`401k`·Oxford 쉼표 생략도 걸림). 서빙+MCP, 그물 SFR-018 428 · mcp 111
5. 폐쇄망 반영 — 아래 "폐쇄망 배포 메모"
6. 커밋 (사용자 확인 후)
7. 남은 데이터 결정: 1-1d(띄어쓰기 변형 행 추가 · `신용 회복` 영문 · `대출 마감` 류 국내 용어) · 한국 고유 용어 보강(DSR · 전세자금대출 · 개인회생 등)
8. 1-3 ② 합성어 안쪽(`신용회복위원회` 속 `신용회복`) · ④ 동형어 플래그 속성 — 아직 안 함

### 폐쇄망 배포 메모
- 코드에 기본값으로 박힌 외부 주소는 **환경변수로 덮는다**: `TRANSLATE_GLOSSARY_API_URL`(기본 `https://genos.genon.ai/api/admin` —
  서빙 · MCP 둘 다) · `GENOS_CDN_UPLOAD_URL` · `GENOS_CDN_HOSTNAME`(서빙 `file_store.py` 기본 `genos.genon.ai`) ·
  OCR MCP `OCR_IMAGE_HOSTS`/`GENOS_CDN_HOSTNAME`. `GENOS_URL` 은 기본값이 없다(필수)
- **프롬프트 위치**: 로더는 `translation_pipeline/common/` 에서 위로 6단계까지 `prompt/SFR-018_translation` 을 찾는다.
  `request/` 만 저장소로 올리면 옆의 `prompt/` 가 빠진다 → `request/prompt/SFR-018_translation/` 으로 같이 넣거나,
  `TRANSLATION_PROMPT_DIR` 지정, 또는 `TRANSLATE_PROMPT_IDS` 로 프롬프트 라이브러리 사용. 라이브러리를 쓰면 이번에 바뀐
  `glossary_{batch,single,stream}.md` 를 라이브러리에도 반영해야 한다
- pip: `fastapi uvicorn pydantic httpx python-multipart lxml` 이 사내 mirror 에 있어야 한다.
- MCP: 이번에 바뀐 것은 `genon_glossary.py` 하나 — 나머지 셋과 번역 스텝 2 는 변경 없음(이미 등록돼 있으면 다시 안 올려도 된다)

## 1. 용어사전 — 금융 용어집을 넣으면 성능이 안 나온다 (2026-11-05 조사)

대상 데이터: 루트 `한영_금융용어집.xlsx`(CFPB 영→한 용어집 2,019건) → 금융 무관 709건을 뺀
`한영_금융용어집_금융특화.xlsx`(1,310건, 제외분은 `제외 목록` 시트). **아직 GenOS 용어사전에
올리지 않았다.** 남은 데이터 파일은 루트 `한영_금융용어집_업로드_축소.xlsx` 하나다(2026-11-06 — 앞 단계 파일 셋은 지웠다).

실측 방법: 번역 코드서빙의 실제 적재(`glossary_store._pairs_from_items` · `_index_pairs`)와
매칭(`glossary_exact.match_occurrences`)에 1,310건을 넣고, **각 용어가 자기 자신의 표기를
찾는지** 봤다.

| 지표 | 값 |
|---|---|
| 실제 적재 | 1,266건 (한국어 중복 43건이 `duplicate_ko` 로 버려진다) |
| en→ko 에서 자기 자신도 못 찾는 용어 | **278건 (22%)** |
| ko→en 에서 자기 자신도 못 찾는 용어 | **234건 (18%)** |
| 2자 이하 한국어 용어 | 96건 |

못 찾는 용어는 **프롬프트에 실리지 않고, 하이라이트도 없고, 준수율 분모에도 안 들어간다**
(`matched_count=0` → 준수율 1.0). 계기판 어디에도 이상이 안 보인다.

### 1-1. 데이터만으로 고칠 수 있는 것 (코드 동결과 무관)

| 문제 | 무엇이 터지나 | 고치는 법 |
|---|---|---|
| **한 칸에 여러 뜻** (`계좌, 계정` · `Arrears, arrearage` · `감가상각 (n.), 가치가 떨어지다 (v.)`) | 적재는 `split()` 이라 `계좌,` 가 쉼표째 한 토큰 → 원문과 영원히 안 맞는다. 준수 판정도 `"계좌, 계정"` 을 통째로 찾아 절대 준수가 안 된다 | **한 행 = 한국어 하나 · 영어 하나**로 나눈다. 단 en→ko 는 1-2 의 ① 때문에 첫 행만 걸린다 |
| **괄호·약어** (`Adjustable-rate mortgage (ARM)` · `자금세탁방지(AML)` · `APR(연이율)`) | `(arm)` 이 한 토큰 → 안 걸린다 | 괄호를 떼고 정식 명칭만 남긴다. 약어를 별도 행으로 두면 **한국어가 같아 `duplicate_ko` 로 버려진다**(1-2 ②) |
| **`[문맥에 따라 선택]` 비고 · `(as in: …)` 설명** | 표기에 섞이면 안 걸린다 | 비고 열은 올리지 않는다. 설명 괄호는 뗀다 |
| **같은 한국어가 여러 영어에** (`수수료`→Commission/Fee · `유예`→Deferment/Forbearance · `채무자`→Borrower/Debtor · `감정`·`압류` 등 43건) | 처음 것만 남아 **ko→en 이 엉뚱한 영어로 고정**된다 (`수수료`→항상 Commission) | 남길 영어를 사람이 정한다. 1-2 를 고치기 전까지는 한 한국어에 한 영어 |
| **하이픈·숫자** (`Auto-pay` · `Back-end ratio` · `제3자` · `1차 주택담보대출` · `401(k)`) | 1-2 ③의 코드 결함 때문에 안 걸린다 | 코드를 고치기 전 우회: 하이픈 → 공백(`Auto pay`). 숫자 낀 용어는 빼거나 숫자 없이 쓴다 |
| **2자 이하 다의 한국어** (`감정` · `연기` · `보장` · `이전` · `전환`) | ko→en 에서 금융 아닌 뜻(감정=emotion)에도 걸려 **틀린 영어를 강제**한다 | 다의어는 빼거나 더 긴 표제어로 바꾼다(`감정`→`감정평가`) |
| **사전 없이도 같게 번역되는 기초어** (Bank · Loan · Cash · Tax · Payment …) | 해는 적지만 매 문서 걸려 프롬프트·하이라이트만 늘린다 | 1-2 를 고치면 그대로 둬도 된다. 안 고치면 뺀다 |
| **빈 번역** (`Ghost mortgage, silent second mortgage`) · **오역** (`Cash to close`→"마감마감에 필요한 현금", `FHA insurance`→"보험 FHA", `Escrow`→"조건부 날인") | 빈 값은 `en_empty` 로 버려진다. 오역은 그대로 강제된다 | 사람이 검수한다 (2026-11-05 사용자 결정: 일단 둔다) |

다 고친 뒤 **같은 자기 매칭 시험을 다시 돌려 0건인지** 확인하고 올린다.

### 진행 상황 (세션이 끊기면 여기서 이어 간다)

- [x] **1-1b 첫 줄(동형어) — 번역 단위에서만 프롬프트로 막는다** (2026-11-05 사용자 지시, 이 건에 한해 동결 해제).
  번역 프롬프트 `final/SFR-018-translate/prompt/SFR-018_translation/glossary_{batch,single,stream}.md`
  를 "**사전의 뜻(금융 의미)으로 쓰였을 때만** 따른다, 일반 의미면 문맥대로 번역" 으로 바꿨다.
  MCP · 다른 단위는 손대지 않았다. `run_all.py` 는 프롬프트 렌더 112/112 · SFR-018 412/412 통과
  (같은 실행의 `check_high_preprocessor` 83/100 은 이 PC 에 `docling_core` 가 없어 hwp 점검이
  건너뛴 것 — 무관).
  배포 시: `TRANSLATE_PROMPT_IDS` 에 `glossary_batch`·`glossary_single`·`glossary_stream` ID 를
  건 배포만 라이브러리 쪽도 같이 바꿔야 한다(문서 예시 `system_batch=44,user_batch=45` 는 해당 없음).
  남는 한계: 일반 의미로 옮긴 자리는 준수율에서 미적용으로 잡힌다.

- [x] **1-1 데이터 정리 — `한영_금융용어집_금융특화.xlsx` 의 `적재용` 시트** (2026-11-06).
  1,310행 → **1,494행**(한 행 = 영어 하나 · 한국어 하나), 버린 31행은 `적재 제외` 시트(숫자 20 · 동사구뿐 11).
  사용자 결정: 같은 한국어에 영어가 여럿이어도(`수수료`→Commission / Fee) **행을 다 남기고 LLM 이 고르게** 한다.
  규칙: 쉼표·`;`·` / ` 로 나눔(양쪽 개수가 같으면 자리별 짝, 아니면 모든 조합) · 낱말 안 `/` 는 펼침 ·
  끝에 붙은 괄호 약어는 머리글자가 맞을 때만 별도 행 · 설명 괄호·`[v.]` 제거 · `of 1977`/`1977년` 제거 ·
  표기를 원문 토큰화(`_TOKEN_RE`)로 다시 씀(하이픈·아포스트로피 → 공백) · `~하다/되다/된` → 명사형 ·
  `마감마감`·`주택주택` 오타 · `Research, Markets, and Regulations` 같은 나열 이름은 안 나눔.
  시트의 `후보` 열에 같은 영어/한국어 후보 수와 일반어 동형 약어(ARM·PIN·TIP 등)를 표시했다.
  자기 매칭(실제 적재·매칭 코드): **ko→en 0건 · en→ko 11건**(영어 7낱말 이상 — 색인 상한, 표시함).
  **지금 코드로 올리면** 같은 한국어 191행이 `duplicate_ko` 로 버려지고, en→ko 는 67행이 첫 후보에 가려진다
  → "LLM 이 고르게" 는 1-2 ①②④⑤ 를 고쳐야 동작한다. 생성 스크립트는 세션 scratchpad 에만 있다.
- [x] **1-1c 도메인 특화만 남기기 — 루트 `한영_금융용어집_업로드_축소.xlsx`** (2026-11-06).
  기존 사전 300건과 합쳐 프롬프트가 길어지는 문제로 `한영_금융용어집_업로드.xlsx`(1,254행)를 **213행**으로 줄였다.
  뺀 1,041행과 사유는 `제외 내역` 시트(일상어·풀어쓴 표현 795 · 미국 고유 기관·법령·제도 195 · 같은 영어 중복 18 ·
  오역 16 · 형용사형 11 · 짧은 다의어 6 — `채권`·`결제`·`증서`·`귀속`·`침해`·`약정`), 표기 바꾼 26행은 `표기 변경` 시트
  (`조건부 날인`→`에스크로`, `선납 벌금`→`중도상환수수료`, `Note;Promissory note`→`Promissory note` 등).
  남긴 기준: 사전 없이는 LLM 이 틀리거나 흔들리는 용어(기한이익 상실·차환·역상각·깡통주택), 신용회복·채무조정 핵심어.
- [ ] **1-1d 데이터 손질 — `한영_금융용어집_업로드_축소.xlsx`** (2026-11-06 사용자 결정, 코드 아님).
  - **띄어쓰기만 다른 표기는 행을 따로 추가한다**(코드에서 공백 무시 비교는 하지 않기로 함). 붙여 쓴 행을
    **위에** 둔다 — 지금 코드는 en→ko 에서 같은 영어의 첫 행이 이긴다. 대상(우선): `신용 회복`·`신용 조회`·
    `신용 상담`·`신용 점수`·`신용 보고서`·`신용 조합`·`신용 이용`·`파산 면책`·`원금 탕감`·`원금 유예`·`채무 구제`·
    `채무 탕감`·`상환 능력`·`대출 관리`·`금리 조정일`. 합성어 안쪽(`신용회복위원회` 속 `신용회복`)은 행으로도 못 잡는다.
  - [x] 같은 영어가 두 행에 걸린 것 정리(`채무`-Encumbrance · `소유권 이전`-Transfer · `탕감`-Write off · `압류`-Impound) — 2026-11-06
  - 사용자가 정할 것: `채무조정`↔`Debt settlement`(기관 공식 영문 표기 확인) · `신용 회복`↔`Credit repair`
    (`Credit recovery`?) · `대출 마감`/`마감 비용`/`대출 개시`(국내 용어: 대출 실행·부대비용·대출 취급) ·
    `체납`의 `Late payment`(대출은 `연체`).
  - 참고: 1-2 ① 을 고치면 같은 영어의 행이 en→ko **후보로 함께** 실린다(`"Credit recovery" -> "신용회복" / "신용 회복"`).
    해는 없고 프롬프트 한 줄이 길어질 뿐이다.
- [x] **1-2 코드 수정 — 2026-11-06 사용자 지시로 착수 확정. 범위는 번역 코드서빙 + MCP 사본(MCP 는 같은 날 오후 착수 — 아래 "2. MCP" 진행).**
  계획은 아래 "1-2 작업 계획" 절. **2026-11-06 구현 완료(커밋 전).** 기준선 FAIL 1건은 `check_high_preprocessor`(docling_core 부재 — 무관).
  - [x] 코드: ②⑥ `glossary_store`(`_texts`·`duplicate_pair`·`_index_pairs` 두 방향) · ③ `load_terms` `_TOKEN_RE` 토큰화
    (**숫자 든 표제어는 싣지 않고 `skipped_digit` 로 센다** — 토큰화하면 숫자가 사라져 `1차`가 `2차`에도 걸리므로) ·
    ① `match_occurrences`·`exact_match`·`terms_for_batch` · ④ `prompt_builder` + 프롬프트 3벌 ·
    ⑤ `glossary_report`(`group_occurrences`·`judge_term`·`term_hit`·`unapplied_label`) — `stream_pipeline` 도 같은 함수를 부른다
  - [x] 테스트 +11(`GlossaryAdminApiLoadTest` +3 · `MultiCandidateTest` 6 · `TermTokenizationTest` 2, 기존 중복 테스트는 새 규칙으로) ·
    `EXPECTED` SFR-018 412→423 · `run_all.py` 20/21(기준선과 같음)
  - [x] 문서: `final/CLAUDE.md` · 루트 `CLAUDE.md`(MCP 갈림 · 건수) · `docs/README.md` · `diff.md` · `ARCHITECTURE.md` · `FEATURES.md` ·
    `DESIGN_NOTES.md` · `mcp/README.md` · `genon_glossary.py` 머리 주석(갈림만 — 동작 무변경)
  - [x] eval `glossary_compliance` 는 이미 `any(허용어)` — 같은 규칙, 고칠 것 없음
  - [x] 자기 매칭 재시험 — `한영_금융용어집_업로드_축소.xlsx` 213행 → (한국어, 영어) 269쌍(`;` 동의어 포함):
    **ko→en 0 · en→ko 0 누락**, 거른 행 0, en→ko 다중 후보 8쌍. 같은 시험을 옛 코드로 돌리면 ko→en 101 · en→ko 102 누락
    (`;` 를 통째 한 표기로 읽어서). (`금융특화.xlsx` 적재용 시트는 지워져 계획의 67·191 대조는 못 했다.)
  - [ ] **남은 확인(데이터 쪽)**: "0. 착수 전에 확인할 것" 셋 — GenOS 에 같은 대표어 중복 등록 가능한가(**불가** — 2026-11-06 확인, 후보 여럿은 `;` 로 싣는다) · 213행 실제 업로드 ·
    `;` 동의어 저장 모양. 코드는 `text[]` · `;` 문자열 · 같은 한국어 여러 행을 **모두** 받으므로 어느 답이어도 코드를 바꿀 일은 없다.

### 1-1b. 걸리긴 하는데 **틀리게** 걸리는 것 (실측 2026-11-05)

1-1 은 "안 걸리는" 문제고, 이쪽은 걸려서 해가 되거나 맞게 번역했는데 미준수로 잡히는 문제다.

| 문제 | 실측 | 무엇이 터지나 | 고치는 법 |
|---|---|---|---|
| **영어 일반어와 같은 철자의 금융 용어** (Note · Check · Title · Index · Closing · Default · Principal · Capital · Margin · Bill · Interest · Balance · Charge · Float · Point · Offer · Value · Cap) | `Note: check the title and index … Default settings` → **어음·수표·소유권·지수·마감·채무불이행** 6건이 "반드시 따른다" 로 실린다. `The principal reason is the capital city` → 원금·자본 | en→ko 에서 금융 아닌 문서·문장도 **오역을 강제**한다. 하이라이트까지 붙어 맞는 것처럼 보인다 | 데이터: 단일어 동형어는 빼고 복합어(`Promissory note`·`Principal balance`)만 남긴다. 코드(1-2 ④): 프롬프트에 "**금융 의미로 쓰였을 때만** 적용" |
| **한국어 띄어쓰기 차이** (한국어 표제어 846건이 띄어 씀) | `신용조회 결과` → 사전의 `신용 조회` 와 **안 맞는다**. `주택담보대출금리가` → `주택담보대출` 안 걸림(합성어) | ko→en 에서 실제 문서의 붙여 쓴 표기를 대부분 놓친다 | 데이터: 붙여 쓴 표기를 별도 행으로 추가. 코드: 한국어는 공백 무시 비교. 합성어 안쪽 일치는 형태소 분석 없이는 한계(문서화) |
| **동사·형용사형 표제어** (`상환하다` · `자본화하다` · `연체된` · `공제 가능한` 36건, 영어 `Amortize` · `Refinance` 등) | `대출을 상환해야` ⊅ `상환하다`, `amortized` ⊅ `Amortize`, `refinanced` ⊅ `Refinance` — 셋 다 **False** | 맞게 번역해도 **미준수**로 잡혀 준수율이 떨어진다. 하이라이트도 빠진다 | 데이터: 명사형으로 바꾼다(`상환하다`→`상환`, `연체된`→`연체`). 코드: 영어 정규화에 `-ed`·`-ing` 규칙(과교정 주의) |
| **조사 과절단** | `자산가 고객` → `자산`(Asset) 으로 걸린다 (`가` 를 조사로 뗌). `감정이 상했고` → `감정`(Appraisal) | ko→en 오매칭. 짧은 표제어일수록 잦다 | 2자 표제어를 줄이는 것이 최선(1-1 2자 이하 다의어 항목) |
| **6낱말 초과 표제어** | 한국어 27건 · 영어 1건이 `skipped_long` 으로 **색인에서 빠진다** (로그에 건수만) | 그 용어는 없는 것과 같다 | 데이터: 6낱말 이하로 줄이거나 뺀다 |
| **표제어 자체의 오타** (`Closing`→"마감마감", `Cash to close`→"마감마감에 필요한 현금") | 그대로 프롬프트에 강제된다 | 번역문에 "마감마감" 이 나간다 | 데이터 검수 (오역 검수와 함께) |

### 1-2. 코드를 고쳐야 하는 것 (기능 코드 동결 — 착수는 사용자 결정)

방향(2026-11-05 사용자 의견, 동의함): **다의어는 행을 나눠 후보를 전부 싣고 LLM 이 문맥으로
고르게 한다.** 지금 코드는 "하나를 강제" 구조라 행을 나눠도 그렇게 동작하지 않는다(실측).

| # | 자리 | 지금 동작 | 터지는 것 | 고칠 방향 |
|---|---|---|---|---|
| ① | `glossary_exact.match_occurrences` (L362 `for … in bucket` → `break`) | 같은 원문의 후보가 여럿이면 **첫 후보에서 멈춘다** | `Account→계좌`·`Account→계정` 두 행을 넣어도 en→ko 는 **계좌만** 나온다. 계정은 프롬프트에 한 번도 안 실린다 | 같은 길이·같은 원문 후보를 **모두** 모은다 (`exact_match` 의 중복 제거 키도 `(source, target)` 으로) |
| ② | `glossary_store._pairs_from_items` | 한국어(casefold)가 같으면 처음 것만 남긴다 (`duplicate_ko`) | 약어 행(`ARM`)·동의 영어 행(`Fee`)이 적재 단계에서 사라진다 | 중복 기준을 **(한국어, 영어) 쌍**으로 바꾼다 |
| ③ | `glossary_exact.load_terms` (`term_source.split()`) vs 원문 `_TOKEN_RE` | 사전은 공백으로만, 원문은 글자 종류로 자른다 — 하이픈·숫자·괄호에서 둘이 갈린다 | `Auto-pay`·`제3자`·`1차`·`401(k)` 이 영원히 안 걸린다 | 사전 표제어도 **`_TOKEN_RE` 로 토큰화**한다(원문과 같은 규칙). 숫자를 토큰 정규식에 넣을지 함께 결정 |
| ④ | 프롬프트 `prompt/SFR-018_translation/glossary_{batch,single,stream}.md` | `[용어사전 — 반드시 따른다] … 그대로 씁니다` | 후보가 여럿이면 모순된 지시가 된다 | 한 원문에 후보가 여럿이면 `"Account" -> "계좌" / "계정"` 으로 묶고 "**후보 중 문맥에 맞는 것을 쓴다**" 로 바꾼다. 후보 하나면 지금처럼 강제 (`prompt_builder.glossary_entries` 가 묶는다) |
| ⑤ | `office/glossary_report.build_report` (L257 `contains_phrase(translated, term_target)`) · `term_map` | 후보 하나씩 따로 판정, `term_map` 은 `{원문: 번역}` dict | LLM 이 `계정` 을 고르면 `계좌` 후보가 **미준수**로 잡혀 준수율이 떨어진다. `term_map` 은 키 충돌로 하나만 남는다 | 같은 원문의 후보를 묶어 **하나라도 썼으면 준수**. `term_map` 값은 실제로 쓴 후보. hits 는 (원문×유닛) 하나 유지(분모 불변) |
| ⑥ | MCP 사본 `final/mcp/genon_glossary.py` | 위 ①②③ 과 같은 코드 (L307 `split()`, `duplicate_ko` L569, 버킷 `break`) | 한쪽만 고치면 같은 질문에 다른 답 | **같이 고친다** (루트 CLAUDE.md "사본은 함께 고친다") |

함께 할 것:
- 그물: `Test/SFR-018/tests/test_glossary_policy.py` 에 ①~⑤ 각 1건 이상 (다의어 두 행 → 두 후보 모두 프롬프트에, 약어 행 적재, 하이픈·숫자 매칭, 후보 중 하나 사용 시 준수). 늘린 만큼 `Test/run_all.py` 의 `EXPECTED` 수정.
- eval: `Test/eval/eval_mcp` 의 `glossary_compliance` 가 같은 "하나라도 쓰면 준수" 규칙인지 확인.
- 문서: `final/CLAUDE.md` 용어사전 절 · `final/docs/README.md` 하이라이트 계약(`term_map` 의미) 갱신.
- 성능: 후보가 늘어도 역색인 구조라 스캔 비용은 그대로다. 프롬프트 길이만 늘어난다.

### 1-2 작업 계획 (2026-11-06 작성 — 구현은 다음 세션)

**목표**: 한 원문에 후보가 여럿이면(`Account`→계좌/계정, `수수료`→Commission/Fee) **전부 프롬프트에
싣고 LLM 이 문맥으로 고르게** 한다. 후보 중 **하나라도 쓰면 준수**다. 후보가 하나면 지금과 똑같이 동작한다.

#### 0. 착수 전에 확인할 것 (막히면 설계가 바뀐다)

- **GenOS `데이터 > 용어사전` 에 같은 한국어(대표어/`ko`)를 두 번 등록할 수 있는가.** 안 되면 ko→en
  다중 후보는 행 나누기로 못 싣는다. 그때는 대안 — `en` 속성이 `text[]` 이면 지금은 **첫 값만** 읽는데
  (`diff.md` 표), **값 전부를 후보로** 읽게 바꾼다(`_text` 사본 두 벌). 두 방식을 다 받게 해 두는 것이 안전하다.
- 축소본 213행(+1-1d 추가 행)을 실제로 올릴 수 있는지(건수·속성 이름 `ko`/`en`).
- **업로드한 `en` 의 `;` 동의어가 GenOS 에 어떤 모양으로 저장되는가** — `text[]` 목록인지, `;` 가 든 문자열 하나인지.
  `GET /terms` 응답 하나만 보면 된다. 로컬 `C:/Users/jooyoung/Desktop/Code/GenOS` 사본에는 속성 기반 용어사전 코드가
  없어 확인하지 못했다. 지금 `_text()` 는 목록이면 **첫 값만**, 문자열이면 통째로 쓴다 → 축소본 45행의 뒤쪽 동의어
  (`ARM`·`AML`·`CBDC` 등)가 지금은 안 걸리고, 문자열로 저장되면 그 행 전체가 안 걸린다(`mortgage;arm` 이 한 토큰).
- 착수 직전 기준선: `python Test/run_all.py` 2026-11-06 실행 **20/21 통과**(SFR-018 412/412 · 프롬프트 렌더 112/112).
  FAIL 1건이 어느 점검인지는 아직 안 봤다 — 착수 전에 먼저 확인해 이번 수정과 무관한지 가른다.

#### 1. 번역 코드서빙 (`final/SFR-018-translate/request/translation_pipeline/`)

| # | 파일 · 자리 | 바꿀 내용 |
|---|---|---|
| ② | `common/glossary_store.py` `_pairs_from_items` (L160–179) | 중복 키를 `ko.casefold()` → **`(ko.casefold(), en.casefold())`**. 사유 코드 `duplicate_ko` → `duplicate_pair`. 독스트링 "같은 한국어는 처음 것만" 수정 |
| ③ | `common/glossary_exact.py` `load_terms` (L206 `term.term_source.split()`) | **`_TOKEN_RE.findall(term.term_source)`** 로 토큰화 — 원문 스캔과 같은 규칙. 하이픈·아포스트로피·괄호 표기가 걸린다. 숫자는 지금처럼 토큰이 아니다(숫자 포함 용어는 계속 안 걸린다 — 문서화만) |
| ① | `common/glossary_exact.py` `match_occurrences` (L361–378) | 첫 후보에서 `break` 하지 말고, 처음 맞은 후보와 **`normalized_words` 가 같은 후보를 전부** 같은 구간으로 `occurrences` 에 넣는다(버킷은 길이 내림차순 정렬이라 같은 길이가 이어져 있다 — 길이가 줄면 멈춘다). 최장 일치 · 구간 건너뛰기는 그대로 |
| ① | 같은 파일 `exact_match` (L403–408) | 중복 제거 키 `term_source` → **`(term_source, term_target)`** |
| ① | `office/glossary_report.py` `terms_for_batch` (L115–121) | 같은 수정 — 키를 `(term_source, term_target)` |
| ④ | `common/prompt_builder.py` `glossary_entries` · `_glossary_block` (L30–55) | `term_source` 로 묶어 **한 줄에 후보를 ` / ` 로** 싣는다: `- "Account" -> "계좌" / "계정"`. 후보 하나면 지금 줄 모양 그대로. 순서는 적재 순서(결정적) |
| ④ | `prompt/SFR-018_translation/glossary_{batch,single,stream}.md` | 한 줄 추가: "후보가 ` / ` 로 여럿 적힌 용어는 문맥에 맞는 **하나를 골라** 그대로 씁니다." (1-1b 의 "사전의 뜻일 때만" 문구는 유지) |
| ⑤ | `office/glossary_report.py` `build_report` (L245–285) | `target_by_term` 을 **후보 목록**으로(`setdefault(..., []).append`, 중복 제외). 같은 등장이 후보 수만큼 들어오므로 `spans` 는 **중복 제거**. `applied = any(contains_phrase(translated, t) for t in 후보)`. `hits[].term_target` = **실제로 쓴 후보**(여럿 썼으면 첫 것, 안 썼으면 첫 후보), 새 키 **`term_targets`** = 후보 전부. `target_spans` = 쓴 후보 전부의 `phrase_positions` 합(겹침은 하이라이트가 이미 병합한다). `term_map[원문]` = 쓴 후보, `term_map_unapplied[원문]` = 후보를 ` / ` 로 이은 문자열. **hits 는 (원문×유닛) 하나 유지** → `matched_count` 분모 불변 |
| ⑤ | `office/stream_pipeline.py` `build_document_glossary` (L443–470) | **`build_report` 와 같은 규칙**으로 같이 고친다(문서 좌표판 사본 — 갈리면 같은 문서가 경로마다 다른 준수율을 낸다). 공통 판정을 작은 함수 하나(`_judge_term(translated, 후보) -> (applied, used, target_spans)`)로 빼 두 곳이 부르게 하면 갈릴 일이 없다 |

#### 1-⑥. `;` 동의어 · `text[]` 값 전부 읽기 (2026-11-06 추가 — 위 0 의 확인 결과에 맞춘다)

| # | 파일 · 자리 | 바꿀 내용 |
|---|---|---|
| ⑥ | `common/glossary_store.py` `_text` (L153) | `_texts(value) -> list[str]` 로 바꾼다 — 목록이면 비어 있지 않은 값 **전부**, 문자열이면 `;` 로 나눠 전부(앞뒤 공백 제거·빈 값 제외·순서 유지·중복 제거) |
| ⑥ | 같은 파일 `_pairs_from_items` (L160) | 한 항목에서 `ko 값들 × en 값들` 쌍을 만든다. ko 가 여럿이면(대표어 + 표기 변형) **ko→en 은 각 ko 가 en 전부를 후보로**, **en→ko 는 첫 ko(대표어)만** 후보로 — 표기 변형이 번역 출력 후보가 되면 안 된다. 그래서 반환을 `(ko 목록, en 목록)` 항목으로 바꾸고 `_index_pairs` 가 두 방향을 따로 만든다. 걸러진 사유 집계는 그대로(빈 값·`duplicate_pair`) |
| ⑥ | `Test/SFR-018/tests/test_glossary_policy.py` `GlossaryAdminApiLoadTest` | `text[]` 두 값 · `;` 문자열 두 값이 각각 두 후보로 적재되는지, en→ko 가 대표어만 내는지 |

#### 2. MCP (`final/mcp/genon_glossary.py`) — **착수** (2026-11-06 오후 사용자 지시: 옛 규칙 버리고 코드서빙에 맞춘다)

사용자 확인(2026-11-06): **GenOS 에 완전히 같은 대표어는 두 번 등록할 수 없다.** → 같은 한국어의 영어 후보 여럿은
행 나누기가 아니라 **`en` 한 칸에 `;`(또는 `text[]`)** 로 싣는다. 코드는 이미 그 모양을 받는다(`_texts`).
띄어쓰기만 다른 표기(`신용회복`/`신용 회복`)는 대표어가 다르므로 행 추가가 가능하다.

진행(세션이 끊기면 여기부터):
- [x] `_GLtexts` · `_GLpairs_from_items`(`duplicate_pair`) · `_GLindex_pairs` 양방향(en→ko 는 첫 한국어만)
- [x] `glload_terms` `_GLTOKEN_RE` 토큰화 + 숫자 든 표제어 `skipped_digit`
- [x] `glexact_match` 같은 표기 후보 전부 · 키 `(원문, 번역)`
- [x] `_GLglossary_lookup` 반환 `terms` 값은 ` / ` 로 이은 문자열 + `candidates` 추가 (도구 독스트링도)
- [x] 머리 주석 갱신 · 루트/final `CLAUDE.md` · `mcp/README.md` · `FEATURES.md` · `diff.md` · `DESIGN_NOTES.md`
- [x] 그물 `check_mcp_tools._check_glossary_candidates` 6건 · `EXPECTED` 99→**105** · `run_all.py` 20/21(남은 FAIL 은
  `check_high_preprocessor` docling_core 부재 — 기준선과 같음). 옛 MCP 코드로 되돌리면 이 점검이 실패하는 것 확인.
- [x] 업로드 파일 `한영_금융용어집_업로드_축소.xlsx` 213행에 **대표어 중복 0건** — GenOS 제약과 충돌 없음.
- 남는 것(문서화만): 원문 표기가 대소문자만 다른 후보(`Account`/`account`)는 서빙 프롬프트 · MCP `terms` 모두 **따로 묶인다**
  (묶음 키가 표기 그대로). 실제 데이터에선 드물어 두었다.
- **커밋은 아직 안 했다**(사용자 확인 대기).

(아래 표는 원래 계획이다 — 위대로 구현했다.)

| # | 자리 | 바꿀 내용 |
|---|---|---|
| ② | `_GLpairs_from_items` (L556–575) | 코드서빙 ② 와 같게 — 키 `(ko, en)`, 사유 `duplicate_pair` |
| ③ | `glload_terms` (L307 `split()`) | `_GLTOKEN_RE.findall` |
| ① | `glexact_match` (L380–404) | 같은 `normalized_words` 후보 전부 수집, `seen` 키 `(source, target)` |
| — | `_GLglossary_lookup` (L699–757) 반환 `terms` | 지금 `{원문: 번역}` dict 라 후보가 겹치면 하나만 남는다. **`terms` 는 모양 유지**(문자열 값, 후보 여럿이면 ` / ` 로 이음) + **`candidates: {원문: [후보, …]}` 추가**. 워크플로우 스텝은 이 도구를 부르지 않는다(호출부 0건 — 문서·점검만 고치면 된다) |

#### 3. 그물 · 기준 건수

- `Test/SFR-018/tests/test_glossary_policy.py` — 새 테스트(각 1건 이상):
  - ② 같은 한국어 · 다른 영어 두 행이 **둘 다 적재**되고, 완전히 같은 쌍은 `duplicate_pair` 로 1건 걸러진다
  - ③ `Auto-pay` · `Broker’s price opinion` 표기 용어가 원문 `auto-pay` · `broker's price opinion` 에 걸린다
  - ① en→ko `Account` 두 후보가 `match_occurrences` · `terms_for_batch` 에 **둘 다** 나온다. 최장 일치는 여전히 이긴다(`Account Review Inquiry` 가 `Account` 보다 먼저)
  - ④ 프롬프트에 `"Account" -> "계좌" / "계정"` 한 줄로 실린다. 후보 하나인 용어는 줄 모양이 그대로다
  - ⑤ 번역문이 `계정` 만 써도 준수 · `term_map["Account"] == "계정"` · `matched_count` 가 후보 수만큼 늘지 않는다 · 아무 후보도 안 쓰면 미준수이고 `term_map_unapplied` 에 `"계좌 / 계정"`
  - ⑤ 스트리밍 `build_document_glossary` 가 같은 입력에 `build_report` 와 **같은 준수율**
- `Test/check/check_mcp_tools.py` — (MCP 보류 중이라 이번엔 없음)
- 늘린 만큼 `Test/run_all.py` 의 `EXPECTED` 수정. `python Test/run_all.py` 전체 통과(이 PC 의 `check_high_preprocessor` 83/100 은 `docling_core` 부재 — 무관)
- eval `Test/eval/eval_mcp/text_metrics.glossary_compliance` 는 이미 `{"원문": ["허용어1","허용어2"]}` 를 받는다 → **고칠 것 없음**(같은 "하나라도 쓰면 준수" 규칙인지만 확인)
- 끝나면 scratchpad 의 `self_match.py` 와 같은 시험을 적재용 시트로 다시 돌려 **en→ko 숨은 후보 67 → 0, 버려진 행 191 → 0** 을 확인한다(스크립트는 세션이 끊기면 사라진다 — 필요하면 다시 쓴다: 실제 `_pairs_from_items` + `_index_pairs` 에 넣고 각 행이 자기 (원문, 번역) 쌍으로 `match_occurrences` 에 나오는지 본다)

#### 4. 문서

- `final/CLAUDE.md` — "용어사전을 GenOS 독립 용어사전 API 에서 받는다" 절의 "중복 한국어는 거르고" → "같은 (한국어, 영어) 쌍만 거른다 · 후보 여럿은 LLM 이 고른다", 하이라이트 절의 `term_map` 정의
- `final/docs/README.md` — L571 사유 코드, L602 하이라이트 계약 표(`term_map` 값 = 실제로 쓴 후보, `hits[].term_targets` 신설)
- `final/mcp/README.md` · `final/docs/FEATURES.md` — (MCP 보류) 대신 번역 서빙과 MCP 매칭이 갈린다는 사실을 적는다
- `final/docs/diff.md` 사유 코드 표 · `final/docs/DESIGN_NOTES.md` 용어사전 절(왜 후보 전부인가: 다의어를 하나로 강제하면 문맥이 맞지 않는 자리에서 오역을 강제한다)

### 1-3. 매칭 한계 다섯 — 2026-11-06 착수 (번역·용어사전 MCP 동결 해제)

순서: ⑤ → ① → ③ 은 코드, ② · ④ 는 데이터부터. 코드는 번역 서빙 `glossary_exact.py`(세 함수가 같은 규칙) + MCP 사본을 함께 고친다.

- [x] ⑤ 대소문자만 다른 원문 후보 — 묶음 키 `casefold()`(서빙 `glossary_entries` · `group_occurrences`, MCP `_GLglossary_lookup`). 표시는 처음 표기
- [x] ① 숫자 — `_TOKEN_RE` 에 `[0-9]+` 독립 토큰. `skipped_digit` 제거. 숫자 뒤 낱말은 조사 절단 하한 1(`제3자에게`)
- [x] ③ 영어 활용형 — 문서 쪽에서만 어간 후보(`_en_stems`: -ed/-ing/-ied, `+e`, 자음 겹침), 어간 3자 이상.
  색인은 그대로(기본형끼리 깎으면 `note`/`not` 충돌). 세 판정 함수는 `_seq_eq` 하나를 쓴다.
  그물 SFR-018 423→426 · `check_mcp_tools` 105→108. `run_all.py` 20/21(남은 FAIL 은 기준선과 같은 docling_core)
- [x] 데이터: `한영_금융용어집_업로드_축소.xlsx` 에서 **미국 고유 제도 53행 추가 제외**(213→160, `제외 내역` 시트에 사유와 함께).
  연도 든 행(`~년`)은 이미 없었다. 한국 고유 용어 보강은 사용자 확인 대기
- [x] 데이터: **600 대표어로 되살림**(2026-11-06 사용자 지시 — "일상어 말고 금융권 용어, Qwen 기준 없을 법한 것"). 160 + 440.
  `되살림 내역` 시트에 등급: **1 필요 311**(일상어 분류였던 금융 용어 + 일반 금융 4 — `물가연동국채`→`물가연동국고채`,
  `기금`→`머니마켓펀드` 표기 고침) · **2 흔하지만 표준 번역 고정 129**(신용카드·인플레이션·할부 등 — 600 을 채우려고 넣은 층).
  미국 고유 기관·법령은 안 살렸다. 같은 영어를 다른 한국어로만 쓴 중복 5행은 다음 2등급으로 바꿨고,
  1-1d 의 영어 겹침 넷(`채무`-Encumbrance · `소유권 이전`-Transfer · `탕감`-Write off · `압류`-Impound)도 뺐다.
  자기 매칭(실제 적재·매칭 코드): **ko→en 0 · en→ko 0 누락**, 대표어 중복 0, 같은 영어 여러 대표어는 `Equity`(자기자본/지분) 하나
- [x] **번역 서빙 실측 검증**(2026-11-06, `/translate/markdown` · LLM 만 대역 — 사전을 안 보고 쓴 자연스러운 번역).
  한국어 상품설명서(ko→en) · 영어 연체 안내문(en→ko). 오매칭 없음(`감정이 상한` · `지수` · `Note:` · `title` · `interest in`).
  찾은 것과 고친 것:
  - 코드: 한국어 `-하다/-되다` 활용 어미(`_KO_PREDICATE_TAILS` 목록) · 조사 `나` — 서빙 · MCP 함께. 그물 SFR-018 427 · mcp 109
  - 데이터: `원금`(Principal 단독 — `principal reason` 에 걸림) 제외 · `자동이체` → Automatic transfer;Direct debit ·
    `이자율`→`금리` 계열 국내 표기(금리 · 금리 상한/하한 · 최고금리 · 금리 조정 · 초기 금리 · 금리 변경 제한, `이자율` 행은 따로 둠) ·
    `월 지불금`→`월 납입액` · `최대 지불금`→`최대 납입액` · `원금잔액`(Original principal balance)→`최초 원금`. 600 유지
  - 결과: 준수율 en→ko 0.62 → **0.90**, ko→en 0.88 → **0.89**. 남은 미적용은 표현 선택(`대출조건 조정`/`변경`) · `채무조정`(영문 미정)
  - 실제 LLM 이 사전을 따르는지는 GenOS 에서 돌려야 확인된다(이 PC 에 LLM 접속 설정 없음)
- [ ] ② 합성어 안쪽 — 데이터: 자주 나오는 합성어(`신용회복위원회`)를 별도 행으로(최장 일치가 이긴다). 코드 앞부분 일치(3자 이상)는 보류
- [ ] ④ 일반 의미 동형어 — 데이터 플래그 속성(예 `동형어`)으로 준수율 분모에서 빼는 안. 속성 이름은 사용자 결정

#### 5. 이 수정으로도 남는 것 (문서화)

- 숫자 낀 용어는 1-3 ① 에서 숫자를 독립 토큰으로 해 풀었다
- 한국어 띄어쓰기 차이는 코드로 풀지 않고 데이터(1-1d, 표기별 행)로 막는다. 합성어 안쪽 일치는 그대로 — 1-1b 표
- 후보가 많은 용어(`Charge` 4개)는 프롬프트가 길어질 뿐 동작은 같다. 후보 상한은 두지 않는다

## 2. 코드스페이스 실측 — `cos/` (2026-11-06)

- [x] `cos/run_translation_glossary.py` — 번역 서빙을 사본 없이 import 해 실제 LLM · 용어사전 API 로 돌린다(사전 적용/미적용 두 회차, `<mark>` 번역문 · 준수율 · 동형어 함정).
  데이터셋 `cos/dataset/` 10건(한 5 · 영 5) + `expect.json`. 배포 묶음 `1106.zip`(cos + 번역 서빙 · 번역 스텝 2 · MCP 4).
- [ ] 코드스페이스에서 실행해 실제 LLM 준수율 확인
- [ ] 데이터셋 매칭에서 본 사전 문제: `Transfer`→양도(잔액 이체에도 걸림) · `Settlement`→채무 합의(결제 뜻) ·
  `약정서`→Commitment letter(대출 약정서 일반) · `계좌 입금`→Direct deposit(`계좌에 입금해` 에 걸림)
- [x] 코드: 문장부호 경계(2026-11-09) — 문서의 부호는 경계, 표제어의 부호는 있어도 없어도 된다(`_seq_len`)
