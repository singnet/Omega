;Configured at runtime memory and history in amount of characters:
(= (maxFeedback) (empty))
(= (maxRecallItems) (empty))
(= (maxEpisodeRecallLines) (empty))
(= (maxHistory) (empty))
(= (embeddingprovider) (empty))

(= (initMemory)
   (progn (log INFO "memory" "Initializing memory")
          (configure maxFeedback 50000)
          (configure maxRecallItems 20)
          (configure maxEpisodeRecallLines 20)
          (configure maxHistory 30000)
          (configure embeddingprovider Local) ;OpenAI or Local
          (if (== (embeddingprovider) Local)
              (py-call (lib_llm_ext.initLocalEmbedding)) _)))

(= (getPrompt $provider)
   (let $model_prompt
         (library Omega (py-str ("./memory/prompt_" $provider ".txt")))
     (if (exists-file $model_prompt)
         (read-file $model_prompt)
         (let $default_prompt ;Safely read the default prompt. Return an empty string if the file does not exist.
               (library Omega ./memory/prompt.txt)
           (if (exists-file $default_prompt)
               (read-file $default_prompt)
               "")))))

(= (getHistory)
   (let $history_file
         (library Omega ./memory/history.metta)
     (if (exists-file $history_file) ;Safely read the history. Return an empty string if the file does not exist.
         (read_file_tail $history_file (maxHistory))
         "")))

(= (addToHistory $lastmessage $response $sexpr $msgnew)
   (if $msgnew
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))))

(= (embed $str)
   (if (== (embeddingprovider) Local)
       (py-call (lib_llm_ext.useLocalEmbedding (string-safe $str)))
       (py-call (rag.openai_embed (string-safe $str)))))

(= (appendToHistory $addition)
   (append-file-raw (library Omega ./memory/history.metta) (swrite $addition)))

(= (createMemory $str)
   (let* (($current_time_str (get_time_as_string))
          ($uuid (py-call (lib_chromadb.remember $str (embed $str) $current_time_str))))
         (progn (py-call (lib_chromadb.link_episode $uuid $current_time_str))
                $uuid)))

(= (remember $str)
   (progn (createMemory $str)
          REMEMBER-SUCCESS))

(= (query $str)
   (py-call (lib_chromadb.query (embed $str) (maxRecallItems))))

(= (episodes $time)
   (py-call (helper.around_time $time (maxEpisodeRecallLines))))

;MeTTaClaw2

(= (forget $time)
   (let $oldids (py-call (lib_chromadb.ids_by_time $time))
        (if (!= $oldids ())
            (progn (py-call (lib_chromadb.forget_ids $oldids))
                   FORGET-SUCCESS)
            FORGET-FAILED-LTM-ITEM-OF-TIME-DID-NOT-EXIST)))

(= (update $ttime $newStr)
   (let* (($time (replace_underscores $ttime))
          ($oldids (py-call (lib_chromadb.ids_by_time $time)))
          ($memories (py-call (lib_chromadb.query_by_ids $oldids)))
          ($episodesPre (collapse (let* ((($oldid $t $c) (superpose $memories))
                                      ($L (py-call (lib_chromadb.query_linked_episodes $oldid))))
                                    (superpose $L))))
          ($episodes (if (== $episodesPre ()) ;old system did not have it so we import the creation time episode at least, while new always has it
                         ($time)
                         $episodesPre)))
         (if (!= $oldids ())
             (let $newid (createMemory $newStr)
                  (progn (py-call (lib_chromadb.forget_ids $oldids))
                         (collapse (let $episode (superpose $episodes)
                                        (py-call (lib_chromadb.link_episode $newid $episode))))
                         (collapse (let* (($oldid (superpose $oldids))
                                          (($s $c) (py-call (lib_chromadb.get_stv $oldid))))
                                         (progn (if (!= ($s $c) (1.0 0.5))
                                                    (py-call (lib_chromadb.set_stv $newid $s $c)) _))))
                         UPDATE-SUCCESS))
             UPDATE-FAILED-LTM-ITEM-OF-TIME-DID-NOT-EXIST)))

(= (tvUpdate $LTM_time $EPISODE_time $sign)
   (let* (($ltm_time (replace_underscores $LTM_time))
          ($episode_time (replace_underscores $EPISODE_time)))
         (progn (link $ltm_time $episode_time)
                (let $oldids (py-call (lib_chromadb.ids_by_time $ltm_time))
                     (if (!= $oldids ())
                         (progn (collapse (let* (($oldid (superpose $oldids))
                                                 (($s $c) (py-call (lib_chromadb.get_stv $oldid)))
                                                 ((stv $snew $cnew) (Truth_Revision (stv $s $c) (stv (if $sign 1.0 0.0) 0.5))))
                                                (py-call (lib_chromadb.set_stv $oldid $snew $cnew))))
                                REVISION-SUCCESS)
                         REVISION-FAILED-LTM-ITEM-OF-TIME-DID-NOT-EXIST)))))

(= (support $LTM_time $EPISODE_time)
   (tvUpdate $LTM_time $EPISODE_time True))

(= (contradict $LTM_time $EPISODE_time)
   (tvUpdate $LTM_time $EPISODE_time False))

(= (link $LTM_time $EPISODE_time)
   (let* (($ltm_time (replace_underscores $LTM_time))
          ($episode_time (replace_underscores $EPISODE_time))
          ($uuids (py-call (lib_chromadb.ids_by_time $ltm_time))))
        (progn (collapse (let $uuid (superpose $uuids)
                              (py-call (lib_chromadb.link_episode $uuid $episode_time))))
               (if (== $uuids ())
                   LINK-FAIL-LTM-ITEM-NOT-EXISTING
                   LINK-SUCCESS))))

(= (unlink $LTM_time $EPISODE_time)
   (let* (($ltm_time (replace_underscores $LTM_time))
          ($episode_time (replace_underscores $EPISODE_time))
          ($uuids (py-call (lib_chromadb.ids_by_time $ltm_time))))
        (progn (collapse (let $uuid (superpose $uuids)
                              (py-call (lib_chromadb.unlink_episode $uuid $episode_time))))
               (if (== $uuids ())
                   UNLINK-FAIL-LTM-ITEM-NOT-EXISTING
                   UNLINK-SUCCESS))))

