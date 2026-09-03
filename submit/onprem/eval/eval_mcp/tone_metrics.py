"""톤 적합성 규칙 검사 (`Text`) — LLM 미사용.

README: 톤은 결정적 도구로 합불한다. `LLM Judge` 는 주관적 편차가 커서
상시로 붙일 실익이 낮고, 필요하면 수동 스팟체크로 대체한다.

여기서 재는 것은 세 가지다.
1. 톤 프리셋이 요구하는 종결 형태를 실제로 썼는지 (`expected_endings`)
2. 톤에서 금지되는 표현(반말·명령형·구어체 축약·과장 수식어)이 남았는지
3. 한국어 조사 선택 오류 — 받침 유무로 결정되므로 유니코드 연산으로 판정 가능

`FORCED_TONE_SNAPSHOT` 은 운영 정책(text_polish/tone_presets.py)의 **사본**이다.
배포 단위 간 import 를 하지 않는 규칙 때문에 복제했으므로, 정책을 바꿀 때는
두 곳을 함께 고친다. 평가에서 정책 불일치가 감지되면 결과에 그대로 노출한다.
"""

import re

from .error_codes import ERR_EMPTY_ITEMS, fail
from .logging_utils import log_warning
from .normalize import normalize, split_sentences

# 톤 4종 — 운영 코드의 TONE_PRESETS 키와 같아야 한다 (2026-09-03 요구 변경).
#
# **옛 `report`(개조식 `~함/~임`)는 없어졌다.** 새 넷은 전부 존댓말을 유지하므로
# `expected_endings` 가 셋에서 겹친다 — 톤을 가르는 것은 종결어미가 아니라 `forbidden`
# 이다(간결·객관은 무엇을 **덜어 냈는지**로 판정한다). 종결어미만 보던 시절의 규칙을
# 그대로 두면 네 톤이 전부 통과해 이 지표가 아무것도 거르지 못한다.
TONE_RULES: dict = {
    "polite": {
        "label": "격식·정중",
        "expected_endings": ("습니다", "합니다", "입니다", "십니다", "됩니다"),
        "forbidden": {
            "반말/평서 종결": r"(?:[가-힣])(?:했다|한다|이다|없다|있다)(?=[\s.]|$)",
            "명령형": r"(?:하라|해라|하시오|해야지)(?=[\s.]|$)",
            "구어체 축약": r"\b(?:좀|되게|진짜|엄청|걍|넘)\b",
        },
    },
    "friendly": {
        "label": "친절·안내",
        "expected_endings": ("습니다", "합니다", "입니다", "세요", "어요", "예요", "에요"),
        "forbidden": {
            "명령형": r"(?:하라|해라|하시오)(?=[\s.]|$)",
            "관공서식 표현": r"(?:요망|필히|하기와\s*같이|동\s*건|귀하께서는|승낙|기\s*제출)",
        },
    },
    "clear": {
        "label": "명확·간결",
        # 개조식이 아니다 — 문장을 줄이는 톤이지 종결어미를 바꾸는 톤이 아니다.
        "expected_endings": ("습니다", "합니다", "입니다", "됩니다"),
        "forbidden": {
            "군더더기 표현": r"(?:에\s*대하여|에\s*대하여는|하는\s*바입니다|에\s*다름\s*아닙니다)",
            "중복 수식어": r"\b(?:매우|정말|아주|굉장히|무척|상당히)\b",
            "명령형": r"(?:하라|해라|하시오)(?=[\s.]|$)",
        },
    },
    "objective": {
        "label": "사실·객관",
        "expected_endings": ("습니다", "합니다", "입니다", "됩니다"),
        "forbidden": {
            # 추측·주관은 **표현**으로 잡는다. "근거가 있는가" 는 이 지표가 답할 수
            # 없다(FAQ 근거 대조가 그 몫이다) — 여기서 재는 것은 어투뿐이다.
            "추측 표현": r"(?:같습니다|듯합니다|생각합니다|느껴집니다|보입니다)(?=[\s.]|$)",
            "주관적 평가": r"\b(?:아쉽게도|다행히|훌륭한|최고의|엄청난)\b",
            "과장 수식어": r"\b(?:매우|정말|아주|굉장히|무척|상당히)\b",
        },
    },
}

# 운영 정책 사본 — 톤 고정군 (사용자 요청 톤과 무관하게 이 톤으로 채점해야 한다).
# 2026-09-03: 고정군이 둘로 줄고 **사실·객관 고정**이 됐다. `asset_opinion`(재산 의견)·
# `press_release`·`official_doc` 은 없어졌고 `customer_notice` 는 자유 선택군이 됐다 —
# 자유 선택군은 여기 넣지 않는다(사용자가 고른 톤으로 채점한다).
FORCED_TONE_SNAPSHOT: dict = {
    "debt_reason": "objective",
    "reviewer_opinion": "objective",
}

# ── 조사 규칙: (받침 필요 형태, 받침 없을 때 형태) ──────────────
_PARTICLE_PAIRS = (
    ("을", "를"),
    ("이", "가"),
    ("은", "는"),
    ("과", "와"),
    ("으로", "로"),
    ("으로써", "로써"),
    ("이라", "라"),
)
_PARTICLES = sorted({p for pair in _PARTICLE_PAIRS for p in pair}, key=len, reverse=True)
_JONG_EXEMPT_RIEUL = {"으로", "으로써"}  # ㄹ 받침은 '로/로써' 를 쓴다
# 어절 끝에 붙은 문장부호 — 조사를 떼기 전에 벗긴다.
_TRAILING_PUNCT = " 	.,!?…:;)]}\"'’”」』〉》"


def _has_jongseong(syllable: str) -> tuple[bool, bool]:
    """(받침 있음, 받침이 ㄹ) — 한글 음절이 아니면 (False, False)."""
    code = ord(syllable)
    if not 0xAC00 <= code <= 0xD7A3:
        return False, False
    jong = (code - 0xAC00) % 28
    return jong != 0, jong == 8


def _split_particle(eojeol: str) -> tuple:
    """어절 → (앞말, 조사). 조사로 볼 수 없으면 (어절, "")."""
    body = eojeol.strip(_TRAILING_PUNCT)
    for particle in _PARTICLES:          # 긴 조사부터 (으로써 > 으로 > 로)
        if len(body) > len(particle) and body.endswith(particle):
            return body[: -len(particle)], particle
    return body, ""


def particle_errors(text: str, nouns=None) -> dict:
    r"""받침 유무와 어긋난 조사 사용을 찾는다 — **앞말이 명사임을 아는 자리에서만.**

    Args:
        text: 검사할 본문.
        nouns: 조사가 붙는 앞말 목록(사내 용어사전 표제어 등). **이 목록에 있는 낱말
            뒤에서만 검사한다.**

    Returns:
        `{"scope", "checked", "issues"}` — `checked` 는 실제로 판정한 자리 수다.
        목록이 없으면 `checked=0` 이고 `issues` 는 비어 있다 (**통과가 아니라 미검사**).

    ## 왜 범위를 좁혔나 — 평범한 낱말을 오검출하고 있었다 (2026-08-30)

    그전에는 `([가-힣])(을|를|이|가|…)(?=[\s,.]|$)` 로 **한글 한 글자 + 조사 글자**면
    무조건 조사로 봤다. 한국어에는 그 글자로 끝나는 보통 낱말이 널려 있어서 실측에서
    이렇게 나왔다:

    | 입력 | 판정 |
    |---|---|
    | `평가.` | `평가` → `평이` 로 고치라고 한다 |
    | `증가.` | `증이` |
    | `국가.` | `국이` |
    | `가을.` | `가를` |
    | `사과.` | `사와` |

    `passed` 가 이 결과를 그대로 받으므로 **"증가" 나 "평가" 가 들어간 평범한 문서가
    톤 불합격**이 됐다. 가드레일이 오탐을 내면 아무도 안 보게 된다.

    형태소 분석기를 넣으면 풀리지만 이 패키지는 외부 모델을 두지 않는다(README).
    **"으로/로" 만 검사하는" 식의 절충도 안 된다** — `진로`·`선로`·`항로` 처럼 받침
    있는 앞 글자 + `로` 로 끝나는 낱말이 그대로 오검출된다.

    그래서 **앞말이 명사라는 것을 아는 자리에서만** 잰다. 사내 용어사전 표제어를
    넘기면 그 용어 뒤의 조사는 정확히 판정된다. 넘기지 않으면 재지 않고, 재지 않았다는
    사실을 `scope` 로 알린다 (미검사를 통과로 보이게 하지 않는다).
    """
    known = {normalize(str(n)) for n in (nouns or []) if str(n).strip()}
    if not known:
        return {"scope": "not_checked", "reason": "nouns_not_provided", "checked": 0, "issues": []}

    issues, checked = [], 0
    for eojeol in normalize(text).split():
        stem, particle = _split_particle(eojeol)
        if not particle or stem not in known:
            continue
        has_jong, is_rieul = _has_jongseong(stem[-1])
        for with_jong, without_jong in _PARTICLE_PAIRS:
            if particle not in (with_jong, without_jong):
                continue
            checked += 1
            if with_jong in _JONG_EXEMPT_RIEUL and is_rieul:
                expected = without_jong  # 'ㄹ 받침 + 로'
            else:
                expected = with_jong if has_jong else without_jong
            if particle != expected:
                issues.append({"context": stem + particle, "used": particle, "expected": expected})
            break
    return {"scope": "provided_nouns", "checked": checked, "issues": issues}


def tone_rule_check(text: str, tone: str, doc_type: str | None = None, nouns=None) -> dict:
    """톤 프리셋 대비 규칙 검사 + 조사 검사.

    doc_type 이 톤 고정군이면 요청 톤을 무시하고 정책 톤으로 채점하며,
    그 사실을 `tone_forced_by_policy` 로 알린다.

    Args:
        nouns: 조사 검사를 걸 앞말 목록 (사내 용어사전 표제어 등). **없으면 조사는
            검사하지 않는다** — 형태소 분석 없이 넓게 잡으면 `평가`·`증가` 같은 평범한
            낱말을 오검출한다 (`particle_errors` 머리말). 검사 여부는
            `particle_check.scope` 로 결과에 남는다.
    """
    sentences = split_sentences(text)
    if not sentences:
        fail(ERR_EMPTY_ITEMS, event="tone_no_sentences")

    forced = FORCED_TONE_SNAPSHOT.get((doc_type or "").strip())
    applied = forced or tone
    rules = TONE_RULES.get(applied)
    if rules is None:
        # **예외로 죽지 않는다** (2026-08-18). 예전에는 알 수 없는 톤이면 `fail()` 로
        # 끝냈다 — 톤 3종이 코드에 고정돼 있던 시절에는 그게 오타를 잡는 그물이었다.
        # 이제 관리자가 프롬프트 라이브러리에 톤을 추가할 수 있으므로(가이드 §10.5),
        # **정상적으로 쓰인 톤에서 스위트 전체가 죽는다.**
        #
        # 그렇다고 통과로 세지도 않는다 — eval 규약이 "미측정을 통과로 보이게 하지
        # 않는다" 이다. 채점하지 않았다는 사실(`scored=False`)과 사유를 담아 돌려주고,
        # 집계(`tone_pass_rate`)가 분모에서 뺀다.
        #
        # **eval 은 배포 단위를 import 하지 않으므로**(파서를 공유하면 파서 버그를 함께
        # 놓친다) 관리자 톤 규칙을 여기서 알 방법이 없다. 추가된 톤을 채점하려면 이
        # 파일의 `TONE_RULES` 에 규칙을 함께 넣어야 한다.
        log_warning(
            "채점 규칙이 없는 톤 — 건너뛴다",
            event="tone_rules_missing",
            resource_id=applied,
            status="skipped",
        )
        return {
            "tone_applied": applied,
            "tone_label": applied,
            "tone_requested": tone,
            "tone_forced_by_policy": bool(forced and forced != tone),
            "sentences": len(sentences),
            "scored": False,
            "skip_reason": "no_rules_for_tone",
            "ending_match_rate": None,
            "forbidden_hits": {},
            "particle_check": {"scope": "not_checked", "reason": "tone_not_scored",
                               "checked": 0, "issues": []},
            "passed": None,
        }

    body = normalize(text)
    endings = rules["expected_endings"]
    matched = [s for s in sentences if s.rstrip(" .!?…").endswith(endings)]
    violations = {
        label: sorted({m.group(0) for m in re.finditer(pattern, body)})
        for label, pattern in rules["forbidden"].items()
    }
    violations = {label: hits for label, hits in violations.items() if hits}
    particles = particle_errors(text, nouns)

    return {
        "tone_applied": applied,
        "tone_label": rules["label"],
        "tone_requested": tone,
        "scored": True,
        "skip_reason": "",
        "tone_forced_by_policy": bool(forced and forced != tone),
        "sentences": len(sentences),
        "ending_match_rate": round(len(matched) / len(sentences), 4),
        "forbidden_hits": violations,
        # 검사 범위를 값과 함께 낸다 — `issues` 가 비었다는 것이 "조사가 맞다" 인지
        # "조사를 안 봤다" 인지 구분되지 않으면 리포트가 거짓말을 한다.
        "particle_check": particles,
        # **`particles` 는 dict 다** — 비어 있는지 보려면 `issues` 를 봐야 한다.
        # dict 자체를 진리값으로 쓰면 언제나 참이라 **모든 문서가 불합격**이 된다.
        "passed": not violations and not particles["issues"],
    }


def tone_pass_rate(items: list, nouns=None) -> dict:
    """여러 결과물의 톤 합불 집계. items: [{"text","tone","doc_type"(선택),"id"(선택)}]

    **한 항목이 이상하다고 묶음 전체를 죽이지 않는다** (2026-08-30). 결과물이 비어
    있으면 `tone_rule_check` 이 예외를 던지는데, 그건 채점할 문장이 없다는 뜻이고
    집계 입장에서는 **그 항목의 불합격**이다 — 예외로 올리면 나머지 99건의 채점 결과가
    통째로 사라진다. 단건 도구는 엄격하게 두고(쓰레기가 들어오면 오류), 집계가 감싼다.
    """
    if not items:
        fail(ERR_EMPTY_ITEMS, event="tone_pass_rate_input_empty")

    failures, ending_rates, skipped = [], [], []
    for index, item in enumerate(items):
        text = str(item.get("text", ""))
        if not split_sentences(text):
            # 결과물이 없다 = 다듬기가 아무것도 내놓지 못했다. **미채점이 아니라 불합격**이다.
            failures.append({"index": index, "id": item.get("id"), "reason": "empty_result"})
            ending_rates.append(0.0)
            continue
        result = tone_rule_check(text, str(item.get("tone", "")), item.get("doc_type"), nouns)
        if not result.get("scored", True):
            # 채점하지 않은 항목은 **분모에서 뺀다.** 통과로 세면 합격률이 부풀고,
            # 불합격으로 세면 관리자가 톤을 추가했다는 이유로 지표가 떨어진다.
            skipped.append({"index": index, "id": item.get("id"),
                            "tone": result["tone_applied"], "reason": result["skip_reason"]})
            continue
        ending_rates.append(result["ending_match_rate"])
        if not result["passed"]:
            failures.append(
                {
                    "index": index,
                    "id": item.get("id"),
                    "forbidden_hits": result["forbidden_hits"],
                    "particle_errors": result["particle_check"]["issues"],
                }
            )

    total = len(items)
    scored = total - len(skipped)
    return {
        "items": total,
        # **채점한 것 중의 합격률**이다. 건너뛴 것이 있으면 `scored`·`skipped` 를 함께
        # 봐야 한다 — 그 둘이 없으면 "1.0" 이 전량 통과인지 전량 미채점인지 알 수 없다.
        "scored": scored,
        "pass_rate": round((scored - len(failures)) / scored, 4) if scored else None,
        "mean_ending_match_rate": (
            round(sum(ending_rates) / scored, 4) if scored else None
        ),
        "failures": failures,
        "skipped": skipped,
    }
