"""다듬기 결과의 **사실 정보 보존**을 결정적으로 확인한다 — 숫자와 날짜.

`markdown_guard` 의 짝이다. 그쪽은 표·제목·코드펜스 같은 **구조**를 보고, 이쪽은 문장 안의
**값**을 본다. 둘 다 "프롬프트 지시를 보장으로 치지 않는다" 는 같은 규율에서 나왔다.

## 왜 필요했나

이 가드가 붙기 전까지 글다듬이는 네 배포 단위 중 **유일하게 사실 보존을 재지 않았다.**

| 단위 | 가드 | 보는 것 |
|---|---|---|
| SFR-006 | `value_guard` | 숫자·날짜 (톤 변환 조각) |
| SFR-018 번역 | `numeric_guard` | 숫자 (번역 유닛) |
| SFR-018 FAQ | `evidence` | 근거 문장 원문 대조 |
| SFR-018 글다듬이 | `markdown_guard` **뿐이었다** | 구조만 |

톤 프리셋(`tone_presets.py`)에 "수치·날짜·고유명사 등 사실 정보는 절대 생략하지 않는다" 는
지시가 있지만 그건 지시일 뿐이다. 루트 README 018 지표 §2 는 숫자·날짜 교차 대조를
글다듬이·번역 **공통의 1차 방어선이자 운영 지표**로 적어 두었고, `eval` 의
`fact_preservation_check` 는 글다듬이 스위트에서 `pass_rate == 1.0` 을 요구한다.
운영이 그걸 재지 않으면 **평가는 통과인데 운영은 깨진** 상태가 된다 — 006 `value_guard`
머리말에 이미 적혀 있는 문장이다.

## 되돌리지 않고 알린다 — 006 과 다른 점

006 은 불일치한 필드의 **원본 값을 유지**한다. 항목 값이 조각이라 그 조각만 되돌리면
되기 때문이다. 글다듬이는 문서 전체를 한 덩어리로 다시 쓰므로 되돌리면 기능 자체가
사라진다. 그래서 `markdown_guard` 와 같은 규율을 쓴다 — **결과는 그대로 전달하고 경고를
노출한다.** 판단은 원문을 아는 사용자가 한다.

## 숫자·날짜만 본다 (단위·고유명사 제외)

`eval` 의 `cross_check_facts` 는 넷을 본다(숫자·날짜·단위·고유명사). 운영 가드는 그중
**둘만** 쓴다. 정의가 갈린 게 아니라 의도한 부분집합이고, 이유는 오탐 비용이 서로 다르기
때문이다 — 평가에서 오탐은 점수 한 칸이지만, 운영에서 오탐은 **모든 결과에 붙는 경고**이고
그러면 사용자가 경고를 읽지 않게 된다.

- **단위 제외.** 글다듬이의 본업 중 하나가 띄어쓰기 교정이다. `1,250만원` → `1,250만 원`
  은 정확히 이 기능이 해야 하는 교정인데, 단위 추출로 보면 `만원` 이 사라지고 `원` 이
  생긴 것으로 잡힌다. 숫자(`1250`)는 양쪽에서 같으므로 값 보존은 이미 확인된다.
- **고유명사 제외.** 라틴 대문자 휴리스틱이라(형태소 분석기 없음) 한국어 고유명사는 어차피
  못 잡고, 잡히는 것은 영문 약어뿐이다. 문장을 다시 쓰면서 `GenOS 는` → `GenOS가` 같은
  변화에도 흔들린다.

날짜는 **표준형으로 비교**한다. `2026. 3. 12.` 과 `2026년 3월 12일` 은 같은 값이고, 표기를
바꾸는 것은 다듬기의 정당한 일이라 감점 대상이 아니다.

## 경고에 값을 담는다

`markdown_guard` 의 안내문은 값이 없는 고정 문구지만, 여기서는 **어떤 숫자·날짜가
어긋났는지**를 넣는다. 긴 문서에서 "숫자가 다릅니다" 만으로는 어디를 봐야 할지 알 수 없다.
그 값은 사용자 자신의 원문에서 온 것이고, 경고가 실리는 곳은 이미 문서 전문이 들어 있는
채팅 답변이다. **로그에는 개수만 남긴다**(3.8절) — 값이 나가는 곳은 사용자 답변뿐이다.
"""

import re

_NUMBER_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")
# 날짜 표기 네 가지. 긴 형식을 먼저 두어 부분 표기가 중복으로 잡히지 않게 한다.
_DATE_RES = (
    re.compile(r"\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}"),
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월"),
    re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일"),
)
# 경고에 나열할 값의 최대 개수. 표가 든 문서에서 수십 개가 어긋나면 안내문이 답변을
# 덮는다 — 앞의 몇 개만 보이고 나머지는 개수로 알린다.
_SAMPLE_LIMIT = 5


def _normalize(text: str) -> str:
    """공백을 하나로 접는다. 다듬기는 줄바꿈·들여쓰기를 자유롭게 바꾼다."""
    return re.sub(r"\s+", " ", text or "")


def _canonical_date(token: str) -> str:
    """날짜 표기를 표준형으로. 표기 차이는 사실 왜곡이 아니다."""
    parts = [int(p) for p in re.findall(r"\d+", token)]
    if len(parts) == 3:
        return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    if len(parts) == 2:
        # 연-월(4자리 시작)인지 월-일인지로 구분한다
        return f"{parts[0]:04d}-{parts[1]:02d}" if parts[0] > 31 else f"{parts[0]:02d}-{parts[1]:02d}"
    return token.strip()


def extract_dates(text: str) -> list:
    """날짜를 표준형으로, 등장 순서대로."""
    body = _normalize(text)
    found: list = []
    spans: list = []
    for pattern in _DATE_RES:
        for match in pattern.finditer(body):
            if any(start <= match.start() < end for start, end in spans):
                continue  # 더 긴 형식에 이미 포함된 부분 표기
            spans.append((match.start(), match.end()))
            found.append(_canonical_date(match.group(0)))
    return found


def _strip_dates(text: str) -> str:
    """숫자 대조에서 날짜 구간을 뺀다.

    날짜는 따로 재므로 이중 계산이고, 표기가 바뀌면(`2026-03-12` ↔ `2026년 3월 12일`)
    구성 숫자의 개수가 달라져 숫자 불일치로 잘못 번진다.
    """
    body = _normalize(text)
    for pattern in _DATE_RES:
        body = pattern.sub(" ", body)
    return body


def extract_numbers(text: str) -> list:
    """날짜를 뺀 본문의 수치. 자릿수 구분 콤마는 제거해 `1,250` 과 `1250` 을 같게 본다."""
    return [m.group(0).replace(",", "") for m in _NUMBER_RE.finditer(_strip_dates(text))]


def _diff(source: list, result: list) -> tuple:
    """다중집합 차이 — (원문에서 사라진 것, 결과에만 새로 생긴 것).

    집합이 아니라 다중집합이다. `47명 중 47명` 이 `47명 중 12명` 이 되는 경우처럼
    **개수가 줄어든 것도 손실**이라 집합 비교로는 놓친다.
    """
    remaining = list(result)
    dropped = []
    for item in source:
        if item in remaining:
            remaining.remove(item)
        else:
            dropped.append(item)
    return dropped, remaining


def _describe(kind: str, dropped: list, added: list) -> str:
    """어긋난 값을 담은 한 줄 안내문."""
    parts = []
    if dropped:
        shown = ", ".join(dropped[:_SAMPLE_LIMIT])
        more = f" 외 {len(dropped) - _SAMPLE_LIMIT}건" if len(dropped) > _SAMPLE_LIMIT else ""
        parts.append(f"원문에 있던 {kind} {shown}{more} 이(가) 결과에 없습니다.")
    if added:
        shown = ", ".join(added[:_SAMPLE_LIMIT])
        more = f" 외 {len(added) - _SAMPLE_LIMIT}건" if len(added) > _SAMPLE_LIMIT else ""
        parts.append(f"원문에 없던 {kind} {shown}{more} 이(가) 결과에 생겼습니다.")
    return " ".join(parts)


def find_fact_issues(original: str, polished: str) -> list:
    """숫자·날짜 보존을 대조해 안내문 목록을 반환한다 (없으면 빈 리스트).

    `markdown_guard.find_structure_issues` 와 같은 계약이다 — 판정만 하고 결과를
    바꾸지 않는다. 되돌릴지 다시 요청할지는 호출부와 사용자가 정한다.
    """
    issues = []
    for kind, source, result in (
        ("숫자", extract_numbers(original), extract_numbers(polished)),
        ("날짜", extract_dates(original), extract_dates(polished)),
    ):
        dropped, added = _diff(source, result)
        if dropped or added:
            issues.append(_describe(kind, dropped, added))
    return issues


def fact_issue_counts(original: str, polished: str) -> dict:
    """로그용 — 값 없이 종류별 개수만 (3.8절)."""
    counts = {}
    for kind, source, result in (
        ("numbers", extract_numbers(original), extract_numbers(polished)),
        ("dates", extract_dates(original), extract_dates(polished)),
    ):
        dropped, added = _diff(source, result)
        counts[kind] = len(dropped) + len(added)
    return counts
