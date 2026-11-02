(= (register-context-frame-skills)
   (progn
     (add-skill new-frame "Create a user-directed task frame" (description))
     (add-skill new-autonomous-frame "Create a low-priority Slow autonomous frame" (description))
     (add-skill switch-mode "Toggle Fast/Slow root mode" ())
     (add-skill switch-frame "Focus an admitted frame" (frameID))
     (add-skill send_probe "Extend Slow-mode processing time" ())
     (add-skill show-root-frame "Inspect root frame" ())
     (add-skill show-current-frame "Inspect current frame" ())
     (add-skill show-frame-index "Inspect frame index" ())
     (add-skill show-active-framespace "Inspect active frames" ())
     (add-skill show-completed-framespace "Inspect completed frames" ())
     (add-skill show-frame-relation "Inspect frame relations" (frameID))
     (add-skill ctx-add-hypothesis "Record a hypothesis in current frame" (hypothesis_id hypothesis))
     (add-skill ctx-add-result "Record a result in current frame" (variant metrics))
     (add-skill complete-goals-stm "Complete current frame in short-term state" (summary))
     (add-skill complete-goals-ltm "Complete current frame and preserve reusable memory" (summary))
     (add-skill clear-frame-junk "Clear transient frame hypotheses and results" (summary))
     ()))

;; Skills for frame management
(= (contextFramesSkills)
      ("CONTEXT_FRAME_MANAGEMENT_SKILLS:"
       "- Create top-level frame: new-frame description" (newline)
       "- Create low-priority Slow autonomous frame: new-autonomous-frame description" (newline)
       "- Toggle Fast/Slow root mode: switch-mode" (newline)
       "- Focus an admitted frame: switch-frame frameID" (newline)
       "- Extend Slow-mode processing time without going into sleep: send_probe" (newline)
       "- Inspect root/current frame: show-root-frame | show-current-frame" (newline)
       "- Inspect frame spaces: show-frame-index | show-active-framespace | show-completed-framespace" (newline)
       "- Inspect frame relations/dependency of the composed frames: show-frame-relation frameID" (newline)
       "- Record hypothesis: ctx-add-hypothesis id hypothesis" (newline)
       "- Record result: ctx-add-result variant metrics" (newline)
       "- Complete to short-term state: complete-goals-stm summary" (newline)
       "- Complete with durable reusable memory: complete-goals-ltm summary" (newline)
       "- Clear transient frame data: clear-frame-junk summary"))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; User-facing / skill-friendly helpers
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (new-frame $description)
   (cfv2-create-frame-from-user-message $description))

(= (new-autonomous-frame $description)
   (cfv2-create-autonomous-frame $description 0.5 Slow))

(= (switch-frame $frameID)
   (cfv2-load-frame $frameID))

(= (show-root-frame)
   (cfv2-root-frame))

(= (show-current-frame)
   (cfv2-current-frame))

(= (show-frame-index)
   (get-state &cfv2-frame-indexspace))

(= (show-active-framespace)
   (get-state &cfv2-active-framespace))

(= (show-completed-framespace)
   (get-state &cfv2-completed-framespace))

(= (show-frame-relation $frameID)
   (cfv2-get-relation $frameID))

(= (switch-mode)
   (cfv2-switch-mode))

(= (send_probe) (progn (change-state! &loops 25) ("ALIVE PROBE SENT")))

; (= (create-sub-frame $description)
;    (cfv2-create-sub-frame $description 0.8 (cfv2-make-deliverable $description)))

(= (ctx-add-hypothesis $id $hypothesis)
   (cfv2-add-hypothesis $id $hypothesis))

(= (ctx-add-result $variant $metrics)
   (cfv2-add-result $variant $metrics))

(= (ctx-set-certified-method $description $parameters $evalProtocol $hash)
   (cfv2-set-certified-method $description $parameters $evalProtocol $hash))

(= (ctx-add-deliverable $artifact)
   (cfv2-add-deliverable $artifact))

(= (compact-frame $summary)
   (progn
      (ctx-record-history FrameCompacted $summary)
      (change-state! &ctx-history-summary
         (last_chars
            (py-str
               ((get-state &ctx-history-summary)
                " | Compact: "
                $summary))
            (ctxHistorySummaryLimit)))
      (ctx-rebuild-history)
      (currentContextFrame)))

(= (complete-goals-stm $summary)
   (once (cfv2-complete-current-frame-to-stm $summary)))

(= (complete-goals-ltm $summary)
   (once (cfv2-complete-current-frame-to-ltm $summary)))

(= (clear-frame-junk $summary)
   (once (cfv2-clear-current-frame-junk $summary)))
