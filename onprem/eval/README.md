# onprem/eval — 평가지표 MCP 서버

저장소 루트 `README.md` 의 평가지표 정의를 **실행 가능한 MCP 도구**로 옮긴 것.
지표 이름 ↔ 도구 이름이 1:1 이고, 각 도구는 README 의 도구 타입 태그
(`Text` / `Numeric` / `Structure` / `Embedding` / `LLM Judge`)를 docstring 첫 줄에 달고 있다.

**GenOS 배포 단위가 아니다.** 옆의 `SFR-006_template_fill/`, `SFR-018_text_polish/`,
`SFR-018_translation/` 는 폐쇄망에 올리는 프로덕션 코드지만, 이 디렉토리는 그 산출물을
채점하는 개발·검증 도구다. 세 배포 단위를 import 하지 않는다 (배포 단위 간 격리 규칙,
그리고 평가기가 피평가 코드의 파서를 공유하면 파서 버그를 함께 놓치기 때문).

## 이 디렉토리는 MCP **서버**다 — 파일 하나 제약은 MCP **도구** 타입에만 있다

가이드 4장(p.18~33) 기준. 파일 제약이 붙는 건 서버 타입이 **MCP 도구
(INTERNAL_PYTHON)** 일 때뿐이다.

> p.19: "GenOS는 컨테이너 시작 시 FastMCP 인스턴스 `mcp`와 ASGI 앱을 먼저 생성한 후
> **사용자 코드를 같은 모듈에 결합한다.** 따라서 사용자 코드에는 FastMCP import,
> `mcp = FastMCP(...)` 및 별도 ASGI app 생성을 작성하지 않는다."

→ 사용자 코드 단위가 **코드 필드 하나 = 모듈 하나**여서 상대 import(`from .normalize import …`)가
성립하지 않는다. 대신 그 안에 `@mcp.tool()` 함수는 **여러 개** 넣을 수 있다(p.5).
그리고 이게 유일한 등록 경로가 아니다:

| 경로 | 서버 타입 / 위치 | 다중 파일 | `eval_mcp/` 수정 |
|---|---|---|---|
| **A. MCP 패키지 — Python 모듈** (권장) | 실행 템플릿 `python3 -m eval_mcp.server` (p.21) | 예 | 없음 — `server.py` 그대로 |
| **B. MCP 도구 + 사내 .whl import** | 코드 필드는 어댑터 몇 줄 (p.65~66 패턴 A) | 예 (.whl 안) | 없음 (어댑터만 추가) |
| **C. 코드 서빙을 MCP 서버로 사용** | 리비전 상세 > 컨테이너 서비스 (p.41 6.5) | 예 (Git 저장소) | `/mcp/list`·`/mcp/call` 추가 |
| **D. MCP 도구 단일 파일 인라인** | 코드 필드에 전부 붙여넣기 | **아니오** | 사본 5개 생성 |

**A·B 는 코드 중복이 0 이다** — 사내 PyPI(.whl) 등록이 되면 `eval_mcp/` 를 그대로 쓴다.
**D 는 사내 PyPI 를 쓸 수 없을 때의 최후 수단**이다(2,300행을 다섯 파일에 인라인해야 한다).

어느 경로든 `eval_mcp/` 자체는 **건드리지 않는다.** 여기가 계산 로직의 원본이고,
로컬(Claude Code) stdio MCP 서버로도 그대로 돌아간다.

### A. MCP 패키지 / Python 모듈 — 현행 구조 그대로 (권장)

p.18 (4.1.2) 의 실행 템플릿 "Python 모듈"은 `python3 -m <module_name>` 을 실행한다.
지금 로컬 실행 방식과 같으므로 서버 설정 JSON 만 쓰면 된다:

```json
{"command": "python3", "args": ["-m", "eval_mcp.server"], "env": {"LOG_LEVEL": "INFO"}}
```

- `eval_mcp` 를 **.whl 로 빌드해 관리 > 리소스 > PyPI 패키지**에 올린다
  (p.19: "사용자 코드에서 pip install을 실행하지 않는다"). `lxml` 도 같이 등록한다.
- 이 경로에서는 `server.py` 의 `FastMCP` 생성·`mcp.run()`·`configure_stderr_logging()` 이
  **맞다** — stdio MCP 서버 본체이기 때문이다. (금지 대상은 MCP *도구* 코드 필드다.)
- 등록 후 **중요 정보 > 도구 동기화**를 실행해야 도구 목록이 잡힌다(p.31).
- 확인 필요: MCP 패키지 타입 화면에서 사내 PyPI 패키지를 선택할 수 있는지. 문서는
  `python3 -m company_mcp.server` 예시만 들고 설치 경로를 명시하지 않는다 → 안 되면 B.

### B. MCP 도구 + 사내 라이브러리 import (p.65~66 패턴 A)

> p.66: "패턴 A: 도구 함수에 **사내 라이브러리**, 로컬 캐시 또는 여러 의존성이 필요할 때
> 사용한다. 도구 함수를 패키지로 분리하면 개별적으로 빌드하고 테스트할 수 있다."

코드 필드에는 어댑터만 둔다. 계산 로직은 .whl 안의 `eval_mcp/` 그대로다:

```python
import asyncio
from eval_mcp import structure_metrics, suites          # 사내 .whl

async def hwpx_document_integrity(before_path: str, after_path: str) -> dict:
    """[언제 쓰나] … (server.py 의 docstring 을 그대로 옮긴다)"""
    return await asyncio.to_thread(structure_metrics.hwpx_integrity, before_path, after_path)

mcp.tool()(hwpx_document_integrity)      # GenOS 가 만든 mcp 인스턴스에 등록 (p.66)
```

- `mcp = FastMCP(...)` 를 쓰지 않으므로 **현행 `server.py` 를 그대로 붙여넣을 수는 없다.**
  어댑터 파일을 따로 만들고 `server.py` 는 로컬용으로 남긴다 (도구 정의는 docstring째 복사).
- 로깅은 `configure_stderr_logging` 대신 GenOS 주입 로거를 쓴다 (p.28):
  `from common.logger import Logger` / `logger = Logger.getLogger(__name__)`.
  stdio 가 아니라 stdout 오염 문제가 없고, 화이트리스트 계약(`ALLOWED_FIELDS`)은 그대로 지킨다.

### C. 코드 서빙을 MCP 서버로 사용 (p.41, 6.5)

Git 저장소 기반이라 파일 구조가 자유롭다. `POST /mcp/list`(도구 목록·`inputSchema`)와
`POST /mcp/call`(`{"code":0,"data":{"content":[{"type":"text","text":"…"}]}}`) 두 엔드포인트를
직접 구현해야 한다. 옆 배포 단위들이 이미 코드 서빙이라 운영 방식이 익숙하다는 점이 이득이고,
`inputSchema` 를 손으로 유지해야 한다는 점이 비용이다.

## 로컬 실행 (개발·회귀 채점 — MCP 서버 형태)

```
pip install -r requirements.txt
python -m eval_mcp.server          # stdio 전송
```

Claude Code 등에 등록할 때 (`.mcp.json`):

```json
{
  "mcpServers": {
    "genon-eval": {
      "command": "python",
      "args": ["-m", "eval_mcp.server"],
      "cwd": "C:/Users/happy/Desktop/Code/genon/onprem/eval"
    }
  }
}
```

LLM·임베딩 서빙에 붙지 않으므로 `GENOS_URL` 등 Gateway 환경변수가 필요 없다.
전부 로컬 결정적 계산이다 (폐쇄망·오프라인에서 그대로 돌아간다).

### D. 단일 파일 인라인 — 어떤 파일을 어떤 도구로 묶는가

A·B·C 가 모두 막혔을 때만(사내 PyPI 등록 불가 + 코드 서빙 사용 불가) 쓴다.
공통 코어를 다섯 번 복사하므로 지표를 고칠 때 다섯 곳을 고쳐야 한다 — 그 비용을 알고 택한다.

**기능별로 나눈다.** 지표 묶음이 이미 기능 단위로 선언돼 있고(`suites.py`),
lxml 이 필요한 도구가 006 쪽에만 있어 나머지 세 파일은 외부 의존이 0 이 된다.

`normalize.py` + `logging_utils.py` + `error_codes.py`(196행)는 **공통 코어**로
다섯 파일에 모두 인라인한다 (import 할 수 없으므로 사본이다 — 배포 단위 간 사본을
두는 `logging_utils.py` 와 같은 이유).

| 단일 파일 | 담는 도구 | 인라인할 모듈 (공통 코어 +) | PyPI 등록 |
|---|---|---|---|
| `eval_common_tool.py` | `metric_catalog` `feature_suites` `text_match` `numeric_threshold` `structure_fingerprint` `fact_preservation_check` `sentence_length_stats` `ending_consistency` `llm_judge_gate` | `catalog.py`(전체), `suites.py`(선언 `SUITES`·`list_suites` 만), `text_metrics.match_text`, `numeric_metrics.py`(전체), `structure_metrics` 의 마크다운/HTML 지문부 + `ending_consistency`, `gating.py` | 없음 |
| `eval_template_fill_tool.py` | `field_extraction_score` `hwpx_fill_roundtrip` `hwpx_document_integrity` `multiturn_scenario_score` `run_template_fill_eval` | `text_metrics.aggregate_extraction`, `structure_metrics` 의 hwpx(OWPML)부, `scenario_metrics.py`, `suites._run_template_fill` + 합불 판정부, `numeric_metrics.compare_threshold`, `gating.py` | **`lxml`** |
| `eval_text_polish_tool.py` | `polish_structure_pass_rate` `tone_rule_check` `tone_pass_rate` `run_text_polish_eval` | `structure_metrics.fingerprint`/`structure_pass_rate`, `tone_metrics.py`, `suites._run_text_polish` + 판정부, `numeric_metrics`(사실 보존·문장 길이·임계 비교), `gating.py` | 없음 |
| `eval_translation_tool.py` | `translation_structure_health` `chrf_score` `glossary_compliance` `run_translation_eval` | `structure_metrics.translation_fallback_rate`, `numeric_metrics.chrf`/`cross_check_facts`/`compare_threshold`, `text_metrics.glossary_compliance`, `suites._run_translation` + 판정부, `gating.py` | 없음 |
| `eval_faq_tool.py` | `grounding_overlap` `run_faq_eval` | `text_metrics.grounding_overlap`, `suites._run_faq` + `_judge_candidates`(faq 분기), `gating.py` | 없음 |

- **도구 이름은 서버 전체에서 유일해야 한다.** 그래서 두 기능이 함께 쓰는
  `fact_preservation_check`·`sentence_length_stats`·`ending_consistency` 는
  **공통 파일에만** 두고, 기능별 파일에서는 집계 함수로만 내부 호출한다.
- 같은 이유로 `run_feature_eval` 은 단일 파일로 쪼갤 때 **기능별 이름**
  (`run_template_fill_eval` 등)으로 나눈다 — 한 도구가 네 기능 전부를 담으면
  모든 지표 모듈을 한 파일에 인라인해야 해서 분할이 의미를 잃는다.
- 파일 다섯 개를 **한 MCP 서버에 함께 등록**해도 되고, 006 만 따로 올려도 된다
  (파일 간 의존이 없다). lxml 을 등록할 수 없는 서버에는 006 파일만 빼면 된다.

### MCP 도구 코드 필드 규약 (B·D 공통 — 가이드 4장 + `quick_search` 선례)

```python
import asyncio                                # 상대 import 금지 (D 에서는 공통 코어 인라인)

def _tf_normalize(text: str) -> str: ...      # 모든 최상위 심볼에 접두 (한 서버 공존)

try:                                          # 런타임이 주입하는 전역 mcp 를 쓴다.
    mcp                                       # FastMCP import·인스턴스·ASGI app 금지 (p.19)
except NameError:                             # 로컬 단독 실행용 최소 shim
    class _TfLocalMCP:
        def tool(self, *a, **k):
            return lambda fn: fn
    mcp = _TfLocalMCP()

@mcp.tool()
async def hwpx_document_integrity(before_path: str, after_path: str) -> dict:
    """[언제 쓰나] …

    Args: …
    Returns: …
    """
    try:
        return await asyncio.to_thread(_tf_integrity, before_path, after_path)
    except _TfEvalInputError as exc:          # MCP 영역은 오류를 '객체로 반환'한다
        return {"error": {"error_code": "01-00020003", "msg": str(exc), "retryable": False}}
```

- **반환 타입은 `str/int/float/bool/dict/list` 중 하나**(p.24) — 현행 도구의 **dict 반환이
  그대로 유효하다.** dataclass·DataFrame·numpy 객체는 반환 금지(p.32: JSON 변환 실패 → 500).
- **타입힌트는 파라미터·반환 모두 필수**다(p.24: 누락하면 입력 형식이 만들어지지 않거나 `Any`).
  docstring 은 Google 스타일 `Args:`/`Returns:`/`Raises:` — "관리자 화면 소개 문구가 아니라
  LLM 이 도구를 선택할 때 사용하는 정보"(p.23). 현행 `server.py` 는 이 형식을 이미 지킨다.
- **함수명이 그대로 도구 이름**이고 "같은 함수명이 있으면 등록하지 않는다"(p.9).
  그래서 위 표에서 공통 도구를 한 파일에만 두고 `run_feature_eval` 을 기능별로 쪼갠다.
- `def`·`async def` 모두 등록되지만 동기 I/O 는 이벤트 루프를 막는다(p.24) → hwpx
  ZIP/XML 파싱은 `async def` + **`asyncio.to_thread`**.
- **전역 mutable 금지**(p.32: 동시 요청 race condition). 현행 코드는 상수뿐이라 문제없다 —
  단일 파일로 옮기면서 캐시를 넣지 말 것.
- **인자 타입은 넓게** 선언한다 (`float | str | None`) — GenOS 는 미입력 인자를 `None` 이
  아니라 **빈 문자열 `""`** 로 주입하고 타입 검증이 본문보다 먼저 돈다(Weaviate 선례).
  캐스팅은 본문에서 한다.
- **오류 전달 방식이 바뀐다.** 평가지표 영역은 "로그 남기고 예외"지만 MCP 영역(01)은
  `isError: true` 와 함께 **오류 객체를 반환**한다(p.16 3.9.5, p.29). `fail()` 이 던지는
  `EvalInputError` 를 어댑터에서 잡아 `{"error": {...}}` 로 감싼다. 메시지는
  `error_codes.py` 상수뿐이라 예외 원문이 새지 않는다 — p.27 이 경고하는 지점이다
  ("Tool 의 오류 결과는 LLM 에도 전달될 수 있다. 예외 메시지, 내부 URL … 을 넣지 않는다").
  `fail()` 의 로그 기록은 그대로 유지한다.
- 로깅은 `configure_stderr_logging` 대신 **GenOS 주입 로거**(p.28):
  `from common.logger import Logger` / `logger = Logger.getLogger(__name__)`.
  `print()` 금지, 화이트리스트 필드 계약은 유지.
- **의존 패키지는 관리 > 리소스 > PyPI 패키지에 `.whl` 을 업로드한 뒤 MCP 도구에서 선택**한다
  (p.19·p.72). 코드 안의 `pip install` 은 "무시되거나 권한 오류" — Weaviate 예제의
  런타임 부트스트랩(`_qs_ensure_packages`)은 **쓰지 않는다.**
- 시크릿은 **중요 정보 > 환경 변수**(p.26). `os.environ["KEY"]` 로 읽고
  **`os.getenv` 기본값으로 오류를 숨기지 않는다.** 이 도구들은 LLM·임베딩 호출이 없어
  현재 필요한 시크릿이 없다.
- 배포 검증: **도구 > MCP 서버 상세 > 테스트**(p.30). 도구가 목록에 안 보이면
  `@mcp.tool()` 등록과 타입힌트를 먼저 확인한다(p.71 11.5.1).

## 기능별 지표 묶음 — 네 기능은 서로 다른 지표로 평가한다

지표는 기능마다 다르다. 그 묶음을 `suites.py` 에 선언해 두고 진입점 두 개로 쓴다.

| 기능 (`feature`) | 운영 지표 | 합불 기준 (기본값) |
|---|---|---|
| `template_fill` (006) | 필드 추출 P/R/F1·환각률, 라운드트립, 문서 무결성, 멀티턴 | 판정 일치율 = 1.0, 무결성 통과, 세션 누적 = 1.0, 완성률 > 0.9, F1 > 0.8, 환각률 < 0.05 |
| `text_polish` (글다듬이) | 지문 대조, 톤 규칙, 어미 일관성, 사실 보존 / *문장 길이는 참고용* | 지문 통과율 = 1.0, 사실 보존 = 1.0, 톤 > 0.9, 어미 일관 > 0.9 |
| `translation` (번역) | fallback·세그먼트 불일치, 사실 보존, 용어집 준수, chrF(참조 있을 때) | fallback = 0, 불일치 = 0, 사실 보존 = 1.0, 용어집 > 0.95 |
| `faq` | 원천 n-gram 중복·자카드 (스크리닝) | **합불 기준 없음** — 낮은 문장만 게이트로 넘긴다 |

```
feature_suites("translation")        # 지표 목록·필요 입력 키·기준 확인
run_feature_eval("translation", {...})  # 묶음 일괄 실행
```

`run_feature_eval` 은 세 가지를 분리해서 돌려준다 — 이게 이 도구의 요점이다.

- `verdict`: `pass` / `fail` / **`pass_but_incomplete`**(측정한 기준은 통과했지만 못 잰 기준이 있음)
  / `not_measured` / `no_operational_target`(FAQ). **미측정을 통과로 읽히게 하지 않는다.**
- `skipped_metrics`: 입력이 없어 실행하지 않은 지표와 그 이유 (`"입력 없음: pairs (측정 안 함)"`)
- `llm_judge_gate`: 결정적 지표를 통과 못한 항목만 후보로 올린 게이트 결과

기준값은 `payload.thresholds` 로 지표 경로별로 덮어쓴다
(예: `{"field_extraction_score.overall.f1": 0.9}`).

## 도구 (21개)

`metric_catalog(scope=…)` 로 기능별 지표만 걸러 볼 수 있고, **미구현 지표 목록 + 그 이유**도
함께 받는다.

| 도구 | 태그 | 대상 | 무엇을 재는가 |
|---|---|---|---|
| `metric_catalog` | - | 공통 | 지표↔도구 대응표, 참조 필요 여부, 게이트드 여부, 측정 공백 |
| `feature_suites` | - | 공통 | 기능별 지표 묶음·입력 키·합불 기준 정의 |
| `run_feature_eval` | - | 기능별 | 한 기능의 묶음 일괄 실행 + 합불·미측정·게이트 리포트 |
| `text_match` | Text | 공통 | 정규화(NFKC·공백 축약) 후 exact / contains / regex |
| `numeric_threshold` | Numeric | 공통 | 수치 추출 후 lt / gt / eq / between |
| `structure_fingerprint` | Structure | 공통 | 마크다운 표·HTML 표·제목·코드펜스 지문 대조 |
| `field_extraction_score` | Text | 006 | 필드별 P/R/F1, 값 exact·부분 일치율, 환각률 |
| `hwpx_fill_roundtrip` | Structure | 006 | 채움→재스캔 판정 일치율(1.0 유지), 미입력 항목 상태 유지 |
| `hwpx_document_integrity` | Structure | 006 | 항목 값 밖 텍스트 동일성, 태그·개체 수, ZIP 엔트리 일치 |
| `multiturn_scenario_score` | Numeric | 006 | 완성 성공률, 완성까지 턴 수, 세션 누적 정확성 |
| `polish_structure_pass_rate` | Structure | 018 글다듬이 | 지문 대조 통과율 + 훼손 유형별 건수 |
| `translation_structure_health` | Structure | 018 번역 | fallback 발생률·세그먼트 수 불일치율 (0 수렴 목표) |
| `tone_rule_check` | Text | 018 글다듬이 | 톤 프리셋 종결 형태, 금지 표현, 조사 오류 |
| `tone_pass_rate` | Text | 018 글다듬이 | 위 검사의 묶음 합불 집계 |
| `ending_consistency` | Text | 018 글다듬이 | 문서 초반·후반 우세 종결 유형 일치 |
| `sentence_length_stats` | Numeric | 018 글다듬이 | 문장 길이 분포 — **참고용, 합불 기준 아님** |
| `fact_preservation_check` | Text/Numeric | 018 공통 | 숫자·날짜·단위·고유명사 원문↔결과 교차 대조 |
| `chrf_score` | Numeric | 018 번역 | chrF (참조 번역 있는 테스트셋 전용) |
| `glossary_compliance` | Text | 018 번역 | 용어집 지정 번역어 준수율 |
| `grounding_overlap` | Text | 018 FAQ | 답변 문장↔원천 n-gram 중복·자카드 (1차 스크리닝) |
| `llm_judge_gate` | LLM Judge | 공통 | **판정 대상 선별만** — 스크리닝 미통과분 + 샘플링 + opt-in |

## 설계 결정 (README 원칙을 코드로 강제한 부분)

- **기능별 지표는 `suites.py` 한 곳에 선언한다.** 네 기능은 지표도 기준도 다르므로 그 차이를
  코드 흐름이 아니라 선언 표로 둔다(지표를 더할 때 한 줄만 고친다). 합불 판정은 기능마다
  따로 구현하지 않고 임계 비교 도구를 재사용한다 — 다른 것은 "무엇을 재는가"와 "기준값"뿐이다.
- **결정적 도구가 기본 경로다.** LLM Judge 게이트를 뺀 모든 도구에 LLM·임베딩 호출이 없다.
- **006 항목은 두 방식을 함께 센다** — 본문에 텍스트로 적힌 라벨 항목(`제목: {고딕, 16pt}`,
  현장 템플릿의 실제 방식)과 누름틀(CLICK_HERE). 무결성 지표에서 라벨 항목은
  **`항목명:` 까지를 문서 골격, 콜론 뒤를 값**으로 나눈다. 나누지 않으면 정상적으로 채워
  넣은 값이 "필드 밖 텍스트가 달라졌다"로 잡혀 무결성이 항상 실패한다.
  서식 명세 표기 `{…}` 는 채우기 단계가 지우는 대상이라 값에서 제외한다.
  이 규칙은 운영 코드(`template_fill`)와 **따로 구현**돼 있다(파서 공유 금지) —
  운영 쪽 인식 규칙을 바꾸면 `structure_metrics.py` 도 함께 고쳐야 한다.
- **`llm_judge_gate` 는 판정 모델을 호출하지 않는다.** 결정적 지표 통과분과 임베딩
  유사도 임계 이상 건을 후보에서 빼고, 남은 후보 중 **id 해시 표본**만 대상으로
  올린다(난수를 쓰지 않으므로 같은 입력이면 같은 표본 — 지표 재현 가능).
  `opt_in` 과 `judge_enabled`(온프레미스 서빙 가용성 확인)가 **둘 다 참**이어야 게이트가
  열리고, 닫혀 있으면 그 사유를 결과에 담아 돌려준다.
- **임베딩은 호출부가 계산해 넘긴다.** 고정 임베딩 모델 서빙 가용성이 확인되기 전까지
  유사도를 이 서버에서 계산하지 않는다. `llm_judge_gate` 의 `similarity` 가 없으면
  "임베딩 스크리닝 미실시"로 별도 보고한다 — 스크리닝 공백을 통과로 위장하지 않는다.
- **참조 없는 지표는 측정 불가로 예외를 낸다.** `field_extraction_score`, `chrf_score`,
  `glossary_compliance`, `grounding_overlap` 는 정답/원천이 없으면 조용히 0 을 주지 않고
  실패한다 (실패 침묵 처리 금지).
- **날짜·숫자 표기 차이로 감점하지 않는다.** `2026년 3월 12일` 과 `2026-03-12` 는 같은
  값으로 표준화하고, 날짜 구간을 뺀 본문에서만 숫자·단위를 센다.
- **한국어 형태소/NER 모델을 쓰지 않는다.** 조사 오류는 받침 유무(유니코드 연산)로 판정하고,
  고유명사는 라틴 대문자 토큰 + 호출부가 준 목록만 센다 (한계를 결과에 명시).
- **오류는 로그를 남긴 뒤 예외로 던진다** (`error_codes.fail()`). 평가지표·MCP 도구 영역은
  오류 객체를 반환하지 않는다는 규칙(GENOS_RULES A.4)에 맞춘 것이고, 로그 없이 예외만
  던지면 폐쇄망에서 실패 원인을 추적할 근거가 남지 않는다. 예외 원문은 `error_type`
  (클래스명)으로만 남기고 체인(`raise ... from exc`)은 유지한다.
- **로그는 stderr 로만** 나간다(`configure_stderr_logging`). stdio MCP 에서 stdout 은
  JSON-RPC 전송 채널이라 로그가 섞이면 프로토콜이 깨진다.
- **로그 필드 화이트리스트**(event/item_count/status/duration_ms/error_type 등)만 기록한다.
  평가 입력에는 문서 원문·사용자 질문·LLM 응답이 그대로 들어오므로(그게 평가 대상이다)
  로그 경로가 특히 위험하다 — 지표 값과 건수만 남긴다.
- **오류 문자열은 `error_codes.py` 상수만** 쓴다. 계산 로직은 MCP 런타임과 무관해서
  스크립트·노트북에서 `from eval_mcp import text_metrics` 로 그대로 쓸 수 있다.

## 미구현 (숨기지 않는 측정 공백)

`metric_catalog` 의 `not_implemented` 에 이유와 함께 들어 있다.

- 임베딩 유사도 스크리닝, BERTScore — 모델 서빙 가용성 확인 후 추가
- LLM Judge 실제 판정(NLI·근거성) 호출 — 게이트 선별까지만 제공
- 렌더링 기반 지표(BBox IOU, TEDS) — 006 은 레이아웃 불변, HWPX 렌더러도 없어 제외 확정
- PosTagging 품사 비율, 한국어 NER — 형태소 모델 미포함

## 검증

`tests/` 를 두지 않는 `onprem/` 규칙을 따르되, 도구 전수 스모크는 합성 hwpx 픽스처로
확인했다 (누름틀 2개 + 표 1개 문서를 만들어 라운드트립·무결성 통과/실패 양쪽 케이스,
라벨 항목 5개(표 안 2개 포함) 문서로 라운드트립 1.0·무결성 통과 및 값 훼손 검출,
계약 위반 입력 6종 예외 확인). 기능별 묶음은 네 기능 각각 + 입력을 일부만 준 경우
(`pass_but_incomplete` 와 건너뛴 지표 목록)까지 확인했다. 정식 회귀 테스트가 필요해지면 저장소 루트
`SFR-006/`, `SFR-018/` 쪽 테스트 규약(`python -m unittest discover`)을 따른다.
