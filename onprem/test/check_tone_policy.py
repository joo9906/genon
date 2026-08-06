"""톤 정책 사본 대조 — 018(원본) ↔ 006 ↔ eval.

`python onprem/test/check_tone_policy.py`

## 왜 필요한가

톤 프리셋은 **세 곳에 복제돼 있다.** 배포 단위 간 import 가 금지돼 있어서(각 단위가
독립 Git 저장소로 배포된다 — 가이드 6.1) 공유 모듈로 뺄 수가 없다.

| 위치 | 역할 |
|---|---|
| `SFR-018_text_polish/text_polish/tone_presets.py` | **원본.** 톤 문구를 바꾸려면 여기부터 |
| `SFR-006_template_fill/template_fill/tone_presets.py` | 006 이 문서 값·본문에 적용하는 사본 |
| `eval/eval_mcp/tone_metrics.py` | 평가가 채점 기준으로 쓰는 사본 |

사본이 갈리면 **같은 톤을 골라도 기능마다 결과가 달라지고, 평가가 틀린 기준으로 채점한다.**
실제로 갈려 있었다 — 006 의 `friendly` 에서 "안내·권유 표현(…)을 활용한다" 한 문장이
빠져 있었다(2026-08-06 발견·수정). 사람 기억에 맡기면 또 갈린다.

이 스크립트는 배포 단위 **바깥**이라 세 파일을 모두 읽을 수 있다. 그게 여기 있는 유일한
이유다. 런타임에 대조하는 것은 import 금지 규칙상 불가능하다.

## 무엇을 대조하나

- 006 ↔ 018: 톤 **키·label·instruction 이 글자 단위로 같은지**
- eval ↔ 018: 톤 **키가 같은지** (eval 의 `TONE_RULES` 는 지시문이 아니라 채점 규칙이라
  내용 대조 대상이 아니다 — 키가 어긋나면 평가가 없는 톤을 채점하거나 빠뜨린다)
- eval `FORCED_TONE_SNAPSHOT` ↔ 018 `DOC_TYPE_POLICIES` 의 `forced_tone`

**006 에는 문서유형 정책이 없는 것이 정상이다** (2026-08-06 결정 — 006 은 템플릿 자체가
문서 종류를 정한다). 그래서 006 에 대해서는 문서유형을 대조하지 않는다.

읽기만 하고 아무것도 고치지 않는다. 어긋나면 종료 코드 1.
"""

import ast
import importlib.util
import os
import sys

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ORIGIN = os.path.join(_ONPREM, "SFR-018_text_polish", "text_polish", "tone_presets.py")
_COPY_006 = os.path.join(_ONPREM, "SFR-006_template_fill", "template_fill", "tone_presets.py")
_COPY_EVAL = os.path.join(_ONPREM, "eval", "eval_mcp", "tone_metrics.py")


def _load_module(path: str, name: str):
    """의존성 없는 모듈을 패키지 맥락 없이 파일 경로로 읽어 들인다.

    두 `tone_presets.py` 는 `dataclasses` 만 import 하므로 이렇게 부를 수 있다.
    같은 이름의 모듈 둘을 한 프로세스에 올려야 해서 이름을 다르게 준다.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_assign(path: str, target: str):
    """모듈을 실행하지 않고 최상위 `NAME = <리터럴>` 값을 꺼낸다.

    eval 쪽은 상대 import(`from .error_codes import …`)가 있어 파일 경로 로드가 안 된다.
    대조할 값이 둘 다 dict 리터럴이라 AST 로 충분하다
    (`check_deploy_contract.py` 가 소스만 읽는 것과 같은 방침).
    """
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        names = (
            [t.id for t in node.targets if isinstance(t, ast.Name)]
            if isinstance(node, ast.Assign)
            else ([node.target.id] if isinstance(node.target, ast.Name) else [])
        )
        if target not in names or node.value is None:
            continue
        try:
            return ast.literal_eval(node.value)
        except ValueError:
            return None
    return None


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0

    def expect(self, condition: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}")
        if detail:
            for line in detail.splitlines():
                print(f"        {line}")


def main() -> int:
    rep = Report()
    for path in (_ORIGIN, _COPY_006, _COPY_EVAL):
        if not os.path.exists(path):
            print(f"[FAIL] 대조 대상 파일이 없다: {path}")
            return 1

    origin = _load_module(_ORIGIN, "_tone_origin")
    copy006 = _load_module(_COPY_006, "_tone_copy_006")

    origin_tones = origin.TONE_PRESETS
    copy_tones = copy006.TONE_PRESETS

    rep.expect(
        set(origin_tones) == set(copy_tones),
        "006 ↔ 018 톤 키가 같다",
        f"018={sorted(origin_tones)}\n006={sorted(copy_tones)}",
    )

    for key in sorted(set(origin_tones) & set(copy_tones)):
        src, dst = origin_tones[key], copy_tones[key]
        rep.expect(
            src.label == dst.label,
            f"006 ↔ 018 '{key}' label 이 같다",
            f"018={src.label!r}\n006={dst.label!r}",
        )
        rep.expect(
            src.instruction == dst.instruction,
            f"006 ↔ 018 '{key}' 지시문이 같다",
            f"018={src.instruction!r}\n006={dst.instruction!r}",
        )

    eval_rules = _literal_assign(_COPY_EVAL, "TONE_RULES")
    rep.expect(
        isinstance(eval_rules, dict) and set(eval_rules) == set(origin_tones),
        "eval ↔ 018 톤 키가 같다",
        f"018={sorted(origin_tones)}\neval={sorted(eval_rules) if isinstance(eval_rules, dict) else eval_rules}",
    )

    origin_forced = {
        key: policy.forced_tone
        for key, policy in origin.DOC_TYPE_POLICIES.items()
        if policy.forced_tone
    }
    eval_forced = _literal_assign(_COPY_EVAL, "FORCED_TONE_SNAPSHOT")
    rep.expect(
        eval_forced == origin_forced,
        "eval ↔ 018 강제 톤(forced_tone) 표가 같다",
        f"018={origin_forced}\neval={eval_forced}",
    )

    # 006 에 문서유형 정책이 없는 것은 결정 사항이다 — 생겼다면 그 결정이 바뀐 것이고,
    # 그러면 이 스크립트도 문서유형을 대조하도록 고쳐야 한다.
    rep.expect(
        not hasattr(copy006, "DOC_TYPE_POLICIES"),
        "006 에는 문서유형 정책이 없다 (2026-08-06 결정)",
        "006 에 DOC_TYPE_POLICIES 가 생겼다 — 이 스크립트에 대조를 추가할 것",
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        print("톤 문구는 018 이 원본이다. 018 을 고치고 나머지 사본을 맞출 것.")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
