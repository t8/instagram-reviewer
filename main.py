import click

from config import load_config
from checkpoint import CheckpointDB


@click.group()
def cli():
    """Instagram Follower Analyzer — sort your followers by their follower count."""
    pass


@cli.command()
@click.option(
    "--export-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Path to extracted Instagram data export directory",
)
def parse(export_dir):
    """Parse Instagram data export to import follower list."""
    from parse_export import parse_instagram_export

    config = load_config()

    print(f"Parsing export from: {export_dir}")
    followers = parse_instagram_export(export_dir)
    print(f"  Found {len(followers)} unique followers in export")

    with CheckpointDB(config.checkpoint_db) as db:
        imported, skipped = db.import_from_export(followers)
        print(f"  Imported {imported} new followers, {skipped} already in database")
        stats = db.get_stats()
        print(f"  Total in database: {stats['total']}")


@cli.command()
@click.option(
    "--mode",
    type=click.Choice(["graph-api", "instaloader", "auto"]),
    default="auto",
    help="Lookup mode: graph-api, instaloader, or auto (both in sequence)",
)
def lookup(mode):
    """Look up follower counts using Graph API and/or Instaloader."""
    from lookup_graph_api import lookup_graph_api
    from lookup_instaloader import lookup_instaloader

    config = load_config()

    with CheckpointDB(config.checkpoint_db) as db:
        stats = db.get_stats()
        if stats["total"] == 0:
            print("No followers in database. Run 'parse' first.")
            return

        pending = stats["pending"] + stats["rate_limited"]
        print(f"Starting lookup — {pending} followers pending out of {stats['total']} total")

        if mode in ("graph-api", "auto"):
            if config.graph_api_token and config.graph_api_user_id:
                print("\n--- Phase 2a: Graph API lookups ---")
                result = lookup_graph_api(config, db)
                print(f"  Graph API done: {result}")
                stats = db.get_stats()
                pending = stats["pending"] + stats["rate_limited"]
                print(f"  Remaining pending: {pending}")
            elif mode == "graph-api":
                print("Error: GRAPH_API_TOKEN and GRAPH_API_USER_ID must be set in .env")
                return
            else:
                print("  Skipping Graph API (no credentials in .env)")

        if mode in ("instaloader", "auto"):
            stats = db.get_stats()
            pending = stats["pending"] + stats["rate_limited"]
            if pending == 0:
                print("\n  All followers already looked up!")
                return

            print(f"\n--- Phase 2b: Instaloader lookups ({pending} remaining) ---")
            print("  This will be slow by design (safety rate limits).")
            print("  Press Ctrl+C to stop — progress is saved automatically.\n")
            result = lookup_instaloader(config, db)
            print(f"\n  Instaloader done: {result}")

        # Final stats
        stats = db.get_stats()
        _print_stats(stats)


@cli.command()
def status():
    """Show current progress statistics."""
    config = load_config()

    if not config.checkpoint_db.exists():
        print("No checkpoint database found. Run 'parse' first.")
        return

    with CheckpointDB(config.checkpoint_db) as db:
        stats = db.get_stats()
        _print_stats(stats)


@cli.command()
@click.option(
    "--output",
    default="followers.xlsx",
    help="Output Excel file path",
)
@click.option(
    "--include-pending",
    is_flag=True,
    default=False,
    help="Include followers whose lookup hasn't completed yet",
)
def export(output, include_pending):
    """Export results to an Excel spreadsheet."""
    from export_excel import export_to_excel

    config = load_config()

    if not config.checkpoint_db.exists():
        print("No checkpoint database found. Run 'parse' first.")
        return

    with CheckpointDB(config.checkpoint_db) as db:
        stats = db.get_stats()
        print(f"Exporting — {stats['success']} completed lookups out of {stats['total']} total")
        export_to_excel(db, output, include_pending=include_pending)


@cli.command()
def login():
    """Interactively log into Instagram and save session for Instaloader."""
    from lookup_instaloader import login_and_save_session

    config = load_config()

    if not config.instagram_username:
        print("Error: INSTAGRAM_USERNAME must be set in .env")
        return

    print(f"Logging in as @{config.instagram_username}...")
    print("You may be prompted for your password and/or 2FA code.\n")
    login_and_save_session(config)


def _print_stats(stats):
    total = stats["total"]
    if total == 0:
        print("\nNo followers in database.")
        return

    success = stats["success"]
    pending = stats["pending"]
    graph_api_miss = stats["graph_api_miss"]
    failed = stats["failed"]
    rate_limited = stats["rate_limited"]
    pct = (success / total * 100) if total > 0 else 0

    print(f"\n--- Follower Lookup Progress ---")
    print(f"  Total followers:  {total:,}")
    print(f"  Completed:        {success:,} ({pct:.1f}%)")
    print(f"  Skipped (personal): {graph_api_miss:,}")
    print(f"  Pending:          {pending:,}")
    print(f"  Rate limited:     {rate_limited:,}")
    print(f"  Failed:           {failed:,}")

    by_source = stats.get("by_source", {})
    if by_source:
        print(f"\n  By source:")
        for source, count in sorted(by_source.items()):
            print(f"    {source}: {count:,}")

    remaining = pending + rate_limited
    if remaining > 0:
        est_days = remaining / 320  # ~320/day at conservative rates
        print(f"\n  Estimated time remaining: ~{est_days:.0f} days at conservative rates")


if __name__ == "__main__":
    cli()
