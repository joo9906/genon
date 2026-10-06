"""`final/` 배포 단위를 import 할 수 있게 `sys.path` 를 세운다.

**이 파일이 이 디렉토리의 존재 이유다.** 테스트는 구현 **사본**이 아니라 **등록하는
코드(`final/SFR-006/request/`)를 직접 태운다.** 사본은 자동 동기화되지 않으므로, 사본을
검증하면 운영 코드를 고쳐도 테스트는 바뀌지 않은 사본을 통과시킨다 — 운영에 없는
함수(mock 경로 등)를 지키거나, 운영이 바꾼 반환형을 모르는 채로 남는다.
테스트가 깨지면 그것은 운영 코드가 바뀐 것이고, 그게 회귀 테스트가 해야 할 일이다.

## 왜 경로를 여기 한 곳에서만 만드는가

경로를 파일마다 적으면 배포 단위를 옮길 때 몇 파일이 낡은 경로를 들고 남고, 그
테스트는 오류가 아니라 import 실패로 통째로 죽는다. 그래서 단위 위치는 이 파일의
`UNIT_ROOT` 한 줄만 안다.
"""

import os
import sys

# 저장소 루트 = 이 파일의 3단계 상위 (Test/SFR-006/tests/final_path.py)
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
# 등록하는 코드는 `final/` 뿐이다.
# 폴더 이름(`SFR-006`)은 읽기용 줄임이고 **배포 단위 이름**은 그 아래
# `prompt/SFR-006_template_fill/` 이 계속 들고 있다(로더가 그 이름으로 찾는다).
UNIT_ROOT = os.path.join(REPO_ROOT, "final", "SFR-006", "request")


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
