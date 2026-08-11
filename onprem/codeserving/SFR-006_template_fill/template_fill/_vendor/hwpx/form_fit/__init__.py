"""측정 코어만 노출한다 — 상류의 `FitEngine`·`FitPolicy`·`apply` 는 가져오지 않았다.

그쪽은 "넘치면 글꼴을 줄여 다시 맞춘다"(shrink ladder)까지 하는 계층인데, 006 은
**절대 막지도 고치지도 않고 경고만** 한다(`overflow.py`). 쓰지 않을 정책 계층을
들여오면 벤더 사본만 커지고 재동기화 비용이 는다.
"""

from .measure import (  # noqa: F401
    DEFAULT_SAFETY,
    Measurement,
    SlotMetrics,
    measure,
    resolve_slot_metrics,
)

__all__ = [
    "DEFAULT_SAFETY",
    "Measurement",
    "SlotMetrics",
    "measure",
    "resolve_slot_metrics",
]
