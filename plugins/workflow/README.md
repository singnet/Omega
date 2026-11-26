# Workflow loading plugin

Workflow loading plugin allows loading skills written in the [Agent Skills
format](https://agentskills.io/specification). A skill is a directory with a
`SKILL.md` file, and this plugin refers to a skill as a workflow. Each workflow
consists of a `SKILL.md` file and optionally a `skill.metta` file which
contains the implementation of the related tools in MeTTa language.

[Research workflow](./instructions/research-workflow) is a ready-to-use example
of the workflow. One can try it starting the agent and asking it doing a
research on some topic:
```
Start research. Build a classifier for iris dataset using sklearn, compare
logistic regression and random forest.
```

## Workflow files

`SKILL.md` (required) is the skill file in the [Agent Skills
format](https://agentskills.io/specification). It starts with YAML frontmatter
between `---` lines, followed by the instructions in Markdown. For example:
```md
---
name: test-workflow
description: Demonstrates the workflow plugin by sending a message with a tool
  that exists only while the workflow is active. Use when the user asks to
  demonstrate or test the workflow plugin.
---
Next are instructions and MeTTa  functions  that should be performed step by step
# Test Workflow (Omega)
## Step 1 - demonstrate usage of tools
- Call test-skill with "This is a test workflow demonstration" message
## Step 2 - complete workflow
- Call `(workflow-unload-instructions)`
```

The frontmatter is required. When the agent starts, the plugin reads the
frontmatter of every workflow and adds the list of workflows to the prompt, so
the agent knows which workflows exist and when to load them. Each entry is the
workflow's directory name and its `description`, so write the description as
the spec recommends: say what the workflow does and when to use it, with the
words a user is likely to say. When the workflow is loaded, the plugin puts the
whole `SKILL.md` file into the prompt as the active workflow instructions.

The plugin checks every `SKILL.md` and logs each problem with the path of the
file. One broken file does not affect the other workflows.
- A workflow is left out of the list when `SKILL.md` is not valid UTF-8, has
  no frontmatter, its frontmatter is not valid YAML (including values YAML
  cannot build, such as the date `2026-02-30`), or it has no `description`. A
  value with an unquoted `: ` inside, such as `description: Use when: ...`, is
  quoted and parsed again before the workflow is skipped.
- A workflow is also left out when `description` is longer than 1024
  characters or `SKILL.md` is longer than 500 lines. The Agent Skills spec
  gives these numbers as guidelines; this plugin uses them as limits, because a
  loaded workflow keeps its whole `SKILL.md` in the prompt. Move long details
  into separate files.
- `workflow-load-instructions` uses the same rules: it refuses to load a
  workflow that is not listed, and its error says why.
- A workflow is listed with a warning when `name` is missing, differs from the
  directory name, is longer than 64 characters or has characters other than
  lowercase letters, digits and single hyphens. The workflow is always listed
  and loaded by its directory name.
- The description is shown as YAML gives it. A plain or folded (`>`)
  description becomes one line, and a block (`|`) description keeps its line
  breaks. Only a `---` at the start of a line ends the frontmatter, so an
  indented `---` inside a block description stays part of it.

Earlier versions of the plugin read the description from a `description.txt`
file. That file is no longer read: move its text into the `description` field.
A workflow that still has `description.txt` and no valid description is
skipped with an error that says so.

`skill.metta` (optional) contains the list of tools which the workflow adds
while it is active and additional MeTTa functions which are mentioned in
`SKILL.md` file.

Tool descriptions are added as high-level expressions. Each such expression
adds one tool to the Omega. First atom of the expression is `skill` symbol
and other atoms are parameters of the `add-skill` function, which the plugin
calls to add the tool when the workflow is loaded. See
[`skills.metta`](/src/skills.metta) for details. Tool implementations are
added as MeTTa functions.

For example:
```metta
(skill test-skill "Test skill to demonstrate workflow by sending message to the user" (message))

(= (test-skill $message)
   (send $message))
```

## Using workflow

The plugin adds three tools of its own. `workflow-load-instructions` loads the
workflow with the given name and adds the tools from its `skill.metta`.
`workflow-unload-instructions` takes no arguments and removes the active
instructions together with all tools added from `skill.metta` files.
`workflow-refresh-list` is described below. While a workflow is active,
`workflow-load-instructions` rejects another one with the error `There is an
active workflow`, so the first workflow has to be unloaded before the next one
is loaded.

Start an agent and ask it to use the workflow. For the test workflow above
send: `Demonstrate workflow plugin`

New workflows put into `pluginWorkflowInstructionsDir` while the agent is
running become available after the agent calls the `workflow-refresh-list`
tool. Ask the agent to refresh the list of workflows, or just ask it to load
the new workflow by name.

## Workflow parameters

Workflow plugin Omega configuration parameters:
- `pluginWorkflowInstructionsDir` - path to the directory which contains
  available workflows. Default value is `<project
  root>/plugins/workflow/instructions`
- `pluginWorkflowMemoryDir` - path to the directory to keep workflow working
  files when workflow is active. Default value is `<project
  root>/memory/workflow_space`

One can set this parameters passing them as a command line arguments. For
example:
```sh
sh run.sh run.metta pluginWorkflowInstructionsDir="<path>"
```
