"""배포된 코드 서빙 확인 — 가이드 11.3 최소 합격 조건을 실제로 때려본다.

**이 스크립트는 서버를 띄우지 않는다.** 이미 배포된 서빙에 요청을 보내기만 한다.
포트를 열지 않으므로 로컬 환경을 건드리지 않는다.

가이드 11.3 은 코드 서빙을 health 응답만으로 판단하지 말라고 정한다:

    GET  /health          → 200, {"status": "ok"}
    정상 입력             → 200 + 문서에 정의한 필수 key
    필드 누락             → 422
    외부 시스템 timeout   → 504 (또는 API 문서에 정의한 응답)

앞의 셋은 여기서 자동으로 확인한다. **timeout 경로는 자동화하지 않는다** — 게이트웨이
LLM 서빙을 실제로 지연시켜야 하고, 가짜로 만들면 확인한 것이 없다. 아래 안내만 출력한다.

실행 (stdlib 만 쓴다):

    python onprem/test/verify_serving.py translation \
        --base-url https://genos.example.com --serving-id 42 --token "$GENOS_TOKEN"

    python onprem/test/verify_serving.py template_fill \
        --base-url https://genos.example.com --serving-id 43 --token "$GENOS_TOKEN"

`--direct http://127.0.0.1:8080` 으로 게이트웨이를 건너뛰고 컨테이너를 직접 볼 수도 있다
(운영 호출 경로가 아니므로 디버깅 용도로만).

종료 코드: 실패한 케이스가 있으면 1.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

TIMEOUT_SECONDS = 20


@dataclass
class Case:
    """확인 케이스 하나."""

    name: str
    method: str
    path: str
    expect_status: int
    body: dict | None = None
    expect_keys: tuple[str, ...] = ()
    why: str = ""  # 어떤 가이드 조항 때문에 보는지


@dataclass
class Target:
    """확인 대상 배포 단위."""

    key: str
    title: str
    cases: list[Case] = field(default_factory=list)
    timeout_note: str = ""


TARGETS: dict[str, Target] = {
    "translation": Target(
        key="translation",
        title="SFR-018 번역 (코드 서빙 03)",
        cases=[
            Case(
                name="health",
                method="GET",
                path="/health",
                expect_status=200,
                expect_keys=("status",),
                why="가이드 6.4 — 상태 확인 프로그램이 직접 호출하는 경로",
            ),
            Case(
                name="정상 입력 — 노드 번역",
                method="POST",
                path="/translate",
                body={
                    "nodes": [{"id": "n1", "text": "사업 개요"}],
                    "target_lang": "en",
                },
                expect_status=200,
                expect_keys=("pairs", "text", "translation_error"),
                why="가이드 11.3 — 정상 입력의 응답이 API 문서와 일치하는지",
            ),
            Case(
                name="정상 입력 — 마크다운 구조 보존",
                method="POST",
                path="/translate/markdown",
                body={
                    "markdown": "| 항목 | 값 |\n|---|---|\n| 매출 | 100 |",
                    "target_lang": "en",
                },
                expect_status=200,
                expect_keys=("markdown", "pairs", "translation_error"),
                why="표 구조가 응답에서 유지되는지 (마크다운 파이프 개수 육안 확인)",
            ),
            Case(
                name="필드 누락 — target_lang 없음",
                method="POST",
                path="/translate",
                body={"nodes": [{"id": "n1", "text": "사업 개요"}]},
                expect_status=422,
                why="가이드 11.3 — 입력 검증 실패가 422 로 나오는지",
            ),
            Case(
                name="필드 누락 — markdown 빈 문자열",
                method="POST",
                path="/translate/markdown",
                body={"markdown": "", "target_lang": "en"},
                expect_status=422,
                why="min_length=1 제약이 실제로 걸리는지",
            ),
        ],
        timeout_note=(
            "게이트웨이 LLM 서빙을 지연시킨 뒤 POST /translate 를 호출해 504 와 "
            "error_code 03-00020001 이 나오는지 확인한다. 응답 본문에 stack trace 가 "
            "섞이지 않는 것도 같이 본다 (가이드 6.4)."
        ),
    ),
    "template_fill": Target(
        key="template_fill",
        title="SFR-006 템플릿 채우기 (코드 서빙 03)",
        cases=[
            Case(
                name="health",
                method="GET",
                path="/health",
                expect_status=200,
                expect_keys=("status",),
                why="가이드 6.4 — 상태 확인 경로",
            ),
            Case(
                name="정상 입력 — 템플릿 목록",
                method="GET",
                path="/templates",
                expect_status=200,
                why="볼륨 마운트와 색인 캐시가 붙었는지. indexed 값을 눈으로 확인한다",
            ),
            Case(
                name="필드 누락 — template_id 없이 /fields",
                method="GET",
                path="/fields",
                expect_status=422,
                why="가이드 11.3 — 입력 검증 실패 경로",
            ),
            Case(
                name="없는 자원 — 존재하지 않는 세션",
                method="GET",
                path="/status?session_id=__none__",
                expect_status=404,
                why="RESOURCE 오류가 404 로 매핑되는지 (GENOS_RULES §A.2)",
            ),
        ],
        timeout_note=(
            "Redis 를 끊은 뒤 PATCH /values 를 호출해 500 이 나오는지 확인한다 "
            "(세션 저장 실패는 화면에만 반영된 상태를 성공으로 보이게 하지 않는다). "
            "템플릿 색인은 반대로 degrade 해야 하므로 GET /fields 는 계속 200 이어야 한다."
        ),
    ),
}


def _request(url: str, method: str, token: str, body: dict | None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # 연결 실패 자체를 결과로 돌려준다
        return 0, f"{type(exc).__name__}: {exc}"


def _base(args: argparse.Namespace) -> str:
    if args.direct:
        return args.direct.rstrip("/")
    if not args.base_url or not args.serving_id:
        raise SystemExit("--base-url 과 --serving-id 를 주거나 --direct 를 쓴다")
    root = args.base_url.rstrip("/")
    # 가이드 6.8: {GENOS_URL}/api/gateway/code_serving/<id>/<앱 경로>
    if not root.endswith("/api/gateway"):
        root = f"{root}/api/gateway"
    return f"{root}/code_serving/{args.serving_id}"


def run(target: Target, args: argparse.Namespace) -> int:
    base = _base(args)
    print(f"# {target.title}")
    print(f"# base: {base}\n")

    failed = 0
    for case in target.cases:
        status, text = _request(f"{base}{case.path}", case.method, args.token, case.body)
        ok = status == case.expect_status

        missing_keys: list[str] = []
        if ok and case.expect_keys:
            try:
                payload = json.loads(text)
                missing_keys = [k for k in case.expect_keys if k not in payload]
                ok = not missing_keys
            except json.JSONDecodeError:
                ok = False
                missing_keys = ["<JSON 아님>"]

        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case.name}")
        print(f"       {case.method} {case.path} → {status} (기대 {case.expect_status})")
        if case.why:
            print(f"       근거: {case.why}")
        if missing_keys:
            print(f"       응답에 없는 key: {', '.join(missing_keys)}")
        if not ok:
            failed += 1
            print(f"       본문: {text[:300]}")
        print()

    print("---")
    print("자동화하지 않는 케이스 — 직접 확인한다 (가이드 11.3 의 외부 timeout 자리):")
    print(f"  {target.timeout_note}\n")
    print(f"결과: {len(target.cases) - failed}/{len(target.cases)} 통과")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=sorted(TARGETS), help="확인할 배포 단위")
    parser.add_argument("--base-url", help="GENOS_URL (호스트 루트). /api/gateway 는 붙여 준다")
    parser.add_argument("--serving-id", help="코드 서빙 ID")
    parser.add_argument("--token", default="", help="Bearer 토큰")
    parser.add_argument("--direct", help="게이트웨이 우회 직접 주소 (디버깅 전용)")
    args = parser.parse_args()
    return run(TARGETS[args.target], args)


if __name__ == "__main__":
    sys.exit(main())
