!(import_prolog_function atomic_list_concat)
!(import_prolog_function split_string)
!(import_prolog_function read_line_to_string)
!(import_prolog_function get_time)
!(import_prolog_function string_length)
!(import_prolog_function sub_string)
!(import_prolog_function swrite)
!(import_prolog_function sread)
!(import_prolog_function string_concat)
!(import_prolog_function make_directory)

(= (sleep $t)
   (progn (translatePredicate (sleep $t))
          True))

(: empty-to-bool (-> Expression Bool))
(= (empty-to-bool $predicate)
   (case (eval $predicate)
     ((Empty False)
      (True True))))

(= (exists-file $path)
   (empty-to-bool (translatePredicate (exists_file $path))))

(= (exists-directory $path)
   (empty-to-bool (translatePredicate (exists_directory $path))))

(= (make-directory $path)
  (let $rc (catch (((translatePredicate (make_directory $path)))))
    (return-on-error $rc True)))

(= (string-replace $str $a $b)
   (atomic_list_concat (split_string $str $a "") $b))

(= (string-safe $str)
   (string-replace (string-replace (string-replace $str "\"\"" "_quote_") "\n" "_newline_") "'" "_apostrophe_"))

(= (get_time_as_string)
   (progn (translatePredicate (format_time (Predicate (string $String)) "%Y-%m-%d %H:%M:%S" (get_time)))
          $String))

(= (last_chars $String $N)
   (let $Len (string_length $String)
        (sub_string $String (max 0 (- $Len $N)) $_ 0)))

(= (take $k ()) ())
(= (take $k (cons $h $t))
   (if (== $k 0)
       ()
       (cons $h (take (- $k 1) $t))))

(= (newline)
   (progn (translatePredicate (atom_codes $NL (10)))
          $NL))

(= (atom_to_number $str)
   (let $res (collapse (progn (translatePredicate (atom_number $str $num)) $num))
        (if (== () $res)
            $str
            (car-atom $res))))

(= (argk $Prefix)
   (let $Atom (argv $1)
         (let $KeyEq (string_concat $Prefix "=")
            (progn
               (translatePredicate (atom_string $Atom $Str))
               (translatePredicate (sub_string $Str 0 $KeyLen $After $KeyEq))
               (translatePredicate (sub_string $Str $KeyLen $After 0 $Value))
               (translatePredicate (atom_string $Res $Value))
               (atom_to_number $Res)))))

(= (argk $Prefix $default)
   (let $res (collapse (argk $Prefix))
        (if (== $res ())
            $default
            (car-atom $res))))

(= (command-line)
   (collapse (argv $_)))

(= (join $sep $strings)
   (if (== $strings ())
     ""
     (let* (($head (car-atom $strings))
            ($tail (cdr-atom $strings)))
       (join $sep $tail $head))))

(= (join $sep $strings $prefix)
   (if (== $strings ())
     $prefix
     (let* (($head (car-atom $strings))
            ($tail (cdr-atom $strings)))
       (join $sep $tail (string_concat (string_concat $prefix $sep) $head)))))

(= (strings-concat $strings)
   (join "" $strings))

(= (atom-concat $a $b)
   (atomic_list_concat ($a $b)))

(= (projectRootDirectory)
   (py-call (helper.projectRootDirectory)))

(= (joinPath $parts)
   (progn
     (let $path (py-call (helper.joinPath $parts)) ())
     (swrite $path)))
