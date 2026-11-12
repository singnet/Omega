!(import! &self ./tests/res/router_setup)

; Basic prompts stay routine; failure signals and multiple user turns escalate.
!(test (default-LLM-ROUTER "segment_user hello") routine)
!(test (default-LLM-ROUTER "segment_user hello segment_tool alert_failed") premium)
!(test (default-LLM-ROUTER "segment_user first segment_user second") premium)

; Nine issues are routine; the tenth selects premium.
!(test (default-LLM-ROUTER "segment_user hello segment_tool one segment_tool two segment_tool three segment_tool four segment_tool five segment_tool six segment_tool seven segment_tool eight") routine)
!(test (default-LLM-ROUTER "segment_user hello segment_tool one segment_tool two segment_tool three segment_tool four segment_tool five segment_tool six segment_tool seven segment_tool eight segment_tool nine") premium)

; Escalation must not leak temporary prompt state into the next request.
!(test (default-LLM-ROUTER "segment_user hello again") routine)
!(test (collapse (match &plugin-default (prompt_atom $term $seq) leaked)) ())
!(test (collapse (match &plugin-default ("segment_user" $terms) leaked)) ())
!(test (collapse (match &plugin-default ("segment_tool" $terms) leaked)) ())
