"""톤 정책 사본 대조 — MCP `lang_policy`(원본) ↔ 글다듬이 ↔ eval.

`python onprem/test/check_tone_policy.py`

## 왜 필요한가

톤 프리셋은 **세 곳에 복제돼 있다.** 배포 단위 간 import 가 금지돼 있어서(각 단위가
독립 Git 저장소로 배포된다 — 가이드 6.1) 공유 모듈로 뺄 수가 없다.

| 위치 | 역할 |
|---|---|
| `mcp/genon_lang_policy.py` (`LPTONE_PRESETS`) | **원본.** 톤 문구를 바꾸려면 여기부터 |
| `codeserving/SFR-018_text_polish/text_polish/tone_presets.py` | 다듬기 프롬프트를 쓰는 사본 |
| `eval/eval_mcp/tone_metrics.py` | 평가가 채점 기준으로 쓰는 사본 |

**원본이 018 에서 MCP 로 옮겨졌다** (2026-08-11 영역 재배치). 톤 결정(`resolve_tone`)을
워크플로우 스텝 1 이 MCP 로 부르기 때문이다 — 판정하는 쪽이 원본을 갖는 것이 맞다.
글다듬이 03 사본은 **프롬프트를 렌더하는 데** 여전히 필요하다(라벨·지시문).

> **006 사본은 2026-08-12 에 없어졌다.** 실제 배포 템플릿 3개가 정해진 톤으로 채우면
> 되는 성격이라, 사용자 발화에 따라 톤을 골라 다시 쓰는 006 의 톤 변환 기능
> (`tone_apply.py`/`tone_presets.py`/`value_guard.py`) 자체를 없앴다 — CLAUDE.md
> "글다듬이(톤)는 006 안에서 한다" 절, 코드는 `archive/sfr006-tone` 브랜치.
> 그래서 이 대조도 4벌 → 3벌로 줄었다.

사본이 갈리면 **같은 톤을 골라도 기능마다 결과가 달라지고, 평가가 틀린 기준으로 채점한다.**
실제로 갈려 있었다 — 006 의 `friendly` 에서 "안내·권유 표현(…)을 활용한다" 한 문장이
빠져 있었다(2026-08-06 발견·수정, 지금은 그 사본 자체가 없다). 사람 기억에 맡기면 또 갈린다.

이 스크립트는 배포 단위 **바깥**이라 두 파일을 모두 읽을 수 있다. 그게 여기 있는 유일한
이유다. 런타임에 대조하는 것은 import 금지 규칙상 불가능하다.

## 무엇을 대조하나

- eval ↔ 018: 톤 **키가 같은지** (eval 의 `TONE_RULES` 는 지시문이 아니라 채점 규칙이라
  내용 대조 대상이 아니다 — 키가 어긋나면 평가가 없는 톤을 채점하거나 빠뜨린다)
- eval `FORCED_TONE_SNAPSHOT` ↔ 018 `DOC_TYPE_POLICIES` 의 `forced_tone`

읽기만 하고 아무것도 고치지 않는다. 어긋나면 종료 코드 1.
"""

import ast
import importlib.util
import os

_ONPREM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 원본은 MCP 도구 파일 **안**에 있다. MCP 는 파일 하나가 등록 단위라 `tone_presets.py`
# 라는 별도 모듈이 없고, 심볼에는 `LP` 접두어가 붙어 있다(`LPTONE_PRESETS`).
_ORIGIN = os.path.join(_ONPREM, "mcp", "genon_lang_policy.py")
_COPY_POLISH = os.path.join(
    _ONPREM, "codeserving", "SFR-018_text_polish", "text_polish", "tone_presets.py"
)
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
    for path in (_ORIGIN, _COPY_POLISH, _COPY_EVAL):
        if not os.path.exists(path):
            print(f"[FAIL] 대조 대상 파일이 없다: {path}")
            return 1

    origin = _load_module(_ORIGIN, "_tone_origin")
    copy_polish = _load_module(_COPY_POLISH, "_tone_copy_polish")

    # MCP 도구 파일은 심볼에 접두어를 붙인다 — 한 서버에 여러 도구 파일이 함께 로드될 수
    # 있고, 겹치면 나중 것이 앞엣것을 덮기 때문이다. 사본 쪽은 배포 단위 안이라 그럴
    # 이유가 없어 접두어가 없다. 이름이 다를 뿐 **대조할 값은 같아야 한다.**
    origin_tones = origin.LPTONE_PRESETS

    for label, module in (("글다듬이", copy_polish),):
        copy_tones = module.TONE_PRESETS
        rep.expect(
            set(origin_tones) == set(copy_tones),
            f"{label} ↔ 원본 톤 키가 같다",
            f"원본={sorted(origin_tones)}\n{label}={sorted(copy_tones)}",
        )
        for key in sorted(set(origin_tones) & set(copy_tones)):
            src, dst = origin_tones[key], copy_tones[key]
            rep.expect(
                src.label == dst.label,
                f"{label} ↔ 원본 '{key}' label 이 같다",
                f"원본={src.label!r}\n{label}={dst.label!r}",
            )
            rep.expect(
                src.instruction == dst.instruction,
                f"{label} ↔ 원본 '{key}' 지시문이 같다",
                f"원본={src.instruction!r}\n{label}={dst.instruction!r}",
            )

    # 문서유형 정책은 글다듬이도 갖는다 (프롬프트의 문서유형 안내문을 렌더한다).
    origin_docs = origin.LPDOC_TYPE_POLICIES
    polish_docs = getattr(copy_polish, "DOC_TYPE_POLICIES", {})
    rep.expect(
        set(origin_docs) == set(polish_docs),
        "글다듬이 ↔ 원본 문서유형 키가 같다",
        f"원본={sorted(origin_docs)}\n글다듬이={sorted(polish_docs)}",
    )
    for key in sorted(set(origin_docs) & set(polish_docs)):
        rep.expect(
            origin_docs[key].forced_tone == polish_docs[key].forced_tone,
            f"글다듬이 ↔ 원본 '{key}' 강제 톤이 같다",
            f"원본={origin_docs[key].forced_tone!r}\n글다듬이={polish_docs[key].forced_tone!r}",
        )

    eval_rules = _literal_assign(_COPY_EVAL, "TONE_RULES")
    rep.expect(
        isinstance(eval_rules, dict) and set(eval_rules) == set(origin_tones),
        "eval ↔ 018 톤 키가 같다",
        f"018={sorted(origin_tones)}\neval={sorted(eval_rules) if isinstance(eval_rules, dict) else eval_rules}",
    )

    origin_forced = {
        key: policy.forced_tone
        for key, policy in origin.LPDOC_TYPE_POLICIES.items()
        if policy.forced_tone
    }
    eval_forced = _literal_assign(_COPY_EVAL, "FORCED_TONE_SNAPSHOT")
    rep.expect(
        eval_forced == origin_forced,
        "eval ↔ 018 강제 톤(forced_tone) 표가 같다",
        f"018={origin_forced}\neval={eval_forced}",
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
