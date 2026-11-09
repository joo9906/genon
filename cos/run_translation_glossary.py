"""코드스페이스에서 번역 + 용어사전을 **실제 LLM · 실제 용어사전**으로 한 번에 돌려 본다.

워크플로우·MCP 를 거치지 않는다. 번역 코드서빙(`final/SFR-018-translate/request`)을 **사본 없이
그대로 import** 해 프로세스 안에서 띄우고(`/translate/markdown`), 그 서빙이 평소처럼 LLM 게이트웨이와
`데이터 > 용어사전` API 를 직접 부른다.

문서 하나를 두 번 번역한다.
- **사전 적용**: 운영과 같다 — 문서에 나온 용어가 프롬프트에 실린다.
- **사전 미적용**: 프롬프트에서 용어 절만 뺀다. 준수율은 같은 사전으로 잰다
  → 두 준수율의 차이가 "사전이 실제로 바꾼 만큼" 이다.

    python cos/run_translation_glossary.py                 # cos/dataset/*.md
    python cos/run_translation_glossary.py --docs 내문서.md 폴더/
    python cos/run_translation_glossary.py --no-baseline    # 사전 미적용 회차 생략
    python cos/run_translation_glossary.py --quiet          # 번역문은 파일로만

콘솔에는 문서마다 **번역 기능 응답 그대로**의 `<mark>` 하이라이트 번역문과 준수율을 찍는다.
결과 파일: `cos/reports/<시각>/` (summary.md · report.json · 문서별 번역문 md).
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_UNIT = ROOT / "final" / "SFR-018-translate" / "request"

REQUIRED_ENV = {
    "GENOS_URL": "LLM 게이트웨이 주소",
    "LLM_SERVING_ID": "번역에 쓸 LLM 서빙 id",
    "GENOS_TOKEN": "게이트웨이 토큰 (용어사전 토큰을 따로 안 주면 이것도 쓴다)",
    "TRANSLATE_GLOSSARY_ID": "데이터 > 용어사전 의 용어사전 id",
}
OPTIONAL_ENV = (
    "TRANSLATE_GLOSSARY_API_URL", "TRANSLATE_GLOSSARY_TOKEN",
    "TRANSLATE_GLOSSARY_KO_ATTR", "TRANSLATE_GLOSSARY_EN_ATTR", "TRANSLATE_PROMPT_IDS",
)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--docs", nargs="*", default=[str(HERE / "dataset")],
                   help="번역할 .md 파일이나 폴더 (기본: cos/dataset). 파일명이 ko_/en_ 로 시작하면 원문 언어로 쓴다")
    p.add_argument("--quiet", action="store_true", help="번역문을 콘솔에 찍지 않는다")
    p.add_argument("--unit-dir", default=str(DEFAULT_UNIT), help="번역 코드서빙 request 폴더")
    p.add_argument("--register", default="", help="문체 (빈 값이면 서빙 기본값)")
    p.add_argument("--no-baseline", action="store_true", help="사전 미적용 회차를 건너뛴다")
    p.add_argument("--out", default=str(HERE / "reports"), help="결과 폴더")
    p.add_argument("--verbose", action="store_true", help="서빙 로그를 INFO 로 본다")
    return p.parse_args()


def load_dotenv(path: Path = HERE / ".env") -> None:
    """`cos/.env` 의 `KEY=값` 을 환경변수로 올린다. 셸에 이미 있는 값은 덮지 않는다.

    파이썬은 `.env` 를 스스로 읽지 않는다 — 이 함수가 없으면 export 해야 한다.
    따옴표·`export ` 접두어·줄 끝 `\\r`(윈도우에서 만든 파일)을 걷는다. 토큰에 그대로 붙으면 401 이 난다.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def check_env() -> None:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k, "").strip()]
    print("── 환경변수")
    for k, why in REQUIRED_ENV.items():
        print(f"  {'OK ' if k not in missing else '없음'} {k:28s} {why}")
    for k in OPTIONAL_ENV:
        if os.environ.get(k, "").strip():
            print(f"  OK  {k}")
    if missing:
        sys.exit(f"\n필수 환경변수가 없다: {', '.join(missing)} — cos/README.md 의 '준비' 절을 본다.")


def collect_docs(paths: list) -> list:
    docs = []
    for raw in paths:
        p = Path(raw)
        docs.extend(sorted(p.glob("*.md")) if p.is_dir() else [p])
    if not docs:
        sys.exit("번역할 .md 문서가 없다.")
    return docs


def source_lang_of(path: Path, text: str) -> str:
    """파일명 접두어(ko_/en_)가 먼저, 없으면 한글 비율로 정한다."""
    head = path.name.split("_", 1)[0].lower()
    if head in ("ko", "en"):
        return head
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ko" if hangul >= latin else "en"


def glossary_lines(system_prompt: str) -> list:
    return [line for line in system_prompt.splitlines() if line.startswith('- "') and '" -> "' in line]


def main() -> None:
    args = parse_args()
    load_dotenv()
    check_env()
    if not args.verbose:
        os.environ.setdefault("LOG_LEVEL", "WARNING")

    unit = Path(args.unit_dir).resolve()
    if not (unit / "main.py").exists():
        sys.exit(f"번역 서빙을 못 찾았다: {unit}")
    sys.path.insert(0, str(unit))

    from fastapi.testclient import TestClient

    import main as serving
    from translation_pipeline.office import translation_modes

    # LLM 에 실제로 들어간 시스템 프롬프트를 엿본다 (용어 절 확인용). 호출 자체는 그대로 넘긴다.
    seen_prompts: list = []
    real_llm = translation_modes.llm_call_async

    async def recording_llm(sem, system, user):
        seen_prompts.append(system)
        return await real_llm(sem, system, user)

    translation_modes.llm_call_async = recording_llm
    real_terms_for_batch = translation_modes.terms_for_batch

    docs = collect_docs(args.docs)
    expect = {}
    for d in {p.parent for p in docs}:
        f = d / "expect.json"
        if f.exists():
            expect.update(json.loads(f.read_text(encoding="utf-8")))
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    with TestClient(serving.app) as client:
        gl = client.get("/glossary").json()
        prompts = client.get("/prompts").json()
        print("\n── 용어사전 적재:", json.dumps(gl, ensure_ascii=False))
        print("── 프롬프트 출처:", json.dumps(prompts, ensure_ascii=False))
        if not gl.get("loaded"):
            print("  ! 용어사전이 적재되지 않았다 — 사전 적용 회차도 사전 없이 돈다. reason 을 먼저 고친다.")

        def translate(text, src, tgt, with_glossary):
            seen_prompts.clear()
            translation_modes.terms_for_batch = (
                real_terms_for_batch if with_glossary else (lambda *a, **k: [])
            )
            started = time.monotonic()
            try:
                resp = client.post("/translate/markdown", json={
                    "markdown": text, "source_lang": src, "target_lang": tgt,
                    "register": args.register, "upload": False,
                })
            finally:
                translation_modes.terms_for_batch = real_terms_for_batch
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            lines = []
            for system in seen_prompts:
                for line in glossary_lines(system):
                    if line not in lines:
                        lines.append(line)
            g = body.get("glossary") or {}
            hit_sources = sorted({h.get("term_source", "") for h in g.get("hits") or []})
            return {
                "matched_terms": hit_sources,
                "http": resp.status_code,
                "seconds": round(time.monotonic() - started, 1),
                "llm_calls": len(seen_prompts),
                "translation_error": body.get("translation_error", body.get("error", "")),
                "fallback_rate": (body.get("stats") or {}).get("fallback_rate"),
                "numeric_warnings": len(body.get("numeric_warnings") or []),
                "compliance": g.get("compliance"),
                "applied": g.get("applied_count"),
                "matched": g.get("matched_count"),
                "term_map": g.get("term_map") or {},
                "unapplied": g.get("term_map_unapplied") or {},
                "prompt_glossary": lines,
                "_markdown": body.get("markdown", ""),
                "_highlighted": body.get("markdown_highlighted", ""),
                "_source_highlighted": body.get("source_markdown_highlighted", ""),
                "_raw": body,
            }

        report = {"glossary": gl, "prompts": prompts, "docs": []}
        for path in docs:
            text = path.read_text(encoding="utf-8")
            src = source_lang_of(path, text)
            tgt = "en" if src == "ko" else "ko"
            print(f"\n══ {path.name} ({src}→{tgt}, {len(text)}자)")
            runs = {"with": translate(text, src, tgt, True)}
            if not args.no_baseline:
                runs["without"] = translate(text, src, tgt, False)

            for name, r in runs.items():
                label = "사전 적용  " if name == "with" else "사전 미적용"
                print(f"  {label} HTTP {r['http']} · {r['seconds']}s · LLM {r['llm_calls']}회 · "
                      f"준수율 {r['compliance']} ({r['applied']}/{r['matched']}) · "
                      f"오류 {r['translation_error'] or '-'} · 폴백률 {r['fallback_rate']} · 숫자경고 {r['numeric_warnings']}")
            w = runs["with"]
            print(f"  프롬프트 용어 절 {len(w['prompt_glossary'])}줄")
            if w["unapplied"]:
                print("  사전 적용인데 안 따른 용어:", json.dumps(w["unapplied"], ensure_ascii=False))
            if "without" in runs:
                gained = sorted(set(w["term_map"]) - set(runs["without"]["term_map"]))
                if gained:
                    print("  사전 덕분에 맞춘 용어:", ", ".join(gained))
            traps = (expect.get(path.name) or {}).get("must_not_match", [])
            wrong = [t for t in traps if t.casefold() in {m.casefold() for m in w["matched_terms"]}]
            w["trap_hits"] = wrong
            if traps:
                print(f"  동형어 함정 {len(traps)}개: " + ("OK — 안 걸림" if not wrong else f"FAIL — 걸림 {wrong}"))
            if not args.quiet:
                print(f"\n  ── 번역문 (<mark> = 사전 용어를 실제로 쓴 자리) · 준수율 {w['compliance']}\n")
                print("\n".join("    " + line for line in w["_highlighted"].splitlines()))

            stem = path.stem
            (out_dir / f"{stem}.with.md").write_text(w["_markdown"], encoding="utf-8")
            (out_dir / f"{stem}.with.highlighted.md").write_text(w["_highlighted"], encoding="utf-8")
            (out_dir / f"{stem}.source.highlighted.md").write_text(w["_source_highlighted"], encoding="utf-8")
            if "without" in runs:
                (out_dir / f"{stem}.without.md").write_text(runs["without"]["_markdown"], encoding="utf-8")
            report["docs"].append({
                "file": str(path), "source_lang": src, "target_lang": tgt,
                "runs": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in runs.items()},
                "raw_with": w["_raw"],
            })

    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary(out_dir / "summary.md", report)

    def total(run_name):
        runs = [d["runs"][run_name] for d in report["docs"] if run_name in d["runs"]]
        applied = sum(r["applied"] or 0 for r in runs)
        matched = sum(r["matched"] or 0 for r in runs)
        return f"{applied / matched:.3f} ({applied}/{matched})" if matched else "-"

    print("\n══ 전체 준수율 — 사전 적용:", total("with"), "· 사전 미적용:", total("without"))
    print(f"\n결과: {out_dir}")


def write_summary(path: Path, report: dict) -> None:
    rows = ["| 문서 | 방향 | 준수율(사전 적용) | 준수율(미적용) | 오류 | 숫자경고 | 프롬프트 용어 | 동형어 함정 |",
            "|---|---|---|---|---|---|---|---|"]
    detail = []
    for d in report["docs"]:
        w, wo = d["runs"]["with"], d["runs"].get("without", {})
        rows.append(f"| {Path(d['file']).name} | {d['source_lang']}→{d['target_lang']} | "
                    f"{w['compliance']} ({w['applied']}/{w['matched']}) | "
                    f"{wo.get('compliance', '-')} | {w['translation_error'] or '-'} | {w['numeric_warnings']} | "
                    f"{len(w['prompt_glossary'])}줄 | {'걸림 ' + str(w['trap_hits']) if w.get('trap_hits') else 'OK'} |")
        detail.append(f"\n## {Path(d['file']).name}\n")
        detail.append("**프롬프트에 실린 용어**\n\n" + ("\n".join(w["prompt_glossary"]) or "(없음)") + "\n")
        detail.append("**안 따른 용어(사전 적용 회차)**: "
                      + (json.dumps(w["unapplied"], ensure_ascii=False) if w["unapplied"] else "없음") + "\n")
    text = (f"# 번역 + 용어사전 실행 결과\n\n용어사전: `{json.dumps(report['glossary'], ensure_ascii=False)}`\n\n"
            + "\n".join(rows) + "\n" + "\n".join(detail))
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
