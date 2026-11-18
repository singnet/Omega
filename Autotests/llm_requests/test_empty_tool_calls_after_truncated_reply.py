import json
import os
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST_ALIAS = "host.docker.internal"
FOLLOW_UP_REQUESTS = 2
REQUEST_TIMEOUT = 100


def docker(*args, timeout=60):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def resolve_image():
    container = os.environ.get("OMEGA_CONTAINER") or "omega"
    inspected = docker("inspect", "-f", "{{.Config.Image}}", container)
    if inspected.returncode == 0 and inspected.stdout.strip():
        return inspected.stdout.strip()
    tag = os.environ.get("AUTOTESTS_OMEGA_TAG")
    if tag:
        return f"singularitynet/omega:{tag}"
    raise RuntimeError(f"no image: run the container '{container}' or set AUTOTESTS_OMEGA_TAG")


class ChatCompletionsStub:
    def __init__(self):
        self.requests = []
        self._cond = threading.Condition()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):
                length = self.headers.get("Content-Length")
                if length is None:
                    raise AssertionError("request to the model stub has no Content-Length")
                size = int(length)
                body = json.loads(self.rfile.read(size) or b"{}")
                with stub._cond:
                    stub.requests.append(body)
                    number = len(stub.requests)
                    stub._cond.notify_all()
                status, payload = stub._answer(body, number)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @staticmethod
    def _answer(body, number):
        for index, message in enumerate(body.get("messages", [])):
            if isinstance(message, dict) and message.get("tool_calls") == []:
                text = (
                    f"Invalid 'messages[{index}].tool_calls': empty array. "
                    "Expected an array with minimum length 1, but got an empty array instead."
                )
                return 400, {"error": {
                    "message": text,
                    "type": "invalid_request_error",
                    "param": f"messages[{index}].tool_calls",
                    "code": "empty_array",
                }}
        if number == 1:
            message = {"role": "assistant", "content": "The answer was cut off by the output limit and"}
            finish_reason = "length"
        else:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call-{number}",
                "type": "function",
                "function": {"name": "pin", "arguments": json.dumps({"message": f"note {number}"})},
            }]}
            finish_reason = "tool_calls"
        return 200, {
            "id": f"stub-{number}",
            "object": "chat.completion",
            "created": 1,
            "model": body.get("model", "stub"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def wait_requests(self, count, timeout, until):
        deadline = time.monotonic() + timeout
        while True:
            with self._cond:
                if len(self.requests) >= count:
                    return True
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._cond.wait(min(remaining, 1.0))
            if remaining <= 0 or until():
                return len(self.snapshot()) >= count

    def snapshot(self):
        with self._cond:
            return list(self.requests)

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=10)


def container_running(name):
    result = docker("inspect", "-f", "{{.State.Running}}", name)
    return result.stdout.strip() == "true"


def find_empty_tool_calls(requests):
    for number, body in enumerate(requests, start=1):
        for index, message in enumerate(body.get("messages", [])):
            if isinstance(message, dict) and message.get("tool_calls") == []:
                return (
                    f"request {number} carries an empty tool_calls in messages[{index}]: "
                    f"{json.dumps(message)[:300]}"
                )
    return None


def test_request_after_truncated_reply_has_no_empty_tool_calls():
    image = resolve_image()
    name = f"omega-llm-requests-{uuid.uuid4().hex[:8]}"
    stub = ChatCompletionsStub()
    try:
        try:
            started = docker(
                "run", "-d", "-t", "--name", name,
                "--security-opt", "no-new-privileges:true",
                "--init",
                "--add-host", f"{HOST_ALIAS}:host-gateway",
                "--tmpfs", "/tmp:size=64m,mode=1777",
                "--tmpfs", "/var/tmp:size=64m,mode=1777",
                "--tmpfs", "/run:size=16m,mode=755",
                "-e", "OPENAIAPI_API_KEY=dummy-key",
                image,
                "commchannel=test",
                "provider=OpenAIAPI",
                "embeddingprovider=Local",
                "securityPolicyPath=/PeTTa/repos/Omega/profile/policy.yaml",
                "model=stub-model",
                f"openaiapi_url=http://{HOST_ALIAS}:{stub.port}/v1",
                timeout=120,
            )
            assert started.returncode == 0, f"docker run failed: {started.stderr.strip()}"

            wanted = 1 + FOLLOW_UP_REQUESTS
            arrived = stub.wait_requests(wanted, REQUEST_TIMEOUT, lambda: not container_running(name))
            requests = stub.snapshot()
            problem = find_empty_tool_calls(requests)
            assert problem is None, problem
            logs = docker("logs", "--tail", "30", name).stdout
            assert arrived, (
                f"expected {wanted} requests to the model, got {len(requests)}; container log tail:\n{logs}"
            )
        finally:
            try:
                docker("stop", "-t", "5", name, timeout=60)
            finally:
                docker("rm", "-f", name, timeout=60)
    finally:
        stub.stop()
