"""Unit tests for Astroturf Autopilot discovery, classification, and scoring tasks."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from shared.schemas.docket_catalog import DiscoveredDocket
from shared.schemas.watchlist import WatchlistItem
from scripts.classify_dockets import classify_topic_and_tags, calculate_priority_score


def test_docket_catalog_schema_validation():
    """Verify that DiscoveredDocket enforces strict field validation and defaults."""
    now = datetime.now(timezone.utc)
    docket = DiscoveredDocket(
        docket_id="TEST-2026-0001",
        source="regulations_gov",
        agency_id="FTC",
        topic_id="unclassified",
        title="Test Rule Title",
        summary="Test Short Summary",
        status="discovered",
        comment_count_estimate=1500,
        last_comment_date=now,
        freshness_label="Active",
        priority_score=0.0,
        user_requested_count=2,
        tags="AI, transparency",
        created_at=now,
        updated_at=now,
    )

    assert docket.docket_id == "TEST-2026-0001"
    assert docket.agency_id == "FTC"
    assert docket.comment_count_estimate == 1500
    assert docket.priority_score == 0.0
    assert docket.user_requested_count == 2


def test_watchlist_schema_validation():
    """Verify that WatchlistItem enforces schema correctness."""
    now = datetime.now(timezone.utc)
    item = WatchlistItem(
        watch_id="watch_abc123",
        kind="keyword",
        value="robocalls",
        label="Monitored Robocalls Campaign",
        status="active",
        created_at=now,
        last_checked_at=now,
        notes="Important test watch rule",
    )

    assert item.watch_id == "watch_abc123"
    assert item.kind == "keyword"
    assert item.value == "robocalls"
    assert item.status == "active"


def test_topic_classification_rules():
    """Verify rules-based topic and tags mapping for discovered dockets."""
    now = datetime.now(timezone.utc)
    d1 = DiscoveredDocket(
        docket_id="FTC-2026-METHANE",
        source="regulations_gov",
        agency_id="FTC",
        topic_id="unclassified",
        title="Standards of Performance for new methane emitters",
        summary="",
        status="discovered",
        freshness_label="Active",
        created_at=now,
        updated_at=now,
    )
    topic1, tags1 = classify_topic_and_tags(d1)
    assert topic1 == "oil_and_gas"
    assert "Methane" in tags1
    assert "FTC" in tags1

    d2 = DiscoveredDocket(
        docket_id="FCC-2026-ROBOCALL",
        source="ecfs",
        agency_id="FCC",
        topic_id="unclassified",
        title="Prevention of caller ID spoofing networks",
        summary="Robocall blocking guidelines",
        status="discovered",
        freshness_label="Active",
        created_at=now,
        updated_at=now,
    )
    topic2, tags2 = classify_topic_and_tags(d2)
    assert topic2 == "privacy"
    assert "Robocalls" in tags2
    assert "FCC" in tags2


def test_priority_scoring_formula():
    """Verify prioritization formula calculates weights and decays accurately."""
    now = datetime.now(timezone.utc)

    # 1. High comment count, recently updated, watched docket
    d1 = DiscoveredDocket(
        docket_id="TEST-PRIORITY-1",
        source="regulations_gov",
        agency_id="FCC",
        topic_id="telecom",
        title="Net Neutrality Restoring Freedom",
        summary="",
        status="discovered",
        comment_count_estimate=100000,
        last_comment_date=now,
        freshness_label="Active",
        user_requested_count=10,
        created_at=now,
        updated_at=now,
    )
    watchlist = [
        {
            "kind": "docket",
            "value": "TEST-PRIORITY-1",
            "status": "active",
            "label": "Test",
        }
    ]
    score1 = calculate_priority_score(d1, watchlist)

    # Scale: 25.0 * min(1.0, 100k/50k) = 25.0
    # Recency: 25.0 * exp(-0/30) = 25.0
    # Watchlist: 30.0 * min(1.0, 10/10) + 15 (bonus match) = 45.0
    # Agency: FCC is core = 5.0
    # Total = 25 + 25 + 45 + 5 = 100.0
    assert score1 == 100.0

    # 2. Low count, older date, no watchlist matches
    old_date = now - timedelta(days=90)
    d2 = DiscoveredDocket(
        docket_id="TEST-PRIORITY-2",
        source="regulations_gov",
        agency_id="FDA",  # Not core
        topic_id="healthcare",
        title="Generics Labeling rule",
        summary="",
        status="discovered",
        comment_count_estimate=1000,
        last_comment_date=old_date,
        freshness_label="Active",
        user_requested_count=0,
        created_at=now,
        updated_at=now,
    )
    score2 = calculate_priority_score(d2, [])
    # Scale: 25.0 * (1000/50000) = 0.5
    # Recency: 25.0 * exp(-90/30) = 25.0 * exp(-3) = 25 * 0.0498 = 1.24
    # Watchlist: 0
    # Agency: FDA = 0
    # Total = ~1.74
    assert 1.0 <= score2 <= 2.5
