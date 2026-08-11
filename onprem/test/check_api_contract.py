"""SFR-006 코드 서빙 API 계약 점검 — 서버·Redis 없이 전 엔드포인트를 한 바퀴 돌린다.

`python onprem/test/check_api_contract.py`

## 왜 있나

`verify_serving.py` 는 **배포된 서빙**에 요청을 보낸다. 그전에, 지금 소스가 계약대로
응답하는지를 확인할 수단이 없었다. 코드 서빙의 엔드포인트가 12개이고 대부분이 세션·색인·
문서 생성을 엮기 때문에, 한 곳을 고치면 다른 곳이 조용히 깨지기 쉽다.

이 점검은 FastAPI 앱을 **인프로세스**로 띄워(`TestClient`) 전 경로를 한 번씩 지난다.
Redis 는 메모리 가짜로 갈아 끼우고, 템플릿 볼륨은 임시 디렉토리를 쓴다. 그래서
네트워크도 포트도 외부 서비스도 필요 없다.

**성격은 특성화(characterization) 점검이다** — "지금 동작이 이렇다" 를 못 박아 두고,
리팩토링이 그것을 바꾸지 않았음을 확인하는 용도다. 개별 함수의 옳고 그름은
`check_body_blocks.py`(문서 조작)와 `check_tone_policy.py`(정책 사본)가 본다.

## 여기 있는 이유 (배포 계약 점검 폴더인데)

`check_body_blocks.py` 와 같다 — 배포 단위 **바깥**이라 이미지에 흘러가지 않고,
`onprem/` 규칙상 배포 단위 안에는 `tests/` 를 둘 수 없다. 가짜 Redis 같은 테스트 장치를
운영 코드에 넣지 않으려면 **주입은 반드시 배포 단위 밖에서** 해야 한다.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 공용 픽스처 헬퍼
_UNIT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "codeserving",  # 2026-08-11 영역별 재배치
    "SFR-006_template_fill",
)
sys.path.insert(0, _UNIT)

import hwpx_package  # noqa: E402  - 온전한 OPC 패키지 뼈대 (배포 단위 바깥)

# 앱 import 전에 환경을 확정한다 — Config 는 모듈 로드 시점에 환경변수를 읽는다.
_TEMPLATE_DIR = tempfile.mkdtemp(prefix="sfr006_templates_")
os.environ["TEMPLATE_FILL_TEMPLATE_DIR"] = _TEMPLATE_DIR
os.environ["TEMPLATE_FILL_ADMIN_TOKEN"] = "test-admin-token"

from fastapi.testclient import TestClient  # noqa: E402

from template_fill import redis_client  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
ADMIN = {"X-Admin-Token": "test-admin-token"}


class FakeRedis:
    """`get`/`set`/`delete` 만 쓰는 메모리 대체품.

    세션 저장소와 색인 캐시가 쓰는 연산이 이 셋뿐이다(`session_store`·`template_index`).
    TTL(`ex`)은 만료를 흉내 내지 않고 받아서 버린다 — 이 점검은 만료를 보지 않는다.
    """

    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{hp}">
  <hp:p paraPrIDRef="1">
    <hp:run charPrIDRef="1"><hp:secPr/></hp:run>
    <hp:run charPrIDRef="1"><hp:t>제 목 : {{'제 목', 고딕, 16pt, 굵게}}</hp:t></hp:run>
  </hp:p>
  <hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:tbl rowCnt="1" colCnt="1">
    <hp:sz width="14000" widthRelTo="ABSOLUTE" height="3000" heightRelTo="ABSOLUTE"/>
    <hp:pos treatAsChar="0" vertRelTo="PARA" horzRelTo="COLUMN" vertOffset="0" horzOffset="0"/>
    <hp:outMargin left="0" right="0" top="0" bottom="0"/>
    <hp:inMargin left="510" right="510" top="141" bottom="141"/>
    <hp:tr>
      <hp:tc><hp:subList>
        <hp:p><hp:run charPrIDRef="0"><hp:t>보고자: {{'보고자'}}</hp:t></hp:run></hp:p>
      </hp:subList>
      <hp:cellAddr colAddr="0" rowAddr="0"/>
      <hp:cellSpan colSpan="1" rowSpan="1"/>
      <hp:cellSz width="14000" height="3000"/>
      <hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>
    </hp:tr>
  </hp:tbl></hp:run></hp:p>
  <hp:p paraPrIDRef="3"><hp:run charPrIDRef="3"><hp:t>주요 내용: {{'주요 내용', 휴먼명조, 11pt}}</hp:t></hp:run></hp:p>
</hs:sec>
""".format(hp=HP)

_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="{hh}">
  <hh:refList>
    <hh:fontfaces>
      <hh:fontface lang="HANGUL" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF"/></hh:fontface>
    </hh:fontfaces>
    <hh:charProperties itemCnt="4">
      <hh:charPr id="0" height="1000"><hh:fontRef hangul="0"/></hh:charPr>
      <hh:charPr id="1" height="1000"><hh:fontRef hangul="0"/></hh:charPr>
      <hh:charPr id="2" height="500"><hh:fontRef hangul="0"/></hh:charPr>
      <hh:charPr id="3" height="1000"><hh:fontRef hangul="0"/></hh:charPr>
    </hh:charProperties>
  </hh:refList>
</hh:head>
""".format(hh=HH)


def build_fixture() -> bytes:
    """**온전한 OPC 패키지**로 만든다 (`hwpx_package.build`).

    `POST /generate` 는 개봉 안전 게이트를 지나며, 그 게이트는 2026-08-10 이후 모든
    환경에서 돈다. 여기가 운영 경로라 게이트를 끌 수 없으므로(끄면 이 점검이 검증하려던
    계약이 사라진다) 픽스처가 온전해야 한다. 표에 `hp:sz`·`cellSz` 등 필수 자식을
    적어 둔 것도 같은 이유다 — 그게 빠진 문서는 한/글이 실제로 거절한다.
    """
    return hwpx_package.build(_SECTION, _HEADER)


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
            for line in str(detail).splitlines()[:6]:
                print(f"        {line}")


def main() -> int:
    rep = Report()
    # 세션과 색인이 같은 저장소를 봐야 하므로 **인스턴스 하나**를 고정해 돌려준다
    # (매번 새로 만들면 방금 저장한 세션을 다음 요청이 못 읽는다).
    fake = FakeRedis()
    redis_client.resolve_client = lambda: fake

    from template_fill.main import app

    client = TestClient(app)
    template = build_fixture()
    session = "sess-contract-001"

    # ── 헬스체크 ──
    res = client.get("/health")
    rep.expect(res.status_code == 200 and res.json() == {"status": "ok"}, "GET /health", res.text)

    # ── 루트 경로 ──
    # 게이트웨이가 서빙 베이스를 경로 없이 때리는 배포가 있다. `@app.get("")` 만 두면
    # **아무 경로에도 매칭되지 않아** 둘 다 404 가 되는데, 그 상태가 2026-08-07~08-11
    # 사이 세 코드서빙 단위에 그대로 있었다 — 점검이 루트를 아예 안 봐서 못 잡았다.
    for path in ("/", ""):
        res = client.get(path)
        rep.expect(
            res.status_code == 200 and res.json().get("status") == "ok",
            f"GET {path!r} (게이트웨이 베이스 경로)",
            f"{res.status_code} {res.text}",
        )

    # ── 관리자 인증 ──
    res = client.post(
        "/templates", files={"template": ("보고서.hwpx", template)}, data={"template_id": "보고서"}
    )
    rep.expect(res.status_code == 403, "POST /templates 토큰 없으면 403", res.text)

    res = client.post(
        "/templates",
        files={"template": ("보고서.hwpx", template)},
        data={"template_id": "보고서"},
        headers=ADMIN,
    )
    rep.expect(res.status_code == 201, "POST /templates 등록", res.text)
    body = res.json() if res.status_code == 201 else {}
    names = [f["name"] for f in body.get("fields", [])]
    rep.expect(
        {"제 목", "보고자", "주요 내용"} <= set(names),
        "등록 응답에 표 안 라벨까지 항목으로 잡힌다",
        names,
    )

    res = client.post(
        "/templates",
        files={"template": ("보고서.hwpx", template)},
        data={"template_id": "보고서"},
        headers=ADMIN,
    )
    rep.expect(res.status_code == 409, "POST /templates 중복이면 409", res.text)

    res = client.post("/templates", files={"template": ("x.txt", b"nope")}, headers=ADMIN)
    rep.expect(res.status_code == 400, "POST /templates hwpx 아니면 400", res.text)

    # ── 목록·항목 ──
    res = client.get("/templates")
    rep.expect(
        res.status_code == 200 and "보고서" in res.json().get("templates", []),
        "GET /templates 목록",
        res.text,
    )

    res = client.get("/fields", params={"template_id": "보고서"})
    payload = res.json() if res.status_code == 200 else {}
    rep.expect(res.status_code == 200, "GET /fields", res.text)
    rep.expect(
        "주요 내용" in payload.get("block_styles", [])
        and "보고자" not in payload.get("block_styles", []),
        "GET /fields 의 block_styles 는 본문 라벨만 (표 안 라벨 제외)",
        payload.get("block_styles"),
    )

    res = client.get("/fields", params={"template_id": "없는템플릿"})
    rep.expect(res.status_code == 404, "GET /fields 없는 템플릿이면 404", res.text)

    # ── 값 수정 ──
    res = client.patch(
        "/values",
        json={
            "session_id": session,
            "template_id": "보고서",
            "values": {"제 목": "상반기 실적", "없는항목": "무시돼야 함"},
        },
    )
    payload = res.json() if res.status_code == 200 else {}
    rep.expect(res.status_code == 200, "PATCH /values", res.text)
    rep.expect(payload.get("updated_fields") == ["제 목"], "PATCH /values 반영 목록", payload)
    rep.expect(payload.get("rejected_fields") == ["없는항목"], "PATCH /values 기각 노출", payload)
    rep.expect("상반기 실적" in payload.get("markdown", ""), "PATCH /values 응답에 미리보기", payload)

    # ── 본문 블록 ──
    res = client.put(
        "/blocks",
        json={
            "session_id": session,
            "template_id": "보고서",
            "blocks": [
                {"text": "1. 추진 배경", "style_ref": "제 목"},
                {"text": "세부 설명입니다.", "style_ref": "없는서식"},
                {"text": "   "},
            ],
        },
    )
    payload = res.json() if res.status_code == 200 else {}
    rep.expect(res.status_code == 200, "PUT /blocks", res.text)
    rep.expect(len(payload.get("blocks", [])) == 2, "PUT /blocks 빈 본문만 버린다", payload.get("blocks"))
    rep.expect(
        any("없는서식" in r for r in payload.get("rejected_blocks", [])),
        "PUT /blocks 모르는 서식은 기각 사유로 노출",
        payload.get("rejected_blocks"),
    )
    rep.expect(
        "1. 추진 배경" in payload.get("markdown", ""),
        "PUT /blocks 응답 미리보기에 블록이 보인다",
        payload.get("markdown"),
    )

    # ── 현황·미리보기 ──
    res = client.get("/status", params={"session_id": session})
    payload = res.json() if res.status_code == 200 else {}
    rep.expect(res.status_code == 200, "GET /status", res.text)
    rep.expect(payload.get("block_count") == 2, "GET /status 의 block_count", payload)
    rep.expect(
        payload.get("ready_for_download") is False and "보고자" in payload.get("fields_missing", []),
        "GET /status 미입력 항목이 남으면 ready=false",
        payload,
    )

    res = client.get("/preview", params={"session_id": session})
    preview_markdown = res.json().get("markdown", "") if res.status_code == 200 else ""
    rep.expect(res.status_code == 200, "GET /preview", res.text)
    rep.expect("1. 추진 배경" in preview_markdown, "GET /preview 에 블록 포함", preview_markdown)

    # ── 값 삭제 ──
    res = client.request(
        "DELETE",
        "/values",
        json={"session_id": session, "template_id": "보고서", "fields": ["제 목"]},
    )
    payload = res.json() if res.status_code == 200 else {}
    rep.expect(res.status_code == 200 and payload.get("deleted_fields") == ["제 목"], "DELETE /values", res.text)
    rep.expect(
        len(payload.get("blocks", [])) == 2,
        "DELETE /values 가 본문 블록을 지우지 않는다",
        payload.get("blocks"),
    )

    # ── 문서 생성 ──
    res = client.post(
        "/generate",
        json={
            "template_id": "보고서",
            "session_id": session,
            "values": {"제 목": "상반기 실적", "보고자": "왕주영", "주요 내용": "핵심 요약"},
        },
    )
    rep.expect(res.status_code == 200, "POST /generate", res.text)
    rep.expect(
        res.headers.get("content-type") == "application/octet-stream",
        "POST /generate 는 바이너리를 내려준다",
        res.headers.get("content-type"),
    )
    rep.expect(res.headers.get("x-body-blocks") == "2", "POST /generate 의 X-Body-Blocks", dict(res.headers))
    generated = res.content
    rep.expect(generated[:2] == b"PK", "POST /generate 결과가 zip(hwpx)", generated[:8])

    if generated[:2] == b"PK":
        from template_fill.hwpx_markdown import render_markdown

        text = render_markdown(generated).markdown
        rep.expect("1. 추진 배경" in text, "생성 문서에 본문 블록이 들어 있다", text)
        rep.expect(
            text.count("1. 추진 배경") == 1,
            "본문 블록이 중복 삽입되지 않는다",
            text,
        )
        rep.expect(preview_markdown.split("\n")[0] in text, "미리보기와 생성 문서의 첫 문단이 같다", text)

    res = client.post("/generate", json={"template_id": "보고서", "format": "docx"})
    rep.expect(res.status_code == 400, "POST /generate 모르는 format 이면 400", res.text)

    res = client.post("/generate", json={"template_id": "없는템플릿"})
    rep.expect(res.status_code == 404, "POST /generate 없는 템플릿이면 404", res.text)

    # 생성 성공 = 세션 종료
    res = client.get("/status", params={"session_id": session, "template_id": "보고서"})
    payload = res.json() if res.status_code == 200 else {}
    rep.expect(
        payload.get("block_count") == 0 and not payload.get("values"),
        "생성에 성공하면 세션이 비워진다",
        payload,
    )

    # ── 업로드 생성 ──
    res = client.post(
        "/generate/upload",
        files={"template": ("즉석.hwpx", template)},
        data={
            "values": json.dumps({"제 목": "즉석 보고"}, ensure_ascii=False),
            "blocks": json.dumps([{"text": "업로드 경로 본문", "style_ref": "주요 내용"}], ensure_ascii=False),
        },
    )
    rep.expect(res.status_code == 200, "POST /generate/upload", res.text)
    if res.status_code == 200:
        from template_fill.hwpx_markdown import render_markdown

        text = render_markdown(res.content).markdown
        rep.expect("업로드 경로 본문" in text, "업로드 경로도 본문 블록을 반영한다", text)

    res = client.post(
        "/generate/upload", files={"template": ("즉석.hwpx", template)}, data={"blocks": "not-json"}
    )
    rep.expect(res.status_code == 400, "POST /generate/upload blocks 가 JSON 아니면 400", res.text)

    # ── 삭제 ──
    res = client.delete("/templates/보고서", headers=ADMIN)
    rep.expect(res.status_code == 200, "DELETE /templates", res.text)
    res = client.get("/fields", params={"template_id": "보고서"})
    rep.expect(res.status_code == 404, "삭제 후에는 404", res.text)

    print()
    if rep.failures:
        print(f"FAIL {len(rep.failures)} / {rep.checks}")
        return 1
    print(f"OK {rep.checks} / {rep.checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
