"""Text formatting and frame selection helpers for the context plugin."""

import hashlib
import json
import re
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple

from helper import normalize_string

# Consume quoted strings as whole tokens, including an unfinished final string,
# so parentheses in message text never become structural delimiters.
_FORM_TOKENS_RE = re.compile(r'"(?:\\.|[^"\\])*(?:"|\\?\Z)|[()]', re.DOTALL)
_FIELD_HEAD_RE = re.compile(r'\(([^\s()"]+)(?=\s|\()\s*')
_FIELD_VALUE_RE = re.compile(r'"(?:\\.|[^"\\])*"|[^\s()"][^\s)]*', re.DOTALL)

def compact_plain(value, limit=1200):
    """
    Return a compact, single-line summary with a stable digest.
    This does not write files and does not store to LTM.
    MeTTa decides whether to pin/remember the resulting summary.
    """
    text = normalize_string(value)
    compact = re.sub(r"\s+", " ", text).strip()
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    if len(compact) > int(limit):
        compact = compact[: int(limit) - 3].rstrip() + "..."

    return f"sha256:{digest[:16]} chars:{len(text)} excerpt:{compact}"


def _unquote_history_string(value):
    """Remove S-expression quotes and only decode escaped quotes/backslashes."""
    text = str(value)
    if len(text) < 2 or text[0] not in ('"', "'") or text[-1] != text[0]:
        return text
    inner = text[1:-1]
    out = []
    i = 0
    while i < len(inner):
        if inner[i] == "\\" and i + 1 < len(inner) and inner[i + 1] in ('"', "'", "\\"):
            out.append(inner[i + 1])
            i += 2
        else:
            out.append(inner[i])
            i += 1
    return "".join(out)


def _decode_history_text(value):
    """Decode one MeTTa/JSON string value when it is quoted."""
    text = normalize_string(value)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                return decoded
        except (TypeError, ValueError):
            pass
    return _unquote_history_string(text)


def cfv2_history_payload(value, limit=900):
    """Normalize, cap, and JSON-quote a payload for safe MeTTa event storage."""
    text = normalize_string(value).strip()
    text = _unquote_history_string(text)
    text = re.sub(r"\s+", " ", text).strip()
    limit = max(0, int(limit))
    if len(text) <= limit:
        compact = text
    elif limit <= 3:
        compact = text[:limit]
    else:
        compact = text[: limit - 3].rstrip() + "..."
    # The caller stores this value directly in a FrameEvent field. Returning a
    # JSON string literal keeps whitespace and escaped characters parseable
    # without routing the payload through MeTTa's swrite function.
    return json.dumps(compact, ensure_ascii=False)


def cfv2_compact_history(events_repr, limit=2400):
    """Format the newest frame events into a plain-text summary within `limit`."""
    limit = max(0, int(limit))
    if limit == 0:
        return ""

    events = _balanced_exprs(normalize_string(events_repr), "FrameEvent")
    lines = []
    for event in events:
        fields = _fields(event, "category", "kind", "timestamp", "payload")
        category = fields.get("category") or "Event"
        kind = fields.get("kind") or category
        timestamp = fields.get("timestamp") or ""
        payload = fields.get("payload") or ""
        timestamp = _unquote_history_string(timestamp)
        if len(payload) >= 2 and payload[0] == '"' and payload[-1] == '"':
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = _unquote_history_string(payload)
        else:
            payload = _unquote_history_string(payload)
        payload = re.sub(r"\s+", " ", payload).strip()
        stamp = f" [{timestamp}]" if timestamp else ""
        lines.append(f"{category}/{kind}{stamp}: {payload}")

    # Preserve recent context first when space is limited, but render the result
    # in chronological order for readability.
    selected = []
    used = 0
    for line in reversed(lines):
        separator = 1 if selected else 0
        remaining = limit - used - separator
        if remaining <= 0:
            break
        if len(line) > remaining:
            # Older events should be omitted rather than included as a broken
            # fragment. If the newest event alone exceeds the limit, retain its
            # header and end the payload with an ellipsis at a word boundary.
            if selected:
                break
            header, delimiter, payload = line.partition(": ")
            marker = "..."
            payload_budget = remaining - len(header) - len(delimiter) - len(marker)
            if not delimiter or payload_budget <= 0:
                break
            excerpt = payload[:payload_budget].rstrip()
            if len(excerpt) < len(payload):
                excerpt = excerpt.rsplit(" ", 1)[0] if " " in excerpt else ""
            line = f"{header}: {excerpt}{marker}"
        selected.append(line)
        used += len(line) + separator
    selected.reverse()
    return "\n".join(selected)


def _summary_parts(summary):
    """Read the stable labeled sections of a prior pruning rollup."""
    text = _decode_history_text(summary)
    parts = {"directive": "", "decisions": [], "outcomes": []}
    labels = {
        "Original directive: ": "directive",
        "Key decisions: ": "decisions",
        "Outcomes: ": "outcomes",
    }
    for line in text.splitlines():
        for prefix, name in labels.items():
            if line.startswith(prefix):
                value = line[len(prefix):].strip()
                if name == "directive":
                    parts[name] = "" if value == "(not recorded)" else value
                elif value:
                    parts[name] = [
                        item.strip()
                        for item in value.split(" | ")
                        if item.strip() and item.strip() != "(none recorded)"
                    ]
                break
    return parts


def _clip_summary(value, limit):
    value = re.sub(r"\s+", " ", str(value)).strip()
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    excerpt = value[:limit - 3].rsplit(" ", 1)[0].rstrip()
    return (excerpt or value[:limit - 3]) + "..."


def cfv2_pruned_event_timestamp(pruned_events_repr, position):
    """Return the first or last timestamp from the pruned events in source order."""
    events = _balanced_exprs(normalize_string(pruned_events_repr), "FrameEvent")
    if not events:
        return ""
    selected = events[0] if _unquote_history_string(position) == "First" else events[-1]
    return _unquote_history_string(_fields(selected, "timestamp").get("timestamp", ""))


def cfv2_update_pruning_summary(
    previous_summary_repr,
    pruned_events_repr,
    omitted_from,
    omitted_to,
    omitted_count,
    summary_limit=1200,
):
    """Roll pruned events into a bounded, useful per-frame summary."""
    limit = max(0, int(summary_limit))
    if limit == 0:
        return ""

    previous = _summary_parts(previous_summary_repr)
    directive = previous["directive"]
    decisions = previous["decisions"]
    outcomes = previous["outcomes"]
    events = _balanced_exprs(normalize_string(pruned_events_repr), "FrameEvent")
    timestamps = [
        _unquote_history_string(_fields(event, "timestamp").get("timestamp", ""))
        for event in events
    ]
    timestamps = [timestamp for timestamp in timestamps if timestamp]
    range_from = _decode_history_text(omitted_from) or (timestamps[0] if timestamps else "")
    range_to = _decode_history_text(omitted_to) or (timestamps[-1] if timestamps else range_from)
    for event in events:
        fields = _fields(event, "category", "kind", "payload")
        category = _unquote_history_string(fields.get("category", ""))
        kind = _unquote_history_string(fields.get("kind", ""))
        payload = fields.get("payload", "")
        if len(payload) >= 2 and payload[0] == '"' and payload[-1] == '"':
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = _unquote_history_string(payload)
        else:
            payload = _unquote_history_string(payload)
        payload = re.sub(r"\s+", " ", payload).strip()
        if category == "Directive" and kind == "UserDirective" and not directive:
            directive = payload
        elif category == "StateChange" or (category == "Directive" and kind == "AgentDirective"):
            decisions.append(f"{kind}: {payload}" if kind else payload)
        elif category in ("Observation", "Execution") or (
            category == "Lifecycle" and kind in ("FrameCompleted", "FrameFailed")
        ):
            outcomes.append(f"{kind}: {payload}" if kind else payload)

    # Keep the original directive and the most recent distinct decisions and
    # outcomes. Their fields are clipped below, so this stays bounded over time.
    decisions = list(dict.fromkeys(item for item in decisions if item))[-3:]
    outcomes = list(dict.fromkeys(item for item in outcomes if item))[-3:]
    notice = (
        f"PRUNED HISTORY: {int(omitted_count)} events omitted from "
        f"{range_from} through {range_to}. "
        f'Retrieve details with episodes "{range_from}" '
        "(timestamp format YYYY-MM-DD HH:MM:SS)."
    )
    labels = ["Original directive: ", "Key decisions: ", "Outcomes: "]
    separators = 3  # three line breaks
    available = max(0, limit - len(notice) - separators - sum(map(len, labels)))
    budgets = [int(available * 0.40), int(available * 0.32), 0]
    budgets[2] = available - budgets[0] - budgets[1]
    directive_text = _clip_summary(directive, budgets[0]) if directive else "(not recorded)"
    decision_text = " | ".join(decisions) or "(none recorded)"
    outcome_text = " | ".join(outcomes) or "(none recorded)"
    rendered = "\n".join((
        notice,
        labels[0] + directive_text,
        labels[1] + _clip_summary(decision_text, budgets[1]),
        labels[2] + _clip_summary(outcome_text, budgets[2]),
    ))
    if len(rendered) <= limit:
        return rendered
    return _clip_summary(rendered, limit)


def cfv2_compact_frame_history(events_repr, pruning_summary_repr, limit=2400):
    """Render the pruning notice/rollup and recent events within one cap."""
    limit = max(0, int(limit))
    summary = _decode_history_text(pruning_summary_repr).strip()
    if not summary:
        return cfv2_compact_history(events_repr, limit)
    if len(summary) >= limit:
        return _clip_summary(summary, limit)
    recent = cfv2_compact_history(events_repr, limit - len(summary) - 1)
    return summary if not recent else summary + "\n" + recent


def cfv2_pruned_audit_entry(event_repr):
    """Format a pruned event as a timestamped line readable by `episodes`."""
    event = _balanced_exprs(normalize_string(event_repr), "FrameEvent")
    if not event:
        return ""
    timestamp = _unquote_history_string(_fields(event[0], "timestamp").get("timestamp", ""))
    if not timestamp:
        return ""
    return f'({json.dumps(timestamp)}\nPRUNED_FRAME_EVENT: {event[0]}\n)'


def cfv2_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _unescape_repr_id(value: str) -> str:
    value = str(value).strip()
    value = value.replace("'", "").replace('"', "")
    value = value.replace("[", "").replace("]", "")
    return value.strip()


def _form_spans(text: str, offset: int = 0) -> Iterator[Tuple[int, int, int]]:
    """Yield balanced forms as (start, end, depth), ignoring quoted contents."""
    starts = []
    depth = 0
    for token in _FORM_TOKENS_RE.finditer(text, offset):
        if token[0] == "(":
            starts.append((token.start(), depth))
            depth += 1
        elif token[0] == ")":
            depth -= 1
            if starts:
                start, form_depth = starts.pop()
                yield start, token.end(), form_depth


def _balanced_exprs(text: str, head: str) -> List[str]:
    """Extract matching forms in source order, excluding nested matches."""
    text = str(text)
    token = f"({head}"
    matches = []
    for start, end, _ in _form_spans(text):
        after_head = start + len(token)
        if (
            text.startswith(token, start)
            and after_head < end
            and (text[after_head].isspace() or text[after_head] == "(")
        ):
            matches.append((start, end))

    out = []
    previous_end = 0
    for start, end in sorted(matches):
        if start >= previous_end:
            out.append(text[start:end])
            previous_end = end
    return out


def _field_value(expr: str, start: int) -> Optional[str]:
    """Read one quoted, nested, or bare value without decoding it."""
    if expr.startswith("(", start):
        end = next((end for _, end, depth in _form_spans(expr, start) if depth == 0), None)
        return expr[start:end] if end is not None else None
    value = _FIELD_VALUE_RE.match(expr, start)
    if value is not None:
        return value[0]
    return "" if start < len(expr) and expr[start] != '"' else None


def _fields(expr: str, *field_names: str) -> Dict[str, str]:
    """Read requested direct-child fields once, keeping each name's first value."""
    expr = str(expr)
    fields = {}
    remaining = set(field_names)
    depth = 0
    for token in _FORM_TOKENS_RE.finditer(expr):
        if token[0] == ")":
            depth -= 1
            continue
        if token[0] != "(":
            continue
        depth += 1
        if depth != 2:
            continue
        head = _FIELD_HEAD_RE.match(expr, token.start())
        if head is None or head[1] not in remaining:
            continue
        name = head[1]
        value = _field_value(expr, head.end())
        if value is not None:
            fields[name] = value
        remaining.remove(name)
        if not remaining:
            break
    return fields


def _field(expr: str, field_name: str) -> Optional[str]:
    """Return the raw value of a direct child `(field value)` form."""
    return _fields(expr, field_name).get(field_name)


def cfv2_refs_completed_after(index_repr, date_prefix) -> str:
    """Return completed FrameRefs whose completed-timestamp starts with or compares after date_prefix.

    date_prefix can be YYYY-MM-DD or a longer timestamp prefix. This is intentionally simple.
    """
    prefix = _unescape_repr_id(date_prefix)
    refs = []
    for ref in _balanced_exprs(str(index_repr), "FrameRef"):
        fields = _fields(ref, "status", "completed-timestamp")
        status = _unescape_repr_id(fields.get("status") or "")
        t = _unescape_repr_id(fields.get("completed-timestamp") or "")
        if status == "Completed" and t and t >= prefix:
            refs.append(ref)
    return "(" + " ".join(refs) + ")"


def cfv2_select_next_frame_id(index_repr, root_mode="Fast") -> str:
    """Select highest-priority active frame matching root mode from FrameRef space.

    If multiple FrameRefs exist for a frame, the last one wins. This supports append-only refs.
    """
    mode = _unescape_repr_id(root_mode)
    latest: Dict[str, Tuple[float, str, str, str]] = {}
    for ref in _balanced_exprs(str(index_repr), "FrameRef"):
        fields = _fields(ref, "frameID", "status", "frame-mode", "space", "priority")
        fid = _unescape_repr_id(fields.get("frameID") or "")
        status = _unescape_repr_id(fields.get("status") or "")
        frame_mode = _unescape_repr_id(fields.get("frame-mode") or "")
        space = _unescape_repr_id(fields.get("space") or "")
        priority_raw = _unescape_repr_id(fields.get("priority") or "0")
        try:
            priority = float(priority_raw)
        except Exception:
            priority = 0.0
        if fid:
            latest[fid] = (priority, status, frame_mode, space)

    best_id = "NON"
    best_priority = float("-inf")
    for fid, (priority, status, frame_mode, space) in latest.items():
        if space == "Active" and status in {"Active", "Focused"} and frame_mode == mode:
            if priority > best_priority:
                best_priority = priority
                best_id = fid
    return best_id
