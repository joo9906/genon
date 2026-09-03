"""onprem 배포 단위·MCP 서빙을 import 할 수 있게 `sys.path` 를 세운다.

**이 파일이 이 디렉토리의 존재 이유다.** 예전에는 `SFR-018/text_polish/` 와
`SFR-018/translation_refactored/` 에 구현 **사본**이 있었고 테스트가 그 사본을
검증했다. 사본은 자동 동기화되지 않으므로 운영 코드를 고쳐도 테스트는 옛 코드를
통과시켰다. 그래서 사본을 지우고 **onprem 을 직접 태운다** (2026-08-11).

## 018 은 006 과 달리 **대상이 두 영역에 걸쳐 있다**

2026-08-11 영역 재배치로 글다듬이의 구조 점검 모듈들이 **MCP 로 옮겨갔다**:

```
SFR-018/text_polish/markdown_guard.py  →  onprem/mcp/genon_text_guard.py  안
SFR-018/text_polish/diff_report.py     →  onprem/mcp/genon_text_guard.py  안
SFR-018/text_polish/tone_presets.py    →  onprem/mcp/genon_lang_policy.py 안 (판정 원본이 그리로 갔다)
```

그래서 `markdown_guard` 테스트는 **코드서빙이 아니라 MCP 를** 태운다. 사본을 그대로
뒀다면 이 이동이 테스트에 전혀 드러나지 않았을 것이다 — 사본 안의 옛 파일이 계속
통과했을 테니까.

## MCP 는 **패키지가 아니라 파일 하나**다

GenOS MCP 는 소스 파일 한 개를 받아 실행하고 `mcp` 객체를 런타임이 주입한다. 그래서
`import guard.markdown_guard` 같은 것이 없다 — 파일을 통째로 실어 그 안의 함수를 꺼낸다.
`load_mcp()` 가 그 일을 한다.

그 파일들의 심볼에는 **접두어**가 붙어 있다(`TG`/`LP`/`HX`/`GL`). 한 서버에 여러 도구
파일이 함께 로드될 수 있어서고, 겹치면 나중 것이 앞엣것을 덮는다. 그래서 여기서
`find_structure_issues` 가 아니라 `tgfind_structure_issues` 를 꺼낸다.
"""

import importlib.util
import os
import sys

# 저장소 루트 = 이 파일의 2단계 상위 (SFR-018/tests/onprem_path.py)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ONPREM = os.path.join(REPO_ROOT, "onprem")

TRANSLATION_UNIT = os.path.join(ONPREM, "codeserving", "SFR-018_translation")
TEXT_POLISH_UNIT = os.path.join(ONPREM, "codeserving", "SFR-018_text_polish")
FAQ_UNIT = os.path.join(ONPREM, "codeserving", "SFR-018_faq")

TEXT_GUARD_MCP = os.path.join(ONPREM, "mcp", "genon_text_guard.py")
LANG_POLICY_MCP = os.path.join(ONPREM, "mcp", "genon_lang_policy.py")


def install(*roots: str) -> None:
    """배포 단위 루트들을 `sys.path` 앞에 넣는다 (코드서빙 전용).

    필요한 것만 넣는다 — 번역 코드서빙이 `translation_pipeline.office` 를 만들고 다른
    단위도 `office`·`config` 같은 흔한 이름을 쓰므로, 한꺼번에 넣으면 한쪽이 다른 쪽을
    가린다.
    """
    for root in roots:
        if not os.path.isdir(root):
            raise RuntimeError(
                f"onprem 단위를 찾지 못했다: {root}\n"
                "배포 단위가 옮겨졌다면 이 파일의 경로 상수만 고치면 된다."
            )
        if root not in sys.path:
            sys.path.insert(0, root)


def load_mcp(path: str):
    """MCP 도구 파일을 실어 모듈 객체로 돌려준다.

    `sys.path` 를 건드리지 않는다 — MCP 는 패키지가 아니라 파일이고, 파일마다 고유
    접두어를 쓰므로 경로에 얹을 이유가 없다.
    """
    if not os.path.isfile(path):
        raise RuntimeError(
            f"MCP 도구 파일을 찾지 못했다: {path}\n"
            "파일이 옮겨졌다면 이 파일의 경로 상수만 고치면 된다."
        )
    name = "_mcp_" + os.path.basename(path)[:-3]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
