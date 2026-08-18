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

# 톤 3종 — 운영 코드의 TONE_PRESETS 키와 같아야 한다
TONE_RULES: dict = {
    "polite": {
        "label": "정중함",
        "expected_endings": ("습니다", "합니다", "입니다", "십니다", "됩니다"),
        "forbidden": {
            "반말/평서 종결": r"(?:[가-힣])(?:했다|한다|이다|없다|있다)(?=[\s.]|$)",
            "명령형": r"(?:하라|해라|하시오|해야지)(?=[\s.]|$)",
            "구어체 축약": r"\b(?:좀|되게|진짜|엄청|걍|넘)\b",
        },
    },
    "friendly": {
        "label": "친절함",
        "expected_endings": ("습니다", "합니다", "입니다", "세요", "어요", "예요", "에요"),
        "forbidden": {
            "명령형": r"(?:하라|해라|하시오)(?=[\s.]|$)",
            "관공서식 표현": r"(?:요망|필히|하기와\s*같이|동\s*건|귀하께서는|승낙|기\s*제출)",
        },
    },
    "report": {
        "label": "간결 및 보고체",
        "expected_endings": ("함", "임", "됨", "음", "요함", "예정임"),
        "forbidden": {
            "존댓말 종결": r"(?:습니다|합니다|입니다|세요|어요)(?=[\s.]|$)",
            "과장 수식어": r"\b(?:매우|정말|아주|굉장히|무척|상당히)\b",
        },
    },
}

# 운영 정책 사본 — 톤 고정군 (사용자 요청 톤과 무관하게 이 톤으로 채점해야 한다)
FORCED_TONE_SNAPSHOT: dict = {
    "debt_reason": "report",
    "reviewer_opinion": "report",
    "asset_opinion": "report",
    "customer_notice": "polite",
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
_PARTICLE_RE = re.compile(
    r"([가-힣])(" + "|".join(sorted({p for pair in _PARTICLE_PAIRS for p in pair}, key=len, reverse=True)) + r")(?=[\s,.]|$)"
)
_JONG_EXEMPT_RIEUL = {"으로", "으로써"}  # ㄹ 받침은 '로/로써' 를 쓴다


def _has_jongseong(syllable: str) -> tuple[bool, bool]:
    """(받침 있음, 받침이 ㄹ) — 한글 음절이 아니면 (False, False)."""
    code = ord(syllable)
    if not 0xAC00 <= code <= 0xD7A3:
        return False, False
    jong = (code - 0xAC00) % 28
    return jong != 0, jong == 8


def particle_errors(text: str) -> list:
    """받침 유무와 어긋난 조사 사용을 찾는다 (결정적 판정)."""
    issues = []
    for match in _PARTICLE_RE.finditer(normalize(text)):
        syllable, particle = match.group(1), match.group(2)
        has_jong, is_rieul = _has_jongseong(syllable)
        for with_jong, without_jong in _PARTICLE_PAIRS:
            if particle not in (with_jong, without_jong):
                continue
            if with_jong in _JONG_EXEMPT_RIEUL and is_rieul:
                expected = without_jong  # 'ㄹ 받침 + 로'
            else:
                expected = with_jong if has_jong else without_jong
            if particle != expected:
                issues.append(
                    {"context": syllable + particle, "used": particle, "expected": expected}
                )
            break
    return issues


def tone_rule_check(text: str, tone: str, doc_type: str | None = None) -> dict:
    """톤 프리셋 대비 규칙 검사 + 조사 검사.

    doc_type 이 톤 고정군이면 요청 톤을 무시하고 정책 톤으로 채점하며,
    그 사실을 `tone_forced_by_policy` 로 알린다.
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
            "particle_errors": [],
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
    particles = particle_errors(text)

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
        "particle_errors": particles,
        "passed": not violations and not particles,
    }


def tone_pass_rate(items: list) -> dict:
    """여러 결과물의 톤 합불 집계. items: [{"text","tone","doc_type"(선택),"id"(선택)}]"""
    if not items:
        fail(ERR_EMPTY_ITEMS, event="tone_pass_rate_input_empty")

    failures, ending_rates, skipped = [], [], []
    for index, item in enumerate(items):
        result = tone_rule_check(str(item.get("text", "")), str(item.get("tone", "")), item.get("doc_type"))
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
                    "particle_errors": result["particle_errors"],
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
