!(import! &self (library lib_spaces))

(= (pluginWorkflowCoreSkillsDir) (empty))
(= (pluginWorkflowCustomSkillsDir) (empty))
(= (pluginWorkflowMemoryDir) (empty))

(= (loadOmegaPlugin)
   (progn
     (change-state! &workflow_active_name "")
     (configure pluginWorkflowCoreSkillsDir (joinPath ((projectRootDirectory) "plugins" "workflow" "core-skills")))
     (if (not (exists-directory (pluginWorkflowCoreSkillsDir)))
       (Error (_loadOmegaPlugin) (strings-concat ("Core skills directory: " (pluginWorkflowCoreSkillsDir) " doesn't exist")))
       (progn
         (configure pluginWorkflowCustomSkillsDir (joinPath ((memoryDirectory) "workflow" "custom-skills")))
         (let $customrc (make-directory-path (pluginWorkflowCustomSkillsDir)) ())
         (if (not (exists-directory (pluginWorkflowCustomSkillsDir)))
           (log ERROR "workflow-plugin" (strings-concat ("Could not create custom skills directory: " (pluginWorkflowCustomSkillsDir)", only core skills are available")))
           ())
         (configure pluginWorkflowMemoryDir (joinPath ((memoryDirectory) "workflow" "space")))
         (log INFO "workflow-plugin" (strings-concat ("Creating working directory: " (pluginWorkflowMemoryDir))))
         (let $rc (make-directory-path (pluginWorkflowMemoryDir)) ())
         (if (exists-directory (pluginWorkflowMemoryDir))
           (progn
             (log INFO "workflow-plugin" "Adding plugin's skills")
             (add-skill workflow-load-skills "Load existing workflow skills into the active context" (workflow_name))
             (add-skill workflow-unload-skills "Unload active workflow from the active context" ())
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

(= (core-skills-dir) (get-existing-dir (pluginWorkflowCoreSkillsDir)))

;; custom skill overrides the core skill with the same name
(= (workflow-dir $name)
   (if (exists-file (joinPath ((pluginWorkflowCustomSkillsDir) $name "SKILL.md")))
     (pluginWorkflowCustomSkillsDir)
     (core-skills-dir)))

(= (workflow-load-skills $name)
   (let $active (get-state &workflow_active_name)
     (if (== $active "")
       (if (not (valid-file-or-folder-name  $name))
         (Error (quote (workflow-load-skills $name)) (strings-concat ("ERROR: invalid workflow name: " $name)))
         (let $path (joinPath ((workflow-dir $name) $name "SKILL.md"))
           (if (not (exists-file $path))
             (Error (quote (workflow-load-skills $name)) (strings-concat ("ERROR: skill file not found: " $path ". Try to call workflow-refresh-list")))
             (let $content (read-file $path)
               (progn
                 (log INFO "workflow-plugin" (strings-concat ("Loading workflow skills for: " $name)))
                 (add-prompt-extension workflow_active_skills (active-skills $content))
                 (add-workflow-skills $name)
                 (add-prompt-extension workflow_active_instructions (active-instructions $content))
                 (change-state! &workflow_active_name $name)
                 (send (strings-concat ("Loaded workflow: " $name
                                        ". Instructions active in context until completion.")))
                 )))))
       (Error (quote (workflow-load-skills $name)) (strings-concat ("ERROR: There is an active workflow: " $active ". Unload it before loading new one"))))))

(= (workflow-unload-skills)
   (let $name (get-state &workflow_active_name)
     (if (== $name "")
       (Error (quote (workflow-unload-skills)) "No active workflow is loaded")
       (progn
          (remove-prompt-extension workflow_active_skills)
          (unload-workflow-skills)
          (change-state! &workflow_active_name "")
          (send (strings-concat ("Unloaded workflow: " $name)))
          ))))

(= (active-skills $content)
   (strings-concat (" ACTIVE_WORKFLOW_SKILLS: " $content
            " FOLLOW THESE INSTRUCTIONS UNTIL THE WORKFLOW IS COMPLETE"
            " AND YOU CALL (workflow-unload-skills) OR THE WORKFLOW CALLS ITS COMPLETION FUNCTION."
            " EXECUTE ONLY COMMANDS YOU DEEM SAFE; OTHERWISE SKIP OR ASK THE USER.")))

; to load skills descriptions which are defined only for current workflow,
; skill.metta is optional so import it only when it exists
(= (add-workflow-skills $name)
   (let $path (joinPath ((workflow-dir $name) $name "skill"))
     (if (exists-file (joinPath ((workflow-dir $name) $name "skill.metta")))
            (progn
              (import! &workflow_skills $path)
              (collapse (match &workflow_skills (skill $func $desc $args) (add-skill $func $desc $args)))
              (strings-concat ("Workflow MeTTa-skills loaded: " $name))
              )
            (strings-concat ("Workflow has no MeTTa-skills: " $name)))))

; to load skills descriptions
(= (unload-workflow-skills)
   (progn
     (match &workflow_skills (skill $func $desc $args) (remove-skill $func))
     (remove-all-atoms &workflow_skills)))

(= (workflow-change-active-skills $content)
   (progn
     (remove-prompt-extension workflow_active_skills)
     (add-prompt-extension workflow_active_skills $content)))

;;========================== Functions to load workflow description =======================
;; returns workflow name and its description, custom skills override core skills with the same name
(= (workflow-list-available)
   (let*  ( ($base (core-skills-dir))
          ($builtin (collect-description (filter-shadowed (directory-dirs $base)) $base ()))
          ($custom (pluginWorkflowCustomSkillsDir)))
     (if (exists-directory $custom)
       (collect-description (directory-dirs $custom) $custom $builtin)
       $builtin)))

;; drops core skills overridden by custom skills with the same name
(= (filter-shadowed ()) ())
(= (filter-shadowed (cons $first $tail))
   (let $rest (filter-shadowed $tail)
     (if (exists-file (joinPath ((pluginWorkflowCustomSkillsDir) $first "SKILL.md")))
       $rest
       (cons-atom $first $rest))))

;; re-reads available workflows into the prompt
(= (workflow-refresh-list)
   (let $text (join (newline) (cons-atom "Available workflows: " (workflow-list-available)))
     (progn
       (remove-prompt-extension workflows-available)
       (add-prompt-extension workflows-available $text))))

;; collects workflow description from description.txt
(= (collect-description () $base $acc) $acc)
(= (collect-description (cons $first $tail) $base $acc)
   (let*  (($path  (joinPath ($base $first "description.txt")))
           ($rest (collect-description $tail $base $acc)))
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
