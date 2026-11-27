(= (llmProviderStart $provider)
   (py-call (providers.llmProviderStart $provider)))

(= (llmProviderChat $request)
     (py-call (providers.llmProviderChat $request)))

;Notice text for the user if the provider reply is the output limit marker, otherwise ""
(= (llmLimitNotice $response)
   (py-call (lib_llm_ext.llmLimitNotice $response)))
(= (llmRequestMessage role $role content $content)
   (py-call (providers.llmRequestMessage $role $content)))

(= (llmToolCallResponseMessage role $role callid $callid content $content)
   (py-call (providers.llmToolCallResponseMessage $role $callid $content)))

(= (llmToolCallMessage role $role calls $calls content $content)
   (py-call (providers.llmToolCallMessage $role $calls $content)))

(= (llmResponseMessage $response)
   (py-call (providers.llmResponseMessage $response)))

(= (llmRequest $prompt $episodes $max_tokens $reasoning_mode $tools)
   (py-call (providers.llmRequest $prompt $episodes $max_tokens $reasoning_mode $tools)))

(= (llmResponseIsEmpty $response)
   (py-call (providers.llmResponseIsEmpty $response)))

(= (llmResponseCalls $response)
   (py-call (providers.llmResponseCalls $response)))

(= (llmToolCallGetName $call)
   (py-call (providers.llmToolCallGetName $call)))

(= (llmToolCallGetId $call)
   (py-call (providers.llmToolCallGetId $call)))

(= (llmToolCallGetArguments $call)
   (py-str ((py-call (providers.llmToolCallGetArguments $call)))))

(= (llmToolCallIsError $call)
   (py-call (providers.llmToolCallIsError $call)))

(= (llmToolCallGetError $call)
   (py-call (providers.llmToolCallGetError $call)))

(= (llmResponseToSExpr $call)
   (py-call (providers.llmResponseToSExpr $call)))

; sread returns the validated tool name as a string. Convert it to a single
; dispatch symbol without parsing it again. Failed calls stay data.
(= (toolCallCommand $call)
   (if (== (car-atom $call) Error)
       $call
       (let $name (car-atom $call)
         (progn (translatePredicate (atom_string $symbol $name))
                (cons-atom $symbol (cdr-atom $call))))))
