"""글다듬이(SFR-018_text_polish) 실측 검증.

    python run_text_polish.py [--doc-type email] [--tone polite]

`Test/data/text_polish/*.hwpx` 를 전처리기(정본)로 마크다운으로 바꾼 뒤
`POST /polish` 로 보낸다. 글다듬이는 hwpx 직접 업로드 경로가 없다(문서 전체를
한 번에 보내는 단위라 그 자리가 없다) — 그래서 여기서만 hwpx→markdown 변환을
거친다(`_harness.hwpx_to_markdown`).
"""

from __future__ import annotations

import argparse
import sys

import _harness as h


def run_one(client, path, *, doc_type: str, tone: str) -> h.DocResult:
    doc_id = path.name
    try:
        markdown = h.hwpx_to_markdown(path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return h.DocResult(doc_id, ok=False, error=f"hwpx→markdown 실패: {type(exc).__name__}: {exc}")

    if not markdown.strip():
        return h.DocResult(doc_id, ok=False, error="문서에서 글자를 찾지 못했습니다")

    try:
        response = client.post(
            "/polish",
            json={"text": markdown, "doc_type": doc_type, "tone": tone, "title": doc_id},
            timeout=h.REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return h.DocResult(doc_id, ok=False, error=f"요청 실패: {type(exc).__name__}: {exc}")

    if response.status_code != 200:
        return h.DocResult(doc_id, ok=False, error=f"HTTP {response.status_code}: {response.text[:300]}")

    body = response.json()
    polished = str(body.get("polished_text") or "")
    if not polished:
        return h.DocResult(doc_id, ok=False, error="polished_text 가 비어 있습니다(전량 실패)")

    pairs = [
        {
            "id": doc_id,
            "source": markdown,
            "target": polished,
            "tone": tone,
            "doc_type": doc_type,
        }
    ]
    eval_report = h.eval_run_suite("text_polish", {"pairs": pairs, "answers": [polished]})

    return h.DocResult(
        doc_id,
        ok=True,
        raw={
            "n_char_source": len(markdown),
            "n_char_result": len(polished),
            "notice": body.get("notice"),
        },
        eval_report=eval_report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc-type", default="email", help="문서유형 코드 (기본 email)")
    parser.add_argument("--tone", default="polite", help="톤 코드 (기본 polite)")
    args = parser.parse_args()

    h.print_gateway_status()
    files = h.hwpx_files("text_polish")
    if not files:
        print(f"{h.DATA_DIR / 'text_polish'} 에 hwpx 파일이 없습니다 — 넣고 다시 실행하세요.")
        return 1

    client = h.boot_client("text_polish")
    results = [run_one(client, path, doc_type=args.doc_type, tone=args.tone) for path in files]

    summary = h.summarize("text_polish", results)
    h.print_summary(summary)
    report_path = h.save_report(
        "text_polish",
        {
            "summary": summary,
            "args": vars(args),
            "per_document": [
                {"id": r.doc_id, "raw": r.raw, "eval": r.eval_report, "error": r.error}
                for r in results
            ],
        },
    )
    print(f"\n전체 리포트: {report_path}")
    return 0 if summary["documents_passed"] == summary["documents_total"] else 1


if __name__ == "__main__":
    sys.exit(main())
