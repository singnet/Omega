import re

from helpers import Checker, make_prompt
from request_log import request_after, wait_for


def test_invalid_name_does_not_drop_sibling_call(llm, comm):
    with Checker("A malformed tool name gets its own result") as c:
        tag = f"field-test-{c.run_id}"
        prompt = make_prompt(c.run_id, tag)
        ids = ['unknown ("tool")', 'valid\\id']
        assert llm.set_answer(prompt, [
            ('unknown "tool" (v2)', {}, ids[0]),
            ("send", {"content": 'Example ("hello")'}, ids[1]),
        ])
        assert comm.send_message(prompt)
        request = wait_for(lambda: request_after(tag))
        assert request is not None
        results = re.findall(r"LLMToolCallResponseMessage\[role='tool',content=(.*?),callid=(.*?)\]",
                             request, re.DOTALL)
        assert len(results) == 2
        by_id = {call_id: content for content, call_id in results}
        assert "ALERT_FAILED" in by_id[repr(ids[0])]
        assert "SUCCESS, RETURN" in by_id[repr(ids[1])]
