(= (maxNewInputLoops) (empty))
(= (maxWakeLoops) (empty))
(= (sleepInterval) (empty))
(= (provider) (empty))
(= (maxOutputToken) (empty))
(= (reasoningMode) (empty))
(= (wakeupInterval) (empty))
(= (episodicTraceSize) (empty))
(= (memoryDirectory) (empty))

(= (initLoop)
   (progn (configure maxNewInputLoops 50) ;20
          (configure maxWakeLoops 1)
          (configure sleepInterval 1) ;10
          (configure provider Anthropic)
          (configure maxOutputToken 6000)
          (configure reasoningMode medium)
          (configure wakeupInterval 600) ;600=10 minutes
          (configure episodicTraceSize 100)
          (configure memoryDirectory
               (joinPath ((py-call (helper.projectRootDirectory)) memory)))
          (change-state! &prevmsg "")
          (change-state! &loops (maxNewInputLoops))
          (change-state! &episodic (py-call (utils.listNew)))
          (change-state! &temporary_message "")
          ))

(= (initKnowledge)
   (progn (log INFO "loop" "Initializing knowledge base")
          (if (== (embeddingprovider) OpenAI)
               (log INFO "loop" (py-call (rag.init_knowledge "OpenAI")))
               (log INFO "loop" (py-call (rag.init_knowledge "Local"))))))

(= (getPrompt)
   (let $content (string-safe (py-str ("PROMPT: " (getPrompt (provider))
                                      (newline) (getPromptExtensions) (newline)
                                      " SAVE_PERMANENT_FILES_DIR: " (memoryDirectory))))
     (llmRequestMessage role "system" content $content)))

(= (addTelegramPromptExtension)
   (if (== (commchannel) telegram)
       (let $path (joinPath ((memoryDirectory) "tg_prompt.txt"))
            (if (exists-file $path)
                (add-prompt-extension tg-prompt (read-file $path))
                (progn (log WARN "loop" (TELEGRAM_PROMPT_NOT_FOUND: $path))
                       ())))
       ()))

(= (getPromptExtensions)
   (join (newline) (collapse (prompt-extension $_))))

; dynamic prompt extension placeholder to eliminate error when no extension is added
(= (prompt-extension placeholder) (empty))

(= (collectTools)
   (py-call (providers.getTools (getSkills))))

(= (episodicAppend $item)
   (let $episodic (get-state &episodic)
     (change-state! &episodic (py-call (utils.listAppend $episodic $item)))))

(= (episodicTail $size)
   (let $episodic (get-state &episodic)
     (change-state! &episodic (py-call (utils.listSlice $episodic (* -1 $size))))))

(= (episodicGet)
   (get-state &episodic))

; TODO: for each "role": "tool" item in the episodic memory cut the content 
; keeping only RETURN_VALUE_TO_PRESERVE chars and adding " ... omitted" postfix
(= (episodicCutToolResults) _)

(= (callTools ()) _)
(= (callTools (cons $head $tail))
   (progn
       (log INFO "loop" (TOOL-CALL: (py-str ($head))))
       (let $content
           (if (llmToolCallIsError $head)
               (llmToolCallGetError $head)
               (let* (($callstr (llmToolCallToSExpr $head))
                      ($_ (addToHistory $callstr))
                      ($_ (log INFO "loop" (TOOL-CALL-SEXPR: $callstr)))
                      ($call (sread $callstr))
                      ($result (catch (eval $call))))
                   (progn
                       (case $result (
                           ((Error $atom $msg) (let $errorstr (swrite $result)
                                                 (strings-concat ("Tool execution failed: " $errorstr))))
                           ($else (py-str ("SUCCESS, RETURN: " $result))) )))))
           _)
       (log INFO "loop" (TOOL-CALL-RESULT: (quote $content)))
       (episodicAppend (llmRequestMessage role "tool"
                                          callid (llmToolCallGetId $head)
                                          content (py-str ("Step " (get_time_as_string) ": " $content))))
       (callTools $tail)))

(= (omega)
  (progn (initConfig)
         (initLogger)
         (initLoop)
         (applySecurityPolicy)
         (initMemory)
         (initKnowledge)
         (initPlugins)
         (initChannels)
         (addTelegramPromptExtension)
         (commChannelSend (version))
         (llmProviderStart (provider))
         (omega 1)))

(= (omega $k)
   (progn 
          (change-state! &loops (- (get-state &loops) 1))
          (let $prompt (getPrompt)
               (progn (log INFO "loop" (---------iteration $k))
                      (heartbeat $k)
                      (let* (($msgrcv (string-safe (repr (receive))))
                             ($msgnew (prog1 (and (> (string_length $msgrcv) 0) (!= $msgrcv (get-state &prevmsg)))
                                             (if (> (string_length $msgrcv) 0) (change-state! &prevmsg $msgrcv) _)))
                             ($msg (get-state &prevmsg))
                             ($_ (if $msgnew
                                     (progn
                                       (change-state! &loops (maxNewInputLoops))
                                       (addToHistory (py-str ("HUMAN_MESSAGE: " $msg))))
                                      _)))
                            (if (> (get-state &loops) 0)
                                (let* (($lastmessage (if $msgnew $msg "[NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK. DO NOT REPEAT THE PREVIOUS RESPONSE. ONLY USE send FOR GENUINELY NEW INFORMATION OR WHEN USER INPUT IS NEEDED.]"))
                                       ($_ (log INFO "loop" (LAST-MESSAGE: $lastmessage)))
                                       ($usercontent (py-str ("Step " (get_time_as_string) ": " $lastmessage)))
                                       ($_ (episodicAppend (llmRequestMessage role "user" content $usercontent)))
                                       ($_ (change-state! &nextWakeAt (+ (get_time) (wakeupInterval))))
                                       ($recent_messages (episodicTail (episodicTraceSize)))
                                       ($request (llmRequest $prompt (episodicGet) (maxOutputToken) (reasoningMode) (collectTools)))
                                       ($_ (log INFO "loop" (REQUEST: (py-str ($request)))))
                                       ($response (llmProviderChat $request))
                                       ($_ (log INFO "loop" (RESPONSE: (py-str ($response))))))
                                       (if (llmResponseIsError $response)
                                           (change-state! &temporary_message (llmRequestMessage role "user" content (llmResponseGetError $response)))
                                           (if (llmResponseIsEmpty $response)
                                               ; TODO: add temp message to the request
                                               (change-state! &temporary_message (llmRequestMessage role "user" content "Your previous response was invalid. Do not answer in plain text. Call at least one tool now."))
                                               (progn
                                                   (change-state! &temporary_message "")
                                                   (episodicCutToolResults)
                                                   (episodicAppend (llmRequestMessage role "assistant"
                                                                                      calls (llmResponseCalls $response)
                                                                                      content (py-str ("Step " (get_time_as_string) ": [TOOL CALL]" ))))
                                                   (callTools (llmResponseCalls $response))
                                               ))))
                                (if (> (get_time) (get-state &nextWakeAt))
                                    (change-state! &loops (+ 1 (maxWakeLoops))) _)))
                      (sleep (sleepInterval))
                      (cut)
                      (gc)
                      (omega (+ 1 $k))))))
