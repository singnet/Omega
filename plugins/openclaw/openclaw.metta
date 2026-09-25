!(import! &self (library Omega ./plugins/openclaw/openclaw.py))

(= (openClawEnabled) (empty))
(= (openClawURL) (empty))
(= (openClawAgent) (empty))

(= (loadOmegaPlugin)
    (progn
        ; Enable or disable the integration.
        (configure openClawEnabled disabled)
        ; OpenClaw Gateway base URL, http://... or https://...
        ; In Docker this is only a fallback: the real target and its token
        ; are set at container start (openclaw_url=, OMEGA_OPENCLAW_TOKEN)
        ; and injected by the local Nginx proxy. See plugins/openclaw/README.md.
        (configure openClawURL "")
        ; OpenClaw agent name. "main" by default
        (configure openClawAgent "main")
        (if (== (openClawEnabled) enabled)
            (if (== (openClawURL) "")
                (Error
                    (_loadOmegaPlugin)
                    "OpenClaw integration is enabled, but openClawURL is not configured")
                (progn
                    (log INFO "openclaw-plugin" "OpenClaw integration is enabled")
                    (add-skill
                        delegate-task-to-openclaw-agent
                        "Delegate a self-contained task to an external OpenClaw agent in a new separate session. Returns an id immediately, the reply arrives later on its own as an OPENCLAW_RESULT line."
                        (task))
                    (add-heartbeat-listener
                        openclaw
                        (|-> ($iter) (openclaw-collect-results $iter)))))
            (log INFO "openclaw-plugin" "OpenClaw integration is disabled"))))

(= (delegate-task-to-openclaw-agent $message)
    (py-call (
        openclaw.send
        $message
        (openClawURL)
        (openClawAgent)
    )))

; Delegations run off the agent loop, so their replies are picked up here once
; per iteration and appended to the history, which - unlike a prompt extension
; or LAST_SKILL_USE_RESULTS - also holds them while the agent is idle. Reading
; the Python side is the only safe direction: the worker threads never touch
; the atomspace.
;
; append-file rather than appendToHistory/library: this plugin's own
; definitions live in the plugin's own MeTTa space (src/plugin.metta),
; library's file-spec resolves against whichever space an
; evaluation started from - it does not find the Omega alias
; reached this way. append-file takes a plain path and has no such
; dependency, so the path is built with projectRootDirectory/joinPath
; (same as pluginWorkflowInstructionsDir in workflow.metta) instead of
; going through library.
(= (openclaw-collect-results $iteration)
    (let $results (repr (py-call (openclaw.take_completed)))
        (if (> (string_length $results) 0)
            (append-file
                (joinPath ((projectRootDirectory) "memory" "history.metta"))
                (swrite ((get_time_as_string) (newline) $results (newline))))
            ())))
