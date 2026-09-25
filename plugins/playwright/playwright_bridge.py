# -----------------------------------------------------------------------------
# Function: Execute Omega browser skill calls using Playwright, a browser automation
#           library that requires a real browser (Chromium, Firefox, or WebKit)
#           which can run headlessly without a visible window.
# Inputs:   Skill calls with browser action arguments, plus browser settings.
# Outputs:  Page snapshots, command results/errors, screenshots, and downloads.
# -----------------------------------------------------------------------------

import hashlib
import ipaddress
import json
import os
import re
import socket
import tempfile
from functools import wraps
from urllib.parse import urljoin, urlsplit

from src.logger import get_logger


logger = get_logger(__name__)

# Browser settings
_browser_name = "chromium"
_headless = True
_timeout_ms = 15_000
_max_text_chars = 20_000
_settle_ms = 750
_download_dir = ""
_max_download_bytes = 10 * 1024 * 1024
_explicit_download = None
_download_notice = ""

# Browser session state
_playwright = None
_browser = None
_context = None
_page = None
_targets = []
_tabs = {}
_next_tab_id = 1
_reading = None

############################################################################
# Utility functions supporting browser skill calls: validation, session
# management, page snapshots, downloads, error handling, etc.
############################################################################

# Wrap browser commands with consistent error reporting for skill calls.
def _browser_command(command):
    """Return skill-visible errors for validation and browser exceptions."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            global _targets, _download_notice, _reading
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                _clear_targets()
                _reading = None
                message = f"BROWSER-{command}-FAILED: {type(exc).__name__}: {exc}"
                if command == "TYPE":
                    message += (
                        "\nDo not retry this text-entry request or press Enter. "
                        "Text may already be partially entered. Use browser-read to "
                        "inspect the page and report the failure before taking another action."
                    )
                if _download_notice:
                    message += f"\n{_download_notice}"
                    _download_notice = ""
                logger.error(f"[PLAYWRIGHT] {message}")
                return message
        return wrapped
    return decorate


# Convert a setting value to a boolean using common true values.
def _as_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# Validate and store browser settings and prepare the download directory.
def configure(browser_name="chromium", headless=True, timeout_ms=15000,
              max_text_chars=20000, settle_ms=750, download_dir="",
              max_download_bytes=10485760):
    global _browser_name, _headless, _timeout_ms, _max_text_chars, _settle_ms
    global _download_dir, _max_download_bytes
    name = str(browser_name).strip().lower()
    if name not in {"chromium", "firefox", "webkit"}:
        raise ValueError("playwrightBrowser must be chromium, firefox, or webkit")
    _browser_name = name
    _headless = _as_bool(headless)
    _timeout_ms = max(1000, int(timeout_ms))
    _max_text_chars = max(1000, int(max_text_chars))
    _settle_ms = min(10_000, max(0, int(settle_ms)))
    _download_dir = os.path.realpath(str(download_dir).strip().strip('"'))
    if not _download_dir:
        raise ValueError("playwrightDownloadDir must not be empty")
    os.makedirs(_download_dir, exist_ok=True)
    _max_download_bytes = max(1, int(max_download_bytes))
    return True


# Validate an HTTP or HTTPS URL and reject credentials and non-public addresses.
def _validate_public_url(url):
    value = str(url).strip().strip('"')
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http:// and https:// URLs are allowed")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must have a hostname and must not contain credentials")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("local and private network URLs are not allowed")

    # Resolve before navigation to reject obvious SSRF targets. The request
    # interception below repeats this check for redirects and subresources.
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except socket.gaierror as exc:
        raise ValueError(f"hostname could not be resolved: {parsed.hostname}") from exc
    if not addresses:
        raise ValueError("hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("local and private network URLs are not allowed")
    return value


# Allow browser requests only when their URLs pass public-address validation.
def _route_request(route):
    try:
        _validate_public_url(route.request.url)
        route.continue_()
    except Exception:
        logger.warning("[PLAYWRIGHT] blocked non-public request")
        route.abort("blockedbyclient")


# Return the browser session, starting Playwright and the browser if needed.
def _ensure_context():
    global _playwright, _browser, _context
    if _context is not None:
        return _context

    # Import lazily so a disabled plugin does not require browser
    # binaries or initialize Playwright during normal OmegaClaw startup.
    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()
    browser_type = getattr(_playwright, _browser_name)
    _browser = browser_type.launch(headless=_headless)
    _context = _browser.new_context(
        accept_downloads=True,
        service_workers="block",
    )
    _context.set_default_timeout(_timeout_ms)
    _context.set_default_navigation_timeout(_timeout_ms)
    _context.route("**/*", _route_request)
    _context.on("page", _register_page)
    return _context


# Track a new tab and attach dialog, download, and close handlers.
def _register_page(page):
    """Track explicit tabs and popups without changing the selected tab."""
    global _next_tab_id
    if page in _tabs.values():
        return
    tab_id = _next_tab_id
    _next_tab_id += 1
    _tabs[tab_id] = page
    page.on("dialog", lambda dialog: dialog.dismiss())
    page.on("download", _handle_download)
    page.on("close", lambda: _forget_page(tab_id))


# Remove a closed tab and select a remaining tab when necessary.
def _forget_page(tab_id):
    global _page, _targets, _reading
    closed = _tabs.pop(tab_id, None)
    if closed is _page:
        _page = next(iter(_tabs.values()), None)
        _clear_targets()
        _reading = None


# Select a tab and clear the previous interaction targets and saved text.
def _select_page(page):
    global _page, _targets, _reading
    _page = page
    _clear_targets()
    _reading = None


# Format the open tab IDs and URLs and mark the selected tab.
def _tab_list():
    lines = ["BROWSER-TABS"]
    for tab_id, page in list(_tabs.items()):
        selected = " (selected)" if page is _page else ""
        lines.append(f"[{tab_id}]{selected} {page.url}")
    return "\n".join(lines) if _tabs else "BROWSER-TABS: (none)"


# Look up a tab by ID, returning None if the ID is invalid or unknown.
def _find_tab(tab_id):
    try:
        return _tabs.get(int(str(tab_id).strip()))
    except ValueError:
        return None


# Cancel downloads that were not explicitly requested and record a notice.
def _handle_download(download):
    """Cancel downloads unless browser-download deliberately initiated one."""
    global _download_notice
    if download.page is not _explicit_download:
        _download_notice = (
            "BROWSER-DOWNLOAD-BLOCKED: automatic or ordinary-click download "
            "was cancelled. Use browser-download with a target number from "
            "the selected tab's latest snapshot to save a file."
        )
        logger.warning(f"[PLAYWRIGHT] {_download_notice}")
        try:
            download.cancel()
        except Exception as exc:
            _download_notice += f" Cancellation failed: {type(exc).__name__}: {exc}"
            logger.error(f"[PLAYWRIGHT] {_download_notice}")


# Collapse whitespace in text into single spaces and trim its ends.
def _clean(value):
    return " ".join((value or "").split())


# Clear interaction targets and release any pinned element handles.
def _clear_targets():
    """Release any pinned typing field before replacing the target list."""
    global _targets
    previous = _targets
    _targets = []
    for target in previous:
        if hasattr(target, "dispose"):
            try:
                target.dispose()
            except Exception:
                pass  # A closed page may already have released its handles.


# Capture page text and numbered interaction targets, saving remaining text for later reads.
def _snapshot():
    global _targets, _download_notice, _reading
    _clear_targets()
    _reading = None
    if _page is None:
        raise RuntimeError("no selected tab; call browser-open first")

    body = _page.locator("body")
    text = body.inner_text(timeout=_timeout_ms) if body.count() else ""
    full_text = text
    text = full_text[:_max_text_chars]

    # Include common custom controls used by client-rendered documentation and
    # notebook sites, along with native text fields and editable content.
    candidates = _page.locator(
        "a:visible, button:visible, summary:visible, select:visible, "
        "[role='button']:visible, [role='link']:visible, "
        "[role='menuitem']:visible, [onclick]:visible, [tabindex]:visible, "
        "input[type='button']:visible, input[type='submit']:visible, "
        "input:not([type]):visible, input[type='text' i]:visible, "
        "input[type='search' i]:visible, input[type='email' i]:visible, "
        "input[type='password' i]:visible, input[type='tel' i]:visible, "
        "input[type='url' i]:visible, input[type='number' i]:visible, "
        "textarea:visible, [contenteditable='true' i]:visible, "
        "[contenteditable='']:visible, [contenteditable='plaintext-only' i]:visible"
    )
    # Read metadata in one browser call, rather than several calls per control.
    controls = candidates.evaluate_all(r"""elements => {
        const clean = value => (value || '').replace(/\s+/g, ' ').trim();
        return {count: elements.length, items: elements.slice(0, 200).map(el => {
            const field = el.matches('input, textarea');
            const textField = el.matches('textarea') || (el.matches('input') &&
                ['text', 'search', 'email', 'password', 'tel', 'url', 'number'].includes(el.type));
            const dropdown = el.matches('select');
            const disabled = el.matches(':disabled') ||
                !!el.closest('[aria-disabled="true"]');
            const label = clean(field || dropdown ? '' : el.innerText) ||
                clean(el.getAttribute('aria-label')) || clean(el.getAttribute('title')) ||
                clean(el.getAttribute('placeholder')) || clean(el.getAttribute('name')) ||
                clean(field ? '' : el.getAttribute('value')) || 'unlabelled control';
            return {label: label.slice(0, 240), dropdown, disabled,
                editable: (textField || el.isContentEditable) && !disabled &&
                    !el.readOnly && el.getAttribute('aria-readonly') !== 'true'};
        })};
    }""")
    lines = []
    for index, control in enumerate(controls["items"]):
        _targets.append(candidates.nth(index))
        lines.append(f"[{index + 1}] {control['label']}")
        if control["editable"]:
            lines.append("  EDITABLE: browser-type fills; for search, click the associated Search button or use Enter if none")
        if control["dropdown"]:
            state = "disabled" if control["disabled"] else "enabled"
            lines.append(f"  DROPDOWN ({state}): browser-options lists choices; browser-select selects")
    if controls["count"] > 200:
        lines.append(f"TARGETS_TRUNCATED: showing 200 of {controls['count']}")

    targets = "\n".join(lines) if lines else "(none)"
    notice = _download_notice
    _download_notice = ""
    result = (
        f"BROWSER-PAGE\nTAB: {next(key for key, page in _tabs.items() if page is _page)}\n"
        f"URL: {_page.url}\nTITLE: {_clean(_page.title())}\n"
        f"TEXT:\n{text}\nTEXT_CHARS: {len(text)}/{len(full_text)}"
        + ("\nMORE_TEXT: call browser-read-more" if len(text) < len(full_text) else "\nEND_OF_TEXT")
        + f"\nCLICK_TARGETS:\n{targets}"
        + (f"\n{notice}" if notice else "")
    )
    _reading = (_page, _page.url, full_text, len(text))
    return result


# Return the selected open tab or raise an error if none is available.
def _require_page():
    if _page is None or _page.is_closed():
        raise RuntimeError("no selected open tab; call browser-open first")
    return _page


# Perform a history or reload action and return the updated page snapshot.
def _history_action(method):
    page = _require_page()
    _select_page(page)
    # A missing history entry is a harmless no-op; same-document history can
    # also return no response, so do not infer failure from a None response.
    getattr(page, method)(wait_until="domcontentloaded", timeout=_timeout_ms)
    if _settle_ms:
        page.wait_for_timeout(_settle_ms)
    return _snapshot()


# Sanitize a suggested download filename and limit its length.
def _safe_download_name(suggested):
    name = os.path.basename(str(suggested or "download"))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not name:
        name = "download"
    return name[:180]


# Choose an unused file path within the configured download directory.
def _unused_download_path(filename):
    stem, extension = os.path.splitext(filename)
    candidate = os.path.join(_download_dir, filename)
    number = 1
    while os.path.exists(candidate):
        candidate = os.path.join(_download_dir, f"{stem}-{number}{extension}")
        number += 1
    candidate = os.path.realpath(candidate)
    if os.path.commonpath((_download_dir, candidate)) != _download_dir:
        raise ValueError("unsafe download filename")
    return candidate


# Log and return a download failure message with the download directory.
def _download_error(reason):
    message = f"BROWSER-DOWNLOAD-FAILED: {reason}; download directory: {_download_dir}"
    logger.error(f"[PLAYWRIGHT] {message}")
    return message


############################################################################
# Browser commands invoked by skill calls.
############################################################################

# List open tabs and identify the selected tab.
@_browser_command("TABS")
def list_tabs():
    return _tab_list()


# Switch to the specified tab and return its page snapshot.
@_browser_command("SWITCH")
def switch_tab(tab_id):
    page = _find_tab(tab_id)
    if page is None:
        raise ValueError("use a tab ID from browser-tabs")
    _select_page(page)
    return _snapshot()


# Close the specified tab and list the remaining tabs.
@_browser_command("CLOSE-TAB")
def close_tab(tab_id):
    page = _find_tab(tab_id)
    if page is None:
        raise ValueError("use a tab ID from browser-tabs")
    page.close()
    return _tab_list()


# Open a public URL in a new tab and return its page snapshot.
@_browser_command("OPEN")
def open_page(url):
    safe_url = _validate_public_url(url)
    context = _ensure_context()
    previous = _page
    page = context.new_page()
    _register_page(page)
    _select_page(page)
    logger.info("[PLAYWRIGHT] opening public page")
    try:
        page.goto(safe_url, wait_until="domcontentloaded")
    except Exception:
        page.close()
        if previous in _tabs.values():
            _select_page(previous)
        raise
    return _snapshot()


# Navigate the selected tab to a public URL and return its page snapshot.
@_browser_command("NAVIGATE")
def navigate_page(url):
    if _page is None:
        raise RuntimeError("no selected tab; call browser-open first")
    safe_url = _validate_public_url(url)
    _select_page(_page)
    _page.goto(safe_url, wait_until="domcontentloaded")
    return _snapshot()


# Return the selected page's text and numbered interaction targets.
@_browser_command("READ")
def read_page():
    return _snapshot()


# Save a full-page screenshot of the selected tab.
@_browser_command("SCREENSHOT")
def screenshot_page():
    page = _require_page()
    if not _download_dir:
        raise RuntimeError("download directory is not configured")
    os.makedirs(_download_dir, exist_ok=True)
    tab_id = next(key for key, tab in _tabs.items() if tab is page)
    # Reserve a unique filename so previous screenshots are never overwritten.
    descriptor, destination = tempfile.mkstemp(
        prefix=f"screenshot-tab-{tab_id}-", suffix=".png", dir=_download_dir
    )
    os.close(descriptor)
    try:
        page.screenshot(path=destination, full_page=True, timeout=_timeout_ms)
        size = os.path.getsize(destination)
        if size == 0:
            raise RuntimeError("browser produced an empty screenshot")
    except Exception:
        os.unlink(destination)
        raise
    logger.info(f"[PLAYWRIGHT] screenshot saved file={destination} bytes={size}")
    return f"BROWSER-SCREENSHOT-SAVED file={destination} bytes={size} tab={tab_id}"


# Go back in the selected tab's history and return its page snapshot.
@_browser_command("BACK")
def back_page():
    return _history_action("go_back")


# Go forward in the selected tab's history and return its page snapshot.
@_browser_command("FORWARD")
def forward_page():
    return _history_action("go_forward")


# Reload the selected tab and return its page snapshot.
@_browser_command("RELOAD")
def reload_page():
    return _history_action("reload")


# Return the next portion of text from the saved page snapshot.
@_browser_command("READ-MORE")
def read_more():
    global _reading
    page = _require_page()
    if _reading is None or _reading[0] is not page or _reading[1] != page.url:
        raise RuntimeError("no text snapshot for this page; call browser-read first")
    _, url, text, start = _reading
    end = min(start + _max_text_chars, len(text))
    _reading = (page, url, text, end)
    status = "MORE_TEXT: call browser-read-more" if end < len(text) else "END_OF_TEXT"
    return (
        f"BROWSER-READ-MORE\nURL: {url}\nTEXT_RANGE: {start}:{end}/{len(text)}\n"
        f"TEXT:\n{text[start:end]}\n{status}"
    )


# Search the selected page's text and return matching excerpts.
@_browser_command("FIND")
def find_text(query):
    page = _require_page()
    query = str(query).strip().strip('"')
    if not query:
        raise ValueError("search text must not be empty")
    body = page.locator("body")
    text = body.inner_text(timeout=_timeout_ms) if body.count() else ""
    lines = []
    used = 0
    truncated = False
    for match in re.finditer(re.escape(query), text, flags=re.IGNORECASE):
        excerpt = _clean(text[max(0, match.start() - 160):match.end() + 160])
        line = f"[{match.start()}] {excerpt}"
        remaining = _max_text_chars - used
        if len(lines) >= 50 or remaining <= 0:
            truncated = True
            break
        lines.append(line[:remaining])
        used += len(line) + 1
        if len(line) > remaining:
            truncated = True
            break
    result = "\n".join(lines) if lines else "NO_MATCHES"
    if truncated:
        result += "\nRESULTS_TRUNCATED: use a more specific search"
    return f"BROWSER-FIND\nURL: {page.url}\n{result}"


# List visible links and their destinations on the selected page.
@_browser_command("LINKS")
def list_links():
    page = _require_page()
    base = page.url
    bases = page.locator("base[href]")
    if bases.count():
        base = urljoin(base, bases.nth(0).get_attribute("href") or "")
    links = page.locator("a[href]:visible, area[href]:visible")
    count = links.count()
    lines = []
    for index in range(min(count, 200)):
        link = links.nth(index)
        label = _clean(
            link.inner_text(timeout=_timeout_ms)
            or link.get_attribute("aria-label")
            or link.get_attribute("title")
            or link.get_attribute("alt")
            or "unlabelled link"
        )
        destination = urljoin(base, link.get_attribute("href") or "")
        lines.append(f"- {label[:240]} -> {destination}")
    result = "\n".join(lines) if lines else "(none)"
    if count > 200:
        result += f"\nLINKS_TRUNCATED: showing 200 of {count}"
    return (
        f"BROWSER-LINKS\nURL: {page.url}\n{result}\n"
        "Destinations are informational, not validated. Use browser-read for click target numbers."
    )


# Click a numbered target and return the updated page snapshot.
@_browser_command("CLICK")
def click_target(target):
    if _page is None:
        raise RuntimeError("no selected tab; call browser-open first")
    try:
        index = int(str(target).strip()) - 1
    except ValueError:
        raise ValueError("target must be a number from the latest snapshot") from None
    if index < 0 or index >= len(_targets):
        raise ValueError("target is not present in the latest snapshot; call browser-read first")

    _targets[index].click(timeout=_timeout_ms)
    if _page is None:
        raise RuntimeError("selected tab closed during click; use browser-tabs or browser-open")
    _page.wait_for_load_state("domcontentloaded", timeout=_timeout_ms)
    if _settle_ms and _page is not None:
        _page.wait_for_timeout(_settle_ms)
    return _snapshot()


# Fill an editable target with text and verify its contents.
@_browser_command("TYPE")
def type_text(target, text=None):
    global _targets, _reading, _download_notice
    # The bot parser combines the field number and text into one string.
    # Keep accepting separate arguments for direct calls as well.
    if text is None:
        match = re.fullmatch(r'\s*(?:"([0-9]+)"|([0-9]+))\s+([\s\S]*)', str(target))
        if match is None:
            raise ValueError('expected a field number followed by text, for example: 11 "search terms"')
        target = match.group(1) or match.group(2)
        text = match.group(3)
        if text.startswith('"'):
            try:
                text = json.loads(text)
            except ValueError:
                raise ValueError("text has invalid quoting; use a double-quoted string") from None
    page = _require_page()
    try:
        index = int(str(target).strip()) - 1
    except ValueError:
        raise ValueError("target must be a field number from the latest snapshot") from None
    if index < 0 or index >= len(_targets):
        raise ValueError("target is not present in the latest snapshot; call browser-read first")
    field = _targets[index]
    value = str(text)
    _reading = None
    stage = "resolving the field"
    attempts = 0
    # Pin the element so validation, filling and
    # verification cannot silently switch controls after a DOM update.
    try:
        if hasattr(field, "element_handle"):
            field = field.element_handle(timeout=_timeout_ms)
            _clear_targets()
            if field is None:
                raise ValueError("field is no longer present")
            _targets = [field]
        stage = "checking the field is visible and editable"
        if not field.is_visible() or not field.is_editable():
            raise ValueError("field is hidden, disabled, read-only, or not editable")
        for attempts in range(1, 4):  # Initial attempt plus at most two retries.
            try:
                stage = "filling the field"
                field.fill(value, timeout=_timeout_ms)
                stage = "checking the selected tab after filling"
                if page.is_closed() or _page is not page:
                    raise RuntimeError("selected tab changed or closed")
                stage = "verifying that the field contains the requested text"
                matches = field.evaluate(r"""(el, expected) => {
                    if (!el.isConnected) return false;
                    if (el.matches('input, textarea')) {
                        if (el.matches('textarea')) expected = expected.replace(/\r\n?/g, '\n');
                        return el.value === expected;
                    }
                    if (el.isContentEditable) {
                        const normalize = value => value.replace(/\r\n?/g, '\n');
                        return normalize(el.innerText) === normalize(expected);
                    }
                    return false;
                }""", value)
                if not matches:
                    raise ValueError("field contents differ or the field was replaced")
                break
            except Exception:
                if attempts == 3 or page.is_closed() or _page is not page:
                    raise
                if not field.evaluate("el => el.isConnected"):
                    raise
    except Exception as exc:
        # Playwright call logs can include supplied text. Report only the
        # failed stage and exception class, never the raw exception or values.
        raise RuntimeError(
            f"{stage} failed ({type(exc).__name__}); {attempts} fill attempt(s), "
            "at most 2 retries allowed"
        ) from None
    notice = _download_notice
    _download_notice = ""
    return (
        "BROWSER-TYPE-OK: field contents verified\n[1] Field just filled\n"
        "No Enter was pressed. Previous target numbers are invalid. "
        "For search, call browser-read. If results already updated, do not submit again. "
        "Otherwise click the Search button associated with this field; if none is available, "
        "use browser-press-enter on the search field. Use target numbers from the new snapshot "
        "and inspect results afterward. Target 1 refers to this field only until that snapshot."
        + (f"\n{notice}" if notice else "")
    )


# Press Enter in an editable target and return the updated page snapshot.
@_browser_command("PRESS-ENTER")
def press_enter(target):
    page = _require_page()
    try:
        index = int(str(target).strip()) - 1
    except ValueError:
        raise ValueError("target must be a field number from the latest snapshot") from None
    if index < 0 or index >= len(_targets):
        raise ValueError("target is not present in the latest snapshot; call browser-read first")
    field = _targets[index]
    if not field.is_editable():
        raise ValueError("target is not editable or is disabled/read-only")
    field.press("Enter", timeout=_timeout_ms)
    if page.is_closed() or _page is not page:
        raise RuntimeError("selected tab closed after pressing Enter; use browser-tabs")
    page.wait_for_load_state("domcontentloaded", timeout=_timeout_ms)
    if _settle_ms:
        page.wait_for_timeout(_settle_ms)
    return _snapshot()


# List the choices available in a native dropdown target.
@_browser_command("OPTIONS")
def list_options(target):
    _require_page()
    try:
        index = int(str(target).strip()) - 1
    except ValueError:
        raise ValueError("target must be a dropdown number from the latest snapshot") from None
    if index < 0 or index >= len(_targets):
        raise ValueError("target is not present in the latest snapshot; call browser-read first")
    data = _targets[index].evaluate("""el => {
        if (el.tagName !== 'SELECT') return null;
        return {count: el.options.length,
            options: Array.from(el.options).slice(0, 200).map(option => ({
                label: option.label, value: option.value, selected: option.selected,
                disabled: el.matches(':disabled') || option.matches(':disabled')
            }))};
    }""")
    if data is None:
        raise ValueError("target is not a native dropdown; use browser-click for custom menus")
    lines = [f"BROWSER-OPTIONS target={index + 1}"]
    for option in data["options"]:
        flags = [name for name in ("disabled", "selected") if option[name]]
        lines.append(
            f"label={option['label']!r} value={option['value']!r}"
            + (f" ({', '.join(flags)})" if flags else "")
        )
    if data["count"] > 200:
        lines.append("OPTIONS_TRUNCATED: first 200 options shown")
    return "\n".join(lines)


# Select a native dropdown option by its label or value.
@_browser_command("SELECT")
def select_dropdown(target, choice):
    page = _require_page()
    try:
        index = int(str(target).strip()) - 1
    except ValueError:
        raise ValueError("target must be a dropdown number from the latest snapshot") from None
    if index < 0 or index >= len(_targets):
        raise ValueError("target is not present in the latest snapshot; call browser-read first")
    dropdown = _targets[index]
    if not dropdown.evaluate("el => el.tagName === 'SELECT'"):
        raise ValueError("target is not a native dropdown; use browser-click for custom menus")
    if dropdown.is_disabled():
        raise ValueError("dropdown is disabled")
    choice = str(choice)
    if len(choice) >= 2 and choice[0] == choice[-1] == '"':
        choice = choice[1:-1]
    options = dropdown.locator("option")
    label_matches = []
    value_matches = []
    for option_index in range(options.count()):
        option = options.nth(option_index)
        label = option.get_attribute("label")
        text = _clean(option.text_content(timeout=_timeout_ms))
        if label is None:
            label = text
        value = option.get_attribute("value")
        if value is None:
            value = text
        if label == choice:
            label_matches.append(option_index)
        if value == choice:
            value_matches.append(option_index)
    matches = label_matches or value_matches
    if not matches:
        raise ValueError("option not found; use an exact label or value from browser-options")
    if len(matches) != 1:
        raise ValueError("option is ambiguous; use a unique option label or value")
    if options.nth(matches[0]).is_disabled():
        raise ValueError("option is disabled")
    dropdown.select_option(index=matches[0], timeout=_timeout_ms)
    if page.is_closed() or _page is not page:
        raise RuntimeError("selected tab closed during selection; use browser-tabs")
    if _settle_ms:
        page.wait_for_timeout(_settle_ms)
    return _snapshot()


# Scroll the selected page vertically and return its page snapshot.
@_browser_command("SCROLL")
def scroll_page(pixels):
    if _page is None:
        raise RuntimeError("no selected tab; call browser-open first")
    try:
        amount = int(str(pixels).strip())
    except ValueError:
        raise ValueError("pixel amount must be an integer") from None
    amount = min(5000, max(-5000, amount))
    _page.mouse.wheel(0, amount)
    if _settle_ms:
        _page.wait_for_timeout(_settle_ms)
    return _snapshot()


# Wait for the specified duration and return the page snapshot.
@_browser_command("WAIT")
def wait_and_read(milliseconds):
    if _page is None:
        raise RuntimeError("no selected tab; call browser-open first")
    try:
        duration = int(str(milliseconds).strip())
    except ValueError:
        raise ValueError("milliseconds must be an integer") from None
    duration = min(10_000, max(0, duration))
    _page.wait_for_timeout(duration)
    return _snapshot()


# Click a target to download a file, enforce the size limit, and verify the saved file.
@_browser_command("DOWNLOAD")
def download_target(target):
    global _explicit_download
    if _page is None:
        return _download_error("no selected tab; call browser-open first")
    try:
        index = int(str(target).strip()) - 1
    except ValueError:
        return _download_error("target must be a number from the latest snapshot")
    if index < 0 or index >= len(_targets):
        return _download_error("target is not present in the latest snapshot; call browser-read first")

    stage = "waiting for a download event after clicking the target"
    try:
        logger.info(
            f"[PLAYWRIGHT] download starting target={target} directory={_download_dir}"
        )
        _explicit_download = _page
        with _page.expect_download(timeout=_timeout_ms) as pending:
            _targets[index].click(timeout=_timeout_ms)
        download = pending.value
        stage = "waiting for the download to complete"
        failure = download.failure()
        if failure:
            return _download_error(f"browser reported: {failure}")
        stage = "checking the downloaded temporary file"
        temporary_path = download.path()
        if temporary_path is None:
            return _download_error("browser returned no temporary file")
        size = os.path.getsize(temporary_path)
        if size > _max_download_bytes:
            download.cancel()
            return _download_error(
                f"file is {size} bytes; limit is "
                f"{_max_download_bytes} bytes"
            )

        destination = _unused_download_path(
            _safe_download_name(download.suggested_filename)
        )
        stage = f"saving file to {destination}"
        download.save_as(destination)
        stage = f"verifying saved file {destination}"
        with open(destination, "rb") as downloaded:
            digest = hashlib.sha256(downloaded.read()).hexdigest()
        verified_size = os.path.getsize(destination)
        logger.info(
            f"[PLAYWRIGHT] download ok file={destination} bytes={verified_size} "
            f"sha256={digest[:16]}"
        )
        return (
            f"BROWSER-DOWNLOAD-VERIFIED file={destination} "
            f"bytes={verified_size} sha256={digest}"
        )
    except Exception as exc:
        return _download_error(f"{stage}: {type(exc).__name__}: {exc}")
    finally:
        _explicit_download = None


# Close the browser session and clear its tracked state.
@_browser_command("CLOSE")
def close_browser():
    global _playwright, _browser, _context, _page, _targets, _explicit_download
    global _next_tab_id, _download_notice, _reading
    failures = []
    try:
        for name, resource, method in (
            ("context", _context, "close"),
            ("browser", _browser, "close"),
            ("playwright", _playwright, "stop"),
        ):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception as exc:
                    failures.append(f"{name}: {type(exc).__name__}: {exc}")
    finally:
        _playwright = None
        _browser = None
        _context = None
        _page = None
        _clear_targets()
        _explicit_download = None
        _download_notice = ""
        _tabs.clear()
        _next_tab_id = 1
        _reading = None
    if failures:
        raise RuntimeError("; ".join(failures))
    return "BROWSER-CLOSED: session cookies and storage discarded"