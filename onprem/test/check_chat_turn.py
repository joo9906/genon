"""SFR-006 대화(워크플로우 02) 한 턴 계약 점검 — LLM·Redis·GenOS 없이 돌린다.

`python onprem/test/check_chat_turn.py`

## 무엇을 보나

`run_chat.run()` 은 GenOS 워크플로우가 부르는 **고정 계약**(함수명 `run`, 인자 `data` 하나,
async generator, 마지막에 `event: result` 1회)이다. 이 계약과 한 턴의 상태 전이를 못 박는다:

- 스트리밍 규약: `token` 이벤트가 여러 번, `result` 이벤트가 **정확히 마지막 1회**
- 값 추출 → 화이트리스트 기각 → 세션 누적
- 본문 블록 추가/삭제, **삭제 번호는 추가 이전 목록 기준**
- 톤(글다듬이)이 값과 블록 **양쪽**에 걸리고, 숫자가 틀어지면 원문을 유지
- 다음 턴이 이전 턴의 값을 이어받는다 (세션 왕복)
- 오류(템플릿 없음)도 `result` 로 끝나고 `data["error"]` 를 담는다

LLM 은 대본을 돌려주는 가짜로 갈아 끼운다 — 무엇을 보내는지 검증하려는 것이 아니라,
**LLM 응답이 주어졌을 때 코드가 어떻게 판정하는지**가 이 점검의 대상이다.
(판정 책임이 코드에 있다는 것이 006 의 설계 전제다 — 루트 CLAUDE.md §5.)

## 여기 있는 이유

`check_api_contract.py` 와 같다. 가짜 LLM·가짜 Redis 주입은 배포 단위 **바깥**에서만
한다 — 운영 코드에 테스트 분기를 만들지 않기 위해서다(`onprem/` 규칙).
"""

import asyncio
import io
import json
import os
import sys
import tempfile
import zipfile

_UNIT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SFR-006_template_fill"
)
sys.path.insert(0, _UNIT)

_TEMPLATE_DIR = tempfile.mkdtemp(prefix="sfr006_chat_")
os.environ["TEMPLATE_FILL_TEMPLATE_DIR"] = _TEMPLATE_DIR

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"

_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{hp}">
  <hp:p paraPrIDRef="1">
    <hp:run charPrIDRef="1"><hp:secPr/></hp:run>
    <hp:run charPrIDRef="1"><hp:t>제 목 : {{'제 목', 고딕, 16pt}}</hp:t></hp:run>
  </hp:p>
  <hp:p paraPrIDRef="3"><hp:run charPrIDRef="3"><hp:t>주요 내용: {{'주요 내용', 휴먼명조, 11pt}}</hp:t></hp:run></hp:p>
</hs:sec>
""".format(hp=HP)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


class FakeLlmResult:
    def __init__(self, content: str) -> None:
        self.content, self.ok, self.error_type, self.is_transport_error = content, True, "", False


class LlmScript:
    """호출 순서대로 준비된 응답을 돌려주는 가짜 LLM.

    한 턴에 추출 1회 + (톤이 켜져 있으면) 값 톤 1회 + 블록 톤 1회가 나갈 수 있어서,
    순서를 그대로 대본으로 쓴다. 남는 호출이 있으면 마지막 응답을 재사용한다.
    """

    def __init__(self) -> None:
        self.queue: list = []
        self.calls: list = []

    def push(self, payload) -> None:
        self.queue.append(json.dumps(payload, ensure_ascii=False))

    async def __call__(self, system_prompt, user_prompt):
        self.calls.append(user_prompt)
        content = self.queue.pop(0) if self.queue else "{}"
        return FakeLlmResult(content)


def write_template(name: str) -> None:
    path = os.path.join(_TEMPLATE_DIR, f"{name}.hwpx")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", _SECTION.encode("utf-8"))
        zf.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><h/>')


def install_fakes():
    """가짜 Redis·LLM 을 꽂고 `run_chat` 을 돌려준다.

    **import 보다 먼저 꽂아야 한다.** `session_store`·`template_index` 는
    `from .redis_client import resolve_client` 로 **이름을 복사**하므로, 모듈이 로드된
    뒤에 `redis_client` 쪽만 갈아 끼우면 이미 복사된 원본이 계속 쓰인다
    (그러면 Redis 접속 실패로 세션이 매 턴 초기화돼 점검이 통째로 무의미해진다).
    """
    from template_fill import redis_client

    fake_redis = FakeRedis()
    redis_client.resolve_client = lambda: fake_redis

    from template_fill import run_chat as chat, tone_apply

    # 소비 모듈이 이미 이름을 복사해 갔다면 그쪽도 함께 바꾼다 (import 순서 무관하게)
    from template_fill import session_store, template_index

    session_store.resolve_client = redis_client.resolve_client
    template_index.resolve_client = redis_client.resolve_client

    script = LlmScript()
    chat.llm_call_async = script
    tone_apply.llm_call_async = script
    return chat, script


async def run_turn(chat, question: str, session_id: str, template_id: str, tone: str = "") -> tuple:
    """한 턴을 끝까지 돌리고 (이벤트 목록, result data) 를 돌려준다."""
    variables = {"template_fill_template_id": template_id}
    if tone:
        variables["template_fill_tone"] = tone
    data = {
        "question": question,
        "genos_state": {"session_id": session_id, "trace_id": "trace-1"},
        "overrideConfig": {"vars": variables},
    }
    events = [event async for event in chat.run(data)]
    result = next((e["data"] for e in events if e.get("event") == "result"), None)
    return events, result


class Report:
    def __init__(self) -> None:
        self.failures: list = []
        self.checks = 0

    def expect(self, condition: bool, label: str, detail="") -> None:
        self.checks += 1
        if condition:
            print(f"[OK  ] {label}")
            return
        self.failures.append(label)
        print(f"[FAIL] {label}")
        if detail:
            for line in str(detail).splitlines()[:6]:
                print(f"        {line}")


def main() -> int:
    rep = Report()
    chat, script = install_fakes()
    write_template("주간보고")

    # ── 1턴: 값 추출 + 화이트리스트 기각 ──
    script.push(
        {
            "updates": {"제 목": "8월 첫째 주 보고", "없는항목": "버려져야 함"},
            "clears": [],
        }
    )
    events, result = asyncio.run(run_turn(chat, "제목은 8월 첫째 주 보고야", "s1", "주간보고"))

    rep.expect(result is not None, "result 이벤트가 있다")
    rep.expect(
        events and events[-1].get("event") == "result",
        "result 가 마지막 이벤트다 (가이드 5.2)",
        [e.get("event") for e in events[-3:]],
    )
    rep.expect(
        sum(1 for e in events if e.get("event") == "result") == 1,
        "result 는 정확히 한 번만 나온다",
    )
    rep.expect(
        any(e.get("event") == "token" for e in events),
        "token 스트리밍이 있다",
    )
    rep.expect(result.get("field_values") == {"제 목": "8월 첫째 주 보고"}, "값이 누적된다", result.get("field_values"))
    rep.expect(result.get("fields_rejected") == ["없는항목"], "템플릿에 없는 항목은 기각", result.get("fields_rejected"))
    rep.expect(result.get("ready_for_download") is False, "미입력이 남으면 ready=false", result.get("fields_missing"))
    rep.expect(
        set(result.get("block_styles") or []) == {"제 목", "주요 내용"},
        "블록 서식 목록이 실린다",
        result.get("block_styles"),
    )

    # ── 2턴: 이전 값 유지 + 본문 블록 추가 ──
    script.push(
        {
            "updates": {"주요 내용": "핵심 요약"},
            "blocks": [
                {"style_ref": "제 목", "text": "1. 추진 배경"},
                {"style_ref": "주요 내용", "text": "전사 차원의 과제를 재정렬하였습니다."},
            ],
        }
    )
    _, result = asyncio.run(run_turn(chat, "주요 내용은 핵심 요약. 아래에 배경도 넣어줘", "s1", "주간보고"))

    rep.expect(
        result.get("field_values", {}).get("제 목") == "8월 첫째 주 보고",
        "이전 턴 값이 세션으로 이어진다",
        result.get("field_values"),
    )
    rep.expect(len(result.get("blocks") or []) == 2, "본문 블록이 추가된다", result.get("blocks"))
    rep.expect(result.get("blocks_added") == 2, "이번 턴 추가 개수", result)
    rep.expect(result.get("ready_for_download") is True, "항목이 다 차면 ready=true", result.get("fields_missing"))
    rep.expect(
        "1. 추진 배경" in (result.get("document_markdown") or ""),
        "대화 미리보기에 블록이 보인다",
        result.get("document_markdown"),
    )
    rep.expect(
        "본문 추가 내용" in (result.get("text") or ""),
        "답변에 본문 추가 목록이 번호로 표시된다",
        result.get("text"),
    )

    # ── 3턴: 삭제 번호는 '추가 이전' 목록 기준 ──
    script.push({"blocks": [{"style_ref": "제 목", "text": "2. 기대 효과"}], "block_clears": [1]})
    _, result = asyncio.run(run_turn(chat, "1번 빼고 기대 효과 넣어줘", "s1", "주간보고"))

    texts = [b["text"] for b in (result.get("blocks") or [])]
    rep.expect(
        texts == ["전사 차원의 과제를 재정렬하였습니다.", "2. 기대 효과"],
        "삭제(1번)를 먼저 하고 추가를 나중에 한다",
        texts,
    )
    rep.expect(result.get("blocks_removed") == 1, "이번 턴 삭제 개수", result)

    # ── 4턴: 톤이 값과 블록 양쪽에 걸린다 ──
    script.push(
        {
            "updates": {"주요 내용": "상반기 매출은 108% 달성하였습니다."},
            "blocks": [{"style_ref": "주요 내용", "text": "하반기에도 같은 기조를 유지하겠습니다."}],
        }
    )
    script.push({"converted": {"주요 내용": "상반기 매출 999% 달성함."}})  # 숫자 훼손 → 기각
    script.push({"converted": {"본문 1": "하반기에도 같은 기조를 유지함."}})
    _, result = asyncio.run(
        run_turn(chat, "매출 실적이랑 하반기 방향 넣어줘", "s2", "주간보고", tone="report")
    )

    rep.expect(
        result.get("field_values", {}).get("주요 내용") == "상반기 매출은 108% 달성하였습니다.",
        "숫자가 틀어진 톤 변환은 기각하고 원문을 지킨다",
        result.get("field_values"),
    )
    rep.expect(
        [r["field"] for r in (result.get("tone_rejected_fields") or [])] == ["주요 내용"],
        "값 톤 기각이 노출된다",
        result.get("tone_rejected_fields"),
    )
    blocks = result.get("blocks") or []
    rep.expect(
        blocks and blocks[0]["text"] == "하반기에도 같은 기조를 유지함.",
        "본문 블록에도 톤이 걸린다",
        blocks,
    )
    rep.expect(
        blocks and blocks[0]["raw_text"] == "하반기에도 같은 기조를 유지하겠습니다.",
        "블록의 톤 적용 전 원문이 보존된다",
        blocks,
    )
    rep.expect(
        result.get("tone_applied_blocks") == ["본문 1"],
        "블록 톤 적용 결과가 노출된다",
        result.get("tone_applied_blocks"),
    )

    # ── 오류 경로: 템플릿 없음 ──
    events, result = asyncio.run(run_turn(chat, "아무 말", "s3", "없는템플릿"))
    rep.expect(
        events and events[-1].get("event") == "result" and result.get("error"),
        "오류도 result 로 끝나고 error 를 담는다 (가이드 3.9.6)",
        result.get("error") if result else None,
    )
    rep.expect(
        (result.get("error") or {}).get("error_code", "").startswith("02-"),
        "워크플로우 영역코드(02)를 쓴다",
        result.get("error"),
    )

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
