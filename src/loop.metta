(= (maxNewInputLoops) (empty))
(= (maxWakeLoops) (empty))
(= (sleepInterval) (empty))
(= (provider) (empty))
(= (maxOutputToken) (empty))
(= (reasoningMode) (empty))
(= (wakeupInterval) (empty))
(= (memoryDirectory) (empty))
(= (showStartupVersion) (empty))

(= (initLoop)
   (progn (configure maxNewInputLoops 50) ;20
          (configure maxWakeLoops 1)
          (configure sleepInterval 1) ;10
          (configure provider Anthropic)
          (configure maxOutputToken 6000)
          (configure reasoningMode medium)
          (configure wakeupInterval 600) ;600=10 minutes
          (configure showStartupVersion True)
          (configure memoryDirectory
               (joinPath ((py-call (helper.projectRootDirectory)) memory)))
          (change-state! &prevmsg "")
          (change-state! &lastresults "")
          (change-state! &loops (maxNewInputLoops))
          (initContext)
          (messagesClear)
          ))

(= (initKnowledge)
   (progn (log INFO "loop" "Initializing knowledge base")
          (log INFO "loop" (py-call (rag.init_knowledge (embeddingprovider))))
          ()))

(= (getContext)
   (string-safe (py-str ("PROMPT: " (getPrompt (provider)) (newline)
                         (context-event Prompt) (newline)
                         "SKILLS: " (getSkillRules) (newline)
                         (getPromptExtensions) (newline)
                         "SAVE_PERMANENT_FILES_DIR: " (memoryDirectory) (newline)
                         "LAST_SKILL_USE_RESULTS: "
                            (last_chars (get-state &lastresults) (maxFeedback)) (newline)
                         "TIME: " (get_time_as_string)))))

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

(= (HandleError $result $error)
   (case $result (
      ((Error $cmd $msg) (let $new (append (get-state &error) (($msg $cmd)))
                           (let $errorstr (swrite $result)
                             (progn
                               (change-state! &error $new)
                               (let $error (strings-concat ("ALERT_FAILED" $errorstr))
                                 True)))))
      ($else False))))

(= (collectTools)
   (py-call (providers.getTools (getSkills))))

(= (messagesGet)
   (get-state &messages_all))

(= (messagesClear)
   (change-state! &messages_all (py-call (utils.listNew))))

(= (messagesAppend $item)
   (let $episodic (get-state &messages_all)
     (change-state! &messages_all (py-call (utils.listAppend $episodic $item)))))

(= (omega)
   (omega 1))
(= (omega $k)
   (progn (if (== $k 1) (progn (initConfig)
                               (initLoop)
                               (initLogger)
                               (applySecurityPolicy)
                               (initMemory)
                               (initKnowledge)
                               (initPlugins)
                               (initChannels)
                               (addTelegramPromptExtension)
                               (if (showStartupVersion)
                                   (commChannelSend (version))
                                   ())
                               (llmProviderStart (provider)))
          (change-state! &loops (- (get-state &loops) 1)))

      (log INFO "loop" (---------iteration $k))

      (heartbeat $k)
      (let* (($msgrcv (string-safe (repr (receive))))
             ($msgnew (prog1 (and (> (string_length $msgrcv) 0) (!= $msgrcv (get-state &prevmsg)))
                             (if (> (string_length $msgrcv) 0) (change-state! &prevmsg $msgrcv) _)))
             ($msg (get-state &prevmsg))
             ($loopSignal (context-event (Input $msg $msgnew)))
             ($_ (if (and (> $k 1) $msgnew) (change-state! &loops (maxNewInputLoops)) _))
             ($prompt (getContext)))

         (if (> (get-state &loops) 0)
             (let* (($_ (change-state! &nextWakeAt (+ (get_time) (wakeupInterval))))
                    ($_ (log INFO "loop" $loopSignal))
                    ($system (llmRequestMessage role "system" content $prompt))
                    ($_ (messagesAppend (llmRequestMessage role "user" content $loopSignal)))
                    ($request (llmRequest $system (messagesGet) (maxOutputToken) (reasoningMode) (collectTools)))
                    ($_ (log INFO "loop" (REQUEST: (py-str ($request)))))
                    ($requestContext (context-event BeforeRequest))
                    ($response (llmProviderChat $request))
                    ($_ (log INFO "loop" (RESPONSE: (py-str ($response)))))
                    ($respstr (py-call (providers.llmResponseToSExpr $response)))
                    ($resp (catch (sread $respstr)))
                    ($_ (log INFO "loop" (RESPONSE: $resp)))
                    ($_ (change-state! &error ()))
                    ($_ (messagesClear))
                    ($_ (change-state! &command-batch-results ()))
                    ($sexpr (if (HandleError (quote $resp) $error)
                              $error
                              (progn (messagesAppend (llmToolCallMessage role "assistant"
                                                                        calls (llmResponseCalls $response)
                                                                        content "[TOOL CALL]"))
                                (collapse
                                      (let ($callid $s) (superpose $resp)
                                        (let $result
                                          (if (HandleError (quote $s) $error) $error
                                            (let $rc (catch (let $R (collapse (eval $s)) (py-call (helper.normalize_string $R))))
                                              (if (HandleError $rc $error) $error (strings-concat ("SUCCESS, RETURN: " $rc)))))
                                          (progn
                                            ($_ (log INFO "loop" (COMMAND_RETURN: ((quote $s) $result))))
                                            (messagesAppend (llmToolCallResponseMessage role "tool" callid $callid content (last_chars $result (maxFeedback))))
                                            (change-state! &command-batch-results
                                              (append (get-state &command-batch-results) ((COMMAND_RETURN (quote $s) $result))))
                                            (quote $s)))))))))
                        (progn
                          (if (or $msgnew (not (== $sexpr ()))) (addToHistory $msg $sexpr $msgnew) _)
                          (context-event (AfterTools $requestContext $sexpr (get-state &command-batch-results)))
                          (change-state! &lastresults (string-safe (repr (get-state &command-batch-results))))))
             (if (> (get_time) (get-state &nextWakeAt))
                 (change-state! &loops (+ 1 (maxWakeLoops)))
                 (context-event Idle))))

      (sleep (sleepInterval))
                      (cut)
                      (gc)
                      (omega (+ 1 $k))))

; Legacy entry points.
(= (omegaclaw) (omega))
(= (omegaclaw $k) (omega $k))
