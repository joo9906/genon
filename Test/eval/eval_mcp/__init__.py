"""genon 평가지표 MCP 패키지.

계산 로직(metrics 모듈)은 MCP 런타임에 의존하지 않으므로 스크립트·노트북에서
그대로 import 해 쓸 수 있다. MCP 서버는 server.py 의 얇은 어댑터 층뿐이다.
"""

__all__ = [
    "catalog",
    "gating",
    "normalize",
    "numeric_metrics",
    "scenario_metrics",
    "structure_metrics",
    "text_metrics",
    "tone_metrics",
]
