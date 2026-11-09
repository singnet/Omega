---
name: research-workflow
description: End-to-end research workflow for Omega. Iterative planning,
  data acquisition, experiments, and write-up.
---
# Research Workflow (Omega)
This workflow guides you through problem definition, online research,
and creating a detailed execution plan. Once the user approves the plan,
it replaces these instructions and you follow it step by step.
## Project Structure
All projects live under `(let $d (researchDir) (strings-concat ($d "/<research-name>/")))`.
(researchDir) - is a tool which returns directory the research folders and files should be located
The `research-start` tool creates the base folders.
(researchDir)/<research-name>/
  topic.txt            # created by research-start
  00_problem.md        # research question, scope, metrics
  01_theory.md         # data sources, methods, assumptions
  02_plan.md           # full execution plan with concrete commands
  src/                 # all scripts
  data/                # raw and processed data
  runs/                # configs + metrics (JSON)
  figures/             # plots and charts
## Step-by-Step
Next are instructions and MeTTa  functions  that should be performed step by step
### Step 1 — Define the problem
- Call `(research-start <research-name>_in_quotes "topic")` to create project folders
- Write research question, scope, success metrics, constraints:
  `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/00_problem.md")) "content"))`
- `(research-step <research-name>_in_quotes "problem-defined" "question: X metric: Y"
                  "search online for related methods and data sources")`
### Step 2 — Research and create plan
- Search online for related methods and data sources:
  `(websearch "query")`
- Save findings:
  `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/01_theory.md")) "content"))`
- `(research-step <research-name>_in_quotes "theory-saved" "sources: X methods: Y"
                  "create plan and present to user")`
- Create the full execution plan using findings and the Plan Template below
- Send plan to user for review:
  `(send "PROPOSED PLAN:\n<full plan text>")`
- `(research-checkpoint <research-name>_in_quotes "Plan ready. Approve or suggest changes?")`
- **WAIT. Do NOT advance until user responds.**
### Step 3 — Plan approval
- If user approves:
save plan:
  `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/02_plan.md")) "approved plan text"))`
  `(research-step <research-name>_in_quotes "plan-approved" "milestones A B C"
                  "follow plan from Milestone A")`
IMPORTANT!!!: load plan to active &active_instructions variable:
  `(load-research-dynamic-instructions <research-name>_in_quotes "02_plan.md")` 
  take into account that this function receives 2 arguments <research-name> and "02_plan.md" both in quotes.
- If user requests changes:
  Revise plan, send again, wait again
## Plan Template
When writing `02_plan.md`, include ALL sections below.
The plan must be self-contained — after loading it replaces this file.
# Research Plan: <topic>
## Operating Rules
- Work autonomously. Make your own decisions on implementation details.
- Use `pin` to track current step between iterations.
- All file paths must be built from `(researchDir)` via `let`: e.g. `(let $d (researchDir) (strings-concat ($d "/<research-name>/...")))`
- Write code via `write-file`, run via `shell`. Never output code in `send`.
- Save seeds and versions in every script.
- Store metrics as JSON in `runs/`.
- Use `(research-step <research-name>_in_quotes "step" "result" "next")` after each milestone.
- Do NOT advance past a checkpoint until user responds.
- When to ask the user (batch questions into one message):
  - Missing credentials, access, or files
  - Ambiguous goal or success metric
  - Methodological choice that materially changes results
## Milestone A — Data Ready + Baseline
### A1 — Prepare data and baseline
- `<concrete data source and acquisition method>`
- Write: `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/src/baseline.py")) "code"))`
  Script: load data, preprocess, simple model, save runs/baseline.json
- Run: `(let $d (researchDir) (shell (strings-concat ("cd " $d "/<research-name> && python src/baseline.py"))))`
- `(research-step <research-name>_in_quotes "data-ready" "N rows, baseline=X"
                  "call research-checkpoint")`
- `(research-checkpoint <research-name>_in_quotes "Data ready. Baseline: X. Proceed?")`
- **WAIT for user.**
## Milestone B — Experiments
### B1 — <experiment name>
- Hypothesis: <what you expect>
- Write: `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/src/experiment_1.py")) "code"))`
- Run: `(let $d (researchDir) (shell (strings-concat ("cd " $d "/<research-name> && python src/experiment_1.py"))))`
- Save: `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/runs/exp1.json")) "metrics"))`
- `(research-step <research-name>_in_quotes "experiment-1" "metric=Y" "next experiment")`
### B2 — <next experiment>
...
## Milestone C — Results + Conclusions
### C1 — Write results
- `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/05_results.md")) "content"))`
- `(research-step <research-name>_in_quotes "results-written" "best: X" "write conclusions")`
### C2 — Conclusions
- `(let $d (researchDir) (write-file (strings-concat ($d "/<research-name>/06_conclusions.md")) "content"))`
- `(research-step <research-name>_in_quotes "conclusions-done" "summary"
                  "call research-checkpoint")`
- `(research-checkpoint <research-name>_in_quotes "Results ready. Next iteration? Proceed?")`
- **WAIT for user.**
## Milestone D — Complete
- `(research-complete <research-name>_in_quotes)`
## Stop/Pivot Conditions
- `<when to stop or change approach>`
