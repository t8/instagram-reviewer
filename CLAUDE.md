# Instagram Follower Analyzer - Agent Context

## What this project does

CLI tool that builds an Excel spreadsheet of Instagram followers sorted by follower count. Designed for Business/Creator accounts with 10k+ followers. Uses a three-phase approach: parse an Instagram data export for the username list, look up follower counts via the Graph API (safe/official), then fill in the rest via Instaloader (rate-limited scraping).

## Architecture

**Two-source hybrid lookup with checkpoint-based resume:**

- `main.py` - Click CLI with commands: `parse`, `lookup`, `login`, `status`, `export`
- `config.py` - Dataclass config loaded from `.env`, with ultra-conservative rate limit defaults
- `models.py` - `Follower` dataclass and `LookupStatus` enum (PENDING/SUCCESS/FAILED/RATE_LIMITED)
- `checkpoint.py` - SQLite DB for progress tracking. All writes are atomic. Enables stop/resume.
- `rate_limiter.py` - Rolling window rate limiter with jitter, hourly/daily/session caps, long pauses, exponential backoff. Accepts a `log_fn` callback for tqdm compatibility.
- `parse_export.py` - Parses Instagram's JSON data export (`connections/followers_and_following/followers_*.json`)
- `lookup_graph_api.py` - Meta Graph API `business_discovery` endpoint. Only works for public/business accounts. Failures are left as PENDING for Instaloader to retry.
- `lookup_instaloader.py` - `Profile.from_username()` lookups. Has abort triggers for login challenges, checkpoint challenges, and suspicious HTTP errors. Never auto-re-logins.
- `export_excel.py` - openpyxl export sorted by follower count descending

## Key design decisions

- **Safety is the top priority.** The Instaloader phase uses 30-90s delays, 40/hr cap, 150/session cap, 400/day cap. This makes it slow (~20 days for 10k) but eliminates ban risk. Do not weaken these defaults.
- **Graph API failures stay PENDING**, not FAILED -- so Instaloader gets a chance to look them up. Only `ProfileNotExistsException` is permanently FAILED.
- **Immediate abort** on `LoginRequiredException`, checkpoint/challenge detection, or HTTP 400/403. The user must manually resolve and re-login.
- **Session cookie reuse** -- Instaloader authenticates once via `main.py login`, session is saved to `data/`. No auto-re-login during lookups.
- **tqdm progress bars** in both lookup modules. Rate limiter uses `log_fn=pbar.write` so status messages don't corrupt the progress bar.
- **All paths use `pathlib.Path`** for cross-platform compatibility (dev on macOS, deploy on Ubuntu).

## Data flow

```
Instagram JSON export
        |
    parse_export.py --> checkpoint.db (all usernames as PENDING)
        |
    lookup_graph_api.py --> checkpoint.db (SUCCESS or stays PENDING)
        |
    lookup_instaloader.py --> checkpoint.db (SUCCESS/FAILED/RATE_LIMITED)
        |
    export_excel.py --> followers.xlsx
```

## Runtime data

All runtime data lives in `data/` (gitignored):
- `data/checkpoint.db` - SQLite database with the `followers` table
- `data/session-<username>` - Instaloader session cookie file

## Dependencies

instaloader, openpyxl, requests, click, python-dotenv, tqdm. All pure Python. Python 3.10+.

## Common tasks

- **Adding a new data field**: Add to `Follower` dataclass in `models.py`, add column to `checkpoint.py` schema (with migration for existing DBs), populate in both lookup modules, add column in `export_excel.py`.
- **Adjusting rate limits**: Defaults are in `config.py` Config dataclass. Users override via `.env`. Do not lower the safety margins without explicit instruction.
- **Adding a new lookup source**: Follow the pattern of `lookup_graph_api.py` -- take `Config` + `CheckpointDB`, create a `RateLimiter`, iterate `get_pending()` batches, call `update_result()` per follower.

## Testing

No test framework is set up. Verify changes by running:
```bash
python -c "import ast; [ast.parse(open(f).read()) for f in ['config.py','models.py','checkpoint.py','rate_limiter.py','parse_export.py','lookup_graph_api.py','lookup_instaloader.py','export_excel.py','main.py']]"
python main.py --help
python main.py status
```

For end-to-end testing, create a temp directory with mock Instagram export JSON (list of `{string_list_data: [{value: username, timestamp: int}]}`) and run `parse` then manually simulate lookups via the checkpoint DB.
