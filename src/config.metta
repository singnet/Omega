; Initialize configuration: load configuration file and drop configuration
; cache.
(= (initConfig)
   (progn
     (py-call (config.init_config (command-line)))
     ()))

; Get the value of the $key (use $default if $key is not found) and add ($key)
; function to the atomspace to allow using MeTTa call for getting the
; parameter's value.
(= (configure $key $default)
   (case $key 
      (
      ;convert the input JSON router catalog, if provided into a MeTTa expression.
      (routerCatalogFile
         (let $filename (configGetByKey routerCatalogFile $default)
            (if (== $filename none)
               ; for backward compatibility, if no router catalog, if we find a provider= parameter
               ; assigned, use the provider= for the "routine" LLM call role.
               (let $model (configGetByKey model none) 
                  (let $provider (provider) 
                     (let*
                       (($api_token_var (lookup_api_token_var $provider))
                        ($openaiurl (configGetByKey openaiapi_url http://localhost:11434/v1/)))
                        (add-atom &self (routerCatalog ((routine ((provider $provider) 
                                                                  (model $model) 
                                                                  (api_token_var $api_token_var)
                                                                  (openaiapi_url $openaiurl)))))))))

               ; else the user has input an LLM router file
               (let $text (py-call (config.read_router_catalog $filename)) 
                   (let* ( 
                          ($catalog (sread $text)) 
                         )
                         (progn 
                           (add-atom &self $catalog)
                           (add-atom &self (= ($key) $filename))))
                           ))))

      ($_ (let $value (configGetByKey $key $default)
               (add-atom &self (= ($key) $value))))
      )))

; Get configuration parameter from the list of sources: (1) command line
; parameters, (2) environment variable with OMEGA_$key name, (3)
; configuration file, (4) use $default value.
(= (configGetByKey $key $default)
   (py-call (config.config_get_by_key $key $default)))
