!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
!(import! &self ../src/logger.py)
!(import! &self ./src/log)
!(import! &self ./src/skills)
!(import! &self ./plugins/workflow/workflow)
!(import! &self ../plugins/workflow/skill_catalog.py)

(= (pluginWorkflowInstructionsDir) (joinPath ((projectRootDirectory) "plugins" "workflow" "instructions")))

(= (send $msg) ())

!(change-state! &workflow_active_name "")

(= (count-test-skill)
   (expression-count-item (getSkills) (test-skill "Test skill to demonstrate workflow by sending message to the user" (message))))

(= (count-research-skills)
   ((expression-count-item (getSkills) (research-start "Create research project folders" (research_name topic)))
    (expression-count-item (getSkills) (research-step "Mark research step done" (research_name step result next_action)))
    (expression-count-item (getSkills) (research-checkpoint "Pause for user approval" (researchname message)))
    (expression-count-item (getSkills) (research-complete "Finish research and unload workflow" (researchname)))
    (expression-count-item (getSkills) (load-research-dynamic-instructions " Load a generated file into active context" (researchname_in_quotes filename_in_quotes)))
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

;;========================== List of available workflows =======================
; tests/res/workflows holds one workflow per frontmatter case

(= (fixture-catalog) (workflow-catalog "./tests/res/workflows"))

(= (catalog-entry $name $description)
   (strings-concat ("<skill><name>" $name "</name><description>" $description "</description></skill>")))

(= (workflows-available-text)
   (match &self (= (prompt-extension workflows-available) $text) $text))

; valid frontmatter is listed with its description
!(test (contains-text (fixture-catalog) (catalog-entry "valid-single" "Single line description. Use when testing."))
       True)

; a folded description is joined by YAML into one line
!(test (contains-text (fixture-catalog) (catalog-entry "valid-folded" "Folded description over two lines."))
       True)

; an unquoted ": " inside a value is quoted and parsed again
!(test (contains-text (fixture-catalog) (catalog-entry "colon-description" "Use when: the user asks for it"))
       True)

; the description is escaped for the prompt markup
!(test (contains-text (fixture-catalog) (catalog-entry "escaped-description" "Compare a &lt; b &amp; c."))
       True)

; a name that differs from the directory is listed under the directory name
!(test (contains-text (fixture-catalog) (catalog-entry "name-mismatch" "Listed under its directory name."))
       True)

; workflows without frontmatter, with broken YAML or without a description are
; left out, and description.txt is not read
!(test (contains-text (fixture-catalog) "<name>no-frontmatter</name>") False)
!(test (contains-text (fixture-catalog) "<name>broken-yaml</name>") False)
!(test (contains-text (fixture-catalog) "<name>empty-description</name>") False)
!(test (contains-text (fixture-catalog) "<name>legacy-description</name>") False)
!(test (contains-text (fixture-catalog) "Old description that is no longer read") False)

; a directory without SKILL.md is not a workflow
!(test (contains-text (fixture-catalog) "<name>not-a-skill</name>") False)

; a block description keeps its lines, and an indented "---" inside it does
; not end the frontmatter
!(test (contains-text (fixture-catalog) "<skill><name>block-description</name><description>Write a report using this layout:") True)
!(test (contains-text (fixture-catalog) "---") True)
!(test (contains-text (fixture-catalog) "Details</description></skill>") True)

; a file that is not UTF-8 or a value YAML cannot build, such as the date
; 2026-02-30, leaves out only that workflow
!(test (contains-text (fixture-catalog) "<name>invalid-utf8</name>") False)
!(test (contains-text (fixture-catalog) "<name>invalid-date</name>") False)

; a description over 1024 characters or a SKILL.md over 500 lines is left out
!(test (contains-text (fixture-catalog) "<name>long-description</name>") False)
!(test (contains-text (fixture-catalog) "<name>long-file</name>") False)

; a workflow may be loaded exactly when it is listed
!(test (string_length (workflow-load-problem "./tests/res/workflows/valid-single")) 0)
!(test (contains-text (workflow-load-problem "./tests/res/workflows/long-file") "more than the limit of 500") True)
!(test (contains-text (workflow-load-problem "./tests/res/workflows/no-frontmatter") "does not start with YAML frontmatter") True)

; a SKILL.md saved with a byte-order mark is read like any other
!(test (contains-text (fixture-catalog) (catalog-entry "bom-skill" "Saved with a byte-order mark.")) True)

; the description.txt hint is given only when the description is missing
!(test (contains-text (workflow-load-problem "./tests/res/workflows/legacy-description") "description.txt is no longer read") True)
!(test (contains-text (workflow-load-problem "./tests/res/workflows/legacy-long-file") "description.txt") False)

; the list tells the agent how to load a workflow and which value to pass
!(test (contains-text (fixture-catalog) "call `workflow-load-instructions <workflow_name>`") True)
!(test (contains-text (fixture-catalog) "the value of that skill's `<name>` field") True)

; no workflows give no list at all
!(test (string_length (workflow-catalog "./tests/res/workflows-none")) 0)

; refresh puts the shipped workflows into the prompt with their frontmatter
; descriptions
!(test (progn
         (workflow-refresh-list)
         (let $text (workflows-available-text)
           (contains-text $text "<skill><name>research-workflow</name><description>End-to-end research workflow.")))
       True)

!(test (progn
         (workflow-refresh-list)
         (let $text (workflows-available-text)
           (contains-text $text "<skill><name>test-workflow</name><description>Demonstrates the workflow plugin")))
       True)

; repeated refreshes keep a single list in the prompt
!(test (progn
         (workflow-refresh-list)
         (workflow-refresh-list)
         (let $all (collapse (workflows-available-text))
           (and (!= $all ()) (== (cdr-atom $all) ()))))
       True)
