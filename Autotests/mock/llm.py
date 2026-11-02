# Support both layouts: imported as a package (Autotests.mock.llm in
# the container's loop.metta), and as a plain directory (host-side
# pytest collecting mock/ without __init__.py).
try:
    from .rpc import Rpc, IPCClient, IPCServer
except ImportError:
    from rpc import Rpc, IPCClient, IPCServer
from contextlib import contextmanager
import re
import threading
from providers import *

LLM_MOCK_PORT = 9765

# The loop sends every user message as "Step <time>: <text>"; answers are keyed by <text>.
_STEP_PREFIX = re.compile(r"^Step \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}: ")

class LlmMockAgent:

    def __init__(self, address):
        self._lock = threading.Lock()
        self._answers = {}
        self._rpc = Rpc(IPCClient(address))
        self._rpc.on_request('set_answer', lambda args: self.on_set_answer(args))
        self._rpc.on_request('ping', lambda args: self.on_ping(args))
        self._rpc.start()

    def stop(self, timeout=None):
        self._rpc.stop(timeout)

    def chat(self, request: LLMRequest) -> LLMResponse:
        user = [m for m in request.messages if m.role == "user"]
        answer = None
        if len(user) > 0:
            body = user[-1].content

            # The agent escapes punctuation that would confuse its s-exp
            # parser ('->_apostrophe_, "->_quote_, \n->_newline_) before
            # the text reaches chat(). set_answer stores the literal
            # prompt key, so try the raw body first, then the normalized
            # form so prompts with quotes/apostrophes/newlines still match.
            def normalize(text):
                return (text
                        .replace("_apostrophe_", "'")
                        .replace("_quote_", '"')
                        .replace("_newline_", "\n"))

            text = _STEP_PREFIX.sub("", body, count=1)
            with self._lock:
                answer = self._answers.get(text) or self._answers.get(normalize(text))

            if not answer:
                # IRC may deliver multiple PRIVMSGs in one agent iteration; the
                # agent concatenates them with " | " between speakers. Split
                # and look up each fragment individually so a registered answer
                # is not missed when several messages arrive together.
                fragments = text.split(" | ")
                for fragment in fragments:
                    if ": " not in fragment:
                        continue
                    prompt = fragment.split(": ", 1)[1]
                    with self._lock:
                        a = self._answers.get(normalize(prompt)) or self._answers.get(prompt)
                    if a:
                        answer = a

        if answer:
            print(f"[LlmMockAgent] Mock answers: {answer}")
            return self._make_llm_response(answer)
        else:
            print(f"[LlmMockAgent] Mock doesn't have answer for: {body}")
            return LLMResponse()

    def on_set_answer(self, args):
        with self._lock:
            request = args['request']
            response = args['response']
            print(f'[LlmMockAgent] Mock request: "{request}" with response "{response}"')
            self._answers[request] = response
            return True

    def on_ping(self, args):
        print('[LlmMockAgent] Mock ping request processed')
        return True

    def _make_llm_response(self, calls: [(str, dict[str, str])]) -> LLMResponse:
        response = LLMResponse()
        id = 0
        for (func, args) in calls:
            response.add_tool_call(LLMToolCall()
                                   .with_name(func)
                                   .with_id(f"mockid#{id}")
                                   .with_arguments(args))
            id = id + 1
        return response


class LlmMockController:

    def __init__(self, address):
        self._rpc = Rpc(IPCServer(address))
        self._rpc.start()

    def stop(self, timeout=None):
        self._rpc.stop(timeout)

    def set_answer(self, request, response, timeout=10):
        result = self._rpc.request('set_answer', { 'request': request, 'response': response })
        if result.get(timeout) != True:
            print(f'[LlmMockController] Cannot set answer to the mock, error: {result.error()}')
            return False
        return True

    def ping(self, timeout=None):
        print('[LlmMockController] Ping agent')
        result = self._rpc.request('ping', {})
        if result.get(timeout) != True:
            print(f'[LlmMockController] Did not get answer on ping in {timeout} seconds')
            return False
        else:
            return True

@contextmanager
def llm_mock_controller(*args, **kwargs) -> LlmMockController:
    timeout = kwargs.pop("timeout", 30)
    controller = LlmMockController(*args, **kwargs)
    try:
        if not controller.ping(timeout):
            raise RuntimeError(f"Agent didn't answered in {timeout} seconds")
        yield controller
    finally:
        controller.stop(5)
