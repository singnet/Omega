"""Set OMEGA_AUTH_TEST_IMAGE to a locally available Omega image to run."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

import pytest


PROXY = Path(__file__).resolve().parents[1] / "proxy"
IMAGE = os.getenv("OMEGA_AUTH_TEST_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires a local Omega Docker image")


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def test_protected_bindings_survive_restart_and_recreation(tmp_path):
    name = "omega-auth-test-" + uuid.uuid4().hex
    # Serve authenticated HTTPS responses locally, with no network or real bot credentials.
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-subj", "/CN=api.telegram.org", "-addext", "subjectAltName=DNS:api.telegram.org",
                    "-keyout", str(tmp_path / "key"), "-out", str(tmp_path / "cert"), "-days", "1"],
                   check=True, capture_output=True)
    (tmp_path / "provider.py").write_text("""
import ssl
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/botfixture/getUpdates':
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(Path('/fixture/updates').read_bytes())

server = HTTPServer(('127.0.0.1', 443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/cert', '/fixture/key')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
""")
    updates = []
    def publish(text, chat_id, chat_type):
        update_id = len(updates) + 1
        updates.append({"update_id": update_id, "message": {
            "text": text, "from": {"id": 123}, "chat": {"id": chat_id, "type": chat_type}}})
        (tmp_path / "updates").write_text(json.dumps({"ok": True, "result": updates}))
        return update_id

    publish("auth test-token", 123, "private")
    volume = docker("volume", "create", name).stdout.strip()
    # Exercise real nginx and Unix permissions without contacting channel providers.
    template = (PROXY / "nginx.conf.template").read_text()
    hosts = sorted(set(re.findall(r"proxy_pass https://([\w.-]+)", template)))
    bootstrap = """
        python3 /fixture/provider.py &
        install -d -o www-data -g www-data -m 0700 /var/lib/omega-state/channel
        cp /fixture/cert /tmp/telegram-test-ca
        cp /source/auth_state.py /source/nginx.sh /source/nginx.conf.template /opt/nginx/
        su www-data -s /bin/sh -c 'sh /opt/nginx/nginx.sh --auth-state'
        exec sleep infinity
    """

    def start():
        docker("run", "-dit", "--name", name, "--network", "none",
               *(arg for host in hosts for arg in ("--add-host", host + ":127.0.0.1")),
               "-v", f"{volume}:/var/lib/omega-state", "-v", f"{PROXY}:/source:ro",
               "-v", f"{tmp_path}:/fixture:ro", "-e", "SSL_CERT_FILE=/tmp/telegram-test-ca",
               "-e", "TG_BOT_TOKEN=fixture", "-e", "OMEGA_AUTH_SECRET=test-token",
               *(arg for key in ("OPENAIAPI_URL", "OPENCLAW_URL", "MM_URL")
                 for arg in ("-e", key + "=http://localhost:8080/")),
               "--entrypoint", "sh", IMAGE, "-ec", bootstrap)

    def request(route, token="", **fields):
        response = docker("exec", "-u", "65534:65534", name, "curl", "-fsS",
                          "-H", "X-Auth-Token: " + token, "-d",
                          json.dumps({"channel_identifier": "TELEGRAM", **fields}),
                          "http://127.0.0.1:8080/auth/" + route)
        return json.loads(response.stdout)

    def wait_ready():
        for _ in range(50):
            try:
                request("state")
                return
            except subprocess.CalledProcessError:
                time.sleep(0.1)
        logs = docker("logs", name)
        pytest.fail(logs.stdout + logs.stderr)

    try:
        start()
        wait_ready()
        assert request("bind", "wrong", user_id="123")["result"] == "ignore"
        assert request("bind", "test-token", user_id="123")["result"] == "auth_bound"
        assert request("bind", "test-token", user_id="other")["result"] == "ignore"
        group = {"group_id": "-10", "requester_user_id": "123", "update_id": 999}
        assert request("group/authorize", **group)["result"] == "ignore"
        group["update_id"] = publish("/bind", -10, "supergroup")
        assert request("group/authorize", **group)["result"] == "group_bound"
        assert request("group/revoke", group_id="g", requester_user_id="other")["result"] == "ignore"
        for record in ("authenticated-user.json", "authenticated-group.json"):
            path = "/var/lib/omega-state/channel/" + record
            for operation in (["cat", path], ["touch", path], ["rm", path]):
                denial = docker("exec", "-u", "65534:65534", name, *operation, check=False)
                assert denial.returncode and "Permission denied" in denial.stderr
        expected = {"owner_id": "123", "groups": ["-10"]}
        docker("restart", name)
        wait_ready()
        assert request("state") == expected
        docker("rm", "-f", name)
        start()
        wait_ready()
        assert request("state") == expected
        revoke = {**group, "update_id": publish("/unbind -10", 123, "private")}
        assert request("group/revoke", **revoke)["result"] == "group_unbound"
        assert request("group/authorize", **group)["result"] == "ignore"
        assert request("state")["groups"] == []
    finally:
        docker("rm", "-f", name, check=False)
        docker("volume", "rm", volume)
