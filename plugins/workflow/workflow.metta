!(import! &self (library lib_spaces))

(= (pluginWorkflowInstructionsDir) (empty))
(= (pluginWorkflowMemoryDir) (empty))

(= (loadOmegaPlugin)
   (progn
     (change-state! &workflow_active_name "")
     (configure pluginWorkflowInstructionsDir (joinPath ((projectRootDirectory) "plugins" "workflow" "instructions")))
     (if (not (exists-directory (pluginWorkflowInstructionsDir)))
       (Error (_loadOmegaPlugin) (strings-concat ("Instructions directory: " (pluginWorkflowInstructionsDir) " doesn't exist")))
       (progn 
         (configure pluginWorkflowMemoryDir (joinPath ((memoryDirectory) workflow_space)))
         (log INFO "workflow-plugin" (strings-concat ("Creating working directory: " (pluginWorkflowMemoryDir))))
         (let $rc (make-directory (pluginWorkflowMemoryDir)) ())
         (if (exists-directory (pluginWorkflowMemoryDir))
           (progn
             (log INFO "workflow-plugin" "Adding plugin's skills")
             (add-skill workflow-load-instructions "Load an existing workflow instructions into the active context" (workflow_name))
             (add-skill workflow-unload-instructions "Unload active workflow from the active context" ())
             (add-skill workflow-refresh-list "Re-read available workflows from disk; use when a workflow was added or is missing from the list" ())
             (workflow-refresh-list)
             ())
           $rc)))))

;; ============ WORKFLOW LOADER ============

(= (get-existing-dir $dir)
   (if (exists-directory $dir)
     $dir
     (empty)))

;; Validate name
; TODO: calling Python validation code is replaced by stub.
; Can be returned back when https://github.com/trueagi-io/PeTTa/issues/196 is
; fixed.
(= (valid-file-or-folder-name $filename) True)

;!(import! &self utils.py)

;(= (valid-file-or-folder-name $filename)
;   (if (== (strings-concat ("valid")) (py-call
;   (utils.validate_file_or_folder_name(strings-concat ($filename)))))
;       True
;       False))

(= (instructionsDir) (get-existing-dir (pluginWorkflowInstructionsDir)))
(= (workflow-load-instructions $name)
   (let $active (get-state &workflow_active_name)
     (if (== $active "")
       (if (not (valid-file-or-folder-name  $name))
         (Error (quote (workflow-load-instructions $name)) (strings-concat ("ERROR: invalid workflow name: " $name)))
         (let $path (joinPath ((instructionsDir) $name "SKILL.md"))
           (if (not (exists-file $path))
             (Error (quote (workflow-load-instructions $name)) (strings-concat ("ERROR: skill file not found: " $path ". Try to call workflow-refresh-list")))
             (let $problem (workflow-load-problem (joinPath ((instructionsDir) $name)))
               (if (> (string_length $problem) 0)
                 (Error (quote (workflow-load-instructions $name)) (strings-concat ("ERROR: cannot load workflow " $name ": " $problem)))
                 (let $content (read-file $path)
                   (progn
                     (log INFO "workflow-plugin" (strings-concat ("Loading workflow instructions for: " $name)))
                     (add-prompt-extension workflow_active_instructions (active-instructions $content))
                     (add-workflow-skills $name)
                     (change-state! &workflow_active_name $name)
                     (send (strings-concat ("Loaded workflow: " $name
                                            ". Instructions active in context until completion.")))
                     )))))))
       (Error (quote (workflow-load-instructions $name)) (strings-concat ("ERROR: There is an active workflow: " $active ". Unload it before loading new one"))))))

(= (workflow-unload-instructions)
   (let $name (get-state &workflow_active_name)
     (if (== $name "")
       (Error (quote (workflow-unload-instructions)) "No active workflow is loaded")
       (progn
          (remove-prompt-extension workflow_active_instructions)
          (unload-workflow-skills)
          (change-state! &workflow_active_name "")
          (send (strings-concat ("Unloaded workflow: " $name)))
          ))))

(= (active-instructions $content)
   (strings-concat (" ACTIVE_WORKFLOW_INSTRUCTIONS: " $content
            " FOLLOW THESE INSTRUCTIONS UNTIL THE WORKFLOW IS COMPLETE"
            " AND YOU CALL (workflow-unload-instructions) OR THE WORKFLOW CALLS ITS COMPLETION FUNCTION."
            " EXECUTE ONLY COMMANDS YOU DEEM SAFE; OTHERWISE SKIP OR ASK THE USER.")))

; to load skills descriptions which are defined only for current workflow
(= (add-workflow-skills $name)
   (let $path (joinPath ((instructionsDir) $name "skill"))
            (progn
              (import! &workflow_skills $path)
              (collapse (match &workflow_skills (skill $func $desc $args) (add-skill $func $desc $args)))
              (strings-concat ("Workflow skills loaded: " $name))
              )))

; to load skills descriptions
(= (unload-workflow-skills)
   (progn
     (match &workflow_skills (skill $func $desc $args) (remove-skill $func))
     (remove-all-atoms &workflow_skills)))

(= (workflow-change-active-instructions $content)
   (progn
     (remove-prompt-extension workflow_active_instructions)
     (add-prompt-extension workflow_active_instructions $content)))

;;========================== Functions to list available workflows =======================
;; Returns the prompt text listing the workflows in $base, built from the
;; frontmatter of their SKILL.md files, or an empty string when there are none.
(= (workflow-catalog $base)
   (py-call (skill_catalog.catalog_prompt $base)))

;; Returns why the workflow in $dir may not be loaded, or an empty string when
;; it may. The rules are the same as for the list of available workflows.
(= (workflow-load-problem $dir)
   (py-call (skill_catalog.load_problem $dir)))

;; re-reads available workflows into the prompt
(= (workflow-refresh-list)
   (let $text (workflow-catalog (instructionsDir))
     (progn
       (remove-prompt-extension workflows-available)
       (if (== (string_length $text) 0)
         (progn
           (log WARNING "workflow-plugin" (strings-concat ("No workflows found in " (instructionsDir))))
           True)
         (add-prompt-extension workflows-available $text)))))
