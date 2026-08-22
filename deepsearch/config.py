from __future__ import annotations

import tomllib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    title: str
    subtitle: str
    timezone: str
    daily_limit: int
    daily_window_days: int
    daily_min_score: int
    retention_days: int
    arxiv_categories: list[str]
    topic_queries: list[str]
    include_keywords: list[str]
    exclude_keywords: list[str]
    enterprise_keywords: list[str]
    company_queries: dict[str, list[str]]
    github_orgs: dict[str, str]
    deepseek_base_url: str
    deepseek_model: str
    semantic_scholar_limit: int


def load_config(path: str | Path = "config.toml") -> Config:
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)
    site = raw.get("site", {})
    discovery = raw.get("discovery", {})
    llm = raw.get("llm", {})
    companies = raw.get("companies", {})
    return Config(
        title=str(site.get("title", "LLM&GR")),
        subtitle=str(site.get("subtitle", "大模型与生成式推荐技术雷达")),
        timezone=str(site.get("timezone", "Asia/Shanghai")),
        daily_limit=int(site.get("daily_limit", 0)),
        daily_window_days=int(site.get("daily_window_days", 3)),
        daily_min_score=int(site.get("daily_min_score", 45)),
        retention_days=int(site.get("retention_days", 90)),
        arxiv_categories=list(discovery.get("arxiv_categories", ["cs.AI", "cs.CL", "cs.LG", "cs.IR"])),
        topic_queries=list(discovery.get("topic_queries", [])),
        include_keywords=list(discovery.get("include_keywords", [])),
        exclude_keywords=list(discovery.get("exclude_keywords", [])),
        enterprise_keywords=list(discovery.get("enterprise_keywords", [])),
        company_queries={key: list(value) for key, value in companies.get("queries", {}).items()},
        github_orgs={key: str(value) for key, value in companies.get("github_orgs", {}).items()},
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", str(llm.get("base_url", "https://api.deepseek.com"))),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", str(llm.get("model", "deepseek-v4-flash"))),
        semantic_scholar_limit=int(discovery.get("semantic_scholar_limit", 12)),
    )
