"""번역(SFR-018_translation) 실측 검증 — 실제 게이트웨이로 실제 hwpx 를 번역하고
숫자 보존·구조 건전성·용어사전 준수·PII 를 채점한다.

    python run_translation.py [--target-lang en] [--source-lang ""] [--register ""]

`Test/data/translation/*.hwpx` 를 전부 `POST /translate/hwpx` 로 보낸다. hwpx 를
직접 올리는 이유는 정본 경로가 그것이기 때문이다 — 전처리기를 태우면 표 안
수치가 깨진다(요구사항 §5, `final/CLAUDE.md`).

**문서 단위로 채점한다.** 여러 문서를 한 번에 eval 에 몰아넣으면 "몇 문서 중 몇
문서가 통과했는지" 가 사라지고 뭉뚱그려진 평균만 남는다 — 어느 파일이 실패했는지
알아야 다음 손을 쓸 수 있다.
"""

from __future__ import annotations

import argparse
import sys

import _harness as h


def run_one(client, path, *, target_lang: str, source_lang: str, register: str) -> h.DocResult:
    doc_id = path.name
    raw = path.read_bytes()
    try:
        response = client.post(
            "/translate/hwpx",
            files={"document": (doc_id, raw, "application/octet-stream")},
            data={"target_lang": target_lang, "source_lang": source_lang, "register": register},
            timeout=h.REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — 문서 하나의 통신 실패로 나머지를 멈추지 않는다
        return h.DocResult(doc_id, ok=False, error=f"요청 실패: {type(exc).__name__}: {exc}")

    if response.status_code != 200:
        return h.DocResult(doc_id, ok=False, error=f"HTTP {response.status_code}: {response.text[:300]}")

    body = response.json()
    if body.get("translation_error"):
        # 계약: `translation_error` 가 있으면 그게 사용자가 보는 오류다(§3.8 고정 안내문).
        return h.DocResult(doc_id, ok=False, error=f"translation_error={body['translation_error']}")

    source_markdown = str(body.get("source_markdown") or "")
    translated_markdown = str(body.get("markdown") or "")
    stats = body.get("stats") or {}

    pairs = [{"id": doc_id, "source": source_markdown, "target": translated_markdown}]
    records = [
        {
            "id": doc_id,
            "segments_in": stats.get("unit_count", 0),
            # "실제로 결과를 낸 유닛" == 전체 - 실패 유닛. `failed_unit_count` 는 서빙이
            # 이미 세어 응답에 낸 값이라 여기서 다시 셀 필요가 없다(2026-08-14 결정).
            "segments_out": max(0, stats.get("unit_count", 0) - stats.get("failed_unit_count", 0)),
            "fallback": bool(stats.get("fallback_rate", 0) > 0),
        }
    ]

    eval_payload = {
        "pairs": pairs,
        "records": records,
        "answers": [translated_markdown] if translated_markdown else [],
    }
    eval_report = h.eval_run_suite("translation", eval_payload)

    return h.DocResult(
        doc_id,
        ok=True,
        raw={
            "stats": stats,
            "glossary": body.get("glossary"),
            "n_char_source": len(source_markdown),
            "n_char_target": len(translated_markdown),
        },
        eval_report=eval_report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-lang", default="en", help="대상 언어 코드 (기본 en)")
    parser.add_argument("--source-lang", default="", help="원문 언어 코드 (비우면 자동 감지)")
    parser.add_argument("--register", default="", help="문어체/구어체 (비우면 기본값)")
    args = parser.parse_args()

    h.print_gateway_status()
    files = h.hwpx_files("translation")
    if not files:
        print(f"{h.DATA_DIR / 'translation'} 에 hwpx 파일이 없습니다 — 넣고 다시 실행하세요.")
        return 1

    client = h.boot_client("translation")
    results = [
        run_one(client, path, target_lang=args.target_lang, source_lang=args.source_lang, register=args.register)
        for path in files
    ]

    summary = h.summarize("translation", results)
    h.print_summary(summary)
    report_path = h.save_report(
        "translation",
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
