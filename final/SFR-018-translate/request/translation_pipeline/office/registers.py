"""번역 문체(register) 프리셋 — 문어체 / 구어체.

사용자가 대상 언어와 함께 고르는 값이다. 018 글다듬이의 톤 프리셋과 같은 형태로
두되(`tone_presets.py`), 여기는 **번역 문체**라 항목이 둘뿐이다 — 글다듬이의 톤은
한국어 산출물 문체를 고르는 것이고, 이쪽은 "원문의 격식을 어느 쪽으로 옮길지"다.

`instruction` 은 시스템 프롬프트의 `[문체]` 절(`{{ register_instruction }}`)에 그대로
들어간다. 지시문도 프롬프트 본문처럼 한국어로 쓴다 — 출력 언어는 프롬프트가 두
자리에서 못박는다(`system_*.txt` 머리말).

알 수 없는 값이 오면 기본값(문어체)으로 **떨어뜨리되 그 사실을 호출부에 돌려준다** —
조용히 바꾸면 사용자가 고른 문체가 무시된 걸 모른다.
"""

from dataclasses import dataclass

DEFAULT_REGISTER = "written"


@dataclass(frozen=True)
class Register:
    key: str
    label: str          # 프롬프트 `[문체: …]` 자리
    korean_label: str   # 사용자 노출용
    instruction: str


REGISTERS = {
    "written": Register(
        key="written",
        label="격식 있는 문어체",
        korean_label="문어체",
        instruction=(
            "공문서·보고서에 맞는 격식 있는 문어체로 옮깁니다. "
            "완결된 문장, 표준 용어, 비인칭 표현을 씁니다. "
            "축약형, 속어, 대화체 군말은 쓰지 않습니다. "
            "한국어로 옮길 때는 '~하다/~한다' 평서형 또는 '~합니다' 격식체 종결을 "
            "문서 전체에서 한 가지로 맞춥니다."
        ),
    ),
    "spoken": Register(
        key="spoken",
        label="자연스러운 구어체",
        korean_label="구어체",
        instruction=(
            "채팅·안내·말로 전달하기에 맞는 자연스러운 구어체로 옮깁니다. "
            "짧은 문장과 일상 어휘를 쓰되 공손하고 업무에 맞는 말씨를 유지합니다. "
            "한국어로 옮길 때는 '~해요/~예요' 해요체 종결을 문서 전체에서 한 가지로 맞춥니다."
        ),
    ),
}

# 화면·워크플로우 변수 표기 흡수 (언어 별칭과 같은 이유 — 표기 정규화는 한 곳에서)
_ALIASES = {
    "문어체": "written", "formal": "written", "document": "written", "written": "written",
    "구어체": "spoken", "casual": "spoken", "conversational": "spoken", "spoken": "spoken",
}


def resolve_register(value: str) -> tuple:
    """(Register, fell_back) 을 돌려준다.

    fell_back 이 True 면 알 수 없는 값이 와서 기본값을 쓴 것이다. 호출부는 이 사실을
    응답·로그에 노출한다 (사용자가 고른 문체가 조용히 무시되지 않게).
    """
    normalized = (value or "").strip().lower()
    if not normalized:
        return REGISTERS[DEFAULT_REGISTER], False
    key = _ALIASES.get(normalized)
    if key is None:
        return REGISTERS[DEFAULT_REGISTER], True
    return REGISTERS[key], False


def supported_payload() -> list:
    """`GET /languages` 응답에 함께 실어 화면이 선택지를 하드코딩하지 않게 한다.

    **식별자 필드는 `code` 다.** 같은 응답 안의 언어 목록도 `code` 이고 글다듬이
    `/policies` 의 문서유형·톤도 `code` 라서, 프론트가 드롭다운을 그릴 때 목록마다
    다른 키를 읽지 않아도 된다. 선택지 목록은 전부 `{code, label}` 한 모양으로 맞춘다.
    """
    return [
        {"code": register.key, "label": register.korean_label}
        for register in REGISTERS.values()
    ]
