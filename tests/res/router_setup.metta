; Exercise the real router with isolated state and no external messaging/logging.
!(import! &self ./src/utils)
(= (log $level $component $message) ())
(= (commChannelSend $message) ())
!(import! &plugin-default ./plugins/router/default)
