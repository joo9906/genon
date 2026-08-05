"""스모크 공용 픽스처 — 현장 템플릿과 같은 형태의 hwpx + 공용 대역(double)들.

왜 필요한가: 스모크는 실제 현장 템플릿(`data/파워.hwpx`)으로 확인했지만 그 파일은
샘플 문서라 커밋하지 않았다. 그래서 **같은 성질을 가진 합성 템플릿**을 여기서 만들어
파일이 없는 환경에서도 그대로 돌 수 있게 한다:

- 라벨이 여러 run 으로 쪼개져 있다 (`제 목` / ` : ` / `{제목, HY헤드라인M, 16pt}`)
- 콜론 앞에 줄맞춤 공백이 있는 항목과 없는 항목이 섞여 있다 (`제 목 : ` vs `주요 내용: `)
- `{…}` 에 서식 명세와 **값 안내**가 섞여 있다 (`{소속} {성명}`, `{YYYY.MM.DD. (요일)}`)

`data/파워.hwpx` 가 있으면 그것을 우선 쓴다 (실물 검증이 항상 더 낫다).

Redis·LLM 대역과 부트스트랩도 여기 하나만 둔다. 스모크마다 복사해 두면 계약이 바뀔 때
(예: `resolve_client()` 가 새 명령을 쓰기 시작할 때) 스크립트가 하나씩 따로 깨진다.
"""

import io
import os
import sys
import tempfile
import zipfile

from redis.exceptions import RedisError

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"

# 저장소 루트 = 이 파일의 2단계 상위 (SFR-006/smoke/fixture.py)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ONPREM_UNIT = os.path.join(REPO_ROOT, "onprem", "SFR-006_template_fill")
SAMPLE_PATH = os.path.join(REPO_ROOT, "data", "파워.hwpx")

HEADER = f"""<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="{HH}">
  <hh:refList>
    <hh:fontfaces itemCnt="2">
      <hh:fontface lang="HANGUL" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF"/></hh:fontface>
      <hh:fontface lang="LATIN" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF"/></hh:fontface>
    </hh:fontfaces>
    <hh:charProperties itemCnt="1">
      <hh:charPr id="0" height="1000"><hh:fontRef hangul="0" latin="0"/></hh:charPr>
    </hh:charProperties>
  </hh:refList>
</hh:head>
"""


def para(runs: str) -> str:
    # 문단 id 는 실제 문서처럼 전부 같은 값을 쓴다 (id 기반 주소 지정 금지 규칙 재현)
    return f'<hp:p id="2147483648">{runs}</hp:p>'


def run(text: str) -> str:
    return f'<hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run>'


def pack(sections: dict, header: str = HEADER) -> bytes:
    """hwpx(zip) 조립.

    Args:
        sections: {엔트리명: xml 문자열}. **넣는 순서를 그대로 쓴다** — 엔트리 순서가
            아니라 섹션 번호로 정렬되는지 확인하려고 일부러 역순으로 넣는 스모크가 있다.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # mimetype 은 무압축 규약 (압축하면 한/글이 열지 못한다)
        zf.writestr("mimetype", "application/hwp+zip", zipfile.ZIP_STORED)
        zf.writestr("Contents/header.xml", header)
        for name, xml in sections.items():
            zf.writestr(name, xml)
    return buf.getvalue()


# 현장 템플릿(파워.hwpx)의 본문과 같은 구성
_SECTION = f"""<?xml version="1.0" encoding="UTF-8"?>
<hp:sec xmlns:hp="{HP}">
  {para(run("제 목") + run(" : ") + run("{제목, HY헤드라인M, 16pt}"))}
  {para(run("본문 : ") + run("{본문, 맑은 고딕, 11pt}"))}
  {para(run(""))}
  {para(run("배포일 : {YYYY.MM.DD. (요일)}"))}
  {para(run("담당자 : ") + run("{소속} {성명}"))}
  {para(run(""))}
  {para(run("주요 내용: {휴먼 명조, 15pt}"))}
</hp:sec>
"""


def synthetic_template() -> bytes:
    """현장 템플릿과 같은 항목·서식 명세를 가진 합성 hwpx."""
    return pack({"Contents/section0.xml": _SECTION})


def template_bytes() -> tuple[bytes, str]:
    """검증에 쓸 템플릿 바이트와 출처.

    Returns:
        (hwpx bytes, "sample" | "synthetic")
    """
    if os.path.exists(SAMPLE_PATH):
        with open(SAMPLE_PATH, "rb") as handle:
            return handle.read(), "sample"
    return synthetic_template(), "synthetic"


def patch_hwpx(src: bytes, before: str, after: str) -> bytes:
    """본문 XML 안의 문자열을 바꾼 새 hwpx (zip 내부라 raw 치환으로는 안 된다)."""
    buf = io.BytesIO()
    changed = False
    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("Contents/section"):
                text = data.decode("utf-8")
                if before in text:
                    data = text.replace(before, after).encode("utf-8")
                    changed = True
            compress = (
                zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
            )
            zout.writestr(item.filename, data, compress_type=compress)
    if not changed:
        raise AssertionError(f"{before!r} 를 본문에서 찾지 못했다")
    return buf.getvalue()


# ── 공통 부트스트랩 ──────────────────────────────────────────
def bootstrap(prefix: str, *, write_template: bool = False) -> str:
    """import 경로·출력 인코딩·임시 템플릿 디렉토리를 준비한다.

    환경변수를 **`template_fill` import 전에** 세워야 한다 (Config 가 import 시점에
    읽는다). 그래서 스모크는 반드시 `bootstrap()` 을 먼저 부르고 그 다음에 임포트한다.

    Args:
        write_template: 템플릿을 디렉토리에 미리 써 둘지 (등록 API 를 거치지 않는 경로용).

    Returns:
        임시 템플릿 디렉토리 경로 (스크립트 끝에서 `shutil.rmtree` 로 지운다).
    """
    if ONPREM_UNIT not in sys.path:
        sys.path.insert(0, ONPREM_UNIT)
    sys.stdout.reconfigure(encoding="utf-8")
    template_dir = tempfile.mkdtemp(prefix=prefix)
    os.environ["TEMPLATE_FILL_TEMPLATE_DIR"] = template_dir
    os.environ["LOG_LEVEL"] = "ERROR"
    if write_template:
        payload, _ = template_bytes()
        with open(os.path.join(template_dir, "파워.hwpx"), "wb") as handle:
            handle.write(payload)
    return template_dir


# ── Redis 대역 ───────────────────────────────────────────────
class FakeRedis:
    """최소 Redis 대역 — get/set/delete 만. 세션 저장소와 색인 캐시가 함께 쓴다.

    장애 주입 두 가지 (degrade 경로가 실제로 도는지 보려면 둘이 구분돼야 한다):
    - `fail=True`: 모든 명령이 실패 (인프라 전면 장애 → 색인은 직접 파싱으로 degrade)
    - `fail_set_prefix=...`: 그 접두사로 시작하는 키의 `set` 만 실패
      (세션 저장만 실패시켜, 색인 캐시는 살아 있는 상태를 만든다)
    """

    def __init__(self, *, fail: bool = False, fail_set_prefix: str | None = None):
        self.store: dict = {}
        self.fail = fail
        self.fail_set_prefix = fail_set_prefix

    def _guard(self) -> None:
        if self.fail:
            raise RedisError("fake down")

    async def get(self, key):
        self._guard()
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self._guard()
        if self.fail_set_prefix and key.startswith(self.fail_set_prefix):
            raise RedisError("fake down")
        self.store[key] = value

    async def delete(self, key):
        self._guard()
        self.store.pop(key, None)


def install_fake_redis(**kwargs) -> FakeRedis:
    """공용 Redis 클라이언트를 대역으로 바꾼다 (`bootstrap()` 이후에 부른다)."""
    from template_fill import redis_client

    fake = FakeRedis(**kwargs)
    redis_client._CLIENT = fake
    return fake


# ── LLM 대역 ─────────────────────────────────────────────────
class StubResult:
    """`llm.LlmResult` 대역 — content 만 쓴다."""

    def __init__(self, content: str):
        self.content = content
        self.ok = True
        self.is_transport_error = False
        self.error_type = None


def make_fake_llm(reply: dict):
    """`llm_call_async` 대역. `reply["content"]` 를 돌려주고 마지막 프롬프트를 기록한다.

    프롬프트를 기록하는 이유: 대화가 "지금까지 모인 값"을 실제로 LLM 에 실어 보내는지
    확인하는 것이 크로스 경로 검증의 핵심이다 (화면에서 고친 값이 다음 턴에 보이는가).
    """

    async def fake_llm(system_prompt, user_prompt, **kwargs):
        fake_llm.last_user_prompt = user_prompt
        return StubResult(reply["content"])

    fake_llm.last_user_prompt = None
    return fake_llm
