(= (contextFrame) (empty))

(= (contextPluginDirectory)
   (joinPath ((projectRootDirectory) "plugins" "context")))

!(import! &plugin-context (joinPath ((contextPluginDirectory) "contextframe")))
!(import! &plugin-context (joinPath ((contextPluginDirectory) "contextframeskill")))

(= (loadOmegaPlugin)
   (progn
     (configure contextFrame disabled)
     (if (== (contextFrame) enabled)
         (progn
           ; Unlike import!, py-call propagates dependency errors to stop startup.
           (py-call (importlib.import_module "frame_helpers"))
           (py-call (importlib.import_module "frame_relation"))
           (initContextFrame)
           (register-context-frame-skills)
           (add-prompt-extension context-frame-skills
             (once (py-str ("CONTEXT_FRAME_SKILLS: " (contextFramesSkills)))))
           (set-context-provider context-frame-provider)
           (log INFO "context-plugin" "Context frames are enabled"))
         (if (== (contextFrame) disabled)
             (log INFO "context-plugin" "Context frames are disabled")
             (Error (_loadOmegaPlugin) "contextFrame must be enabled or disabled")))))

(= (context-frame-provider (Input $message $isNew))
   (let $hadFrame (if $isNew (cfv2-has-current-frame) False)
     (progn
       (if $isNew (ctx-ingest-user-message $message) ())
       (if (not (ctx-has-active-goals)) (ctx-maintain-frame) ())
       (if $isNew
           (if $hadFrame
               "NEW_INPUT_HAS_BEEN_ADMITTED_AS_ACTIVE_FRAME. Continue current frame or switch-frame to a higher-priority admitted frame if appropriate."
               "NEW_INPUT_HAS_BEEN_ADMITTED_AS_ACTIVE_FRAME.")
           (if (cfv2-has-current-frame)
               "NO NEW USER INPUT. Continue only if the context frame contains an active useful goal or select relevant frame from the active space."
               "NO NEW USER INPUT. No active frame. Consider switching your mode to pursue frames registered with mode = Slow or create a new autonomous goal.")))))

(= (context-frame-provider Prompt)
   (py-str ("RUNTIME-PROMPT: " (getContextFramePrompt) (newline)
            "CURRENT_CONTEXT_FRAME_S_EXPR: " (contextFrameForPrompt))))

(= (context-frame-provider BeforeRequest)
   (get-state &cfv2-current-frame-id))

(= (context-frame-provider (AfterTools $frameID $commands $results))
   (progn
     (ctx-record-command-batch-for-frame $frameID $commands $results)
     (ctx-maintain-frame)
     ()))

(= (context-frame-provider Idle)
   (if (== (get-state &cfv2-root-mode) Fast) (switch-mode) ()))

(= (getContextFramePrompt)
   (let $path (joinPath ((contextPluginDirectory) "prompt_context_frame.txt"))
     (if (exists-file $path)
         (read-file $path)
         "")))
