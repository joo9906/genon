"""지표 카탈로그 — README 의 지표 목록과 도구의 대응 표.

이 표가 있어야 "어떤 지표가 어떤 도구 타입이고, 참조 데이터가 필요한지,
게이트드인지"를 호출자가 매번 README 를 다시 읽지 않고 알 수 있다.
지표를 추가할 때 여기에도 한 줄을 넣는다 — 표에 없는 도구는 운영 지표가 아니다.
"""

# tag: Text / Numeric / Structure / Embedding / LLM Judge (README 도구 타입)
CATALOG: list = [
    # ── 기능별 묶음 진입점 (기능마다 지표·기준이 다르다 — suites.py) ──
    {"tool": "feature_suites", "tag": "-", "scope": "공통", "metric": "기능별 지표 묶음·입력 키·합불 기준 정의", "needs_reference": False, "gated": False},
    {"tool": "run_feature_eval", "tag": "-", "scope": "006/번역/글다듬이/FAQ", "metric": "한 기능의 지표 묶음 일괄 실행 + 합불·미측정·게이트 후보 리포트", "needs_reference": False, "gated": False},
    # ── 공통 프리미티브 ──
    {"tool": "text_match", "tag": "Text", "scope": "공통", "metric": "정규화 후 exact/contains/정규식 매칭", "needs_reference": True, "gated": False},
    {"tool": "numeric_threshold", "tag": "Numeric", "scope": "공통", "metric": "수치 추출 후 임계 비교(lt/gt/eq/between)", "needs_reference": True, "gated": False},
    {"tool": "structure_fingerprint", "tag": "Structure", "scope": "공통", "metric": "마크다운/HTML 구조 지문 대조", "needs_reference": False, "gated": False},
    # ── 006 ──
    {"tool": "field_extraction_score", "tag": "Text", "scope": "006", "metric": "필드 추출 precision/recall/F1 + 값 exact/부분 일치 + 환각률", "needs_reference": True, "gated": False},
    {"tool": "hwpx_fill_roundtrip", "tag": "Structure", "scope": "006", "metric": "채움→재스캔 판정 일치율(100% 유지), 미입력 필드 안내문 유지", "needs_reference": False, "gated": False},
    {"tool": "hwpx_document_integrity", "tag": "Structure", "scope": "006", "metric": "필드 외 텍스트 동일성, 개체(표·이미지) 수 일치", "needs_reference": False, "gated": False},
    {"tool": "multiturn_scenario_score", "tag": "Numeric", "scope": "006", "metric": "최종 완성 성공률·완성 턴 수, 세션 누적 정확성", "needs_reference": True, "gated": False},
    # ── 018 ──
    {"tool": "polish_structure_pass_rate", "tag": "Structure", "scope": "018 글다듬이", "metric": "markdown_guard 지문 대조 통과율", "needs_reference": False, "gated": False},
    {"tool": "translation_structure_health", "tag": "Structure", "scope": "018 번역", "metric": "재조립 실패·세그먼트 불일치 fallback 발생률(0 수렴)", "needs_reference": False, "gated": False},
    {"tool": "tone_rule_check", "tag": "Text", "scope": "018 글다듬이", "metric": "톤 프리셋 대비 종결/금지표현/조사 규칙 검사", "needs_reference": False, "gated": False},
    {"tool": "ending_consistency", "tag": "Text", "scope": "018 글다듬이", "metric": "문서 초반·후반 종결어미 일관성", "needs_reference": False, "gated": False},
    {"tool": "sentence_length_stats", "tag": "Numeric", "scope": "018 글다듬이", "metric": "문장 길이 분포 (참고용 — 합불 기준 아님)", "needs_reference": False, "gated": False},
    {"tool": "fact_preservation_check", "tag": "Text/Numeric", "scope": "018 공통", "metric": "숫자·날짜·단위·고유명사 원문↔결과 교차 대조 (1차 방어선)", "needs_reference": False, "gated": False},
    {"tool": "chrf_score", "tag": "Numeric", "scope": "018 번역", "metric": "chrF (참조 번역 있는 테스트셋 전용)", "needs_reference": True, "gated": False},
    {"tool": "glossary_compliance", "tag": "Text", "scope": "018 번역", "metric": "용어집 지정 번역어 준수율", "needs_reference": True, "gated": False},
    {"tool": "grounding_overlap", "tag": "Text", "scope": "018 FAQ", "metric": "답변 문장 ↔ 원천 n-gram 중복·자카드 (1차 스크리닝)", "needs_reference": True, "gated": False},
    {"tool": "llm_judge_gate", "tag": "LLM Judge", "scope": "공통", "metric": "게이트 판정 — 스크리닝 미통과분만 샘플링/opt-in", "needs_reference": False, "gated": True},
]

# 아직 이 서버에 없는 지표와 그 이유. 숨기지 않고 명시한다 (측정 공백을 드러낸다).
NOT_IMPLEMENTED: list = [
    {
        "metric": "임베딩 유사도 스크리닝 (의미 보존·번역 품질·FAQ 근거성)",
        "tag": "Embedding",
        "reason": "고정 임베딩 모델 서빙이 필요 — 온프레미스 가용성 확인 후 추가. "
        "그때까지 유사도는 호출부가 계산해 llm_judge_gate 에 넘긴다.",
    },
    {
        "metric": "BERTScore (참조 번역 대비)",
        "tag": "Embedding",
        "reason": "사전학습 모델 서빙 필요. 현재 참조 기반 지표는 chrF 만 운영한다.",
    },
    {
        "metric": "LLM Judge 실제 판정 호출 (NLI·근거성)",
        "tag": "LLM Judge",
        "reason": "게이트드 도구. 대상 선별(llm_judge_gate)까지만 제공하고 판정 호출은 "
        "서빙 가용성·opt-in 확인 후 붙인다.",
    },
    {
        "metric": "렌더링 기반 지표(BBox IOU, TEDS)",
        "tag": "-",
        "reason": "006 은 누름틀 텍스트 치환이라 레이아웃이 설계상 불변이고 HWPX 렌더러도 없다 "
        "— README 에서 제외로 확정.",
    },
    {
        "metric": "PosTagging 품사 비율, 한국어 NER",
        "tag": "-",
        "reason": "형태소/NER 모델 미포함. 고유명사는 라틴 대문자 토큰 + 호출부가 준 목록만 센다.",
    },
]
