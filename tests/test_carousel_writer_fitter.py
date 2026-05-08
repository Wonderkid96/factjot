import pytest
from src.content.carousel_writer import (
    EditorialSlide,
    SlideFit,
    write_editorial_slides,
    fit_slide_lines,
    FactPreservationError,
    LineFitError,
)


def test_editorial_slide_dataclass_round_trip():
    slide = EditorialSlide(
        slide_index=2,
        prose="Phineas Gage survived an iron rod through his skull in 1848.",
        beat_id="2",
    )
    assert slide.slide_index == 2
    assert "1848" in slide.prose
    assert slide.beat_id == "2"


def test_slide_fit_dataclass():
    fit = SlideFit(
        slide_index=2,
        lines=["phineas gage", "took an iron rod", "to the head, 1848"],
    )
    assert len(fit.lines) == 3


import json
from unittest.mock import MagicMock


def _mock_anthropic_response(payload: dict):
    """Build a fake Anthropic SDK response carrying the given JSON payload."""
    res = MagicMock()
    res.content = [MagicMock()]
    res.content[0].text = "```json\n" + json.dumps(payload) + "\n```"
    res.usage.input_tokens = 100
    res.usage.output_tokens = 200
    return res


def test_fitter_rejects_dropped_numbers(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": ["phineas gage", "took a rod", "to the head"]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    with pytest.raises(FactPreservationError) as exc:
        fit_slide_lines(
            editorial_slides=[EditorialSlide(
                slide_index=2,
                prose="Phineas Gage survived an iron rod through his skull in 1848.",
            )],
            hard_cap=24,
            api_key="dummy",
        )
    assert "1848" in str(exc.value)


def test_fitter_rejects_dropped_proper_noun(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": ["a man survived", "an iron rod", "through his head"]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    with pytest.raises(FactPreservationError) as exc:
        fit_slide_lines(
            editorial_slides=[EditorialSlide(
                slide_index=2,
                prose="Phineas Gage survived an iron rod through his skull.",
            )],
            hard_cap=24,
            api_key="dummy",
        )
    assert "Gage" in str(exc.value) or "Phineas" in str(exc.value)


def test_fitter_rejects_overcap_line(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": [
                "phineas gage took an iron rod to his head",
                "in 1848",
                "and survived the injury.",
            ]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    with pytest.raises(LineFitError):
        fit_slide_lines(
            editorial_slides=[EditorialSlide(
                slide_index=2,
                prose="Phineas Gage survived an iron rod through his skull in 1848.",
            )],
            hard_cap=24,
            api_key="dummy",
        )


def test_fitter_accepts_clean_output(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": ["phineas gage,", "took a rod", "in 1848"]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    fits, _ = fit_slide_lines(
        editorial_slides=[EditorialSlide(
            slide_index=2,
            prose="Phineas Gage took a rod through his skull in 1848.",
        )],
        hard_cap=24,
        api_key="dummy",
    )
    assert len(fits) == 1
    assert fits[0].lines == ["phineas gage,", "took a rod", "in 1848"]


def test_parse_json_payload_handles_trailing_commentary():
    """Haiku sometimes appends explanatory text after the JSON object.
    The parser must extract the first valid object regardless. This is
    the actual production failure observed on run 25541381828.
    """
    from src.content.carousel_writer import _parse_json_payload
    raw = (
        '{"slides": [{"slide_index": 2, "lines": ["a", "b", "c"]}]}\n\n'
        "I tightened slide 2 by dropping the redundant clause and "
        "moved the date marker to the second line."
    )
    out = _parse_json_payload(raw)
    assert out["slides"][0]["slide_index"] == 2


def test_parse_json_payload_handles_fenced_block():
    from src.content.carousel_writer import _parse_json_payload
    raw = '```json\n{"slides": [{"slide_index": 2, "lines": ["a", "b", "c"]}]}\n```'
    out = _parse_json_payload(raw)
    assert out["slides"][0]["slide_index"] == 2


def test_parse_json_payload_handles_trailing_comma_in_array():
    """Haiku occasionally emits trailing commas (JavaScript-ism, invalid JSON).
    This is the second flavor of failure observed on run 25542151236
    (JSONDecodeError 'Expecting value: line 8 column 3 (char 677)').
    """
    from src.content.carousel_writer import _parse_json_payload
    raw = (
        '{"slides": [\n'
        '  {"slide_index": 2, "lines": ["a", "b", "c",]},\n'
        '  {"slide_index": 3, "lines": ["d", "e", "f"]},\n'
        ']}'
    )
    out = _parse_json_payload(raw)
    assert len(out["slides"]) == 2
    assert out["slides"][0]["lines"] == ["a", "b", "c"]


def test_parse_json_payload_handles_trailing_comma_in_object():
    from src.content.carousel_writer import _parse_json_payload
    raw = (
        '{"slides": [{"slide_index": 2, "lines": ["a", "b", "c"],}],}'
    )
    out = _parse_json_payload(raw)
    assert out["slides"][0]["slide_index"] == 2


def test_fitter_exception_carries_partial_usage(monkeypatch):
    """When the fitter raises, callers must be able to read the partial
    cost so the carousel_quality.jsonl ledger reflects honest spend."""
    fake = MagicMock()
    fake.messages.create.return_value = _mock_anthropic_response({
        "slides": [
            {"slide_index": 2, "lines": ["phineas gage", "took a rod", "to the head"]}
        ]
    })
    monkeypatch.setattr("src.content.carousel_writer.Anthropic", lambda api_key: fake)
    with pytest.raises(FactPreservationError) as exc:
        fit_slide_lines(
            editorial_slides=[EditorialSlide(
                slide_index=2,
                prose="Phineas Gage survived an iron rod through his skull in 1848.",
            )],
            hard_cap=24,
            api_key="dummy",
        )
    assert exc.value.usage["stage"] == "fitter"
    assert exc.value.usage["input_tokens"] == 100
    assert exc.value.usage["output_tokens"] == 200
    assert exc.value.usage["cost_usd"] > 0
