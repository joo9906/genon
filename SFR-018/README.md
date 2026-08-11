# SFR-018 — 회귀 테스트 (구현은 `onprem/` 에 있다)

> **이 디렉토리에는 글다듬이·번역 구현이 없다.** 2026-08-11 부터 테스트 전용이다.
> 실행 코드는 `onprem/codeserving/SFR-018_*` 와 `onprem/mcp/`, `onprem/workflow/` 에 있다.

## 왜 사본을 없앴나

사본은 자동 동기화되지 않으므로 **운영 코드를 고쳐도 테스트는 옛 코드를 통과시켰다.**
실제로 갈려 있던 지점:

| 사본 | 실제 |
|---|---|
| `translation_refactored/tests` 가 `run_markdown_translation_job(..., translator_mode="mock")` 전제 | onprem 에는 그 인자가 없다 — 배포 단위에 mock 경로를 두지 않는다 |
| `text_polish/markdown_guard.py`·`diff_report.py` | **MCP `genon_text_guard` 로 옮겨갔다** (2026-08-11). 사본을 두면 이동이 테스트에 전혀 드러나지 않는다 |
| `text_polish/tone_presets.py` | 판정 원본이 MCP `genon_lang_policy` 로 갔다 |
| `text_polish/main.py` (02 진입점) | 글다듬이는 **02 → 03** 이 됐다. 그 파일은 onprem 에서 지워졌다 |
| 코드 문자열 프롬프트 | onprem 은 네 단위 모두 jinja 파일(`onprem/prompt/<단위>/*.j2`) |

## 구성

```
tests/
  onprem_path.py          ⭐ onprem 단위·MCP 경로를 sys.path 에 세운다
  test_markdown_guard.py  구조 훼손 감지 — **MCP `genon_text_guard`** 를 태운다
  test_markdown_units.py  마크다운 무손실 왕복·구조 보존 — 번역 코드서빙을 태운다
genos-glossary/           용어집 실험 스냅샷 (아래 참고 — 지우지 않았다)
```

### `genos-glossary/` 를 남긴 이유

1단계(정확 매칭, `glossary_exact.py`)는 이미 `onprem/` 에 병합됐지만,
**2단계 `glossary.py`(Weaviate + 임베딩 게이트웨이)는 onprem 어디에도 없다.**
폐쇄망 벡터DB 가용성이 확인되지 않아 보류된 상태이고, 이 파일이 **유일한 사본**이다.
나머지 파일은 중복이지만 실험 스냅샷을 쪼개면 되살릴 때 맥락이 끊기므로 통째로 둔다.

## 실행

```
cd SFR-018 && python -m unittest discover -s tests -t .
```

서버·Redis·LLM 불필요. LLM 경계에는 대역을 꽂는다 — 주입은 배포 단위 **바깥**인
테스트 파일에서만 하므로 운영 코드에 테스트용 분기가 생기지 않는다.

## 무엇을 여기서 보고, 무엇을 `onprem/test/` 에서 보나

| 여기(`SFR-018/tests`) | `onprem/test/` |
|---|---|
| 파서·가드 같은 **함수 단위 동작** | 배포 계약, 엔드포인트, 영역 간 계약, 사본 대조 |
| 마크다운 스켈레톤 무손실 왕복 | `check_unit_endpoints`(번역·FAQ 경계), `check_mcp_tools`(MCP 결정적 판정), `check_tone_policy`(톤 4벌 대조) |

## 입력 경로 공통 사항 — 전처리기 산출물 (마크다운 + HTML 표)

docx/pdf/hwpx 는 회사 전처리기를 거쳐 들어오며, 표 형식이 유형별로 다르다
(`genos_files/` 전처리기 소스 확인 결과):

- **첨부용(attach_processor)**: 마크다운 표(`| a | b |`) + `<!-- PB -->` 페이지 마커
- **지능형(intelligence_processor)**: `table_format` 설정에 따라 마크다운 표 또는
  **한 줄 HTML 표**(`<table><tbody>…`, 셀 텍스트 html.escape, colspan 보존,
  같은 줄에 제목 접두 텍스트 가능) + `[표 설명]` 요약 병기

표 등 구조는 건드리지 않고 내용만 바꾸는 원칙의 구현 방식이 기능별로 다르다:

- **번역**: `/translate/markdown` — 분해 시점에 표 파이프·HTML 태그·제목·목록·
  코드펜스를 코드가 스켈레톤으로 분리하고 **텍스트 내용만 LLM 에 보낸다**.
  재조립 결과의 구조는 LLM 출력과 무관하게 항상 원본과 동일 (구조적 보장).
- **글다듬이**: 문장 문맥이 필요해 문서를 통째로 보내되, 다듬기 전/후 구조
  지문(마크다운 표 행·열, HTML 표 행·셀, 제목, 코드펜스)을 `markdown_guard.py`
  로 대조해 훼손 시 경고를 노출한다 (감지 방식 — 재작성 특성상 스켈레톤 분리가 부적합).

## 글다듬이 — 지금 어디에 있나

영역 재배치(2026-08-11)로 **한 기능이 세 영역에 나뉘어 있다.** 고칠 곳을 찾을 때 쓴다.

| 하는 일 | 위치 |
|---|---|
| 워크플로우 스텝 (정책 확정 → 다듬기·스트리밍) | `onprem/workflow/sfr018_polish_01_policy.py`·`_02_polish.py` |
| LLM 호출·프롬프트 렌더 | `onprem/codeserving/SFR-018_text_polish/` (02 → **03** 이 됐다) |
| 문서유형 8종 × 톤 3종 정책 판정 | `onprem/mcp/genon_lang_policy/` — 판정하는 쪽이 원본을 갖는다 |
| 구조 훼손 감지·변경 내역 산출 | `onprem/mcp/genon_text_guard/` (`markdown_guard`·`diff_report`) |

설계 성질은 그대로다: 변경 내역은 LLM 에 묻지 않고 difflib 으로 **결정적으로** 계산하고,
LLM 호출 결과는 `LlmResult`(전역 오류 상태 없음, 통신/실행 실패를 예외 타입으로 분류)로
돌린다. 톤 프리셋은 4벌로 갈려 있고 `onprem/test/check_tone_policy.py` 가 대조한다.

## 번역 — 지금 어디에 있나

`onprem/codeserving/SFR-018_translation/`. 핵심 리팩토링 3가지는 유지된다:
전역 오류 레이스 제거(`LlmResult`), 동일 원문 dict 키 충돌 계약 명시,
배치 실패 시 단건 fallback 병렬화 + 실패 유닛 명시 추적.

고도화분(6개 언어·한국어 축 제약, 용어사전 1단계, 숫자 보존 검사, 표 셀 파이프
이스케이프, hwpx 직접 파싱)은 루트 `CLAUDE.md` 의 "SFR-018 번역 고도화" 절에 있다.
