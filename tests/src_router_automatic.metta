!(import! &self ./tests/res/router_setup)

; Basic prompts stay routine; failure signals and multiple user turns escalate.
!(test (default-LLM-ROUTER "role_user hello") routine)
!(test (default-LLM-ROUTER "role_user hello role_tool alert_failed") premium)
!(test (default-LLM-ROUTER "role_user first role_user second") premium)

; Nine issues are routine; the tenth selects premium.
!(test (default-LLM-ROUTER "role_user hello role_tool one role_tool two role_tool three role_tool four role_tool five role_tool six role_tool seven role_tool eight") routine)
!(test (default-LLM-ROUTER "role_user hello role_tool one role_tool two role_tool three role_tool four role_tool five role_tool six role_tool seven role_tool eight role_tool nine") premium)

; Escalation must not leak temporary prompt state into the next request.
!(test (default-LLM-ROUTER "role_user hello again") routine)
!(test (collapse (match &plugin-default (prompt_atom $term $seq) leaked)) ())
!(test (collapse (match &plugin-default ("role_user" $terms) leaked)) ())
!(test (collapse (match &plugin-default ("role_tool" $terms) leaked)) ())
