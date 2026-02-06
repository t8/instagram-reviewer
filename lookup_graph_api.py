import json
import time
import requests
from tqdm import tqdm

from checkpoint import CheckpointDB
from config import Config
from models import Follower, LookupStatus


GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
BATCH_SIZE = 50  # Facebook batch API maximum


def lookup_graph_api(config: Config, db: CheckpointDB) -> dict:
    """Look up follower info via Instagram Graph API business_discovery.

    Uses the Facebook Batch API (50 lookups per HTTP request) and
    dynamic throttling based on X-App-Usage headers.
    """
    if not config.graph_api_token or not config.graph_api_user_id:
        print("Error: GRAPH_API_TOKEN and GRAPH_API_USER_ID must be set in .env")
        return {"error": "missing credentials"}

    stats = db.get_stats()
    total_pending = stats["pending"] + stats["rate_limited"]

    pbar = tqdm(
        total=total_pending,
        desc="Graph API",
        unit="profile",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {postfix}",
    )

    success_count = 0
    skip_count = 0
    rate_limit_count = 0
    processed = 0
    consecutive_rate_limits = 0

    while True:
        batch = db.get_pending(batch_size=BATCH_SIZE, max_retries=config.max_retries)
        if not batch:
            break

        results, usage = _batch_lookup(config, batch)

        batch_had_rate_limit = False
        last_success_msg = ""
        for follower in results:
            db.update_result(follower)
            processed += 1

            if follower.lookup_status == LookupStatus.SUCCESS:
                success_count += 1
                last_success_msg = (
                    f" | {follower.username}: {follower.follower_count:,}"
                )
            elif follower.lookup_status == LookupStatus.RATE_LIMITED:
                rate_limit_count += 1
                batch_had_rate_limit = True
            else:
                skip_count += 1

        pbar.update(len(results))
        call_pct = usage.get("call_count", "?")
        pbar.set_postfix_str(
            f"ok={success_count} skip={skip_count} api={call_pct}%{last_success_msg}"
        )

        if batch_had_rate_limit:
            consecutive_rate_limits += 1
            backoff = 120 * (2 ** (consecutive_rate_limits - 1))  # 2m, 4m, 8m...
            pbar.write(
                f"  Rate limited by API — backing off {backoff // 60}m "
                f"(attempt #{consecutive_rate_limits})"
            )
            time.sleep(backoff)
            continue
        else:
            consecutive_rate_limits = 0

        delay = _delay_from_usage(usage)
        if delay > 0:
            pbar.write(f"  API usage: {call_pct}% — waiting {delay}s")
            time.sleep(delay)

    pbar.close()

    return {
        "processed": processed,
        "success": success_count,
        "skipped": skip_count,
        "rate_limited": rate_limit_count,
    }


def _batch_lookup(
    config: Config, followers: list[Follower]
) -> tuple[list[Follower], dict]:
    """Send a batch of lookups in a single HTTP request.

    Returns (updated followers list, usage dict from X-App-Usage header).
    """
    batch_requests = []
    for f in followers:
        fields = (
            f"business_discovery.username({f.username})"
            "{followers_count,follows_count,name}"
        )
        relative_url = f"{config.graph_api_user_id}?fields={fields}"
        batch_requests.append({"method": "GET", "relative_url": relative_url})

    try:
        resp = requests.post(
            f"{GRAPH_API_BASE}/",
            data={
                "access_token": config.graph_api_token,
                "batch": json.dumps(batch_requests),
            },
            timeout=120,
        )
    except requests.RequestException as e:
        for f in followers:
            f.lookup_status = LookupStatus.RATE_LIMITED
            f.error_message = f"Batch request error: {e}"
        return followers, {}

    usage = _parse_usage_header(resp)

    # Outer 429 — entire batch was rate limited
    if resp.status_code == 429:
        for f in followers:
            f.lookup_status = LookupStatus.RATE_LIMITED
            f.error_message = "Batch: 429 rate limited"
        return followers, usage

    if resp.status_code != 200:
        for f in followers:
            f.lookup_status = LookupStatus.RATE_LIMITED
            f.error_message = f"Batch: HTTP {resp.status_code}"
        return followers, usage

    # Parse individual sub-responses
    sub_responses = resp.json()
    for follower, sub_resp in zip(followers, sub_responses):
        _parse_sub_response(follower, sub_resp)

    return followers, usage


def _parse_sub_response(follower: Follower, sub_resp: dict):
    """Parse a single sub-response from the batch."""
    code = sub_resp.get("code", 0)
    try:
        body = json.loads(sub_resp.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        body = {}

    if code == 200:
        data = body.get("business_discovery", {})
        follower.follower_count = data.get("followers_count")
        follower.following_count = data.get("follows_count")
        follower.full_name = data.get("name")
        follower.is_verified = None
        follower.is_private = False
        follower.lookup_status = LookupStatus.SUCCESS
        follower.lookup_source = "graph_api"
        follower.error_message = None
        return

    if code == 429:
        follower.lookup_status = LookupStatus.RATE_LIMITED
        follower.error_message = "429 rate limited"
        return

    error = body.get("error", {})
    error_code = error.get("code")
    error_msg = error.get("message", str(body)[:200])

    # Facebook error codes 4 and 32 are rate limiting
    if error_code in (4, 32):
        follower.lookup_status = LookupStatus.RATE_LIMITED
        follower.error_message = f"Rate limit: {error_msg}"
        return

    follower.lookup_status = LookupStatus.GRAPH_API_MISS
    follower.error_message = f"Graph API: {error_msg}"


def _parse_usage_header(resp: requests.Response) -> dict:
    """Parse the X-App-Usage header from a Graph API response."""
    header = resp.headers.get("x-app-usage", "")
    if not header:
        return {}
    try:
        return json.loads(header)
    except (json.JSONDecodeError, TypeError):
        return {}


def _delay_from_usage(usage: dict) -> float:
    """Calculate how long to wait based on API usage percentage.

    X-App-Usage.call_count is the percentage of rate limit used (0-100).
    We throttle progressively as we approach the limit.
    """
    call_count = usage.get("call_count", 0)

    if call_count >= 95:
        return 300   # 5 min — almost at limit, let it cool down
    if call_count >= 80:
        return 60    # 1 min
    if call_count >= 60:
        return 20    # 20s
    if call_count >= 40:
        return 5     # 5s
    return 1         # 1s — plenty of headroom, go fast
