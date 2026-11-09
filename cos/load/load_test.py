"""젠포탈 `/api/genportal/chat` 부하 테스트 — 동시 사용자 N 명이 한꺼번에 요청한다.

    python cos/load/load_test.py                                  # 번역+글다듬이 섞어서 26명 동시 (기본)
    python cos/load/load_test.py --scenario translate             # 번역만
    python cos/load/load_test.py --scenario polish --rounds 3     # 글다듬이만, 사용자당 3회
    python cos/load/load_test.py --dry-run                        # 보내지 않고 본문만 본다
    python cos/load/load_test.py --url http://다른주소/api/genportal/chat --header "Authorization: Bearer ..."

- 사용자마다 `--rounds` 번 요청한다. 첫 요청은 **모두 같은 순간에** 출발한다(동시 접속 재현).
- 시나리오는 `cos/load/scenarios.json` — **payload 템플릿을 그대로 고친다**(자리표시자만 채워진다).
  입력은 `cos/load/messages/*.txt`(`---` 줄로 구분) · `cos/dataset/*.md` · `--message`.
  `mix` 는 쓸 수 있는 시나리오를 사용자마다 돌아가며 고른다.
- 응답은 끝까지 읽는다(스트리밍이어도). 첫 바이트(TTFB) · **첫 토큰(TTFT)** · 전체 시간을 따로 잰다.
- **합격 기준: 모든 요청의 첫 토큰이 `--ttft-limit`(기본 10초) 안에 나오고 성공할 것.** 마지막 줄에 PASS/FAIL.
- 첫 토큰 = 내용이 있는 첫 조각(빈 줄 · SSE 주석 `:` · keep-alive 제외). 젠포탈이 메타데이터를 먼저 보내면
  `--token-pattern` 정규식으로 "토큰" 을 좁힌다(예: `"event"\\s*:\\s*"token"` 또는 `^event: token`).
  무엇을 첫 토큰으로 셌는지 `requests.jsonl` 의 `first_token_preview` 에 남는다 — 첫 실행 뒤 한 번 확인한다.
- 성공 판정: HTTP 2xx **이고** 본문에 `"error": {…}`/`"error": "…"` 가 없을 것. 정상 응답에는 `error` 키가 없다(FRONT.md §1.2).

결과: 콘솔 요약 + `cos/reports/load_<시각>/` (requests.jsonl · summary.md).
의존: httpx (번역 서빙 requirements 에 있다).
"""

import argparse
import asyncio
import json
import random
import re
import statistics
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
COS = HERE.parent
ERROR_RE = re.compile(r'"error"\s*:\s*(\{|"[^"]+")')


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", default="http://10.168.31.100:30908/api/genportal/chat")
    p.add_argument("--users", type=int, default=26, help="동시 사용자 수")
    p.add_argument("--rounds", type=int, default=1, help="사용자당 요청 횟수 (앞 요청이 끝나면 다음)")
    p.add_argument("--scenario", default="mix", help="translate | polish | mix(번역+글다듬이 섞어서)")
    p.add_argument("--scenarios", default=str(HERE / "scenarios.json"))
    p.add_argument("--file-id", action="append", default=[], help="첨부 파일 id (FAQ 등). 여러 번 줄 수 있다")
    p.add_argument("--template-id", default="", help="006 템플릿 id")
    p.add_argument("--message", action="append", default=[],
                   help="입력을 명령행으로 준다(여러 번 가능). 주면 시나리오의 입력 파일 대신 이것만 쓴다")
    p.add_argument("--header", action="append", default=[], help='추가 헤더 "이름: 값" (인증 등)')
    p.add_argument("--timeout", type=float, default=600.0, help="요청 하나의 최대 시간(초)")
    p.add_argument("--ttft-limit", type=float, default=10.0, help="첫 토큰 합격 한도(초)")
    p.add_argument("--token-pattern", default="", help="이 정규식에 맞는 조각이 와야 첫 토큰으로 친다 (기본: 내용 있는 첫 조각)")
    p.add_argument("--ramp", type=float, default=0.0, help="사용자 출발을 이 초 동안 고르게 펼친다 (0 = 동시)")
    p.add_argument("--same-session", action="store_true", help="사용자마다 세션 하나를 계속 쓴다 (기본: 요청마다 새 세션)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--dry-run", action="store_true", help="보내지 않고 사용자별 첫 본문만 찍는다")
    p.add_argument("--out", default=str(COS / "reports"))
    return p.parse_args()


def lang_of(text: str) -> str:
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ko" if hangul >= latin else "en"


def read_messages_file(path: Path) -> list:
    """`---` 만 있는 줄로 입력을 나눈다. 빈 입력은 버린다."""
    blocks = re.split(r"^\s*---\s*$", path.read_text(encoding="utf-8"), flags=re.M)
    return [{"text": b.strip(), "name": f"{path.name}#{i + 1}"} for i, b in enumerate(blocks) if b.strip()]


def scenario_messages(name: str, sc: dict, args) -> list:
    if args.message:  # 명령행 입력이 있으면 그것만 쓴다
        return [{"text": m, "name": f"cli#{i + 1}"} for i, m in enumerate(args.message)]
    out = []
    for f in sc.get("messages_files", []):
        p = Path(f) if Path(f).is_absolute() else HERE / f
        if p.exists():
            out += read_messages_file(p)
        else:
            print(f"  - 시나리오 {name}: 입력 파일 없음 {p}")
    out += [{"text": m, "name": f"{name}#{i + 1}"} for i, m in enumerate(sc.get("messages", []))]
    if sc.get("messages_from_dataset"):
        out += [{"text": f.read_text(encoding="utf-8"), "name": f.name}
                for f in sorted((COS / "dataset").glob("*.md"))]
    for m in out:
        m["source"] = lang_of(m["text"])
    return out


def build_scenarios(args) -> dict:
    raw = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    values = {"file_ids": [str(x) for x in args.file_id if str(x).strip()], "template_id": args.template_id}
    ready = {}
    for name, sc in raw.items():
        if name.startswith("_"):
            continue
        missing = [k for k in sc.get("requires", []) if not values.get(k)]
        if missing:
            hint = {"file_ids": "--file-id", "template_id": "--template-id"}
            print(f"  - 시나리오 {name}: 건너뜀 — {', '.join(f'{k} 없음({hint.get(k, k)} 로 준다)' for k in missing)}")
            continue
        sc = dict(sc, _messages=scenario_messages(name, sc, args), _values=values)
        if not sc["_messages"]:
            print(f"  - 시나리오 {name}: 건너뜀 — 보낼 입력이 없다")
            continue
        print(f"  - 시나리오 {name}: 입력 {len(sc['_messages'])}개")
        ready[name] = sc
    return ready


def fill(node, slots: dict):
    """payload 템플릿의 자리표시자를 채운다. 값 전체가 자리표시자면 타입째(리스트 등) 바꾼다."""
    if isinstance(node, dict):
        return {k: fill(v, slots) for k, v in node.items()}
    if isinstance(node, list):
        return [fill(v, slots) for v in node]
    if isinstance(node, str):
        whole = re.fullmatch(r"\{(\w+)\}", node)
        if whole and whole.group(1) in slots:
            return slots[whole.group(1)]
        return re.sub(r"\{(\w+)\}", lambda m: str(slots.get(m.group(1), m.group(0))), node)
    return node


def make_payload(sc: dict, msg: dict, session_id: str) -> dict:
    src = msg["source"]
    slots = dict(sc["_values"], message=msg["text"], session_id=session_id,
                 source_lang=src, target_lang="en" if src == "ko" else "ko")
    return fill(sc["payload"], slots)


def has_content(text: str) -> bool:
    """빈 줄 · SSE 주석(`:`) · keep-alive 만 있는 조각은 토큰이 아니다."""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(":") or s in ("data:", "data: ", "ping", "event: ping"):
            continue
        return True
    return False


async def one_request(client, url, headers, payload, timeout, token_re) -> dict:
    started = time.perf_counter()
    rec = {"status": None, "ttfb_s": None, "ttft_s": None, "total_s": None, "bytes": 0,
           "ok": False, "error": "", "first_token_preview": ""}
    try:
        async with client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as resp:
            rec["status"] = resp.status_code
            chunks = []
            seen = ""
            async for chunk in resp.aiter_bytes():
                now = round(time.perf_counter() - started, 3)
                if rec["ttfb_s"] is None:
                    rec["ttfb_s"] = now
                chunks.append(chunk)
                if rec["ttft_s"] is None:
                    piece = chunk.decode("utf-8", errors="replace")
                    seen += piece
                    hit = token_re.search(seen) if token_re else (has_content(piece) or None)
                    if hit:
                        rec["ttft_s"] = now
                        rec["first_token_preview"] = seen[-300:]
            body = b"".join(chunks).decode("utf-8", errors="replace")
        rec["bytes"] = len(body.encode("utf-8"))
        rec["tail"] = body[-400:]
        m = ERROR_RE.search(body)
        if not (200 <= resp.status_code < 300):
            rec["error"] = f"HTTP {resp.status_code}"
        elif m:
            rec["error"] = "body_error"
            rec["error_snippet"] = body[max(0, m.start() - 20): m.start() + 200]
        elif not body.strip():
            rec["error"] = "empty_body"
        else:
            rec["ok"] = True
    except httpx.TimeoutException:
        rec["error"] = "timeout"
    except httpx.HTTPError as exc:
        rec["error"] = type(exc).__name__
    rec["total_s"] = round(time.perf_counter() - started, 3)
    return rec


def pct(values, q):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 2)


async def main_async(args):
    headers = {"Content-Type": "application/json"}
    for h in args.header:
        name, _, value = h.partition(":")
        headers[name.strip()] = value.strip()

    print("── 시나리오")
    scenarios = build_scenarios(args)
    if not scenarios:
        raise SystemExit("쓸 수 있는 시나리오가 없다.")
    if args.scenario == "mix":
        names = list(scenarios)
    elif args.scenario in scenarios:
        names = [args.scenario]
    else:
        raise SystemExit(f"시나리오 '{args.scenario}' 를 쓸 수 없다. 가능: {list(scenarios)} 또는 mix")
    print(f"  사용: {names} · 사용자 {args.users} · 사용자당 {args.rounds}회 · URL {args.url}")

    rng = random.Random(args.seed)
    plan = []  # 사용자별 [(scenario, msg, session_id)]
    cursor = Counter()  # 시나리오별로 입력을 차례로 돌린다 — 26명이 같은 입력만 보내지 않게
    for u in range(args.users):
        name = names[u % len(names)]
        sc = scenarios[name]
        user_session = f"load-{uuid.uuid4().hex[:12]}"
        reqs = []
        for _ in range(args.rounds):
            msg = sc["_messages"][cursor[name] % len(sc["_messages"])]
            cursor[name] += 1
            sid = user_session if args.same_session else f"load-{uuid.uuid4().hex[:12]}"
            reqs.append((name, msg, sid))
        plan.append(reqs)
    rng.shuffle(plan)

    if args.dry_run:
        for u, reqs in enumerate(plan[: min(4, len(plan))]):
            name, msg, sid = reqs[0]
            p = make_payload(scenarios[name], msg, sid)
            p["message"] = p["message"][:120] + ("…" if len(p["message"]) > 120 else "")
            print(f"\n사용자 {u + 1} ({name}, {msg['name']}):\n" + json.dumps(p, ensure_ascii=False, indent=2))
        print(f"\n(사용자 {len(plan)} 명 중 앞 {min(4, len(plan))} 명만 표시)")
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / f"load_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    token_re = re.compile(args.token_pattern, re.M) if args.token_pattern else None
    gate = asyncio.Event()
    limits = httpx.Limits(max_connections=args.users + 4, max_keepalive_connections=args.users + 4)

    async with httpx.AsyncClient(limits=limits, timeout=args.timeout) as client:
        async def user(idx, reqs):
            await gate.wait()
            if args.ramp:
                await asyncio.sleep(args.ramp * idx / max(1, args.users))
            for r, (name, msg, sid) in enumerate(reqs):
                payload = make_payload(scenarios[name], msg, sid)
                rec = await one_request(client, args.url, headers, payload, args.timeout, token_re)
                rec["ttft_ok"] = rec["ttft_s"] is not None and rec["ttft_s"] <= args.ttft_limit
                rec.update(user=idx + 1, round=r + 1, scenario=name, doc=msg["name"],
                           session_id=sid, message_chars=len(msg["text"]),
                           started_at=round(time.perf_counter() - t0 - rec["total_s"], 3))
                records.append(rec)
                mark = "OK " if rec["ok"] else "ERR"
                slow = "" if rec["ttft_ok"] else f"  ← 첫 토큰 {args.ttft_limit:g}s 초과"
                print(f"  [{mark}] 사용자 {idx + 1:>2} #{r + 1} {name:9s} 첫 토큰 {rec['ttft_s']}s · "
                      f"전체 {rec['total_s']}s · HTTP {rec['status']} {rec['error']}{slow}")

        tasks = [asyncio.create_task(user(i, reqs)) for i, reqs in enumerate(plan)]
        print(f"\n── 출발 ({len(tasks)} 명 동시)")
        t0 = time.perf_counter()
        gate.set()
        await asyncio.gather(*tasks)
        wall = time.perf_counter() - t0

    with (out_dir / "requests.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = summarize(records, wall, args)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print(f"결과: {out_dir}")


def summarize(records, wall, args) -> str:
    lines = [f"# 부하 테스트 결과\n",
             f"- URL: `{args.url}`",
             f"- 동시 사용자 {args.users} · 사용자당 {args.rounds}회 · 시나리오 `{args.scenario}` · ramp {args.ramp}s",
             f"- 전체 경과 {wall:.1f}s · 요청 {len(records)}건 · 처리량 {len(records) / wall:.2f} 건/s\n",
             f"| 시나리오 | 요청 | 성공 | 첫 토큰 ≤{args.ttft_limit:g}s | 첫 토큰 p50 | p95 | 최대 | 전체 p50 | p95 | 최대 | 판정 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    groups = defaultdict(list)
    for r in records:
        groups[r["scenario"]].append(r)
    groups["전체"] = list(records)
    for name, rs in groups.items():
        ok = [r for r in rs if r["ok"]]
        t = [r["total_s"] for r in ok]
        ft = [r["ttft_s"] for r in rs if r["ttft_s"] is not None]
        within = sum(1 for r in rs if r["ttft_ok"])
        passed = all(r["ok"] and r["ttft_ok"] for r in rs)
        lines.append(f"| {name} | {len(rs)} | {len(ok)} | {within}/{len(rs)} | "
                     f"{pct(ft, .5)} | {pct(ft, .95)} | {max(ft) if ft else None} | "
                     f"{pct(t, .5)} | {pct(t, .95)} | {max(t) if t else None} | {'PASS' if passed else 'FAIL'} |")
    errs = Counter(r["error"] for r in records if not r["ok"])
    slow = [r for r in records if not r["ttft_ok"]]
    lines.append(f"\n시간 단위: 초. 첫 토큰은 모든 요청, 전체 시간은 **성공한 요청만**으로 잰다. "
                 f"판정 PASS = 모든 요청이 성공하고 첫 토큰이 {args.ttft_limit:g}s 안.\n")
    lines.append(f"**첫 토큰 {args.ttft_limit:g}s 초과 · 토큰 없음**: {len(slow)}건"
                 + (" — " + ", ".join(f"사용자 {r['user']} {r['scenario']} {r['ttft_s']}s" for r in slow[:10]) if slow else ""))
    lines.append("**실패 사유**: " + (", ".join(f"{k} {v}건" for k, v in errs.most_common()) if errs else "없음"))
    sample = next((r for r in records if not r["ok"]), None)
    if sample:
        lines.append(f"\n실패 예시 (사용자 {sample['user']}, {sample['scenario']}):\n\n```\n"
                     f"{sample.get('error_snippet') or sample.get('tail', '')}\n```")
    first = next((r for r in records if r["first_token_preview"]), None)
    if first:
        lines.append(f"\n첫 토큰으로 센 조각 예시 (확인용 — 메타데이터라면 `--token-pattern` 으로 좁힌다):\n\n```\n"
                     f"{first['first_token_preview']}\n```")
    if records:
        lines.append(f"\n평균 응답 크기 {statistics.mean(r['bytes'] for r in records):.0f} bytes")
    verdict = bool(records) and all(r["ok"] and r["ttft_ok"] for r in records)
    lines.append(f"\n## 최종 판정: {'PASS' if verdict else 'FAIL'} "
                 f"(모든 기능 첫 토큰 {args.ttft_limit:g}s 이내 + 전부 성공)")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
