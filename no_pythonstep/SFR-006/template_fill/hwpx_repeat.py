"""반복 묶음 — 템플릿의 `{'본문 1'}`·`{'내용 1-1'}` 구간을 입력 분량만큼 늘린다.

## 무엇을 하나

공문은 `본문+내용`, 보도자료는 `본문+요약+내용` 이 한 묶음이고, 들어온 정보·파일이
많으면 그 묶음이 `본문 1 / 본문 2 / …` 로 늘어나야 한다. 묶음 안의 세부 내용도
묶음마다 개수가 다르다 — 본문 1 은 내용이 셋, 본문 2 는 하나일 수 있다.

```
템플릿(관리자가 1벌만 적는다)        산출물
  {'본문 1'}                          본문 1 / 내용 1-1 / 내용 1-2 / 내용 1-3
    {'내용 1-1'}             ──▶      본문 2 / 내용 2-1
```

## 템플릿 규칙 (관리자가 지키는 것)

- 이름이 **`1` 로 끝나는 슬롯**이 묶음 항목이다(`본문 1`, `본문1`). **`1-1` 로 끝나면**
  묶음 안에서 다시 늘어나는 세부 항목이다(`내용 1-1`). 템플릿에는 **1번만** 적는다.
- **묶음 구간**은 묶음 항목을 가진 첫 최상위 문단부터 마지막 최상위 문단까지다 — 사이의
  글자·빈 줄·표가 함께 복제된다. 세부 구간도 같은 방식으로 그 안에서 정한다.
- 들여쓰기·줄간격은 **문단 모양(paraPr)째 복제**되므로 템플릿에서 들여 둔 그대로 나온다.
  한/글 자동 번호 문단도 복제본에서 번호가 저절로 이어진다.

## 값은 평범한 `{항목명: 값}` 이다

`본문 2`·`내용 2-3` 을 **그냥 항목 이름**으로 다룬다. 세션·자동 채움·커밋·화면 편집·
프론트 payload 가 `{항목명: 값}` 그대로라 묶음 기능이 그쪽으로 번지지 않는다.
**묶음 개수는 따로 저장하지 않는다** — 값이 든 가장 큰 번호가 개수다(`counts`). 개수와
값을 따로 들면 둘이 어긋날 자리가 생긴다.

## 문서 조립에서의 자리

`document.build` 의 **맨 앞**이다: 복제 → 서식 → 채우기 → 블록. 복제는 슬롯 **이름만**
`1` → `k` 로 바꾸고 서식 인자(`14pt` 등)는 그대로 두므로, 뒤의 세 단계는 늘어난 문서를
처음부터 그렇게 생긴 템플릿으로 보고 지금 코드 그대로 돈다.

## 반복으로 보지 않는 경우 (등록 경고로 알린다)

- 같은 이름의 `2` 이상(`본문 2`)이 이미 적혀 있다 — 관리자가 번호를 고정해 둔 문서다.
  늘린 이름과 부딪히므로 반복을 끄고 지금처럼 고정 항목으로 채운다.
- 묶음 항목이 섹션 둘에 걸쳐 있다.
- 세부 구간 안에 묶음 항목이 섞여 있다 — 세부 반복만 끄고 묶음 반복은 한다.

이 모듈은 `hwpx_fields` 와 같은 성질이다 — **Config·GenOS 런타임 의존이 없다.**
상한은 호출부가 인자로 준다.
"""

import io
import re
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field as dc_field, replace

from .hwpx_fields import (
    HP_NS,
    iter_section_xml,
    open_hwpx,
    owns_any,
    parse_xml,
    rewrite_slots,
    section_order,
    serialize_part,
    slot_occurrences,
)

_PARA = f"{{{HP_NS}}}p"
_FIELD_BEGIN = f"{{{HP_NS}}}fieldBegin"
_SEC_PR = f"{{{HP_NS}}}secPr"
_CTRL = f"{{{HP_NS}}}ctrl"

# 복제본에서 버리는 **쪽 단위** 제어. 섹션 첫 문단이 구간에 걸리면 이것들이 함께 따라오는데,
# 복제하면 단 정의·머리말·쪽 번호가 묶음마다 다시 선언된다. 자동 번호(`autoNum`)는
# 표·그림 캡션 번호라 남긴다.
_PAGE_CTRLS = frozenset(
    f"{{{HP_NS}}}{tag}"
    for tag in ("colPr", "header", "footer", "pageNum", "pageNumCtrl", "pageHiding", "newNum")
)

# 이름 끝 번호. 앞 글자가 숫자·하이픈이면 번호의 일부라 묶음 이름으로 보지 않는다
# (`2024 1`, `1-1` 의 앞쪽 `1`). 공백은 관리자가 쓴 그대로 보존한다(`본문1` ↔ `본문 1`).
_INNER_RE = re.compile(r"^(?P<base>.*?[^\d\s\-])(?P<sep>\s*)(?P<k>\d+)-(?P<j>\d+)$")
_OUTER_RE = re.compile(r"^(?P<base>.*?[^\d\s\-])(?P<sep>\s*)(?P<k>\d+)$")


@dataclass(frozen=True)
class RepeatMember:
    """묶음 항목 하나 — 템플릿에 적힌 1번 이름과, 번호를 바꿔 끼울 틀."""

    name: str      # 템플릿에 적힌 그대로 (`본문 1`, `내용 1-1`)
    base: str      # `본문`
    sep: str       # 이름과 번호 사이 공백 (없을 수 있다)
    inner: bool    # 세부 항목(`k-j`)인가

    def name_for(self, k: int, j: int = 1) -> str:
        if self.inner:
            return f"{self.base}{self.sep}{k}-{j}"
        return f"{self.base}{self.sep}{k}"

    def parse(self, key: str):
        """이 항목의 늘린 이름이면 `(k, j)`, 아니면 None. 바깥 항목의 j 는 1 이다."""
        pattern = _INNER_RE if self.inner else _OUTER_RE
        match = pattern.match(key)
        if match is None or match.group("base") != self.base or match.group("sep") != self.sep:
            return None
        k = int(match.group("k"))
        j = int(match.group("j")) if self.inner else 1
        if k < 1 or j < 1:
            return None
        return k, j


@dataclass(frozen=True)
class RepeatGroup:
    """템플릿 하나의 반복 묶음 (문서당 하나). 색인에 들어가는 것은 이것뿐이다."""

    members: tuple            # RepeatMember, 문서 등장 순서
    inner_repeatable: bool    # 세부 항목을 묶음마다 늘릴 수 있는가

    @property
    def outer(self) -> list:
        return [m for m in self.members if not m.inner]

    @property
    def inner(self) -> list:
        return [m for m in self.members if m.inner]

    @property
    def template_names(self) -> set:
        return {m.name for m in self.members}

    def _parse_key(self, key: str):
        for member in self.members:
            parsed = member.parse(key)
            if parsed is not None:
                return member, parsed
        return None

    def counts(self, values: dict, max_outer: int, max_inner: int) -> list:
        """값으로부터 묶음 수와 묶음별 세부 수를 정한다. `[M_1, …, M_N]`.

        **값이 든 가장 큰 번호가 개수다.** 빈 값은 세지 않는다. 묶음은 최소 1개 —
        템플릿에 적힌 1번 자리는 늘 있다. 상한 밖 번호는 무시한다(화이트리스트가 이미
        걸렀어야 하는 값이다).
        """
        inner: dict = {}
        for key, value in (values or {}).items():
            if not str(value or "").strip():
                continue
            found = self._parse_key(str(key))
            if found is None:
                continue
            member, (k, j) = found
            if not 1 <= k <= max_outer:
                continue
            if member.inner and not 1 <= j <= self._inner_cap(max_inner):
                continue
            inner[k] = max(inner.get(k, 1), j if member.inner else 1)
        total = max(inner, default=1)
        return [inner.get(k, 1) for k in range(1, total + 1)]

    def _inner_cap(self, max_inner: int) -> int:
        return max_inner if self.inner_repeatable else 1

    def allowed_names(self, max_outer: int, max_inner: int) -> set:
        """상한 안에서 쓸 수 있는 모든 이름 (값 화이트리스트에 더한다)."""
        names: set = set()
        for k in range(1, max_outer + 1):
            for member in self.outer:
                names.add(member.name_for(k))
            for j in range(1, self._inner_cap(max_inner) + 1):
                for member in self.inner:
                    names.add(member.name_for(k, j))
        return names

    def copy_names(self, k: int, inner_count: int) -> list:
        """묶음 k 의 항목 이름 — 바깥 항목은 세부 구간 앞뒤로, 세부 항목은 j 순서로."""
        before, after, seen_inner = [], [], False
        for member in self.members:
            if member.inner:
                seen_inner = True
            elif seen_inner:
                after.append(member)
            else:
                before.append(member)
        names = [m.name_for(k) for m in before]
        for j in range(1, inner_count + 1):
            names.extend(m.name_for(k, j) for m in self.inner)
        names.extend(m.name_for(k) for m in after)
        return names

    def expand_specs(self, specs: list, values: dict, max_outer: int, max_inner: int,
                     extra_copy: bool = False) -> list:
        """템플릿 항목 목록(1번만 있는 것)을 지금 값의 묶음 수만큼 편다.

        묶음 항목은 **첫 묶음 항목이 있던 자리**에 묶음 순서대로 들어간다. 묶음 밖 항목은
        제자리다. `extra_copy` 면 묶음 하나를 더 편다(자동 채움이 새 주제를 넣을 자리).
        """
        by_name = {spec.name: spec for spec in specs}
        counts = self.counts(values, max_outer, max_inner)
        if extra_copy and len(counts) < max_outer and self._used(values):
            counts = counts + [1]
        group_specs: list = []
        for k, inner_count in enumerate(counts, start=1):
            for name in self.copy_names(k, inner_count):
                template = by_name.get(self._template_name(name))
                if template is None:
                    continue
                guide = name if template.guide == template.name else template.guide
                group_specs.append(replace(template, name=name, guide=guide))

        result: list = []
        placed = False
        for spec in specs:
            if spec.name in self.template_names:
                if not placed:
                    result.extend(group_specs)
                    placed = True
                continue
            result.append(spec)
        return result

    def _used(self, values: dict) -> bool:
        """묶음 1번에라도 값이 있는가 — 비어 있으면 1번 자리가 곧 새 자리다."""
        return any(
            str(value or "").strip() and self._parse_key(str(key)) is not None
            for key, value in (values or {}).items()
        )

    def used_count(self, values: dict, max_outer: int, max_inner: int) -> int:
        """값이 든 묶음 수 (0 일 수 있다 — 프롬프트의 "다음 번호" 계산용)."""
        return len(self.counts(values, max_outer, max_inner)) if self._used(values) else 0

    def _template_name(self, name: str) -> str:
        found = self._parse_key(name)
        return found[0].name if found else ""

    def compact(self, values: dict) -> dict:
        """빈 묶음·빈 세부 번호를 당겨 번호를 1부터 촘촘하게 다시 매긴다.

        "2번 묶음 지워줘" 는 그 묶음 항목을 전부 비우는 것으로 들어온다. 당기지 않으면
        빈 2번이 문서에 남고 `ready` 가 영영 안 된다. 묶음 밖 키는 그대로다.
        """
        grouped: dict = {}
        others: dict = {}
        for key, value in (values or {}).items():
            found = self._parse_key(str(key)) if str(value or "").strip() else None
            if found is None:
                others[key] = value
                continue
            member, (k, j) = found
            grouped.setdefault(k, []).append((member, j, value))

        result = dict(others)
        for new_k, old_k in enumerate(sorted(grouped), start=1):
            items = grouped[old_k]
            inner_order = sorted({j for member, j, _ in items if member.inner})
            renumber = {old: new for new, old in enumerate(inner_order, start=1)}
            for member, j, value in items:
                if member.inner:
                    result[member.name_for(new_k, renumber[j])] = value
                else:
                    result[member.name_for(new_k)] = value
        return result

    def to_payload(self) -> dict:
        return {
            "members": [
                {"name": m.name, "base": m.base, "sep": m.sep, "inner": m.inner}
                for m in self.members
            ],
            "inner_repeatable": self.inner_repeatable,
        }

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("members"), list):
            return None
        members = []
        for item in payload["members"]:
            if not isinstance(item, dict) or not item.get("name"):
                return None
            members.append(
                RepeatMember(
                    name=str(item["name"]),
                    base=str(item.get("base") or ""),
                    sep=str(item.get("sep") or ""),
                    inner=bool(item.get("inner")),
                )
            )
        if not members:
            return None
        return cls(members=tuple(members), inner_repeatable=bool(payload.get("inner_repeatable")))


@dataclass
class RepeatScan:
    """템플릿 스캔 결과. 복제에 필요한 위치는 여기에만 있고 색인에는 안 들어간다."""

    group: RepeatGroup | None = None
    warnings: list = dc_field(default_factory=list)
    section: str = ""
    span: tuple = ()          # (첫, 끝) 최상위 문단 인덱스 — 섹션 루트 자식 기준
    inner_span: tuple = ()    # 세부 구간. 비어 있으면 세부 반복 없음


def _classify(name: str):
    """슬롯 이름 → `(member, k, j)` 또는 None. 번호가 몇이든 받는다(2 이상 검출용)."""
    match = _INNER_RE.match(name)
    if match:
        member = RepeatMember(name=name, base=match.group("base"), sep=match.group("sep"), inner=True)
        return member, int(match.group("k")), int(match.group("j"))
    match = _OUTER_RE.match(name)
    if match:
        member = RepeatMember(name=name, base=match.group("base"), sep=match.group("sep"), inner=False)
        return member, int(match.group("k")), 1
    return None


def _top_paragraphs(root) -> list:
    return [(index, child) for index, child in enumerate(root) if child.tag == _PARA]


def _slot_names(para) -> list:
    """최상위 문단 하나(표 셀 안 문단 포함)의 슬롯 이름. 누름틀 문단은 슬롯 경로가 안 본다."""
    names: list = []
    for inner_para in para.iter(_PARA):
        if owns_any(inner_para, _FIELD_BEGIN):
            continue
        names.extend(occ.name for occ in slot_occurrences(inner_para))
    return names


def _scan_section(root) -> list:
    """`[(루트 자식 인덱스, [슬롯 이름…])]` — 슬롯이 있는 최상위 문단만."""
    found: list = []
    for index, para in _top_paragraphs(root):
        names = _slot_names(para)
        if names:
            found.append((index, names))
    return found


def scan_repeat(hwpx_bytes: bytes) -> RepeatScan:
    """템플릿에서 반복 묶음을 찾는다. 없으면 `group=None`.

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    sections = [(name, parse_xml(xml)) for name, xml in iter_section_xml(hwpx_bytes)]
    return _scan_roots(sections)


def _scan_roots(sections: list) -> RepeatScan:
    numbered: dict = {}       # (base, sep, inner) → 번호 집합
    members: dict = {}        # 1번 이름 → (member, 섹션, 문단 인덱스 목록)
    order: list = []
    other_slots: list = []    # (섹션, 문단 인덱스, 이름)
    for section_name, root in sections:
        for index, names in _scan_section(root):
            for name in names:
                found = _classify(name)
                if found is None:
                    other_slots.append((section_name, index, name))
                    continue
                member, k, j = found
                numbered.setdefault((member.base, member.sep, member.inner), set()).add((k, j))
                if (k, j) != (1, 1):
                    other_slots.append((section_name, index, name))
                    continue
                if name not in members:
                    members[name] = (member, set(), [])
                    order.append(name)
                members[name][1].add(section_name)
                members[name][2].append((section_name, index))

    if not order:
        return RepeatScan()

    warnings: list = []
    fixed = sorted(
        f"{base}{sep}{'k-j' if inner else 'k'}"
        for (base, sep, inner), numbers in numbered.items()
        if any(number != (1, 1) for number in numbers)
        and any(members[n][0].base == base and members[n][0].sep == sep for n in order)
    )
    if fixed:
        warnings.append(
            "번호 2 이상이 이미 적힌 항목이 있어 반복 묶음으로 보지 않았습니다: " + ", ".join(fixed)
        )
        return RepeatScan(warnings=warnings)

    section_names = {s for name in order for s in members[name][1]}
    if len(section_names) > 1:
        warnings.append("반복 묶음 항목이 여러 구역에 나뉘어 있어 반복으로 보지 않았습니다.")
        return RepeatScan(warnings=warnings)
    section = section_names.pop()

    outer_rows = [i for n in order if not members[n][0].inner for _, i in members[n][2]]
    inner_rows = [i for n in order if members[n][0].inner for _, i in members[n][2]]
    rows = outer_rows + inner_rows
    span = (min(rows), max(rows))

    inner_span: tuple = ()
    if inner_rows:
        candidate = (min(inner_rows), max(inner_rows))
        if any(candidate[0] <= row <= candidate[1] for row in outer_rows):
            warnings.append(
                "세부 항목(…1-1) 구간 안에 묶음 항목이 섞여 있어 세부 항목은 늘리지 않습니다."
            )
        else:
            inner_span = candidate

    loose = sorted({
        name for s, index, name in other_slots if s == section and span[0] <= index <= span[1]
    })
    if loose:
        warnings.append(
            "반복 구간 안에 번호 없는 항목이 있어 모든 묶음에 같은 값이 들어갑니다: "
            + ", ".join(loose)
        )

    # 문서 등장 순서. 문단 안 순서는 슬롯 순서를 따른다(`order` 가 이미 그 순서다).
    group = RepeatGroup(
        members=tuple(members[name][0] for name in order),
        inner_repeatable=bool(inner_span),
    )
    return RepeatScan(
        group=group, warnings=warnings, section=section, span=span, inner_span=inner_span
    )


# ─────────────────────────────────────────────────────────────
# 복제
# ─────────────────────────────────────────────────────────────
def _rename_slots(paras: list, mapping: dict) -> None:
    """문단들(표 셀 안 포함)의 슬롯 이름을 바꾼다. 서식 인자·중괄호 밖 글자는 그대로다."""
    if not mapping:
        return
    for para in paras:
        for inner_para in list(para.iter(_PARA)):
            if owns_any(inner_para, _FIELD_BEGIN):
                continue
            occurrences = slot_occurrences(inner_para)
            texts = []
            for occ in occurrences:
                new_name = mapping.get(occ.name)
                if new_name is None:
                    texts.append(None)
                    continue
                at = occ.raw.index(occ.name)  # 첫 등장은 따옴표 안 이름이다 (`{` + 따옴표 뒤)
                texts.append(occ.raw[:at] + new_name + occ.raw[at + len(occ.name):])
            if any(text is not None for text in texts):
                rewrite_slots(inner_para, occurrences, texts)


class _IdIssuer:
    """복제본의 개체 id(표·그림)를 문서 안에서 겹치지 않게 새로 준다.

    문단 id 는 원래 전부 같은 값이라(규칙 문서 §3.2) 건드리지 않는다.
    """

    def __init__(self, roots: list) -> None:
        top = 0
        for root in roots:
            for elem in root.iter():
                value = elem.get("id")
                if elem.tag != _PARA and value and value.isdigit():
                    top = max(top, int(value))
        self._next = top + 1

    def refresh(self, para) -> None:
        for elem in para.iter():
            value = elem.get("id")
            if elem.tag != _PARA and value and value.isdigit():
                elem.set("id", str(self._next))
                self._next += 1


def _sanitize(para) -> None:
    """복제본에서 구역 정의와 쪽 단위 제어를 뗀다 (원본 1벌에만 있어야 하는 것)."""
    for elem in list(para.iter(_SEC_PR)):
        elem.getparent().remove(elem)
    for ctrl in list(para.iter(_CTRL)):
        if len(ctrl) and all(child.tag in _PAGE_CTRLS for child in ctrl):
            ctrl.getparent().remove(ctrl)


def _clone(paras: list, issuer: _IdIssuer) -> list:
    copies = [deepcopy(p) for p in paras]
    for para in copies:
        _sanitize(para)
        issuer.refresh(para)
    return copies


def _build_copy(group: RepeatGroup, paras: list, inner_rel: tuple, k: int,
                inner_count: int, issuer: _IdIssuer, fresh: bool) -> list:
    """묶음 k 한 벌. `fresh` 가 거짓이면 원본 문단을 그대로 고쳐 쓴다(1번 묶음)."""
    copy = _clone(paras, issuer) if fresh else list(paras)
    if inner_rel:
        start, end = inner_rel
        inner_paras = copy[start:end + 1]
        # 복제를 이름 바꾸기보다 **먼저** 다 해 둔다 — 바꾼 뒤에 뜨면 복제본이 이미
        # `내용 2-1` 을 들고 있어 템플릿 이름(`내용 1-1`)으로 다시 찾을 수 없다.
        pieces = [inner_paras] + [_clone(inner_paras, issuer) for _ in range(inner_count - 1)]
        expanded: list = []
        for j, piece in enumerate(pieces, start=1):
            _rename_slots(piece, {m.name: m.name_for(k, j) for m in group.inner})
            expanded.extend(piece)
        copy = copy[:start] + expanded + copy[end + 1:]
        outer_mapping = {m.name: m.name_for(k) for m in group.outer}
    else:
        outer_mapping = {m.name: m.name_for(k) for m in group.members}
    _rename_slots(copy, outer_mapping)
    return copy


def expand_repeats(hwpx_bytes: bytes, values: dict, *, max_outer: int, max_inner: int) -> bytes:
    """값의 묶음 수만큼 묶음 구간을 복제한 템플릿 바이트. 반복이 없으면 입력 그대로다.

    결과는 **템플릿**이다 — 슬롯은 아직 `{'본문 2', 14pt}` 로 남아 있고, 채우기는
    다음 단계(`fill_template`)가 한다.

    Raises:
        TemplateError: ZIP/XML 손상.
    """
    with open_hwpx(hwpx_bytes) as src:
        entries = [(item, src.read(item.filename)) for item in src.infolist()]
    roots = {
        item.filename: parse_xml(data)
        for item, data in entries
        if section_order(item.filename) is not None
    }
    ordered = sorted(roots.items(), key=lambda pair: section_order(pair[0]))
    scan = _scan_roots(ordered)
    if scan.group is None:
        return hwpx_bytes
    counts = scan.group.counts(values, max_outer, max_inner)
    if counts == [1]:
        return hwpx_bytes  # 1번 한 벌 — 템플릿 이름 그대로 채운다

    root = roots[scan.section]
    children = list(root)
    start, end = scan.span
    span_paras = children[start:end + 1]
    inner_rel = (
        (scan.inner_span[0] - start, scan.inner_span[1] - start) if scan.inner_span else ()
    )
    issuer = _IdIssuer(list(roots.values()))

    built: list = []
    for k, inner_count in enumerate(counts, start=1):
        built.extend(
            _build_copy(scan.group, span_paras, inner_rel, k, inner_count, issuer, fresh=k > 1)
        )

    anchor = start
    for para in span_paras:
        root.remove(para)
    for offset, para in enumerate(built):
        root.insert(anchor + offset, para)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item, data in entries:
            if item.filename == scan.section:
                data = serialize_part(root)
            compress = (
                zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
            )
            dst.writestr(item.filename, data, compress_type=compress)
    return buf.getvalue()
