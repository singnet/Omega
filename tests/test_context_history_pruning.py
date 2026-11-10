import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "plugins" / "context"))

import frame_helpers
import helper


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


def test_pruned_audit_entry_is_retrievable_by_episodes_timestamp(tmp_path, monkeypatch):
    timestamp = "2026-11-08 12:34:56"
    event = _event("F1", "Observation", "ResultAdded", "Archived weather result", timestamp)
    audit_entry = frame_helpers.cfv2_pruned_audit_entry(event)
    history = tmp_path / "repos" / "Omega" / "memory" / "history.metta"
    history.parent.mkdir(parents=True)
    history.write_text(audit_entry + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    episodes = helper.around_time(timestamp, 20)

    assert "PRUNED_FRAME_EVENT" in episodes
    assert "Archived weather result" in episodes
    assert timestamp in episodes
