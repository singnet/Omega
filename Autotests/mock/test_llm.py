import pytest

from llm import *
from rpc import LOCALHOST
from providers import *

TEST_ADDRESS = (LOCALHOST, 9767)

FRAME = "Frame-20260729T144803343500Z"
OTHER_FRAME = "Frame-20260729T144839020270Z"
SIGNAL = "NEW_INPUT_HAS_BEEN_ADMITTED_AS_ACTIVE_FRAME."


def frame_prompt(deliverable, frame=FRAME, signal=SIGNAL):
    return (
        "PROMPT: You are a OmegaClaw agentic harness in a continuous loop._newline_"
        "RUNTIME-PROMPT: The current frame is the authoritative task state._newline_"
        "CURRENT_CONTEXT_FRAME_S_EXPR: (ContextProjection (RootFrame (RootFrame RootFrame-1 "
        f"(current-frame-id {frame}) (last-admitted-frame-id {frame}) (mode Fast))) "
        f"(CurrentFrame (Frame (frameID {frame}) (parent-frameID ()) (source UserDirective) "
        "(priority 1.0) (status Active) (frame-mode Fast) "
        f"(history-summary sha256:a48d311b2a4172dc chars:{len(deliverable)} excerpt:{deliverable}) "
        f"(deliverables ({deliverable})) (results ()))))_newline_"
        "SKILLS: - Remember a particular string: remember string_newline_"
        "OUTPUT_FORMAT: Up to 5 lines_newline_"
        "TIME: 2026-07-29 14:48:03"
        f":-:-:-:{signal}"
    )

class TestLlmMock:

    def setup_class(cls):
        import logging
        import threading

        def thread_id_filter(record):
            record.thread_id = threading.get_native_id()
            return record

        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] [%(thread_id)d]: %(message)s'))
        handler.addFilter(thread_id_filter)
        logging.getLogger().handlers.clear()
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)

    @pytest.fixture
    def agent(self):
        agent = LlmMockAgent(TEST_ADDRESS)
        yield agent
        agent.stop(5)

    @pytest.fixture
    def controller(self):
        controller = LlmMockController(TEST_ADDRESS)
        yield controller
        controller.stop(5)

    def test_response(self, agent, controller):
        assert controller.set_answer("hello", _llm_response_json("world"))
        assert agent.chat(_llm_request('test: hello')) == _llm_response("world")

    def test_test_restart(self, agent):
        controller = LlmMockController(TEST_ADDRESS)
        assert controller.set_answer("hello", _llm_response_json("world"))
        assert agent.chat(_llm_request('test: hello')) == _llm_response("world")
        controller.stop(5)
        controller = LlmMockController(TEST_ADDRESS)
        assert controller.set_answer("hello", _llm_response_json("earth"))
        assert agent.chat(_llm_request('test: hello')) == _llm_response("earth")
        controller.stop(5)

    def test_no_message(self, agent, controller):
        assert controller.set_answer("hello", _llm_response_json("world"))
        assert agent.chat(_llm_request("DO NOT RE-SEND OR SPAM!")) == LLMResponse()

    def test_step_prefix_before_sender(self, agent, controller):
        assert controller.set_answer("hello", _llm_response_json("world"))
        msg = "Step 2026-09-24 15:12:23: <@U0B6ML16Q84> (OmegaClaw Driver): hello"
        assert agent.chat(_llm_request(msg)) == _llm_response("world")

    def test_step_prefix_without_sender(self, agent, controller):
        assert controller.set_answer("hello", _llm_response_json("world"))
        msg = "Step 2026-09-24 15:12:23: hello"
        assert agent.chat(_llm_request(msg)) == _llm_response("world")

    def test_clear_answer(self, agent, controller):
        assert controller.set_answer("hello", _llm_response_json("world"))
        assert agent.chat(_llm_request('test: hello')) == _llm_response("world")
        assert controller.clear_answer("hello")
        assert agent.chat(_llm_request('test: hello')) == LLMResponse()

    def test_clear_answer_keeps_other_answers(self, agent, controller):
        assert controller.set_answer("hello", _llm_response_json("world"))
        assert controller.set_answer("bye", _llm_response_json("earth"))
        assert controller.clear_answer("hello")
        assert agent.chat(_llm_request('test: bye')) == _llm_response("earth")

    def test_clear_unknown_answer(self, agent, controller):
        assert controller.clear_answer("never set")

    def test_context_manager(self, agent):
        with llm_mock_controller(address=TEST_ADDRESS) as controller:
            assert controller.set_answer("hello", _llm_response_json("world"))
            assert agent.chat(_llm_request('test: hello')) == _llm_response("world")

    def test_context_manager_timeout(self, agent):
        address = (TEST_ADDRESS[0], TEST_ADDRESS[1] + 1)
        try:
            with llm_mock_controller(address=address, timeout=2) as controller:
                assert False
        except RuntimeError as e:
            assert e.args == ("Agent didn't answered in 2 seconds",)

    def test_iteration_without_message_is_silent(self, agent, controller, capsys):
        assert controller.set_answer("hello", "world")
        capsys.readouterr()

        assert agent.chat("PROMPT: nothing new here:-:-:-:") == ""

        assert "Mock doesn't have answer" not in capsys.readouterr().out

    def test_missing_answer_is_reported_with_the_message(self, agent, controller, capsys):
        assert controller.set_answer("hello", "world")
        capsys.readouterr()

        assert agent.chat(":-:-:-:['HUMAN-MSG', 'test: goodbye']") == ""

        assert "Mock doesn't have answer for: test: goodbye" in capsys.readouterr().out

    def test_reset_drops_answers(self, agent, controller):
        assert controller.set_answer("hello", "world")
        assert agent.chat(":-:-:-:['HUMAN-MSG', 'test: hello']") == "world"
        assert controller.reset()
        assert agent.chat(":-:-:-:['HUMAN-MSG', 'test: hello']") == ""


class TestLlmMockContextFrames:

    @pytest.fixture
    def agent(self):
        agent = LlmMockAgent(TEST_ADDRESS)
        yield agent
        agent.stop(5)

    @pytest.fixture
    def controller(self):
        controller = LlmMockController(TEST_ADDRESS)
        yield controller
        controller.stop(5)

    def test_answer_matched_against_current_frame(self, agent, controller):
        request = "[REQ-1] please write Hello into /tmp/hello.txt"
        assert controller.set_answer(request, '(write-file "/tmp/hello.txt" "Hello")')

        answer = agent.chat(frame_prompt(request))

        assert answer.startswith('(write-file "/tmp/hello.txt" "Hello")')

    def test_answer_completes_the_frame(self, agent, controller):
        request = "[REQ-2] send Done"
        assert controller.set_answer(request, '(send "Done")')

        answer = agent.chat(frame_prompt(request))

        assert answer == f'(send "Done") {FRAME_COMPLETION_ANSWER}'

    def test_own_completion_is_not_duplicated(self, agent, controller):
        request = "[REQ-3] send Done"
        response = '(send "Done") (complete-goals-ltm "kept for later")'
        assert controller.set_answer(request, response)

        assert agent.chat(frame_prompt(request)) == response

    def test_frame_kept_open_when_test_asks_for_it(self, agent, controller):
        request = "[REQ-4] send Done"
        assert controller.set_answer(request, '(send "Done")', complete_frame=False)

        assert agent.chat(frame_prompt(request)) == '(send "Done")'

    def test_answer_is_served_once_then_frame_is_drained(self, agent, controller):
        request = "[REQ-5] send Done"
        assert controller.set_answer(request, '(send "Done")')
        prompt = frame_prompt(request)

        first = agent.chat(prompt)
        second = agent.chat(prompt)
        third = agent.chat(prompt)
        fourth = agent.chat(prompt)

        assert first.startswith('(send "Done")')
        assert second == FRAME_COMPLETION_ANSWER
        assert third == FRAME_COMPLETION_ANSWER
        assert fourth == ""

    def test_same_request_in_a_new_frame_is_answered_again(self, agent, controller):
        request = "[REQ-6] send Done"
        assert controller.set_answer(request, '(send "Done")')

        assert agent.chat(frame_prompt(request)).startswith('(send "Done")')
        assert agent.chat(frame_prompt(request, frame=OTHER_FRAME)).startswith('(send "Done")')

    def test_escaped_request_matches(self, agent, controller):
        request = 'don\'t write "Hello world" into\n/tmp/e.txt'
        escaped = 'don_apostrophe_t write _quote_Hello world_quote_ into_newline_/tmp/e.txt'
        assert controller.set_answer(request, '(send "ok")')

        assert agent.chat(frame_prompt(escaped)).startswith('(send "ok")')

    def test_unknown_frame_is_not_answered(self, agent, controller):
        assert controller.set_answer("[REQ-7] something else", '(send "Done")')

        assert agent.chat(frame_prompt("[REQ-8] not registered")) == ""

    def test_request_outside_the_frame_section_is_not_answered(self, agent, controller):
        request = "[REQ-9] send Done"
        assert controller.set_answer(request, '(send "Done")')
        prompt = frame_prompt("another task entirely")
        prompt = prompt.replace("OUTPUT_FORMAT:", f"LAST_SKILL_USE_RESULTS: {request}_newline_OUTPUT_FORMAT:")

        assert agent.chat(prompt) == ""
def _llm_request(msg):
    return (LLMRequest().add_message(
        LLMMessage().with_role("user").with_content(msg)))

def _llm_response_json(msg):
    return [("send", { "content": msg })]

def _llm_response(msg):
    return (LLMResponse().add_tool_call(
        LLMToolCall().with_name("send")
        .with_id("mockid#0")
        .add_argument("content", msg)))


def test_structured_frame_request_completes_and_drains():
    import threading
    agent = LlmMockAgent.__new__(LlmMockAgent)
    agent._lock = threading.Lock()
    agent._answers = {}
    agent._served = {}
    agent.on_set_answer({'request': 'frame task', 'response': [('send', {'content': 'done'})]})
    request = (LLMRequest()
               .add_message(LLMMessage().with_role('system').with_content(frame_prompt('frame task')))
               .add_message(LLMMessage().with_role('user').with_content(SIGNAL)))
    first = agent.chat(request)
    assert [call.name for call in first.calls] == ['send', 'complete-goals-stm']
    assert first.calls[0].arguments == {'content': 'done'}
    assert [call.name for call in agent.chat(request).calls] == ['complete-goals-stm']
    assert [call.name for call in agent.chat(request).calls] == ['complete-goals-stm']
    assert agent.chat(request).calls == []


def test_structured_request_does_not_answer_an_unfocused_frame():
    import threading
    agent = LlmMockAgent.__new__(LlmMockAgent)
    agent._lock = threading.Lock()
    agent._answers = {}
    agent._served = {}
    agent.on_set_answer({'request': 'waiting task', 'response': [('send', {'content': 'wrong'})]})
    request = (LLMRequest()
               .add_message(LLMMessage().with_role('system').with_content(frame_prompt('focused task')))
               .add_message(LLMMessage().with_role('user').with_content('waiting task')))
    assert agent.chat(request).calls == []
