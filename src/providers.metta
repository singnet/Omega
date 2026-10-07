(= (llmProviderStart $provider)
   (py-call (providers.llmProviderStart $provider)))

(= (llmProviderChat $request)
     (py-call (providers.llmProviderChat $request)))

(= (llmRequestMessage role $role content $content)
   (py-call (providers.llmRequestMessage $role $content)))

(= (llmRequestMessage role $role callid $callid content $content)
   (py-call (providers.llmToolCallResponseMessage $role $callid $content)))

(= (llmRequestMessage role $role calls $calls content $content)
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

(= (llmToolCallToSExpr $call)
   (py-call (providers.llmToolCallToSExpr $call)))
