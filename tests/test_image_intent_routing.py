from src.research.image_sourcer import (
    _classify_slot_intent,
    _literalise_slot_text_query,
    _meta_matches_query,
    _r3_provider_order_for_query,
)


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


def test_classifies_capitalised_named_subject_from_slide_text():
    intent = _classify_slot_intent(
        slide_text="Deepwater Horizon exploded in 2010",
        query="offshore drilling accident",
        slot_aliases=[],
    )
    assert intent == "entity"


def test_r3_provider_order_prefers_archives_for_named_queries():
    order = _r3_provider_order_for_query("OpenAI logo")
    assert order[:3] == ("commons", "wiki", "wiki_article")


def test_r3_provider_order_prefers_stock_for_descriptive_queries():
    order = _r3_provider_order_for_query("smartphone chat app")
    assert order[:2] == ("pexels", "pixabay")


def test_literalise_slot_text_query_prefers_content_words():
    q = _literalise_slot_text_query(
        "OpenAI rolled back GPT-4o after users reported sycophantic answers.",
    )
    assert "openai" in q
    assert "rolled" in q or "rollback" in q


def test_meta_matches_query_requires_meaningful_overlap():
    assert _meta_matches_query("OpenAI office San Francisco", "OpenAI logo") is True
    assert _meta_matches_query("red sports car closeup", "OpenAI logo") is False


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


from src.research.image_sourcer import ImageSourcer, MAX_REUSES


def test_max_reuses_allows_second_use_per_carousel():
    """SPEC section 10: 'same URL is capped at 2 uses per carousel'.

    Implementation contract: a URL with _use_count == 1 must remain
    eligible (so _pick_reuse can return it). With MAX_REUSES == 1 the
    URL would already be ineligible at count 1; with MAX_REUSES == 2
    it stays eligible for the second use.
    """
    assert MAX_REUSES >= 2, (
        f"MAX_REUSES={MAX_REUSES} blocks second use; "
        "SPEC_IMAGE_PIPELINE.md section 10 requires up to 2 uses per carousel."
    )

    sourcer = ImageSourcer(topic="editorial", use_fresh_ledger=True)
    sourcer._use_count["data:image/jpeg;base64,fake"] = 1
    eligible_at_count_1 = (
        sourcer._use_count.get("data:image/jpeg;base64,fake", 0) < MAX_REUSES
    )
    assert eligible_at_count_1 is True
    sourcer._use_count["data:image/jpeg;base64,fake"] = 2
    eligible_at_count_2 = (
        sourcer._use_count.get("data:image/jpeg;base64,fake", 0) < MAX_REUSES
    )
    assert eligible_at_count_2 is False
