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
