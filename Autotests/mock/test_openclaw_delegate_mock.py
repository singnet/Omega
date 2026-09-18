"""
Mock tests for the openclaw plugin's delegate-task-to-openclaw-agent skill.

The LLM and comm channel are mocked and deterministic, but the skill itself
runs for real: it makes an actual HTTP call to the OpenClaw Gateway - in
Docker via the local Nginx proxy (see plugins/openclaw/README.md), which is
why the container must be started with the Gateway URL known at launch (see
Autotests/mock/README.md, "5a. OpenClaw plugin"). That Gateway (mock or
live) is started and configured by the tester ahead of time - these tests do
not manage it.

Delegation is asynchronous: the skill returns an acceptance envelope at once
and the Gateway's reply is appended to history later as an OPENCLAW_RESULT
line, so the tests assert those two stages separately.

Run:
    pytest test_openclaw_delegate_mock.py -s
"""
import json
import re
import time

from helpers import (
    Checker, dexec, make_prompt, read_history, wait_for_history_keyword,
    wait_for_skill_call, _history_block_for_run_id,
)

# The delegated task travels to a real agent and back, so allow for a slow
# Gateway; the skill call itself must still return within one iteration.
RESULT_TIMEOUT = 180
# The stub holds a reply for this long. The acknowledgement budget below is
# shorter, so a delegation that blocked the loop could not meet it.
SLOW_GATEWAY_SECONDS = 30
ACK_BUDGET_SECONDS = 15
# Same shape helper.TS_RE requires to slice history into episodes.
HISTORY_BLOCK_RE = re.compile(r'\("\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"')


def _read_json(path):
    raw = dexec("cat", path).stdout.strip()
    return json.loads(raw)


def test_delegate_isolated_and_success_mock(llm, comm, gateway):
    with Checker("delegate-task-to-openclaw-agent mock") as c:
        print(f"\n=== Omega: openclaw delegate mock (run-id {c.run_id}) ===", flush=True)

        ####################################
        # Phase 1: check isolated skill call
        ####################################

        c.step("send prompt to check isolated skill invocation")
        prompt = make_prompt(c.run_id, "Delegate a task to OpenClaw.")
        llm.set_answer(
            request=prompt,
            response=([
                ("send", { "content": f"Delegating task {c.run_id}" }),
                ("delegate-task-to-openclaw-agent", { "task": "Reply with exactly: unused" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within timeout")

        c.step("verify send message does not absorb the skill")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30, arg_substr="Delegating task")
        if not send_arg:
            c.fail("send", "Agent did not respond to first prompt.")
        if "delegate-task-to-openclaw-agent" in send_arg:
            c.fail("parser", "Bug regression: delegate call was absorbed into the send message.")
        c.ok("parser", "delegate-task-to-openclaw-agent was correctly parsed as a separate command.")

        ##############################################
        # Phase 2: acceptance envelope, then the reply
        ##############################################

        out_path = f"/tmp/openclaw_out_{c.run_id}.json"
        echo_marker = f"PONG-{c.run_id}"

        c.step("send prompt that writes the skill result straight to a file")
        prompt = make_prompt(c.run_id + 1, "Delegate a task and save the raw result.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression": f'(write-file "{out_path}" '
                f'(delegate-task-to-openclaw-agent "Reply with exactly: {echo_marker}"))' }),
                ("send", { "content": f"Delegation saved {c.run_id}" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within timeout")
        c.ok("comm", f"run-id={c.run_id}")

        # A short timeout on purpose: the skill hands the task to a worker
        # thread, so the acknowledging send must land without waiting for the
        # Gateway. A delegation that blocks the agent loop fails here.
        c.step("wait for the agent to acknowledge without waiting for the Gateway")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30, arg_substr="Delegation saved")
        if not send_arg:
            c.fail("send", "Agent did not respond in time; the delegation is blocking the loop.")
        c.ok("send", "Agent stayed responsive while the delegation ran.")

        c.step("read and parse the acceptance envelope from the container")
        try:
            accepted = _read_json(out_path)
        except json.JSONDecodeError as e:
            c.fail("json", f"Failed to parse skill result: {e}")
        c.ok("json_parse", "delegate-task-to-openclaw-agent result successfully parsed")

        c.step("verify the envelope acknowledges the task")
        if accepted.get("status") != "accepted":
            c.fail("status", f"expected status 'accepted', got: {accepted}")
        if not accepted.get("id"):
            c.fail("id", f"task id missing from envelope: {accepted}")
        if echo_marker not in accepted.get("task", ""):
            c.fail("task", f"expected the task echo to mention {echo_marker!r}, got: {accepted}")
        c.ok("envelope", f"{accepted}")

        c.step("wait for the delegation result to reach history on its own")
        matched = wait_for_history_keyword(
            c.run_id,
            [f"id={accepted['id']} status=ok", echo_marker],
            timeout=RESULT_TIMEOUT,
            require_all=True,
        )
        if not matched:
            c.fail("result",
                   f"no successful OPENCLAW_RESULT for {accepted['id']} within {RESULT_TIMEOUT}s")
        c.ok("result", "the Gateway reply was appended to history")

        c.step("verify the appended record keeps history parsable by episodes")
        history = read_history()
        idx = history.find("OPENCLAW_RESULT")
        if idx == -1:
            c.fail("history", "OPENCLAW_RESULT vanished from history")
        if not HISTORY_BLOCK_RE.search(history[:idx]):
            c.fail("history", "the record is not inside a timestamped block; episodes would miss it")
        c.ok("history", "record sits in a well-formed timestamped block")

        c.done()


def test_delegate_empty_message_mock(llm, comm, gateway):
    with Checker("delegate-task-to-openclaw-agent empty message mock") as c:
        print(f"\n=== Omega: openclaw delegate empty mock (run-id {c.run_id}) ===", flush=True)

        out_path = f"/tmp/openclaw_empty_{c.run_id}.json"

        c.step("send prompt that delegates an empty message")
        prompt = make_prompt(c.run_id, "Delegate an empty task and save the raw result.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression": f'(write-file "{out_path}" (delegate-task-to-openclaw-agent ""))' }),
                ("send", { "content": f"Empty delegation checked {c.run_id}" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within timeout")

        c.step("wait for the agent to complete without crashing")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30, arg_substr="Empty delegation checked")
        if not send_arg:
            c.fail("send", "Agent did not respond (might have crashed on an empty message).")
        c.ok("send", "Agent survived an empty delegation.")

        c.step("verify the skill rejected the empty message without a network call")
        try:
            result = _read_json(out_path)
        except json.JSONDecodeError as e:
            c.fail("json", f"Failed to parse skill result: {e}")
        if result.get("status") != "error" or result.get("type") != "invalid_input":
            c.fail("result", f"expected an invalid_input error, got: {result}")
        c.ok("result", f"{result}")

        c.done()


def test_delegate_new_session_per_call_mock(llm, comm, gateway):
    with Checker("delegate-task-to-openclaw-agent new session per call mock") as c:
        print(f"\n=== Omega: openclaw delegate session isolation mock (run-id {c.run_id}) ===", flush=True)

        first_path = f"/tmp/openclaw_session1_{c.run_id}.json"
        second_path = f"/tmp/openclaw_session2_{c.run_id}.json"
        first_marker = f"FIRST-{c.run_id}"
        second_marker = f"SECOND-{c.run_id}"

        c.step("send prompt that delegates two independent tasks")
        prompt = make_prompt(c.run_id, "Delegate two independent tasks and save both raw results.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression": f'(write-file "{first_path}" '
                f'(delegate-task-to-openclaw-agent "Reply with exactly: {first_marker}"))' }),
                ("metta", { "sexpression": f'(write-file "{second_path}" '
                f'(delegate-task-to-openclaw-agent "Reply with exactly: {second_marker}"))' }),
                ("send", { "content": f"Both delegations saved {c.run_id}" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within timeout")

        c.step("wait for the agent to acknowledge both delegations")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30, arg_substr="Both delegations saved")
        if not send_arg:
            c.fail("send", "Agent did not respond in time; a delegation is blocking the loop.")
        c.ok("send", "Agent accepted both delegations.")

        c.step("verify each delegation got its own task id")
        try:
            first = _read_json(first_path)
            second = _read_json(second_path)
        except json.JSONDecodeError as e:
            c.fail("json", f"Failed to parse a skill result: {e}")
        if first.get("status") != "accepted" or second.get("status") != "accepted":
            c.fail("status", f"expected both to be accepted, got: {first}, {second}")
        if not first.get("id") or first.get("id") == second.get("id"):
            c.fail("id", f"task ids must differ, got: {first.get('id')} and {second.get('id')}")
        c.ok("ids", f"{first['id']} and {second['id']}")

        c.step("wait for both replies to reach history")
        matched = wait_for_history_keyword(
            c.run_id,
            [f"id={first['id']} status=ok", f"id={second['id']} status=ok"],
            timeout=RESULT_TIMEOUT,
            require_all=True,
        )
        if not matched:
            c.fail("result",
                   f"both successful OPENCLAW_RESULT records did not arrive within {RESULT_TIMEOUT}s")
        c.ok("result", "both replies were appended to history")

        # Scoped to this run's slice of history so ids left by earlier tests
        # cannot make the comparison pass on their own.
        c.step("verify the two calls ran in separate Gateway sessions")
        window = _history_block_for_run_id(read_history(), c.run_id) or ""
        response_ids = set(re.findall(r"responseId=(\S+)", window))
        if len(response_ids) < 2:
            c.fail("session isolation",
                   f"expected two distinct responseId values, found: {response_ids or 'none'}")
        c.ok("session isolation", f"{len(response_ids)} distinct responseId values")

        c.done()


def test_delegate_stays_async_under_a_slow_gateway_mock(llm, comm, gateway):
    with Checker("delegate-task-to-openclaw-agent stays async") as c:
        print(f"\n=== Omega: openclaw slow-gateway mock (run-id {c.run_id}) ===", flush=True)

        out_path = f"/tmp/openclaw_slow_{c.run_id}.json"

        c.step(f"delegate a task the Gateway holds for {SLOW_GATEWAY_SECONDS}s")
        prompt = make_prompt(c.run_id, "Delegate a long task.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression": f'(write-file "{out_path}" '
                f'(delegate-task-to-openclaw-agent '
                f'"OCGW_SLEEP:{SLOW_GATEWAY_SECONDS} Reply with exactly: SLOW-{c.run_id}"))' }),
                ("send", { "content": f"Long delegation started {c.run_id}" })
            ]),
        )
        started = time.time()
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the prompt within timeout")

        # Shorter than the Gateway delay on purpose: a blocking delegation
        # cannot answer this fast.
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=ACK_BUDGET_SECONDS,
                                       arg_substr="Long delegation started")
        acknowledged_after = time.time() - started
        if not send_arg:
            c.fail("async", f"no acknowledgement within {ACK_BUDGET_SECONDS}s; "
                            "the delegation is blocking the agent loop")
        c.ok("async", f"acknowledged in {acknowledged_after:.1f}s "
                      f"against a {SLOW_GATEWAY_SECONDS}s Gateway")

        c.step("an unrelated prompt is answered while the delegation is still pending")
        second_id = c.run_id + 1
        second = make_prompt(second_id, "Answer with the marker.")
        llm.set_answer(request=second, response=[("send", { "content": f"STILL-ALIVE-{c.run_id}" })])
        if not comm.send_message(second):
            c.fail("comm", "could not deliver the second prompt within timeout")
        alive = wait_for_skill_call(second_id, "send", timeout=ACK_BUDGET_SECONDS,
                                    arg_substr=f"STILL-ALIVE-{c.run_id}")
        answered_after = time.time() - started
        if not alive:
            c.fail("responsive", "the agent went unresponsive while a delegation was pending "
                                 f"({answered_after:.1f}s in)")
        if answered_after >= SLOW_GATEWAY_SECONDS:
            c.fail("responsive", f"the second answer only arrived at {answered_after:.1f}s, "
                                 "i.e. after the Gateway released the loop")
        c.ok("responsive", f"second prompt answered at {answered_after:.1f}s")

        c.step("the slow reply still reaches history once the Gateway answers")
        try:
            envelope = _read_json(out_path)
        except json.JSONDecodeError as e:
            c.fail("json", f"Failed to parse the skill result: {e}")
        task_id = envelope.get("id")
        if envelope.get("status") != "accepted" or not task_id:
            c.fail("envelope", f"expected an accepted envelope, got: {envelope}")
        # Matching the id and the ok status, not the marker on its own: the marker
        # is part of the delegated task text, so it also shows up in a failed record.
        if not wait_for_history_keyword(c.run_id,
                                        [f"id={task_id} status=ok", f"reply=SLOW-{c.run_id}"],
                                        timeout=SLOW_GATEWAY_SECONDS + RESULT_TIMEOUT,
                                        require_all=True):
            c.fail("result", "the slow delegation never produced a successful history record")
        c.ok("result", f"slow delegation result reached history as {task_id}")

        c.done()


def test_delegate_reports_gateway_rejection_mock(llm, comm, gateway):
    with Checker("delegate-task-to-openclaw-agent reports a rejection") as c:
        print(f"\n=== Omega: openclaw rejection mock (run-id {c.run_id}) ===", flush=True)

        out_path = f"/tmp/openclaw_401_{c.run_id}.json"

        c.step("delegate a task the Gateway refuses with 401")
        prompt = make_prompt(c.run_id, "Delegate a task that will be refused.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression": f'(write-file "{out_path}" '
                f'(delegate-task-to-openclaw-agent "OCGW_UNAUTHORIZED {c.run_id}"))' }),
                ("send", { "content": f"Refused delegation checked {c.run_id}" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the prompt within timeout")

        if not wait_for_skill_call(c.run_id, "send", timeout=30,
                                   arg_substr="Refused delegation checked"):
            c.fail("send", "the agent did not stay responsive through a refused delegation")
        c.ok("send", "the refusal did not disturb the agent loop")

        c.step("the task is still accepted up front, since the skill returns before the call")
        accepted = _read_json(out_path)
        if accepted.get("status") != "accepted":
            c.fail("status", f"expected the envelope to accept the task, got: {accepted}")
        c.ok("envelope", f"{accepted}")

        c.step("the failure reaches history as an error record carrying the reason")
        matched = wait_for_history_keyword(
            c.run_id,
            [f"id={accepted['id']} status=error", "401"],
            timeout=RESULT_TIMEOUT,
            require_all=True,
        )
        if not matched:
            c.fail("result", f"no failing OPENCLAW_RESULT for {accepted['id']} "
                             f"within {RESULT_TIMEOUT}s")
        c.ok("result", "the rejection was reported to the agent rather than swallowed")

        c.done()


def test_delegate_retries_a_starting_gateway_mock(llm, comm, gateway):
    with Checker("delegate-task-to-openclaw-agent retries a starting Gateway") as c:
        print(f"\n=== Omega: openclaw startup-retry mock (run-id {c.run_id}) ===", flush=True)

        out_path = f"/tmp/openclaw_503_{c.run_id}.json"
        marker = f"RETRIED-{c.run_id}"

        c.step("delegate a task the Gateway rejects twice with 503 before answering")
        prompt = make_prompt(c.run_id, "Delegate a task to a starting Gateway.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression": f'(write-file "{out_path}" (delegate-task-to-openclaw-agent '
                f'"OCGW_503:2 Reply with exactly: {marker}"))' }),
                ("send", { "content": f"Retry delegation started {c.run_id}" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the prompt within timeout")

        if not wait_for_skill_call(c.run_id, "send", timeout=30,
                                   arg_substr="Retry delegation started"):
            c.fail("send", "the agent did not acknowledge; retries must run off the loop")
        c.ok("send", "retries did not stall the agent loop")

        accepted = _read_json(out_path)
        c.step("the delegation eventually succeeds and reaches history")
        matched = wait_for_history_keyword(
            c.run_id,
            [f"id={accepted['id']} status=ok", marker],
            timeout=RESULT_TIMEOUT,
            require_all=True,
        )
        if not matched:
            c.fail("result", f"the retried delegation never succeeded within {RESULT_TIMEOUT}s")
        c.ok("result", "the delegation succeeded after the Gateway finished starting")

        c.step("the Gateway saw the retries rather than a single call")
        attempts = [r for r in gateway.recorder.requests if "OCGW_503:2" in r["input"]]
        if len(attempts) < 3:
            c.fail("retry", f"expected 3 attempts (2 refused, 1 served), saw {len(attempts)}")
        c.ok("retry", f"{len(attempts)} attempts reached the Gateway")

        c.done()


def test_delegate_reports_a_reply_without_text_mock(llm, comm, gateway):
    with Checker("delegate-task-to-openclaw-agent reports an empty Gateway reply") as c:
        print(f"\n=== Omega: openclaw no-text mock (run-id {c.run_id}) ===", flush=True)

        out_path = f"/tmp/openclaw_notext_{c.run_id}.json"

        c.step("delegate a task the Gateway answers without any visible text")
        prompt = make_prompt(c.run_id, "Delegate a task answered without text.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression": f'(write-file "{out_path}" '
                f'(delegate-task-to-openclaw-agent "OCGW_NOTEXT {c.run_id}"))' }),
                ("send", { "content": f"Empty reply checked {c.run_id}" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the prompt within timeout")

        if not wait_for_skill_call(c.run_id, "send", timeout=30,
                                   arg_substr="Empty reply checked"):
            c.fail("send", "the agent did not survive a reply carrying no text")
        c.ok("send", "the agent stayed responsive")

        accepted = _read_json(out_path)
        c.step("the empty reply is reported as an error rather than an empty success")
        if not wait_for_history_keyword(c.run_id, [f"id={accepted['id']} status=error"],
                                        timeout=RESULT_TIMEOUT):
            c.fail("result", "an empty Gateway reply was not reported as an error")
        c.ok("result", "reported as an error record")

        c.done()


def test_delegation_is_authenticated_by_the_proxy_mock(llm, comm, gateway):
    with Checker("delegation is authenticated by the proxy, not by the agent") as c:
        print(f"\n=== Omega: openclaw token-injection mock (run-id {c.run_id}) ===", flush=True)

        c.step("delegate a task and let it reach the Gateway")
        prompt = make_prompt(c.run_id, "Delegate a task.")
        llm.set_answer(
            request=prompt,
            response=([
                ("delegate-task-to-openclaw-agent", { "task": f"Reply with exactly: TOKEN-{c.run_id}" }),
                ("send", { "content": f"Token delegation sent {c.run_id}" })
            ]),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the prompt within timeout")
        if not wait_for_skill_call(c.run_id, "send", timeout=30,
                                   arg_substr="Token delegation sent"):
            c.fail("send", "the agent did not acknowledge the delegation")
        if not wait_for_history_keyword(c.run_id, [f"TOKEN-{c.run_id}"], timeout=RESULT_TIMEOUT):
            c.fail("result", "the delegation never completed")

        c.step("the Gateway received a correctly authenticated request")
        served = gateway.recorder.requests
        authorized = gateway.recorder.authorized_requests()
        if not authorized:
            c.fail("auth", "no authenticated request reached the Gateway; "
                           "the proxy did not inject the token")
        c.ok("auth", f"{len(authorized)} authenticated request(s) reached the Gateway")

        c.step("every delegation carried the header, none arrived bare")
        bare = [r for r in served if not r["auth_header_present"]]
        if bare:
            c.fail("auth", f"{len(bare)} request(s) reached the Gateway without an "
                           "Authorization header")
        c.ok("auth", "the proxy authenticated every delegation")

        c.done()
