!(import! &self (library lib_spaces))

(= (pluginWorkflowInstructionsDir) (empty))
(= (pluginWorkflowMemoryDir) (empty))

(= (loadOmegaPlugin)
   (progn
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
             (let $workflows (join (newline) (cons-atom "Available workflows: " (workflow-list-available)))
               (add-prompt-extension workflows-available $workflows))
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
   (if (not (valid-file-or-folder-name  $name))
       (send (strings-concat ("ERROR: invalid workflow name: " $name)))
       (let $path (joinPath ((instructionsDir) $name "SKILL.md"))
            (if (not (exists-file $path))
                (send (strings-concat ("ERROR: skill file not found: " $path)))
                (let $content (read-file $path)
                     (progn
                       (add-prompt-extension workflow_active_instructions (active-instructions $content))
                       (add-workflow-skills $name)
                       (change-state! &workflow_active_name $name)
                       (send (strings-concat ("Loaded workflow: " $name
                                     ". Instructions active in context until completion.")))
                       (addToHistory (strings-concat ("Workflow skills loaded: " $name)))
                     ))))))

(= (workflow-unload-instructions)
   (let $name (get-state &workflow_active_name)
     (if (== $name "")
       (send "No active workflow is loaded")
       (progn
          (remove-prompt-extension workflow_active_instructions)
          (unload-workflow-skills)
          (change-state! &workflow_active_name "")
          (send (strings-concat ("Unloaded workflow: " $name)))
          (addToHistory (strings-concat ("Workflow skills unloaded: " $name)))
       ))))

(= (active-instructions $content)
   (strings-concat (" ACTIVE_WORKFLOW_INSTRUCTIONS: " $content
            " FOLLOW THESE INSTRUCTIONS UNTIL THE WORKFLOW IS COMPLETE"
            " AND YOU CALL (unload-instructions) OR THE WORKFLOW CALLS ITS COMPLETION FUNCTION."
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

;;========================== Functions to load workflow description =======================
;; returns workflow name and its description
(= (workflow-list-available)
   (let*  ( ($base (instructionsDir))
            ($dirs (directory-dirs $base)))
        (collect-description $dirs $base)))

;; collects workflow description from description.txt
(= (collect-description () $base) ())
(= (collect-description (cons $first $tail) $base)
   (let*  (($path  (joinPath ($base $first "description.txt")))
           ($rest (collect-description $tail $base)))
     (if (exists-file $path)
       (cons-atom (strings-concat ($first ": " (read-file $path))) $rest)
       $rest)))

( = (directory-files $dir)
   (progn (translatePredicate (directory_files $dir $files))
          $files)
)

( = (directory-dirs $dir)
  (let $f (directory-files $dir)
       (filter-dirs  $f $dir)
   )
)

(= (filter-dirs () $dir) ())
(= (filter-dirs (cons $head $tail) $dir)
   (progn (translatePredicate (atom_string $head $first))
          (let* (
                 ($fullpath (joinPath ($dir $first)))
                 ($rest     (filter-dirs $tail $dir)))
            (if (or (== $first ".") (== $first ".."))
              $rest
              (if (exists-directory $fullpath)
                (cons-atom $first $rest)
                $rest))
            )
          )
   )
