!(import! &self (library Omega ./plugins/playwright/playwright_bridge.py))

(= (playwrightEnabled) (empty))
(= (playwrightBrowser) (empty))
(= (playwrightHeadless) (empty))
(= (playwrightTimeoutMs) (empty))
(= (playwrightMaxTextChars) (empty))
(= (playwrightSettleMs) (empty))
(= (playwrightDownloadDir) (empty))
(= (playwrightMaxDownloadBytes) (empty))

(= (loadOmegaPlugin)
   (progn
     (configure playwrightEnabled enabled)
     (configure playwrightBrowser chromium)
     (configure playwrightHeadless True)
     (configure playwrightTimeoutMs 15000)
     (configure playwrightMaxTextChars 20000)
     (configure playwrightSettleMs 750)
     (configure playwrightDownloadDir
                (joinPath ((memoryDirectory) browser_downloads)))
     (configure playwrightMaxDownloadBytes 10485760)
     (if (== (playwrightEnabled) enabled)
       (progn
         (py-call (playwright_bridge.configure
                    (playwrightBrowser)
                    (playwrightHeadless)
                    (playwrightTimeoutMs)
                    (playwrightMaxTextChars)
                    (playwrightSettleMs)
                    (playwrightDownloadDir)
                    (playwrightMaxDownloadBytes)))
         (add-skill browser-open
                    "Open a public HTTP(S) URL in a new selected tab in the shared browser session and return its tab ID, readable text, and numbered click targets"
                    (url_in_quotes))
         (add-skill browser-tabs
                    "List all open browser tab IDs and URLs, marking the selected tab; includes popups"
                    ())
         (add-skill browser-switch
                    "Select an open tab by its ID from browser-tabs and return a fresh page snapshot; use the new click target numbers"
                    (tab_id))
         (add-skill browser-close-tab
                    "Close a tab by ID and list remaining tabs; if selected, select the oldest remaining tab; call browser-read before clicking"
                    (tab_id))
         (add-skill browser-navigate
                    "Navigate the selected tab to a public HTTP(S) URL without opening a new tab and return a fresh page snapshot"
                    (url_in_quotes))
         (add-skill browser-read
                    "Read the current page and return its URL, title, visible text, and numbered click targets"
                    ())
         (add-skill browser-screenshot
                    (strings-concat
                      ("Save a full-page PNG screenshot of the selected tab into "
                       (playwrightDownloadDir)
                       "; by default the browser_downloads subdirectory of SAVE_PERMANENT_FILES_DIR. Returns the full saved path, byte count, and tab ID; errors return BROWSER-SCREENSHOT-FAILED"))
                    ())
         (add-skill browser-back
                    "Go back in the selected tab's history and return a fresh snapshot; unchanged if no previous entry"
                    ())
         (add-skill browser-forward
                    "Go forward in the selected tab's history and return a fresh snapshot; unchanged if no next entry"
                    ())
         (add-skill browser-reload
                    "Reload the selected tab and return a fresh page snapshot"
                    ())
         (add-skill browser-find
                    "Search the selected page's current text without case sensitivity and return matching excerpts with character offsets; at most 50 matches"
                    (text_in_quotes))
         (add-skill browser-read-more
                    "Return the next text chunk from the selected tab's latest captured snapshot until END_OF_TEXT; browser-read refreshes the text and restarts at the beginning"
                    ())
         (add-skill browser-links
                    "List up to 200 visible link labels and destination URLs in the selected tab; URLs are informational and not validated; use browser-read for click target numbers"
                    ())
         (add-skill browser-click
                    "Click a numbered target from the latest browser page snapshot and return the resulting page snapshot"
                    (target_number))
         (add-skill browser-select
                    "Select one option in a native dropdown using its target number and exact option label or value from browser-options; labels take precedence; replaces any prior selections and returns a fresh snapshot; errors return BROWSER-SELECT-FAILED"
                    (target_number option_in_quotes))
         (add-skill browser-options
                    "List up to 200 options for one native dropdown using its target number from browser-read. Shows labels, values, disabled and selected states without scanning the rest of the page. Target numbers are unchanged. Use browser-select to choose an option."
                    (target_number))
         (add-skill browser-type
                    "Fill a visible editable field and verify its contents; empty text clears it. Allows up to 2 retries after the initial attempt (3 total). Does not submit. Returns a brief confirmation; ONLY target 1 refers to the filled field until the next snapshot. Default search workflow: after success call browser-read; if results already updated, stop. Otherwise browser-click the Search button associated with that field; if none is available, browser-press-enter on the search field. Use the refreshed target numbers and inspect results afterward. On BROWSER-TYPE-FAILED do not start another retry cycle or submit: inspect and report the failure. Text may be partially entered."
                    (target_number text_in_quotes))
         (add-skill browser-press-enter
                    "Press Enter in an editable field. For search, first use browser-read and prefer clicking the Search button associated with the field; use Enter if no such button is available. Never submit after failed typing or if results already updated. Use the search field number from the latest snapshot (target 1 only immediately after browser-type). Waits for DOM loading and the settling delay, then returns a fresh snapshot; inspect results to confirm success. In multiline fields Enter may insert a newline. Errors return BROWSER-PRESS-ENTER-FAILED"
                    (target_number))
         (add-skill browser-scroll
                    "Scroll the current page up or down by a pixel amount, then return a refreshed page snapshot; positive numbers scroll down and negative numbers scroll up"
                    (pixel_amount))
         (add-skill browser-wait
                    "Wait briefly for asynchronous page content to update, then return a refreshed page snapshot; maximum 10000 milliseconds"
                    (milliseconds))
         (add-skill browser-download
                    (strings-concat
                      ("Download a numbered target from the selected tab's latest snapshot into "
                       (playwrightDownloadDir)
                       "; by default this is the browser_downloads subdirectory of SAVE_PERMANENT_FILES_DIR (the permanent files directory). Enforces the configured size limit and returns the full saved file path, byte count, and SHA-256 hash"))
                    (target_number))
         (add-skill browser-close
                    "Close and discard the playwright browser session, including all session cookies and storage"
                    ())
         (log INFO "playwright-plugin" "playwright read/click browser skills enabled")
         ())
       (log INFO "playwright-plugin" "playwright read/click browser skills disabled"))))

(= (browser-open $url)
   (py-call (playwright_bridge.open_page $url)))

(= (browser-tabs)
   (py-call (playwright_bridge.list_tabs)))

(= (browser-switch $tab)
   (py-call (playwright_bridge.switch_tab $tab)))

(= (browser-close-tab $tab)
   (py-call (playwright_bridge.close_tab $tab)))

(= (browser-navigate $url)
   (py-call (playwright_bridge.navigate_page $url)))

(= (browser-read)
   (py-call (playwright_bridge.read_page)))

(= (browser-screenshot)
   (py-call (playwright_bridge.screenshot_page)))

(= (browser-back)
   (py-call (playwright_bridge.back_page)))

(= (browser-forward)
   (py-call (playwright_bridge.forward_page)))

(= (browser-reload)
   (py-call (playwright_bridge.reload_page)))

(= (browser-find $text)
   (py-call (playwright_bridge.find_text $text)))

(= (browser-read-more)
   (py-call (playwright_bridge.read_more)))

(= (browser-links)
   (py-call (playwright_bridge.list_links)))

(= (browser-click $target)
   (py-call (playwright_bridge.click_target $target)))

(= (browser-select $target $option)
   (py-call (playwright_bridge.select_dropdown $target $option)))

(= (browser-options $target)
   (py-call (playwright_bridge.list_options $target)))

(= (browser-type $target $text)
   (py-call (playwright_bridge.type_text $target $text)))

; Accept the bot parser's combined field-number-and-text string.
(= (browser-type $request)
   (py-call (playwright_bridge.type_text $request)))

(= (browser-press-enter $target)
   (py-call (playwright_bridge.press_enter $target)))

(= (browser-scroll $pixels)
   (py-call (playwright_bridge.scroll_page $pixels)))

(= (browser-wait $milliseconds)
   (py-call (playwright_bridge.wait_and_read $milliseconds)))

(= (browser-download $target)
   (py-call (playwright_bridge.download_target $target)))

(= (browser-close)
   (py-call (playwright_bridge.close_browser)))
