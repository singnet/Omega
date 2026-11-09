---
name: custom-skill-management
description: Create, edit and delete custom skills (workflows). Custom skills
  are stored in the custom skills directory and survive Omega updates and
  container recreation.
---

Next are instructions and MeTTa functions that should be performed step by step

# Custom Skill Management (Omega)
## Skill types

- Core skills are shipped with Omega and are read-only. Never create, change
  or delete them.
- Custom skills are managed by the user. Only custom skills can be created,
  edited or deleted with this workflow.
- A custom skill with the same name as a core skill overrides the core one.
## Workflow skills
- `(custom-skill-list)` - names of existing custom skills
- `(custom-skill-read skill_name file_name)` - read a file of a custom skill
- `(custom-skill-write skill_name file_name content)` - create or overwrite a
  file of a custom skill, the skill directory is created automatically
- `(custom-skill-delete skill_name)` - delete a custom skill with all its files

`file_name` is one of `SKILL.md`, `description.txt`, `skill.metta`.
Manage skill files only with the skills above, never with `write-file`,
`delete-file` or `shell`.

## Skill files
- `SKILL.md` (required) - skill instructions, see the template below
- `description.txt` (required) - one line which tells when to load the skill
- `skill.metta` (optional) - MeTTa functions the skill adds, only if the skill
  really needs its own functions or stores files

## Working files
- Files are only for data which must survive the skill completion: results,
  notes, history. Progress of a running skill (current step, score, collected
  answers) is tracked with `pin`, not in files.
- A skill which stores files keeps them only in its own working directory in
  the workflow space. Never anywhere else: not in the memory directory root,
  not in `/tmp`, not in paths taken from `get-io-policy`.
- Such skill MUST have `skill.metta` with the `<skill-name>-dir` skill, see
  the template below. `SKILL.md` gets the path by calling `(<skill-name>-dir)`
  and never contains hardcoded paths.
- `append-file` fails when the file doesn't exist yet, create the file with
  `write-file` first.

## Skill name rules
- 1-64 characters: lowercase letters `a-z`, digits `0-9` and hyphens `-` only
- does not start or end with a hyphen, has no two hyphens in a row
- the name is the same in the skill directory and in the `name` field of `SKILL.md`
IMPORTANT!!!: never call the workflow skills with a name which breaks these
rules. If the user asks for such a name, propose a valid one instead.

## Step 1 - Determine the operation
- Call `(custom-skill-list)`
- Determine what the user wants: create, edit or delete a custom skill. If it
  is not clear, ask the user.
- Follow the section of the operation below, then the Finish section.

## Create
### Step C1 - Gather requirements
- Find out what the skill does, when it should be used, its steps, whether it
  needs its own MeTTa functions and which files it produces. A skill which
  produces files needs `skill.metta` with `<skill-name>-dir`, see the Working
  files section.
- Ask only what is not clear yet, batch all questions into one message.

### Step C2 - Choose the name and check collisions
- Choose the name following the name rules.
- If the name is in `(custom-skill-list)`: such custom skill exists. Ask the
  user whether to replace it (then follow the Edit section) or to choose
  another name.
- If the name is in the list of available workflows but not in
  `(custom-skill-list)`: it is a core skill. Warn the user that the new custom
  skill will override the core one and ask for confirmation.

### Step C3 - Agree the skill with the user
- Send a short description of the skill: name, when it is used, its steps and
  the functions it adds (names and purpose only, no code). If the skill stores
  files, tell that they are kept in the skill working directory.
- **WAIT. Do NOT write files until the user approves.** If the user requests
  changes, revise the description and send it again.

### Step C4 - Write files
- Compose the files using the templates below.
- Write `description.txt`, then `skill.metta` if needed, then `SKILL.md` last:
  `(custom-skill-write <skill-name>_in_quotes "description.txt" "content")`
- Every call must return `WRITE-VERIFIED`. On failure report it to the user
  and go to Finish.

## Edit
### Step E1 - Choose the skill
- The skill must be in `(custom-skill-list)`. Core skills can't be edited:
  tell the user and go to Finish.

### Step E2 - Read the skill
- Read the existing files:
  `(custom-skill-read <skill-name>_in_quotes "SKILL.md")`,
  the same for `description.txt` and `skill.metta`. `skill.metta` may be absent.

### Step E3 - Agree the changes with the user
- Find out what to change if it is not clear yet.
- Send a short description of the changes: what is changed, added or removed
  and why. No code, no full file contents.
- **WAIT. Do NOT write files until the user approves.**

### Step E4 - Write changed files
- Write every changed file in full, not only the changed part:
  `(custom-skill-write <skill-name>_in_quotes "SKILL.md" "full new content")`
- Every call must return `WRITE-VERIFIED`. On failure report it to the user
  and go to Finish.

## Delete
### Step D1 - Choose the skill
- The skill must be in `(custom-skill-list)`. Core skills can't be deleted:
  tell the user and go to Finish.

### Step D2 - Confirm with the user
- Ask the user to confirm deleting the skill with all its files. If the skill
  overrides a core skill, tell that the core skill becomes active again.
- **WAIT. Do NOT delete until the user confirms.**

### Step D3 - Delete
- `(custom-skill-delete <skill-name>_in_quotes)`
- The call must return `DELETE-VERIFIED`. On failure report it to the user.

## Finish
- If any skill was written or deleted, call `(workflow-refresh-list)`. It is
  MANDATORY, otherwise the changes are not available until restart.
- Call `(workflow-unload-instructions)`
- Send the user a short report: what was done and with which skill. For a
  created or edited skill tell when it is used, or that the user can ask to
  load it by name.

## Templates
### description.txt
One line: when to load the skill and the command to load it.
```
When user asks to <when to use>, load <skill-name> instructions: (workflow-load-instructions "<skill-name>")
```

### SKILL.md
```
---
name: <skill-name>
description: <what the skill does and when to use it, up to 1024 characters>
---
Next are instructions and MeTTa functions that should be performed step by step
# <Skill Title> (Omega)
## Step 1 - <step name>
- <concrete actions and skill calls>
## Step N - Complete
- Call `(workflow-unload-instructions)`
```
- Steps are concrete, skills and functions are referenced by exact names.
- The workflow stays loaded across loop iterations and user messages until it
  is unloaded. A step which needs the user's reply ends with
  `**WAIT for the user's reply. Do NOT unload the workflow.**`
- `(workflow-unload-instructions)` is called only once, in the last step, when
  the whole task is complete or the user cancels it.

### skill.metta
```metta
; Skills added when the workflow is loaded and removed on unloading
(skill <skill-name>-<action> "<what it does>" (<arg_1> <arg_2>))

(= (<skill-name>-<action> $arg_1 $arg_2)
   <implementation>)
```
A skill which stores files also gets the working directory skill exactly as
below, the directory is created on call:
```metta
(skill <skill-name>-dir "Get working directory of the skill" ())

(= (<skill-name>-dir)
   (let $dir (joinPath ((pluginWorkflowMemoryDir) "<skill-name>"))
     (let $rc (make-directory-path $dir) $dir)))
```
- Every function used as a skill is declared with `(skill ...)` and
  implemented with `(= ...)`. A skill without arguments is declared with `()`.
- Function names start with `<skill-name>-` to avoid collisions with other
  skills.
- Working files follow the Working files section. Functions build their paths
  from the working directory:
  `(joinPath ((<skill-name>-dir) "results.md"))`
