"""점검 17개 + unittest 2벌을 돌리고 요약만 출력한다.

    python Test/run_all.py                    # 전부
    python Test/run_all.py mcp_tools SFR-018  # 이름 일부로 골라서
    python Test/run_all.py --006=no_pythonstep  # 006 을 no_pythonstep 판으로

018 세 단위는 `no_pythonstep/` 을 본다. 006 은 기본이 `final/` 이고, `--006=no_pythonstep`
(또는 `GENON_SFR006_SOURCE=no_pythonstep`)이면 그쪽 코드와 `/chat` 점검·unittest 를 함께 본다
(`Test/check/paths.py`).

건수가 EXPECTED 와 다르면 FAIL 로 친다 — 판정이 조용히 사라지면(실물 파일 경로가
어긋나 건수만 줄어드는 경우) 종료 코드로는 드러나지 않기 때문이다.
점검을 늘리거나 줄이면 EXPECTED 를 같이 고친다.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 006 출처에 따라 갈리는 기준 건수. 나머지 점검은 출처와 무관하게 같다.
EXPECTED_BY_006 = {
    "final": {"check_chat_direct": 79},
    "no_pythonstep": {"check_chat_direct": 92, "SFR-006-chat": 11},
}

EXPECTED = {
    "check_deploy_contract": 82,
    "check_service_boot": 16,
    "check_workflow_run": 124,
    "check_mcp_tools": 99,
    "check_smart_preprocessor": 35,
    "check_final_preprocessor": 153,
    "check_high_preprocessor": 90,
    "check_api_contract": 57,
    "check_unit_endpoints": 123,
    "check_chat_turn": 60,
    "check_body_blocks": 17,
    "check_output_safety": 5,
    "check_table_grid": 31,
    "check_tone_policy": 20,
    "check_prompt_render": 86,
    "check_eval_metrics": 91,
    "SFR-006": 117,
    "SFR-018": 404,
}


def _command(name):
    if name.startswith("check_"):
        return [sys.executable, os.path.join("Test", "check", name + ".py")], ROOT
    if name == "SFR-006-chat":
        cwd = os.path.join(ROOT, "Test", "SFR-006")
        return [sys.executable, "-m", "unittest", "discover", "-s", "tests_chat", "-t", "."], cwd
    cwd = os.path.join(ROOT, "Test", name)
    return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd


def _count(name, out):
    if name.startswith("check_"):
        lines = [l for l in out.splitlines() if re.search(r"\bOK \d+", l)]
        if not lines:
            return None, None
        last = lines[-1]
        ok = int(re.search(r"\bOK (\d+)", last).group(1))
        fail = re.search(r"FAIL (\d+)", last)
        return ok, int(fail.group(1)) if fail else 0
    ran = re.search(r"Ran (\d+) test", out)
    bad = re.search(r"FAILED \((.*)\)", out)
    fail = sum(int(n) for n in re.findall(r"=(\d+)", bad.group(1))) if bad else 0
    return (int(ran.group(1)) - fail if ran else None), fail


def main(args):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    source = os.environ.get("GENON_SFR006_SOURCE", "final").strip() or "final"
    filters = []
    for arg in args:
        if arg.startswith("--006="):
            source = arg.split("=", 1)[1]
        else:
            filters.append(arg)
    if source not in EXPECTED_BY_006:
        print(f"006 출처는 {sorted(EXPECTED_BY_006)} 중 하나다: {source!r}")
        return 2
    expected = dict(EXPECTED, **EXPECTED_BY_006[source])
    env = dict(os.environ, PYTHONIOENCODING="utf-8", SSL_CERT_FILE="", GENON_SFR006_SOURCE=source)
    print(f"006 출처: {source}  (018 은 no_pythonstep)\n")
    names = [n for n in expected if not filters or any(f in n for f in filters)]
    bad = 0
    for name in names:
        cmd, cwd = _command(name)
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        out = proc.stdout + proc.stderr
        ok, fail = _count(name, out)
        good = proc.returncode == 0 and fail == 0 and ok == expected[name]
        print(f"{'OK  ' if good else 'FAIL'} {name:28} {ok}/{expected[name]}"
              + ("" if good else f"  (exit {proc.returncode}, fail {fail})"))
        if not good:
            bad += 1
            tail = [l for l in out.splitlines() if "FAIL" in l or "Error" in l][:15]
            for line in tail or out.splitlines()[-15:]:
                print("     " + line)
    print(f"\n{len(names) - bad}/{len(names)} 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
