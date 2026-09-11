from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .models import Paper
from .ranking import choose_daily_picks, prepare_candidates
from .sources import classify_company, collect_all, deduplicate
from .summarizer import analyze_papers


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the DeepSearch daily digest")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--out", default="public/papers.json")
    parser.add_argument("--fixtures", action="store_true", help="Use the bundled preview data")
    parser.add_argument("--reset", action="store_true", help="Rebuild without the previous archive")
    parser.add_argument("--reselect-existing", action="store_true", help="Reapply ranking to the current archive without network calls")
    args = parser.parse_args()

    config = load_config(args.config)
    output = Path(args.out)
    previous_payload = {"papers": []} if args.reset else _load_payload(output)
    previous = [Paper.from_dict(item) for item in previous_payload.get("papers", [])]
    for paper in previous:
        classify_company(paper, config)
    previous_by_id = {paper.id: paper for paper in previous}

    if args.reselect_existing:
        discovered = previous
        source_errors = []
        for paper in discovered:
            classify_company(paper, config)
    elif args.fixtures:
        discovered = [Paper.from_dict(item) for item in _load_payload(Path("fixtures/papers.json")).get("papers", [])]
        source_errors: list[str] = []
    else:
        discovered, source_errors = collect_all(config)

    candidates = prepare_candidates(discovered, config)
    daily_picks = choose_daily_picks(candidates, config)

    archived = prepare_candidates(previous, config)
    merged = deduplicate(_merge(daily_picks, candidates, archived))
    cutoff = dt.date.today() - dt.timedelta(days=config.retention_days)
    merged = [paper for paper in merged if _paper_date(paper) >= cutoff]
    merged.sort(key=lambda paper: (_paper_date(paper), paper.score), reverse=True)
    previous_titles = {_normalized_title(paper.title) for paper in previous}
    new_papers = sum(_normalized_title(paper.title) not in previous_titles for paper in merged)

    # Analyze the complete rolling archive. Existing complete analyses are reused by
    # signature, while newly discovered or fallback entries are backfilled.
    analyze_papers(merged, previous_by_id, config)

    daily_ids = {paper.id for paper in daily_picks}
    for paper in merged:
        paper.is_daily_pick = paper.id in daily_ids

    now = dt.datetime.now(ZoneInfo(config.timezone))
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "site": {
            "title": config.title,
            "subtitle": config.subtitle,
            "timezone": config.timezone,
            "daily_limit": config.daily_limit,
            "daily_window_days": config.daily_window_days,
            "daily_min_score": config.daily_min_score,
            "retention_days": config.retention_days,
        },
        "status": {
            "analysis_enabled": bool(os.getenv("DEEPSEEK_API_KEY")),
            "source_errors": source_errors,
            "discovered": len(discovered),
            "candidates": len(candidates),
            "new_papers": new_papers,
            "daily_picks": len(daily_picks),
            "analysis_complete": sum(paper.analysis_status == "complete" for paper in merged),
            "analysis_fallback": sum(paper.analysis_status != "complete" for paper in merged),
        },
        "sources": ["arXiv", "DBLP", "OpenAlex", "Semantic Scholar", "Official GitHub"],
        "companies": list(config.company_queries),
        "papers": [paper.to_dict() for paper in merged],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(merged)} papers ({len(daily_picks)} daily picks) to {output}")
    if source_errors:
        print("Source warnings: " + "; ".join(source_errors))
        if os.getenv("GITHUB_ACTIONS") == "true":
            for warning in source_errors:
                escaped = warning.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                print(f"::warning title=Data source degraded::{escaped}")
    return 0


def _load_payload(path: Path) -> dict:
    if not path.exists():
        return {"papers": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"papers": []}


def _merge(*groups: list[Paper]) -> list[Paper]:
    result: list[Paper] = []
    seen: set[str] = set()
    for group in groups:
        for paper in group:
            if paper.id in seen:
                continue
            seen.add(paper.id)
            result.append(paper)
    return result


def _paper_date(paper: Paper) -> dt.date:
    value = (paper.published or paper.updated or "")[:10]
    for fmt in ("%Y-%m-%d", "%Y"):
        try:
            return dt.datetime.strptime(value[:4] if fmt == "%Y" else value, fmt).date()
        except ValueError:
            continue
    return dt.date.today()


def _normalized_title(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


if __name__ == "__main__":
    raise SystemExit(main())
