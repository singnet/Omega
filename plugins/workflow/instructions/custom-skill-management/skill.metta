; Skills to manage custom skills kept in (pluginWorkflowCustomInstructionsDir).
; Core skills in (pluginWorkflowInstructionsDir) are never touched.

(skill custom-skill-list "List names of custom skills" ())
(skill custom-skill-read "Read a file of a custom skill, file_name is SKILL.md, description.txt or skill.metta" (skill_name file_name))
(skill custom-skill-write "Create or overwrite a file of a custom skill, file_name is SKILL.md, description.txt or skill.metta" (skill_name file_name content))
(skill custom-skill-delete "Delete a custom skill with all its files" (skill_name))

;; Actual skills implementation

(= (custom-skill-valid-file $file)
   (or (== $file "SKILL.md")
       (or (== $file "description.txt")
           (== $file "skill.metta"))))

(= (custom-skill-invalid-file-message $file)
   (strings-concat ("ERROR: invalid file name: " $file ". Allowed: SKILL.md, description.txt, skill.metta")))

(= (custom-skill-exists $name)
   (let $skills (custom-skill-list)
     (empty-to-bool (translatePredicate (memberchk $name $skills)))))

(= (custom-skill-list)
   (directory-dirs (pluginWorkflowCustomInstructionsDir)))

(= (custom-skill-read $name $file)
   (if (not (custom-skill-valid-file $file))
     (Error (quote (custom-skill-read $name $file)) (custom-skill-invalid-file-message $file))
     (let $path (joinPath ((pluginWorkflowCustomInstructionsDir) $name $file))
       (if (exists-file $path)
         (read-file $path)
         (Error (quote (custom-skill-read $name $file)) (strings-concat ("ERROR: file not found: " $path)))))))

(= (custom-skill-write $name $file $content)
   (if (not (custom-skill-valid-file $file))
     (Error (quote (custom-skill-write $name $file)) (custom-skill-invalid-file-message $file))
     (let* (($dir (joinPath ((pluginWorkflowCustomInstructionsDir) $name)))
            ($rc (make-directory-path $dir)))
       (if (exists-directory $dir)
         (write-file (joinPath ($dir $file)) $content)
         (Error (quote (custom-skill-write $name $file)) (strings-concat ("ERROR: could not create directory: " $dir)))))))

(= (custom-skill-delete $name)
   (if (not (custom-skill-exists $name))
     (Error (quote (custom-skill-delete $name)) (strings-concat ("ERROR: custom skill not found: " $name)))
     (let* (($path (joinPath ((pluginWorkflowCustomInstructionsDir) $name)))
            ($rc (catch (((translatePredicate (delete_directory_and_contents $path)))))))
       (if (exists-directory $path)
         (Error (quote (custom-skill-delete $name)) (strings-concat ("ERROR: could not delete directory: " $path)))
         (strings-concat ("DELETE-VERIFIED " $path))))))
