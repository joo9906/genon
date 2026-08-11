"""글다듬이 톤/문서유형 정책.

- 톤 3종: polite(정중함), friendly(친절함), report(간결 및 보고체)
- 문서유형:
  * 자유 선택군: 메일 / 게시글 / 보도자료 / 공문 — 사용자가 3종 중 선택 가능
  * 톤 고정군: 채무 및 연체발생 사유 / 심사역 의견 / 재산 의견 / 고객발송문구
    — 관리자가 지정한 톤만 사용 (사용자가 다른 톤을 보내도 강제 톤으로 대체)

정책은 선언적 딕셔너리로만 관리한다. 관리자 UI(매니페스트 기반 필드 스키마)에서
이 구조를 그대로 내려받아 렌더링할 수 있고, 새 문서유형/톤을 추가할 때
다른 코드를 수정할 필요가 없다.
"""

from dataclasses import dataclass, field

# ── 톤 정의 ───────────────────────────────────────────────

DEFAULT_TONE = "polite"


@dataclass(frozen=True)
class TonePreset:
    label: str
    instruction: str


TONE_PRESETS: dict[str, TonePreset] = {
    "polite": TonePreset(
        label="정중함",
        instruction=(
            "격식 있는 존댓말('~습니다/~합니다')로 다듬는다. "
            "명령형·반말·구어체 표현을 정중한 문어체로 바꾸고, "
            "상대를 존중하는 완곡한 표현을 사용한다."
        ),
    ),
    "friendly": TonePreset(
        label="친절함",
        instruction=(
            "부드럽고 친근한 존댓말로 다듬는다. 딱딱한 한자어와 관공서식 표현은 "
            "쉬운 일상어로 풀어 쓰되 정보 누락은 없어야 한다. "
            "안내·권유 표현('~해 주시면 됩니다', '~하실 수 있습니다')을 활용한다."
        ),
    ),
    "report": TonePreset(
        label="간결 및 보고체",
        instruction=(
            "간결한 보고체('~함', '~임', '~됨' 개조식 종결)로 다듬는다. "
            "중복 수식어와 부연 설명을 제거하고 핵심 정보 위주로 압축하되, "
            "수치·날짜·고유명사 등 사실 정보는 절대 생략하지 않는다."
        ),
    ),
}


def is_valid_tone(value: str | None) -> bool:
    return bool(value) and value in TONE_PRESETS


# ── 문서유형 정책 ─────────────────────────────────────────


@dataclass(frozen=True)
class DocTypePolicy:
    label: str
    # forced_tone이 있으면 톤 고정 — 사용자가 다른 톤을 요청해도 이 톤으로 강제
    forced_tone: str | None = None
    # forced_tone이 없을 때 사용자가 선택 가능한 톤 목록
    allowed_tones: tuple[str, ...] = field(default=("polite", "friendly", "report"))
    # 문서유형별 추가 지시문 (선택)
    extra_instruction: str = ""


DEFAULT_DOC_TYPE = "email"

# forced_tone 값은 관리자가 운영 정책에 맞게 조정하는 부분이다.
# (아래는 초안 기본값 — 실제 강제 톤은 관리자 확정 후 매니페스트/환경설정에서 주입)
DOC_TYPE_POLICIES: dict[str, DocTypePolicy] = {
    # ── 자유 선택군 ──
    "email": DocTypePolicy(
        label="메일",
        extra_instruction="수신자에게 보내는 이메일 형식(인사-본문-맺음말 흐름)을 유지한다.",
    ),
    "post": DocTypePolicy(
        label="게시글",
        extra_instruction="사내/대외 게시글로 읽기 쉽도록 문단 구분을 유지한다.",
    ),
    "press_release": DocTypePolicy(
        label="보도자료",
        extra_instruction="보도자료 관례(핵심 사실 우선, 객관적 서술)를 따른다.",
    ),
    "official_doc": DocTypePolicy(
        label="공문",
        extra_instruction="공문서 형식(항목 번호, 붙임 표기 등 구조)을 훼손하지 않는다.",
    ),
    # ── 톤 고정군 (관리자 지정 톤만 사용) ──
    "debt_reason": DocTypePolicy(
        label="채무 및 연체발생 사유",
        forced_tone="report",
        extra_instruction="사실관계 중심으로 서술하고 주관적 평가·추측 표현을 제거한다.",
    ),
    "reviewer_opinion": DocTypePolicy(
        label="심사역 의견",
        forced_tone="report",
        extra_instruction="심사 판단 근거가 드러나도록 논리 순서를 유지한다.",
    ),
    "asset_opinion": DocTypePolicy(
        label="재산 의견",
        forced_tone="report",
        extra_instruction="금액·자산 내역 등 수치는 원문 그대로 유지한다.",
    ),
    "customer_notice": DocTypePolicy(
        label="고객발송문구",
        forced_tone="polite",
        extra_instruction="법적 고지 문구·필수 안내 항목은 임의로 삭제하거나 완화하지 않는다.",
    ),
}


def normalize_doc_type(value: str | None) -> str:
    key = (value or DEFAULT_DOC_TYPE).strip()
    return key if key in DOC_TYPE_POLICIES else DEFAULT_DOC_TYPE


def resolve_tone(doc_type_raw: str | None, tone_raw: str | None) -> tuple[str, str, bool]:
    """문서유형 정책에 따라 실제 적용할 톤을 결정한다.

    Returns:
        (doc_type_key, tone_key, tone_overridden)
        tone_overridden: 사용자가 요청한 톤이 정책에 의해 다른 톤으로 대체됐는지 여부.
                         True면 응답에 안내 문구를 붙여 사용자에게 알린다.
    """
    doc_type = normalize_doc_type(doc_type_raw)
    policy = DOC_TYPE_POLICIES[doc_type]
    requested = (tone_raw or "").strip()

    if policy.forced_tone:
        overridden = is_valid_tone(requested) and requested != policy.forced_tone
        return doc_type, policy.forced_tone, overridden

    if is_valid_tone(requested) and requested in policy.allowed_tones:
        return doc_type, requested, False

    # 미지정/허용 외 톤 → 허용 목록의 첫 톤(또는 기본 톤)으로 안전하게 대체
    fallback = policy.allowed_tones[0] if policy.allowed_tones else DEFAULT_TONE
    return doc_type, fallback, is_valid_tone(requested)
