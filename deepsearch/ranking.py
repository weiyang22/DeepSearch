from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable

from .config import Config
from .models import Paper

TAG_RULES = {
    "LLM": ["large language model", "llm", "foundation model"],
    "GenRec": ["generative recommendation", "generative recommender", "generative retrieval"],
    "Semantic ID": ["semantic id", "semantic identifier", "item identifier"],
    "Tokenization": ["semantic token", "item token", "tokenization", "codebook"],
    "Agent": ["agentic", "agent", "tool use", "tool-use"],
    "Reasoning": ["reasoning", "reinforcement learning", "chain of thought"],
    "Long Context": ["long context", "long-context", "million token"],
    "MoE": ["mixture of experts", "mixture-of-experts", "moe"],
    "Multimodal": ["multimodal", "vision-language", "audio-language"],
    "Systems": ["inference", "serving", "training system", "distributed"],
}


def prepare_candidates(papers: Iterable[Paper], config: Config) -> list[Paper]:
    cutoff = dt.date.today() - dt.timedelta(days=config.retention_days)
    selected: list[Paper] = []
    for paper in papers:
        if _paper_date(paper) < cutoff:
            continue
        text = _search_text(paper)
        if any(term.lower() in text for term in config.exclude_keywords):
            continue
        company_match = bool(paper.company)
        topic_match = any(term.lower() in text for term in config.include_keywords)
        if not company_match and not topic_match:
            continue
        paper.tags = infer_tags(paper)
        paper.score = score_paper(paper)
        selected.append(paper)
    return sorted(selected, key=lambda item: (-item.score, -_date_ordinal(item), item.title.lower()))


def choose_daily_picks(papers: list[Paper], limit: int) -> list[Paper]:
    if len(papers) <= limit:
        return papers
    reports = [item for item in papers if item.content_type == "company_report"]
    genrec = [item for item in papers if any(tag in item.tags for tag in ("GenRec", "Semantic ID", "Tokenization"))]
    result: list[Paper] = []

    def add(items: list[Paper], count: int) -> None:
        for paper in items:
            if paper not in result:
                result.append(paper)
            if len([item for item in result if item in items]) >= count:
                break

    add(reports, min(2, limit // 2))
    add(genrec, min(2, limit - len(result)))
    for paper in papers:
        if paper not in result:
            result.append(paper)
        if len(result) >= limit:
            break
    return result[:limit]


def score_paper(paper: Paper) -> int:
    text = _search_text(paper)
    score = 0
    if paper.content_type == "company_report":
        score += 45
    if paper.company:
        score += 22
    for tag in infer_tags(paper):
        score += {
            "GenRec": 28,
            "Semantic ID": 28,
            "Tokenization": 18,
            "LLM": 12,
            "Agent": 10,
            "Reasoning": 10,
            "Systems": 8,
        }.get(tag, 5)
    if paper.venue.lower() in {"recsys", "sigir", "www", "kdd", "wsdm", "neurips", "icml", "iclr", "acl", "emnlp"}:
        score += 20
    if paper.pdf_url:
        score += 5
    if paper.abstract:
        score += 5
    if any(term in text for term in ("technical report", "whitepaper", "white paper")):
        score += 12
    age = max(0, (dt.date.today() - _paper_date(paper)).days)
    score += max(0, 20 - age // 3)
    return score


def infer_tags(paper: Paper) -> list[str]:
    text = _search_text(paper)
    tags = [tag for tag, terms in TAG_RULES.items() if any(term in text for term in terms)]
    if paper.content_type == "company_report":
        tags.insert(0, "技术报告")
    if paper.company:
        tags.insert(0, paper.company)
    unique: list[str] = []
    for tag in tags:
        if tag not in unique:
            unique.append(tag)
    return unique[:6] or ["推荐系统"]


def _search_text(paper: Paper) -> str:
    return re.sub(
        r"\s+",
        " ",
        " ".join(
            [
                paper.title,
                paper.abstract,
                paper.venue,
                paper.company,
                " ".join(paper.categories),
                " ".join(paper.affiliations),
            ]
        ).lower(),
    )


def _paper_date(paper: Paper) -> dt.date:
    value = (paper.published or paper.updated or "")[:10]
    for fmt in ("%Y-%m-%d", "%Y"):
        try:
            return dt.datetime.strptime(value[:4] if fmt == "%Y" else value, fmt).date()
        except ValueError:
            continue
    return dt.date.today()


def _date_ordinal(paper: Paper) -> int:
    return _paper_date(paper).toordinal()
