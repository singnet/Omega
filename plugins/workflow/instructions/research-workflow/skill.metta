; Declare skills to be added to the agent skills when workflow is loaded and
; removed on unloading workflow

(skill research-start "Create research project folders" (research_name topic))
(skill research-step "Mark research step done" (research_name step result next_action))
(skill research-checkpoint "Pause for user approval" (researchname message))
(skill research-complete "Finish research and unload workflow" (researchname))
(skill load-research-dynamic-instructions " Load a generated file into active context" (researchname_in_quotes filename_in_quotes))
(skill research-write-file "Write a UTF-8 file inside an existing research project" (research_name relative_path content))
(skill researchDir "Get research directory" ())

;; Actual skills implementation

(= (load-research-dynamic-instructions $research-name $filename)
   (if (not (valid-file-or-folder-name $research-name))
       (send (file-or-folder-name-error "research name"))
       (if (not (valid-file-or-folder-name $filename))
           (send (file-or-folder-name-error "filename"))
           (let $result (py-call (fileio.read_research_instructions (memoryDirectory) (pluginWorkflowMemoryDir) $research-name $filename))
             (let $message (string_concat "" (car-atom (cdr-atom $result)))
               (if (== (car-atom $result) ok)
                 (progn
                   (workflow-change-active-instructions $message)
                   (send (strings-concat ("Loaded " $filename " for " $research-name ". Following instructions."))))
                 (send $message)))))))

; Returning no value stops callers that compose this path with a filename.
(= (researchDir)
   (let $path (string_concat "" (py-call (fileio.research_directory (memoryDirectory) (pluginWorkflowMemoryDir))))
     (if (== $path "") (empty) $path)))

(= (research-start $research-name $topic)
   (if (valid-file-or-folder-name $research-name)
       (send (string_concat "" (py-call (fileio.start_research (memoryDirectory) (pluginWorkflowMemoryDir) $research-name $topic))))
       (send (file-or-folder-name-error "research name"))))

(= (research-write-file $research-name $filename $content)
   (py-call (fileio.write_research_file (memoryDirectory) (pluginWorkflowMemoryDir) $research-name $filename $content)))

;; update current step
(= (research-step $research-name $step $result $next)
    (if (valid-file-or-folder-name $research-name)
        (progn
            (send (strings-concat ("[" $research-name "] done: " $step)))
            (strings-concat ("Done: " $step)))
        (send (file-or-folder-name-error "research name"))
     )
)


;; Checkpoint: wait user's response
(= (research-checkpoint $research-name $message)
    (if (valid-file-or-folder-name $research-name)
        (progn
              (send (strings-concat ("CHECKPOINT [" $research-name "]\n" $message "\n"
                             "Reply to continue.")))
              "Waiting for user")
        (send (file-or-folder-name-error "research name"))
     )
)

;; Unload research skill
(= (research-complete $research-name)
   (if (valid-file-or-folder-name $research-name)
       (let $dirs (collapse (researchDir))
         (let $location (if (== $dirs ()) "Research directory is unavailable."
                           (strings-concat ("Results in " (car-atom $dirs) "/" $research-name "/")))
           (progn (workflow-unload-instructions)
                  (send (strings-concat ("Research complete: " $research-name "\n" $location
                                         "\nWorkflow unloaded from context.")))
                  "Research complete, workflow unloaded")))
       (send (file-or-folder-name-error "research name"))))
