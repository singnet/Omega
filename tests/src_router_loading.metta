!(import! &self ./tests/lib/utils)
!(import! &self ./src/utils)
!(import! &self ../src/logger.py)
!(import! &self ./src/log)
!(import! &self ./src/plugin)
!(import! &self ../src/providers.py)
!(import! &self ./src/providers)

!(initLogger)

; Inspect the loaded definition without invoking the router.
!(test (loadPlugin (metta "default" "./routers")) ())
!(test (collapse (match &plugin-default (= (default-LLM-ROUTER $prompt) $body) loaded)) (loaded))
