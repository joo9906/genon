"""`test_preprocessor.py` 를 만든다 — **hwpx 단독 등록** 시험용 판본.

## 왜 이 판본이 따로 필요한가 (2026-09-02)

합친 등록 단위(`final_preprocessor.py`)는 벤더 절반으로 **우리가 뜬 참조 사본**
(`genos_files/attach_processor.py`, v.2.2.4)을 담는데, 사이트에 설치된
`genon.preprocessor` 가 그보다 낮은 판본이라 최상위 import 두 개가 없다:

    genon.preprocessor.facade.enrichment.page_description   # 2026-09-02 가드 씌움
    genon.preprocessor.facade.guardrail                     # #315 민감정보 마스킹

attach 절반이 통째로 한 `try:` 안이라 import 하나가 죽으면 `_FP_ATTACH_IMPORT_ERROR`
가 서고 라우터가 **hwpx 아닌 전 형식을 거부한다** — hwpx 는 가드 밖이라 그대로 돌아
"pdf 만 안 되는" 얼굴로 나타난다.

**그 벽을 우회하지 않고 없앤다.** 사이트에는 첨부용 전처리기가 이미 등록돼 돌고 있으므로
우리가 올릴 것은 hwpx 하나면 된다. 이 판본에는 `genon.preprocessor` import 가 **0개**라
사이트 패키지 판본이 무엇이든 영향을 받지 않는다.

| | 합친 단위 | 이 판본 |
|---|---|---|
| 받는 확장자 | 전부 | `.hwpx` 만 |
| `genon.preprocessor` 의존 | 있다 (판본 어긋남에 걸린다) | **없다** |
| 나머지 형식 | 우리 파일 안 attach 절반 | **사이트의 첨부용 등록**(손대지 않는다) |

## 생성물이지 사본이 아니다

정본은 `hwpx_preprocessor.py` 다. 손으로 복사해 두면 정본을 고쳤을 때 **옛 코드를
올리게 되고 그 실수는 잡을 그물이 없다**(치는 순간에는 맞아 보인다). 그래서 매번
생성하고, 생성물에 **정본의 sha** 를 박아 컨테이너 로그로 대조한다.

    python onprem/preprocessor/build_test_preprocessor.py             # 생성
    python onprem/preprocessor/build_test_preprocessor.py --print-sha # 지금 정본의 sha
    python onprem/preprocessor/build_test_preprocessor.py --check     # 생성물이 최신인가

`--check` 가 서면 정본이 바뀐 채로 생성물이 옛 코드다 — 그 상태로 올리면 안 된다.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SOURCE = os.path.join(_HERE, "hwpx_preprocessor.py")
_OUTPUT = os.path.join(_HERE, "test_preprocessor.py")

# 등록 파일에 박히는 표식. `hwpx_preprocessor.py` 의 임시 디버그 블록이 쓰는 것과 같은
# 문자열을 **리터럴로** 둔다 — 그 블록을 지워도 이 줄이 `NameError` 로 죽지 않게.
_DEBUG_TAG = "[GENON-DEBUG]"

_HEADER = """\
# ===========================================================================
# [생성물] hwpx 단독 등록 시험용 — **손으로 고치지 말 것**
# ===========================================================================
#
#   정본:   onprem/preprocessor/hwpx_preprocessor.py
#   생성:   python onprem/preprocessor/build_test_preprocessor.py
#
# 이 파일을 고치면 다음 생성에 지워진다. 고칠 곳은 정본이다.
#
# ## 등록 방법
#
# 1. GenOS 전처리기 **생성** 화면에 이 파일 하나를 올린다(기존 등록을 덮지 않는다).
# 2. 받을 확장자를 **`hwpx` 만** 고른다.
#    - 다른 확장자를 함께 걸면 그 형식은 적재가 **실패**한다(빈 결과가 아니라 예외다).
#    - 나머지 형식은 사이트에 이미 등록된 **첨부용 전처리기**가 그대로 맡는다.
# 3. 컨테이너 로그에서 아래 세 줄을 확인한다.
#
#        {tag} test_preprocessor loaded sha=xxxxxxxxxxxx
#        {tag} engine=hwpx file=....hwpx chunks=NN
#        {tag} first200>>>
#
#    첫 줄의 sha 가 `--print-sha` 값과 다르면 **업로드가 반영되지 않은 것**이다.
#
# ## 확인이 끝나면
#
# `{tag}` 로 검색되는 블록 둘(적재 판본 표식 · 디버그 덤프)을 지운다 —
# 문서 본문이 컨테이너 로그에 남는 것은 §3.8 이 금지하는 것이고, 확인용으로 일부러
# 넣은 것이다. 운영에 그대로 두지 말 것.
# ===========================================================================
"""

_TAIL = """\


# ===========================================================================
# [테스트 등록 전용] 적재 판본 표식 — 확인이 끝나면 이 블록을 지운다
# ===========================================================================
#
# **올린 파일이 정말 바뀌었는지는 이 한 줄로만 확인된다.** 전처리기는 실패해도 "그
# 형식이 원래 안 되는 것" 처럼 보이므로, 고친 판본이 반영됐는지를 결과만 보고 가릴 수
# 없다. sha 가 그대로면 업로드가 반영되지 않은 것이다.
#
#     python onprem/preprocessor/build_test_preprocessor.py --print-sha

_TEST_SOURCE_SHA = "{sha}"

print(
    "{tag} test_preprocessor loaded"
    " sha={sha_short} src=hwpx_preprocessor.py engine=hwpx-only",
    flush=True,
)
"""


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _sha(text: str) -> str:
    # 줄바꿈을 정규화한 뒤 해시한다 — CRLF 로 체크아웃한 사람과 LF 인 사람이 같은 값을
    # 봐야 한다(그렇지 않으면 sha 대조가 "환경이 다르다" 만 말하게 된다).
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _render(source: str) -> str:
    sha = _sha(source)
    header = _HEADER.format(tag=_DEBUG_TAG)
    tail = _TAIL.format(tag=_DEBUG_TAG, sha=sha, sha_short=sha[:12])
    return header + source + tail


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-sha", action="store_true", help="정본의 sha 만 찍는다")
    parser.add_argument(
        "--check", action="store_true", help="생성물이 지금 정본과 맞는지만 본다(쓰지 않는다)"
    )
    args = parser.parse_args(argv)

    source = _read(_SOURCE)
    sha = _sha(source)

    if args.print_sha:
        print(sha)
        return 0

    rendered = _render(source)

    if args.check:
        if not os.path.exists(_OUTPUT):
            print(f"[build] FAIL: {_OUTPUT} 가 없다 — 생성할 것", file=sys.stderr)
            return 1
        if _read(_OUTPUT) != rendered:
            print(
                "[build] FAIL: test_preprocessor.py 가 정본과 어긋난다"
                " — 다시 생성하고 올릴 것",
                file=sys.stderr,
            )
            return 1
        print(f"[build] OK: 최신이다 (sha={sha[:12]})")
        return 0

    with open(_OUTPUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(rendered)

    lines = rendered.count("\n") + 1
    print(f"[build] {os.path.relpath(_OUTPUT, os.getcwd())} ({lines}줄, sha={sha[:12]})")
    print("[build] 등록 시 받을 확장자는 hwpx 만 고를 것 — 나머지는 첨부용 등록이 맡는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
