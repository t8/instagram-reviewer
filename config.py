from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv
import os


@dataclass
class Config:
    # Paths (relative to project root by default)
    project_root: Path = field(default_factory=lambda: Path(__file__).parent)
    data_dir: Path = field(init=False)
    checkpoint_db: Path = field(init=False)
    session_dir: Path = field(init=False)

    # Instagram credentials
    instagram_username: str = ""

    # Graph API credentials
    graph_api_token: str = ""
    graph_api_user_id: str = ""

    # Instaloader rate limits (ultra-conservative)
    instaloader_min_delay: float = 30.0   # seconds between requests
    instaloader_max_delay: float = 90.0   # seconds between requests
    instaloader_hourly_cap: int = 40      # max requests per hour
    instaloader_session_cap: int = 150    # max requests before mandatory rest
    instaloader_session_rest: float = 7200.0  # 2 hours rest between sessions
    instaloader_daily_cap: int = 400      # max requests per 24 hours
    instaloader_rate_limit_cooldown: float = 1800.0  # 30 min on 429
    instaloader_long_pause_min: float = 120.0  # 2 min occasional long pause
    instaloader_long_pause_max: float = 300.0  # 5 min occasional long pause
    instaloader_long_pause_interval_min: int = 10  # every 10-20 requests
    instaloader_long_pause_interval_max: int = 20

    # Graph API rate limits (official API — safe to run near the limit)
    graph_api_hourly_cap: int = 200  # Instagram Graph API limit
    graph_api_min_delay: float = 17.0   # spread evenly: 3600/200 = 18s avg
    graph_api_max_delay: float = 21.0

    # Retry settings
    max_retries: int = 3

    def __post_init__(self):
        self.data_dir = self.project_root / "data"
        self.checkpoint_db = self.data_dir / "checkpoint.db"
        self.session_dir = self.data_dir

    def ensure_data_dir(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    load_dotenv()

    config = Config(
        instagram_username=os.getenv("INSTAGRAM_USERNAME", ""),
        graph_api_token=os.getenv("GRAPH_API_TOKEN", ""),
        graph_api_user_id=os.getenv("GRAPH_API_USER_ID", ""),
        instaloader_min_delay=float(os.getenv("INSTALOADER_MIN_DELAY", "30")),
        instaloader_max_delay=float(os.getenv("INSTALOADER_MAX_DELAY", "90")),
        instaloader_hourly_cap=int(os.getenv("INSTALOADER_HOURLY_CAP", "40")),
        instaloader_session_cap=int(os.getenv("INSTALOADER_SESSION_CAP", "150")),
        instaloader_session_rest=float(os.getenv("INSTALOADER_SESSION_REST", "7200")),
        instaloader_daily_cap=int(os.getenv("INSTALOADER_DAILY_CAP", "400")),
        graph_api_hourly_cap=int(os.getenv("GRAPH_API_HOURLY_CAP", "200")),
    )
    config.ensure_data_dir()
    return config
