;
;----------------;
; Default router ;
;----------------;
;
; The simple default router looks for single terms in tool results and user messages and
; returns either role "routine" tier model or role "premium" tier model. It also checks other criteria
; as defined herein.
;
; The default router can be refined to look for a variety of conditions and keywords.

; Using the prompt, create term atoms for fast access. Note a sequence number is attached for reference.
(= (create_temp_atoms $prompt_list $seq_number)
   (if (== $prompt_list ())
      True
      (let*
        (
        ($atom (car-atom $prompt_list))
        ($next_number (+ $seq_number 1))
        ($_ (add-atom &plugin-default (prompt_atom $atom $next_number)))
        )
        (create_temp_atoms (cdr-atom $prompt_list) $next_number))))

(= (lookup_term $term)
    (match &plugin-default (prompt_atom $atom $_) 
                        (if (== $atom $term)
                           $atom
                           (empty))))

; Input a role like "role_user" and an atom, output the atom if it falls inside a "role_user".
; Note: presently this will only work for "role_user" segment lookups since "role_user" appear after "role_tool".
(= (lookup_term_by_role $role $term)
    (match &plugin-default (prompt_atom $role $role_sequence_no)
      (match &plugin-default (prompt_atom $atom $atom_sequence_no)
         (if (and (== $atom $term) (> $atom_sequence_no $role_sequence_no))
            $atom
            (empty)))))

(= (delete_temp_atoms)
   (collapse (match &plugin-default (prompt_atom $x $seq) (remove-atom &plugin-default (prompt_atom $x $seq)))))

; Look for a variety of common situations signalling the need for a premium model call.
; Return either routine or premium symbols.
; Note:  The $prompt variable represents a subset of the prompt -- the tool call results and
;     user messages.
(= (default $prompt)
   (let* (
         ; Create a list of terms, type string, using native Prolog from the single prompt string.
         ; We are using type string for terms in the prompt but this could be changed to symbols. 
         ($prompt_list (split_string $prompt " " " "))
         ($_ (create_temp_atoms $prompt_list 0))
         ; look for simple terms hinting at complexity
         ($found_complexity_term 
               (collapse (lookup_term 
                    (superpose 
                         ; INSERT TERMS TO LIST TO FLAG LIKELY COMPLEXITY, USER LOWERCASE TYPE STRING (prompt was converted)
                         ("alert_failed")))))

         ; Create list to check for more than one user message
         ($role_user_occurances (collapse (match &plugin-default (prompt_atom "role_user" $seq) $seq)))
         ($number_of_user_msgs (size-atom $role_user_occurances))

         ; Create list to count the total number of tool results and user messages 
         ($issues (collapse (match &plugin-default (prompt_atom $atom $seq) 
                              (if (or (== $atom "role_user") (== $atom "role_tool")) 
                                    $seq
                                    (empty)))))
         ($number_of_issues (size-atom $issues))

         ; If the user enters the "/premium" slash command, create an atom to latch the premium model on for all calls.
         ; If we find the "/routine" slash command, consider it a total reset by deleting any role of premium atom.
         ; The default model role is routine.
         ($found_routine_in_current_prompt
               (collapse (lookup_term_by_role "role_user" "/routine")))
         ($_ (if (> (size-atom $found_routine_in_current_prompt) 0)
               (progn
                  (commChannelSend "Switching to the routine model.")
                  (collapse (match &plugin-default (role $x) (remove-atom &plugin-default (role $x)))))
               ()))
         ; If we find the /premium slash command, add a role atom for premium to latch this on. 
         ; This will work if more than one "/premium" is found in the prompt.
         ($found_premium_in_current_prompt
               (collapse (lookup_term_by_role "role_user" "/premium"))) 
         ($_ (if (> (size-atom $found_premium_in_current_prompt) 0)
               (progn
                  (commChannelSend "Switching to the premium model.")
                  (add-atom &plugin-default (role /premium)))
               ()))
         ($premium_latched_on 
               (collapse (match &plugin-default (role /premium) premium)))
         ($premium_switch (if (> (size-atom $premium_latched_on) 0) 
               Y
               N))

         ; cleanup
         ($_ (delete_temp_atoms))
         )
         (if (or
               (or  
                  (or (> (size-atom $found_complexity_term) 0) (> $number_of_user_msgs 1))
                    (> $number_of_issues 9))
                       (== $premium_switch Y))
                           (progn (log INFO "router" (LLM: premium)) premium)
                           (progn (log INFO "router" (LLM: routine)) routine))))

; Required entry point for the MeTTa plugin loader.
(= (loadOmegaPlugin)
   ())