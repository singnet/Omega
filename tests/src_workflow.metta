!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ../src/fileio.py)
!(import! &self ./src/utils)
!(import! &self ../src/logger.py)
!(import! &self ./src/log)
!(import! &self ./src/skills)
!(import! &self ./plugins/workflow/workflow)

(= (pluginWorkflowInstructionsDir) (joinPath ((projectRootDirectory) "plugins" "workflow" "instructions")))

(= (send $msg)
   (progn (change-state! &test-workflow-message $msg) ()))

!(change-state! &workflow_active_name "")

(= (count-test-skill)
   (expression-count-item (getSkills) (test-skill "Test skill to demonstrate workflow by sending message to the user" (message))))

(= (count-research-skills)
   ((expression-count-item (getSkills) (research-start "Create research project folders" (research_name topic)))
    (expression-count-item (getSkills) (research-step "Mark research step done" (research_name step result next_action)))
    (expression-count-item (getSkills) (research-checkpoint "Pause for user approval" (researchname message)))
    (expression-count-item (getSkills) (research-complete "Finish research and unload workflow" (researchname)))
    (expression-count-item (getSkills) (load-research-dynamic-instructions " Load a generated file into active context" (researchname_in_quotes filename_in_quotes)))
    (expression-count-item (getSkills) (research-write-file "Write a UTF-8 file inside an existing research project" (research_name relative_path content)))
    (expression-count-item (getSkills) (researchDir "Get research directory" ()))))

!(test (progn
         (collapse (workflow-load-instructions test-workflow))
         (count-test-skill))
       1)

!(test (let $res (collapse (workflow-load-instructions test-workflow))
         (= (cons (cons Error (cons $_ $error)) ()) $res))
       True)

!(test (progn
         (collapse (workflow-load-instructions test-workflow))
         (count-test-skill))
       1)

!(test (progn
         (add-skill test-skill "Test skill to demonstrate workflow by sending message to the user" (message))
         (count-test-skill))
       1)

!(test (progn
         (collapse (workflow-unload-instructions))
         (count-test-skill))
       0)

!(test (progn
         (collapse (workflow-load-instructions test-workflow))
         (count-test-skill))
       1)

!(test (progn
         (collapse (workflow-unload-instructions))
         (count-test-skill))
       0)

!(test (progn
         (collapse (workflow-load-instructions research-workflow))
         (count-research-skills))
       (1 1 1 1 1 1 1))

!(test (progn
         (collapse (workflow-unload-instructions))
         (count-research-skills))
       (0 0 0 0 0 0 0))

!(test (progn
         (collapse (workflow-load-instructions research-workflow))
         (count-research-skills))
       (1 1 1 1 1 1 1))

!(test (progn
         (collapse (workflow-unload-instructions))
         (count-research-skills))
       (0 0 0 0 0 0 0))

!(test (collapse (match &self (dynamic-skill nop (nop $description $args)) ($description $args)))
       (("Perform no action." ())))

!(test (let $res (nop)
         (= (cons Error (cons $_ $error)) $res))
       False)

(= (invalid-workflow-rejected $name)
   (let $results (collapse (workflow-load-instructions $name))
     (let ((Error $_ $message)) $results
       (contains-text $message "ERROR: invalid workflow name"))))

!(test (invalid-workflow-rejected "./test-workflow") True)
!(test (invalid-workflow-rejected "test-workflow;") True)
!(test (get-state &workflow_active_name) "")

!(change-state! &test-workspace (py-call (tempfile.TemporaryDirectory)))
(= (pluginWorkflowMemoryDir) (py-call (.__enter__ (get-state &test-workspace))))

;; Discovery also excludes invalid names when those directories exist.
!(make-dirs (joinPath ((pluginWorkflowMemoryDir) "test-workflow;")))
!(make-dirs (joinPath ((pluginWorkflowMemoryDir) "listed-workflow")))
!(test (directory-dirs (pluginWorkflowMemoryDir)) ("listed-workflow"))

;; Fail any attempt to invoke the shell in this test process, even after
;; removing the agent-facing skill from the registry.
!(remove-skill shell)
!(test (collapse (match &self (dynamic-skill shell $_) shell)) ())
!(translatePredicate (abolish (Predicate (quote (/ shell 2)))))
!(change-state! &test-shell-called False)
(= (shell $command)
   (progn (change-state! &test-shell-called True) "Unexpected shell call"))

!(collapse (workflow-load-instructions research-workflow))
(= (test-research-path $folder $file) (joinPath ((researchDir) $folder $file)))

!(research-start "study.v0.2" "Research topic")
!(test (contains-text (get-state &test-workflow-message) "Created project: ") True)
!(test (exists-directory (test-research-path "study.v0.2" "src")) True)
!(test (exists-directory (test-research-path "study.v0.2" "data")) True)
!(test (exists-directory (test-research-path "study.v0.2" "runs")) True)
!(test (exists-directory (test-research-path "study.v0.2" "figures")) True)
!(test (read-file (test-research-path "study.v0.2" "topic.txt")) "Research topic")

!(research-start "study;" "Rejected topic")
!(test (contains-text (get-state &test-workflow-message) "ERROR: invalid research name") True)
!(research-start "../outside" "Rejected topic")
!(test (contains-text (get-state &test-workflow-message) "ERROR: invalid research name") True)
!(test (exists-directory (joinPath ((pluginWorkflowMemoryDir) "outside"))) False)
!(test (get-state &test-shell-called) False)

!(research-step "-study" "step" "result" "next")
!(test (contains-text (get-state &test-workflow-message) "ERROR: invalid research name") True)
!(research-checkpoint ".study" "Plan ready")
!(test (contains-text (get-state &test-workflow-message) "ERROR: invalid research name") True)
!(research-complete "study..old")
!(test (contains-text (get-state &test-workflow-message) "ERROR: invalid research name") True)
!(test (get-state &workflow_active_name) research-workflow)

!(research-write-file "study.v0.2" "02_plan.md" "Approved plan")
!(research-write-file "study.v0.2" "runs/result.txt" "Saved result")
!(test (read-file (test-research-path "study.v0.2" "runs/result.txt")) "Saved result")
!(load-research-dynamic-instructions "study.v0.2" "02_plan.md")
!(test (prompt-extension workflow_active_instructions) "Approved plan")

!(load-research-dynamic-instructions "../outside" "plan.md")
!(test (contains-text (get-state &test-workflow-message) "ERROR: invalid research name") True)
!(load-research-dynamic-instructions "study.v0.2" "../fixture.md")
!(test (contains-text (get-state &test-workflow-message) "ERROR: invalid filename") True)

(= (test-external-file) (joinPath ((pluginWorkflowMemoryDir) "fixture.md")))
!(write-file (test-external-file) "External fixture")
!(py-call (os.symlink (test-external-file) (test-research-path "study.v0.2" "external.md")))
!(test (exists-file (test-research-path "study.v0.2" "external.md")) True)
!(load-research-dynamic-instructions "study.v0.2" "external.md")
!(test (contains-text (get-state &test-workflow-message) "ERROR: path traversal rejected") True)
!(test (prompt-extension workflow_active_instructions) "Approved plan")

;; An existing file in place of a required directory must prevent topic writes.
!(make-dirs (joinPath ((researchDir) "blocked")))
!(write-file (test-research-path "blocked" "data") "Directory blocker")
!(research-start "blocked" "Rejected topic")
!(test (contains-text (get-state &test-workflow-message) "ERROR: could not create research project directories") True)
!(test (exists-file (test-research-path "blocked" "topic.txt")) False)

!(make-dirs (joinPath ((researchDir) "linked-topic")))
!(py-call (os.symlink (test-external-file) (test-research-path "linked-topic" "topic.txt")))
!(research-start "linked-topic" "Rejected topic")
!(test (get-state &test-workflow-message) "ERROR: unsafe research topic path")
!(test (read-file (test-external-file)) "External fixture")

;; An escaping link in the directory layout must prevent any topic write.
!(make-dirs (joinPath ((researchDir) "linked-src")))
!(py-call (os.symlink (pluginWorkflowMemoryDir) (test-research-path "linked-src" "src")))
!(research-start "linked-src" "Rejected topic")
!(test (contains-text (get-state &test-workflow-message) "ERROR: could not create research project directories") True)
!(test (exists-file (test-research-path "linked-src" "topic.txt")) False)

!(py-call (os.rename (researchDir) (joinPath ((pluginWorkflowMemoryDir) "saved-research"))))
!(test (collapse (let $d (researchDir) (strings-concat ($d "/study/00_problem.md")))) ())
!(py-call (os.symlink (pluginWorkflowMemoryDir) (joinPath ((pluginWorkflowMemoryDir) "research"))))
!(test (collapse (researchDir)) ())

!(py-call (.cleanup (get-state &test-workspace)))
!(test (collapse (let $d (researchDir) (strings-concat ($d "/study/00_problem.md")))) ())
!(collapse (research-complete "study.v0.2"))
!(test (contains-text (get-state &test-workflow-message) "Research directory is unavailable.") True)
!(test (get-state &workflow_active_name) "")
