!(import! &self ./tests/res/router_setup)

; A user override persists across calls until explicitly cleared.
!(test (default-LLM-ROUTER "role_user /premium") premium)
!(test (default-LLM-ROUTER "role_user hello") premium)
!(test (default-LLM-ROUTER "role_user /routine") routine)
!(test (default-LLM-ROUTER "role_user hello") routine)

; Clearing the override still permits automatic escalation.
!(test (default-LLM-ROUTER "role_user /premium") premium)
!(test (default-LLM-ROUTER "role_user /routine role_tool alert_failed") premium)
!(test (collapse (match &plugin-default (role /premium) latched)) ())
!(test (default-LLM-ROUTER "role_user hello") routine)
