"""
Mock variant of test_convert_format.

The harness pre-creates document.md. The mocked LLM response copies
the source verbatim into document.txt via shell — the simplest valid
.md → .txt conversion that preserves all content.

Run:
    pytest test_convert_format_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, make_prompt, wait_for_file,
)
from tg_helpers import tg_send_prompt

TARGET_DIR = "/tmp/test_convert"
SOURCE_FILE = "/tmp/test_convert/document.md"
DEST_FILE = "/tmp/test_convert/document.txt"
FILE_CONTENT = "# My Title\n\nSome paragraph text.\n\n- item one\n- item two\n"
KEY_PHRASES = ["My Title", "Some paragraph text", "item one", "item two"]


def test_convert_md_to_txt_telegram_mock(llm, tg):
    with Checker("convert .md to .txt (telegram mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: convert format telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create .md file")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("sh", "-c",
                   f"cat > {SOURCE_FILE} << 'ENDOFFILE'\n{FILE_CONTENT}ENDOFFILE")
        dexec_root("chmod", "777", TARGET_DIR)
        dexec_root("chmod", "666", SOURCE_FILE)
        if dexec("cat", SOURCE_FILE).returncode != 0:
            c.fail("pre-create", "could not create .md file")
        c.ok("pre-create")

        start_ts = int(time.time()) - 1

        c.step("send prompt via Telegram with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Convert the file {SOURCE_FILE} from .md format to .txt format. "
            f"The result should be saved as {DEST_FILE}. "
            "Preserve ALL of the original text content.",
        )
        llm.set_answer(
            prompt,
            [("shell", { "cmd": f"cp {SOURCE_FILE} {DEST_FILE}" })],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step(f"wait for {DEST_FILE}")
        mtime = wait_for_file(DEST_FILE, start_ts, timeout=30)
        if mtime is None:
            c.fail("file created", f"{DEST_FILE} not created within timeout")
        c.ok("file created", f"after {mtime - start_ts}s")

        c.step("check content preserved")
        converted = dexec("cat", DEST_FILE).stdout
        for key_phrase in KEY_PHRASES:
            if key_phrase not in converted:
                c.fail("content",
                       f"missing {repr(key_phrase)} in converted file: {repr(converted)}")
        c.ok("content", f"{len(converted)} bytes")

        c.step("check mtime fresh")
        if mtime < start_ts:
            c.fail("file mtime", f"{mtime} < {start_ts}")
        c.ok("file mtime", f"{mtime} >= {start_ts}")

        c.done()
