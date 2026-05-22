import pandas as pd

from debug_ui.app import (
    get_dockets,
    get_overview_stats,
    get_duplicate_text_stats,
    get_records_per_day,
    get_disk_size_mb,
    get_exact_hash_baseline_stats,
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


def test_get_exact_hash_baseline_stats():
    # 1. Empty / None cases
    assert get_exact_hash_baseline_stats(None, "D1") == {
        "substantive_rows": 0,
        "duplicate_hash_groups": 0,
        "exact_duplicate_comments_covered": 0,
        "largest_exact_duplicate_group": 0,
        "exact_duplicate_coverage_pct": 0.0,
    }
    assert get_exact_hash_baseline_stats(pd.DataFrame(), "D1") == {
        "substantive_rows": 0,
        "duplicate_hash_groups": 0,
        "exact_duplicate_comments_covered": 0,
        "largest_exact_duplicate_group": 0,
        "exact_duplicate_coverage_pct": 0.0,
    }

    # 2. Missing columns gracefully handled
    df_missing = pd.DataFrame({"comment_id": ["C1", "C2"]})
    res_missing = get_exact_hash_baseline_stats(df_missing, "D1")
    assert res_missing["substantive_rows"] == 2
    assert res_missing["duplicate_hash_groups"] == 0

    # 3. Multiple dockets & Non-substantive rows ignored
    data = {
        "comment_id": ["C1", "C2", "C3", "C4", "C5", "C6"],
        "docket_id": ["D1", "D1", "D1", "D1", "D2", "D1"],
        "text_source": [
            "detail_comment_text",  # D1 sub
            "detail_comment_text",  # D1 sub
            "detail_cover_note",  # D1 non-sub (should be ignored)
            "detail_comment_text",  # D1 sub
            "detail_comment_text",  # D2 sub (should be ignored for D1)
            "detail_comment_text",  # D1 sub
        ],
        "normalized_text_hash": [
            "hash_A",  # C1
            "hash_A",  # C2 (duplicate group A)
            "hash_A",  # C3 (ignored since non-sub)
            "hash_B",  # C4 (unique)
            "hash_A",  # C5 (ignored since D2)
            "hash_A",  # C6 (duplicate group A, size 3)
        ],
    }
    df = pd.DataFrame(data)

    res = get_exact_hash_baseline_stats(df, "D1")
    # Substantive rows for D1: C1, C2, C4, C6 => 4 rows
    assert res["substantive_rows"] == 4
    # Duplicate groups: only hash_A (since C1, C2, C6 have hash_A and text_source = detail_comment_text) => 1 group
    assert res["duplicate_hash_groups"] == 1
    # Comments covered by duplicates: C1, C2, C6 => 3 comments
    assert res["exact_duplicate_comments_covered"] == 3
    # Largest duplicate group: size 3 (hash_A has 3 occurrences)
    assert res["largest_exact_duplicate_group"] == 3
    # Coverage %: 3 / 4 * 100 = 75.0%
    assert res["exact_duplicate_coverage_pct"] == 75.0
