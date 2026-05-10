"""Tests for src.brain.subject_fingerprint.

Behavioural contract (audit Phase C.3):

The fingerprint is a normalised noun-phrase signature suitable for
matching "same subject framed differently". It is a heuristic, not a
classifier. False positives are acceptable (the agent skips a slot,
preferable to a duplicate). False negatives are the bigger concern.

Two posts about "phone with no apps" framed differently must produce
overlapping fingerprints (Jaccard >= 0.6). Two unrelated posts must not.
"""
from __future__ import annotations

from src.brain import subject_fingerprint, fingerprint_similarity


# ----- subject_fingerprint -----------------------------------------

def test_literal_duplicates_same_fingerprint():
    a = "Five horror films changed cinema by weaponising fear"
    b = "Five horror films changed cinema by weaponising fear"
    assert subject_fingerprint(a) == subject_fingerprint(b)


def test_phone_no_apps_overlap_high():
    # Same subject framed differently - the 2026-05-06 incident shape.
    # Both are "phone with no apps", reworded. The shared content tokens
    # (phone, apps, store, app) must dominate both fingerprints.
    a = "Phone with no apps and no app store"
    b = "Phone with apps and app store removed"
    fa = subject_fingerprint(a)
    fb = subject_fingerprint(b)
    sim = fingerprint_similarity(fa, fb)
    assert sim >= 0.6, f"expected sim>=0.6, got {sim} fa={fa!r} fb={fb!r}"


def test_distinct_subjects_low_overlap():
    a = "Vasili Arkhipov saved the world by refusing to launch a torpedo"
    b = "Pepsi briefly owned a navy of Soviet warships"
    fa = subject_fingerprint(a)
    fb = subject_fingerprint(b)
    sim = fingerprint_similarity(fa, fb)
    assert sim < 0.3, f"expected sim<0.3, got {sim} fa={fa!r} fb={fb!r}"


def test_empty_input_returns_empty():
    assert subject_fingerprint("") == ""


def test_stopwords_only_returns_empty():
    assert subject_fingerprint("the and of") == ""


def test_all_digit_input_returns_empty():
    assert subject_fingerprint("1972 1989") == ""


def test_short_tokens_dropped():
    # "a", "an", "of" are stopwords; "in" is too short and a stopword.
    # The 3-char floor + stopword filter together must reject these.
    assert subject_fingerprint("an a of in") == ""


def test_punctuation_stripped():
    a = "Phone, with no apps. And no app-store!"
    b = "Phone with no apps and no app store"
    # Punctuation should not change the fingerprint.
    assert subject_fingerprint(a) == subject_fingerprint(b)


def test_case_insensitive():
    a = "PHONE WITH NO APPS"
    b = "phone with no apps"
    assert subject_fingerprint(a) == subject_fingerprint(b)


def test_fingerprint_is_alphabetical_join():
    # Tokens should be sorted alphabetically and joined with "-" so two
    # identical token sets produce the same string regardless of input order.
    a = subject_fingerprint("zebra apple mango banana")
    b = subject_fingerprint("banana mango apple zebra")
    assert a == b
    assert "-" in a
    # Should be alphabetical.
    parts = a.split("-")
    assert parts == sorted(parts)


def test_fingerprint_caps_token_count():
    # Long input with many candidate tokens should still produce a short
    # fingerprint (top 3-5 longest). 10 distinct content tokens must not
    # produce 10 tokens in the fingerprint.
    text = "submarine torpedo nuclear missile arctic spetsnaz cosmonaut " \
           "kamchatka politburo cosmodrome"
    fp = subject_fingerprint(text)
    parts = fp.split("-")
    assert 3 <= len(parts) <= 5, f"expected 3-5 tokens, got {len(parts)}: {fp!r}"


def test_fingerprint_returns_non_empty_for_short_real_subject():
    # Smoke check from the task spec.
    fp = subject_fingerprint("Five horror films changed cinema by weaponising fear")
    assert fp != ""
    parts = fp.split("-")
    assert all(len(p) >= 3 for p in parts), f"all tokens >=3 chars, got {parts!r}"


# ----- fingerprint_similarity --------------------------------------

def test_similarity_identical_returns_one():
    fp = subject_fingerprint("phone with no apps and no app store")
    assert fingerprint_similarity(fp, fp) == 1.0


def test_similarity_disjoint_returns_zero():
    a = subject_fingerprint("zebra mango banana")
    b = subject_fingerprint("submarine torpedo helmet")
    assert fingerprint_similarity(a, b) == 0.0


def test_similarity_empty_returns_zero():
    assert fingerprint_similarity("", "") == 0.0
    assert fingerprint_similarity("", "phone-apps-store") == 0.0
    assert fingerprint_similarity("phone-apps-store", "") == 0.0


def test_similarity_in_range():
    # Sanity: any pair returns a value in [0, 1].
    samples = [
        ("phone with no apps", "the app-free phone"),
        ("Vasili Arkhipov saved the world", "Pepsi owned a navy"),
        ("Concorde supersonic flight", "Concorde retired in 2003"),
        ("", "anything"),
        ("anything", ""),
    ]
    for a, b in samples:
        fa = subject_fingerprint(a)
        fb = subject_fingerprint(b)
        s = fingerprint_similarity(fa, fb)
        assert 0.0 <= s <= 1.0, f"sim out of range for ({a!r}, {b!r}): {s}"


def test_similarity_partial_overlap():
    # Three tokens shared out of five total = Jaccard 3/5 = 0.6.
    a = "apple-banana-cherry"
    b = "banana-cherry-date"
    # Union: {apple, banana, cherry, date} = 4. Intersection: {banana, cherry} = 2.
    # Jaccard = 2/4 = 0.5.
    s = fingerprint_similarity(a, b)
    assert s == 0.5
