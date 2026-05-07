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
