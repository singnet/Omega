!(import! &self (library Omega ./routers/default))

(= (llmProviderStart $provider)
   (py-call (providers.llmProviderStart $provider)))

(= (llmProviderChat $request)
     (py-call (providers.llmProviderChat $request "none")))

(= (llmProviderChat $request $router)
   (case $router (
    (default 
      (let* 
        (
         ($prompt_contents_normalized (py-call (providers.llmRequestContentsNormalized $request)))
         ($tier (default_router $prompt_contents_normalized))
         ($_ (log INFO "providers" $tier))
        )
        (py-call (providers.llmProviderChat $request $tier)))
    )
    ($_otherwise (py-call (providers.llmProviderChat $request "none")))
   )))

(= (llmRequestMessage role $role content $content)
   (py-call (providers.llmRequestMessage $role $content)))

(= (llmToolCallResponseMessage role $role callid $callid content $content)
   (py-call (providers.llmToolCallResponseMessage $role $callid $content)))

(= (llmToolCallMessage role $role calls $calls content $content)
   (py-call (providers.llmToolCallMessage $role $calls $content)))

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
