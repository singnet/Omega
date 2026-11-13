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
import ast
from providers import *

_STEP_PREFIX = re.compile(r"^Step \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}: ")

LLM_MOCK_PORT = 9765

FRAME_SECTION_HEADER = "CURRENT_CONTEXT_FRAME_S_EXPR:"
FRAME_SECTION_END = "_newline_SKILLS:"
FRAME_COMPLETION_SKILLS = ("complete-goals-stm", "complete-goals-ltm", "clear-frame-junk")
FRAME_COMPLETION_ANSWER = '(complete-goals-stm "Answered by the mock, frame completed by the test harness.")'
FRAME_COMPLETION_ATTEMPTS = 2
FRAME_ID = re.compile(r"\(frameID\s+([^)\s]+)\)")


def unescape(text):
    return (text
            .replace("_apostrophe_", "'")
            .replace("_quote_", '"')
            .replace("_newline_", "\n"))


def frame_section(prompt):
    start = prompt.find(FRAME_SECTION_HEADER)
    if start < 0:
        return None
    start += len(FRAME_SECTION_HEADER)
    end = prompt.find(FRAME_SECTION_END, start)
    return prompt[start:] if end < 0 else prompt[start:end]


def frame_id(section):
    found = FRAME_ID.search(section)
    return found.group(1) if found else "unknown-frame"


class LlmMockAgent:

    def __init__(self, address):
        self._lock = threading.Lock()
        self._answers = {}
        self._served = {}
        self._rpc = Rpc(IPCClient(address))
        self._rpc.on_request('set_answer', lambda args: self.on_set_answer(args))
        self._rpc.on_request('reset', lambda args: self.on_reset(args))
        self._rpc.on_request('clear_answer', lambda args: self.on_clear_answer(args))
        self._rpc.on_request('ping', lambda args: self.on_ping(args))
        self._rpc.start()

    def stop(self, timeout=None):
        self._rpc.stop(timeout)

    def chat(self, request):
        if isinstance(request, str):
            return self._legacy_chat(request)
        # Only the focused frame can answer; admitted but unfocused work waits.
        for message in request.messages:
            if message.role == "system":
                section = frame_section(message.content)
                if section is not None:
                    return self._make_llm_response(self._frame_answer(section))
        users = [m for m in request.messages if m.role == "user"]
        if not users:
            return LLMResponse()
        body = _STEP_PREFIX.sub("", users[-1].content, count=1)
        return self._make_llm_response(self._message_answer(body))

    def _legacy_chat(self, content):
        user = content.rsplit(":-:-:-:", 1)
        if len(user) < 2:
            return ""

        message = self._message(user[1])
        if message is not None:
            answer = self._message_answer(message)
            if answer:
                print(f"[LlmMockAgent] Mock answers: {answer}")
                return answer

        section = frame_section(user[0])
        if section is not None:
            return self._frame_answer(section)

        if message is not None:
            print(f"[LlmMockAgent] Mock doesn't have answer for: {message}")
        return ""

    def _message(self, suffix):
        try:
            return ast.literal_eval(suffix)[1]
        except Exception:
            return None

    def _message_answer(self, body):
        # The agent escapes punctuation that would confuse its s-exp
        # parser ('->_apostrophe_, "->_quote_, \n->_newline_) before
        # the text reaches chat(). set_answer stores the literal
        # prompt key, so try the raw body first, then the normalized
        # form so prompts with quotes/apostrophes/newlines still match.
        with self._lock:
            answer = self._response(self._answers.get(body) or self._answers.get(unescape(body)))
        if answer:
            return answer

        # IRC may deliver multiple PRIVMSGs in one agent iteration; the
        # agent concatenates them with " | " between speakers. Split
        # and look up each fragment individually so a registered answer
        # is not missed when several messages arrive together.
        for fragment in body.split(" | "):
            if ": " not in fragment:
                continue
            prompt = fragment.split(": ", 1)[1]
            with self._lock:
                found = self._answers.get(unescape(prompt)) or self._answers.get(prompt)
            if found:
                answer = self._response(found)

        return answer

    # With context frames the received message is no longer passed after
    # the ":-:-:-:" delimiter: the delimiter carries a loop signal and the
    # text becomes the current frame, projected into the prompt under
    # CURRENT_CONTEXT_FRAME_S_EXPR. Matching against that section rather
    # than the whole prompt keeps the mock honest: a message that was
    # admitted but did not become current is not answered.
    def _frame_answer(self, section):
        current = unescape(section)
        frame = frame_id(section)

        with self._lock:
            match = None
            for request, entry in self._answers.items():
                if request in current or unescape(request) in current:
                    match = (request, entry)
                    break

            if match is None:
                print(f"[LlmMockAgent] Mock doesn't have answer for frame: {frame}")
                return ""

            request, (response, complete_frame) = match
            served = self._served.get((frame, request), 0)
            self._served[(frame, request)] = served + 1

        # A frame outlives the iteration that answered it, so the answer is
        # served once. While the same frame keeps coming back the harness
        # completes it instead, otherwise the next message is admitted but
        # never becomes current and every later test fails with it.
        if served == 0:
            if isinstance(response, str):
                if complete_frame and not any(skill in response for skill in FRAME_COMPLETION_SKILLS):
                    response = f"{response} {FRAME_COMPLETION_ANSWER}"
            else:
                response = list(response)
                if complete_frame and not any(name in FRAME_COMPLETION_SKILLS for name, _ in response):
                    response.append(("complete-goals-stm", {"summary": "Answered by the mock, frame completed by the test harness."}))
            print(f"[LlmMockAgent] Mock answers: {response}")
            return response

        if complete_frame and served <= FRAME_COMPLETION_ATTEMPTS:
            print(f"[LlmMockAgent] Frame {frame} is still current, completing it")
            return FRAME_COMPLETION_ANSWER

        print(f"[LlmMockAgent] Frame {frame} was already answered")
        return ""

    def _response(self, entry):
        return entry[0] if entry else None

    def _make_llm_response(self, calls):
        if not calls:
            return LLMResponse()
        if isinstance(calls, str):
            # Parse quoted arguments without interpreting them as Python code.
            tokens = re.findall(r'"(?:\\.|[^"\\])*"|[^\s()]+|[()]', calls)
            parsed = []
            index = 0
            while index < len(tokens):
                if tokens[index] != "(":
                    raise ValueError("Expected mock tool call")
                name = tokens[index + 1]
                index += 2
                args = []
                while tokens[index] != ")":
                    token = tokens[index]
                    args.append(ast.literal_eval(token) if token.startswith('"') else token)
                    index += 1
                index += 1
                names = {
                    "send": ["content"], "write-file": ["filename", "content"],
                    "append-file": ["filename", "content"], "write-file-b64": ["filename", "content_base64"],
                    "complete-goals-stm": ["summary"], "complete-goals-ltm": ["summary"],
                    "clear-frame-junk": ["summary"], "metta": ["sexpression"],
                    "pin": ["message"], "remember": ["content"], "query": ["content"],
                    "shell": ["cmd"], "read-file": ["filename"], "websearch": ["content"],
                }.get(name)
                if names is None or len(names) != len(args):
                    raise ValueError(f"Unsupported legacy mock call: {name}")
                parsed.append((name, dict(zip(names, args))))
            calls = parsed
        response = LLMResponse()
        for index, (name, args) in enumerate(calls):
            response.add_tool_call(LLMToolCall().with_name(name).with_id(f"mockid#{index}").with_arguments(args))
        return response

    def on_set_answer(self, args):
        with self._lock:
            request = args['request']
            response = args['response']
            complete_frame = args.get('complete_frame', True)
            print(f'[LlmMockAgent] Mock request: "{request}" with response "{response}"')
            self._answers[request] = (response, complete_frame)
            return True

    def on_reset(self, args):
        with self._lock:
            self._answers.clear()
            self._served.clear()
        print('[LlmMockAgent] Mock answers cleared')
        return True

    def on_clear_answer(self, args):
        with self._lock:
            request = args['request']
            print(f'[LlmMockAgent] Mock request cleared: "{request}"')
            self._answers.pop(request, None)
            return True

    def on_ping(self, args):
        print(f'[LlmMockAgent] Mock ping request processed')
        return True

class LlmMockController:

    def __init__(self, address):
        self._rpc = Rpc(IPCServer(address))
        self._rpc.start()

    def stop(self, timeout=None):
        self._rpc.stop(timeout)

    def set_answer(self, request, response, complete_frame=True, timeout=10):
        result = self._rpc.request('set_answer', { 'request': request, 'response': response,
                                                   'complete_frame': complete_frame })
        if result.get(timeout) != True:
            print(f'[LlmMockController] Cannot set answer to the mock, error: {result.error()}')
            return False
        return True

    def reset(self, timeout=10):
        result = self._rpc.request('reset', {})
        if result.get(timeout) != True:
            print(f'[LlmMockController] Cannot reset the mock, error: {result.error()}')
            return False
        return True

    def clear_answer(self, request, timeout=10):
        result = self._rpc.request('clear_answer', { 'request': request })
        if result.get(timeout) != True:
            print(f'[LlmMockController] Cannot clear answer in the mock, error: {result.error()}')
            return False
        return True

    def ping(self, timeout=None):
        print(f'[LlmMockController] Ping agent')
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
