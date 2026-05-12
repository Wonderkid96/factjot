from __future__ import annotations

from src.research import story_scout


def test_infer_topic_space():
    t = story_scout._infer_topic("NASA found an asteroid orbit near Jupiter")
    assert t == "space"


def test_score_title_rejects_bad_terms():
    hook, novelty, visual, confidence, shock, weird = story_scout._score_title(
        "Celebrity drama rumour leak update", []
    )
    assert hook == 0.0
    assert novelty == 0.0
    assert visual == 0.0
    assert confidence == 0.0
    assert shock == 0.0
    assert weird == ""


def test_novelty_drops_on_overlap():
    post_bank = [
        "In 1919 Boston had a giant molasses flood through city streets"
    ]
    low = story_scout._novelty(
        "Boston molasses flood killed 21 people", post_bank
    )
    high = story_scout._novelty(
        "Hidden moon ocean under Europa ice shell", post_bank
    )
    assert low < high
