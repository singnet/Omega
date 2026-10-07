(= (getSkills)
     (collapse (match &self (dynamic-skill $name $info) $info)))

; Add skill to the list of skills available to the agent.
; $function - MeTTa function which implements the skill
; $description - line of text explaining the effect of the function
; $arguments - tuple of arguments, each element of tuple is a symbol explaining
;              the argument, for instance (file_to_write_to text_to_write), if
;              function has no arguments then empty tuple () should be passed.
(: add-skill (-> Atom String Expression Bool))
(= (add-skill $function $description $arguments)
   (let $text (strings-concat ($description ": " $function " " (join " " $arguments)))
     (progn
       (py-call (helper.add_llm_command $function))
       (log INFO "skills" (strings-concat ("Add skill: " $text)))
       (add-atom &self (dynamic-skill $function ($function $description $arguments))) )))

; Remove skill from the list of skills available to the agent.
; $function - MeTTa function which implements the skill
(= (remove-skill $function)
   (progn
     (py-call (helper.remove_llm_command $function))
     (log INFO "skills" (strings-concat ("Remove skill: " $function)))
     (collapse (match &self (dynamic-skill $function $info) (remove-atom &self (dynamic-skill $function $info))))
     True))

; Add new section to the LLM's prompt. The extension is inserted into the
; prompt after SKILL section and before OUTPUT_FORMAT section.
; $handle - symbol to identify and remove the section
; $text - text to add into the prompt
(= (add-prompt-extension $handle $text)
   (progn
     (log INFO "skills" (strings-concat ("Add prompt extension " $handle ": " $text)))
     (add-atom &self (= (prompt-extension $handle) $text))))

; Remove section from the LLM's prompt.
; $handle - symbol to identify the section
(= (remove-prompt-extension $handle)
   (progn
     (log INFO "skills" (strings-concat ("Remove prompt extension: " $handle)))
     (collapse (match &self (= (prompt-extension $handle) $text) (remove-atom &self (= (prompt-extension $handle) $text))))
     True))
; Heartbeat function is called at the start of each iteration of the agentic
; loop. Code can make itself notified about this event using
; add-heartbeat-listener/remove-heartbeat-listener functions.
(= (heartbeat $iteration)
   (let $_ (collapse (heartbeat-listener $_ $iteration)) ()))

; placeholder to eliminate error when no heartbeat listener is added
(= (heartbeat-listener placeholder $_) (empty))

; Subscribe on heartbeat event notifications
; $handle - symbol to identify the subscription
; $callback - lambda to evaluate on event
(= (add-heartbeat-listener $handle $callback)
   (progn
     (log INFO "skills" (strings-concat ("Add heartbeat listener " $handle)))
     (add-atom &self (= (heartbeat-listener $handle $iter) ($callback $iter)))))

; Unsubscribe from heartbeat event notifications
; $handle - symbol to identify the subscription
(= (remove-heartbeat-listener $handle)
   (progn
     (log INFO "skills" (strings-concat ("Remove heartbeat listener: " $handle)))
     (collapse (match &self (= (heartbeat-listener $handle $arg) $body) (remove-atom &self (= (heartbeat-listener $handle $arg) $body))))
     True))

(= (read-file $file)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (read_file_to_string $file $content ()))
          $content))

(= (write-file $file $str)
   (py-call (fileio.write_file $file $str)))

(= (write-file-b64 $file $b64)
   (py-call (fileio.write_file_b64 $file $b64)))

(= (append-file $file $str)
   (py-call (fileio.append_file $file $str)))

(= (delete-file $path)
   (py-call (fileio.delete_file $path)))

; Prolog-backed append used by the harness itself (memory.metta appendToHistory):
; it receives a (library ...) file-spec term that only the Prolog open/4 path
; resolves. Body is the previous append-file minus its exists_file guard:
; open/4 in append mode creates a missing file, so the history file
; self-heals instead of the append failing silently.
(= (append-file-raw $file $str)
   (progn (translatePredicate (open $file append $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (nl $Out)),
          (translatePredicate (close $Out))
          APPEND-FILE-SUCCESS))

(= (websearch $msg)
   (py-call (websearch.search $msg)))

(= (get-io-policy)
   (py-call (policy.get_allowed_policy_paths (securityPolicyPath))))

!(import_prolog_functions_from_file (library Omega ./src/skills.pl) (shell first_char gc read_file_tail))

(= (metta $str)
   (let $code (sread $str)
        (repr (swrite (eval $code)))))

(= (pin $x)
   PIN-SUCCESS)

(= (version)
   (py-call (helper.omega_version)))

(= (nop)
   (log INFO "skills" "NOP"))

; Embedded skills

!(add-skill remember "Remember a particular string such as a skill or memory." (content))
!(add-skill query "Query long-term embedding memory using a short phrase." (content))
!(add-skill episodes  "Search history for episodes around a timestamp in %Y-%m-%d %H:%M:%S format." (timestamp))
!(add-skill pin "Pin a string as a short-term working-memory item to keep track of task state and relevant query results as query returns are only available once and gone next cycle." (message))
!(add-skill shell "Execute a shell command." (cmd))
!(add-skill read-file "Read a file." (filename))
!(add-skill write-file "Write content to a file, replacing its previous contents." (filename content))
!(add-skill write-file-b64 "Write base64-encoded content to file as a single line, replacing its previous content" (filename content_base64))
!(add-skill append-file "Append content to a file." (filename content))
!(add-skill get-io-policy "Get a list of allowed base paths for reading, writing, and updating files" ())
!(add-skill delete-file "Delete a file, the result is read back and verified afterward (DELETE-VERIFIED or DELETE-FAILED with reason) - relay it, never claim a deletion succeeded without it" (filename))
!(add-skill send "To send a message to the user but keep yourself very brief." (content))
!(add-skill websearch "Search the internet for content." (content))
!(add-skill version "To get the Omega version number" ())
!(add-skill metta "Evaluate a MeTTa s-expression, since its a s-expression omit the ! in the beginning. Use (add-atom &persistent X) to add X to space, same for remove-atom." (sexpression))
!(add-skill nop "Perform no action if task is complete, do not re-send!" ())
; TODO add load-plugin/unload-plugin skills
