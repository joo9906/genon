# onprem/eval — 평가지표 MCP 서버

저장소 루트 `README.md` 의 평가지표 정의를 **실행 가능한 MCP 도구**로 옮긴 것.
지표 이름 ↔ 도구 이름이 1:1 이고, 각 도구는 README 의 도구 타입 태그
(`Text` / `Numeric` / `Structure` / `Embedding` / `LLM Judge`)를 docstring 첫 줄에 달고 있다.

**GenOS 배포 단위가 아니다.** 옆의 `SFR-006_template_fill/`, `SFR-018_text_polish/`,
`SFR-018_translation/` 는 폐쇄망에 올리는 프로덕션 코드지만, 이 디렉토리는 그 산출물을
채점하는 개발·검증 도구다. 세 배포 단위를 import 하지 않는다 (배포 단위 간 격리 규칙,
그리고 평가기가 피평가 코드의 파서를 공유하면 파서 버그를 함께 놓치기 때문).

## 실행 / 등록

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
| `hwpx_fill_roundtrip` | Structure | 006 | 채움→재스캔 판정 일치율(1.0 유지), 미입력 필드 안내문 유지 |
| `hwpx_document_integrity` | Structure | 006 | 필드 밖 텍스트 동일성, 태그·개체 수, ZIP 엔트리 일치 |
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
계약 위반 입력 6종 예외 확인). 기능별 묶음은 네 기능 각각 + 입력을 일부만 준 경우
(`pass_but_incomplete` 와 건너뛴 지표 목록)까지 확인했다. 정식 회귀 테스트가 필요해지면 저장소 루트
`SFR-006/`, `SFR-018/` 쪽 테스트 규약(`python -m unittest discover`)을 따른다.
