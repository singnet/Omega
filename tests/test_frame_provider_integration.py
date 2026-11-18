"""Frame classification uses the configured provider without agent tool calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import providers


@pytest.fixture
def relations(monkeypatch):
    # These services are not involved in the provider adapter; keep tests offline.
    monkeypatch.setitem(sys.modules, 'chromadb', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=object))
    monkeypatch.setitem(sys.modules, 'lib_llm_ext', Mock())
    path = Path(__file__).resolve().parents[1] / 'plugins/context/frame_relation.py'
    spec = importlib.util.spec_from_file_location('frame_relation_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'config_get_by_key', lambda key, default=None: default)
    return module


def _select_provider(monkeypatch, relations, api, response=None, error=None):
    client = Mock()
    create = client.responses.create if api == 'input' else client.chat.completions.create
    create.return_value = response
    create.side_effect = error
    delegate = SimpleNamespace(
        name='ConfiguredProvider', _client=None, _ensure_client=Mock(),
        convert_request=Mock(return_value={
            'model': 'configured-model', api: 'converted messages',
            'reasoning': {'effort': 'low'},
            'tools': [], 'tool_choice': 'required',
        }),
    )
    delegate._ensure_client.side_effect = lambda: setattr(delegate, '_client', client)
    monkeypatch.setattr(providers, '_llmprovider', SimpleNamespace(delegate=delegate), raising=False)
    monkeypatch.setattr(relations.lib_llm_ext, '_retrying', lambda call, provider: call(), raising=False)
    return delegate, create


@pytest.mark.parametrize('api', ['messages', 'input'])
def test_classifier_reads_json_from_the_configured_client(relations, monkeypatch, api):
    expected = {'relations': [{'frameID1': 'A', 'frameID2': 'B', 'class': 'FollowUp',
                               'reason': 'Continues the prior work', 'confidence': 0.9}]}
    text = json.dumps(expected)
    if api == 'input':
        response = SimpleNamespace(output=[
            SimpleNamespace(type='reasoning', content=[]),
            SimpleNamespace(type='message', content=[
                SimpleNamespace(type='output_text', text=text)]),
        ])
    else:
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=text, tool_calls=[]))])
    delegate, create = _select_provider(monkeypatch, relations, api, response)
    settings = {'maxOutputToken': 100, 'reasoningMode': 'low'}
    monkeypatch.setattr(relations, 'config_get_by_key',
                        lambda key, default=None: settings.get(key, default))

    assert relations._call_classifier_llm({'query_frame': {'frameID': 'A'}}) == expected
    delegate._ensure_client.assert_called_once()
    request = delegate.convert_request.call_args.args[0]
    assert request.tools == []
    assert request.max_tokens == 100
    assert request.reasoning_mode == 'low'
    assert '"frameID": "A"' in request.messages[-1].content
    create.assert_called_once_with(**{
        'model': 'configured-model', api: 'converted messages', 'reasoning': {'effort': 'low'},
    })
    assert delegate.convert_request.return_value['tools'] == []
    assert delegate.convert_request.return_value['tool_choice'] == 'required'


@pytest.mark.parametrize('api,response', [
    ('messages', SimpleNamespace(choices=[])),
    ('messages', SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])),
    ('messages', SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='  '))])),
    ('messages', SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=42))])),
    ('input', SimpleNamespace(output=[])),
    ('input', SimpleNamespace(output=[SimpleNamespace(type='reasoning', content=[])])),
])
def test_classifier_rejects_missing_text(relations, monkeypatch, api, response):
    _select_provider(monkeypatch, relations, api, response)
    with pytest.raises(RuntimeError):
        relations._call_selected_llm('classify A and B', 100, 'low')


def test_classifier_reports_client_errors_without_agent_tools(relations, monkeypatch):
    _select_provider(monkeypatch, relations, 'messages', error=TimeoutError('request timed out'))
    with pytest.raises(RuntimeError, match='request timed out'):
        relations._call_selected_llm('classify A and B', 100, 'low')


def test_classifier_reports_unsupported_provider(relations, monkeypatch):
    monkeypatch.setattr(providers, '_llmprovider', SimpleNamespace(), raising=False)
    with pytest.raises(RuntimeError):
        relations._call_selected_llm('classify A and B', 100, 'low')


@pytest.mark.parametrize('content', [None, '[]'])
def test_classification_failure_returns_no_relations_and_logs(relations, monkeypatch, caplog, content):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    _select_provider(monkeypatch, relations, 'messages', response)
    monkeypatch.setattr(relations, '_upsert_changed_frames', lambda frames, provider: {'A': [1.0]})
    monkeypatch.setattr(relations, '_search_top_k', lambda *args: [
        {'frameID': 'B', 'distance': 0.1, 'document': 'candidate', 'metadata': {}},
    ])

    with caplog.at_level('WARNING'):
        result = relations.cfv2_compose_frame_relations(
            '((Frame (frameID A) (status Active) (deliverable "new task")))',
            'A', '(FollowUp Unrelated)', 'Local',
        )

    assert result == '()'
    assert 'classification failed' in caplog.text.lower()


@pytest.mark.parametrize('query_id', ['OTHER_QUERY', None, 'A!'])
def test_classifier_rejects_incorrect_query_ids(relations, monkeypatch, query_id):
    item = {'frameID2': 'B', 'class': 'FollowUp', 'reason': 'related', 'confidence': 0.9}
    if query_id is not None:
        item['frameID1'] = query_id
    monkeypatch.setattr(relations, '_call_classifier_llm', lambda payload: {'relations': [item]})
    query = relations._parse_frame_sketches('(Frame (frameID A) (status Active))')[0]
    hits = [{'frameID': 'B', 'distance': 0.1, 'document': 'candidate', 'metadata': {}}]

    with pytest.raises(ValueError, match='query frame ID'):
        relations._classify_relations(query, hits, ['FollowUp', 'Unrelated'])


def test_classifier_uses_current_candidate_snapshots_without_reindexing(relations, monkeypatch):
    relation = {'frameID1': 'A', 'frameID2': 'B', 'class': 'FollowUp',
                'reason': 'related', 'confidence': 0.9}
    classifier = Mock(return_value={'relations': [relation]})
    monkeypatch.setattr(relations, '_call_classifier_llm', classifier)
    hits = [
        {'frameID': frame_id, 'distance': distance, 'document': 'stored sketch',
         'metadata': {'status': 'Active', 'contentHash': 'stored hash'}}
        for frame_id, distance in [('B', 0.1), ('C', 0.2), ('H', 0.3)]
    ]
    original_hits = deepcopy(hits)
    upsert = Mock(return_value={'A': [1.0]})
    search = Mock(return_value=hits)
    monkeypatch.setattr(relations, '_upsert_changed_frames', upsert)
    monkeypatch.setattr(relations, '_search_top_k', search)
    snapshots = '''(
        (Frame (frameID B) (status Active) (results "stored runtime result"))
        (Frame (frameID C) (status Completed) (results "finished result"))
        (Frame (frameID X) (status Active) (results "not retrieved"))
        (Frame (frameID B) (status Active) (priority 3) (results "latest hot result")))'''

    result = relations.cfv2_compose_frame_relations(
        '(Frame (frameID A) (status Active) (deliverable "new task"))',
        'A', '(FollowUp Unrelated)', 'Local', 5, snapshots,
    )
    assert '(FrameID-1 A) (FrameID-2 B)' in result

    candidates = classifier.call_args.args[0]['candidate_frames']
    assert [candidate['frameID'] for candidate in candidates] == ['B', 'C', 'H']
    hot, completed, historical = candidates
    assert 'latest hot result' in hot['document']
    assert hot['metadata']['priority'] == 3.0
    assert 'contentHash' not in hot['metadata']
    assert '(status Completed)' in completed['document']
    assert 'finished result' in completed['document']
    assert completed['metadata']['status'] == 'Completed'
    assert historical == original_hits[2]
    assert hits == original_hits
    upsert.assert_called_once()
    frames, provider = upsert.call_args.args
    assert [frame['frameID'] for frame in frames] == ['A']
    assert provider == 'Local'
    search.assert_called_once_with(frames[0], [1.0], 'Local', 5)
