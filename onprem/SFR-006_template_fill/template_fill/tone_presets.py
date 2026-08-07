"""문서 값·본문에 적용할 톤 정책 (018 글다듬이 프리셋의 사본).

요구사항: 템플릿을 채울 때 지정된 톤(문체)을 문서 내용에 적용한다. 즉 **018 글다듬이를
006 산출물에 적용하는 것**이 목적이고, 이 파일은 그 정책의 006 쪽 사본이다.

**018 text_polish/tone_presets.py 의 톤 3종(label·instruction)과 글자 단위로 같아야 한다.**
배포 단위 간 import 금지 규칙 때문에 사본으로 둘 수밖에 없으므로, 어긋남을 사람 기억에
맡기지 않고 **`python onprem/test/check_tone_policy.py` 가 대조**한다 (그 스크립트는 배포
단위 바깥이라 세 벌을 모두 읽을 수 있다). 톤 문구를 바꾸면 018 원본을 고치고 이 대조를 돌린다.
사본은 셋이다 — 018(원본), 여기, 그리고 eval/eval_mcp/tone_metrics.py.

**문서유형 정책(DOC_TYPE_POLICIES·forced_tone)은 가져오지 않는다** (2026-08-06 결정).
018 은 "메일/공문/심사역 의견" 처럼 입력 글의 종류를 사용자가 고르지만, 006 은 **템플릿
자체가 문서 종류를 정한다** — 관리자가 올린 `주간보고.hwpx` 를 쓰는 순간 문서유형이
확정되므로 사용자가 다시 고를 것이 없다. 필요해지면 템플릿 등록 시 문서유형을 함께
지정하는 쪽이 맞다(그때는 템플릿 메타데이터 저장이 새로 필요하다).

기본값은 **톤 미적용**이다. 톤 변수가 없으면 변환 단계를 아예 건너뛴다 —
문서에 들어갈 값을 LLM 이 다시 쓰는 것은 되돌릴 수 없는 변형이므로, 관리자가
명시적으로 켰을 때만 동작해야 한다(opt-in).
"""

from dataclasses import dataclass


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


def resolve_tone(tone_raw: str | None) -> str:
    """워크플로우 변수로 들어온 톤 키를 확정한다. 미지정/오타면 빈 문자열(=톤 미적용)."""
    key = (tone_raw or "").strip()
    return key if key in TONE_PRESETS else ""
