"""FAQ(SFR-018_faq) 실측 검증 — 산출률·스키마 준수·근거 중복도·PII.

    python run_faq.py [--count 5]

`Test/data/faq/*.hwpx` 를 `POST /generate/upload` 로 보낸다. 응답이 그대로
`FaqResult.as_payload()` 모양이라(`requested_count`·`count`·`rejected`·
`coverage_capped`·`chunks_planned`·`chunks_used`) eval 의 `faq_generation_health`
에 그대로 먹인다 — 따로 조립하지 않는다(손으로 다시 만들면 응답이 키를 바꿔도
이 스크립트만 옛 키를 읽게 된다).

**근거 대조(`grounding_overlap`)는 스크리닝일 뿐이다** — 어휘 중복이 낮다고 곧
오답은 아니다(재서술). 원문은 FAQ 가 실제로 쓰는 파서(`faq.hwpx_text.to_markdown`)
로 다시 열어 만든다 — 다른 파서로 열면 LLM 이 실제로 본 것과 다른 원문을
대조하게 된다.
"""

from __future__ import annotations

import argparse
import sys

import _harness as h


def run_one(client, path, faq_to_markdown, max_context_chars: int, *, count: int) -> h.DocResult:
    doc_id = path.name
    raw = path.read_bytes()

    try:
        parsed = faq_to_markdown(raw, max_context_chars)
    except Exception as exc:  # noqa: BLE001
        return h.DocResult(doc_id, ok=False, error=f"hwpx 파싱 실패: {type(exc).__name__}: {exc}")

    try:
        response = client.post(
            "/generate/upload",
            files={"document": (doc_id, raw, "application/octet-stream")},
            data={"count": str(count)},
            timeout=h.REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return h.DocResult(doc_id, ok=False, error=f"요청 실패: {type(exc).__name__}: {exc}")

    if response.status_code != 200:
        return h.DocResult(doc_id, ok=False, error=f"HTTP {response.status_code}: {response.text[:300]}")

    body = response.json()
    items = body.get("items") or []
    source_markdown = parsed.markdown

    grounding_items = [
        {"id": f"{doc_id}#{i}", "answer": str(item.get("answer") or ""), "sources": [source_markdown]}
        for i, item in enumerate(items)
        if str(item.get("answer") or "").strip()
    ]
    answers = [str(item.get("answer") or "") for item in items]

    eval_payload = {"generation": body, "answers": answers}
    if grounding_items:
        eval_payload["items"] = grounding_items
    eval_report = h.eval_run_suite("faq", eval_payload)

    return h.DocResult(
        doc_id,
        ok=True,
        raw={
            "requested_count": body.get("requested_count"),
            "count": body.get("count"),
            "rejected": body.get("rejected"),
            "coverage_capped": body.get("coverage_capped"),
            "source_truncated": body.get("source_truncated"),
            "chunks_planned": body.get("chunks_planned"),
            "chunks_used": body.get("chunks_used"),
        },
        eval_report=eval_report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5, help="요청할 FAQ 개수 (기본 5)")
    args = parser.parse_args()

    h.print_gateway_status()
    files = h.hwpx_files("faq")
    if not files:
        print(f"{h.DATA_DIR / 'faq'} 에 hwpx 파일이 없습니다 — 넣고 다시 실행하세요.")
        return 1

    client = h.boot_client("faq")
    # `faq` 패키지가 방금 부팅으로 sys.path 에 올라와 있다 — FAQ 가 실제로 쓰는
    # 파서·설정을 그대로 재사용한다(새 hwpx 파서를 만들지 않는다는 규약 그대로).
    from faq.config import Config as FaqConfig
    from faq.hwpx_text import to_markdown as faq_to_markdown

    results = [
        run_one(client, path, faq_to_markdown, FaqConfig.MAX_CONTEXT_CHARS, count=args.count)
        for path in files
    ]

    summary = h.summarize("faq", results)
    h.print_summary(summary)
    report_path = h.save_report(
        "faq",
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
