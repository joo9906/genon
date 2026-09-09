"""문서 조립 파이프라인 — **채우기 → 본문 블록** (`not/` 판본, 2026-09-08).

> **이 파일은 `onprem/codeserving/SFR-006_template_fill/` 의 한시 판본이다.** 정본은
> 그쪽이고, 사내 PyPI mirror 에 `lxml` 이 들어오면 이 디렉토리를 통째로 버린다.
> 무엇을 왜 뺐는지는 `not/README.md`.

## 정본과 다른 점 — **서식 단계가 없고, 산출물이 txt 다**

정본의 순서는 **서식 → 채우기 → 본문 블록** 셋이었다. 여기서는 둘이다:

1. **채우기**(`hwpx_fields.fill_sections`) — 슬롯·누름틀·`{{token}}` 자리에 값을 쓴다.
   값이 없는 슬롯은 표기를 지운다(작성 지시문이므로). **정본과 같은 코드, 같은 판정.**
2. **본문 블록**(`hwpx_blocks.plan_blocks`) — 템플릿 항목 밖의 내용을 이어 붙인다.

빠진 것은 **서식**(`hwpx_style.apply_styles`)이고, 그 파일 자체가 이 판본에 없다.
`{'제목', 16pt, 고딕, 볼드}` 의 `16pt` 를 걸 곳이 txt 에는 없기 때문이다 — 정본에서
서식이 "부가 기능이라 실패해도 삼킨다" 였던 것과 같은 성질이고, 여기서는 아예 하지
않는다. **`styled_fields` 는 언제나 빈 목록**이고 그 사실을 이 자리에 적어 둔다:
값을 그럴듯하게 채워 두면 화면이 "서식이 걸렸다"고 읽는다.

## 순서를 뒤집을 수 없는 이유는 그대로다

슬롯은 값을 채우면 `{…}` 자체가 사라진다. 그래서 **블록의 서식 원본은 채운 문서가
아니라 템플릿 원본에서 뜬다**(`style_source=template_bytes`) — 채운 문서에는 어느
문단이 '제목' 이었는지 알 방법이 없다. txt 라서 서식을 안 쓰는데도 이 배선을 유지하는
이유는 `plan_blocks` 의 주석에 적었다 (이름 검사가 화면 선택지와 갈리면 안 된다).

## 산출물이 바이트가 아니다

`BuiltDocument.hwpx_bytes` 는 **없다.** 대신 `section_roots`(값이 채워진 XML 트리)와
블록 계획이 나가고, 글자로 만드는 것은 `to_text()` 다. 이름을 그대로 두면 호출부가
그 값을 파일로 착각해 그대로 내려보내고, 그러면 **열리지 않는 hwpx** 가 다운로드된다.

이 모듈은 HTTP 를 모른다 — `TemplateError` 를 그대로 던지고, 그것을 무슨 응답으로 바꿀지는
호출부(`main.py`)가 정한다.
"""

from dataclasses import dataclass, field as dc_field

from .config import Config
from .hwpx_blocks import plan_blocks
from .hwpx_fields import TemplateError, fill_sections
from .logging_utils import log_warning


@dataclass
class BuiltDocument:
    """조립 결과 + 각 단계가 무엇을 했는지."""

    # 값이 채워진 섹션 트리 (문서 순서). 정본의 `hwpx_bytes` 자리다 — 이름이 다른
    # 이유는 모듈 docstring 참고.
    section_roots: list = dc_field(default_factory=list)
    block_paragraphs: list = dc_field(default_factory=list)  # 이어 붙일 문단 글
    block_anchor_para: object = None      # 이 문단 뒤에 넣는다 (None 이면 맨 끝)
    written_fields: list = dc_field(default_factory=list)   # 값이 기록된 항목명
    missing_fields: list = dc_field(default_factory=list)   # 값이 없어 비워 둔 항목명
    unknown_keys: list = dc_field(default_factory=list)     # 템플릿에 없는 values 키
    leftover_tokens: list = dc_field(default_factory=list)  # 치환되지 않은 {{token}}
    # **언제나 빈 목록이다** (이 판본에는 서식 단계가 없다). 계약을 유지하려고 남긴다 —
    # 없애면 정본과 응답 모양이 갈려 화면이 두 벌이 된다.
    styled_fields: list = dc_field(default_factory=list)
    appended_blocks: int = 0                                # 삽입한 본문 문단 수


def build(
    template_bytes: bytes,
    values: dict,
    blocks: list | None = None,
    *,
    label: str = "",
    apply_style: bool = True,
) -> BuiltDocument:
    """템플릿 + 값 + 본문 블록 → **채워진 트리 + 블록 계획**.

    **동기 함수다.** zip 해제·XML 파싱을 여러 번 하므로 async 핸들러는
    `asyncio.to_thread` 로 감싸 부른다 (가이드 6.9절).

    Args:
        values: {항목명: 값}. 템플릿에 없는 키는 기록되지 않고 `unknown_keys` 로 나온다.
        blocks: 템플릿 항목 밖에 이어 쓸 `BodyBlock` 목록.
        label: 로그에 남길 템플릿 식별자 (파일명 등). 값·문서 내용은 남기지 않는다.
        apply_style: **이 판본에서는 무시한다.** 서식 단계가 없다. 인자를 지우지 않는
            이유는 호출부가 정본과 같아야 하기 때문이다 — 미리보기는
            `apply_style=False` 로 부르고, 그 호출이 여기서 터지면 안 된다.

    Raises:
        TemplateError: ZIP/XML 손상, 또는 블록을 붙일 자리를 찾지 못한 경우.
    """
    result = fill_sections(template_bytes, values, include_slots=Config.SLOT_FIELDS)

    paragraphs: list = []
    anchor_para = None
    appended = 0
    if blocks and Config.BODY_BLOCKS:
        outcome = plan_blocks(
            result.sections,
            blocks,
            after=Config.BLOCK_ANCHOR,
            # 서식 원본은 **채우기 전** 문서에서 뜬다 — 모듈 docstring 참고.
            style_source=template_bytes,
        )
        paragraphs = outcome.paragraphs
        anchor_para = outcome.anchor_para
        appended = outcome.appended

    _warn_on_dropped_input(result, label)

    return BuiltDocument(
        section_roots=[root for _name, root in result.sections],
        block_paragraphs=paragraphs,
        block_anchor_para=anchor_para,
        written_fields=result.written_fields,
        missing_fields=result.missing_fields,
        unknown_keys=result.unknown_keys,
        leftover_tokens=result.leftover_tokens,
        styled_fields=[],
        appended_blocks=appended,
    )


def to_text(template_bytes: bytes, built: BuiltDocument, *, max_chars: int | None = None) -> str:
    """조립 결과를 **내려받을 txt 본문**으로 만든다.

    **미리보기와 같은 렌더러를 쓴다** (`hwpx_markdown.render_roots`). 정본이 미리보기와
    다운로드를 같은 조립 경로에 태워 "화면에는 보이는데 파일에는 없는" 상태를 구조적으로
    막았던 것과 같은 이유다 — 여기서 렌더러를 하나 더 만들면 그 보장이 사라진다.

    `import` 를 함수 안에서 하는 이유는 순환 때문이다: `hwpx_markdown` 이 이 모듈의
    `build` 를 쓴다.
    """
    from .hwpx_markdown import HEADER_ENTRY, read_entry, render_roots

    rendered = render_roots(
        read_entry(template_bytes, HEADER_ENTRY),
        built.section_roots,
        max_chars=max_chars,
        extra_after=(built.block_anchor_para, built.block_paragraphs),
    )
    return rendered.markdown


def _warn_on_dropped_input(result, label: str) -> None:
    """문서에 못 들어간 입력을 로그로 노출한다 (침묵 처리 금지 — §5).

    둘 다 "사용자가 말한 값이 문서에 안 들어갔다" 는 신호라 운영에서 잡아야 한다.
    """
    if result.unknown_keys:
        log_warning(
            "템플릿에 없는 키가 있어 기록하지 못했다",
            event="generate_unknown_keys",
            resource_id=label,
            item_count=len(result.unknown_keys),
        )
    if result.leftover_tokens:
        log_warning(
            "치환되지 않은 토큰이 남았다",
            event="generate_leftover_tokens",
            resource_id=label,
            item_count=len(result.leftover_tokens),
        )


__all__ = ["BuiltDocument", "TemplateError", "build", "to_text"]
