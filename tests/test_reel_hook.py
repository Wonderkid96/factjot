import unittest


class TestReelHookOptimiser(unittest.TestCase):
    def setUp(self) -> None:
        self.claim = (
            "In 1966 a US Air Force bomber collided with a refuelling aircraft "
            "over Spain and accidentally dropped four nuclear bombs. None of them detonated."
        )
        self.topic = "history"

    def test_optimise_hook_is_deterministic(self) -> None:
        try:
            from src.content.reel_hook import optimise_hook
        except ImportError:
            self.fail("Missing module src/content/reel_hook.py (implement hook optimiser)")

        winner1, top1 = optimise_hook(self.claim, self.topic, seed=123)
        winner2, top2 = optimise_hook(self.claim, self.topic, seed=123)

        self.assertEqual(winner1, winner2)
        self.assertEqual(top1, top2)

    def test_winner_has_reasonable_length_and_keywords(self) -> None:
        try:
            from src.content.reel_hook import optimise_hook
        except ImportError:
            self.fail("Missing module src/content/reel_hook.py (implement hook optimiser)")

        winner, top = optimise_hook(self.claim, self.topic, seed=123)

        # Title/hook cards should be short to read cleanly.
        self.assertLessEqual(len(winner.split()), 7)

        # We expect one or more of: the year, the place, or the key number.
        wl = winner.lower()
        self.assertTrue(any(tok in wl for tok in ("1966", "spain", "four")))

        # Top-3 list is required for later analysis/logging.
        self.assertEqual(len(top), 3)
        for text, _score in top:
            self.assertLessEqual(len(text.split()), 7)


if __name__ == "__main__":
    unittest.main()

