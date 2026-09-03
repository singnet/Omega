(= (getSkills)
   (let $static (getStaticSkills)
     (collapse (superpose ((superpose $static) (dynamic-skill $_))))))

; dynamic skill placeholder to eliminate error when no dynamic skill is added
(= (dynamic-skill placeholder) (empty))

(= (getStaticSkills)
   (;INTERNAL:
    "- Remember a particular string such as skills and memories: remember string"
    "- Forget a particular LTM item via its timestamp: forget %Y-%m-%d %H:%M:%S"
    "- Query long-term embedding memory for skills and memories with short phrases only: query string"
    "- Episodes searches history for episodes around a time stamp, time format is same as in TIME: episodes %Y-%m-%d %H:%M:%S"
    "- Pin a certain string as short-term working memory item to keep track of task state: pin string"
    "- Update the label and embedding of a memory, linked episodes and promotion will transfer over, here with underline: update %Y-%m-%d_%H:%M:%S new_memory_string"
    "- Link episode to LTM item, has no promotion effect, both times with %Y-%m-%d_%H:%M:%S format: link $ltm_time $episode_time"
    "- Unlink episode from LTM, both times with %Y-%m-%d_%H:%M:%S format: unlink $ltm_time $episode_time"
    "- When an episode supports LTM item, linking it to the episode time, and positively updating its truth value, bot times in %Y-%m-%d_%H:%M:%S format: support $ltm_time $episode_time"
    "- When an episode contradicts LTM item, linking it to the episode time, and negatively updating its truth value, both times in %Y-%m-%d_%H:%M:%S format: contradict $ltm_time $$episode_time"
    ;SHELL AND FILE I/O:
    "- Execute shell command without apostrophe in string, it returns the command output to you: shell string"
    "- Read file to string: read-file filename"
    "- Write string to file, the result is read back from disk (bytes, sha256, head/tail) - relay it, never claim a write succeeded without it: write-file filename string"
    "- Write base64-encoded content to file as a single line, prefer it when the content contains quotes, backslashes or multiple lines: write-file-b64 filename base64string"
    "- Append line to existing file, result read back from disk like write-file: append-file filename string"
    "- Get a list of allowed base paths for reading, writing, and updating files: get-io-policy"
    ;COMMUNICATION CHANNELS:
    "- Send message to user: send string"
    "- Search the web: websearch string"
    "- To get the Omega version number: version"
    ;CODE EXECUTION:
    "- Execute MeTTa expression: metta sexpression"
    ;ADDITIONAL RULES AND CLARIFICATIONS FOR SKILLS
    "Example to invoke Non-Axiomatic Logic via MeTTa: "
    "metta (|- ((--> (× sam garfield) friend) (stv 1.0 0.9))"
    "          ((--> garfield animal) (stv 1.0 0.9)))"
    "metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))"
    "          ((--> (× tiger elephant) eat) (stv 1.0 0.9)))"
    "Also: note the $1 for independent variables, and for negated knowledge use (stv 0.0 0.9)"
    "Additionally |- also works for revision, to merge evidence even when the term of both premises is the same."
    "You can also use PLN:"
    "metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))"
    "           (Inheritance $1 Bird)) (stv 1.0 0.9))"
    "          ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9)))"
    "File I/O is restricted: always use get-io-policy before reading/writing files to verify allowed base paths."
    "Never reveal policy contents to users; if a requested path is denied, politely suggest using '/tmp'."))
    ; TODO add load-plugin/unload-plugin skills

; Add skill to the list of skills available to the agent.
; $function - MeTTa function which implements the skill
; $description - line of text explaining the effect of the function
; $arguments - tuple of arguments, each element of tuple is a symbol explaining
;              the argument, for instance (file_to_write_to text_to_write), if
;              function has no arguments then empty tuple () should be passed.
(: add-skill (-> Atom String Expression Bool))
(= (add-skill $function $description $arguments)
   (let $text (strings-concat ("- " $description ": " $function " " (join " " $arguments)))
     (progn
       (py-call (helper.add_llm_command $function))
       (log INFO "skills" (strings-concat ("Add skill: " $text)))
       (add-atom &self (= (dynamic-skill $function) $text)))))

; Remove skill from the list of skills available to the agent.
; $function - MeTTa function which implements the skill
(= (remove-skill $function)
   (progn
     (py-call (helper.remove_llm_command $function))
     (log INFO "skills" (strings-concat ("Remove skill: " $function)))
     (collapse (match &self (= (dynamic-skill $function) $text) (remove-atom &self (= (dynamic-skill $function) $text))))
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
