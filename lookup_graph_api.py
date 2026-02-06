import requests
from tqdm import tqdm

from checkpoint import CheckpointDB
from config import Config
from models import Follower, LookupStatus
from rate_limiter import RateLimiter


GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def lookup_graph_api(config: Config, db: CheckpointDB) -> dict:
    """Look up follower info via Instagram Graph API business_discovery.

    Returns stats dict with counts of successful/failed/remaining lookups.
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

    limiter = RateLimiter(
        min_delay=config.graph_api_min_delay,
        max_delay=config.graph_api_max_delay,
        hourly_cap=config.graph_api_hourly_cap,
        session_cap=999999,       # No session cap for Graph API
        session_rest=0,
        daily_cap=999999,         # No daily cap for Graph API
        rate_limit_cooldown=60,   # 1 min cooldown on rate limit
        long_pause_min=0,
        long_pause_max=0,
        long_pause_interval_min=999999,
        long_pause_interval_max=999999,
        log_fn=pbar.write,
    )

    success_count = 0
    fail_count = 0
    processed = 0

    while True:
        batch = db.get_pending(batch_size=50, max_retries=config.max_retries)
        if not batch:
            break

        for follower in batch:
            try:
                limiter.wait_before_request()
            except StopIteration as e:
                pbar.write(f"  {e}")
                break

            result = _lookup_single(config, follower)
            db.update_result(result)
            limiter.record_request()
            processed += 1

            if result.lookup_status == LookupStatus.SUCCESS:
                success_count += 1
                pbar.set_postfix_str(
                    f"ok={success_count} skip={fail_count} | {result.username}: {result.follower_count:,}"
                )
            else:
                fail_count += 1
                # Mark as PENDING so Instaloader can try later (not FAILED)
                result.lookup_status = LookupStatus.PENDING
                db.update_result(result)
                pbar.set_postfix_str(f"ok={success_count} skip={fail_count}")

            pbar.update(1)
        else:
            continue
        break

    pbar.close()

    return {
        "processed": processed,
        "success": success_count,
        "failed_will_retry": fail_count,
    }


def _lookup_single(config: Config, follower: Follower) -> Follower:
    """Look up a single profile via business_discovery."""
    fields = (
        "business_discovery.username({username})"
        "{{followers_count,follows_count,media_count,name,biography}}"
    ).format(username=follower.username)

    url = f"{GRAPH_API_BASE}/{config.graph_api_user_id}"
    params = {
        "fields": fields,
        "access_token": config.graph_api_token,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)

        if resp.status_code == 200:
            data = resp.json().get("business_discovery", {})
            follower.follower_count = data.get("followers_count")
            follower.following_count = data.get("follows_count")
            follower.full_name = data.get("name")
            follower.is_verified = None  # Not available via business_discovery
            follower.is_private = False  # business_discovery only works for public
            follower.lookup_status = LookupStatus.SUCCESS
            follower.lookup_source = "graph_api"
            follower.error_message = None
            return follower

        # API error — likely private account or not a business account
        error_data = resp.json().get("error", {})
        error_msg = error_data.get("message", resp.text[:200])

        follower.lookup_status = LookupStatus.PENDING  # Let Instaloader try
        follower.error_message = f"Graph API: {error_msg}"
        follower.retry_count += 1
        return follower

    except requests.RequestException as e:
        follower.lookup_status = LookupStatus.PENDING
        follower.error_message = f"Graph API request error: {e}"
        follower.retry_count += 1
        return follower
