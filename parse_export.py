import json
from pathlib import Path

from models import Follower


def parse_instagram_export(export_dir: str | Path) -> list[Follower]:
    """Parse Instagram's JSON data export to extract follower usernames.

    The export contains files like:
      connections/followers_and_following/followers_1.json
      connections/followers_and_following/followers_2.json
      ...

    Each file has a list of dicts with 'string_list_data' containing
    the username (value) and timestamp.
    """
    export_path = Path(export_dir)
    if not export_path.is_dir():
        raise FileNotFoundError(f"Export directory not found: {export_path}")

    # Glob for follower JSON files
    follower_files = sorted(
        export_path.glob("**/followers_*.json")
    )

    if not follower_files:
        # Try alternate path patterns
        follower_files = sorted(
            export_path.glob("**/followers.json")
        )

    if not follower_files:
        raise FileNotFoundError(
            f"No follower JSON files found in {export_path}. "
            "Expected files like 'connections/followers_and_following/followers_1.json'. "
            "Make sure you selected JSON format when requesting your data export."
        )

    seen_usernames: set[str] = set()
    followers: list[Follower] = []

    for file_path in follower_files:
        print(f"  Parsing {file_path.name}...")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Handle both list format and dict-with-key format
        entries = data if isinstance(data, list) else data.get("relationships_followers", data.get("followers", []))
        if isinstance(entries, dict):
            # Some exports wrap in a dict; try to find the list
            for key, val in entries.items():
                if isinstance(val, list):
                    entries = val
                    break

        for entry in entries:
            string_list = entry.get("string_list_data", [])
            if not string_list:
                continue

            item = string_list[0]
            username = item.get("value", "").strip().lower()
            timestamp = item.get("timestamp")

            if not username or username in seen_usernames:
                continue

            seen_usernames.add(username)
            followers.append(
                Follower(
                    username=username,
                    followed_at=timestamp,
                )
            )

    return followers
