"""Tests for compound noun detection in extract_entities.

Verifies that adjacent (proper|noun)+(proper|noun) token pairs are captured
as compound_nouns, which video_finder uses to search phrases like
"mantis shrimp" before individual tokens like "mantis".
"""
from __future__ import annotations

import unittest

from src.research.narrative_beats import extract_entities


class TestCompoundNounDetection(unittest.TestCase):

    def test_animal_compound_noun(self):
        ents = extract_entities(
            "The Mantis shrimp can throw a punch faster than a bullet leaving a gun."
        )
        self.assertIn("mantis shrimp", ents.compound_nouns)

    def test_physics_compound_noun(self):
        ents = extract_entities(
            "The strike is so fast it creates a shock wave that boils the water around it."
        )
        self.assertIn("shock wave", ents.compound_nouns)

    def test_no_compound_across_verb(self):
        # "bullet leaving" — leaving is a verb (ends in -ing) so no bigram
        ents = extract_entities(
            "A bullet leaving the barrel travels faster than sound."
        )
        compounds = ents.compound_nouns
        self.assertNotIn("bullet leaving", compounds)

    def test_no_compound_from_short_words(self):
        # Short words (len ≤ 3) never enter the compound pool
        ents = extract_entities("The cat sat on the mat.")
        self.assertEqual([], ents.compound_nouns)

    def test_proper_noun_pair_becomes_compound(self):
        # Two adjacent proper nouns form a compound (also joined in proper_nouns[:2])
        ents = extract_entities("In 1962 Vasili Arkhipov refused to launch.")
        self.assertIn("vasili arkhipov", ents.compound_nouns)

    def test_compound_nouns_capped_at_four(self):
        # Long claims should not produce unbounded compound lists
        claim = (
            "The Mantis shrimp uses shock waves, rifle rounds, cave pressure, "
            "solar flares, brain scans, and deep time to survive ocean depths."
        )
        ents = extract_entities(claim)
        self.assertLessEqual(len(ents.compound_nouns), 4)

    def test_empty_claim(self):
        ents = extract_entities("")
        self.assertEqual([], ents.compound_nouns)

    def test_single_word_claim(self):
        ents = extract_entities("Fire.")
        self.assertEqual([], ents.compound_nouns)

    def test_stop_words_not_in_compounds(self):
        # "the ocean" — "the" is a stop word, should not form a compound
        ents = extract_entities("The ocean is very deep and full of life.")
        for cn in ents.compound_nouns:
            self.assertNotIn("the ", cn)
            self.assertNotIn(" the", cn)


if __name__ == "__main__":
    unittest.main()
