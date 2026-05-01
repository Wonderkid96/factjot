from __future__ import annotations

TRUSTED_FACT_SOURCES = {
    "science": [
        "https://www.nature.com/",
        "https://www.science.org/",
        "https://www.nasa.gov/",
        "https://www.noaa.gov/",
    ],
    "history": [
        "https://www.britannica.com/",
        "https://www.loc.gov/",
        "https://www.smithsonianmag.com/",
    ],
    "geography": [
        "https://www.nationalgeographic.com/",
        "https://www.usgs.gov/",
        "https://www.worldbank.org/",
    ],
    "technology": [
        "https://www.ieee.org/",
        "https://www.acm.org/",
        "https://ourworldindata.org/",
    ],
    "general": [
        "https://en.wikipedia.org/",
        "https://www.britannica.com/",
    ],
}


def get_source_pool(topic: str) -> list[str]:
    lowered = topic.lower()
    for key in ("science", "history", "geography", "technology"):
        if key in lowered:
            return TRUSTED_FACT_SOURCES[key]
    return TRUSTED_FACT_SOURCES["general"]
