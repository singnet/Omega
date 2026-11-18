; A context provider handles input, renders working context and observes tool
; results. The default provider needs no plugin state.
(= (initContext)
   (set-context-provider default-context-provider))

(= (set-context-provider $callback)
   (change-state! &context-provider $callback))

(= (context-event $event)
   (let $callback (get-state &context-provider)
     ($callback $event)))

(= (default-context-provider (Input $message $isNew))
   (if $isNew
       $message
       "[NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK. DO NOT REPEAT THE PREVIOUS RESPONSE. ONLY USE send FOR GENUINELY NEW INFORMATION OR WHEN USER INPUT IS NEEDED.]"))

(= (default-context-provider Prompt)
   (py-str ("HISTORY: " (getHistory))))

(= (default-context-provider BeforeRequest) ())

(= (default-context-provider (AfterTools $context $commands $results)) ())

(= (default-context-provider Idle) ())
