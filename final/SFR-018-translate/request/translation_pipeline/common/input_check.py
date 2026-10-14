"""입력 판단 — 번역할 만한 글인가 (`POST /input/check`).

워크플로우 스텝 1(번역-1)이 원문을 확정한 뒤 부른다. 뜻을 알 수 없는 입력(낱자모 나열 ·
빈 표 틀)을 본 기능에 넣으면 LLM 이 거절 문장을 지어내거나 입력을 되뱉고, 그 결과가 정상
응답처럼 나간다. 여기서 먼저 걸러 스텝이 "입력 내용을 확인해 주세요" 로 끝낸다.

글다듬이 단위 `text_polish/input_check.py` 와 같은 계약의 사본이다(배포 단위 간
import 금지) — 다른 것은 LLM 호출 함수와 프롬프트 문구뿐이다.

## 판단이 실패하면 통과시킨다 (fail-open)

판단기는 품질 장치다. LLM 장애 · 화이트리스트 밖 응답 · 프롬프트 부재로 판단을 못 하면
`judged=False` 로 **통과**시키고 사유를 로그에 남긴다 — 판단기 때문에 기능 전체가 서면
안 된다.

## 응답은 화이트리스트로만 받는다

`{"usable": bool, "reason": 코드}` 이고 `usable` 과 `reason` 이 서로 맞아야 한다
(`true` ↔ `ok`, `false` ↔ `gibberish`/`no_content`). 그 밖은 판단 실패로 본다.

## 앞부분만 보낸다

`INPUT_CHECK_MAX_CHARS` 까지만 보낸다 — 비용 · 지연 상한이다. 앞부분이 멀쩡하면 문서 전체를
번역할 만한 글로 본다.
"""

import asyncio
import json
import re
from dataclasses import dataclass

from config import Config
from translation_pipeline.common.llm import llm_call_async
from translation_pipeline.common.logging_utils import log_info, log_warning
from translation_pipeline.common.prompt_loader import (
    PromptRenderError,
    render as render_prompt,
)

INPUT_CHECK_MAX_CHARS = 2000

REASON_OK = "ok"
# 판단 LLM 이 낼 수 있는 "못 돌린다" 사유. 스텝이 사유별로 문구를 가르지는 않지만 로그 ·
# 응답에 남겨 어떤 입력이 막혔는지 볼 수 있게 한다.
UNUSABLE_REASONS = frozenset({"gibberish", "no_content"})
# 판단을 못 했을 때의 사유 — LLM 이 낸 값이 아니다.
REASON_NOT_JUDGED = "not_judged"

_JSON_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)


@dataclass(frozen=True)
class InputVerdict:
    usable: bool
    reason: str
    judged: bool

    def as_payload(self) -> dict:
        return {"usable": self.usable, "reason": self.reason, "judged": self.judged}


def parse_verdict(content: str):
    """판단 LLM 응답을 `(usable, reason)` 으로. 화이트리스트 밖이면 `None`.

    모델이 코드펜스나 앞뒤 말을 붙이는 경우가 있어 첫 JSON 객체만 본다.
    """
    match = _JSON_OBJECT.search(content or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    usable = data.get("usable")
    reason = data.get("reason")
    if usable is True and reason == REASON_OK:
        return True, reason
    if usable is False and reason in UNUSABLE_REASONS:
        return False, reason
    return None


def _not_judged(status: str, error_type: str = "") -> InputVerdict:
    log_warning(
        "입력 판단을 못 해 통과시킨다",
        event="input_check_skipped",
        resource_id="input_check",
        status=status,
        error_type=error_type,
    )
    return InputVerdict(usable=True, reason=REASON_NOT_JUDGED, judged=False)


async def check_input(text: str) -> InputVerdict:
    """입력이 번역할 만한지 판단한다. 예외를 던지지 않는다 — 실패는 통과다."""
    head = (text or "").strip()[:INPUT_CHECK_MAX_CHARS]
    try:
        system_prompt = render_prompt("input_check_system.md")
    except PromptRenderError:
        return _not_judged("prompt_render_failed")

    result = await llm_call_async(
        asyncio.Semaphore(1), system_prompt, head,
        serving_id=Config.input_check_serving_id(),
    )
    if not result.ok:
        return _not_judged("llm_failed", result.error_type)

    parsed = parse_verdict(result.content)
    if parsed is None:
        return _not_judged("response_rejected")

    usable, reason = parsed
    log_info(
        "입력 판단 완료",
        event="input_check_done",
        resource_id="input_check",
        status=reason,
        item_count=len(head),
    )
    return InputVerdict(usable=usable, reason=reason, judged=True)
