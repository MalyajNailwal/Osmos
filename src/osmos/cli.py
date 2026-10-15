"""Command-line entry point.

    osmos run data/seed_usernames.txt     # collect + classify in one go
    osmos collect data/seed_usernames.txt # scrape only (no media downloaded)
    osmos classify                        # classify whatever hasn't been classified yet
    osmos discover                        # surface candidate usernames from mentions
    osmos export --format csv             # dump results
    osmos stats                           # category breakdown
    osmos dashboard                       # a static visual HTML report (point-in-time snapshot)
    osmos serve                           # the full interactive app: setup, run, live dashboard
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import sqlite3
import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import pipeline, storage
from .config import settings
from .dashboard import render_dashboard
from .usernames import parse_usernames

app = typer.Typer(
    add_completion=False,
    help="Collect Instagram influencer profiles and classify them by content niche.",
)
console = Console()

logging.basicConfig(level=logging.INFO, format="%(message)s")


def _read_usernames(source: str) -> list[str]:
    path = Path(source)
    text = path.read_text() if path.exists() else source
    return parse_usernames(text)


def _db() -> sqlite3.Connection:
    return storage.connect(settings.db_path)


@app.command()
def collect(
    source: str = typer.Argument(..., help="Username file (one per line) or comma-separated list."),
    posts: int = typer.Option(settings.posts_per_profile, help="Recent posts to pull per profile."),
) -> None:
    """Scrape profiles and recent post metadata into the local database. No media is downloaded."""
    usernames = _read_usernames(source)
    console.print(f"Collecting {len(usernames)} profile(s)...")
    conn = _db()
    count = asyncio.run(pipeline.run_collect(conn, usernames, posts_limit=posts))
    console.print(f"[green]Collected {count}/{len(usernames)}[/green]")


@app.command()
def classify(
    limit: int = typer.Option(0, help="Classify at most this many pending profiles (0 = no limit)."),
) -> None:
    """Classify every profile in the database that doesn't have a category yet."""
    conn = _db()
    count = asyncio.run(pipeline.run_classify(conn, limit=limit or None))
    console.print(f"[green]Classified {count} profile(s)[/green]")


@app.command()
def run(
    source: str = typer.Argument(..., help="Username file or comma-separated list."),
    posts: int = typer.Option(settings.posts_per_profile, help="Recent posts to pull per profile."),
) -> None:
    """Collect then classify in one pass."""
    usernames = _read_usernames(source)
    conn = _db()
    console.print(f"Collecting {len(usernames)} profile(s)...")
    collected = asyncio.run(pipeline.run_collect(conn, usernames, posts_limit=posts))
    console.print(f"[green]Collected {collected}/{len(usernames)}[/green]. Classifying...")
    classified = asyncio.run(pipeline.run_classify(conn))
    console.print(f"[green]Classified {classified}[/green]")


@app.command()
def discover(
    min_mentions: int = typer.Option(2, help="Only show candidates mentioned at least this many times."),
    limit: int = typer.Option(30, help="Max candidates to show."),
) -> None:
    """List candidate usernames mentioned across already-collected posts.

    osmos_core has no search/explore endpoint, so this is how new accounts
    surface: who the accounts you already have are tagging and shouting out.
    """
    conn = _db()
    candidates = storage.top_mentions(conn, min_count=min_mentions, limit=limit)
    if not candidates:
        console.print("No new candidates found yet — collect more profiles first.")
        return
    table = Table("username", "mention_count")
    for username, count in candidates:
        table.add_row(f"@{username}", str(count))
    console.print(table)


@app.command()
def export(
    fmt: str = typer.Option("csv", "--format", help="csv or json"),
    category: str = typer.Option("", help="Filter to one category."),
    output: Path | None = typer.Option(None, help="Write to a file instead of stdout."),
) -> None:
    """Dump classified influencers."""
    conn = _db()
    rows = [dict(row) for row in storage.fetch_all(conn, category=category or None)]
    if fmt == "json":
        text = json.dumps(rows, indent=2, default=str)
    elif fmt == "csv":
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        text = buf.getvalue()
    else:
        raise typer.BadParameter("format must be csv or json")

    if output:
        output.write_text(text)
        console.print(f"[green]Wrote {len(rows)} row(s) to {output}[/green]")
    else:
        console.print(text)


@app.command()
def dashboard(
    output: Path = typer.Option(Path("dashboard.html"), help="Where to write the HTML file."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open it in your browser after writing."),
) -> None:
    """Generate a visual HTML report — category chart + sortable/filterable table.

    Self-contained, works fully offline, no server needed. Re-run any time to
    refresh it with whatever's in the database now.
    """
    conn = _db()
    rows = [dict(row) for row in storage.fetch_all(conn)]
    output.write_text(render_dashboard(rows))
    console.print(f"[green]Wrote dashboard for {len(rows)} profile(s) to {output}[/green]")
    if open_browser:
        webbrowser.open(output.resolve().as_uri())


@app.command()
def stats() -> None:
    """Category breakdown of everything collected so far."""
    conn = _db()
    rows = storage.fetch_all(conn)
    counts: dict[str, int] = {}
    for row in rows:
        key = row["category"] or "(unclassified)"
        counts[key] = counts.get(key, 0) + 1
    table = Table("category", "count")
    for category, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        table.add_row(category, str(count))
    console.print(table)
    console.print(f"Total: {len(rows)}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8420, help="Port."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open it in your browser on start."),
) -> None:
    """Run the full interactive app — setup, collect/classify, and a live dashboard, all in the browser."""
    import threading

    import uvicorn

    from .web import app as web_app

    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    console.print(f"[green]Serving on {url}[/green] — Ctrl+C to stop")
    uvicorn.run(web_app, host=host, port=port, log_level="warning")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
