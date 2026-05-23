from __future__ import annotations

from src.content.reel_quality import validate_reel_copy, validate_reel_script, validate_reel_title


VALID_SCRIPT = (
    "In 1992, Pepsi accidentally printed 800,000 winning bottle caps in the Philippines. "
    "The prize was one million pesos. "
    "Pepsi had meant to print two winning caps, not a small city of them. "
    "The company refused to pay most winners. "
    "Crowds gathered outside offices. "
    "Delivery trucks were attacked. "
    "A marketing promotion became a national court case, and the number 349 stopped being a number on a cap. "
    "That was the official lesson."
)


def test_valid_reel_copy_passes():
    ok, reason = validate_reel_copy(VALID_SCRIPT, "The Bottle Cap That Started Riots")
    assert ok, reason


def test_short_script_fails():
    ok, reason = validate_reel_script("In 1903, something failed. It was bad.")
    assert not ok
    assert "too short" in reason


def test_first_sentence_must_carry_concrete_weird_bit():
    script = (
        "This is one of history's more unusual stories. "
        "In 1992, Pepsi accidentally printed 800,000 winning bottle caps in the Philippines. "
        "The company refused to pay most winners. "
        "Crowds gathered outside offices and the promotion became a national court case. "
        "The number on the cap was 349, which stopped being a harmless number very quickly. "
        "The whole campaign was supposed to sell soft drinks, not create a legal disaster. "
        "It managed the second thing better."
    )
    ok, reason = validate_reel_script(script)
    assert not ok
    assert "first sentence" in reason


def test_awkward_title_shape_fails():
    ok, reason = validate_reel_title("The War That Ended For 1 Man In 1974", VALID_SCRIPT)
    assert not ok
    assert "awkward" in reason


def test_title_must_connect_to_opening():
    ok, reason = validate_reel_title("The Moon With No Door", VALID_SCRIPT)
    assert not ok
    assert "connect" in reason
