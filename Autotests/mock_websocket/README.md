# WebSocket autotests — setup and run

This suite exercises the WebSocket communication channel (`channels/wschat.py`)
with the deterministic LLM mock (`provider=Test`). The agent is a WebSocket
**client**; a local mock WebSocket **server** (`WsMockDriver`) stands in for the
ASI Create chat, so no external service participates and the whole flow is local
and deterministic (CI-eligible).

For the LLM-mock harness shared with this suite see `Autotests/mock/README.md`.

## 1. Prerequisites

- Docker engine on the host.
- Repository checked out, working from its root.
- Python virtual environment under `Autotests/venv` with `pytest` and
  `websockets` installed (`pip install pytest websockets`).

## 2. Build the local image

```
docker build -t omega:mock .
```

## 3. Start the container on the websocket channel with the Test provider

The container connects back to the host on TCP port 9765 to reach the mock LLM
controller (`TEST_SERVER_IP`) and to `WS_URL` for the chat transport. Under the
default Docker bridge the host is `172.17.0.1`. The mock WS server listens on
`WS_MOCK_PORT` (default `8770`); `WS_URL` must point at it and `WS_TOKEN` must
match the bearer token the mock server checks (`test-token`).

```
env WS_URL=ws://172.17.0.1:8770 WS_TOKEN=test-token TEST_SERVER_IP=172.17.0.1 \
  ./scripts/omega start -s 0000 -p Test -t websocket -d omega:mock
```

Notes:

- `-t websocket` selects the WebSocket channel; `WS_URL`/`WS_TOKEN` are passed to
  the container.
- `-p Test` selects the mock LLM dispatcher; `TEST_SERVER_IP` is the host's
  docker-bridge address used to reach the mock LLM controller.
- The container is created with the name `omega` (the script default).

The agent reconnects with backoff until the mock server is up, so the container
can be started before or after the pytest session. Wait until the agent loop is
running:

```
until docker logs omega 2>&1 | grep -qE "iteration 1"; do sleep 2; done
```

## 4. Configure the test environment

```
export OMEGA_CONTAINER=omega
export WS_MOCK_PORT=8770        # must match the WS_URL port used in step 3
export WS_TOKEN=test-token      # must match step 3
```

| Variable | Required | Description |
|---|---|---|
| `OMEGA_CONTAINER` | Yes | Container name passed to `docker exec`. |
| `WS_MOCK_PORT` | No | Port the mock WS server binds (default `8770`). Must match the `WS_URL` port. |
| `WS_TOKEN` | No | Bearer token the mock server requires (default `test-token`). Must match the container's `WS_TOKEN`. |

## 5. Run the suite

This directory has two tiers:

- `test_wschat_unit.py` — in-process unit tests of `channels/wschat.py`. No
  container, no `-t websocket`, no `websockets` library needed (wschat imports it
  lazily). Runs in the same CI job as `mock/test_comm.py` / `test_llm.py` /
  `test_rpc.py`; registered in `Autotests/run_mandatory`.
- `test_*_ws_mock.py` — end-to-end integration tests that drive a `-t websocket`
  container through `WsMockDriver`. They need the container started as in step 3
  and the `websockets` library on the host. Not in `run_mandatory` (a single CI
  container runs one commchannel; these need `-t websocket`, not the `-t test`
  used by `run_mandatory`).

Unit tests (no container required):

```
cd Autotests
pytest -s -v mock_websocket/test_wschat_unit.py       # expect: 6 passed
```

Integration tests (against the `-t websocket` container from step 3):

```
cd Autotests
source venv/bin/activate
pytest -s -v mock_websocket/test_*_ws_mock.py         # expect: 7 passed
```

The `LlmMockController` (tcp:9765) and `WsMockDriver` (tcp:`WS_MOCK_PORT`) are
provided by session-scoped fixtures in `mock_websocket/conftest.py`, started once
per session.

## 6. Tear down

```
./scripts/omega clean
```

# Tests description

## Unit — `test_wschat_unit.py` (registered in `Autotests/run_mandatory`)

In-process tests of `channels/wschat.py`, driving its pure functions directly:
no container, no `websockets` library. This is the CI regression entry — it runs
on every PR in the same job as `test_comm` / `test_llm` / `test_rpc`.

- `test_enqueue_join_and_last_seen` — three `user_message` frames drain as
  `A | B | C`; `last_seen_seq` advances to 3; a second drain is empty.
- `test_dedup_by_last_seen_seq` — frames with `seq <= last_seen_seq` are dropped.
- `test_dedup_by_inbox_order` — a frame with `seq <= inbox[-1]` is dropped.
- `test_frame_robustness` — non-JSON / non-dict / non-int seq / non-str text /
  unknown / ack / error frames are dropped without raising; a following valid
  frame is enqueued.
- `test_outbox_buffers_while_disconnected_and_flushes` — `send_message` while
  disconnected buffers an `agent_message` (uuid `client_seq`); `_drain_outbox`
  flushes it with the same `client_seq`.
- `test_resume_frame_reflects_last_seen` — `_build_resume_frame` carries the
  current `last_seen_seq`.

## Integration — `test_*_ws_mock.py` (needs a `-t websocket` container)

End-to-end tests through `WsMockDriver`. They prove the full wiring
(`channels.metta` websocket dispatch, `send` skill → `agent_message`, real drain
→ LLM) that the unit tests cannot reach. Not in `run_mandatory` (they need a
`-t websocket` container, unlike the `-t test` container `run_mandatory` runs
against); run them on the stand or a dedicated CI stage.

### 1. test_ws_delivery_ws_mock.py

Delivery round-trip. A `user_message` reaches the agent; the agent replies with
`(send "WS-PONG-<run_id>")`; the mock receives an `agent_message` and acks it.

- Checks: an `agent_message` carrying the token arrives; its `client_seq` is a
  valid uuid hex; the mock acked that `client_seq`.

### 2. test_ws_queue_merge_ws_mock.py

Queue merge. Three `user_message` frames (contiguous seq) are injected
back-to-back before the agent drains, so they join as `A | B | C` in one LLM
input (the merged prompt is the registered answer key).

- Checks: a single merged `agent_message` (`WS-MERGED-<run_id>`) arrives; after a
  forced reconnect the `resume` frame carries `last_seen_seq` equal to the last
  of the three seqs.

### 3. test_ws_resume_dedup_ws_mock.py

Resume + dedup. After one delivered/answered prompt the connection is dropped;
the agent reconnects and sends `resume` with the advanced `last_seen_seq`; the
mock replays the already-seen frame.

- Checks: the `resume` frame carries the advanced `last_seen_seq`; the replayed
  frame (`seq <= last_seen_seq`) is deduped by the agent — no second answer.

### 4. test_ws_outbox_flush_ws_mock.py

Outbox flush. A prompt is delivered while connected; the connection is dropped
and reconnects refused for a short window, so the agent produces its reply while
disconnected and buffers it in the outbox; on reconnect the outbox is flushed
before any new inbound traffic.

- Checks: the buffered `agent_message` (`WS-BUFFERED-<run_id>`) is delivered after
  reconnect and not duplicated.

### 5. test_ws_frame_robustness_ws_mock.py

Frame robustness. Non-JSON, a malformed `user_message` (non-int `seq`), an
unknown frame type, an `error` frame, and a non-object payload are all sent to
the agent.

- Checks: the channel drops them without crashing (connection stays open); a
  following valid prompt (`WS-ALIVE-<run_id>`) is answered normally.

## Skill smoke (prove skills work over this transport)

Two mirrors of the `mock/` suite with delivery swapped to `ws_send_prompt` — not
in `run_mandatory` (skills are already covered there over the comm channel).

### 6. test_create_file_ws_mock.py

Creates `/tmp/testcat/hello.txt` containing exactly `Hello`, delivered over
WebSocket. Same assertions as `mock/test_create_file_mock.py`.

### 7. test_memory_chromadb_ws_mock.py

Requests the agent to remember a fact tagged `CI-SMOKE-<run_id>`, delivered over
WebSocket; the `remember` skill runs for real and grows the ChromaDB vector
store. Same assertions as `mock/test_memory_chromadb_mock.py`.
