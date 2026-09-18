!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)

(= (foo) True)
(= (bar) (empty))

!(test (empty-to-bool (foo)) True)
!(test (empty-to-bool (bar)) False)

;This test relies on mettatest.sh script changes directory to the project root
!(test (projectRootDirectory)
       (let True (translatePredicate (absolute_file_name "." $root)) $root))

!(test (exists-directory "./not-exist") False)
!(test (exists-directory (projectRootDirectory)) True)

!(test (joinPath ("a" "b"))
       "a/b")
!(test (joinPath ("a/" "b"))
       "a/b")

!(test (swrite a) "a")
!(test (swrite "a") "\"a\"")
!(test (swrite (a b)) "(a b)")
