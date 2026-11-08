from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .models import Paper
from .ranking import choose_daily_picks, effective_daily_window, prepare_candidates
from .sources import classify_company, collect_all, deduplicate
from .summarizer import analyze_papers


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the DeepSearch daily digest")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--out", default="public/papers.json")
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
    else:
        discovered, source_errors = collect_all(config)

    candidates = prepare_candidates(discovered, config)
    archived = prepare_candidates(previous, config)
    # Daily picks compete across the whole recent pool — fresh discoveries plus
    # the current archive — so a slow discovery day (for example a paper aging
    # out of a source's per-query window) cannot blank the 近期 feed.
    daily_pool = deduplicate(_merge(candidates, archived))
    daily_picks = choose_daily_picks(daily_pool, config)

    merged = deduplicate(_merge(daily_picks, candidates, archived))
    # No age-based eviction: the archive accumulates and each run overwrites
    # it with the merged pool.
    merged.sort(key=lambda paper: (_paper_date(paper), paper.score), reverse=True)
    merged_titles = {_normalized_title(paper.title) for paper in merged}
    merged_ids = {paper.id for paper in merged}
    # "Never evict" only holds if the committed archive actually came in: a
    # stale or conflict-clobbered papers.json silently rebuilt the archive from
    # fewer papers and 56 entries disappeared in Nov 2026. Fail loudly instead
    # of shrinking quietly - restoring lost papers is cheap, noticing them is not.
    #
    # Identity is id OR normalized title: a preprint can be retitled upstream
    # (Open-HumanScale became Open-HumanWAM in Nov 2026), and _merge keys on id,
    # so the record survives with a new title. Judging by title alone failed the
    # daily run for a paper that was present all along.
    lost = [
        paper
        for paper in previous
        if paper.id not in merged_ids and _normalized_title(paper.title) not in merged_titles
    ]
    if lost:
        raise RuntimeError(
            f"归档回退：{len(lost)} 篇历史论文未进入新归档（首例 {lost[0].id} / {lost[0].title[:60]!r}）。"
            "若为有意的门槛收紧，请先移除这些条目；否则说明输入归档不完整。"
        )
    # Count by identity, not title: a retitled preprint is the same paper.
    previous_ids = {paper.id for paper in previous}
    new_papers = sum(paper.id not in previous_ids for paper in merged)

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
        },
        "status": {
            "analysis_enabled": bool(os.getenv("DEEPSEEK_API_KEY")),
            "source_errors": source_errors,
            "discovered": len(discovered),
            "candidates": len(candidates),
            "new_papers": new_papers,
            "daily_picks": len(daily_picks),
            # Window that actually produced the daily picks; equals
            # daily_window_days on healthy days and relaxes on degraded ones.
            "effective_daily_window_days": effective_daily_window(daily_pool, config)
            or config.daily_window_days,
            "analysis_complete": sum(paper.analysis_status == "complete" for paper in merged),
            "analysis_fallback": sum(paper.analysis_status != "complete" for paper in merged),
        },
        "sources": [
            "arXiv",
            *(["DBLP"] if config.enable_dblp else []),
            "OpenAlex",
            "Semantic Scholar",
            "Official GitHub",
        ],
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
