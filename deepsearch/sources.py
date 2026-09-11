from __future__ import annotations

import base64
import datetime as dt
import http.client
import json
import os
import re
import socket
import time
import urllib.error
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
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


class PartialCollectionError(RuntimeError):
    """A source returned useful records while some of its requests failed."""

    def __init__(self, message: str, papers: list[Paper]):
        super().__init__(message)
        self.papers = papers


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
        started = time.monotonic()
        print(f"Collecting {name}...")
        try:
            papers.extend(collector(config))
        except PartialCollectionError as exc:
            papers.extend(exc.papers)
            errors.append(f"{name}: {exc}")
        except Exception as exc:  # one source must not stop the daily digest
            errors.append(f"{name}: {exc}")
        finally:
            print(f"Finished {name} in {time.monotonic() - started:.1f}s")
    return deduplicate(papers), errors


def collect_arxiv(config: Config) -> list[Paper]:
    categories = " OR ".join(f"cat:{item}" for item in config.arxiv_categories)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=config.retention_days)
    date_range = f"submittedDate:[{cutoff:%Y%m%d%H%M} TO {dt.datetime.now(dt.timezone.utc):%Y%m%d%H%M}]"
    queries = _arxiv_queries(config, categories, date_range)
    papers: list[Paper] = []
    failures: list[str] = []
    for query in queries:
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {
                "search_query": query,
                "start": 0,
                "max_results": min(config.arxiv_max_results, 200),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        try:
            body = _request(url, timeout=30, attempts=3)
            root = ET.fromstring(body)
        except Exception as exc:
            failures.append(str(exc))
            continue
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
        # arXiv asks API clients to leave at least three seconds between calls.
        # A little extra headroom matters on shared GitHub Actions IP ranges.
        time.sleep(4)
    papers = deduplicate(papers)
    if failures:
        if not papers:
            raise RuntimeError(f"全部 {len(queries)} 个分片失败（{_short_error(failures[0])}）")
        message = f"{len(failures)}/{len(queries)} 个分片失败，已保留成功分片（{_short_error(failures[0])}）"
        raise PartialCollectionError(message, papers)
    return papers


def _arxiv_queries(config: Config, categories: str, date_range: str) -> list[str]:
    """Build a few balanced queries to avoid both oversized requests and rate limits."""
    queries: list[str] = []
    topic_terms = " OR ".join(f'all:\"{term}\"' for term in config.topic_queries[:8])
    if topic_terms:
        queries.append(f"({categories}) AND ({topic_terms}) AND {date_range}")

    # Model-family names cover focused company releases without issuing one query
    # for every institution. Company-only discovery remains covered by OpenAlex,
    # Semantic Scholar and official GitHub collectors.
    discovery_terms = _unique(
        term for terms in config.model_families.values() for term in terms
    )
    for chunk in _chunks(discovery_terms, 11):
        terms = " OR ".join(f'all:\"{term}\"' for term in chunk)
        queries.append(f"({categories}) AND ({terms}) AND {date_range}")
    return queries


def collect_dblp(config: Config) -> list[Paper]:
    papers: list[Paper] = []
    failures: list[str] = []
    # DBLP is supplementary metadata (it does not provide abstracts), so keep its
    # daily footprint small and let the richer sources handle broad discovery.
    query_indexes = (0, 4, 6)
    queries = _unique(
        config.topic_queries[index]
        for index in query_indexes
        if index < len(config.topic_queries)
    )
    for query in queries:
        url = "https://dblp.org/search/publ/api?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "h": "12"}
        )
        try:
            payload = _request_json(
                url,
                headers={"Accept": "application/json"},
                timeout=10,
                request_attempts=1,
                parse_attempts=2,
            )
        except Exception as exc:
            failures.append(str(exc))
            continue
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
        time.sleep(2)
    papers = deduplicate(papers)
    if failures:
        if not papers:
            raise RuntimeError(f"全部关键词失败（{_short_error(failures[0])}）")
        message = f"{len(failures)}/{len(queries)} 个关键词失败，已保留成功结果（{_short_error(failures[0])}）"
        raise PartialCollectionError(message, papers)
    return papers


def collect_openalex(config: Config) -> list[Paper]:
    papers: list[Paper] = []
    cutoff = (dt.date.today() - dt.timedelta(days=config.retention_days)).isoformat()
    queries = _unique([
        *config.topic_queries[:8],
        *[terms[0] for terms in config.company_queries.values()],
        *[terms[0] for terms in config.model_families.values()],
    ])
    requests: list[tuple[str, str, str, str]] = [
        (query, f"from_publication_date:{cutoff}", "", "") for query in queries
    ]
    for company, institution_id in config.openalex_institutions.items():
        requests.extend(
            (
                query,
                f"institutions.id:{institution_id},from_publication_date:{cutoff},type:article|preprint",
                company,
                institution_id,
            )
            for query in config.topic_queries[:8]
        )

    for query, work_filter, focus_company, focus_institution_id in requests:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
            {
                "search": query,
                "filter": work_filter,
                "per-page": str(config.openalex_per_query),
                "sort": "publication_date:desc",
            }
        )
        for work in _request_json(url).get("results", []) or []:
            if focus_institution_id and not _has_human_institution_author(work, focus_institution_id):
                continue
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
            if focus_company:
                paper.company = focus_company
            papers.append(paper)
        time.sleep(0.2)
    return papers


def _has_human_institution_author(work: dict[str, Any], institution_id: str) -> bool:
    normalized_id = institution_id.rstrip("/").split("/")[-1].lower()
    model_author = re.compile(r"\b(?:gemini|chatgpt|gpt[- ]?\d|claude|chatterbox)\b", re.I)
    for authorship in work.get("authorships", []) or []:
        author_name = str(authorship.get("author", {}).get("display_name", ""))
        if not author_name or model_author.search(author_name):
            continue
        institution_ids = {
            str(item.get("id", "")).rstrip("/").split("/")[-1].lower()
            for item in authorship.get("institutions", []) or []
        }
        if normalized_id in institution_ids:
            return True
    return False


def collect_semantic_scholar(config: Config) -> list[Paper]:
    papers: list[Paper] = []
    fields = "paperId,title,abstract,authors,year,venue,url,externalIds,publicationDate,openAccessPdf"
    headers = {}
    if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        headers["x-api-key"] = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
    # Anonymous Semantic Scholar traffic is heavily throttled on shared CI IPs.
    # Core topic searches provide the useful abstracts; company-wide discovery is
    # already handled by OpenAlex and official GitHub.
    queries = config.topic_queries[:8]
    for query in queries:
        url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
            {"query": query, "limit": str(config.semantic_scholar_limit), "fields": fields}
        )
        try:
            results = _request_json(
                url,
                headers=headers,
                timeout=15,
                request_attempts=3 if headers else 2,
                parse_attempts=1,
            ).get("data", []) or []
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
        time.sleep(1 if not headers else 0.35)
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
            if not _repo_matches_model_family(company, repo_name, description, config):
                continue
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


def _repo_matches_model_family(company: str, name: str, description: str, config: Config) -> bool:
    terms = config.model_families.get(company, [])
    if not terms:
        return True
    text = f"{name} {description}".lower()
    return any(term.lower() in text for term in terms)


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
            "minimax-", "glm-", "gemini", "gemma", "gpt-", "claude", "llama", "grok",
            "phi-", "nova", "nemotron", "qwen", "doubao", "seed", "hunyuan", "mimo",
            "baichuan", "yi-", "step-", "pangu", "mistral", "mixtral", "language model",
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


def _request_json(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: int = 25,
    request_attempts: int = 4,
    parse_attempts: int = 3,
) -> Any:
    """Fetch JSON and retry transient HTML/empty responses from public indexes."""
    last_error: Exception | None = None
    body = b""
    for attempt in range(parse_attempts):
        body = _request(url, headers=headers, timeout=timeout, attempts=request_attempts)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < parse_attempts - 1:
                time.sleep(2 ** attempt)
    preview = _clean(body.decode("utf-8", errors="ignore"))[:80]
    detail = preview or _short_error(str(last_error))
    raise RuntimeError(f"响应不是有效 JSON（{detail}）")


def _request(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 25,
    attempts: int = 4,
) -> bytes:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_HTTP_STATUS:
                break
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            elif exc.code == 429:
                delay = 10 * (attempt + 1)
            else:
                delay = 2 ** attempt
        except (urllib.error.URLError, http.client.HTTPException, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            delay = 2 ** attempt
        except Exception as exc:
            last_error = exc
            break
        if attempt < attempts - 1:
            time.sleep(min(delay, 30))
    raise RuntimeError(_short_error(str(last_error)))


def _short_error(value: str) -> str:
    clean = _clean(value)
    return clean[:180] or "未知网络错误"


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


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
    # A model name in a title is not evidence of enterprise authorship.
    text = f"{' '.join(paper.authors)} {' '.join(paper.affiliations)}".lower()
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
