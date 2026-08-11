"""산출 hwpx 개봉 안전성 검사 — 내보내기 직전의 마지막 관문.

**왜 필요한가.** 이 저장소에는 한/글이 없다. `charPr`·`itemCnt` 한 글자가 틀리면 한/글이
문서를 아예 못 여는데, 우리는 그것을 확인할 수단이 없어서 "생성한 hwpx 를 한/글에서
열어보기" 가 006·FAQ 양쪽에서 미검증으로 남아 있었다. 검사를 붙이면 그 공백이
**한/글 없이** 닫힌다 — 패키지 구조와 문서 루트를 코드가 대신 판정한다.

**무엇으로 하는가.** 둘을 본다.

- `validate_package` — mimetype/container/manifest/파트 XML 선언·표 필수 자식·secCnt
  대조 등 OPC·OWPML 계약. 벤더 사본(`_vendor/hwpx/tools/package_validator.py`)이고,
  한컴 산출물 corpus 에 맞춰 조정된 판정이라 우리가 다시 만들 이유가 없다.
- `_check_document_roots` — header/section 파트의 **루트 요소와 필수 속성**. 이건 우리
  코드다. 상류 `validate_document` 가 쓰던 XSD 두 장이 실제로는 이 정도만 단언하고
  (`head@version`·`head@secCnt` 필수, 자식은 전부 `xs:any lax`), 그것 하나 때문에
  `HwpxDocument` 와 lxml XMLSchema 를 끌어올 이유가 없었다.

**재개봉(reopen)은 하지 않는다 — 그리고 했다고 말하지 않는다.** 상류
`validate_editor_open_safety` 의 세 번째 검사는 산출 바이트를 그 라이브러리로 실제 다시
열어 보는 것이었다. 그 검사의 가치는 *다른 코드베이스가* 우리 출력을 파싱한다는 데
있으므로, 우리 파서로 대신하면 구조상 통과하는 항등식이 된다 — 없는 것보다 나쁘다.
그래서 검사를 지우고 `VerifyResult.reopen_checked=False` 와 통과 로그의
`reopen=not_checked` 로 **미판정을 통과와 구분해** 드러낸다. 근거는 `_vendor/README.md`.

**차단과 경고를 나눈다.** 검사기는 오류 중 일부를 advisory 로 분류한다 — 실한컴이
그래도 열어 주는 것이 관측된 항목들이다(파트 XML 선언의 `standalone="yes"` 누락 등).
차단은 **advisory 가 아닌 오류**에만 건다. 이 구분을 무시하고 전부 막으면, 열리는
문서를 못 열린다고 거절하는 쪽으로 틀린다.

이 모듈은 mock 경로를 두지 않는다(`onprem/` 규칙). 검사기는 이미지에 항상 들어 있으므로
(pip 의존이 아니라 벤더 사본이다) "검사기가 없어 통과시켰다" 는 상태 자체가 사라졌다.
끄는 수단은 `TEMPLATE_FILL_VERIFY_OUTPUT=0` 하나뿐이고, 그건 검사기가 정상 문서를 오판해
운영이 막힐 때의 탈출구다.
"""

from dataclasses import dataclass, field as dc_field

from lxml import etree

from ._vendor.hwpx.tools.package_validator import (
    is_editor_open_blocking_issue,
    validate_package,
)
from .hwpx_fields import parse_xml, open_hwpx, section_order
from .hwpx_style import HEADER_ENTRY
from .logging_utils import log_info, log_warning


class OpenSafetyError(RuntimeError):
    """산출 문서가 개봉 안전 검사를 통과하지 못했다.

    계약: 메시지는 이 파일에서 만든 고정 한국어 안내문만 담는다 (3.8절 —
    검사기 원문·문서 내용을 사용자에게 노출하지 않는다).
    """


_FAILED_MSG = "생성한 문서가 한/글 개봉 안전 검사를 통과하지 못했습니다."


@dataclass
class VerifyResult:
    """검사 결과. `checked=False` 면 검사 중 예외가 나 **판정하지 않은** 것이다."""

    checked: bool
    ok: bool = True
    blocking: list = dc_field(default_factory=list)   # 개봉을 막는 오류 (분류 문자열)
    advisory: list = dc_field(default_factory=list)   # 실한컴이 열어 주는 관측 항목
    # 재개봉은 **구조적으로** 하지 않는다 (모듈 docstring). 상수 False 인 것이 맞고,
    # 필드로 남겨 둔 이유는 "검사했는데 실패" 와 "검사 안 함" 을 호출부가 구분할 수
    # 있어야 하기 때문이다 — 나중에 진짜 독립 검사기가 생기면 여기가 True 가 된다.
    reopen_checked: bool = False


def _issue_kinds(issues) -> list:
    """검사기 메시지를 **분류 이름만** 남긴다.

    원문에는 파트명·수치 같은 문서 내부 정보가 섞이므로 그대로 로그·응답에 싣지
    않는다(3.8절). 파트명(콜론 앞)만 취하면 어디가 문제인지는 알면서 내용은 새지 않는다.
    """
    kinds = []
    for issue in issues:
        head = str(issue).split(":", 1)[0].strip()
        if head and head not in kinds:
            kinds.append(head)
    return kinds


def _check_document_roots(hwpx_bytes: bytes) -> list:
    """header/section 파트의 루트 요소와 필수 속성을 본다. 문제 분류 목록을 낸다.

    상류 `validate_document` 의 XSD 를 대신한다. 그 XSD 가 단언하던 것 전부다 —
    `hh:head` 루트에 `version`·`secCnt`(음이 아닌 정수), `hs:sec` 루트. 자식 요소는
    XSD 에서도 `xs:any processContents="lax"` 라 검사 대상이 아니었다.

    **네임스페이스는 보지 않고 지역명만 본다.** XSD 는 2011 네임스페이스로 고정돼
    있었지만, 그 규칙을 그대로 옮기면 2016/2024 네임스페이스로 저장된 정상 문서를
    거절한다 — 이 모듈이 피하려는 바로 그 방향의 오판이다. 네임스페이스 선언 자체는
    `validate_package` 가 advisory 로 이미 본다.
    """
    problems: list = []
    with open_hwpx(hwpx_bytes) as archive:
        names = set(archive.namelist())

        if HEADER_ENTRY not in names:
            problems.append("header-missing")
        else:
            head = parse_xml(archive.read(HEADER_ENTRY))
            if etree.QName(head).localname != "head":
                problems.append("header-root")
            else:
                if not (head.get("version") or "").strip():
                    problems.append("header-version")
                sec_count = (head.get("secCnt") or "").strip()
                if not sec_count.isdigit():
                    problems.append("header-secCnt")

        sections = sorted(name for name in names if section_order(name) is not None)
        if not sections:
            problems.append("section-missing")
        for name in sections:
            root = parse_xml(archive.read(name))
            if etree.QName(root).localname != "sec":
                problems.append("section-root")
                break
    return problems


def verify(hwpx_bytes: bytes, label: str = "") -> VerifyResult:
    """산출 바이트를 검사한다. **판정만 하고 예외를 던지지 않는다.**

    막을지 말지는 호출부(`document.build`)가 정한다 — 이 모듈은 미리보기처럼 막으면
    안 되는 경로에서도 쓰일 수 있어야 한다.
    """
    try:
        report = validate_package(hwpx_bytes)
        blocking = _issue_kinds(
            issue for issue in report.errors if is_editor_open_blocking_issue(issue)
        )
        advisory = _issue_kinds(
            issue for issue in report.errors if not is_editor_open_blocking_issue(issue)
        )
        blocking.extend(_check_document_roots(hwpx_bytes))
    except Exception as exc:  # noqa: BLE001 - 검사기 내부 예외가 문서 생성을 막지 않게
        log_warning(
            "개봉 안전 검사 중 예외 — 검사 없이 진행",
            event="open_safety_error",
            resource_id=label,
            error_type=type(exc).__name__,
        )
        return VerifyResult(checked=False)

    return VerifyResult(
        checked=True,
        ok=not blocking,
        blocking=blocking,
        advisory=advisory,
    )


def enforce(hwpx_bytes: bytes, label: str = "") -> VerifyResult:
    """검사하고, 개봉을 막는 오류가 있으면 **문서를 내보내지 않는다**(fail-closed).

    advisory 는 막지 않고 로그로만 남긴다 — 실한컴이 열어 주는 것이 관측된 항목이라
    여기서 막으면 정상 문서를 거절하게 된다.

    Raises:
        OpenSafetyError: 개봉을 막는 오류가 있음.
    """
    result = verify(hwpx_bytes, label)
    if not result.checked:
        return result

    if result.advisory:
        log_warning(
            "산출 문서에 개봉 권고사항이 있다 (열림에는 지장 없음)",
            event="open_safety_advisory",
            resource_id=label,
            item_count=len(result.advisory),
        )
    if not result.ok:
        log_warning(
            "산출 문서가 개봉 안전 검사에 실패해 내보내지 않는다",
            event="open_safety_blocked",
            resource_id=label,
            item_count=len(result.blocking),
        )
        raise OpenSafetyError(_FAILED_MSG)

    log_info(
        "산출 문서 개봉 안전 검사 통과",
        event="open_safety_passed",
        resource_id=label,
        # 무엇을 보고 통과시켰는지 남긴다 — "통과" 를 "한/글로 열어 봤다" 로 읽지
        # 않게 하는 것이 이 문자열의 목적이다 (모듈 docstring 의 재개봉 절).
        status="package+roots reopen=not_checked",
    )
    return result
