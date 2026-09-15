"""FAQ 항목 **증분 파서** — 델타를 먹여 완성된 조각을 그때그때 뽑는다.

> **스트리밍·비스트리밍이 이 파서 하나를 쓴다** (`generator._parse_faq_payload` 도
> `parse_all` 을 부른다). 경로마다 파서를 두면 마크다운 파서가 스트리밍 요청에서만
> 돌아 **거의 검증되지 않는 갈래**가 된다.

## 왜 JSON 이 아닌가 — **10초 안에 첫 글자**

JSON 은 **미완성 상태를 파싱할 수 없다.** 그래서 JSON 으로 받으면 조각 하나가 통째로
끝나야 화면에 무언가를 낼 수 있고, 그게 30~60초다. 구분자 형식은 필드가 닫히는 순간을
알 수 있어 **한 항목씩**, 나아가 **한 필드씩** 내보낼 수 있다.

## 필드 순서가 설계의 전부다

프롬프트가 `근거 → 질문 → 답변` 순으로 쓰게 한다. 그래야 검증이 **접두어 연산**이 된다:

| 이벤트 | 그 시점에 할 수 있는 것 |
|---|---|
| `evidence` | **근거 대조** — 실패면 그 항목은 한 글자도 화면에 안 나간다 |
| `question` | **중복 판정** — 실패면 역시 버린다 |
| `answer_delta` | 위 둘을 통과한 항목이므로 **토큰 그대로 흘려도 된다** |
| `item_end` | 스키마 확인(세 필드가 다 찼나) 후 채택 |

항목이 다 만들어진 뒤에 검증하면 **기각될 항목이 이미 화면에 나타난 뒤**다 — 이
저장소가 계속 피해 온 "답이 나왔다가 사라진다" 가 그것이다.

## 구분자를 어기면 그 항목은 기각이다

`json.loads` 라는 깨끗한 실패 지점을 잃는 대가다. 라벨이 흔들리면 필드가 섞인 채
통과할 여지가 있으므로 **세 필드가 다 있고 비어 있지 않을 때만** 완성으로 본다.
나머지는 호출부가 `rejected_schema` 로 센다 — 조용히 버리지 않는다.

**라벨 상수는 프롬프트(`prompt/SFR-018_faq/md_system.txt`)와 사본 관계다.** 한쪽만
고치면 모든 항목이 스키마 기각으로 떨어지는데, 그 상태는 "FAQ 가 하나도 안 나온다" 로만
드러난다 — 예외도 로그도 없다. 프롬프트를 고칠 때 이 세 상수를 함께 본다.

## 버리는 판정은 여기가 아니다

이 파서는 **일부러 관용적이다** — 모델이 `>>>` 를 빠뜨리는 일이 흔해서 닫히지 않은
마지막 묶음도 흘려보내고, 필드가 빈 항목도 그대로 내놓는다. 채택 여부는
`generator._adopt_one` 이 정하고 거기서 `rejected_schema` 로 센다. 두 층을 헷갈리면
"파서가 걸러 줄 것" 이라 믿고 채택 판정을 지우게 되고, 그러면 **답변이 빈 항목이
결과에 실린다.**
"""

from dataclasses import dataclass, field

# 프롬프트와 **글자 그대로** 같아야 한다 (위 머리말).
OPEN_MARK = "<<<FAQ"
CLOSE_MARK = ">>>"
LABELS = {
    "근거:": "evidence",
    "질문:": "question",
    "답변:": "answer",
}

# 이벤트 종류
EVIDENCE = "evidence"
QUESTION = "question"
ANSWER_DELTA = "answer_delta"
ITEM_END = "item_end"


@dataclass(frozen=True)
class Event:
    """파서가 내는 사건 하나.

    `kind` 가 `item_end` 일 때만 `item` 이 찬다. 나머지는 `text` 만 쓴다.
    """

    kind: str
    text: str = ""
    item: dict = field(default_factory=dict)


def _blank_item() -> dict:
    return {"evidence": "", "question": "", "answer": ""}


class ItemStream:
    """LLM 델타를 먹여 이벤트를 받는다. **상태를 들고 있으므로 요청마다 새로 만든다.**

    사용:

        stream = ItemStream()
        for delta in ...:
            for event in stream.feed(delta):
                ...
        for event in stream.finish():   # 닫히지 않은 마지막 묶음까지 흘려보낸다
            ...
    """

    def __init__(self) -> None:
        self._line = ""          # 아직 개행을 못 만난 현재 줄
        self._in_item = False
        self._field = ""         # 지금 채우고 있는 필드
        self._item = _blank_item()
        # 이 항목의 답변으로 **이미 내보낸** 글자 수. 줄이 끝나기 전에 흘리므로
        # 어디까지 냈는지를 들고 있어야 같은 글자를 두 번 내보내지 않는다.
        self._answer_emitted = 0
        # 현재 줄이 `답변:` 을 달고 있는가. 그 줄에서만 증분을 흘린다 —
        # 이어지는 줄은 `>>>` 일 수 있어서 반쪽(`>`·`>>`)이 화면에 나갈 위험이 있다.
        self._answer_line = False

    # ── 입력 ────────────────────────────────────────────────
    def feed(self, text: str) -> list:
        """델타 한 조각을 먹인다. 이번에 확정된 이벤트 목록을 돌려준다."""
        events: list = []
        for char in text:
            if char == "\n":
                events.extend(self._end_line())
            elif char == "\r":
                continue  # CRLF 를 흡수한다 — 줄 판정이 개행 하나로만 돌게
            else:
                self._line += char
        events.extend(self._partial())
        return events

    def finish(self) -> list:
        """입력이 끝났다. 남은 줄과 **닫히지 않은 묶음**을 정리한다.

        `>>>` 없이 끝난 항목도 세 필드가 차 있으면 내보낸다 — 모델이 마지막 닫기를
        빠뜨리는 일이 흔한데, 그것 때문에 멀쩡한 항목 하나를 버릴 이유가 없다.
        호출부의 스키마 검사가 최종 판정을 한다.
        """
        events: list = []
        if self._line:
            events.extend(self._end_line())
        if self._in_item:
            events.append(Event(kind=ITEM_END, item=dict(self._item)))
            self._reset_item()
        return events

    # ── 내부 ────────────────────────────────────────────────
    def _reset_item(self) -> None:
        self._in_item = False
        self._field = ""
        self._item = _blank_item()
        self._answer_emitted = 0
        self._answer_line = False

    def _end_line(self) -> list:
        line, self._line = self._line, ""
        self._answer_line = False
        stripped = line.strip()

        if not self._in_item:
            # 묶음 밖 — 여는 표식만 본다. 그 앞의 글자(설명·인사말)는 버린다.
            if stripped.startswith(OPEN_MARK):
                self._in_item = True
                self._item = _blank_item()
                self._field = ""
                self._answer_emitted = 0
            return []

        if stripped.startswith(CLOSE_MARK):
            item = dict(self._item)
            self._reset_item()
            return [Event(kind=ITEM_END, item=item)]

        if stripped.startswith(OPEN_MARK):
            # 닫기를 빠뜨리고 다음 묶음이 시작됐다. 여기서 앞 항목을 끊어 준다 —
            # 안 그러면 두 항목의 필드가 섞여 **한 항목으로 통과**한다.
            item = dict(self._item)
            self._reset_item()
            self._in_item = True
            return [Event(kind=ITEM_END, item=item)]

        label = self._label_of(stripped)
        if label:
            value = stripped[len(label[0]):].strip()
            name = label[1]
            self._field = name
            self._item[name] = value
            if name == "answer":
                # 줄이 끝나며 확정된 부분 중 아직 안 낸 만큼을 흘린다.
                delta = value[self._answer_emitted:]
                self._answer_emitted = len(value)
                return [Event(kind=ANSWER_DELTA, text=delta)] if delta else []
            return [Event(kind=name, text=value)]

        if self._field == "answer" and stripped:
            # 답변이 여러 줄로 왔다 (형식 위반이지만 버리지 않는다). 한 줄로 잇는다 —
            # 줄바꿈을 그대로 두면 화면 조립과 파일 산출에서 항목 경계가 흐려진다.
            joined = (self._item["answer"] + " " + stripped).strip()
            self._item["answer"] = joined
            delta = joined[self._answer_emitted:]
            self._answer_emitted = len(joined)
            return [Event(kind=ANSWER_DELTA, text=delta)] if delta else []

        return []

    def _partial(self) -> list:
        """줄이 끝나기 전에 **답변만** 증분으로 흘린다.

        근거·질문은 흘리지 않는다 — 그 둘은 **검증 재료**이고, 검증 전에 화면에 나가면
        기각될 항목이 보였다 사라진다(이 파서의 존재 이유).
        """
        if not self._in_item or not self._line:
            return []
        label = self._label_of(self._line.lstrip())
        if label and label[1] == "answer":
            self._answer_line = True
        if not self._answer_line:
            return []
        # 현재 줄에서 라벨을 뗀 나머지가 지금까지의 답변이다.
        head = self._line.lstrip()
        value = head[len("답변:"):].lstrip()
        self._item["answer"] = value
        delta = value[self._answer_emitted:]
        if not delta:
            return []
        self._answer_emitted = len(value)
        return [Event(kind=ANSWER_DELTA, text=delta)]

    @staticmethod
    def _label_of(stripped: str):
        for mark, name in LABELS.items():
            if stripped.startswith(mark):
                return mark, name
        return None


def parse_all(text: str) -> list:
    """완성된 응답 전체에서 항목을 뽑는다 — **비스트리밍 경로가 쓴다.**

    스트리밍과 **같은 파서**를 지나게 하는 것이 요점이다. 경로마다 파서를 두면
    마크다운 파서가 스트리밍 요청에서만 돌아 **거의 검증되지 않는 갈래**가 된다.
    """
    stream = ItemStream()
    items: list = []
    for event in list(stream.feed(text)) + list(stream.finish()):
        if event.kind == ITEM_END:
            items.append(event.item)
    return items


def is_complete(item: dict) -> bool:
    """세 필드가 다 있고 비어 있지 않은가. **아니면 호출부가 스키마 기각으로 센다.**"""
    return all(str(item.get(name, "")).strip() for name in ("evidence", "question", "answer"))
