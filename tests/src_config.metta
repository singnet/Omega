!(import! &self ./lib/utils.py)
!(import! &self ../src/config.py)
!(import! &self ./src/config)

(= (cleanup)
   (progn
     (match &self (= (command-line) $b) (remove-atom &self (= (command-line) $b)))
     (py-call (utils.unsetenv arg_))))

; empty configuration

(= (command-line)
   ("config=./tests/res/src_config_empty.yaml"
    "arg_cmdline=val_cmdline"))
!(py-call (utils.setenv OMEGA_arg_env val_env))
!(initConfig)

!(test (configGetByKey arg_config val_default) val_default)
!(test (configGetByKey arg_cmdline val_default) val_cmdline)
!(test (configGetByKey arg_env val_default) val_env)
!(test (configGetByKey arg_notexist val_default) val_default)

; Numeric CLI values must survive configure and Prolog arithmetic.
!(cleanup)
(= (command-line)
   ("config=./tests/res/src_config_empty.yaml"
    "maxFeedback=25000"
    "sleepInterval=0.5"))
!(initConfig)
!(configure maxFeedback 50000)
!(configure sleepInterval 1)
!(test (+ (maxFeedback) 1) 25001)
!(test (+ (sleepInterval) 0.5) 1.0)

!(cleanup)

; filled configuration

(= (command-line)
   ("config=./tests/res/src_config_filled.yaml"
    "arg_cmdline=val_cmdline"))
!(py-call (utils.setenv OMEGA_arg_env val_env))
!(initConfig)

!(test (configGetByKey arg_config val_default) val_config)
!(test (configGetByKey arg_cmdline val_default) val_cmdline)
!(test (configGetByKey arg_env val_default) val_env)
!(test (configGetByKey arg_notexist val_default) val_default)

!(configure arg_notexist val_default)
!(configure arg_config val_default)
!(configure arg_cmdline val_default)
!(configure arg_env val_default)

!(test (arg_notexist) val_default)
!(test (arg_config) val_config)
!(test (arg_cmdline) val_cmdline)
!(test (arg_env) val_env)

!(cleanup)

; priorities configuration

(= (command-line)
   ("config=./tests/res/src_config_priorities.yaml"
    "arg_cmdline=val_cmdline"))
!(py-call (utils.setenv OMEGA_arg_cmdline val_env))
!(py-call (utils.setenv OMEGA_arg_env val_env))
!(initConfig)

!(test (configGetByKey arg_cmdline val_default) val_cmdline)
!(test (configGetByKey arg_env val_default) val_env)
!(test (configGetByKey arg_config val_default) val_config)
!(test (configGetByKey arg_notexist val_default) val_default)
