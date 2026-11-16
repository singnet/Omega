import json
import shlex

import router_harness as rh

TOKEN = "fake-compat-token"
COMPAT_REQUEST_TIMEOUT = 90
ARGUMENT_CATALOG_WINDOW = 20
TEST_CHANNEL = ["commchannel=test", "embeddingprovider=Local"]


def standalone(app_args):
    script = "cd /PeTTa && exec sh run.sh run.metta " + " ".join(shlex.quote(a) for a in app_args)
    return ["-c", script]


def failed_cycles(agent):
    return len(agent.runtime_lines("providers", r"Exception while getting LLM response"))


def test_bare_docker_run_without_router_argument_reaches_stub(start_agent, make_stub):
    stub = make_stub("only")
    agent = start_agent(
        ["provider=OpenAIAPI", "model=model-r66", f"openaiapi_url={rh.stub_url(stub)}", *TEST_CHANNEL],
        env={"OPENAIAPI_API_KEY": TOKEN},
    )
    received = agent.wait_stub_request(stub, COMPAT_REQUEST_TIMEOUT)
    assert received, (
        f"stub received no request in {COMPAT_REQUEST_TIMEOUT}s; "
        f"failed LLM cycles in log: {failed_cycles(agent)}; " + agent.describe())
    assert stub.requests[0]["body"]["model"] == "model-r66"


def test_catalog_with_token_in_command_line_argument_is_not_used(start_agent, make_stub):
    stub = make_stub("only")
    catalog = rh.catalog((stub, "model-r71", TOKEN))
    agent = start_agent(
        ["router=default", f"router_catalog={json.dumps(catalog)}", *TEST_CHANNEL],
    )
    reached = agent.tail.wait_for(rh.ITERATION_1, rh.STARTUP_TIMEOUT) is not None
    if reached:
        agent.wait_stub_request(stub, ARGUMENT_CATALOG_WINDOW)
    used = [item for item in stub.requests if item["authorization"] == f"Bearer {TOKEN}"]
    assert not used, (
        f"the token passed in the router_catalog argument was used for {len(used)} request(s); "
        + agent.describe())
    if agent.state()[0] != "running":
        started = [line for line in agent.runtime_lines("providers", r"Started LLM provider ")
                   if "model-r71" in line]
        assert not started, (
            "container exited after starting the role from the router_catalog argument: "
            f"{started}; " + agent.describe())


def test_bare_docker_run_with_only_anthropic_key_starts_anthropic_routine_role(start_agent):
    agent = start_agent(
        TEST_CHANNEL,
        env={"ANTHROPIC_API_KEY": "fake-anthropic-token"},
        docker_args=["--add-host", "api.anthropic.com:127.0.0.1"],
    )
    line = agent.tail.wait_for(
        rh.RUNTIME + r"providers \| Started LLM provider role=routine provider=Anthropic ",
        rh.STARTUP_TIMEOUT)
    assert line is not None, (
        "routine role did not start with provider Anthropic; " + agent.describe())


def test_openai_embeddings_with_openaiapi_llm_start_and_nginx_has_openai_route(start_agent, make_stub):
    stub = make_stub("only")
    agent = start_agent(
        ["router=none", "provider=OpenAIAPI", "embeddingprovider=OpenAI", "commchannel=test",
         "model=model-r74", f"openaiapi_url={rh.stub_url(stub)}"],
        env={"OPENAIAPI_API_KEY": TOKEN, "OPENAI_API_KEY": "fake-embeddings-token"},
    )
    assert agent.wait_stub_request(stub, COMPAT_REQUEST_TIMEOUT), (
        "stub received no request; " + agent.describe())
    routes = agent.exec("grep", "-c", "location /openai/", "/opt/nginx/router.conf")
    assert routes.stdout.strip() == "1", (routes.stdout, routes.stderr)


def test_standalone_default_config_reaches_iteration_one(start_agent):
    agent = start_agent(standalone(TEST_CHANNEL), entrypoint="sh")
    agent.wait_iteration_1()
    assert agent.state()[0] == "running", agent.describe()


def test_standalone_openaiapi_provider_reaches_stub(start_agent, make_stub):
    stub = make_stub("only")
    agent = start_agent(
        standalone(["provider=OpenAIAPI", "model=model-r76", f"openaiapi_url={rh.stub_url(stub)}", *TEST_CHANNEL]),
        env={"OPENAIAPI_API_KEY": TOKEN},
        entrypoint="sh",
    )
    agent.wait_iteration_1()
    assert stub.wait_requests(1, COMPAT_REQUEST_TIMEOUT), (
        "stub received no request; " + agent.describe())
    assert stub.requests[0]["body"]["model"] == "model-r76"
