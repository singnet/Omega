;----------------;
; Default router ;
;----------------;
;
; The simple default router looks for single terms in tool results and user messages and
; returns either "economy" tier model or "premium" tier model. It also checks other criteria
; as defined herein.
; If a complexity condition is found, the premium model tier is returned, else the economy model. 
; The default_router can be refined to look for a variety of conditions and keywords.

; Create term atoms for fast access. Note a sequence number is attached for reference.
(= (create_temp_atoms $prompt_list $seq_number)
   (if (== $prompt_list ())
      True
      (let*
        (
        ($atom (car-atom $prompt_list))
        ($next_number (+ $seq_number 1))
        ($_ (add-atom &temp (prompt_atom $atom $next_number)))
        ($_ (log INFO "atom>" ($atom $next_number)))
        )
        (create_temp_atoms (cdr-atom $prompt_list) $next_number))))

(= (lookup_term $term)
    (match &temp (prompt_atom $atom $_) 
                        (if (== $atom $term)
                           $atom
                           (empty))))

(= (delete_temp_atoms)
   (collapse (match &temp (prompt_atom $x $seq) (remove-atom &temp (prompt_atom $x $seq)))))

; Look for a variety of common situations signalling the need for a premium model call.
; Return either an economy model or premium model tier.
; Note:  The $prompt variable represents a subset of the prompt -- the tool call results and
;     user messages.
(= (default_router $prompt)
   (let* (
         ; create a list of terms, type string, using native Prolog from the single prompt string.
         ($prompt_list (split_string $prompt " " " "))
         ($_ (create_temp_atoms $prompt_list 0))
         ; look for simple terms hinting at complexity
         ($found_complexity_term 
               (collapse (lookup_term 
                    (superpose 
                         ; INSERT TERMS TO LIST TO FLAG COMPLEXITY, USER LOWERCASE TYPE STRING
                         ("alert_failed" "premium" "error")))))

         ; Create list to check for more than one user message
         ($number_of_user_msgs (collapse (match &temp (prompt_atom "role_user" $seq) $seq)))
         ; Create list to count the total number of tool results and user messages 
         ($number_of_issues (collapse (match &temp (prompt_atom $atom $seq) 
                              (if (or (== $atom "role_user") (== $atom "role_tool")) 
                                    $seq
                                    (empty))))) 
         ; cleanup
         ($_ (delete_temp_atoms))
         )
         (if (and 
               (and (== $found_complexity_term ()) (< (size-atom $number_of_user_msgs) 2 ))
                    (< (size-atom $number_of_issues) 9))
                           economy_model
                           premium_model)))
