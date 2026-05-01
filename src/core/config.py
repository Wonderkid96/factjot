from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class AppConfig:
    pipeline: dict[str, Any]
    discovery: dict[str, Any]
    render: dict[str, Any]
    review: dict[str, Any]
    storage: dict[str, Any]
    publish: dict[str, Any]
    images: dict[str, Any]
    brand: dict[str, Any]
    env: dict[str, str]


def load_config(
    pipeline_path: str = "config/pipeline.yaml",
    brand_path: str = "brand/brand_kit.json",
    env_path: str = ".env",
) -> AppConfig:
    load_dotenv(env_path)
    with Path(pipeline_path).open("r", encoding="utf-8") as fh:
        pipeline_cfg = yaml.safe_load(fh)
    with Path(brand_path).open("r", encoding="utf-8") as fh:
        brand_cfg = json.load(fh)

    env = {
        "INSTAGRAM_ACCOUNT_ID": os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
        "FACEBOOK_PAGE_ID": os.getenv("FACEBOOK_PAGE_ID", ""),
        "META_ACCESS_TOKEN": os.getenv("META_ACCESS_TOKEN", ""),
        "META_GRAPH_VERSION": os.getenv("META_GRAPH_VERSION", "v21.0"),
        "META_GRAPH_HOST": os.getenv("META_GRAPH_HOST", "graph.facebook.com"),
        "META_LOGIN_FLOW": os.getenv("META_LOGIN_FLOW", "facebook_login"),
        "IMGBB_API_KEY": os.getenv("IMGBB_API_KEY", ""),
        "TIMEZONE": os.getenv("TIMEZONE", "UTC"),
    }
    return AppConfig(
        pipeline=pipeline_cfg["pipeline"],
        discovery=pipeline_cfg["discovery"],
        render=pipeline_cfg["render"],
        review=pipeline_cfg["review"],
        storage=pipeline_cfg["storage"],
        publish=pipeline_cfg.get("publish", {}),
        images=pipeline_cfg.get("images", {}),
        brand=brand_cfg,
        env=env,
    )
