# Workflow loading plugin

Workflow loading plugin allows loading agent skills written according to the
[common specification](https://agentskills.io/specification). Each workflow
consists of short description, detailed description in `SKILL.md` file and
optionally `skill.metta` file which contains related skills implementation in
MeTTa language.

[Research workflow](./core-skills/research-workflow) is a ready-to-use example
of the workflow. One can try it starting the agent and asking it doing a
research on some topic:
```
Start research. Build a classifier for iris dataset using sklearn, compare
logistic regression and random forest.
```

## Workflow files

`description.txt` (required) contains short usually one-line workflow
description for the agent. For example:
```
When user asks to demonstrate workflow plugin load test-workflow instructions: (workflow-load-skills \"test-workflow\")
```

`SKILL.md` (required) is an agent skills file in the [common
format](https://agentskills.io/specification). For example:
```md
---
name: test-workflow
description: Created to check how SKILL.md is loaded to Omega.
---
Next are instructions and MeTTa  functions  that should be performed step by step
# Test Workflow (Omega)
## Step 1 - demonstrate usage of skills
- Call test-skill with "This is a test workflow demonstration" message
## Step 2 - complete workflow
- Call `(workflow-unload-skills)`
```

`skill.metta` (optional) contains the list of the Omega skills to load
when workflow is active and additional MeTTa functions which are mentioned in
`SKILL.md` file.

Skill description are added as high-level expressions. Each such expression
adds one skill to the Omega. First atom of the expression is `skill` symbol
and other atoms are parameters of the `add-skill` function. See
[skills.metta](/src/skills.metta) for details. Skill implementations are
added as MeTTa functions.

For example:
```metta
(skill test-skill "Test skill to demonstrate workflow by sending message to the user" (message_in_quotes))

(= (test-skill $message)
   (send $message))
```

## Using workflow

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
skill. Ask the agent to refresh the list of workflows, or just ask it to load
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
