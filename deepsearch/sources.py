from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import Any

from .config import Config
from .models import Paper

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
USER_AGENT = "DeepSearch/0.1 (+https://github.com/weiyang22/DeepSearch)"


def collect_all(config: Config) -> tuple[list[Paper], list[str]]:
    papers: list[Paper] = []
    errors: list[str] = []
    collectors = [
        ("arXiv", collect_arxiv),
        ("DBLP", collect_dblp),
        ("OpenAlex", collect_openalex),
        ("Semantic Scholar", collect_semantic_scholar),
        ("Official GitHub", collect_official_github),
    ]
    for name, collector in collectors:
        try:
            papers.extend(collector(config))
        except Exception as exc:  # one source must not stop the daily digest
            errors.append(f"{name}: {exc}")
    return deduplicate(papers), errors


def collect_arxiv(config: Config) -> list[Paper]:
    categories = " OR ".join(f"cat:{item}" for item in config.arxiv_categories)
    topic_terms = " OR ".join(f'all:"{item}"' for item in config.topic_queries)
    company_terms = " OR ".join(
        f'all:"{term}"' for terms in config.company_queries.values() for term in terms
    )
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=config.retention_days)
    date_range = f"submittedDate:[{cutoff:%Y%m%d%H%M} TO {dt.datetime.now(dt.timezone.utc):%Y%m%d%H%M}]"
    queries = [
        f"({categories}) AND ({topic_terms}) AND {date_range}",
        f"({company_terms}) AND {date_range}",
    ]
    papers: list[Paper] = []
    for query in queries:
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {
                "search_query": query,
                "start": 0,
                "max_results": config.arxiv_max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        body = _request(url, timeout=45)
        root = ET.fromstring(body)
        for entry in root.findall(ATOM + "entry"):
            abs_url = _xml_text(entry, ATOM + "id")
            arxiv_id = re.sub(r"v\d+$", "", abs_url.rstrip("/").split("/")[-1])
            authors = [_xml_text(author, ATOM + "name") for author in entry.findall(ATOM + "author")]
            categories_found = [
                node.attrib.get("term", "")
                for node in entry.findall(ATOM + "category")
                if node.attrib.get("term")
            ]
            pdf_url = next(
                (
                    node.attrib.get("href", "")
                    for node in entry.findall(ATOM + "link")
                    if node.attrib.get("title") == "pdf" or node.attrib.get("type") == "application/pdf"
                ),
                abs_url.replace("/abs/", "/pdf/"),
            )
            paper = Paper(
                id=f"arxiv:{arxiv_id}",
                title=_clean(_xml_text(entry, ATOM + "title")),
                authors=[item for item in authors if item],
                published=_xml_text(entry, ATOM + "published"),
                updated=_xml_text(entry, ATOM + "updated"),
                abstract=_clean(_xml_text(entry, ATOM + "summary")),
                url=abs_url,
                pdf_url=pdf_url,
                doi=_xml_text(entry, ARXIV + "doi"),
                source="arXiv",
                categories=categories_found,
            )
            classify_company(paper, config)
            papers.append(paper)
        time.sleep(1)
    return papers


def collect_dblp(config: Config) -> list[Paper]:
    papers: list[Paper] = []
    for query in config.topic_queries[:8]:
        url = "https://dblp.org/search/publ/api?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "h": "12"}
        )
        payload = _request_json(url)
        hits = payload.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        for hit in hits or []:
            info = hit.get("info", {}) or {}
            title = _clean(str(info.get("title", ""))).rstrip(".")
            if not title:
                continue
            authors = info.get("authors", {}).get("author", []) if isinstance(info.get("authors"), dict) else []
            if isinstance(authors, dict):
                authors = [authors]
            author_names = [str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in authors]
            doi = str(info.get("doi", ""))
            link = str(info.get("ee", "") or info.get("url", ""))
            paper = Paper(
                id=f"dblp:{info.get('key') or _slug(title)}",
                title=title,
                authors=[item for item in author_names if item],
                published=str(info.get("year", "")),
                updated=str(info.get("year", "")),
                url=link,
                pdf_url=link,
                doi=doi,
                source="DBLP",
                venue=str(info.get("venue", "")),
                categories=[str(info.get("venue", ""))] if info.get("venue") else [],
            )
            classify_company(paper, config)
            papers.append(paper)
        time.sleep(0.25)
    return papers


def collect_openalex(config: Config) -> list[Paper]:
    papers: list[Paper] = []
    cutoff = (dt.date.today() - dt.timedelta(days=config.retention_days)).isoformat()
    queries = config.topic_queries[:8] + [terms[0] for terms in config.company_queries.values()]
    for query in queries:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
            {
                "search": query,
                "filter": f"from_publication_date:{cutoff}",
                "per-page": str(config.openalex_per_query),
                "sort": "publication_date:desc",
            }
        )
        for work in _request_json(url).get("results", []) or []:
            title = _clean(str(work.get("display_name", "")))
            if not title:
                continue
            primary = work.get("primary_location", {}) or {}
            source = primary.get("source", {}) or {}
            ids = work.get("ids", {}) or {}
            open_access = work.get("best_oa_location", {}) or {}
            authorships = work.get("authorships", []) or []
            paper = Paper(
                id=f"openalex:{str(work.get('id', '')).rstrip('/').split('/')[-1]}",
                title=title,
                authors=[str(item.get("author", {}).get("display_name", "")) for item in authorships],
                affiliations=_unique(
                    str(inst.get("display_name", ""))
                    for item in authorships
                    for inst in item.get("institutions", []) or []
                ),
                published=str(work.get("publication_date", "") or work.get("publication_year", "")),
                updated=str(work.get("updated_date", "") or work.get("publication_date", "")),
                abstract=_openalex_abstract(work.get("abstract_inverted_index") or {}),
                url=str(primary.get("landing_page_url", "") or ids.get("openalex", "")),
                pdf_url=str(open_access.get("pdf_url", "") or primary.get("pdf_url", "")),
                doi=_clean_doi(str(ids.get("doi", ""))),
                source="OpenAlex",
                venue=str(source.get("display_name", "")),
                categories=[str(item.get("display_name", "")) for item in work.get("topics", [])[:4]],
            )
            classify_company(paper, config)
            papers.append(paper)
        time.sleep(0.2)
    return papers


def collect_semantic_scholar(config: Config) -> list[Paper]:
    papers: list[Paper] = []
    fields = "paperId,title,abstract,authors,year,venue,url,externalIds,publicationDate,openAccessPdf"
    headers = {}
    if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        headers["x-api-key"] = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
    queries = config.topic_queries[:8] + [terms[0] for terms in config.company_queries.values()]
    for query in queries:
        url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
            {"query": query, "limit": str(config.semantic_scholar_limit), "fields": fields}
        )
        try:
            results = _request_json(url, headers=headers).get("data", []) or []
        except Exception:
            continue
        for work in results:
            external = work.get("externalIds", {}) or {}
            pdf = work.get("openAccessPdf", {}) or {}
            paper = Paper(
                id=f"s2:{work.get('paperId')}",
                title=_clean(str(work.get("title", ""))),
                authors=[str(item.get("name", "")) for item in work.get("authors", []) or []],
                published=str(work.get("publicationDate", "") or work.get("year", "")),
                updated=str(work.get("publicationDate", "") or work.get("year", "")),
                abstract=_clean(str(work.get("abstract", "") or "")),
                url=str(work.get("url", "") or ""),
                pdf_url=str(pdf.get("url", "") or ""),
                doi=str(external.get("DOI", "") or ""),
                source="Semantic Scholar",
                venue=str(work.get("venue", "") or ""),
            )
            classify_company(paper, config)
            papers.append(paper)
        time.sleep(0.35)
    return papers


def collect_official_github(config: Config) -> list[Paper]:
    papers: list[Paper] = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=config.retention_days)
    github_headers = {"Accept": "application/vnd.github+json"}
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if github_token:
        github_headers["Authorization"] = f"Bearer {github_token}"
    for company, org in config.github_orgs.items():
        url = (
            f"https://api.github.com/orgs/{urllib.parse.quote(org)}/repos"
            f"?sort=created&direction=desc&per_page={config.official_github_per_org}"
        )
        repos = _request_json(url, headers=github_headers)
        for repo in repos:
            repo_name = str(repo.get("name", ""))
            created = _parse_datetime(str(repo.get("created_at", "")))
            if not created or created < cutoff:
                continue
            description = _clean(str(repo.get("description", "") or ""))
            readme = _github_readme(org, repo_name, github_headers)
            text = f"{repo_name} {description} {readme}".lower()
            if not _looks_like_foundation_model_report(text):
                continue
            arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", text)
            report_url = _github_report_url(
                org,
                repo_name,
                str(repo.get("default_branch", "main") or "main"),
                readme,
            )
            abstract = _readme_excerpt(readme) or description
            paper = Paper(
                id=(f"arxiv:{arxiv_match.group(1)}" if arxiv_match else f"github:{org}/{repo_name}"),
                title=_display_repo_title(repo_name, description),
                authors=[f"{company} Research"],
                published=str(repo.get("created_at", "")),
                updated=str(repo.get("pushed_at", "") or repo.get("updated_at", "")),
                abstract=abstract,
                url=str(repo.get("html_url", "")),
                pdf_url=(
                    f"https://arxiv.org/pdf/{arxiv_match.group(1)}" if arxiv_match else report_url
                ),
                source="Official GitHub",
                content_type="company_report",
                company=company,
                venue="Official release",
                categories=["LLM", "Technical Report"],
                evidence_basis="official_release",
            )
            papers.append(paper)
    return papers


def _looks_like_foundation_model_report(text: str) -> bool:
    report_signal = any(
        term in text
        for term in (
            "technical report", "tech report", "technical_report", "tech_report",
            "full report", "whitepaper", "white paper", "arxiv.org",
        )
    )
    model_signal = any(
        term in text
        for term in (
            "foundation model", "base model", "pretraining", "pre-training", "post-training",
            "alignment", "mixture of experts", "deepseek-v", "deepseek-r", "kimi k",
            "minimax-", "glm-", "gemini", "gemma", "language model",
        )
    )
    return report_signal and model_signal


def _github_report_url(org: str, repo: str, branch: str, readme: str) -> str:
    """Resolve an official report PDF linked by URL or repository-relative path."""
    links = re.findall(r"(?:href=[\"']|\]\()([^\"')]+\.pdf)(?:[\"']|\))", readme, re.I)
    links.extend(re.findall(r"https?://[^\s)\]>'\"]+\.pdf", readme, re.I))
    for link in links:
        clean = link.strip()
        normalized = clean.lower().replace("-", "_")
        if not any(term in normalized for term in ("report", "whitepaper", "white_paper")):
            continue
        if clean.startswith(("http://", "https://")):
            return clean
        path = clean.lstrip("./")
        return (
            f"https://github.com/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}"
            f"/blob/{urllib.parse.quote(branch)}/{urllib.parse.quote(path, safe='/')}"
        )
    return ""


def deduplicate(papers: Iterable[Paper]) -> list[Paper]:
    by_key: dict[str, Paper] = {}
    for paper in papers:
        if not paper.title:
            continue
        key = _normalized_title(paper.title)
        current = by_key.get(key)
        if not current:
            by_key[key] = paper
            continue
        preferred, other = (paper, current) if _paper_quality(paper) > _paper_quality(current) else (current, paper)
        preferred.company = preferred.company or other.company
        preferred.affiliations = _unique([*preferred.affiliations, *other.affiliations])
        preferred.authors = _unique([*preferred.authors, *other.authors])
        preferred.categories = _unique([*preferred.categories, *other.categories])
        preferred.doi = preferred.doi or other.doi
        preferred.url = preferred.url or other.url
        preferred.pdf_url = preferred.pdf_url or other.pdf_url
        if other.content_type == "company_report":
            preferred.content_type = "company_report"
            preferred.evidence_basis = "official_release"
        by_key[key] = preferred
    return list(by_key.values())


def _request_json(url: str, headers: dict[str, str] | None = None) -> Any:
    return json.loads(_request(url, headers=headers).decode("utf-8"))


def _request(url: str, headers: dict[str, str] | None = None, timeout: int = 25) -> bytes:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def _github_readme(org: str, repo: str, headers: dict[str, str]) -> str:
    try:
        payload = _request_json(f"https://api.github.com/repos/{org}/{repo}/readme", headers=headers)
        return base64.b64decode(payload.get("content", "")).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _readme_excerpt(value: str) -> str:
    clean = re.sub(r"```.*?```", " ", value, flags=re.S)
    clean = re.sub(r"!\[[^]]*\]\([^)]*\)", " ", clean)
    clean = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", clean)
    clean = re.sub(r"[#>*|`]+", " ", clean)
    paragraphs = [_clean(item) for item in re.split(r"\n\s*\n", clean)]
    useful = [item for item in paragraphs if 90 <= len(item) <= 1400]
    return (useful[0] if useful else _clean(clean))[:1800]


def _display_repo_title(name: str, description: str) -> str:
    pretty = name.replace("-", " ").replace("_", " ").strip()
    if description and len(description) < 110:
        return f"{pretty}: {description}"
    return pretty


def classify_company(paper: Paper, config: Config) -> None:
    if paper.content_type == "company_report" and paper.company:
        return
    text = f"{paper.title} {' '.join(paper.authors)} {' '.join(paper.affiliations)}".lower()
    paper.company = ""
    for company, terms in config.company_queries.items():
        if any(term.lower() in text for term in terms):
            paper.company = company
            return


def _paper_quality(paper: Paper) -> int:
    return (
        len(paper.abstract)
        + (200 if paper.content_type == "company_report" else 0)
        + (120 if paper.pdf_url else 0)
        + (80 if paper.doi else 0)
        + len(paper.affiliations) * 10
    )


def _openalex_abstract(index: dict[str, list[int]]) -> str:
    positions: list[tuple[int, str]] = []
    for word, values in index.items():
        positions.extend((position, word) for position in values)
    return " ".join(word for _, word in sorted(positions))


def _xml_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_doi(value: str) -> str:
    return value.replace("https://doi.org/", "").strip()


def _normalized_title(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        if clean and clean not in result:
            result.append(clean)
    return result


def _parse_datetime(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
