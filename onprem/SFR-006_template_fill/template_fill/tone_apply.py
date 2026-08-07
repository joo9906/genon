"""추출된 값에 톤(문체)을 적용하는 2단계 — 서술형 필드 한정.

왜 추출과 분리하는가:
- 추출 프롬프트에 톤 지시를 섞으면 "사용자가 말한 값"과 "문체를 바꾼 값"이 한 응답에
  뒤섞여, 값 정확도(정답 대비 exact match) 평가가 흐려진다.
- 이름·날짜·금액 같은 짧은 필드는 문체를 바꿀 대상이 아니고, 바꾸면 사실이 훼손된다.

그래서 이 단계는:
1. **서술형 필드만 고른다** (결정적 규칙 — 길이/문장 종결/줄바꿈. 관리자가 필드명을
   직접 지정하면 그 목록이 우선한다).
2. 후보가 없으면 LLM 을 호출하지 않는다 (불필요한 호출·지연 방지).
3. 응답은 화이트리스트·스키마로 검증하고(field_judge 와 같은 취지),
   **숫자·날짜 보존을 value_guard 로 결정적으로 확인**한다.
4. 검증에 걸린 필드는 **원본 값을 유지**하고 기각 사실을 상위로 노출한다
   (실패 침묵 처리 금지 — 사용자에게도 알린다).

3.8절: 로그에는 값이 아니라 개수만 남긴다.
"""

import json
import re
from dataclasses import dataclass, field as dc_field

from .config import Config
from .llm import llm_call_async
from .logging_utils import log_info, log_warning
from .prompt_loader import PromptRenderError
from .prompts import build_tone_prompts
from .tone_presets import TONE_PRESETS
from .value_guard import fact_diff

# 서술형 판정 기준 (결정적). 짧은 값·단일 명사구는 문체 변환 대상이 아니다.
_NARRATIVE_MIN_CHARS = 25
# 종결어미만 본다. 마침표를 종결 신호로 쓰면 "2026. 8. 4." 같은 날짜가 문장으로 잡힌다.
_SENTENCE_ENDINGS = ("다", "요", "음", "함", "임", "됨")
# 한글이 이만큼도 없는 값은 날짜·금액·코드·사람 이름이다 — 문체를 바꿀 대상이 아니다.
_MIN_HANGUL_CHARS = 4
_HANGUL_RE = re.compile(r"[가-힣]")


@dataclass
class ToneResult:
    """톤 적용 결과.

    values: 적용 후 최종 값 (기각된 필드는 원본 그대로).
    applied: 실제로 문체가 바뀐 필드명.
    rejected: 검증에 걸려 원본을 유지한 [{"field":…, "reason":…}].
    skipped_short: 서술형이 아니어서 대상에서 제외한 필드명.
    llm_error_type: LLM 호출 실패 시 분류 (성공/미호출이면 "").
    """

    values: dict
    applied: list = dc_field(default_factory=list)
    rejected: list = dc_field(default_factory=list)
    skipped_short: list = dc_field(default_factory=list)
    llm_error_type: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def is_narrative(value: str) -> bool:
    """문체를 바꿀 만한 서술형 값인지 결정적으로 판정한다.

    한글 문장 성분이 거의 없는 값(날짜 '2026. 8. 4.', 금액, 사번, 사람 이름)은
    제외한다 — 이런 값에 문체 변환을 걸면 얻는 것 없이 사실이 훼손된다.
    한국어 문서 전용 판정이므로, 영문 서술형은 관리자가 필드를 직접 지정해야 한다.
    """
    text = (value or "").strip()
    if not text:
        return False
    if len(_HANGUL_RE.findall(text)) < _MIN_HANGUL_CHARS:
        return False
    if "\n" in text or len(text) >= _NARRATIVE_MIN_CHARS:
        return True
    # 짧아도 종결어미로 끝나면 서술형으로 본다 ("검토를 완료했습니다")
    return text.endswith(_SENTENCE_ENDINGS)


def select_targets(values: dict, explicit_fields: list | None = None) -> tuple[dict, list]:
    """톤 적용 대상과 제외 대상을 가른다.

    explicit_fields 가 주어지면(관리자 지정) 그 필드만 대상으로 한다 — 짧은 값이라도
    관리자가 지정했다면 의도가 있다고 본다.
    """
    if explicit_fields:
        allowed = {str(f).strip() for f in explicit_fields}
        targets = {k: v for k, v in values.items() if k in allowed and str(v).strip()}
        skipped = sorted(k for k in values if k not in targets)
        return targets, skipped

    targets = {k: v for k, v in values.items() if is_narrative(str(v))}
    skipped = sorted(k for k in values if k not in targets)
    return targets, skipped


def _parse_converted(raw: str, allowed_names: set) -> tuple[dict, list]:
    """LLM 응답에서 {"converted": {필드명: 값}} 을 안전하게 뽑는다."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return {}, ["<응답 전체: JSON 파싱 실패>"]
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}, ["<응답 전체: JSON 파싱 실패>"]

    if not isinstance(parsed, dict) or not isinstance(parsed.get("converted"), dict):
        return {}, ["<응답 전체: converted 객체 없음>"]

    accepted, rejected = {}, []
    for key, value in parsed["converted"].items():
        name = str(key).strip()
        if name not in allowed_names or isinstance(value, (list, dict)) or value is None:
            rejected.append(name)
            continue
        text = str(value).strip()
        if not text:
            rejected.append(name)
            continue
        accepted[name] = text[: Config.MAX_VALUE_CHARS]
    return accepted, rejected


async def apply_tone(
    values: dict, tone_key: str, explicit_fields: list | None = None
) -> ToneResult:
    """values 중 서술형 필드에 톤을 적용한다. 실패·검증 위반 시 원본을 유지한다."""
    preset = TONE_PRESETS.get(tone_key)
    if preset is None or not values:
        return ToneResult(values=dict(values))

    targets, skipped = select_targets(values, explicit_fields)
    if not targets:
        log_info(
            "톤 적용 대상 없음 — LLM 호출 생략",
            event="tone_no_targets",
            resource_id=tone_key,
            item_count=len(values),
        )
        return ToneResult(values=dict(values), skipped_short=skipped)

    # 프롬프트 렌더 실패도 톤 LLM 실패와 같이 다룬다 — 문서 생성을 막지 않고 원본 값으로
    # 진행하되, 사유를 노출해 "톤이 적용된 문서"로 오인되지 않게 한다.
    try:
        system_prompt, user_prompt = build_tone_prompts(
            targets, preset.label, preset.instruction
        )
    except PromptRenderError as exc:
        log_warning(
            "톤 프롬프트 생성 실패 — 원본 값 유지",
            event="tone_prompt_render_failed",
            resource_id=tone_key,
            error_type=type(exc).__name__,
            item_count=len(targets),
        )
        return ToneResult(
            values=dict(values), skipped_short=skipped, llm_error_type=type(exc).__name__
        )

    result = await llm_call_async(system_prompt, user_prompt)
    if not result.ok:
        # 톤 적용 실패는 문서 생성을 막지 않는다 — 원본 값으로 진행하고 사실을 노출한다
        log_warning(
            "톤 적용 실패 — 원본 값 유지",
            event="tone_llm_failed",
            resource_id=tone_key,
            error_type=result.error_type,
            item_count=len(targets),
        )
        return ToneResult(
            values=dict(values), skipped_short=skipped, llm_error_type=result.error_type or "UNKNOWN"
        )

    converted, schema_rejected = _parse_converted(result.content, set(targets))

    final = dict(values)
    applied, rejected = [], [{"field": name, "reason": "schema"} for name in schema_rejected]
    for name, new_text in converted.items():
        issues = fact_diff(str(values[name]), new_text)
        if issues:
            # 숫자·날짜가 어긋난 변환은 채택하지 않는다 (사실 훼손 방지)
            rejected.append({"field": name, "reason": ",".join(issues)})
            continue
        if new_text != str(values[name]):
            final[name] = new_text
            applied.append(name)

    log_info(
        "톤 적용 완료",
        event="tone_applied",
        resource_id=tone_key,
        item_count=len(applied),
        status=f"targets={len(targets)} rejected={len(rejected)}",
    )
    if rejected:
        log_warning(
            "톤 변환 결과 일부 기각 — 해당 필드는 원본 유지",
            event="tone_conversion_rejected",
            resource_id=tone_key,
            item_count=len(rejected),
        )

    return ToneResult(
        values=final, applied=sorted(applied), rejected=rejected, skipped_short=skipped
    )
