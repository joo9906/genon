"""onprem 배포 단위를 import 할 수 있게 `sys.path` 를 세운다.

**이 파일이 이 디렉토리의 존재 이유다.** 예전에는 `SFR-006/template_fill/` 에 구현
**사본**이 있었고 테스트가 그 사본을 검증했다. 사본은 자동 동기화되지 않으므로,
운영 코드(`onprem/`)를 고쳐도 테스트는 옛 코드를 통과시켰다 — 실제로 그렇게 갈렸다:

| 사본에만 있던 것 | 실제 |
|---|---|
| `field_judge.mock_extract` | onprem 에 없다 (배포 단위에 mock 경로를 두지 않는다) |
| `hwpx_fields.scan_tokens` | 슬롯 문법 전환으로 없어졌다 |
| `parse_updates -> (dict, list)` | 지금은 `ParsedIntent` 를 돌려준다 |

그래서 사본을 지우고 **onprem 을 직접 태운다** (2026-08-11). 이제 테스트가 깨지면
그것은 운영 코드가 바뀐 것이고, 그게 회귀 테스트가 해야 할 일이다.

## 왜 경로를 여기 한 곳에서만 만드는가

재배치(2026-08-11)로 단위가 `onprem/codeserving/` 아래로 한 겹 내려갔을 때
`SFR-006/smoke/fixture.py` 가 옛 경로를 들고 있어 **스모크 6개가 전부 죽어 있었다.**
경로를 파일마다 적으면 다음 이동 때 같은 일이 반복된다.
"""

import os
import sys

# 저장소 루트 = 이 파일의 2단계 상위 (SFR-006/tests/onprem_path.py)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UNIT_ROOT = os.path.join(REPO_ROOT, "onprem", "codeserving", "SFR-006_template_fill")


def install() -> str:
    """`template_fill` 패키지를 import 가능하게 만든다. 단위 루트 경로를 돌려준다."""
    if not os.path.isdir(os.path.join(UNIT_ROOT, "template_fill")):
        raise RuntimeError(
            f"onprem 단위를 찾지 못했다: {UNIT_ROOT}\n"
            "배포 단위가 옮겨졌다면 이 파일의 UNIT_ROOT 만 고치면 된다."
        )
    if UNIT_ROOT not in sys.path:
        sys.path.insert(0, UNIT_ROOT)
    return UNIT_ROOT


install()
