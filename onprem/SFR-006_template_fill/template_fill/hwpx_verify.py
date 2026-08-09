"""산출 hwpx 개봉 안전성 검사 — 내보내기 직전의 마지막 관문.

**왜 필요한가.** 이 저장소에는 한/글이 없다. `charPr`·`itemCnt` 한 글자가 틀리면 한/글이
문서를 아예 못 여는데, 우리는 그것을 확인할 수단이 없어서 "생성한 hwpx 를 한/글에서
열어보기" 가 006·FAQ 양쪽에서 미검증으로 남아 있었다. 검사를 붙이면 그 공백이
**한/글 없이** 닫힌다 — 패키지 구조·문서 스키마·재개봉을 코드가 대신 판정한다.

**무엇으로 하는가.** `python-hwpx`(Apache-2.0, 의존성은 lxml 하나)의
`validate_editor_open_safety` 를 부른다. 셋을 한 번에 본다:

- `validate_package` — mimetype/container/manifest/파트 선언 등 OPC 계약
- `validate_document` — OWPML 문서 스키마
- 재개봉 — 산출 바이트를 그 라이브러리가 실제로 다시 열어 본다

**차단과 경고를 나눈다.** 검사기는 오류 중 일부를 advisory 로 분류한다 — 실한컴이
그래도 열어 주는 것이 관측된 항목들이다(파트 XML 선언의 `standalone="yes"` 누락 등).
차단은 **advisory 가 아닌 오류**에만 건다. 이 구분을 무시하고 전부 막으면, 열리는
문서를 못 열린다고 거절하는 쪽으로 틀린다.

**라이브러리가 없는 환경에서는 통과시킨다.** 워크플로우(02) pod 는 `requirements.txt` 를
설치하지 않고 기본 이미지 패키지만 쓴다(가이드 11.5.6). 검사기가 없다는 이유로 문서
생성을 막으면 **검사를 붙였다는 사실 자체가 기능을 죽인다.** 대신 그 상태를 로그로
드러낸다 — `pdf_convert` 가 "변환 수단 없음"과 "변환 실패"를 나누는 것과 같은 규약이고,
검사 없이 지나갔다는 사실을 침묵 처리하지 않는다(§5).

이 모듈은 mock 경로를 두지 않는다(`onprem/` 규칙). 검사기가 있으면 진짜로 검사하고,
없으면 없다고 말한다 — 통과한 척하는 가짜 결과를 만들지 않는다.
"""

from dataclasses import dataclass, field as dc_field

from .logging_utils import log_info, log_warning

# 가용성은 이미지 빌드 시점에 결정되고 런타임에 바뀌지 않는다 — 프로세스당 1회만 본다
# (`pdf_convert.available()` 과 같은 규약).
_AVAILABLE: "bool | None" = None


class OpenSafetyError(RuntimeError):
    """산출 문서가 개봉 안전 검사를 통과하지 못했다.

    계약: 메시지는 이 파일에서 만든 고정 한국어 안내문만 담는다 (3.8절 —
    검사기 원문·문서 내용을 사용자에게 노출하지 않는다).
    """


_FAILED_MSG = "생성한 문서가 한/글 개봉 안전 검사를 통과하지 못했습니다."


@dataclass
class VerifyResult:
    """검사 결과. `checked=False` 면 검사기가 없어 **판정하지 않은** 것이다."""

    checked: bool
    ok: bool = True
    blocking: list = dc_field(default_factory=list)   # 개봉을 막는 오류 (분류 문자열)
    advisory: list = dc_field(default_factory=list)   # 실한컴이 열어 주는 관측 항목
    reopen_ok: bool | None = None


def _load_validator():
    """검사 함수를 가져온다. 없으면 None (미설치는 오류가 아니라 상태다)."""
    try:
        from hwpx.tools.package_validator import validate_editor_open_safety
    except ImportError:
        return None
    return validate_editor_open_safety


def available() -> bool:
    """이 환경에서 개봉 안전 검사를 할 수 있는가."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    _AVAILABLE = _load_validator() is not None
    if not _AVAILABLE:
        log_warning(
            "개봉 안전 검사기(python-hwpx)가 없어 산출물 검증 없이 진행한다",
            event="open_safety_unavailable",
            status="unavailable",
        )
    return _AVAILABLE


def _issue_kinds(messages) -> list:
    """검사기 메시지를 **분류 이름만** 남긴다.

    원문에는 파트명·수치 같은 문서 내부 정보가 섞이므로 그대로 로그·응답에 싣지
    않는다(3.8절). 파트명(콜론 앞)만 취하면 어디가 문제인지는 알면서 내용은 새지 않는다.
    """
    kinds = []
    for message in messages:
        head = str(message).split(":", 1)[0].strip()
        if head and head not in kinds:
            kinds.append(head)
    return kinds


def verify(hwpx_bytes: bytes, label: str = "") -> VerifyResult:
    """산출 바이트를 검사한다. **판정만 하고 예외를 던지지 않는다.**

    막을지 말지는 호출부(`document.build`)가 정한다 — 이 모듈은 미리보기처럼 막으면
    안 되는 경로에서도 쓰일 수 있어야 한다.
    """
    validate = _load_validator()
    if validate is None:
        available()  # 최초 1회 경고를 남긴다
        return VerifyResult(checked=False)

    try:
        report = validate(hwpx_bytes).to_dict()
    except Exception as exc:  # noqa: BLE001 - 검사기 내부 예외가 문서 생성을 막지 않게
        log_warning(
            "개봉 안전 검사 중 예외 — 검사 없이 진행",
            event="open_safety_error",
            resource_id=label,
            error_type=type(exc).__name__,
        )
        return VerifyResult(checked=False)

    package = report.get("validatePackage", {})
    blocking = _issue_kinds(package.get("blockingErrors", []))
    advisory = _issue_kinds(
        [
            message
            for message in package.get("errors", [])
            if message not in package.get("blockingErrors", [])
        ]
    )
    document = report.get("validateDocument", {})
    if not document.get("ok", True):
        blocking.append("document-schema")
    reopen = report.get("reopen", {})
    if not reopen.get("ok", False):
        blocking.append("reopen")

    return VerifyResult(
        checked=True,
        ok=not blocking,
        blocking=blocking,
        advisory=advisory,
        reopen_ok=bool(reopen.get("ok", False)),
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
    )
    return result
