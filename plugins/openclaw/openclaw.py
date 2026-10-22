"""Bridge between an Omega dynamic skill and an external OpenClaw Gateway.

Protocol reference: https://docs.openclaw.ai/gateway/openresponses-http-api
(Gateway OpenResponses HTTP API).

The endpoint is stateless per request: the Gateway generates a fresh session
key for every call unless one is supplied, which matches the "new separate
session per delegation" contract of the skill.

Delegation is asynchronous. A Gateway turn can take minutes and the agent
loop is single-threaded, so `send` only hands the task to a worker thread and
returns an acceptance envelope. The worker never touches the atomspace: it
parks its record here, and the MeTTa side drains it with `take_completed` on
its own thread. This mirrors how the communication channels feed the loop.
"""


import json
import threading
import time
import os
import requests

from config import config_get_by_key
from src.logger import get_logger


logger = get_logger(__name__)

RESPONSES_PATH = "/v1/responses"
# Required by the request schema, but it selects the agent rather than a
# model: the run uses whatever model that agent is configured with.
MODEL_ROUTE = "openclaw"
SESSION_TIMEOUT = 600.0
STARTUP_RETRY_ATTEMPTS = 3
STARTUP_RETRY_MAX_WAIT = 5.0
MAX_IN_FLIGHT = 5
# The history window keeps only its last `maxHistory` bytes, so one unbounded
# reply would evict everything else.
MAX_REPLY_CHARS = 8000
TASK_ECHO_CHARS = 80

_lock = threading.Lock()
_completed = []
_in_flight = 0
_seq = 0


class OpenClawError(RuntimeError):
    """Base error raised by the OpenClaw bridge."""

    def __init__(self, msg: str = "OpenClaw Error"):
        """Store the human-readable failure description.

        Args:
            msg (str): Message shown to the agent in the skill result.
        """
        self.msg = msg
        super().__init__(msg)


class OpenClawStartupError(OpenClawError):
    """Raised when the Gateway is still booting and asks the client to retry."""

    def __init__(self, msg: str, retry_after: float):
        """Store the retry hint sent by the Gateway.

        Args:
            msg (str): Human-readable failure description.
            retry_after (float): Seconds the Gateway asked the client to wait.
        """
        self.retry_after = retry_after
        super().__init__(msg)


def _get_token() -> str:
    """Retrieves OpenClaw token from environment variables.

    Returns:
        str: The auth token.
    """
    return os.getenv("OMEGA_OPENCLAW_TOKEN", "").strip()


def send(
    message: str,
    openclaw_url: str,
    openclaw_agent: str
) -> str:
    """Hand one independent task to OpenClaw without waiting for the reply.

    A new OpenClaw session is created for every invocation. The returned JSON
    string is an acceptance envelope suitable for insertion into LLM request;
    the reply itself is collected later through `take_completed`.

    Args:
        message (str): Self-contained natural-language task.
        openclaw_url (str): The base URL of the OpenClaw Gateway.
        openclaw_agent (str): The target agent identifier.

    Returns:
        str: JSON string acknowledging the task, or reporting why it was not
             accepted, formatted for the agent's context.
    """
    global _in_flight, _seq
    task = str(message).strip()
    if not task:
        logger.warning("Refusing to delegate an empty message")
        return json.dumps({
            "status": "error",
            "type": "invalid_input",
            "message": "message is empty"
        }, ensure_ascii=False)
    with _lock:
        if _in_flight >= MAX_IN_FLIGHT:
            logger.info(f"Refusing to delegate, {_in_flight} tasks in flight")
            return json.dumps({
                "status": "error",
                "type": "busy",
                "message": f"{_in_flight} delegations are still running, max in flight: {MAX_IN_FLIGHT}"
            }, ensure_ascii=False)
        _seq += 1
        _in_flight += 1
        task_id = f"oc-{_seq}"
    threading.Thread(
        target=_worker,
        args=(task_id, task, str(openclaw_url), str(openclaw_agent)),
        daemon=True,
    ).start()
    logger.info(f"Delegated {task_id} to OpenClaw agent '{openclaw_agent}'")
    return json.dumps({
        "status": "accepted",
        "id": task_id,
        "task": task[:TASK_ECHO_CHARS],
    }, ensure_ascii=False)


def _worker(
    task_id: str,
    message: str,
    openclaw_url: str,
    openclaw_agent: str
) -> None:
    """Run one delegation off the agent loop and park its record for pickup.

    Args:
        task_id (str): Identifier echoed back to the agent on acceptance.
        message (str): The task description.
        openclaw_url (str): The base URL.
        openclaw_agent (str): Target agent ID.
    """
    global _in_flight
    try:
        record = _record(task_id, message, _run(message, openclaw_url, openclaw_agent))
    except Exception as exc:
        logger.exception(f"Delegation {task_id} crashed: {exc}")
        # crashed worker reports back instead of leaving the agent waiting
        # for a record that never arrives.
        record = _record(task_id, message, json.dumps({
            "status": "error",
            "type": "gateway",
            "message": str(exc)[:256]
        }, ensure_ascii=False))
    with _lock:
        _completed.append(record)
        _in_flight -= 1


def take_completed() -> str:
    """Drain every delegation record finished since the previous call.

    Returns:
        str: The records joined by newlines, empty when nothing finished.
    """
    global _completed
    with _lock:
        records = _completed
        _completed = []
    return "\n".join(records)


def _record(task_id: str, message: str, result: str) -> str:
    """Render one finished delegation as a single history line.

    Plain `key=value` text rather than JSON: the record is written through
    `swrite`, which doubles embedded quotes and would mangle a JSON envelope.

    Args:
        task_id (str): Identifier the agent saw on acceptance.
        message (str): The delegated task, echoed so the agent can match it.
        result (str): The JSON string produced by `_run`.

    Returns:
        str: One `OPENCLAW_RESULT ...` line.
    """
    try:
        payload = json.loads(result)
    except ValueError as decode_error:
        logger.exception(f"Unreadable delegation result: {decode_error}")
        payload = {"status": "error", "message": result}
    fields = [
        f"OPENCLAW_RESULT id={task_id}",
        f"status={payload.get('status', 'error')}",
    ]
    if payload.get("responseId"):
        fields.append(f"responseId={payload['responseId']}")
    fields.append(f"task={_flatten(message, TASK_ECHO_CHARS)}")
    body = payload.get("reply") or payload.get("message") or ""
    fields.append(f"reply={_flatten(body, MAX_REPLY_CHARS)}")
    return " ".join(fields)


def _flatten(text: str, limit: int) -> str:
    """Collapse text to one quote-free line that survives `swrite`.

    Args:
        text (str): Arbitrary text coming from the Gateway or the agent.
        limit (int): Maximum number of characters to keep.

    Returns:
        str: The trimmed single-line form.
    """
    return " ".join(str(text).replace('"', "'").split())[:limit]


def _run(
    message: str,
    openclaw_url: str,
    openclaw_agent: str
) -> str:
    """Run one delegation to completion and describe its outcome.

    Args:
        message (str): Self-contained natural-language task.
        openclaw_url (str): The base URL of the OpenClaw Gateway.
        openclaw_agent (str): The target agent identifier.

    Returns:
        str: JSON string containing either the OpenClaw reply or an error
             formatted for the agent's context.
    """
    logger.info(f"Delegating a task to OpenClaw agent '{openclaw_agent}'")
    try:
        result = _send_with_startup_retry(
            message=str(message).strip(),
            openclaw_url=str(openclaw_url),
            openclaw_agent=str(openclaw_agent)
        )
    except OpenClawError as gateway_error:
        logger.exception(f"Delegation failed: {gateway_error.msg}")
        return json.dumps({
            "status": "error",
            "type": "gateway",
            "message": gateway_error.msg
        }, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"Unexpected error while delegating to OpenClaw: {exc}")
        return json.dumps({
            "status": "error",
            "type": "gateway",
            "message": str(exc)[:256]
        }, ensure_ascii=False)
    logger.info("Delegation completed")
    return result


def _send_with_startup_retry(
    message: str,
    openclaw_url: str,
    openclaw_agent: str
) -> str:
    """Run one turn, retrying while the Gateway reports it is still starting.

    A Gateway that is still booting answers `503` with an optional
    `Retry-After` hint. That is a retryable condition.

    Args:
        message (str): The task description.
        openclaw_url (str): The base URL.
        openclaw_agent (str): Target agent ID.

    Raises:
        OpenClawError: Propagated from the underlying turn once retries are
            exhausted or the failure is not retryable.

    Returns:
        str: The JSON string produced by `_send`.
    """
    last_error = None
    for attempt in range(STARTUP_RETRY_ATTEMPTS):
        try:
            return _send(
                message=message,
                openclaw_url=openclaw_url,
                openclaw_agent=openclaw_agent
            )
        except OpenClawStartupError as startup_error:
            last_error = startup_error
            if attempt == STARTUP_RETRY_ATTEMPTS - 1:
                break
            wait = min(startup_error.retry_after, STARTUP_RETRY_MAX_WAIT)
            logger.warning(
                f"OpenClaw Gateway is still starting, retrying in {wait}s "
                f"({attempt + 1}/{STARTUP_RETRY_ATTEMPTS}): {startup_error.msg}"
            )
            time.sleep(wait)
    raise last_error or OpenClawError("OpenClaw Gateway unavailable")


def _send(
    message: str,
    openclaw_url: str,
    openclaw_agent: str
) -> str:
    """Post one agent turn to the Gateway and return the result.

    The Gateway responds only once the run reaches a terminal state, so a
    single blocking request covers the whole turn.

    Args:
        message (str): The task description.
        openclaw_url (str): The base URL.
        openclaw_agent (str): Target agent ID.

    Raises:
        OpenClawStartupError: If the Gateway is still booting.
        OpenClawError: If the Gateway is unreachable, authentication fails,
            the request is rejected, or no valid reply is found.

    Returns:
        str: The extracted textual reply formatted as a JSON string.
    """
    endpoint, headers = _request_target(openclaw_url)
    headers["x-openclaw-agent-id"] = openclaw_agent
    logger.debug(f"POST {endpoint} for agent '{openclaw_agent}'")
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                url=endpoint,
                json={
                    "model": MODEL_ROUTE,
                    "input": message,
                },
                headers=headers,
                timeout=SESSION_TIMEOUT,
            )
    except requests.RequestException as request_error:
        raise OpenClawError(
            f"Cannot reach OpenClaw Gateway: {request_error}"
        )
    if not response.ok:
        raise _http_error(response)
    return _extract_reply(response.json())


def _request_target(openclaw_url: str):
    """Pick the HTTP target and headers for one delegation call.

    In Docker, `GATEWAY_URL` (the local Nginx proxy, see proxy/nginx.conf.template)
    is always set: requests go to `{GATEWAY_URL}/openclaw{RESPONSES_PATH}` and
    Nginx injects the Bearer token from its own environment, so this process
    never holds the Gateway token. Without `GATEWAY_URL` (e.g. running outside
    Docker), fall back to talking to `openclaw_url` directly with a token read
    from `OMEGA_OPENCLAW_TOKEN`.

    Args:
        openclaw_url (str): The configured Gateway base URL, used only by the
            direct fallback.

    Raises:
        OpenClawError: If neither transport can authenticate, i.e. there is no
            proxy to inject the token and no token in the environment either.

    Returns:
        tuple[str, dict]: The request URL and the headers to seed (the caller
            still adds `x-openclaw-agent-id`).
    """
    gateway_url = config_get_by_key("GATEWAY_URL")
    if gateway_url:
        logger.debug(f"Using the Nginx proxy at {gateway_url} for OpenClaw")
        return f"{gateway_url.rstrip('/')}/openclaw{RESPONSES_PATH}", {}
    token = _get_token()
    if not token:
        # Sending an empty Bearer would come back as a plain 401, which is
        # indistinguishable from a wrong token. Say what is actually missing.
        raise OpenClawError(
            "No GATEWAY_URL to proxy through and OMEGA_OPENCLAW_TOKEN is "
            "empty, so the request cannot be authenticated"
        )
    logger.debug("No GATEWAY_URL, calling the OpenClaw Gateway directly")
    return _endpoint(openclaw_url), {"Authorization": f"Bearer {token}"}


def _endpoint(openclaw_url: str) -> str:
    """Build the OpenResponses endpoint URL from the configured base URL.

    `ws://` and `wss://` are accepted so that a base URL left over from the
    previous WebSocket transport keeps working.

    Args:
        openclaw_url (str): The configured Gateway base URL.

    Returns:
        str: Absolute URL of the OpenResponses endpoint.
    """
    base = openclaw_url.strip().rstrip("/")
    for ws_scheme, http_scheme in (("wss://", "https://"), ("ws://", "http://")):
        if base.startswith(ws_scheme):
            base = http_scheme + base[len(ws_scheme):]
            break
    return base + RESPONSES_PATH


def _http_error(response: requests.Response) -> OpenClawError:
    """Convert a failed HTTP response into the matching bridge error.

    Rejections carry `{"error": {"message": ..., "type": ...}}`; the HTTP
    reason is used when the body is not that envelope.

    Args:
        response (requests.Response): The failed response.

    Returns:
        OpenClawError: `OpenClawStartupError` for a booting Gateway, a plain
            `OpenClawError` otherwise.
    """
    try:
        error = response.json().get("error", {})
        message = error.get("message") or response.reason
        kind = error.get("type", "")
    except ValueError as decode_error:
        logger.warning(
            f"Gateway error body is not JSON, falling back to the HTTP "
            f"reason: {decode_error}"
        )
        message, kind = response.reason, ""
    message = f"{message} ({kind})" if kind else message
    if response.status_code == 503:
        try:
            retry_after = float(response.headers.get("Retry-After", 1))
        except ValueError as retry_after_error:
            logger.warning(
                f"Unusable Retry-After header, waiting 1s: {retry_after_error}"
            )
            retry_after = 1.0
        return OpenClawStartupError(message, retry_after)
    return OpenClawError(f"HTTP {response.status_code}: {message}")


def _extract_reply(payload: dict) -> str:
    """Extract visible text from the terminal Gateway response payload.

    The reply lives in `output`, whose message items hold `output_text`
    fragments. Non-message items (reasoning, tool calls) carry no visible
    text and are skipped.

    Args:
        payload (dict): The decoded OpenResponses response body.

    Raises:
        OpenClawError: If the response contains no textual reply.

    Returns:
        str: JSON formatted string indicating success and containing the
             combined text.
    """
    texts = [
        fragment.get("text", "")
        for item in payload.get("output", [])
        if isinstance(item, dict) and item.get("type") == "message"
        for fragment in item.get("content", [])
        if isinstance(fragment, dict) and fragment.get("type") == "output_text"
    ]
    reply = "\n".join(text for text in texts if text.strip()).strip()
    if not reply:
        raise OpenClawError(
            f"OpenClaw returned no textual reply; keys={sorted(payload)}"
        )
    return json.dumps({
        "status": "ok",
        "responseId": payload.get("id"),
        "reply": reply,
    }, ensure_ascii=False)
