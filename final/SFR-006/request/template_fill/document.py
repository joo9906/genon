"""문서 조립 파이프라인 — **서식 → 채우기 → 본문 블록**.

이 순서가 이 파일에 적힌 **단 한 벌**이어야 한다. 예전에는 세 곳에 흩어져 있었다:
코드 서빙의 `_build_document`, 미리보기의 `render_filled`, 그리고 점검 스크립트가 각자
같은 순서를 다시 적었다. 점검 스크립트가 자기가 검증하려는 순서를 스스로 복제하고 있어서,
운영 순서가 바뀌어도 점검은 여전히 통과하는 상태였다.

## 순서에 근거가 있다

1. **서식**(`hwpx_style.apply_styles`) — 슬롯(`{'제목', 16pt}`)을 전용 run 으로 떼어내고
   그 run 에 `charPr` 을 건다. **텍스트는 그대로 둔다.**
2. **채우기**(`hwpx_fields.fill_template`) — 슬롯·누름틀·`{{token}}` 자리에 값을 쓴다.
   1번이 만들어 둔 run 안의 글자만 갈아 끼우므로 서식이 그대로 남는다. 값이 없는 슬롯은
   표기를 지운다(작성 지시문이므로).
3. **본문 블록**(`hwpx_blocks.append_blocks`) — 템플릿 항목 밖의 내용을 이어 붙인다.

**개봉 안전 검사·넘침 측정은 뺐다** (2026-08-12). `hwpx_verify.py`·`overflow.py`와 그
둘이 의존하던 `_vendor/hwpx/`(상류 python-hwpx 사본, opc/oxml/tools/form_fit)를
통째로 지웠다 — 실제 배포 템플릿이 3개뿐이고 전부 표가 없어(넘침 측정은 표 셀 슬롯만
잰다) 두 기능 다 실질적으로 아무 판정도 하지 않는 코드였다. 지운 상태는
`archive/hwpx-genon-vendor` 브랜치에 남아 있다 — 필요해지면
`git show archive/hwpx-genon-vendor:onprem/codeserving/SFR-006_template_fill/template_fill/hwpx_verify.py`
처럼 꺼낸다.

**1번과 2번의 순서는 뒤집을 수 없다.** 슬롯은 값을 채우면 `{…}` 자체가 사라진다 —
채운 뒤에는 어느 자리에 무슨 서식을 걸어야 하는지 알 방법이 없다. (라벨 방식일 때는
`제 목 :` 라벨이 문서에 남아 이름으로 다시 찾을 수 있었고, 그래서 순서가 반대였다.)

같은 이유로 **블록은 서식 원본을 채운 문서가 아니라 1번 결과에서 뜬다**(`style_source`).
채운 문서에는 항목명이 남아 있지 않아 `style_ref` 를 대조할 수 없다.

## 미리보기도 같은 함수를 쓴다

마크다운 미리보기는 `apply_style=False` 로 부를 뿐 나머지는 같다. 서식만 건너뛰는 이유는
마크다운에 글꼴·크기를 담을 자리가 없어서이고, **텍스트 결과는 완전히 같다**(서식 단계는
글자를 건드리지 않는다). 별도 렌더러를 두면 화면과 파일이 어긋난다.

## 실패를 다루는 규율이 단계마다 다르다

- **채우기 실패 → 올린다.** 문서를 못 만든 것이다.
- **서식 실패 → 삼킨다.** 서식은 부가 기능이라, 서식 없는 초안이라도 내려주는 편이 낫다
  (경고 로그는 남긴다).
- **블록 실패 → 올린다.** 블록은 사용자가 직접 쓴 본문이다. 조용히 빠뜨린 문서를 주면
  빠진 줄 모르고 그대로 제출한다.

이 모듈은 HTTP 를 모른다 — `TemplateError` 를 그대로 던지고, 그것을 무슨 응답으로 바꿀지는
호출부(`main.py`)가 정한다.
"""

from dataclasses import dataclass, field as dc_field

from .config import Config
from .hwpx_blocks import append_blocks
from .hwpx_fields import TemplateError, fill_template
from .hwpx_style import apply_styles
from .logging_utils import log_warning


@dataclass
class BuiltDocument:
    """조립 결과 + 각 단계가 무엇을 했는지."""

    hwpx_bytes: bytes
    written_fields: list = dc_field(default_factory=list)   # 값이 기록된 항목명
    missing_fields: list = dc_field(default_factory=list)   # 값이 없어 비워 둔 항목명
    unknown_keys: list = dc_field(default_factory=list)     # 템플릿에 없는 values 키
    leftover_tokens: list = dc_field(default_factory=list)  # 치환되지 않은 {{token}}
    styled_fields: list = dc_field(default_factory=list)    # 서식 명세를 적용한 항목명
    appended_blocks: int = 0                                # 삽입한 본문 문단 수


def build(
    template_bytes: bytes,
    values: dict,
    blocks: list | None = None,
    *,
    label: str = "",
    apply_style: bool = True,
) -> BuiltDocument:
    """템플릿 + 값 + 본문 블록 → 완성된 hwpx 바이트.

    **동기 함수다.** zip 해제·XML 파싱·재직렬화를 여러 번 하므로 async 핸들러는
    `asyncio.to_thread` 로 감싸 부른다 (가이드 6.9절).

    Args:
        values: {항목명: 값}. 템플릿에 없는 키는 기록되지 않고 `unknown_keys` 로 나온다.
        blocks: 템플릿 항목 밖에 이어 쓸 `BodyBlock` 목록.
        label: 로그에 남길 템플릿 식별자 (파일명 등). 값·문서 내용은 남기지 않는다.
        apply_style: 서식 명세를 실제 서식으로 반영할지. 마크다운 미리보기는 False.

    Raises:
        TemplateError: ZIP/XML 손상, 또는 블록을 붙일 자리를 찾지 못한 경우.
    """
    styled: list = []
    styled_template = template_bytes
    if apply_style and Config.APPLY_STYLE_SPEC:
        styled_template, styled = _apply_style_spec(template_bytes, label)

    result = fill_template(styled_template, values, include_slots=Config.SLOT_FIELDS)
    document = result.hwpx_bytes

    appended = 0
    if blocks and Config.BODY_BLOCKS:
        outcome = append_blocks(
            document,
            blocks,
            after=Config.BLOCK_ANCHOR,
            # 서식 원본은 **채우기 전** 문서에서 뜬다 — 모듈 docstring 참고.
            style_source=styled_template,
        )
        document, appended = outcome.hwpx_bytes, outcome.appended

    _warn_on_dropped_input(result, label)

    return BuiltDocument(
        hwpx_bytes=document,
        written_fields=result.written_fields,
        missing_fields=result.missing_fields,
        unknown_keys=result.unknown_keys,
        leftover_tokens=result.leftover_tokens,
        styled_fields=styled,
        appended_blocks=appended,
    )



def _apply_style_spec(template_bytes: bytes, label: str) -> tuple:
    """서식을 반영한다. **실패해도 문서 생성을 막지 않는다.**

    서식은 부가 기능이다. 여기서 예외를 올리면 글자 크기 하나 때문에 초안 전체를 못 받는다.
    실패하면 원본 템플릿을 그대로 돌려주므로 다음 단계(채우기)는 정상 동작한다 —
    서식 없는 초안이 나올 뿐이다.
    """
    try:
        outcome = apply_styles(template_bytes, scope=Config.STYLE_SCOPE)
        return outcome.hwpx_bytes, outcome.applied_fields
    except TemplateError:
        log_warning(
            "서식 명세를 적용하지 못했다 — 서식 미적용 문서로 진행",
            event="style_apply_failed",
            resource_id=label,
        )
    except Exception as exc:  # noqa: BLE001 - 서식이 본 기능을 막지 않게 하는 최종 방어선
        log_warning(
            "서식 적용 중 예상 밖 오류 — 서식 미적용 문서로 진행",
            event="style_apply_error",
            resource_id=label,
            error_type=type(exc).__name__,
        )
    return template_bytes, []


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
