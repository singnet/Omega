import os
import lib_llm_ext as llm
from providers import *

class MockProvider(LLMProvider):

    def __init__(self):
        super().__init__()

    def start(self) -> None:
        self.delegate = MockProviderImpl()

    def stop(self) -> None:
        self.delegate.stop()

    def chat(self, args: LLMRequest) -> LLMResponse:
        return self.delegate.chat(args)

def loadOmegaPlugin():
    registerLLMProvider("Test", MockProvider())

class MockProviderImpl(llm.AbstractAIProvider):
    """Test provider for mocking LLM output"""

    def __init__(self):
        super().__init__("Mockprovider")
        self._mock = None
        self._controller_ip = os.environ.get("TEST_SERVER_IP")

    def _llm_mock(self):
        if not self._mock:
            from Autotests.mock.llm import LlmMockAgent, LLM_MOCK_PORT
            self._mock = LlmMockAgent((self._controller_ip, LLM_MOCK_PORT))
        return self._mock

    @property
    def is_available(self) -> bool:
        return self._controller_ip is not None

    def chat(self, request: LLMRequest) -> LLMResponse:
        return self._llm_mock().chat(request)

    def stop(self) -> None:
        if self._mock is not None:
            self._mock.stop(timeout=10)
            self._mock = None
