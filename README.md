# Instagram Follower Analyzer

CLI tool that produces an Excel spreadsheet of all your Instagram followers sorted by their follower count (descending). Designed for Business/Creator accounts with 10,000+ followers.

Uses a three-phase approach to avoid getting flagged:

1. **Parse** - Instagram's official data export (JSON) for the follower list (zero risk)
2. **Graph API** - `business_discovery` lookups for public/business accounts (~180/hour, zero risk)
3. **Instaloader** - Profile scraping for remaining followers with ultra-conservative rate limits (~40/hour)

SQLite checkpoint database enables stop/resume across sessions. The Instaloader phase is intentionally slow (~20 days for 10k followers) and runs unattended.

## Prerequisites

- Python 3.10+
- An Instagram Business or Creator account
- Your Instagram data export (JSON format)
- (Optional) A Meta Developer App for Graph API access

## Setup

```bash
# Clone and set up virtual environment
git clone <repo-url> && cd instagram-reviewer
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create your .env file from the template
cp .env.example .env
```

Edit `.env` with your credentials:

```
INSTAGRAM_USERNAME=your_username
GRAPH_API_TOKEN=your_long_lived_token        # optional, for Graph API phase
GRAPH_API_USER_ID=your_instagram_user_id     # optional, for Graph API phase
```

### Getting your Instagram data export

1. Go to Instagram Settings > Your Activity > Download Your Information
2. Select **JSON** format (not HTML)
3. Request the download and wait for the email (can take up to 48 hours)
4. Download and extract the zip file

### Getting Graph API credentials (optional)

1. Create an app at [developers.facebook.com](https://developers.facebook.com)
2. Add the Instagram Graph API product
3. Generate a long-lived access token
4. Find your Instagram Business User ID via the API Explorer

## Usage

### 1. Import your follower list

```bash
python main.py parse --export-dir ~/Downloads/instagram-export/
```

This reads the JSON export and imports all follower usernames into the local SQLite database.

### 2. Log into Instagram (required for Instaloader)

```bash
python main.py login
```

You'll be prompted for your password and possibly a 2FA code. The session cookie is saved to `data/` for reuse. On a server, you can log in locally and copy the session file over.

### 3. Look up follower counts

```bash
# Auto mode: Graph API first, then Instaloader for the rest (recommended)
python main.py lookup --mode auto

# Graph API only (safe, fast, but only works for public/business accounts)
python main.py lookup --mode graph-api

# Instaloader only (works for all accounts, but slow by design)
python main.py lookup --mode instaloader
```

The lookup shows a live progress bar with success/fail counts and rate limit budget. Press `Ctrl+C` at any time to stop -- progress is saved automatically and will resume where it left off.

### 4. Check progress

```bash
python main.py status
```

Shows total followers, completed lookups, pending, failed, and breakdown by source.

### 5. Export to Excel

```bash
python main.py export --output followers.xlsx

# Include followers whose lookup hasn't completed yet
python main.py export --output followers.xlsx --include-pending
```

The spreadsheet is sorted by follower count (descending) with columns: Username, Follower Count, Following Count, Full Name, Verified, Private, Followed At, Lookup Source, Lookup Status.

## Rate Limits

Instaloader defaults are intentionally ultra-conservative to protect your account:

| Setting | Default | Description |
|---|---|---|
| Request delay | 30-90s random | Time between each profile lookup |
| Hourly cap | 40/hour | Max lookups per rolling hour |
| Session cap | 150/session | Lookups before mandatory 2-hour rest |
| Daily cap | 400/day | Max lookups per 24 hours |
| Rate limit cooldown | 30 min | Initial backoff on 429, doubles each time |
| Long pause | 2-5 min every 10-20 requests | Mimics human browsing patterns |

All settings are overridable via `.env`. See `.env.example` for the full list.

**Estimated timeline for ~10,000 followers:** Graph API resolves ~30-40% instantly, then Instaloader handles the rest at ~320/day = ~20 days unattended.

## Project Structure

```
main.py                # CLI entry point (click-based commands)
config.py              # Configuration dataclass + .env loading
models.py              # Follower dataclass + LookupStatus enum
checkpoint.py          # SQLite-based progress tracking
rate_limiter.py        # Rate limiter with jitter + backoff
parse_export.py        # Parse Instagram data export JSON
lookup_graph_api.py    # Graph API business_discovery lookups
lookup_instaloader.py  # Instaloader profile lookups
export_excel.py        # Excel spreadsheet generation
requirements.txt       # Dependencies
.env.example           # Template for credentials
data/                  # Runtime data directory (gitignored)
  checkpoint.db        # SQLite progress database
  session-<username>   # Instaloader session cookie
```

## Safety

The tool immediately aborts on:
- Login challenges or checkpoint challenges from Instagram
- HTTP 400/403 responses
- Session expiration

On abort it prints clear instructions for what to do next. The checkpoint DB means no progress is lost.
