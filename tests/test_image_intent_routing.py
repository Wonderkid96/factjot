import pytest
from src.research.image_sourcer import _classify_slot_intent


def test_classifies_named_entity_query_as_entity():
    intent = _classify_slot_intent(
        slide_text="phineas gage survived a rod",
        query="phineas gage portrait",
        slot_aliases=["Phineas Gage"],
    )
    assert intent == "entity"


def test_classifies_descriptive_b_roll_as_scene():
    intent = _classify_slot_intent(
        slide_text="crews lifted the wreckage",
        query="bridge collapse rescue crew",
        slot_aliases=[],
    )
    assert intent == "scene"


def test_classifies_abstract_concept_as_abstract():
    intent = _classify_slot_intent(
        slide_text="the budget was approved",
        query="federal budget approval",
        slot_aliases=[],
    )
    assert intent == "abstract"


from src.research.image_fetcher import _negative_term_hits


def test_negative_term_hits_token_boundary():
    """A negative 'station' must not fire on 'destination' (substring trap)."""
    hits = _negative_term_hits(
        meta="travel destination paris",
        negative_terms=["station"],
    )
    assert hits == []

    hits = _negative_term_hits(
        meta="metro station entrance",
        negative_terms=["station"],
    )
    assert hits == ["station"]


def test_negative_term_hits_compound_phrase():
    hits = _negative_term_hits(
        meta="place de la concorde paris square",
        negative_terms=["place de la concorde", "obelisk"],
    )
    assert "place de la concorde" in hits
