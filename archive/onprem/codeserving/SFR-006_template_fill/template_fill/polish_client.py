"""본문 블록을 **글다듬이 서빙에 맡겨** 다듬는다 (2026-09-15 요구 추가).

## 왜 006 안에서 다시 만들지 않나

006 에는 2026-08-12 까지 자체 톤 변환(`tone_apply.py`, 346줄)이 있었고, 그때
톤 프리셋 표가 **4벌**이었다(MCP·글다듬이·006·eval). 지우면서 3벌로 줄었다.
여기서 되살리면 그 4벌로 되돌아가고, 같은 톤 지시문이 두 단위에 살게 된다 —
한쪽만 고치면 **같은 톤이 기능마다 다른 문체**를 내고 오류로는 드러나지 않는다.

그래서 **글다듬이 서빙을 부른다.** 이 저장소에서 서빙이 서빙을 부르는 첫 자리다.
금지된 것은 배포 단위 간 **import** 이고(§D.3), 게이트웨이를 지나는 HTTP 호출은
워크플로우 스텝이 늘 하던 것과 같다.

## 스텝이 아니라 서빙이 부르는 이유

템플릿별 문체 지시문이 **006 프롬프트 디렉토리**에 있는데, **워크플로우 스텝은
프롬프트 파일을 못 읽는다**(프롬프트는 코드서빙 이미지에만 들어간다). 스텝이 부르면
"006 이 지시문을 스텝에 내려주고 스텝이 글다듬이로 넘기는" 3자 왕복이 되고, 006 을
두 번 부르게 된다. 게다가 `/chat/commit` 은 **병합·저장·미리보기가 한 요청**이라
(나누면 "저장은 됐는데 미리보기에서 실패한" 중간 상태가 캔버스에 생긴다) 다듬기가
그 앞에 들어가야 한다.

## 계약 셋

1. **실패는 오류가 아니다** (fail-open). 다듬기가 안 되면 **원문 그대로** 넣는다 —
   사용자가 원래 하려던 일(템플릿 채우기)이 문체 손질 때문에 막히면 안 된다.
   그 사실은 `PolishOutcome.failed` 로 알리고 답변이 한 줄 말한다.
2. **숫자·날짜가 바뀌면 원문을 쓴다** (`value_guard`). 다듬기는 LLM 이 문장을 다시
   쓰는 단계이고 프롬프트 지시는 보장이 아니다(§5). 그리고 이 값은 **hwpx 파일에
   그대로 박히므로** 되돌릴 수 없다 — "2025년 3월 5일" 이 조용히 달라지면 사용자가
   파일을 열어 보기 전까지 아무도 모른다.
3. **항목 값은 건드리지 않는다** (요구 확정). 이 모듈은 본문 블록만 받는다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from .config import Config
from .logging_utils import log_info, log_warning
from .value_guard import fact_diff

# 글다듬이 코드서빙 경로. 게이트웨이 표준 경로(§H)를 **여기 한 곳에서만** 만든다 —
# f-string 으로 base 를 직접 이어붙이면 `/api/gateway` prefix 를 빠뜨린다(018 두 단위가
# 실제로 그래서 게이트웨이를 지나지 않고 있었다 — 2026-08-05 수정).
_POLISH_PATH = "/polish"


@dataclass
class PolishOutcome:
    """다듬기 결과 — **블록 텍스트 목록과 왜 못 했는지**.

    Attributes:
        texts: 블록마다의 최종 본문. 다듬지 못했거나 값이 어긋난 자리는 **원문**이다.
        failed: 다듬기 호출이 실패한 블록 수.
        guarded: 숫자·날짜가 어긋나 **원문으로 되돌린** 블록 수.
        skipped: 다듬기를 아예 시도하지 않았다 (꺼져 있거나 배선이 없다).
    """

    texts: list = field(default_factory=list)
    failed: int = 0
    guarded: int = 0
    skipped: bool = False


def _gateway_base() -> str:
    """`{GENOS_URL}/api/gateway` — 이미 그걸로 끝나면 중복시키지 않는다."""
    base = Config.genos_url().rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/api/gateway") else f"{base}/api/gateway"


def _polish_url() -> str:
    serving_id = Config.text_polish_serving_id()
    base = _gateway_base()
    if not base or not serving_id:
        return ""
    return f"{base}/code_serving/{serving_id}{_POLISH_PATH}"


def polish_policy(template_id: str) -> tuple:
    """이 템플릿에 쓸 `(톤, 문서유형)`.

    표기는 `템플릿=톤/문서유형` 목록이다(`Config.POLISH_MAP_RAW`). **목록에 없으면
    전역 기본값**으로 떨어진다 — 빠뜨린 템플릿에서 다듬기가 멈추는 것보다 "그 템플릿만
    문체가 기본값" 인 편이 낫다.

    **형식이 깨진 항목은 건너뛴다.** 환경변수 오타 하나로 서빙이 안 뜨면 그 사실이
    "기능이 통째로 죽었다" 로 보인다 (`prompt_library.prompt_ids` 와 같은 규약).
    """
    default = (Config.POLISH_TONE, Config.POLISH_DOC_TYPE)
    wanted = (template_id or "").strip()
    if not wanted or not Config.POLISH_MAP_RAW:
        return default
    for part in Config.POLISH_MAP_RAW.split(","):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        if name.strip() != wanted:
            continue
        tone, _, doc_type = value.strip().partition("/")
        return (tone.strip() or default[0], doc_type.strip() or default[1])
    return default


async def _polish_one(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    text: str,
    tone: str,
    doc_type: str,
    instruction: str,
) -> tuple:
    """한 블록. `(본문, 사유)` — 사유가 비면 다듬어진 것이다.

    **블록마다 따로 부른다.** 이어 붙여 한 번에 보내면 다듬은 글을 다시 블록으로
    쪼개야 하는데, LLM 이 문단을 합치면 그 경계가 사라진다 — 블록 수가 보통 한 자릿수라
    호출 수보다 경계가 중요하다.
    """
    body = {
        "text": text,
        "tone": tone,
        "doc_type": doc_type,
        "extra_instruction": instruction,
    }
    try:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 실패는 분류만 하고 원문으로 진행한다
        return "", type(exc).__name__
    if not isinstance(payload, dict):
        return "", "BAD_RESPONSE"
    polished = str(payload.get("polished_text") or "").strip()
    if not polished:
        return "", "EMPTY_RESULT"
    return polished, ""


async def polish_blocks(
    blocks: list, template_id: str, instruction: str = ""
) -> PolishOutcome:
    """본문 블록들을 다듬는다 — **실패해도 예외를 올리지 않는다.**

    Args:
        blocks: `BodyBlock` 목록 (`text` 속성을 읽는다).
        template_id: 톤·문서유형을 고르는 키.
        instruction: 템플릿별 문체 지시문. 글다듬이가 문서유형 지시문 **뒤에** 잇는다.

    Returns:
        `PolishOutcome`. `texts` 는 **언제나 블록 수만큼** 있다 — 실패한 자리에는 원문이
        들어간다. 빈 목록을 돌려주면 그 구간이 통째로 사라진 결과가 정상 응답처럼 나간다.
    """
    originals = [str(getattr(item, "text", "") or "") for item in blocks]
    if not originals:
        return PolishOutcome(texts=[])

    url = _polish_url()
    if not Config.POLISH_BLOCKS or not url:
        # **왜 안 돌았는지가 갈려야 한다** — 껐는가, 배선이 없는가.
        log_info(
            "본문 다듬기를 건너뛴다",
            event="polish_skipped",
            status="disabled" if not Config.POLISH_BLOCKS else "not_configured",
            item_count=len(originals),
        )
        return PolishOutcome(texts=originals, skipped=True)

    # **토큰은 여기서 한 번 읽는다** — `Config.genos_token()` 은 값이 없으면 예외를
    # 던진다(다른 필수 설정과 같은 규약). 블록마다 읽으면 그 예외가 `gather` 를 타고
    # 올라가 **커밋 전체가 죽는다** — 다듬기 실패는 커밋 실패가 아니라는 계약이 그
    # 자리에서 깨진다. 스모크가 실제로 잡았다.
    try:
        headers = {"Authorization": f"Bearer {Config.genos_token()}"}
    except Exception:  # noqa: BLE001 - 설정 부재는 다듬기를 건너뛸 사유이지 오류가 아니다
        log_warning(
            "게이트웨이 토큰이 없어 본문 다듬기를 건너뛴다",
            event="polish_skipped",
            status="no_token",
            item_count=len(originals),
        )
        return PolishOutcome(texts=originals, skipped=True)

    tone, doc_type = polish_policy(template_id)
    timeout = httpx.Timeout(
        connect=3.0, read=Config.POLISH_TIMEOUT, write=5.0, pool=3.0
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(
            *(
                _polish_one(client, url, headers, text, tone, doc_type, instruction)
                for text in originals
            )
        )

    outcome = PolishOutcome(texts=[])
    for original, (polished, reason) in zip(originals, results):
        if reason:
            outcome.failed += 1
            outcome.texts.append(original)
            continue
        # **숫자·날짜가 바뀌면 원문을 쓴다** (위 계약 2). 이 값은 hwpx 에 그대로
        # 박히므로 되돌릴 수 없다.
        issues = fact_diff(original, polished)
        if issues:
            outcome.guarded += 1
            outcome.texts.append(original)
            log_warning(
                "다듬은 본문의 사실 정보가 어긋나 원문을 유지한다",
                event="polish_fact_drift",
                status=",".join(issues),
            )
            continue
        outcome.texts.append(polished)

    log_info(
        "본문 다듬기 완료",
        event="polish_blocks_done",
        resource_id=f"{tone}/{doc_type}" if doc_type else tone,
        item_count=len(originals),
        status=f"failed={outcome.failed},guarded={outcome.guarded}",
    )
    return outcome
