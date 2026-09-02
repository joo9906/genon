"""평가 입력 쌍(원문 ↔ 결과)의 **계약** — 별칭 해석과 빈 입력 판정을 한 곳에서 한다.

## 왜 생겼나 — 다섯 집계기가 각자 다른 키를 읽고 있었다

같은 `pairs` 를 받는데 읽는 키가 제각각이었다:

| 집계기 | 원문으로 읽던 키 | 결과로 읽던 키 |
|---|---|---|
| `structure_pass_rate` | `original` | `result` |
| `_aggregate_facts` | `source` → `original` | `target` → `result` |
| `_aggregate_glossary` | `source` | `target` |
| `_aggregate_ending` | — | `result` → `target` |
| 톤 집계 | — | `result` |

**그래서 키 이름을 하나로 통일해 주면 일부 지표만 조용히 빈 문자열을 채점했다.**
실측(2026-08-30): `pairs=[{"source": …, "target": …}]` 을 주면
`polish_structure_pass_rate` 가 `""` 와 `""` 를 비교해 **pass_rate 1.0** 을 냈고,
`{"original": …, "result": …}` 을 주면 `glossary_compliance` 가 원문을 `""` 로 읽어
**측정 불가(not_measured)** 로 빠졌다. 둘 다 예외를 던지지 않는다.

가드레일에서 이 실패 모드가 제일 나쁘다 — **아무것도 재지 않고 통과라고 말한다.**

## 계약

- 원문 키는 `source` 또는 `original`, 결과 키는 `target` 또는 `result` 다.
- **원문이 비어 있으면 예외다.** 원문 없이는 어떤 대조도 성립하지 않으므로 그 입력은
  채점 대상이 아니라 호출자 실수다 (조용히 0점이나 만점을 주지 않는다).
- **결과가 비어 있는 것은 예외가 아니라 불합격이다.** 다듬기·번역이 아무것도 내놓지
  못한 것은 실제 실패이고, 지표가 그것을 잡아내야 한다.
- **표시용 `<mark>` 는 여기서 벗긴다** (2026-09-02). 운영 payload 에 남은 텍스트는
  하이라이트가 입혀진 사본이고 정본은 파일로만 있다 — 태그를 그대로 채점하면 어미
  판정이 `other` 로 떨어져 톤·어미 지표가 **미측정으로 조용히 빠진다.**
  벗기는 자리를 이 한 곳으로 모은 이유는 다섯 집계기가 전부 여기를 지나기 때문이다
  (각자 벗기게 두면 이 파일이 생긴 이유였던 그 드리프트가 되풀이된다).
"""

from .error_codes import ERR_PAIR_NOT_A_MAPPING, ERR_PAIR_SOURCE_MISSING, fail
from .normalize import strip_display_tags

SOURCE_KEYS = ("source", "original")
RESULT_KEYS = ("target", "result")


def _first(pair: dict, keys: tuple) -> str:
    for key in keys:
        value = pair.get(key)
        if value:
            return strip_display_tags(str(value))
    return ""


def pair_texts(pair, index: int = 0) -> tuple:
    """`(원문, 결과)`. 원문이 없으면 예외를 던진다.

    Args:
        pair: `{"source"|"original": …, "target"|"result": …}`
        index: 오류 로그에 남길 항목 번호 (값은 남기지 않는다 — 3.8절).

    Returns:
        (source, result). `result` 는 빈 문자열일 수 있다 (= 결과물이 없다 = 불합격).
    """
    if not isinstance(pair, dict):
        fail(ERR_PAIR_NOT_A_MAPPING, event="pair_not_a_mapping", item_count=index)
    source = _first(pair, SOURCE_KEYS)
    if not source.strip():
        fail(ERR_PAIR_SOURCE_MISSING, event="pair_source_missing", item_count=index)
    return source, _first(pair, RESULT_KEYS)


def pair_id(pair: dict, index: int):
    """항목 식별자 — 없으면 순번. 리포트·게이트 표본이 이 값으로 재현된다."""
    ident = pair.get("id") if isinstance(pair, dict) else None
    return ident if ident is not None else index
