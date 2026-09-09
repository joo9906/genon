"""표준 라이브러리 XML 층 — `lxml` 자리를 메운다 (`not/` 판본, 2026-09-08).

> **이 파일은 정본(`onprem/`)에 없다.** 사내 PyPI mirror 에 `lxml` 이 없어 코드 서빙
> 배포가 막혀 만든 한시 판본의 일부다. mirror 에 `lxml` 이 들어오면 이 파일과 함께
> `not/SFR-006_template_fill/` 을 통째로 버리고 정본으로 돌아간다.

## 왜 이 얇은 층이 필요한가

`hwpx_fields`·`hwpx_markdown`·`hwpx_blocks` 가 실제로 쓰는 lxml API 는 **다섯뿐**이다:

| lxml | 표준 `xml.etree.ElementTree` |
|---|---|
| `etree.fromstring` | 그대로 있다 |
| `etree.SubElement` | 그대로 있다 |
| `etree.XMLSyntaxError` | 이름만 다르다 (`ParseError`) |
| `etree.tostring` | 있지만 **쓰지 않는다** (아래) |
| `elem.getparent()` | **없다** ← 이 파일이 메우는 것 |

즉 갈아 끼울 것은 실질적으로 `getparent()` 하나다.

## 부모 맵 — lxml 보다 오히려 안전하다

정본 `hwpx_fields.py` 에는 "**lxml 프록시 id 는 붙들어야 유효하다**"는 주석이 있다.
lxml 요소는 C 트리 위의 일회용 프록시라 참조를 놓으면 회수되고 `id()` 가 재사용되어,
`{id(elem): 위치}` 맵이 **조용히 엉뚱한 요소를 가리키게** 된다.

표준 ElementTree 에는 그 함정이 없다 — 트리가 요소 객체를 직접 들고 있으므로 요소를
그대로 dict 키로 쓸 수 있고(기본 해시 = 동일성), `WeakKeyDictionary` 라 트리가 사라지면
항목도 함께 사라진다. **즉 이 층은 기능을 흉내 내는 것이 아니라 같은 판정을 더 단순한
수단으로 하는 것이다.**

## 되쓰기는 하지 않는다 — `tostring` 을 감싸지 않은 이유

이 판본은 **hwpx 를 다시 봉하지 않는다**(산출물이 txt 다). 표준 ElementTree 로 hwpx 파트를
재직렬화하려면 문서가 쓰는 네임스페이스 접두어를 **전부** `register_namespace` 로 되살려야
하고, 하나라도 놓치면 `ns0:` 로 나가 **한/글이 열지 못하는 파일**이 된다 — 예외가 나지
않고 산출물만 깨지는 형태다. 그래서 그 문을 아예 열지 않는다. 재직렬화가 필요해지면
`lxml` 이 돌아온 것이므로 정본을 쓴다.
"""

from __future__ import annotations

import weakref
import xml.etree.ElementTree as _ET

# 정본이 `etree.XMLSyntaxError` 로 잡던 것. 표준 라이브러리의 이름만 다르다.
XMLSyntaxError = _ET.ParseError

SubElement = _ET.SubElement
Element = _ET.Element

# 자식 → 부모. 요소가 회수되면 항목도 함께 사라진다 (문서 하나가 요청 하나이므로
# 이 맵이 요청 사이에 남으면 그대로 누수다).
_PARENTS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def fromstring(xml_bytes: bytes):
    """파싱하면서 **부모 맵을 함께 만든다.**

    맵을 나중에 따로 만들지 않는 이유: 만드는 자리를 호출부에 맡기면 한 곳만 빠뜨려도
    그 트리에서 `parent_of` 가 조용히 `None` 을 돌려준다 — `nearest_para` 가 `None` 이
    되어 **문단 소유 판정이 전부 빗나가고**, 그 결과는 오류가 아니라 "라벨을 못 찾는다"
    로만 드러난다. 파싱과 묶어 두면 빠뜨릴 자리가 없다.
    """
    root = _ET.fromstring(xml_bytes)
    index_parents(root)
    return root


def index_parents(root) -> None:
    """`root` 아래 전체의 부모 관계를 등록한다 (구조를 바꾼 뒤 다시 부른다)."""
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node:
            _PARENTS[child] = node
            stack.append(child)


def register(child, parent) -> None:
    """요소 하나를 새로 끼워 넣은 직후 부모를 등록한다.

    `index_parents` 를 통째로 다시 부르는 것보다 싸고, **무엇보다 빠뜨리면 그 자리에서
    드러난다** — 새 요소의 `parent_of` 가 `None` 이라 곧바로 문단을 못 찾는다.
    """
    _PARENTS[child] = parent


def parent_of(elem):
    """lxml `elem.getparent()` 자리. 뿌리이거나 등록되지 않았으면 `None`."""
    return _PARENTS.get(elem)
