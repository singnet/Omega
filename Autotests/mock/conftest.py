"""Pytest fixtures for the mock test suite.

The session-scoped llm fixture keeps a single LlmMockController alive
for the whole pytest run. The agent's IPCClient connects to it once
and holds the connection until the session ends, so per-test
set_answer() calls land before the corresponding HUMAN-MSG arrives,
without the reconnect race that hits the per-test controller pattern.

Answer keys are the full prompt strings, which include a unique
REQ-{run_id} tag, so answers do not collide across tests sharing the
same controller.

Mock-only speedups: the live Checker.__exit__ sends an IRC cancel and
sleeps 15s to give the agent time to stop writing before the harness
wipes the filesystem. In the mock suite the agent runs on the test
comm channel and never sees the IRC cancel; the mocked response is
deterministic and one-shot, so neither the cancel nor the sleep are
needed. We monkey-patch helpers at session start to drop those waits
and lower POLL, which leaves Autotests/helpers.py untouched for live
runs.
"""
import os
import re
import subprocess

import pytest

import helpers
from comm import CommMockServer, COMM_MOCK_PORT
from llm import LlmMockController, LLM_MOCK_PORT
from ocgw_stub import GATEWAY_PORT, GatewayStub


def _mock_checker_exit(self, _exc_type, _exc_val, _exc_tb):
    self.step("teardown: cleanup test artifacts")
    for path in self._cleanup_dirs:
        helpers.cleanup_dir(path)
        if helpers.dexec("test", "-e", path).returncode == 0:
            print(f"       [WARN] {path} still exists", flush=True)
        else:
            print(f"       removed {path}", flush=True)
    h_removed = helpers.history_cleanup_by_markers(self._cleanup_markers)
    print(f"       history: {h_removed} blocks removed", flush=True)
    c_removed = helpers.chromadb_cleanup_by_markers(self._cleanup_markers)
    print(f"       chromadb: {c_removed} vectors removed", flush=True)
    return False


helpers.POLL = 0.5
helpers.Checker.__exit__ = _mock_checker_exit


@pytest.fixture(scope="session")
def llm():
    controller = LlmMockController(("0.0.0.0", LLM_MOCK_PORT))
    try:
        yield controller
    finally:
        controller.stop(5)

@pytest.fixture(scope="session")
def comm():
    server = CommMockServer(("0.0.0.0", COMM_MOCK_PORT))
    try:
        yield server
    finally:
        server.stop(5)


# Answers and the frames they were served for do not outlive the test that
# registered them, so a frame left unfinished by one test cannot answer for
# the next one.
@pytest.fixture(autouse=True)
def reset_llm(request):
    yield
    if "llm" in request.fixturenames:
        request.getfixturevalue("llm").reset(5)
@pytest.fixture(scope="session")
def openclaw_gateway():
    token = os.environ.get("OMEGA_OPENCLAW_TOKEN", "")
    if not token:
        pytest.skip("OMEGA_OPENCLAW_TOKEN is not set, so the openclaw plugin cannot be "
                    "exercised; start the container with -g <gateway url> and the token")
    # A token with the plugin disabled means the container was started without
    # -g. Fail here instead of skipping: the token is always set in CI, so a
    # skip would hide a suite that checks nothing.
    #
    # Match the runtime log line, not the phrase: the container log also carries
    # the MeTTa source dump and its prolog translation, so the plain text
    # appears even when the plugin is off.
    container = os.environ.get("OMEGA_CONTAINER", "omega")
    logs = subprocess.run(["docker", "logs", container],
                          capture_output=True, text=True, errors="replace")
    enabled = re.search(r"\|\s*openclaw-plugin\s*\|\s*\"OpenClaw integration is enabled\"",
                        logs.stdout + logs.stderr)
    if not enabled:
        pytest.fail("OMEGA_OPENCLAW_TOKEN is set but the openclaw plugin is disabled in "
                    f"container {container!r}: start it with -g <gateway url> "
                    f"pointing at port {GATEWAY_PORT}")
    stub = GatewayStub(token).start()
    try:
        yield stub
    finally:
        stub.stop(5)


@pytest.fixture
def gateway(openclaw_gateway):
    openclaw_gateway.recorder.reset()
    return openclaw_gateway
