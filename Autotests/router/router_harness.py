import itertools
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAME_PREFIX = os.environ.get("OMEGA_ROUTER_TEST_PREFIX", "omega-router-test")
LOG_DIR = os.environ.get("OMEGA_ROUTER_TEST_LOGS") or os.path.join(
    tempfile.gettempdir(), "omega-router-tests")
PORT_RANGE = range(19101, 19121)
STARTUP_TIMEOUT = 150
REQUEST_TIMEOUT = 90
HOST_ALIAS = "host.docker.internal"

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RUNTIME = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| [A-Z]+ +\| "
ITERATION_1 = RUNTIME + r"loop \| \(---------iteration 1\)"

DOCKER_FLAGS = [
    "--init",
    "--security-opt", "no-new-privileges:true",
    "--tmpfs", "/tmp:size=64m,mode=1777",
    "--tmpfs", "/var/tmp:size=64m,mode=1777",
    "--tmpfs", "/run:size=16m,mode=755",
    "--add-host", f"{HOST_ALIAS}:host-gateway",
]

_ports = itertools.cycle(PORT_RANGE)


def docker(*args, timeout=60):
    cmd = ["docker", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def resolve_image():
    explicit = os.environ.get("OMEGA_ROUTER_TEST_IMAGE")
    if explicit:
        return explicit
    container = os.environ.get("OMEGA_CONTAINER") or "omega"
    inspected = docker("inspect", "-f", "{{.Config.Image}}", container)
    if inspected.returncode == 0 and inspected.stdout.strip():
        return inspected.stdout.strip()
    tag = os.environ.get("AUTOTESTS_OMEGA_TAG")
    if tag:
        return f"singularitynet/omega:{tag}"
    raise RuntimeError(
        "no image: set OMEGA_ROUTER_TEST_IMAGE, or run the container "
        f"'{container}', or set AUTOTESTS_OMEGA_TAG")


def pin_calls(count, tag="p"):
    return [("pin", {"message": f"{tag}-{i}"}) for i in range(count)]


def failing_calls():
    return [("pin", {"wrong_argument": "x"})]


def stub_url(stub):
    return f"http://{HOST_ALIAS}:{stub.port}/v1/"


def catalog(routine, premium=None):
    def record(stub, model, token):
        return {
            "provider": "OpenAIAPI",
            "api_token_var": "OPENAIAPI_API_KEY",
            "model": model,
            "openaiapi_url": stub_url(stub),
            "token": token,
        }
    result = {"routine": record(*routine)}
    if premium is not None:
        result["premium"] = record(*premium)
    return result


class Timeline:
    def __init__(self):
        self._items = []
        self._cond = threading.Condition()

    def add(self, label):
        with self._cond:
            self._items.append(label)
            self._cond.notify_all()

    def snapshot(self):
        with self._cond:
            return list(self._items)

    def wait_len(self, count, timeout):
        deadline = time.monotonic() + timeout
        with self._cond:
            while len(self._items) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True


class Stub:
    def __init__(self, label, script=None, timeline=None):
        self.label = label
        self.requests = []
        self._script = script or (lambda _number: pin_calls(1))
        self._timeline = timeline
        self._cond = threading.Condition()
        self._thread = None
        self.port, self._server = self._bind()

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _bind(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                with stub._cond:
                    stub.requests.append({
                        "path": self.path,
                        "authorization": self.headers.get("Authorization", ""),
                        "body": body,
                    })
                    number = len(stub.requests)
                    stub._cond.notify_all()
                if stub._timeline is not None:
                    stub._timeline.add(stub.label)
                calls = stub._script(number)
                data = json.dumps(stub._response(body, number, calls)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        last_error = None
        for _ in PORT_RANGE:
            port = next(_ports)
            try:
                return port, ThreadingHTTPServer(("0.0.0.0", port), Handler)
            except OSError as error:
                last_error = error
        raise RuntimeError(f"no free stub port in {PORT_RANGE}: {last_error}")

    @staticmethod
    def _response(body, number, calls):
        return {
            "id": f"stub-{number}",
            "object": "chat.completion",
            "created": 1,
            "model": body.get("model", "stub"),
            "choices": [{
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": f"call-{number}-{index}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    } for index, (name, arguments) in enumerate(calls)],
                },
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def stop(self):
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=10)
        self._server.server_close()

    def wait_requests(self, count, timeout=REQUEST_TIMEOUT, until=None):
        deadline = time.monotonic() + timeout
        with self._cond:
            while len(self.requests) < count:
                if until is not None and until():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(min(remaining, 1.0))
            return True

    def models(self):
        with self._cond:
            return [item["body"].get("model") for item in self.requests]


class LogTail:
    def __init__(self, name):
        self.lines = []
        self.ended = False
        self._cond = threading.Condition()
        self._proc = subprocess.Popen(
            ["docker", "logs", "-f", name],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        for line in self._proc.stdout or ():
            with self._cond:
                self.lines.append(ANSI.sub("", line.rstrip("\n")))
                self._cond.notify_all()
        with self._cond:
            self.ended = True
            self._cond.notify_all()

    def wait_for(self, pattern, timeout):
        regex = re.compile(pattern)
        deadline = time.monotonic() + timeout
        checked = 0
        with self._cond:
            while True:
                while checked < len(self.lines):
                    line = self.lines[checked]
                    checked += 1
                    if regex.search(line):
                        return line
                if self.ended:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)

    def matching(self, pattern):
        regex = re.compile(pattern)
        with self._cond:
            return [line for line in self.lines if regex.search(line)]

    def text(self):
        with self._cond:
            return "\n".join(self.lines)

    def close(self):
        self._proc.kill()
        self._thread.join(timeout=10)


class Agent:
    def __init__(self, name, image, app_args, env=None, entrypoint=None, docker_args=()):
        self.name = name
        self.image = image
        cmd = ["docker", "run", "-d", "-t", "--name", name]
        if entrypoint is None:
            cmd += DOCKER_FLAGS
        else:
            cmd += ["--add-host", f"{HOST_ALIAS}:host-gateway", "--entrypoint", entrypoint]
        cmd += list(docker_args)
        for key, value in (env or {}).items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [image, *app_args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"docker run failed: {result.stderr.strip()}")
        self.tail = LogTail(name)

    def wait_stub_request(self, stub, timeout):
        return stub.wait_requests(1, timeout, until=lambda: self.state()[0] != "running")

    def state(self):
        result = docker("inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", self.name)
        status, _, code = result.stdout.strip().partition(" ")
        return status, int(code) if code else None

    def inspect(self, template):
        return docker("inspect", "-f", template, self.name).stdout.strip()

    def exec(self, *args, user=None):
        cmd = ["exec"]
        if user:
            cmd += ["-u", user]
        return docker(*cmd, self.name, *args)

    def runtime_lines(self, module, text):
        return self.tail.matching(RUNTIME + module + r" \| " + text)

    def describe(self):
        status, code = self.state()
        runtime = self.tail.matching(RUNTIME)[-8:]
        raw = self.tail.lines[-8:]
        return (f"container state={status} exit_code={code}; last runtime lines:\n"
                + "\n".join(runtime) + "\nlast raw lines:\n" + "\n".join(raw))

    def wait_log(self, module, text, timeout=STARTUP_TIMEOUT):
        line = self.tail.wait_for(RUNTIME + module + r" \| " + text, timeout)
        assert line is not None, (
            f"no log line for module={module} text={text!r} within {timeout}s; "
            + self.describe())
        return line

    def wait_iteration_1(self, timeout=STARTUP_TIMEOUT):
        line = self.tail.wait_for(ITERATION_1, timeout)
        assert line is not None, f"agent did not reach iteration 1 within {timeout}s; " + self.describe()
        return line

    def wait_exit(self, timeout=STARTUP_TIMEOUT):
        result = docker("wait", self.name, timeout=timeout + 10)
        return int(result.stdout.strip())

    def save_log(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, f"{self.name}.log"), "w", encoding="utf-8") as out:
            out.write(self.tail.text() if self.tail else "")


def new_name(label):
    return f"{NAME_PREFIX}-{label}-{uuid.uuid4().hex[:6]}"
