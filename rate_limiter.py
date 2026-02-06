import random
import time
from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    def __init__(
        self,
        min_delay: float = 30.0,
        max_delay: float = 90.0,
        hourly_cap: int = 40,
        session_cap: int = 150,
        session_rest: float = 7200.0,
        daily_cap: int = 400,
        rate_limit_cooldown: float = 1800.0,
        long_pause_min: float = 120.0,
        long_pause_max: float = 300.0,
        long_pause_interval_min: int = 10,
        long_pause_interval_max: int = 20,
        log_fn=None,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.hourly_cap = hourly_cap
        self.session_cap = session_cap
        self.session_rest = session_rest
        self.daily_cap = daily_cap
        self.rate_limit_cooldown = rate_limit_cooldown
        self.long_pause_min = long_pause_min
        self.long_pause_max = long_pause_max
        self.long_pause_interval_min = long_pause_interval_min
        self.long_pause_interval_max = long_pause_interval_max
        self._log = log_fn or print

        # Rolling window for hourly tracking
        self._hourly_timestamps: deque[float] = deque()
        # Daily tracking
        self._daily_timestamps: deque[float] = deque()
        # Session counter
        self._session_count = 0
        # Requests since last long pause
        self._since_long_pause = 0
        self._next_long_pause_at = random.randint(
            long_pause_interval_min, long_pause_interval_max
        )
        # Backoff state
        self._consecutive_rate_limits = 0

    def _prune_old(self, timestamps: deque, window_seconds: float):
        cutoff = time.monotonic() - window_seconds
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

    def _prune_daily(self):
        cutoff = time.monotonic() - 86400
        while self._daily_timestamps and self._daily_timestamps[0] < cutoff:
            self._daily_timestamps.popleft()

    def check_daily_cap(self) -> bool:
        self._prune_daily()
        return len(self._daily_timestamps) >= self.daily_cap

    def check_session_cap(self) -> bool:
        return self._session_count >= self.session_cap

    def check_hourly_cap(self) -> bool:
        self._prune_old(self._hourly_timestamps, 3600)
        return len(self._hourly_timestamps) >= self.hourly_cap

    def wait_before_request(self) -> str:
        """Wait the appropriate amount of time before the next request.

        Returns a description of what wait was performed, or raises
        StopIteration if the daily or session cap has been reached.
        """
        # Check daily cap
        if self.check_daily_cap():
            self._prune_daily()
            if self._daily_timestamps:
                resume_at = datetime.now() + timedelta(
                    seconds=86400 - (time.monotonic() - self._daily_timestamps[0])
                )
                raise StopIteration(
                    f"Daily cap of {self.daily_cap} reached. "
                    f"Resume after {resume_at.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            raise StopIteration(f"Daily cap of {self.daily_cap} reached.")

        # Check session cap
        if self.check_session_cap():
            rest_minutes = self.session_rest / 60
            self._log(
                f"  Session cap of {self.session_cap} reached. "
                f"Resting for {rest_minutes:.0f} minutes..."
            )
            time.sleep(self.session_rest)
            self._session_count = 0
            return f"session rest ({rest_minutes:.0f}m)"

        # Check hourly cap — wait until the oldest request falls out of the window
        if self.check_hourly_cap():
            self._prune_old(self._hourly_timestamps, 3600)
            if self._hourly_timestamps:
                wait_time = 3600 - (time.monotonic() - self._hourly_timestamps[0])
                if wait_time > 0:
                    wait_minutes = wait_time / 60
                    self._log(
                        f"  Hourly cap of {self.hourly_cap} reached. "
                        f"Waiting {wait_minutes:.1f} minutes..."
                    )
                    time.sleep(wait_time)
                    return f"hourly cap wait ({wait_minutes:.1f}m)"

        # Occasional long pause
        if self._since_long_pause >= self._next_long_pause_at:
            pause = random.uniform(self.long_pause_min, self.long_pause_max)
            self._since_long_pause = 0
            self._next_long_pause_at = random.randint(
                self.long_pause_interval_min, self.long_pause_interval_max
            )
            self._log(f"  Long pause: {pause:.0f}s...")
            time.sleep(pause)
            return f"long pause ({pause:.0f}s)"

        # Standard jitter delay
        delay = random.uniform(self.min_delay, self.max_delay)
        self._log(f"  Waiting {delay:.0f}s...")
        time.sleep(delay)
        return f"delay ({delay:.0f}s)"

    def record_request(self):
        now = time.monotonic()
        self._hourly_timestamps.append(now)
        self._daily_timestamps.append(now)
        self._session_count += 1
        self._since_long_pause += 1
        self._consecutive_rate_limits = 0

    def handle_rate_limit(self):
        """Handle a 429 response with exponential backoff."""
        self._consecutive_rate_limits += 1
        backoff = self.rate_limit_cooldown * (2 ** (self._consecutive_rate_limits - 1))
        backoff_minutes = backoff / 60
        self._log(
            f"  Rate limited! Backing off for {backoff_minutes:.0f} minutes "
            f"(attempt #{self._consecutive_rate_limits})..."
        )
        time.sleep(backoff)

    def get_stats(self) -> dict:
        self._prune_old(self._hourly_timestamps, 3600)
        self._prune_daily()
        return {
            "hourly_count": len(self._hourly_timestamps),
            "hourly_cap": self.hourly_cap,
            "daily_count": len(self._daily_timestamps),
            "daily_cap": self.daily_cap,
            "session_count": self._session_count,
            "session_cap": self.session_cap,
        }
