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
