"""
Mock variant of test_complex_weather_flow.

The live test exercises the agent's ability to chain search в†’ write-file
в†’ write-file в†’ shell. Under the mock we cannot meaningfully exercise
search (the mock controls only the LLM dispatch; the search skill still
hits the network). Instead the mocked response provides the forecast
text directly, so the chain reduces to a deterministic
write-file в†’ write-file в†’ shell pipeline. The chain still validates
that the agent can sequence multiple skills and that the resulting
artefacts are consistent.

Run:
    pytest test_complex_weather_flow_mock.py -s
"""
import re
import time


from helpers import (
    Checker, dexec, dexec_root, find_skill_calls, make_prompt,
    wait_for_file,
)
from slack_helpers import sl_send_prompt

TARGET_DIR = "/tmp/wflow"
WEATHER_TXT = f"{TARGET_DIR}/w.txt"
SCRIPT_SH = f"{TARGET_DIR}/p.sh"
TEMP_ONLY = f"{TARGET_DIR}/t.txt"

# Synthetic forecast вЂ” deterministic, contains a single Celsius number
# so the extraction script has exactly one match.
FORECAST_TEXT = "New York tomorrow: clear, high 22 degrees Celsius."


def test_complex_weather_flow_slack_mock(llm, sl):
    with Checker("complex weather flow (slack mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: complex flow slack mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create target dir 0777")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("chmod", "777", TARGET_DIR)
        c.ok("pre-create dir", TARGET_DIR)

        start_ts = int(time.time()) - 1

        c.step("send prompt via Slack with mocked chain response")
        prompt = make_prompt(
            c.run_id,
            f"Save tomorrow's NY weather forecast to {WEATHER_TXT}. Then "
            f"build script {SCRIPT_SH} that extracts the first Celsius "
            f"number from {WEATHER_TXT} into {TEMP_ONLY}. Make {SCRIPT_SH} "
            f"executable, then run it.",
        )
        # Single LLM response containing the full pipeline.
        llm.set_answer(
            prompt,
            [
                ("write-file", { "filename": f"{WEATHER_TXT}", "content": f"{FORECAST_TEXT}" }),
                ("write-file", { "filename": f"{SCRIPT_SH}", "content": f"#!/bin/bash\\ngrep -oE '[0-9]+' {WEATHER_TXT} | head -1 > {TEMP_ONLY}\\n" }),
                ("shell", { "cmd": f"chmod +x {SCRIPT_SH}" }),
                ("shell", { "cmd": f"sh {SCRIPT_SH}" }),
            ],
        )
        sl_send_prompt(sl, prompt)
        c.ok("slack", f"run-id={c.run_id}")

        c.step(f"wait for {WEATHER_TXT}")
        mtime_w = wait_for_file(WEATHER_TXT, start_ts, timeout=30)
        if mtime_w is None:
            c.fail("w.txt", f"{WEATHER_TXT} not created within timeout")
        c.ok("w.txt", f"after {mtime_w - start_ts}s")

        c.step("verify (write-file ...) targeted w.txt")
        wf = find_skill_calls(c.run_id, "write-file") or []
        if not any(WEATHER_TXT in a for a in wf):
            c.fail("write-file w.txt", f"no write-file referencing {WEATHER_TXT}: {wf[:3]}")
        c.ok("write-file w.txt", f"{len(wf)} write-file calls")

        c.step(f"wait for {SCRIPT_SH}")
        mtime_s = wait_for_file(SCRIPT_SH, start_ts, timeout=30)
        if mtime_s is None:
            c.fail("script", f"{SCRIPT_SH} not created within timeout")
        c.ok("script", f"after {mtime_s - start_ts}s")

        c.step("check script is executable")
        # Wait briefly for the chmod to land.
        deadline = time.time() + 10
        perms = ""
        while time.time() < deadline:
            perms = dexec("stat", "-c", "%A", SCRIPT_SH).stdout.strip()
            if "x" in perms:
                break
            time.sleep(0.5)
        if "x" not in perms:
            c.fail("script perms", f"not executable: {perms}")
        c.ok("script perms", perms)

        c.step(f"wait for {TEMP_ONLY}")
        mtime_t = wait_for_file(TEMP_ONLY, start_ts, timeout=30)
        if mtime_t is None:
            c.fail("t.txt", f"{TEMP_ONLY} not created within timeout")
        c.ok("t.txt", f"after {mtime_t - start_ts}s")

        c.step("verify (shell ...) was invoked to run p.sh")
        sh = find_skill_calls(c.run_id, "shell") or []
        if not any("p.sh" in a for a in sh):
            c.fail("shell invoked", f"no shell call referencing p.sh: {sh[:3]}")
        c.ok("shell invoked", f"{len(sh)} shell calls")

        c.step("verify t.txt contains a numeric temperature")
        content = dexec("cat", TEMP_ONLY).stdout.strip()
        if not content:
            c.fail("t.txt content", "file is empty")
        m = re.search(r"-?\d+(?:\.\d+)?", content)
        if not m:
            c.fail("t.txt numeric", f"no number in {content!r}")
        num = float(m.group(0))
        if not (-60 <= num <= 120):
            c.fail("t.txt range", f"value {num} out of plausible range")
        if len(content) > 40:
            c.fail("t.txt tidy", f"content too long ({len(content)} chars)")
        c.ok("t.txt content", f"{content!r} (parsed {num})")

        c.done()
