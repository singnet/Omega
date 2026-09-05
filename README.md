# Meet Oma

Oma is the first Telegram agent built on the Omega framework. Interacting
with Oma is the fastest way to experience what we’re building with Omega.

<p align="center">
  <a href="https://t.me/ASI_Alliance">
    <img src="/docs/assets/tg-button.png" width="25%" alt="Chat with Oma">
  </a>
</p>

---

## Overview

Omega is a neural-symbolic agent framework built on the Hyperon AGI stack.
It unifies large language models with a formal symbolic layer to create a
stateful cognitive architecture capable of auditable inference, autonomous
self-improvement, and long-term persistence.

Unlike reactive, session-based agents, Omega operates in a continuous
execution loop, managing its own goals and providing auditable proof trails for
its reasoning.

The primary design criteria for Omega were simplicity, ease of extension,
and transparent implementation. This results in a minimalist MeTTa-based core
of approximately 200 lines of code.

---

## Installation

Prerequisites: Git, Python 3.10 or later including dev headers, Pip and [venv](https://docs.python.org/3/library/venv.html) library, C compiler (for building [janus-swi](https://pypi.org/project/janus-swi/) library)

Under Ubuntu one can use the following command to install prerequisites:
```
sudo apt-get install git python3 python3-dev python3-pip python3-venv build-essential
```

Get [SWI-Prolog 10.0.2 or later](https://www.swi-prolog.org/).

Install Omega:
```
git clone https://github.com/trueagi-io/PeTTa
cd PeTTa
mkdir -p repos
git clone https://github.com/singnet/Omega.git repos/Omega
git clone https://github.com/patham9/petta_lib_chromadb.git repos/petta_lib_chromadb
cp repos/Omega/run.metta ./
```

Setup Python virtual environment (or use your own):
```
python3 -m venv ./.venv
source ./.venv/bin/activate
```

If you have CPU only machine or don't want calculate embeddings on GPU:
```
python3 -m pip install --index-url https://download.pytorch.org/whl/cpu torch
```

Install Python dependencies:
```
python3 -m pip install -r ./repos/Omega/requirements.txt
```
---

## Run Omega in Docker

Ensure that you have [Docker installed](https://docs.docker.com/engine/install/)

Run Omega using the next command:
```
curl -fsSL https://raw.githubusercontent.com/singnet/Omega/refs/heads/main/scripts/omega | bash -s -- singularitynet/omega:latest
```

To run a specific version of Omega set version in `TAG` environment variable and run the following command:
```
export TAG=<version>; curl -fsSL  https://github.com/singnet/Omega/raw/refs/tags/$TAG/scripts/omega | bash -s -- singularitynet/omega:$TAG
```

To stop the Omega Docker container:
```
docker stop omega
```

To restart the Omega Docker container:
```
docker start omega
```

To reset Omega's memory:
```
docker volume rm omega-memory
```

### Memory portability

Memory export is disabled by default. See the [memory portability reference](./docs/reference-memory-portability.md)
for setup, export controls, archive contents, and import modes.

> **Current limitation:** Memory import does not work in a standalone Omega
> run. Import and interrupted-import recovery are supported only through Docker
> using `scripts/omega`, because both operations run from the container
> entrypoint before the agent loop starts.

To restore an archive while upgrading to a tagged image, use the same transfer directory:

```sh
scripts/omega start -d singularitynet/omega:<tag> -p OpenAI -t telegram \
  --memory-transfer-dir "$HOME/omega-transfers" \
  --memory-import omegaclaw-memory-<timestamp>.tar.gz \
  --memory-mode overwrite
```

### Run with the visual control panel

The included Compose application starts a local React control panel first and
keeps the OmegaClaw agent stopped until it has a channel and LLM configuration.

In Docker Desktop, open [`compose.yaml`](./compose.yaml), start the `control`
service, and use the published `3210:3210` port link. The page is also available
at [http://localhost:3210](http://localhost:3210).

For a one-command start that also opens the default browser, use the launcher
for your operating system:

```sh
# macOS, Linux, or WSL
./scripts/start-control-ui
```

```powershell
# Windows PowerShell
.\scripts\start-control-ui.ps1
```

Select a communication channel and LLM provider in the page, enter their
credentials, accept the safety notice, and press **Start OmegaClaw**. Pressing
**Stop** stops the agent container without deleting its memory volume. Starting
again recreates only the agent container with the new settings.

The control page is bound to `127.0.0.1` by default. It mounts the Docker socket
so it can manage the `omegaclaw` service declared in the same Compose file; do
not expose the control port to other machines. API credentials are not stored
in browser storage, but Docker necessarily places them in the agent container's
environment while it runs.

Optional environment overrides:

| Variable | Default | Purpose |
|---|---|---|
| `OMEGACLAW_CONTROL_PORT` | `3210` | Host port for the control page. |
| `OMEGACLAW_IMAGE` | `singularitynet/omegaclaw:latest` | OmegaClaw image started by the panel. |

---

## Usage

Before running the system you need to choose your LLM API provider and export the API key as the environment variable.
| Provider | Env var name | Notes |
|---|---|---|
| `Anthropic` (default) | `ANTHROPIC_API_KEY` | Claude models via the Anthropic API. |
| `OpenAI` | `OPENAI_API_KEY` | GPT models. Also reused by the OpenAI embedding provider below. |
| `ASICloud` | `ASI_API_KEY` |  MiniMax models via ASI Alliance inference endpoint (`inference.asicloud.cudos.org`). |
| `ASIOne` | `ASIONE_API_KEY` |  ASI1 Ultra model via ASI:One inference endpoint (`https://api.asi1.ai/v1`). |
| `OpenAIAPI` | `OPENAIAPI_API_KEY` |  Use OpenAI API with any endpoint and model. API endpoint and model are set via `openaiapi_url` and `model` command line parameters. |
| `OpenRouter` | `OPENROUTER_API_KEY` |  GLM model via OpenRouter inference endpoint. |

Run the system via the following command which ensures the system is started from the root folder of PeTTa:
```
OMEGA_AUTH_SECRET=<channel-secret> sh run.sh run.metta IRC_channel="<irc-channel>"
```
After start go to https://webchat.quakenet.org/ to communicate with the agent. Join `<irc-channel>` and after agent is joined send `auth <channel-secret>` message to authenticate yourself as an agent owner. Please replace `<irc-channel>` and `<channel-secret>` by your own values.

### Import Knowledge

If you are running Omega without Docker and would like to load it with preset knowledge, follow these steps:

1. Set EMBEDDING_PROVIDER in your environment. It can be set to either OpenAI or Local. OpenAI embeddings also require OPENAI_API_KEY to be set in your environment.

2. Run:
```
  sh ./import_knowledge.sh
```
After the script finishes, your Omega bot will have the preset knowledge stored in its long-term memory (LTM).

If you want to skip preloading the knowledge then run `export IMPORT_KB_ON_START=0`

## Configuration Options

These are the following sources of the configuration parameters for the
Omega agent:
- command line parameters
- environment variables
- configuration file

Omega looks for parameters in each of the locations. Command line
parameters override environment variables which in turn override configuration
file values. Environment variables should be named `OMEGA_<parameter>` in
order to separate them from other variables. For example to override the
default LLM model one can set an `OMEGA_model` environment variable. The full
list of parameters with descriptions and default values can be found in
[default configuration file](/config/config.yaml).

The configuration file location can be specified manually using `config` option:
```sh
sh run.sh run.metta config=<config.yaml path>
```

The LLM API keys (see [table above](#usage)) and communication channel tokens
from the table below are passed via environment variables (without `OMEGA_`
prefix) to prevent agent accessing them.

| Environment variable | Meaning |
|---|---|
| `TG_BOT_TOKEN` | Telegram bot token. |
| `MM_BOT_TOKEN` | Mattermost bot token. |
| `SL_BOT_TOKEN` | Slack bot token (`xoxb-...`). |

---

## Documentation

Full documentation lives in [`docs/`](./docs/README.md): introduction,
tutorials, and API reference as a flat set of markdown files.

---

### Disclaimer

<sub>Omega is experimental, open-source software developed by SingularityNET Foundation, a Swiss foundation, and distributed and promoted by Superintelligence Alliance Ltd., a Singapore company (collectively, the "Parties"), and is provided "AS IS" and "AS AVAILABLE," without warranty of any kind, express or implied, including but not limited to the implied warranties of merchantability, fitness for a particular purpose, and non-infringement. Omega is an autonomous AI agent that is designed to independently set goals, make decisions, and take actions (including actions that the user did not specifically request or anticipate) and whose behavior is influenced by large language models provided by third parties, the outputs of which are inherently non-deterministic. Depending on its configuration and the permissions granted to it, Omega may execute operating-system shell commands, read, write, modify, or delete files, access network resources, send and receive messages through connected communication channels, and modify its own skills, memory, and operational logic at runtime. Omega may also be susceptible to prompt injection and other adversarial manipulation techniques whereby malicious content embedded in data sources consumed by the agent could influence its behavior in unintended ways. Omega supports third-party skills and extensions that have not necessarily been reviewed, audited, or endorsed by either of the Parties and that may introduce security vulnerabilities, cause data loss, or result in unintended behavior including data exfiltration. Omega relies on third-party services, including large language model providers, whose availability, accuracy, cost, and conduct are outside the control of the Parties and whose use is subject to their respective terms, conditions, and privacy policies. The user is solely responsible for configuring appropriate access controls, sandboxing, and permission boundaries, for monitoring, supervising, and constraining Omega's actions, for ensuring that no sensitive personal data is exposed to the agent without adequate safeguards, and for all actions taken by Omega on the user's systems or on the user's behalf, including communications sent and files modified. The user is strongly advised to run Omega in an isolated environment with the minimum permissions necessary for the intended use case. To the maximum extent permitted by applicable law, in no event shall the Parties, their respective board members, directors, contributors, employees, or affiliates be liable for any direct, indirect, incidental, special, consequential, or exemplary damages (including but not limited to damages for loss of data, loss of profits, business interruption, unauthorized transactions, reputational harm, or any damages arising from the autonomous actions taken by Omega) however caused and on any theory of liability, whether in contract, strict liability, or tort (including negligence or otherwise), even if advised of the possibility of such damages. By downloading, installing, running, or otherwise using Omega, the user acknowledges that they have read, understood, and agreed to this disclaimer in its entirety. This disclaimer supplements but does not replace the terms of the Apache License, Version 2.0, under which Omega is released.</sub>
