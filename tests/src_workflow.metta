!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
!(import! &self ../src/logger.py)
!(import! &self ./src/log)
!(import! &self ./src/skills)
!(import! &self ./plugins/workflow/workflow)

(= (pluginWorkflowInstructionsDir) (get-state &test-instructions-dir))

(= (send $msg) ())

!(change-state! &workflow_active_name "")

(= (count-test-skill)
   (expression-count-item (getSkills) (test-skill "Test skill to demonstrate workflow by sending message to the user" (message))))

(= (rejected-workflow $name)
   (let $results (collapse (workflow-load-instructions $name))
     (= ((Error $_ "ERROR: invalid workflow name")) $results)))

;; Verify each fixture is a real link to an existing target before exercising
;; discovery and loading through the same entry points used by the agent.
!(change-state! &test-instructions-dir (joinPath ((projectRootDirectory) "tests" "res" "workflow-links")))
(= (fixture-link-exists $relative)
   (let $path (joinPath ((instructionsDir) $relative))
     (and (workflow-symlink $path) (or (exists-file $path) (exists-directory $path)))))
!(test (fixture-link-exists "linked-directory") True)
!(test (fixture-link-exists "linked-instructions/SKILL.md") True)
!(test (fixture-link-exists "linked-skills/skill.metta") True)
!(test (fixture-link-exists "linked-description/description.txt") True)
!(test (workflow-list-available) ())
!(test (rejected-workflow "linked-directory") True)
!(test (rejected-workflow "linked-instructions") True)
!(test (rejected-workflow "linked-skills") True)

;; No shell or metta skills are registered in this fixture.
!(change-state! &test-instructions-dir (joinPath ((projectRootDirectory) "plugins" "workflow" "instructions")))
!(test (rejected-workflow "../../../memory/workflow_space") True)
!(test (rejected-workflow "./test-workflow") True)
!(test (rejected-workflow "missing-workflow") True)
!(test (get-state &workflow_active_name) "")
!(test (count-test-skill) 0)

(= (count-research-skills)
   ((expression-count-item (getSkills) (research-start "Create research project folders" (research_name topic)))
    (expression-count-item (getSkills) (research-step "Mark research step done" (research_name step result next_action)))
    (expression-count-item (getSkills) (research-checkpoint "Pause for user approval" (researchname message)))
    (expression-count-item (getSkills) (research-complete "Finish research and unload workflow" (researchname)))
    (expression-count-item (getSkills) (load-research-dynamic-instructions " Load a generated file into active context" (researchname_in_quotes filename_in_quotes)))
    (expression-count-item (getSkills) (researchDir "Get research directory" ()))))

!(test (progn
         (collapse (workflow-load-instructions "test-workflow"))
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
       (1 1 1 1 1 1))

!(test (progn
         (collapse (workflow-unload-instructions))
         (count-research-skills))
       (0 0 0 0 0 0))

!(test (progn
         (collapse (workflow-load-instructions research-workflow))
         (count-research-skills))
       (1 1 1 1 1 1))

!(test (progn
         (collapse (workflow-unload-instructions))
         (count-research-skills))
       (0 0 0 0 0 0))

!(test (collapse (match &self (dynamic-skill nop (nop $description $args)) ($description $args)))
       (("Perform no action." ())))

!(test (let $res (nop)
         (= (cons Error (cons $_ $error)) $res))
       False)
