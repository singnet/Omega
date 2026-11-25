# Workflow loading plugin

Workflow loading plugin allows loading skills written in the [Agent Skills
format](https://agentskills.io/specification). A skill is a directory with a
`SKILL.md` file, and this plugin refers to a skill as a workflow. Each workflow
consists of short description in `description.txt` file, detailed description
in `SKILL.md` file and optionally `skill.metta` file which contains the
implementation of the related tools in MeTTa language.

[Research workflow](./core-skills/research-workflow) is a ready-to-use example
of the workflow. One can try it starting the agent and asking it doing a
research on some topic:
```
Start research. Build a classifier for iris dataset using sklearn, compare
logistic regression and random forest.
```

## Workflow files

`description.txt` (required) contains short usually one-line workflow
description for the agent. The file is specific to this plugin and is not part
of the Agent Skills format. When the agent starts, the plugin adds the
descriptions of all workflows to the prompt, so the agent knows which
workflows it can load. A workflow without `description.txt` is not listed. An
example of the file:
```
When user asks to demonstrate workflow plugin load test-workflow skills: (workflow-load-skills \"test-workflow\")
```

`SKILL.md` (required) is the skill file in the [Agent Skills
format](https://agentskills.io/specification). When the workflow is loaded, the
plugin puts the whole file into the prompt as the active workflow skills.
The plugin does not parse the frontmatter. The workflow name is the name of its
directory, and the prompt lists the workflow with the text of
`description.txt`. For example:
```md
---
name: test-workflow
description: Created to check how SKILL.md is loaded to Omega.
---
Next are skills and MeTTa  functions  that should be performed step by step
# Test Workflow (Omega)
## Step 1 - demonstrate usage of tools
- Call test-skill with "This is a test workflow demonstration" message
## Step 2 - complete workflow
- Call `(workflow-unload-skills)`
```

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

The plugin adds three tools of its own. `workflow-load-skills` loads the
workflow with the given name and adds the tools from its `skill.metta`.
`workflow-unload-skills` takes no arguments and removes the active
skills together with all tools added from `skill.metta` files.
`workflow-refresh-list` is described below. While a workflow is active,
`workflow-load-skills` rejects another one with the error `There is an
active workflow`, so the first workflow has to be unloaded before the next one
is loaded.

Start an agent and ask it to use the workflow. For the test workflow above
send: `Demonstrate workflow plugin`

## Core and custom skills

Workflows are looked up in two directories:
- core skills shipped with Omega are kept in
  `pluginWorkflowCoreSkillsDir` and are updated together with Omega;
- custom skills are kept in `pluginWorkflowCustomSkillsDir` which is
  placed in the memory directory by default, so they survive container
  restarts and image updates. The directory is created on start if missing.

A custom skill overrides the core skill with the same name. To change a core
skill, copy its directory into `custom-skills` and edit the copy.

New workflows put into `pluginWorkflowCustomSkillsDir` while the agent is
running become available after the agent calls the `workflow-refresh-list`
tool. Ask the agent to refresh the list of workflows, or just ask it to load
the new workflow by name.

## Workflow parameters

Workflow plugin Omega configuration parameters:
- `pluginWorkflowCoreSkillsDir` - path to the directory which contains
  core skills. Default value is `<project_root>/plugins/workflow/core-skills`
- `pluginWorkflowCustomSkillsDir` - path to the directory which contains
  custom skills. Default value is `<memoryDirectory>/workflow/custom-skills`
- `pluginWorkflowMemoryDir` - path to the directory to keep workflow working
  files when workflow is active. Default value is `<memoryDirectory>/workflow/space`

Custom and working directories are created on start together with missing
parent directories.

One can set this parameters passing them as a command line arguments. For
example:
```sh
sh run.sh run.metta pluginWorkflowCoreSkillsDir="<path>"
```
