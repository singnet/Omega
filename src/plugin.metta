(= (initPlugins)
   (progn
       (loadPlugins (py-call (plugin.listPlugins)))
       ()))

; Plugin loader

(= (loadPlugins $list)
   (map-atom $list $plugin (loadPlugin $plugin)))

(= (loadPlugin (python $name $location))
   (py-call (plugin.loadPythonPlugin $name $location)))

(= (loadPlugin (metta $name $location))
   (loadMettaPlugin $name $location))

(= (loadMettaPlugin $name $location)
   (let $rc1
       (if (== $location "")
         (Error (_loadMettaPlugin $name $location) (strings-concat ("Location is empty")))
         (progn
           (let $path (joinPath ($location $name)) ())
           (let $space (atom-concat & (atom-concat plugin- $name)) ())
           (log INFO "plugin" (strings-concat ("Loading MeTTa plugin " $name " from " $path ".metta")))
           ; put the plugin folder on sys.path so it can py-call into its own .py files
           (let $addpathrc (py-call (plugin.addLocationToPath $location)) ())
             (if (== () (collapse (import! $space $path)))
               (Error (_loadMettaPlugin $name $location) (strings-concat ("Cannot import " $name " plugin from " $path)))
               (progn
                 (let $rcs (collapse (eval (loadOmegaPlugin))) ())
                 (match $space (= (loadOmegaPlugin) $body) (remove-atom $space (= (loadOmegaPlugin) $body)))
                 (let $agg (|-> ($acc $next) (if (== $acc ()) (if (== Error (car-atom $next)) $next ()) ()))
                   (let $rc (foldl-atom $rcs () $agg) ()))
                 $rc))))
       (progn
         (if (= $rc1 (cons Error (cons $_ $error)))
             (progn
               (log ERROR "plugin" $error)
               (log ERROR "plugin" (strings-concat ("Plugin " $name " loading failed")))
               $rc1)
             (progn
               (log INFO "plugin" (strings-concat ("Plugin " $name " is loaded")))
               ())))))
