import unittest
from modules.script_agent import _hook_is_specific


class BackspaceHookTests(unittest.TestCase):
    def test_observable_deleting_action_is_specific(self):
        for hook in (
            'You typed three honest sentences, held backspace, and sent "all good."',
            'Three honest sentences, typed. Then you hold backspace and send "all good."',
        ):
            self.assertTrue(_hook_is_specific(hook))

    def test_abstract_hook_is_still_rejected(self):
        self.assertFalse(_hook_is_specific("Healing starts when you listen to yourself."))
