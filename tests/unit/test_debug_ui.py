import pandas as pd

from debug_ui.app import (
    get_dockets,
    get_overview_stats,
    get_duplicate_text_stats,
    get_records_per_day,
    get_disk_size_mb,
)


def test_get_dockets():
    # Empty / None df cases
    assert get_dockets(None) == []
    assert get_dockets(pd.DataFrame()) == []

    # Valid docket_id list
    df = pd.DataFrame(
        {"docket_id": ["FDA-2023-N-2177", "FDA-2013-S-0610", "FDA-2023-N-2177", None]}
    )
    assert get_dockets(df) == ["FDA-2013-S-0610", "FDA-2023-N-2177"]


def test_get_disk_size_mb():
    assert get_disk_size_mb("non_existent_path_xyz") == 0.0


def test_get_overview_stats():
    # Construct a test DataFrame representing bronze table comments
    data = {
        "comment_id": ["C1", "C2", "C3", "C3"],  # duplicate comment_id C3
        "docket_id": ["D1", "D1", "D1", "D1"],
        "posted_date": [
            "2026-05-21 12:00:00",
            "2026-05-22 12:00:00",
            None,
            "2026-05-22 13:00:00",
        ],
        "last_modified_date": [
            "2026-05-21 12:00:00",
            "2026-05-22 12:00:00",
            "2026-05-22 12:00:00",
            "2026-05-22 12:00:00",
        ],
        "received_date": [None, None, None, None],
        "has_attachments": [True, False, True, False],
        "comment_text": ["This is text 1", "  This  is   text 1  ", "", None],
    }
    df = pd.DataFrame(data)

    stats = get_overview_stats(df, "D1", "non_existent_path")
    assert stats["total_rows"] == 4
    assert stats["unique_comment_id_count"] == 3
    assert stats["duplicate_comment_id_count"] == 1
    assert stats["attachment_count"] == 2
    assert stats["null_empty_text_count"] == 2  # empty string and None
    assert stats["text_col_found"] == "comment_text"
    assert stats["posted_date_range"][0] is not None
    assert stats["received_date_range"] == (None, None)


def test_get_duplicate_text_stats():
    data = {
        "comment_id": ["C1", "C2", "C3", "C4"],
        "docket_id": ["D1", "D1", "D1", "D1"],
        "comment_text": [
            "Hello World",
            "hello   world",  # normalized duplicate
            "hello world",  # normalized duplicate
            "different text",
        ],
    }
    df = pd.DataFrame(data)

    dup_df = get_duplicate_text_stats(df, "D1", "comment_text")
    assert not dup_df.empty
    assert len(dup_df) == 1  # only one duplicate set
    assert dup_df.iloc[0]["count"] == 3
    # Check that it collapsing whitespace and lowercasing worked
    assert dup_df.iloc[0]["sample_text"] == "Hello World"


def test_get_records_per_day():
    data = {
        "comment_id": ["C1", "C2", "C3"],
        "docket_id": ["D1", "D1", "D1"],
        "last_modified_date": [
            "2026-05-21 12:00:00",
            "2026-05-21 15:00:00",
            "2026-05-22 12:00:00",
        ],
    }
    df = pd.DataFrame(data)

    daily = get_records_per_day(df, "D1", "last_modified_date")
    assert len(daily) == 2
    # Verify exact counts per day
    assert daily.iloc[0]["count"] == 2
    assert daily.iloc[1]["count"] == 1
