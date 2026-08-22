from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable

from .config import Config
from .models import Paper


GENREC_TERMS = (
    "generative recommendation",
    "generative recommender",
    "generative retrieval",
    "semantic id",
    "semantic identifier",
    "semantic token",
    "item token",
    "item tokenizer",
    "item tokenization",
)

CORE_LLM_TERMS = (
    "foundation model",
    "base model",
    "large language model",
    "language model pretraining",
    "language model pre-training",
    "pretraining",
    "pre-training",
    "post-training",
    "post training",
    "instruction tuning",
    "supervised fine-tuning",
    "alignment",
    "rlhf",
    "rlaif",
    "direct preference optimization",
    "dpo",
    "grpo",
    "mixture of experts",
    "mixture-of-experts",
    "scaling law",
    "training data",
    "data curation",
    "tokenizer",
    "technical report",
    "whitepaper",
    "white paper",
)

STRONG_LLM_TERMS = (
    "foundation model",
    "base model",
    "pretraining",
    "pre-training",
    "post-training",
    "post training",
    "instruction tuning",
    "supervised fine-tuning",
    "rlhf",
    "rlaif",
    "preference optimization",
    "mixture of experts",
    "mixture-of-experts",
    "scaling law",
    "training data",
    "data curation",
    "distributed training",
    "technical report",
    "whitepaper",
    "white paper",
)

LLM_CONTEXT_TERMS = (
    "large language model",
    "language model",
    "llm",
    "autoregressive text",
    "text generation model",
)

AB_EXPERIMENT_PATTERN = re.compile(
    r"(?:\ba\s*/\s*b(?:\s+(?:tests?|testing|experiments?))?\b|"
    r"\bonline\s+(?:controlled\s+)?(?:tests?|testing|experiments?)\b|"
    r"\bcontrolled\s+online\s+experiments?\b|"
    r"\blive[- ]traffic\s+experiments?\b)",
    re.IGNORECASE,
)

OFFICIAL_MODEL_PATTERN = re.compile(
    r"\b(?:gpt[- ]?\d(?:\.\d)?|openai[- ]?o[134]|claude(?:[- ]\w+)?|"
    r"gemini[- ]?\d(?:\.\d)?|gemma[- ]?\d|llama[- ]?\d(?:\.\d)?|grok[- ]?\d|"
    r"phi[- ]?\d|nova(?:[- ]\w+)?|nemotron(?:[- ]\w+)?|deepseek[- ]?[vr]\d|"
    r"kimi[- ]?k\d|minimax[- ]?m\d|glm[- ]?\d|chatglm|qwen[- ]?\d(?:\.\d)?|"
    r"doubao(?:[- ]\w+)?|seed[- ]?\d(?:\.\d)?|hunyuan(?:[- ]\w+)?|mimo[- ]?\w+|"
    r"baichuan[- ]?\w+|yi[- ]?\w+|step[- ]?\d|pangu(?:[- ]\w+)?|mixtral|mistral)\b",
    re.IGNORECASE,
)

NON_BASE_MODEL_TITLE_TERMS = (
    "benchmark",
    "bench:",
    "toolkit",
    "evaluation",
    "perceptionbench",
    "minitriton",
)

APPLICATION_ONLY_TERMS = (
    "healthcare application",
    "medical application",
    "legal application",
    "education application",
    "financial application",
    "llm agent for",
    "using llm for",
    "large language models for recommendation",
)

TAG_RULES = {
    "LLM 基模": ["large language model", "foundation model", "base model"],
    "预训练": ["pretraining", "pre-training", "pretrain", "scaling law"],
    "后训练": ["post-training", "post training", "instruction tuning", "supervised fine-tuning", "rlhf", "rlaif", "dpo", "grpo"],
    "GenRec": ["generative recommendation", "generative recommender", "generative retrieval"],
    "Semantic ID": ["semantic id", "semantic identifier", "item identifier"],
    "Tokenization": ["semantic token", "item token", "tokenization", "codebook"],
    "Reasoning": ["reasoning", "reinforcement learning", "chain of thought"],
    "MoE": ["mixture of experts", "mixture-of-experts", "moe"],
    "Multimodal": ["multimodal", "vision-language", "audio-language"],
    "训练系统": ["training system", "distributed training", "parallelism", "training efficiency"],
    "推理系统": ["inference", "serving", "kv cache", "speculative decoding"],
}


def prepare_candidates(papers: Iterable[Paper], config: Config) -> list[Paper]:
    cutoff = dt.date.today() - dt.timedelta(days=config.retention_days)
    selected: list[Paper] = []
    for paper in papers:
        paper_date = _paper_date(paper)
        if paper_date < cutoff or paper_date > dt.date.today() + dt.timedelta(days=7):
            continue
        text = _search_text(paper)
        if any(term.lower() in text for term in config.exclude_keywords):
            continue
        genrec = is_genrec(paper)
        core_llm = is_core_llm(paper)
        enterprise = is_enterprise_paper(paper, config)
        if not genrec and not core_llm:
            continue
        if genrec and config.require_ab_genrec and not has_ab_experiment(paper):
            continue
        if core_llm and not genrec and config.require_enterprise_llm and not enterprise:
            continue
        paper.tags = infer_tags(paper, config)
        paper.score = score_paper(paper, config)
        selected.append(paper)
    return sorted(selected, key=lambda item: (-_date_ordinal(item), -item.score, item.title.lower()))


def choose_daily_picks(papers: list[Paper], config: Config) -> list[Paper]:
    """Choose every fresh, high-signal item; daily_limit=0 means no count cap."""
    if not papers:
        return []
    newest = max(_paper_date(paper) for paper in papers)
    window_start = newest - dt.timedelta(days=max(0, config.daily_window_days - 1))
    selected = [
        paper
        for paper in papers
        if _paper_date(paper) >= window_start and paper.score >= config.daily_min_score
    ]
    if not selected:
        selected = [paper for paper in papers if _paper_date(paper) == newest]
    if config.daily_limit > 0:
        return selected[: config.daily_limit]
    return selected


def score_paper(paper: Paper, config: Config) -> int:
    text = _search_text(paper)
    genrec = is_genrec(paper)
    enterprise = is_enterprise_paper(paper, config)
    score = 0
    if paper.content_type == "company_report" and is_core_llm(paper):
        score += 50
    if genrec:
        score += 32
    if genrec and enterprise:
        score += 42
    elif enterprise:
        score += 12
    for tag in infer_tags(paper, config):
        score += {
            "LLM 基模": 18,
            "预训练": 18,
            "后训练": 18,
            "GenRec": 24,
            "Semantic ID": 22,
            "Tokenization": 14,
            "企业论文": 18,
            "A/B 实验": 28,
            "Reasoning": 8,
            "MoE": 10,
            "训练系统": 10,
            "推理系统": 8,
        }.get(tag, 2)
    if paper.venue.lower() in {"recsys", "sigir", "www", "kdd", "wsdm", "neurips", "icml", "iclr", "acl", "emnlp"}:
        score += 18
    if paper.pdf_url:
        score += 4
    if paper.abstract:
        score += 4
    if any(term in text for term in ("technical report", "whitepaper", "white paper")):
        score += 14
    age = max(0, (dt.date.today() - _paper_date(paper)).days)
    score += max(0, 18 - age // 3)
    return score


def infer_tags(paper: Paper, config: Config | None = None) -> list[str]:
    text = _search_text(paper)
    tags = [tag for tag, terms in TAG_RULES.items() if any(term in text for term in terms)]
    if paper.content_type == "company_report":
        tags.insert(0, "LLM 基模")
        tags.insert(0, "官方技术报告")
    if config and is_enterprise_paper(paper, config):
        tags.insert(0, "企业论文")
    if has_ab_experiment(paper):
        tags.insert(0, "A/B 实验")
    if paper.company:
        tags.insert(0, paper.company)
    unique: list[str] = []
    for tag in tags:
        if tag not in unique:
            unique.append(tag)
    return unique[:8] or ["GenRec"]


def is_genrec(paper: Paper) -> bool:
    text = _search_text(paper)
    return any(term in text for term in GENREC_TERMS)


def is_core_llm(paper: Paper) -> bool:
    text = _search_text(paper)
    if paper.content_type == "company_report":
        title = paper.title.lower()
        if any(term in title for term in NON_BASE_MODEL_TITLE_TERMS):
            return False
        training_signal = any(
            term in text
            for term in STRONG_LLM_TERMS
            if term not in {"technical report", "whitepaper", "white paper"}
        )
        return bool(OFFICIAL_MODEL_PATTERN.search(text)) or (
            training_signal and any(term in text for term in LLM_CONTEXT_TERMS)
        )
    if not any(term in text for term in LLM_CONTEXT_TERMS):
        return False
    if not any(term in text for term in STRONG_LLM_TERMS):
        return False
    application_only = any(term in text for term in APPLICATION_ONLY_TERMS)
    technical_depth = sum(term in text for term in STRONG_LLM_TERMS) >= 2
    return not application_only or technical_depth


def is_enterprise_paper(paper: Paper, config: Config) -> bool:
    text = " ".join([paper.company, *paper.affiliations, *paper.authors]).lower()
    return bool(paper.company) or any(term.lower() in text for term in config.enterprise_keywords)


def has_ab_experiment(paper: Paper) -> bool:
    return bool(AB_EXPERIMENT_PATTERN.search(_search_text(paper)))


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
