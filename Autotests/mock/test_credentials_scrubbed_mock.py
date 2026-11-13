"""
Test (OMEGA-38): provider/channel secrets are scrubbed from the agent
process environment.

entrypoint.sh runs the agent as `nobody` and rebuilds the environment
with `env -i` + a SAFE_VARS allowlist, so no provider key, channel token,
or auth secret survives into the agent process.

Red/green: before the fix the agent was the container's main process and
inherited every `-e` var. OMEGA_AUTH_SECRET is always injected by
scripts/omega (default 0000), so it is the reliable marker: this test
is RED before the fix and GREEN after.

The agent reads its OWN environment via the shell skill, because only the
process owner can read it (container root lacks CAP_SYS_PTRACE under
no-new-privileges).
"""
import time

from helpers import Checker, dexec, make_prompt, wait_for_file

WAIT = 30
DUMP = "/tmp/omega38_agentenv.txt"

FORBIDDEN = [
    "OMEGA_AUTH_SECRET",
    "ANTHROPIC_API_KEY", "ASI_API_KEY", "ASIONE_API_KEY",
    "OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAIAPI_API_KEY",
    "TG_BOT_TOKEN", "SL_BOT_TOKEN", "MM_BOT_TOKEN",
    "OMEGA_OPENCLAW_TOKEN",
]


def test_agent_env_has_no_secrets(llm, comm):
    with Checker("agent env scrubbed of secrets", cleanup_dirs=[DUMP]) as c:
        print(f"\n=== OMEGA-38 credential-scrub test (run-id {c.run_id}) ===", flush=True)

        start_ts = int(time.time()) - 1

        c.step("ask agent to dump its own process environment")
        prompt = make_prompt(
            c.run_id,
            f"Use the shell skill to write your environment to a file: shell env > {DUMP}",
        )
        llm.set_answer(prompt, [("shell", { "cmd": f"env > {DUMP}" })])

        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within 60s")
        c.ok("comm", f"prompt delivered, run-id={c.run_id}")

        c.step(f"wait for env dump {DUMP} (timeout {WAIT}s)")
        if wait_for_file(DUMP, start_ts, timeout=WAIT) is None:
            c.fail("dump created", f"{DUMP} not created within {WAIT}s")
        c.ok("dump created")

        c.step("read dumped environment")
        raw = dexec("cat", DUMP).stdout
        names = {ln.split("=", 1)[0] for ln in raw.splitlines() if "=" in ln}

        c.step("positive control: PATH present (env really captured)")
        if "PATH" not in names:
            c.fail("env captured", f"PATH missing; got {sorted(names)}")
        c.ok("env captured", f"{len(names)} vars")

        c.step("no forbidden secret vars in agent env")
        leaked = sorted(n for n in FORBIDDEN if n in names)
        if leaked:
            c.fail("secrets scrubbed", f"leaked into agent env: {leaked}")
        c.ok("secrets scrubbed", "none present")

        c.done()
