# genon — GenOS 폐쇄망 문서 자동화

사내 **GenOS** 플랫폼에 올리는 문서 자동화 기능 **4종**의 프로덕션 코드와, 그것을 실제로
배포·검증하기 위한 계약 점검 도구를 담은 저장소.

| | |
|---|---|
| **현행 구현** | [`onprem/`](onprem/) — 여기가 유일한 구현이다 |
| **등록 단위** | **9개** (코드 서빙 4 + MCP 도구 4 + hwpx 전처리기 1) + 캔버스 워크플로우 스텝 9개 |
| **자동 검증** | unittest **163건** + 계약·실행 점검 **366건** — 전부 통과 (2026-08-14) |
| **옮겨 적는 차례** | [`onprem/WORK.MD`](onprem/WORK.MD) — 어떤 파일부터 쓰나 (103파일 / 21,169줄) |
| **막힌 것** | LLM 게이트웨이·Redis·한/글 **실물이 있어야 확인되는 것** ([HANDOFF §4](onprem/HANDOFF.md)) |

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

### 018 세 기능의 산출물은 **txt 하나**다 (2026-08-12 요구 변경)

글다듬이·번역·FAQ 는 화면에 결과를 보여주고 **`POST /download` 로 txt 파일**을 준다.
사용자가 그 파일을 메모장에서 이어 편집하기 때문이다. FAQ 에 있던 **hwpx·pdf·xlsx
내보내기는 전부 걷어냈다**(`archive/sfr018-doc-export` 브랜치에 코드가 남아 있다).

- **입력은 그대로다.** hwpx 직접 파싱·전처리기 마크다운·업로드 상한 전부 유지 —
  달라진 것은 마지막 산출 형식뿐이다.
- **화면도 그대로다.** UI 는 여전히 마크다운을 보여준다. 파일만 평문이다.
- **006 은 hwpx 로 낸다.** 사내 양식을 채우는 것이 기능 자체다. PDF 출력은
  2026-08-14 에 걷어냈다(`archive/sfr006-pdf`) — 그 경로만 기본 이미지 패키지를
  요구하고 있었다.
- txt 는 **UTF-8 BOM + CRLF** 로 낸다. 옛 윈도우 메모장이 BOM 없는 UTF-8 을 cp949 로
  읽어 한글을 깨뜨리고, LF 만 있는 파일을 한 줄로 붙여 보여주기 때문이다.

## 영역 3개 + 전처리기 (GenOS 등록 방식이 다르다)

```
사용자 ── 캔버스 워크플로우(02) ── 게이트웨이 ─┬─ 코드 서빙(03) ── LLM
              스텝 9개                        │     단위 4개
           httpx 만 쓴다                      └─ MCP 도구(01)
                                                 파일 4개 · LLM 없음
```

| | 02 워크플로우 | 03 코드 서빙 | 01 MCP |
|---|---|---|---|
| 등록 단위 | **파일 1개 = 스텝 1개** (9) | 디렉토리 = 서빙 (4) | **파일 1개 = 도구 묶음** (4) |
| 진입점 | `run(data)` | FastAPI 앱 + `$PORT` | `@mcp.tool()` — 앱도 포트도 없다 |
| 외부 패키지 | **`httpx` 뿐** | fastapi·lxml·redis·jinja2·openai | stdlib (hwpx 만 `lxml`) |
| LLM 호출 | ❌ | ✅ | ❌ |

**워크플로우 이미지에 추가되는 패키지가 0개**인 것이 2026-08-11 영역 재배치의 결과다 —
그전에는 스텝이 `lxml`·`redis`·`jinja2` 를 끌어써서 기본 이미지 변경 요청에 배포가 묶여
있었다. 근거는 [`ARCHITECTURE_SPLIT.md`](onprem/ARCHITECTURE_SPLIT.md).

**여기에 area 05 가 하나 더 있다** (2026-08-13) — `onprem/preprocessor/hwpx_preprocessor.py`.
hwpx 를 **RAG 로 적재**할 때 표가 깨지지 않게 직접 파싱·청킹하는 전처리기이고, 위 그림의
어디에도 배선돼 있지 않다(워크플로우가 부르지 않는다). MCP 와 같은 **파일 단위 등록**이며
표를 **언제나 HTML** 로 낸다 — 검색 결과가 프롬프트로 조립될 때 개행이 뭉개져 마크다운
표가 표가 아니게 되기 때문이다. 정본은 [`preprocessor/README.md`](onprem/preprocessor/README.md).

---

## 저장소 구조

| 경로 | 성격 |
|---|---|
| [**`onprem/`**](onprem/) | ⭐ **폐쇄망에 올라가는 현행 코드.** `codeserving/` 4 · `mcp/` 4 · `workflow/` 9 · `preprocessor/` 1 · `prompt/` · `eval/` · `test/` · `docs/` |
| [`data/`](data/) | 요구사항 문서(`FAQ_rule.md`·`translation_rule.md`)와 샘플 hwpx |
| `SFR-006/` `SFR-018/` | **테스트 전용.** `onprem/` 을 직접 import 한다 (구현 사본 없음 — 드리프트 불가) |
| `genos-project/` | 📖 읽기 전용 참조 번들 (개발가이드 PDF, 규칙 원문, 과거 스냅샷). **수정하지 않는다** |
| `genos_files/` | 실제 운영 배포에서 긁어온 참고 코드 + 전처리기 사본. **작동 샘플이지 규칙 준수 모델이 아니다** |
| `archive/` | zip 백업 |

**우선순위는 `onprem/` > `genos-project/source/`.** 후자는 과거 스냅샷이라 참조만 한다.

## 먼저 읽을 것

| 문서 | 답하는 질문 |
|---|---|
| [`onprem/HANDOFF.md`](onprem/HANDOFF.md) | **어디서부터 이어서 하나** — 무엇이 어디까지 검증됐고 무엇이 막혀 있나 |
| [`onprem/WORK.MD`](onprem/WORK.MD) | **어떤 파일부터 쓰나** — 단계별 작성 순서·분량·완료 판정 |
| [`onprem/docs/SERVING_REGISTRY.md`](onprem/docs/SERVING_REGISTRY.md) | **무엇을 등록하나** — 9번의 등록, 칸마다 적을 값 |
| [`onprem/README.md`](onprem/README.md) | **어떻게 배포하나** — 환경변수·로깅 규약·이관 순서의 **정본** |
| [`onprem/docs/FEATURES.md`](onprem/docs/FEATURES.md) | **무엇이 구현돼 있나** — 엔드포인트·MCP 도구·캔버스 변수·보장 |
| [`CLAUDE.md`](CLAUDE.md) | **왜 그렇게 했나** — 설계 결정과 그 근거 (작업 진입 문서) |
| [`genos-project/docs/GENOS_RULES.md`](genos-project/docs/GENOS_RULES.md) | GenOS 개발가이드 **강제 규칙** (영역별 시그니처·오류 코드·배포 계약) |

---

## 배포 — 등록은 9번

```
코드 서빙 4      onprem/codeserving/{SFR-006_template_fill, SFR-018_text_polish,
                                     SFR-018_translation, SFR-018_faq}
MCP 도구 4       onprem/mcp/genon_{text_guard, lang_policy, glossary, hwpx_text}.py
전처리기 1       onprem/preprocessor/hwpx_preprocessor.py — hwpx RAG 적재 (2026-08-13)
워크플로우 9     onprem/workflow/*.py — 서빙이 아니다. 캔버스에 파일을 붙여 넣는다
```

- **코드 서빙 1개 = 컨테이너 1개 = URL 1개.** 저장소를 어떻게 두든 등록 횟수는 줄지 않는다.
- **저장소는 1개로 간다.** 배포 단위 간 import 금지로 **의도된 사본**(표 격자 4벌·톤 프리셋
  3벌)이 있고, 갈렸는지는 한 커밋 안에서 동시에 읽어야 확인된다.
- **MCP 는 서빙이 아니라 파일이다.** GenOS 가 소스 파일 하나를 실행하고 `mcp` 객체를 전역
  주입한다 — FastAPI 앱·`/health`·`$PORT`·`requirements.txt` 가 전부 없다.
  **hwpx 전처리기도 같은 파일 단위 등록**이고, 등록 뒤 관리 화면에서 **hwpx 업로드를 그쪽으로
  매핑**해야 실제로 쓰인다(안 하면 종전 경로가 받고 그쪽은 표 안 수치가 깨진다).
- 등록만으로는 안 되는 전제(프롬프트 디렉토리 동봉·Redis 공유·기본 이미지 패키지)는
  [SERVING_REGISTRY §4](onprem/docs/SERVING_REGISTRY.md) 에 표로 있다.

## 검증

서버·Redis·LLM 없이 전부 돈다. 가짜는 **배포 단위 밖에서** 주입한다 — 운영 코드에
테스트용 분기를 만들지 않기 위해서다.

```bash
export PYTHONIOENCODING=utf-8      # Windows 콘솔 필수 (cp949 가 '—' 에서 죽는다)

cd SFR-006 && python -m unittest discover -s tests -t .   #  28건
cd SFR-018 && python -m unittest discover -s tests -t .   # 135건 (전처리기 80건 포함)

python onprem/test/check_deploy_contract.py   # 빌드·기동 계약 (FAIL 0 / WARN 3 / OK 62)
python onprem/test/check_service_boot.py      # 코드서빙 4단위 실제 기동          16
python onprem/test/check_workflow_run.py      # 워크플로우 스텝 9개 실행          72
python onprem/test/check_mcp_tools.py         # MCP 파일 4개 공존·결정적 판정     40
python onprem/test/check_api_contract.py      # 006 엔드포인트 (hwpx 전용 판정 포함) 45
python onprem/test/check_chat_turn.py         # 대화 한 턴 (02 스텝 ↔ 03 경계)    22
python onprem/test/check_unit_endpoints.py    # 018 세 단위 엔드포인트 + txt 규약  51
python onprem/test/check_body_blocks.py       # 문단 복제 안전장치                17
python onprem/test/check_output_safety.py     # 파트 선언·누름틀 안내문            5
python onprem/test/check_table_grid.py        # 표 격자 사본 4벌 대조             18
python onprem/test/check_tone_policy.py       # 톤 프리셋 사본 3벌 대조           18
```

**11개 + unittest 2벌. 위 건수는 2026-08-14 에 전부 다시 돌려 확인한 값이다.**

2026-08-13~14 에 **점검이 크게 늘었다** — 그때까지 아무 점검도 보지 않던 층이 있었다:
워크플로우 스텝이 **성공 응답에서 무슨 키를 꺼내는지**(`translated_markdown`·`stats` 가
그래서 두 번 유실됐다)와 **서빙의 재시도 불가 판정이 스텝을 넘어오는지**(스텝이 상태코드로만
판정해 통째로 뒤집고 있었다 — 세 번째 경계 유실). `check_workflow_run` 35→**70**,
`check_unit_endpoints` 31→**49**, `check_mcp_tools` 37→**40**, `check_chat_turn` 20→**22**,
SFR-018 unittest 56→**129**(표 HTML 전환·hwpx 전처리기 80건·용어사전 하이라이트).
변화 사유 표는 [`onprem/HANDOFF.md`](onprem/HANDOFF.md) §3-1.

그전, 2026-08-12 에는 세 번 걷어냈고 그때마다 점검 건수가 움직였다:

1. **개봉 안전 게이트·넘침 측정·`check_vendor_closure.py`** — 실제 배포 템플릿 3개가 표 없는
   소규모라 판정할 게 없었다 (`onprem/docs/hwpx_library_adoption.md` 상단 공지, 코드는
   `archive/hwpx-genon-vendor` 브랜치).
2. **006 의 톤(글다듬이) 변환** — 사용자 발화별 톤 선택이 아니라 관리자가 정한 고정 톤으로
   채우면 되는 성격이었다 (CLAUDE.md "글다듬이(톤)는 006 안에서 했었다" 절, 코드는
   `archive/sfr006-tone`). `check_tone_policy.py` 4벌→3벌, `check_chat_turn.py` 25→20건.
3. **FAQ 의 hwpx/pdf/xlsx 내보내기** — 018 산출물이 txt 로 통일됐다 (코드는
   `archive/sfr018-doc-export`). `check_unit_endpoints.py` 가 11→31건으로 **늘었다** —
   글다듬이가 파일을 내게 돼 점검 대상 단위가 둘에서 셋이 됐고, 세 단위의 **txt 응답
   바이트를 대조**하는 판정 7건이 새로 붙었다(BOM·CRLF·헤더·파일명 정리).

4. **006 의 PDF 출력** (2026-08-14) — 산출이 hwpx 하나가 됐다 (`archive/sfr006-pdf`).
   `check_api_contract.py` 42→**45건**(옛 `format=pdf` 는 400, `formats` 는 환경 무관),
   `check_deploy_contract` 의 WARN 4→**3**.

남은 WARN 3 은 의도된 것이다 — `try/except ImportError` 로 방어된 `fastmcp`, 루트
`main.py` 가 없어 시작 커맨드가 필수인 두 단위. **이미지가 제공해야 하는 패키지를
요구하는 코드서빙 단위는 이제 없다** (FAQ 는 3번으로, 006 은 4번으로 사라졌다).

**사본 대조 점검이 왜 있나**: 배포 단위 간 import 가 금지돼 있어 같은 규칙이 여러 벌
존재한다. 그 사본들이 실제로 갈려 있었기 때문에, 문서가 아니라 **출력으로** 대조한다.

## 알려진 공백

정직하게 적어 둔다 — [`onprem/HANDOFF.md`](onprem/HANDOFF.md) §4 가 상세하다.

- **LLM 실호출 경로 전체를 한 번도 본 적이 없다.** 게이트웨이가 없어 프롬프트 한/영 분리가
  실제 출력에 어떻게 작용하는지 미확인이다.
- **게이트웨이가 JSON-RPC 를 그대로 통과시키는지 미확인.** 우리 MCP 앱과의 계약까지만
  확인했다. 형식이 다르면 스텝 9개의 `_mcp_call` 을 각각 고친다(자기완결 규율).
- **빌드·시작 커맨드가 셸을 거치는지 미확인** (`cd A && B`). 안 먹으면 `--app-dir` 로 바꾼다.
- 생성한 hwpx 를 **한/글에서 열어본 적이 없다**. 개봉 안전 게이트도 2026-08-12 에 뺐으므로
  지금은 그 확인을 대신하는 장치가 없다 — 남은 hwpx 산출 경로는 **006 하나**뿐이고
  (FAQ 는 txt 로 바뀌었다), `check_output_safety.py` 가 파트 선언·누름틀 안내문만 본다.
- 임베딩·LLM Judge 평가 도구는 온프레미스 서빙 가용성 확인 후 착수 — 미구현 사실이
  `metric_catalog` 의 `not_implemented` 로 노출된다.

---

# 평가지표

아래는 **지표 정의의 정본**이다. 실행 가능한 구현은 [`onprem/eval/`](onprem/eval/) 의
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
