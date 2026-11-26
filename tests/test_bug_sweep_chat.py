"""Static regression checks for app/chat.js (CHAT-1, CHAT-3)."""

import re
import unittest
from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "app" / "chat.js").read_text(encoding="utf-8")


def _func(name: str) -> str:
    m = re.search(rf"async function {name}\(.*?\n  }}\n", JS, re.S)
    assert m, name
    return m.group(0)


class ChatRegressionTest(unittest.TestCase):
    def test_chat1_ephemeral_catch_keeps_partial(self) -> None:
        m = re.search(r"if \(S\.ephemeral\) \{.*?\} catch \(err\) \{(.*?)\n      \}", JS, re.S)
        self.assertTrue(m)
        self.assertIn("draft.content = acc", m.group(1))
        self.assertIn("S.ephemeralLog.push", m.group(1))

    def test_chat3_submit_restores_draft_on_failure(self) -> None:
        body = _func("onSubmit")
        catch = body[body.rindex("} catch (err) {"):]
        self.assertIn("restoreDraft()", catch)
        self.assertIn("savedAttachments", body)


if __name__ == "__main__":
    unittest.main()
