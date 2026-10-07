; Declare skills to be added to the agent skills when workflow is loaded and
; removed on unloading workflow

(skill research-start "Create research project folders" (research_name topic))
(skill research-step "Mark research step done" (research_name step result next_action))
(skill research-checkpoint "Pause for user approval" (researchname message))
(skill research-complete "Finish research and unload workflow" (researchname))
(skill load-research-dynamic-instructions " Load a generated file into active context" (researchname_in_quotes filename_in_quotes))
(skill researchDir "Get research directory" ())

;; Actual skills implementation

;; Build a safe path or empty string if validation fails
(= (safe-instruction-path $project_dir $research-name $filename)
   ; TODO: calling Python validation code is replaced by stub.
   ; Can be returned back when https://github.com/trueagi-io/PeTTa/issues/196 is
   ; fixed.
   ;(py-call (utils.safe_path $project_dir $research-name $filename)))
   (joinPath ($project_dir $research-name $filename)))

(= (load-research-dynamic-instructions  $research-name $filename)
    (let $d (researchDir) (load-dynamic-instructions $d $research-name $filename)))

; loads instructions created during workflow
(= (load-dynamic-instructions $project_dir $research-name $filename)
   (if (not (valid-file-or-folder-name $research-name))
       (send (strings-concat ("ERROR: invalid name: " $research-name)))
       (if (not (valid-file-or-folder-name $filename))
           (send (strings-concat ("ERROR: invalid filename: " $filename)))
           (let $path (safe-instruction-path $project_dir $research-name $filename)
                (if (== $path "")
                    (send (strings-concat ("ERROR: path traversal rejected for " $research-name "/" $filename)))
                    (load-dynamic-instructions-safe $path $research-name $filename))))))

; actually loads the file (internal). Only called after validation.
(= (load-dynamic-instructions-safe $path $research-name $filename)
   (if (not (exists-file $path))
       (send (strings-concat ("ERROR: file not found: " $path)))
       (let $content (read-file $path)
            (progn
              (log INFO "workflow-research" (strings-concat "Loading file into prompt: " $path))
              (workflow-change-active-instructions $content)
              (send (strings-concat ("Loaded " $filename " for " $research-name ". Following instructions.")))
             ))))


(= (researchDir)
   (let $dir (get-existing-dir (pluginWorkflowMemoryDir))
     (joinPath ($dir "research"))))


;; LLM decides to start research
;; creates folders for research and asks to create 00_problem.md then search online
(= (research-start $research-name $topic)
    (if (valid-file-or-folder-name $research-name)
       (progn (shell (strings-concat ("mkdir -p " (researchDir) "/" $research-name "/src")))
              (shell (strings-concat ("mkdir -p " (researchDir) "/" $research-name "/data")))
              (shell (strings-concat ("mkdir -p " (researchDir) "/" $research-name "/runs")))
              (shell (strings-concat ("mkdir -p " (researchDir) "/" $research-name "/figures")))
              (write-file (strings-concat ((researchDir) "/" $research-name "/topic.txt")) $topic)
              (send (strings-concat ("Created project: " (researchDir) "/" $research-name "\n"
                             "Folders: src/ data/ runs/ figures/")))
              )
        (send (strings-concat ("Invalid name: " $research-name ". Only a-z, 0-9, - and _ allowed.")))
     )
)

;; update current step
(= (research-step $research-name $step $result $next)
    (if (valid-file-or-folder-name $research-name)
        (progn
            (send (strings-concat ("[" $research-name "] done: " $step)))
            (addToHistory (strings-concat  ("RESEARCH [" $research-name "] done: " $step " — " $result "; next: " $next )) )
            (strings-concat ("Done: " $step)))
        (send (strings-concat ("Invalid name: " $research-name ". Only a-z, 0-9, - and _ allowed.")))
     )
)


;; Checkpoint: wait user's response
(= (research-checkpoint $research-name $message)
    (if (valid-file-or-folder-name $research-name)
        (progn
              (send (strings-concat ("CHECKPOINT [" $research-name "]\n" $message "\n"
                             "Reply to continue.")))
              (addToHistory  (strings-concat ("RESEARCH_ACTIVE: " $research-name
                            " STATUS: WAITING_FOR_USER")))
              "Waiting for user")
        (send (strings-concat ("Invalid name: " $research-name ". Only a-z, 0-9, - and _ allowed.")))
     )
)

;; Unload research skill
(= (research-complete $research-name)
    (if (valid-file-or-folder-name $research-name)
        (progn (workflow-unload-instructions)
              (send (strings-concat ("Research complete: " $research-name
                             "\nResults in " (researchDir) "/" $research-name "/"
                             "\nWorkflow unloaded from context.")))
              (addToHistory  (strings-concat  ("RESEARCH [" $research-name "] COMPLETED")))
              "Research complete, workflow unloaded")
         (send (strings-concat ("Invalid name: " $research-name ". Only a-z, 0-9, - and _ allowed.")))
      )
)
