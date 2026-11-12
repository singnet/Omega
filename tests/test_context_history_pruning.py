import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "plugins" / "context"))

import frame_helpers
import helper


@pytest.fixture
def history_file(tmp_path, monkeypatch):
    path = tmp_path / "repos" / "Omega" / "memory" / "history.metta"
    path.parent.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return path


def _episode_pages(timestamp, radius, max_chars=50000):
    pages = []
    seen = set()
    query = timestamp
    while True:
        assert query not in seen, "episodes must advance its continuation cursor"
        seen.add(query)
        page = helper.around_time(query, radius, max_chars)
        assert page
        assert len(page.partition("\nMORE HISTORY:")[0].splitlines()) <= 2 * radius + 1
        assert len("SUCCESS, RETURN: " + str([page])) <= max_chars
        pages.append(page)
        continuation = re.search(r'^MORE HISTORY: \(episodes "([^"]+)"\)$', page, re.MULTILINE)
        if not continuation:
            return pages
        query = continuation.group(1)


def _event(frame_id, category, kind, payload, timestamp):
    return (
        f'(FrameEvent (frameID {frame_id}) (category {category}) (kind {kind}) '
        f'(payload {json.dumps(payload)}) (timestamp {json.dumps(timestamp)}))'
    )


def test_pruning_rollup_preserves_directive_decisions_outcomes_and_is_bounded():
    directive = _event(
        "F1", "Directive", "UserDirective", "Research the weather impacts", "2026-11-08 10:00:00"
    )
    decision = _event(
        "F1", "StateChange", "HypothesisAdded", "Rain is likely in the afternoon", "2026-11-08 10:01:00"
    )
    outcome = _event(
        "F1", "Observation", "ResultAdded", "Forecast confirmed rain", "2026-11-08 10:02:00"
    )
    execution = _event(
        "F1", "Execution", "CommandBatch", "SearchWeather returned rain", "2026-11-08 10:03:00"
    )

    assert frame_helpers.cfv2_pruned_event_timestamp(f"({directive} {decision})", "First") == "2026-11-08 10:00:00"
    assert frame_helpers.cfv2_pruned_event_timestamp(f"({directive} {decision})", "Last") == "2026-11-08 10:01:00"

    summary = frame_helpers.cfv2_update_pruning_summary(
        '""', f"({directive})", '"2026-11-08 10:00:00"',
        '"2026-11-08 10:00:00"', 1, 1200,
    )
    summary = frame_helpers.cfv2_update_pruning_summary(
        json.dumps(summary), f"({decision} {outcome} {execution})", '"2026-11-08 10:00:00"',
        '"2026-11-08 10:03:00"', 4, 1200,
    )

    assert "Original directive: Research the weather impacts" in summary
    assert "HypothesisAdded: Rain is likely" in summary
    assert "ResultAdded: Forecast confirmed rain" in summary
    assert "CommandBatch: SearchWeather returned rain" in summary
    assert "2026-11-08 10:00:00 through 2026-11-08 10:03:00" in summary
    assert 'episodes "2026-11-08 10:00:00"' in summary
    assert len(summary) <= 1200

    for index in range(20):
        expected_to = f"2026-11-08 10:{index + 3:02d}:00"
        next_event = _event(
            "F1", "StateChange", "ConstraintAdded", f"Constraint detail {index}",
            expected_to,
        )
        summary = frame_helpers.cfv2_update_pruning_summary(
            json.dumps(summary), f"({next_event})", '"2026-11-08 10:00:00"',
            json.dumps(expected_to), index + 4, 1200,
        )
        assert f"through {expected_to}" in summary
        assert len(summary) <= 1200
        assert "Original directive: Research the weather impacts" in summary


def test_repeated_pruning_preserves_autonomous_frame_originating_directive():
    directive = _event(
        "F-autonomous", "Directive", "AgentDirective",
        "Investigate autonomous memory cleanup", "2026-11-08 13:00:00",
    )
    summary = frame_helpers.cfv2_update_pruning_summary(
        '""', f"({directive})", '"2026-11-08 13:00:00"',
        '"2026-11-08 13:00:00"', 1, 1200,
    )
    assert "Original directive: Investigate autonomous memory cleanup" in summary

    for index in range(12):
        timestamp = f"2026-11-08 13:{index + 1:02d}:00"
        decision = _event(
            "F-autonomous", "StateChange", "HypothesisAdded",
            f"Autonomous decision {index}", timestamp,
        )
        summary = frame_helpers.cfv2_update_pruning_summary(
            json.dumps(summary), f"({decision})", '"2026-11-08 13:00:00"',
            json.dumps(timestamp), index + 2, 1200,
        )

    assert "Original directive: Investigate autonomous memory cleanup" in summary
    assert "AgentDirective:" not in summary
    assert "HypothesisAdded: Autonomous decision 11" in summary
    assert len(summary) <= 1200


def test_summary_budget_keeps_newest_decision_and_outcome():
    timestamp = "2026-11-08 14:00:00"
    events = [
        _event("F1", "StateChange", "HypothesisAdded", "Old decision A " + "x" * 220, timestamp),
        _event("F1", "StateChange", "ConstraintAdded", "Old decision B " + "x" * 220, timestamp),
        _event("F1", "StateChange", "MethodCertified", "NewestDecision", timestamp),
        _event("F1", "Observation", "ResultAdded", "Old outcome A " + "y" * 220, timestamp),
        _event("F1", "Execution", "CommandBatch", "Old outcome B " + "y" * 220, timestamp),
        _event("F1", "Observation", "ExternalInput", "NewestOutcome", timestamp),
    ]

    summary = frame_helpers.cfv2_update_pruning_summary(
        '""', f"({' '.join(events)})", json.dumps(timestamp), json.dumps(timestamp), 6, 500,
    )

    assert "MethodCertified: NewestDecision" in summary
    assert "ExternalInput: NewestOutcome" in summary
    assert "Old decision A" not in summary
    assert "Old outcome A" not in summary
    assert len(summary) <= 500


def test_frame_history_summary_respects_limit_and_keeps_pruning_notice():
    recent = _event(
        "F1", "Observation", "ResultAdded", "A recent useful finding", "2026-11-08 11:00:00"
    )
    notice = (
        'PRUNED HISTORY: 3 events omitted from 2026-11-08 10:00:00 through '
        '2026-11-08 10:30:00. Retrieve details with episodes "2026-11-08 10:00:00".'
    )
    rendered = frame_helpers.cfv2_compact_frame_history(f"({recent})", json.dumps(notice), 2400)
    assert rendered.startswith("PRUNED HISTORY:")
    assert "A recent useful finding" in rendered
    assert len(rendered) <= 2400


def test_pruned_audit_entry_is_retrievable_by_episodes_timestamp(history_file):
    timestamp = "2026-11-08 12:34:56"
    event = _event("F1", "Observation", "ResultAdded", "Archived weather result", timestamp)
    audit_entry = frame_helpers.cfv2_pruned_audit_entry(event)
    history_file.write_text(audit_entry + "\n", encoding="utf-8")

    episodes = helper.around_time(timestamp, 20)

    assert "PRUNED_FRAME_EVENT" in episodes
    assert "Archived weather result" in episodes
    assert timestamp in episodes


@pytest.mark.parametrize("count,radius,max_chars,original", [
    (1, 1, 50000, "Earlier ordinary entry"),
    (100, 20, 50000, "Earlier ordinary entry"),
    (1, 20, 1024, "original detail " * 800 + "ORIGINAL_AUDIT_TAIL_MARKER"),
    (1, 20, 1024, "'\"\\\t☃\u2028" * 800 + "ORIGINAL_AUDIT_TAIL_MARKER"),
])
def test_episodes_retrieves_original_and_all_same_timestamp_archives_in_bounded_pages(
    history_file, count, radius, max_chars, original,
):
    timestamp = "2026-11-08 12:34:56"
    entries = [
        frame_helpers.cfv2_pruned_audit_entry(
            _event(f"F{index}", "Observation", "ResultAdded", f"Archived-{index:03d} " + "x" * 840, timestamp)
        )
        for index in range(count)
    ]
    history_file.write_text(
        f'({json.dumps(timestamp)}\n{original}\n)\n'
        + "unrelated filler\n" * 50
        + "\n".join(entries)
        + "\n",
        encoding="utf-8",
    )

    pages = _episode_pages(timestamp, radius, max_chars)
    recovered = "".join(page.partition("\nMORE HISTORY:")[0] for page in pages)

    assert len(pages) > 1
    assert original in recovered
    assert re.findall(r"Archived-\d{3}", recovered) == [f"Archived-{index:03d}" for index in range(count)]


def test_episodes_keeps_nearest_timestamp_neighborhood(history_file):
    history_file.write_text(
        '("2026-11-08 12:34:00"\nOlder ordinary detail\n)\n'
        '("2026-11-08 12:34:50"\nNearest ordinary detail\n)\n',
        encoding="utf-8",
    )

    assert helper.around_time('"2026-11-08 12:34:51"', 1) == (
        '3:)\n4:("2026-11-08 12:34:50"\n5:Nearest ordinary detail\n'
    )


@pytest.mark.parametrize("history", ["", "History without a timestamp\n"])
def test_episodes_returns_none_without_timestamped_history(history_file, history):
    history_file.write_text(history, encoding="utf-8")

    assert helper.around_time("2026-11-08 12:34:56", 20) is None
