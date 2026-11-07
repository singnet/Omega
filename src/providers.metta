(= (llmProvidersInitialize)
   (progn
      (py-call (providers.llmProvidersInitDict))
      (match &self (routerCatalog $catalog)
         (llmProvidersStartEntries $catalog))))

(= (llmProvidersStartEntries $entries)
   (if (== $entries ())
       ()
       (let $entry (car-atom $entries)
          (let* (($role (car-atom $entry))
                 ($fields (car-atom (cdr-atom $entry)))
                 ($provider (llmProviderField provider $fields))
                 ($model (llmProviderField model $fields))
                 ($api_token_var (llmProviderField api_token_var $fields))
                 ($url (llmProviderField openaiapi_url $fields)))
             (progn
                (py-call (providers.llmProviderStart $role $provider $model $api_token_var $url))
                (llmProvidersStartEntries (cdr-atom $entries)))))))

(= (llmProviderField $key $fields)
   (if (== $fields ())
       none
       (let $field (car-atom $fields)
          (if (== $key (car-atom $field))
              (car-atom (cdr-atom $field))
              (llmProviderField $key (cdr-atom $fields))))))

(= (llmProviderChat $request $router)
   (if (== $router none)
      (py-call (providers.llmProviderChat $request "routine"))
   (let* 
        (
         ($prompt_contents_normalized (py-call (providers.llmRequestContentsNormalized $request)))
         ($tier ($router $prompt_contents_normalized))
        )
        (py-call (providers.llmProviderChat $request $tier)))))
    
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
