!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
!(import! &self ./src/loop)

; orderedContextSections is a pure function of the two section strings and returns
; the sections as a plain tuple, so the ordering can be checked directly without
; loop state, the global flag, or building the final string.

; Flag off (default): the volatile results section stays ahead of HISTORY, which
; keeps the assembled prompt byte-for-byte identical to the original layout.
!(test (orderedContextSections False "RESULT" "HIST")
       (" LAST_SKILL_USE_RESULTS: " "RESULT" " HISTORY: " "HIST"))

; Flag on: HISTORY moves ahead of the volatile results section.
!(test (orderedContextSections True "RESULT" "HIST")
       (" HISTORY: " "HIST" " LAST_SKILL_USE_RESULTS: " "RESULT"))

; The flag can arrive as a string (command line, environment variable or config
; file all deliver strings), a symbol or a boolean; is_true accepts all of them so
; operators can actually turn it on, not only by editing the default.
!(test (== (py-call (helper.is_true "True")) 1) True)
!(test (== (py-call (helper.is_true "true")) 1) True)
!(test (== (py-call (helper.is_true "False")) 1) False)
!(test (== (py-call (helper.is_true True)) 1) True)
!(test (== (py-call (helper.is_true False)) 1) False)
