"""Trusted channel-state backend. Only nginx can reach the Unix socket."""
import fcntl
import hmac
import json
import os
import socketserver
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

DIRECTORY = Path("/var/lib/omega-state/channel")
SOCKET = Path("/opt/nginx/auth-state.sock")


def read_map(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def write_map(path, records):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as output:
        json.dump(records, output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def field(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(key)
    return value.strip()


def telegram_api(method):
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        raise ValueError("Telegram bot is not configured")
    # Only fixed Bot API methods are used here. Never log a URL containing the token.
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", timeout=3) as response:
        payload = json.load(response)
    if not payload.get("ok"):
        raise OSError("Telegram verification unavailable")
    return payload["result"]


def bot_username():
    return telegram_api("getMe")["username"].lower()


def telegram_confirms(route, owner, target, secret="", update_id=None, last_id=None):
    # The adapter processes the current batch before acknowledging its offset.
    # Read it independently, without advancing the shared Telegram cursor.
    if route != "/auth/bind" and type(update_id) is not int:
        return False
    pending = telegram_api("getUpdates")
    if route != "/auth/bind":
        # Telegram returns the unacknowledged suffix in delivery order. If
        # the last applied command is still pending, discard its predecessors.
        for index, update in enumerate(pending):
            if update["update_id"] == last_id:
                pending = pending[index:]
                break
        pending = [update for update in pending if update["update_id"] == update_id]
    for update in pending:
        msg = update.get("message") or update.get("edited_message") or {}
        if str(msg.get("from", {}).get("id", "")) != owner:
            continue
        parts = msg.get("text", "").strip().split(None, 1)
        if not parts:
            continue
        command, marker, username = parts[0].lower().partition("@")
        chat = msg["chat"]
        if route == "/auth/bind":
            if (chat["type"] == "private" and str(chat["id"]) == owner and not marker
                    and command in ("auth", "/auth") and len(parts) == 2
                    and hmac.compare_digest(parts[1].encode(), secret.encode())):
                return True
            continue
        if command in ("/bind", "/authorize_group"):
            action = "/auth/group/authorize"
        elif command in ("/unbind", "/unauthorize_group"):
            action = "/auth/group/revoke"
        else:
            continue
        if chat["type"] == "private":
            if action != "/auth/group/revoke" or len(parts) != 2:
                continue
            group = parts[1]
        elif chat["type"] in ("group", "supergroup"):
            group = str(chat["id"])
        else:
            continue
        if group == target and (not marker or username == bot_username()):
            return action == route
    return False


def handle(directory, route, data, token, secret):
    channel = field(data, "channel_identifier")
    owners_path = directory / "authenticated-user.json"
    groups_path = directory / "authenticated-group.json"
    # Serialize check and update even if two containers share the volume.
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        owners = read_map(owners_path)
        owner = owners.get(channel)
        if route == "/auth/bind":
            user = field(data, "user_id")
            if owner is not None or not secret or not hmac.compare_digest(token.encode(), secret.encode()):
                return {"result": "ignore"}
            if channel == "TELEGRAM" and not telegram_confirms(route, user, None, secret):
                return {"result": "ignore"}
            owners[channel] = user
            write_map(owners_path, owners)
            return {"result": "auth_bound"}

        groups = read_map(groups_path)
        records = groups.get(channel, [])
        if isinstance(records, dict):
            active = set(records["active"])
            last_updates = records["last_updates"]
        else:
            active = set(records)
            last_updates = {}
        if route == "/auth/state":
            return {"owner_id": owner, "groups": sorted(active)}
        group = field(data, "group_id")
        if channel != "TELEGRAM" or field(data, "requester_user_id") != owner:
            return {"result": "ignore"}
        update_id = data.get("update_id")
        if not telegram_confirms(route, owner, group, update_id=update_id, last_id=last_updates.get(group)):
            return {"result": "ignore"}
        if route == "/auth/group/authorize":
            result = "allow" if group in active else "group_bound"
            active.add(group)
        elif route == "/auth/group/revoke":
            active.discard(group)
            result = "group_unbound"
        else:
            return {"result": "ignore"}
        last_updates[group] = update_id
        groups[channel] = {"active": sorted(active), "last_updates": last_updates}
        write_map(groups_path, groups)
        return {"result": result}


class Handler(BaseHTTPRequestHandler):
    def address_string(self):
        return "nginx"

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError("invalid body length")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("expected object")
            result = handle(DIRECTORY, self.path, data, self.headers.get("X-Auth-Token", ""),
                            self.server.secret)
        except OSError:
            self.send_error(503)
            return
        except ValueError:
            self.send_error(400)
            return
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    os.umask(0o077)
    with socketserver.UnixStreamServer(str(SOCKET), Handler) as server:
        server.secret = os.getenv("OMEGA_AUTH_SECRET") or os.getenv("OMEGACLAW_AUTH_SECRET", "")
        server.serve_forever()
