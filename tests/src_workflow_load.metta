!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
!(import! &self ../src/logger.py)
!(import! &self ./src/log)
!(import! &self ./src/skills)
!(import! &self ./plugins/workflow/workflow)
!(import! &self ../plugins/workflow/skill_catalog.py)

; The workflows in tests/res/workflows stand in for the instructions directory,
; so workflow-load-instructions sees the broken and oversized fixtures.
(= (pluginWorkflowInstructionsDir) (joinPath ((projectRootDirectory) "tests" "res" "workflows")))

(= (send $msg) ())

!(change-state! &workflow_active_name "")

(= (load-error $name)
   (let $res (collapse (workflow-load-instructions $name))
     (if (= (cons (cons Error (cons $_ ($message))) ()) $res) $message "")))

(= (active-instructions-count)
   (let $all (collapse (match &self (= (prompt-extension workflow_active_instructions) $text) $text))
     (if (== $all ()) 0 1)))

; a workflow that is not listed is refused with the reason, and nothing is loaded
!(test (contains-text (load-error long-file) "ERROR: cannot load workflow long-file") True)
!(test (contains-text (load-error long-file) "more than the limit of 500") True)
!(test (contains-text (load-error no-frontmatter) "does not start with YAML frontmatter") True)
!(test (contains-text (load-error legacy-description) "description.txt is no longer read") True)
!(test (get-state &workflow_active_name) "")
!(test (active-instructions-count) 0)
