import unittest

from modules.script_agent import _hook_is_specific


class ConcreteSceneHookTests(unittest.TestCase):
    def test_rejected_production_openings_are_concrete(self):
        hooks = (
            "It's 1 a.m., and you're on their profile again. You say you miss them, but look at what you're actually studying: the photos, the captions, whether anyone looks sad.",
            "It's 1 a.m. and you're zooming in on their smile, trying to decide if it's real.",
            "It's 1 a.m. You open their profile and zoom in on their smile, trying to tell if it's real.",
        )
        for hook in hooks:
            with self.subTest(hook=hook):
                self.assertTrue(_hook_is_specific(hook))

    def test_concrete_actions_do_not_need_a_contradiction_keyword(self):
        for hook in ("You hover over their photo at midnight.",
                     "You're scrolling through their posts again.",
                     "Your cursor hovers over the draft."):
            with self.subTest(hook=hook):
                self.assertTrue(_hook_is_specific(hook))

    def test_generic_or_object_only_openings_still_fail(self):
        for hook in ("You open yourself to love.", "You study your feelings.",
                     "You deserve a smile.", "Photos tell stories.",
                     "Healing starts when you look at their profile."):
            with self.subTest(hook=hook):
                self.assertFalse(_hook_is_specific(hook))
