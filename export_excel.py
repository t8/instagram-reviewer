from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, numbers
from openpyxl.utils import get_column_letter

from checkpoint import CheckpointDB


def export_to_excel(db: CheckpointDB, output_path: str | Path, include_pending: bool = False):
    """Export follower data to an Excel spreadsheet sorted by follower count."""
    if include_pending:
        followers = db.get_all()
    else:
        followers = db.get_all_completed()

    if not followers:
        print("  No followers to export.")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "Followers"

    # Column definitions
    columns = [
        ("Username", 25),
        ("Follower Count", 16),
        ("Following Count", 16),
        ("Full Name", 25),
        ("Verified", 10),
        ("Private", 10),
        ("Followed At", 20),
        ("Lookup Source", 15),
        ("Lookup Status", 15),
    ]

    # Header row
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

    for col_idx, (name, width) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # Data rows
    for row_idx, f in enumerate(followers, 2):
        followed_at_str = ""
        if f.followed_at:
            try:
                followed_at_str = datetime.fromtimestamp(f.followed_at).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except (OSError, ValueError):
                followed_at_str = str(f.followed_at)

        ws.cell(row=row_idx, column=1, value=f.username)

        count_cell = ws.cell(row=row_idx, column=2, value=f.follower_count)
        count_cell.number_format = "#,##0"

        following_cell = ws.cell(row=row_idx, column=3, value=f.following_count)
        following_cell.number_format = "#,##0"

        ws.cell(row=row_idx, column=4, value=f.full_name)
        ws.cell(row=row_idx, column=5, value="Yes" if f.is_verified else ("No" if f.is_verified is not None else ""))
        ws.cell(row=row_idx, column=6, value="Yes" if f.is_private else ("No" if f.is_private is not None else ""))
        ws.cell(row=row_idx, column=7, value=followed_at_str)
        ws.cell(row=row_idx, column=8, value=f.lookup_source or "")
        ws.cell(row=row_idx, column=9, value=f.lookup_status.value)

    # Freeze header row
    ws.freeze_panes = "A2"

    # Auto-filter
    ws.auto_filter.ref = ws.dimensions

    output_path = Path(output_path)
    wb.save(str(output_path))
    print(f"  Exported {len(followers)} followers to {output_path}")
    print(f"  Sorted by follower count (descending)")
