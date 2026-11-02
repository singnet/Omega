"""Frame composition must use the same structured provider protocol as the loop."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import providers


@pytest.fixture
def relations(monkeypatch):
    # These services are not involved in the provider adapter; keep tests offline.
    monkeypatch.setitem(sys.modules, 'chromadb', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=object))
    monkeypatch.setitem(sys.modules, 'lib_llm_ext', SimpleNamespace())
    path = Path(__file__).resolve().parents[1] / 'plugins/context/frame_relation.py'
    spec = importlib.util.spec_from_file_location('frame_relation_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classifier_returns_json_through_a_dedicated_tool(relations, monkeypatch):
    requests = []
    expected = {'relations': [{'frameID1': 'A', 'frameID2': 'B', 'class': 'FollowUp'}]}
    import json

    def chat(request):
        requests.append(request)
        return providers.LLMResponse().add_tool_call(
            providers.LLMToolCall().with_name('frame_relations').with_id('relation-1')
            .with_arguments({'json': json.dumps(expected)}))

    monkeypatch.setattr(providers, '_llmprovider', SimpleNamespace(chat=chat), raising=False)
    assert relations._call_classifier_llm({'query_frame': {'frameID': 'A'}}) == expected
    assert [tool.name for tool in requests[0].tools] == ['frame_relations']
    assert '"frameID": "A"' in requests[0].messages[-1].content


def test_classifier_rejects_user_facing_tools(relations, monkeypatch):
    def chat(request):
        return providers.LLMResponse().add_tool_call(
            providers.LLMToolCall().with_name('send').with_id('wrong-tool')
            .with_arguments({'content': '{}'}))

    monkeypatch.setattr(providers, '_llmprovider', SimpleNamespace(chat=chat), raising=False)
    with pytest.raises(RuntimeError, match='valid frame_relations'):
        relations._call_selected_llm('classify A and B', 100, 'low')
