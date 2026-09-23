"""006(SFR-006_template_fill) 실측 검증.

    python run_template_fill.py --template <실제 hwpx 템플릿 경로>
        [--admin-token ...] [--values-json Test/data/template_fill/values.json]

두 갈래를 돈다 — **하나는 LLM 이 필요 없고, 하나는 필요하다.**

1. **라운드트립(구조 무결성)** — `--values-json` 을 주면 그 값으로 `/generate/upload`
   를 한 번 불러 채우기 전/후 hwpx 를 저장하고 `hwpx_fill_roundtrip`·
   `hwpx_document_integrity`·`hwpx_text_crosscheck` 를 돌린다. **결정적**이라 LLM
   이 필요 없다 — 이 값 자체는 `field_extraction_score` 처럼 LLM 이 뽑은 게 아니라
   테스터가 직접 준 값이고, 검증 대상은 "그 값을 hwpx 에 정확히 박아 넣었는가" 다.
2. **문서 자동 채움(멀티턴 시나리오)** — `Test/data/template_fill/sources/*.hwpx`
   각각에 대해 `/chat/context → /chat/prefill → /chat/commit → /chat/context` 를
   돌려 **세션이 값을 잃거나 덮어쓰지 않는지**(`multiturn_scenario_score`)를 본다.
   **LLM 이 실제로 문서에서 값을 뽑는 유일한 구간**이라 여기서만 게이트웨이가 쓰인다.
   정답(gold)이 있으면(`Test/data/template_fill/expected.json`) `field_extraction_score`
   (정밀도·재현율·환각률)도 함께 낸다 — 없으면 그 지표만 건너뛴다.

**템플릿은 외부에서 구할 수 없다.** `{{필드명}}` 슬롯 문법은 이 프로젝트 내부
규약이라, 실제 사내 템플릿을 `--template` 으로 직접 지정해야 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import _harness as h


def _headers(admin_token: str) -> dict:
    return {"X-Admin-Token": admin_token} if admin_token else {}


def register_template(client, template_path: Path, template_id: str, admin_token: str) -> dict:
    with template_path.open("rb") as fh:
        response = client.post(
            "/templates",
            files={"template": (template_path.name, fh, "application/octet-stream")},
            data={"template_id": template_id, "overwrite": "true"},
            headers=_headers(admin_token),
            timeout=h.REQUEST_TIMEOUT,
        )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"템플릿 등록 실패: HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def run_roundtrip(client, template_path: Path, values: dict) -> h.DocResult:
    """LLM 없이 도는 구조 검증 — 준 값이 hwpx 에 정확히 반영됐는가."""
    before_bytes = template_path.read_bytes()
    try:
        with template_path.open("rb") as fh:
            response = client.post(
                "/generate/upload",
                files={"template": (template_path.name, fh, "application/octet-stream")},
                data={"values": json.dumps(values, ensure_ascii=False), "filename": "onprem_roundtrip"},
                timeout=h.REQUEST_TIMEOUT,
            )
    except Exception as exc:  # noqa: BLE001
        return h.DocResult("__roundtrip__", ok=False, error=f"요청 실패: {type(exc).__name__}: {exc}")

    if response.status_code != 200:
        return h.DocResult("__roundtrip__", ok=False, error=f"HTTP {response.status_code}: {response.text[:300]}")

    after_bytes = response.content
    stamp = time.strftime("%Y%m%d_%H%M%S")
    before_path = h.REPORTS_DIR / f"roundtrip_before_{stamp}.hwpx"
    after_path = h.REPORTS_DIR / f"roundtrip_after_{stamp}.hwpx"
    before_path.write_bytes(before_bytes)
    after_path.write_bytes(after_bytes)

    eval_report = h.eval_run_suite(
        "template_fill",
        {
            "hwpx_before": str(before_path),
            "hwpx_after": str(after_path),
            "written_values": values,
        },
    )
    return h.DocResult(
        "__roundtrip__",
        ok=True,
        raw={"before_path": str(before_path), "after_path": str(after_path), "values": values},
        eval_report=eval_report,
    )


def run_prefill_scenario(client, template_id: str, source_path: Path, gold: dict | None) -> h.DocResult:
    doc_id = source_path.name
    try:
        markdown = h.hwpx_to_markdown(source_path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return h.DocResult(doc_id, ok=False, error=f"hwpx→markdown 실패: {type(exc).__name__}: {exc}")

    session_id = f"onprem-{template_id}-{source_path.stem}-{int(time.time())}"

    def _context() -> dict:
        r = client.post("/chat/context", json={"session_id": session_id, "template_id": template_id}, timeout=h.REQUEST_TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"/chat/context 실패: HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    try:
        context0 = _context()
        allowed_names = list(context0.get("field_names") or [])

        prefill_resp = client.post(
            "/chat/prefill",
            json={"session_id": session_id, "template_id": template_id, "document": markdown},
            timeout=h.REQUEST_TIMEOUT,
        )
        if prefill_resp.status_code != 200:
            raise RuntimeError(f"/chat/prefill 실패: HTTP {prefill_resp.status_code}: {prefill_resp.text[:300]}")
        prefill = prefill_resp.json()

        commit_resp = client.post(
            "/chat/commit",
            json={
                "session_id": session_id,
                "template_id": template_id,
                "fields_prefilled": prefill.get("fields_prefilled") or {},
                "source_doc_hash": prefill.get("source_doc_hash") or "",
                "prefill_failed": bool(prefill.get("prefill_failed")),
            },
            timeout=h.REQUEST_TIMEOUT,
        )
        if commit_resp.status_code != 200:
            raise RuntimeError(f"/chat/commit 실패: HTTP {commit_resp.status_code}: {commit_resp.text[:300]}")

        context1 = _context()
        # 두 번째 관찰 — 새로 추출한 것 없이 다시 조회해, 세션이 값을 그대로
        # 들고 있는지(유실·덮어쓰기 없음)를 본다.
        context2 = _context()
    except Exception as exc:  # noqa: BLE001
        return h.DocResult(doc_id, ok=False, error=str(exc))

    extracted = dict(prefill.get("fields_prefilled") or {})
    scenario = {
        "id": doc_id,
        "required_fields": allowed_names,
        "turns": [
            {"extracted": extracted, "session_after": context1.get("field_values") or {}},
            {"extracted": {}, "session_after": context2.get("field_values") or {}},
        ],
    }

    eval_payload = {"scenarios": [scenario]}
    if gold:
        eval_payload["extraction_samples"] = [
            {"predicted": extracted, "gold": gold, "allowed_names": allowed_names}
        ]
    eval_report = h.eval_run_suite("template_fill", eval_payload)

    return h.DocResult(
        doc_id,
        ok=True,
        raw={
            "prefill_failed": prefill.get("prefill_failed"),
            "skipped_reason": prefill.get("skipped_reason"),
            "chunks_called": prefill.get("chunks_called"),
            "chunk_count": prefill.get("chunk_count"),
            "fields_prefilled": extracted,
        },
        eval_report=eval_report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, help="{{필드}} 슬롯이 있는 실제 hwpx 템플릿 경로")
    parser.add_argument("--template-id", default="", help="생략하면 파일명을 쓴다")
    parser.add_argument("--admin-token", default="", help="TEMPLATE_FILL_ADMIN_TOKEN 이 설정돼 있으면 지정")
    parser.add_argument(
        "--values-json", default="",
        help="라운드트립 검증에 쓸 {필드명: 값} JSON 파일. 생략하면 그 검증만 건너뛴다.",
    )
    args = parser.parse_args()

    template_path = Path(args.template).resolve()
    if not template_path.is_file():
        print(f"템플릿 파일을 찾지 못했습니다: {template_path}")
        return 1
    template_id = args.template_id or template_path.stem

    h.print_gateway_status()
    print(f"[Redis] REDIS_URL 이 통해야 세션(대화 자동 채움) 검증이 의미가 있습니다 — {__doc__.splitlines()[0]}")

    client = h.boot_client("template_fill")

    print(f"템플릿 등록: {template_path.name} → template_id={template_id}")
    register_template(client, template_path, template_id, args.admin_token)

    results: list[h.DocResult] = []

    if args.values_json:
        values = json.loads(Path(args.values_json).read_text(encoding="utf-8"))
        results.append(run_roundtrip(client, template_path, values))
    else:
        print("--values-json 이 없어 라운드트립(구조) 검증을 건너뜁니다.")

    expected_path = h.DATA_DIR / "template_fill" / "expected.json"
    expected_all = json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.is_file() else {}

    source_files = h.hwpx_files("template_fill/sources")
    if not source_files:
        print(f"{h.DATA_DIR / 'template_fill' / 'sources'} 에 hwpx 파일이 없습니다 — "
              "자동 채움(LLM) 검증을 건너뜁니다.")
    for path in source_files:
        gold = expected_all.get(path.name)
        results.append(run_prefill_scenario(client, template_id, path, gold))

    summary = h.summarize("template_fill", results)
    h.print_summary(summary)
    report_path = h.save_report(
        "template_fill",
        {
            "summary": summary,
            "args": {**vars(args), "template_id": template_id},
            "per_document": [
                {"id": r.doc_id, "raw": r.raw, "eval": r.eval_report, "error": r.error}
                for r in results
            ],
        },
    )
    print(f"\n전체 리포트: {report_path}")
    return 0 if results and summary["documents_passed"] == summary["documents_total"] else 1


if __name__ == "__main__":
    sys.exit(main())
