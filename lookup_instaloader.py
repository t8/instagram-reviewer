import instaloader
from pathlib import Path
from tqdm import tqdm

from checkpoint import CheckpointDB
from config import Config
from models import Follower, LookupStatus
from rate_limiter import RateLimiter


class InstaloaderAbort(Exception):
    """Raised when we must immediately stop all lookups."""
    pass


def create_instaloader_context(config: Config) -> instaloader.Instaloader:
    """Create an Instaloader instance with a saved session."""
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    session_file = config.session_dir / f"session-{config.instagram_username}"
    if session_file.exists():
        L.load_session_from_file(config.instagram_username, str(session_file))
        print(f"  Loaded session for @{config.instagram_username}")
    else:
        raise FileNotFoundError(
            f"No session file found at {session_file}. "
            f"Run 'python main.py login' first to create a session."
        )

    return L


def login_and_save_session(config: Config):
    """Interactive login — saves session file for future use."""
    if not config.instagram_username:
        print("Error: INSTAGRAM_USERNAME must be set in .env")
        return

    config.ensure_data_dir()
    L = instaloader.Instaloader(
        quiet=False,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
    )

    try:
        L.interactive_login(config.instagram_username)
        session_file = config.session_dir / f"session-{config.instagram_username}"
        L.save_session_to_file(str(session_file))
        print(f"  Session saved to {session_file}")
        print("  You can copy this file to your server for headless operation.")
    except Exception as e:
        print(f"  Login failed: {e}")


def lookup_instaloader(config: Config, db: CheckpointDB) -> dict:
    """Look up follower info via Instaloader profile scraping."""
    try:
        L = create_instaloader_context(config)
    except FileNotFoundError as e:
        print(f"  {e}")
        return {"error": "no session"}

    stats = db.get_stats()
    total_pending = stats["pending"] + stats["rate_limited"]

    pbar = tqdm(
        total=total_pending,
        desc="Instaloader",
        unit="profile",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {postfix}",
    )

    limiter = RateLimiter(
        min_delay=config.instaloader_min_delay,
        max_delay=config.instaloader_max_delay,
        hourly_cap=config.instaloader_hourly_cap,
        session_cap=config.instaloader_session_cap,
        session_rest=config.instaloader_session_rest,
        daily_cap=config.instaloader_daily_cap,
        rate_limit_cooldown=config.instaloader_rate_limit_cooldown,
        long_pause_min=config.instaloader_long_pause_min,
        long_pause_max=config.instaloader_long_pause_max,
        long_pause_interval_min=config.instaloader_long_pause_interval_min,
        long_pause_interval_max=config.instaloader_long_pause_interval_max,
        log_fn=pbar.write,
    )

    success_count = 0
    fail_count = 0
    processed = 0

    def _update_postfix(last_msg=""):
        limiter_stats = limiter.get_stats()
        parts = [
            f"ok={success_count}",
            f"fail={fail_count}",
            f"hr={limiter_stats['hourly_count']}/{limiter_stats['hourly_cap']}",
            f"day={limiter_stats['daily_count']}/{limiter_stats['daily_cap']}",
            f"sess={limiter_stats['session_count']}/{limiter_stats['session_cap']}",
        ]
        if last_msg:
            parts.append(last_msg)
        pbar.set_postfix_str(" ".join(parts))

    try:
        while True:
            batch = db.get_pending(batch_size=50, max_retries=config.max_retries)
            if not batch:
                break

            for follower in batch:
                try:
                    limiter.wait_before_request()
                except StopIteration as e:
                    pbar.write(f"  Stopping: {e}")
                    pbar.close()
                    return _make_stats(processed, success_count, fail_count, "daily_cap")

                try:
                    result = _lookup_single(L, follower)
                except InstaloaderAbort as e:
                    pbar.write(f"\n  ABORT: {e}")
                    pbar.close()
                    return _make_stats(processed, success_count, fail_count, str(e))

                db.update_result(result)
                limiter.record_request()
                processed += 1
                pbar.update(1)

                if result.lookup_status == LookupStatus.SUCCESS:
                    success_count += 1
                    _update_postfix(f"| {result.username}: {result.follower_count:,}")
                elif result.lookup_status == LookupStatus.RATE_LIMITED:
                    _update_postfix(f"| {result.username}: rate limited")
                    limiter.handle_rate_limit()
                else:
                    fail_count += 1
                    _update_postfix(f"| {result.username}: failed")

    except KeyboardInterrupt:
        pbar.write("\n  Interrupted by user. Progress has been saved.")

    pbar.close()
    return _make_stats(processed, success_count, fail_count, "completed")


def _lookup_single(L: instaloader.Instaloader, follower: Follower) -> Follower:
    """Look up a single profile. Raises InstaloaderAbort on critical errors."""
    try:
        profile = instaloader.Profile.from_username(L.context, follower.username)
        follower.follower_count = profile.followers
        follower.following_count = profile.followees
        follower.full_name = profile.full_name
        follower.is_verified = profile.is_verified
        follower.is_private = profile.is_private
        follower.lookup_status = LookupStatus.SUCCESS
        follower.lookup_source = "instaloader"
        follower.error_message = None
        return follower

    except instaloader.exceptions.ProfileNotExistsException:
        follower.lookup_status = LookupStatus.FAILED
        follower.error_message = "Profile does not exist"
        follower.retry_count = 999  # Don't retry
        return follower

    except instaloader.exceptions.LoginRequiredException as e:
        raise InstaloaderAbort(
            f"Session expired (LoginRequired). "
            f"Run 'python main.py login' to re-authenticate, "
            f"then resume with 'python main.py lookup --mode instaloader'"
        ) from e

    except instaloader.exceptions.TooManyRequestsException as e:
        follower.lookup_status = LookupStatus.RATE_LIMITED
        follower.error_message = f"429 Too Many Requests: {e}"
        return follower

    except instaloader.exceptions.ConnectionException as e:
        error_str = str(e).lower()
        if "checkpoint" in error_str or "challenge" in error_str:
            raise InstaloaderAbort(
                f"Instagram challenge/checkpoint detected: {e}. "
                f"Log into Instagram manually, complete the challenge, "
                f"then run 'python main.py login' and resume."
            ) from e
        if "400" in str(e) or "403" in str(e):
            raise InstaloaderAbort(
                f"Suspicious HTTP error ({e}). Stopping to protect account. "
                f"Wait several hours, then resume."
            ) from e
        # Transient connection error — mark for retry
        follower.lookup_status = LookupStatus.RATE_LIMITED
        follower.error_message = f"Connection error: {e}"
        follower.retry_count += 1
        return follower

    except Exception as e:
        follower.lookup_status = LookupStatus.FAILED
        follower.error_message = f"Unexpected error: {e}"
        follower.retry_count += 1
        return follower


def _make_stats(processed, success, failed, stop_reason):
    return {
        "processed": processed,
        "success": success,
        "failed": failed,
        "stop_reason": stop_reason,
    }
