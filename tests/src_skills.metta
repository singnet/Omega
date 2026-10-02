!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
!(import! &self ./src/skills)

; Define the selected channel and memory path used by the Telegram prompt
; registration test.
(= (commchannel) telegram)
(= (memoryDirectory) (joinPath ((projectRootDirectory) "memory")))

!(import! &self ./src/loop)

!(test (progn
         (add-skill test-skill "This is a test skill" (test_arg))
         (expression-count-item (getSkills) (test-skill "This is a test skill" (test_arg))))
       1)

!(test (progn
         (remove-skill test-skill)
         (expression-count-item (getSkills) (test-skill "This is a test skill" (test_arg))))
       0)

!(test (progn
         (add-prompt-extension test-prompt "TEST PROMPT EXTENSION")
         (contains-text (getPromptExtensions) "TEST PROMPT EXTENSION"))
       True)

!(test (progn
         (remove-prompt-extension test-prompt)
         (contains-text (getPromptExtensions) "TEST PROMPT EXTENSION"))
       False)

!(test (progn
         (addTelegramPromptExtension)
         (contains-text (getPromptExtensions) "TELEGRAM ROUTING:"))
       True)

!(test (progn
         (remove-prompt-extension tg-prompt)
         (contains-text (getPromptExtensions) "TELEGRAM ROUTING:"))
       False)

(= (on-heartbeat $iter)
   (let $count (get-state &test_heartbeat_counter)
     (change-state! &test_heartbeat_counter (+ $count $iter))))

!(test (progn
         (change-state! &test_heartbeat_counter 0)
         (add-heartbeat-listener test-heartbeat (|-> ($iter) (on-heartbeat $iter)))
         (heartbeat 1)
         (heartbeat 2)
         (remove-heartbeat-listener test-heartbeat)
         (get-state &test_heartbeat_counter))
       3)

!(test (progn
         (change-state! &test_heartbeat_counter 0)
         (add-heartbeat-listener test-heartbeat (|-> ($iter) (on-heartbeat $iter)))
         (remove-heartbeat-listener test-heartbeat)
         (heartbeat 1)
         (get-state &test_heartbeat_counter))
       0)
