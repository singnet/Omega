# Reference - Plugin API

Omega provides a plugin API which allows writing plugins to extend the
agent's functionality. A plugin is a MeTTa or Python module which provides the
entry point function `loadOmegaPlugin`. 

The `loadOmegaPlugin` function calls the Omega plugin API in order to 
implement new agent's features. The plugin API provides functions to:
- add communication channel integrations
- add LLM provider integrations
- add new skills or remove added skills
- extend LLM prompt by adding new information or removing it
- etc

In order to be loaded the plugin should be included into the
[config/plugins.yaml](/config/plugins.yaml) file. The agent loads each module
listed in this file on start and calls `loadOmegaPlugin` entry function of
each loaded module. All communication channels and LLM integrations of
Omega are implemented using this API. The full list of plugins available in
the Omega repository can be found in the
[config/plugins.yaml](/config/plugins.yaml) file.

Plugin can be implemented as a MeTTa module, a single Python file or a Python
module. The plugin record has the following fields:
  - `name` (required) - each plugin should have an unique name. In case of
    MeTTa plugin `name` is the name of the MeTTa module. In case of Python
    plugin `name` is the name of the Python file (without `.py` extension) or
    Python module.
  - `loader` (required) - possible values are `metta` or `python`. The runtime
    which should be used to load the plugin.
  - `location` (optional) - must be specified if plugin is a single Python file
    or MeTTa module. In such case it provides the path to the directory where
    `name` module is located. Can include `{REPO}` placeholder to designate the
    root folder of the Omega source repository.

## Plugin dependencies

A plugin that imports a third-party package declares it in a `requirements.txt`
in the plugin's own directory. `scripts/install_dependencies.sh` installs those
alongside Omega's own, and both the image build and the source install in
[README.md](/README.md#installation) call it. A plugin that imports nothing
outside the standard library and Omega ships no such file and needs no entry
anywhere.

Everything is installed by a single pip invocation, so Omega's own pins win. They
are exact, and a plugin asking for a different version of a package Omega pins
fails the install with a conflict rather than replacing it. Declare ranges wide
enough to include Omega's pin — `openai>=1.0.0` rather than `openai==2.1.0` —
and list only what the plugin actually imports.

The file holds requirements and nothing else. pip reads an option written inside
a requirements file — `--index-url` and `--extra-index-url` above all — as an
instruction for the whole invocation rather than for the file carrying it, which
would let one plugin choose where Omega's own packages are fetched from. Sharing
one invocation is what makes Omega's pins win, so there is nowhere to scope such
a line to, and a plugin that carries one stops the install with the line quoted.

Two limits are worth knowing. A plugin that pins a package Omega depends on
*indirectly* can change it without any error, because nothing is violated: keep
the list short for this reason. And a plugin mounted into an already built image
gets no installation at all, since the packages are baked in at build time — that
route needs an image built with the plugin present.

As an example of a MeTTa plugin one can look at the code of the [workflow
plugin](/plugins/workflow/workflow.metta). As an example of a Python plugin
one can look at the code of the [IRC communication channel](/channels/irc.py).

The Omega plugin API is under construction. This is the reason why some
APIs are available only as the Python modules and others only as the MeTTa
modules. Partially it is because writing some kinds of plugins is simpler using
Python.

Another issue is that it is difficult to run plugins inside Docker container.
There are two ways of doing this:
  1. Build fresh image including plugin's code and modified
     `config/plugins.yaml` configuration file.
  2. Mount the plugin's code and modified `config/plugins.yaml` configuration
     file into the container using custom `docker run` command.

This document doesn't describe using Docker in details it is a subject to the
future Omega improvements.

## Communication channel integration

Each plugin can register more than one communication channel. Each
communication channel must have an unique id which is used as the value of the
`commchannel` configuration parameter in order to enable the channel.

In order to implement new communication channel one should implement two main
functions:
- "receive" - returns the next message received through the communication channel
- "send" - sends the message through the communication channel

Communication channel integration should be implemented as a Python class.
Inherit the class from `channels.CommChannel` and implement at least two
methods of the ancestor.

```python
import channels

class ExampleCommChannel(channels.CommChannel):

    def start(self) -> None:
        print("ExampleCommChannel is started")

    def stop(self) -> None:
        print("ExampleCommChannel is stopped")

    def receive(self) -> str:
        return "Received message example" 

    def send(self, message: str) -> None:
        print(f"ExampleCommChannel sends {message}")
```

In order to be able to use a new communication channel the plugin code should
register the instance of the `ExampleCommChannel` in the system using
`registerCommChannel` function.

```python
def loadOmegaPlugin():
    channels.registerCommChannel("Example", ExampleCommChannel())
```

Here `"Example"` is an identifier of the communication channel.

### Using communication channel

The communication channel identifier should be used as the value for the
`commchannel` command line parameter to use the communication channel with the
agent (see [README.md](/README.md#configuration-options)):

For example one can use the following command to run the agent using `Example`
as the communication plugin. This command requires Omega to be installed in
the system first (see [README.md](/README.md#installation)):
```sh
sh run.sh run.metta commchannel=Example
```

## LLM provider integration

Each plugin can register more than one LLM provider. Each LLM provider must
have an unique id which is used as the value of the `provider` configuration
parameter in order to enable the provider.

In order to implement a new LLM provider integration one should provide
implementation of the single function `chat`. The function takes three
parameters:
- `prompt` - the string which is sent to LLM by agent as a prompt, required
- `max_tokens` - the maximum number of tokens can be used by provider to answer the
  prompt, default value is 6000
- `reasoning_mode` - the reasoning mode of the LLM, default value is "medium"

LLM provider integration should be implemented as a Python class. Inherit the
class from `providers.LLMProvider` and implement at least one method of the
ancestor.

```python
import providers

class ExampleLLMProvider(providers.LLMProvider):

    def start(self) -> None:
        print("ExampleLLMProvider is started")

    def stop(self) -> None:
        print("ExampleLLMProvider is stopped")

    def chat(self, prompt: str, max_tokens: int = 6000, reasoning_mode: str = "medium") -> str:
        return "LLM answer example" 
```

In order to be able to use this LLM provider integration the plugin code should
register the instance of the `ExampleLLMProvider` in the system using
`registerLLMProvider` function.

```python
def loadOmegaPlugin():
    providers.registerLLMProvider("Example", ExampleLLMProvider())
```

Here `"Example"` is an identifier of the LLM provider.

### Using LLM provider

The LLM provider identifier should be used as the value for the `provider`
configuration parameter to use the LLM provider with the agent (see
[README.md](/README.md#configuration-options)):

For example one can use the following command to run the agent using `Example`
as the LLM provider plugin. This command requires Omega to be installed in
the system first (see [README.md](/README.md#installation)):
```sh
sh run.sh run.metta provider=Example
```

## Other agent related APIs

A plugin can dynamically add new skills or modify the agent's prompt if it is
required. This ability is provided by the following MeTTa functions:
- `(add-skill $function $description $arguments)` - adds the skill
- `(remove-skill $function)` - removes the skill by its function name
- `(add-prompt-extension $handle $text)` - adds text to the prompt
- `(remove-prompt-extension $handle)` - removes text from the prompt by the
  handle

One can look at [source code](/src/skills.metta) for a detailed description.
Please also look at [workflow plugin](/plugins/workflow/workflow.metta) for
example usage.

One can add the callback which is called on each main agent loop iteration:
- `(add-heartbeat-listener $handle $callback)` - adds heartbeat listener
- `(remove-heartbeat-listener $handle)` - removes heartbeat listener

Callback is called once in the beginning of the each loop iteration and it has
a single parameter which receives the iteration number. Please see [unit
tests](/tests/src_skills.metta) for an example of usage.
