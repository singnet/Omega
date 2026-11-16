import re

import pytest

import router_harness as rh


@pytest.fixture(scope="session")
def omega_image():
    return rh.resolve_image()


@pytest.fixture
def make_stub():
    stubs = []

    def make(label, script=None, timeline=None):
        stub = rh.Stub(label, script=script, timeline=timeline)
        stub.start()
        stubs.append(stub)
        return stub

    yield make
    for stub in stubs:
        stub.stop()


@pytest.fixture
def start_agent(request, omega_image, make_stub):
    agents = []
    names = []

    def start(app_args, env=None, entrypoint=None, docker_args=()):
        label = re.sub(r"[^a-z0-9]+", "-", request.node.name.lower())[:28].strip("-")
        name = rh.new_name(label)
        names.append(name)
        agent = rh.Agent(name, omega_image, app_args, env=env, entrypoint=entrypoint,
                         docker_args=docker_args)
        agents.append(agent)
        return agent

    yield start
    try:
        for agent in agents:
            try:
                agent.save_log()
            finally:
                agent.tail.close()
    finally:
        for name in names:
            rh.docker("rm", "-f", name, timeout=120)
