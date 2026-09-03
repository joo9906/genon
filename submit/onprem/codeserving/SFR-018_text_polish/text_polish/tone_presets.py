"""글다듬이 톤/문서유형 정책.

**2026-09-03 요구 변경 — 톤 4종·문서유형 5종.**

- 톤 4종: polite(격식·정중) / friendly(친절·안내) / clear(명확·간결) / objective(사실·객관)
  * 옛 `report`(간결 및 보고체, 개조식 `~함/~임`)는 없어졌다. 새 넷은 **전부 존댓말**을
    유지한다 — "명확·간결" 은 문장을 줄이는 것이지 종결어미를 바꾸는 것이 아니다.
  * 옛 값은 `LEGACY_TONE_ALIASES` 가 받는다. 없으면 캔버스에 `report` 가 남아 있는
    배포에서 그 선택이 **조용히 기본 톤(격식·정중)으로 바뀐다.**
- 문서유형 5종:
  * 자유 선택군: 메일 / 게시글 / 고객발송문구 — 네 톤 중 사용자가 고른다
  * 톤 고정군: 채무 및 연체발생 사유 / 심사역 의견 — **사실·객관 고정**
    (사용자가 다른 톤을 보내도 강제 톤으로 대체하고 `tone_overridden` 으로 알린다)
  * 없어진 것: 보도자료 / 공문 / 재산 의견. 고객발송문구는 고정군 → **자유 선택군**
    으로 옮겼다.

정책은 선언적 딕셔너리로만 관리한다. 관리자 UI(매니페스트 기반 필드 스키마)에서
이 구조를 그대로 내려받아 렌더링할 수 있고, 새 문서유형/톤을 추가할 때
다른 코드를 수정할 필요가 없다.
"""

from dataclasses import dataclass

from text_polish import policy_store

# ── 톤 정의 ───────────────────────────────────────────────

DEFAULT_TONE = "polite"


@dataclass(frozen=True)
class TonePreset:
    label: str
    instruction: str


TONE_PRESETS: dict[str, TonePreset] = {
    "polite": TonePreset(
        label="격식·정중",
        instruction=(
            "격식 있는 존댓말('~습니다/~합니다')로 다듬는다. "
            "명령형·반말·구어체 표현을 정중한 문어체로 바꾸고, "
            "상대를 존중하는 완곡한 표현을 사용한다."
        ),
    ),
    "friendly": TonePreset(
        label="친절·안내",
        instruction=(
            "부드럽고 친근한 존댓말로 다듬는다. 딱딱한 한자어와 관공서식 표현은 "
            "쉬운 일상어로 풀어 쓰되 정보 누락은 없어야 한다. "
            "안내·권유 표현('~해 주시면 됩니다', '~하실 수 있습니다')을 활용한다."
        ),
    ),
    "clear": TonePreset(
        label="명확·간결",
        instruction=(
            "짧고 명확한 문장으로 다듬는다. 한 문장에 한 가지만 담고, "
            "군더더기('~에 대하여', '~하는 바입니다')와 중복 수식어를 덜어 낸다. "
            "모호한 표현은 구체적으로 바꾸되 존댓말('~습니다')은 유지하고, "
            "수치·날짜·고유명사는 원문 그대로 둔다."
        ),
    ),
    "objective": TonePreset(
        label="사실·객관",
        instruction=(
            "확인된 사실 중심으로 다듬는다. 주관적 평가·추측·과장 표현"
            "('~인 것 같습니다', '매우', '아쉽게도')을 덜어 내고 근거가 있는 서술만 "
            "남긴다. 존댓말('~습니다')을 유지하며 수치·날짜·고유명사는 원문 그대로 둔다."
        ),
    ),
}

# 없어진 톤 코드 → 지금 코드. **캔버스에 옛 값이 남아 있어도 조용히 기본 톤으로
# 떨어지지 않게** 한다 (2026-09-03). 옛 `report`(간결 및 보고체)의 이름값은 '간결'
# 이므로 `clear` 가 받는다 — 고정군이 쓰던 사실 중심 성격은 `objective` 가 이어받지만,
# 그쪽은 문서유형이 강제하므로 사용자 선택값을 그리로 보낼 이유가 없다.
LEGACY_TONE_ALIASES: dict[str, str] = {"report": "clear"}


def canonical_tone(value: str | None) -> str:
    """옛 톤 코드를 지금 코드로. 아는 값이 아니면 받은 값을 그대로 돌려준다."""
    key = (value or "").strip()
    return LEGACY_TONE_ALIASES.get(key, key)


def is_valid_tone(value: str | None) -> bool:
    return bool(value) and canonical_tone(value) in TONE_PRESETS


def _tone_allowed(tone: str, policy) -> bool:
    """이 문서유형에서 그 톤을 고를 수 있는가. **빈 목록은 제한 없음**이다."""
    return not policy.allowed_tones or tone in policy.allowed_tones


# ── 문서유형 정책 ─────────────────────────────────────────


@dataclass(frozen=True)
class DocTypePolicy:
    label: str
    # forced_tone이 있으면 톤 고정 — 사용자가 다른 톤을 요청해도 이 톤으로 강제
    forced_tone: str | None = None
    # forced_tone 이 없을 때 사용자가 고를 수 있는 톤. **빈 튜플이면 제한 없음**이다
    # (2026-08-18). 예전 기본값은 내장 3종을 적어 둔 닫힌 목록이었는데, 관리자가
    # 프롬프트 라이브러리에 톤을 추가해도 **자유 선택군에서 못 고르는** 상태가 됐다 —
    # 목록에는 뜨는데 고르면 기본 톤으로 되돌아간다(오류 없이). 자유 선택군의 뜻이
    # 원래 "전부 허용" 이므로 빈 튜플로 표현하고, 제한이 필요한 곳만 적는다.
    allowed_tones: tuple[str, ...] = ()
    # 문서유형별 추가 지시문 (선택)
    extra_instruction: str = ""


DEFAULT_DOC_TYPE = "email"

# forced_tone 값은 관리자가 운영 정책에 맞게 조정하는 부분이다.
# (아래는 초안 기본값 — 실제 강제 톤은 관리자 확정 후 매니페스트/환경설정에서 주입)
DOC_TYPE_POLICIES: dict[str, DocTypePolicy] = {
    # ── 자유 선택군 (톤 4종 중 사용자가 고른다) ──
    "email": DocTypePolicy(
        label="메일",
        extra_instruction="수신자에게 보내는 이메일 형식(인사-본문-맺음말 흐름)을 유지한다.",
    ),
    "post": DocTypePolicy(
        label="게시글",
        extra_instruction="사내/대외 게시글로 읽기 쉽도록 문단 구분을 유지한다.",
    ),
    "customer_notice": DocTypePolicy(
        # 2026-09-03: 톤 고정군 → **자유 선택군**으로 옮겼다.
        label="고객발송문구",
        extra_instruction="법적 고지 문구·필수 안내 항목은 임의로 삭제하거나 완화하지 않는다.",
    ),
    # ── 톤 고정군 (사실·객관 고정 — 2026-09-03 요구 확정) ──
    "debt_reason": DocTypePolicy(
        label="채무 및 연체발생 사유",
        forced_tone="objective",
        extra_instruction="사실관계 중심으로 서술하고 주관적 평가·추측 표현을 제거한다.",
    ),
    "reviewer_opinion": DocTypePolicy(
        label="심사역 의견",
        forced_tone="objective",
        extra_instruction="심사 판단 근거가 드러나도록 논리 순서를 유지한다.",
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
    # 옛 코드(`report`)를 지금 코드로 옮긴 뒤 판정한다 — 안 하면 캔버스에 남은 옛 값이
    # "모르는 톤" 이 되어 기본 톤으로 조용히 떨어진다.
    requested = canonical_tone(tone_raw)

    if policy.forced_tone:
        overridden = is_valid_tone(requested) and requested != policy.forced_tone
        return doc_type, policy.forced_tone, overridden

    if is_valid_tone(requested) and _tone_allowed(requested, policy):
        return doc_type, requested, False

    # 미지정/허용 외 톤 → 허용 목록의 첫 톤(또는 기본 톤)으로 안전하게 대체
    fallback = policy.allowed_tones[0] if policy.allowed_tones else DEFAULT_TONE
    return doc_type, fallback, is_valid_tone(requested)


# ── 관리자 정책과의 병합 (2026-08-18) ─────────────────────────
#
# 위 표는 이제 **기본값**이다. 관리자가 GenOS 프롬프트 라이브러리에 등록한 톤·문서유형이
# 그 위에 얹힌다 (`policy_store`). 병합이지 대체가 아니다 — 관리자가 톤 하나만 등록했을
# 때 내장 셋이 사라지면 안 된다. 같은 `code` 면 관리자 것이 이기고, `disabled: true` 면
# 그 항목을 감춘다.
#
# **이 아래 함수들만 쓰고 위 dict 를 직접 읽지 않는다.** 직접 읽으면 관리자가 추가한
# 톤이 그 자리에서만 빠지고, 그 실패는 "톤을 골랐는데 기본 톤으로 나온다" 로만 드러난다.


def _merged_tones() -> dict:
    """`{code: TonePreset}` — 내장 + 관리자. 감춘 항목은 빠진다."""
    merged = dict(TONE_PRESETS)
    for code, item in (policy_store.load().get("tones") or {}).items():
        if item.get("disabled"):
            merged.pop(code, None)
            continue
        merged[code] = TonePreset(label=item["label"], instruction=item["instruction"])
    return merged


def _merged_doc_types() -> dict:
    """`{code: DocTypePolicy}` — 내장 + 관리자. 감춘 항목은 빠진다."""
    merged = dict(DOC_TYPE_POLICIES)
    for code, item in (policy_store.load().get("doc_types") or {}).items():
        if item.get("disabled"):
            merged.pop(code, None)
            continue
        base = merged.get(code)
        # `allowed_tones` 를 안 준 항목은 **내장값을 물려받는다.** 내장에도 없으면
        # 빈 튜플 = 제한 없음이다 (관리자가 추가한 문서유형은 기본이 자유 선택군이다).
        allowed = item.get("allowed_tones") or (base.allowed_tones if base else ())
        merged[code] = DocTypePolicy(
            label=item["label"],
            forced_tone=item.get("forced_tone") or None,
            allowed_tones=tuple(allowed),
            extra_instruction=item.get("extra_instruction", ""),
        )
    return merged


def tone_choices() -> list:
    """`GET /policies` 의 톤 목록. 화면이 이걸로 드롭다운을 그린다."""
    return [{"code": code, "label": preset.label} for code, preset in _merged_tones().items()]


def doc_type_choices() -> list:
    """`GET /policies` 의 문서유형 목록.

    **톤 제약을 함께 낸다** (2026-09-02). 그전에는 `{code, label}` 뿐이라 **문서유형이
    톤을 강제한다는 사실이 계약 어디에도 없었다** — 화면은 톤 3종을 그대로 보여주고,
    사용자가 고른 톤은 `resolve_policy` 가 조용히 바꾼다. 그 대체는 오류가 아니라
    **결과물의 문체로만** 드러난다(`tone_overridden` 은 스텝 1 이 만들지만 payload 로
    나가지 않는다).

    **화면이 문서유형 코드로 표를 들고 있는 것은 답이 아니다.** 강제 톤은 관리자가
    프롬프트 라이브러리에서 바꿀 수 있어(`_merged_doc_types`) 그 순간 화면만 옛 표를
    쥐게 되고, 증상은 똑같이 "고른 톤이 무시된다" 다. 선택지의 원천을 하나로 두는
    `GET /languages` 규약과 같은 이유다.

    ## `allowed_tones` 는 **언제나 실제 목록**이다 (2026-09-02 개정)

    처음에는 내부 표를 그대로 실어 `[]` 가 "제한 없음" 을 뜻했다. **그 규약은 계약으로
    나쁘다** — 내장 문서유형 8개가 전부 빈 튜플이라 그것이 예외가 아니라 **기본 경로**이고,
    화면이 "빈 배열 = 전체" 규칙을 구현하지 않으면 **모든 문서유형에서 드롭다운이 빈다.**
    이제 빈 배열이라는 상태 자체가 없다. 화면 규칙은 한 줄이다 —
    **`allowed_tones` 를 그리고, 하나뿐이면 잠근다.**

    ## `forced_tone` 은 **불리언**이다

    "무엇으로 잠겼나" 는 `allowed_tones` 가 이미 말한다(강제군은 원소가 하나다). 이 값이
    답하는 것은 **왜 하나뿐인가** 다 — 강제라서인지(`true`), 관리자가 허용을 하나만
    적어서인지(`false`). 화면 문구가 갈리는 자리라 남긴다.

    ## 목록을 `resolve_policy` 에서 **파생**시킨다

    표를 다시 읽어 조립하면 판정과 갈릴 수 있고, 그 어긋남은 "화면이 잠근 톤과 실제
    적용 톤이 다르다" — 즉 **사용자가 고른 톤이 조용히 바뀌는** 바로 그 실패다. 그래서
    "고를 수 있다" 를 **판정의 정의 그대로** 계산한다: 그 톤을 보냈을 때 그 톤이 나오는가.

    덤으로 판정이 가진 예외 처리를 공짜로 물려받는다 — 관리자가 지운 톤을 `forced_tone`
    으로 가리키거나(`resolve_policy` 는 존재 확인 후 무시한다) `allowed_tones` 에 없는
    톤만 적어 둔 경우, 표를 베낀 목록은 **고를 수 없는 톤을 보여주게 된다.**

    호출 수는 (문서유형 × 톤)이고 둘 다 `policy_store` 캐시를 지나므로 조회당 수십 번의
    dict 조회다 — `GET /policies` 는 화면을 그릴 때만 불린다.
    """
    tones = _merged_tones()
    return [
        {
            "code": code,
            "label": policy.label,
            # 강제로 **성립하는** 경우만 true — `resolve_policy` 와 같은 존재 확인을 건다.
            # 표에 적혀 있다는 것만으로 true 를 내면 관리자가 그 톤을 지운 순간
            # "잠겼다는데 목록에는 세 개" 가 된다.
            "forced_tone": bool(policy.forced_tone and policy.forced_tone in tones),
            # 보냈을 때 그대로 적용되는 톤 = 고를 수 있는 톤. 강제군은 자연히 하나가 된다.
            "allowed_tones": [t for t in tones if resolve_policy(code, t)[1] == t],
        }
        for code, policy in _merged_doc_types().items()
    ]


def resolve_policy(doc_type_raw: str | None, tone_raw: str | None) -> tuple:
    """`resolve_tone` 과 같은 판정을 하되 **적용할 항목까지** 돌려준다.

    Returns:
        `(doc_type_key, tone_key, tone_overridden, DocTypePolicy, TonePreset)`.

    호출부가 판정 뒤에 표를 다시 뒤지지 않게 하려는 것이다 — 뒤지면 그 자리에서
    내장 dict 를 읽게 되고(`KeyError`), 관리자가 추가한 톤에서만 죽는다.
    """
    tones = _merged_tones()
    doc_types = _merged_doc_types()

    doc_type = (doc_type_raw or DEFAULT_DOC_TYPE).strip()
    if doc_type not in doc_types:
        doc_type = DEFAULT_DOC_TYPE if DEFAULT_DOC_TYPE in doc_types else next(iter(doc_types))
    policy = doc_types[doc_type]
    requested = (tone_raw or "").strip()
    if requested and requested not in tones:
        # 옛 코드(`report`) 구제. **관리자가 같은 이름의 톤을 등록했으면 그쪽이 이긴다**
        # — 위 조건이 그것을 보장한다(등록돼 있으면 별칭을 타지 않는다).
        requested = canonical_tone(requested)
    valid = bool(requested) and requested in tones

    if policy.forced_tone and policy.forced_tone in tones:
        overridden = valid and requested != policy.forced_tone
        return doc_type, policy.forced_tone, overridden, policy, tones[policy.forced_tone]

    if valid and _tone_allowed(requested, policy):
        return doc_type, requested, False, policy, tones[requested]

    # 미지정/허용 외 톤 → 허용 목록의 첫 톤. 관리자가 지운 톤을 가리킬 수 있으므로
    # **존재 확인**을 거친다 — 없으면 기본 톤, 그것도 없으면 남은 첫 톤이다.
    for candidate in tuple(policy.allowed_tones) + (DEFAULT_TONE,) + tuple(tones):
        if candidate in tones:
            return doc_type, candidate, valid, policy, tones[candidate]
    raise KeyError("no tone available")


def policy_source() -> dict:
    """정책을 어디서 받았는지 — `GET /policies` 에 싣는다.

    **관리자가 넣은 톤이 왜 안 보이는지**를 화면에서 답할 수 있어야 한다. 이 값이 없으면
    조회 실패와 "아직 아무것도 등록하지 않음" 이 똑같이 내장 목록으로 보인다.
    """
    loaded = policy_store.load()
    return {
        "source": loaded.get("source", "builtin"),
        "reason": loaded.get("reason", "not_configured"),
        "rejected": dict(loaded.get("rejected") or {}),
    }
