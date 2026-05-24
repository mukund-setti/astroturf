"""Unit tests for the comment cluster quality evaluation metrics."""

from __future__ import annotations

from scripts.evaluate_demo_quality import calculate_length_sanity, calculate_purity


def test_calculate_purity_computes_exact_or_near_phrase_percentage() -> None:
    texts = [
        "The unprecedented regulatory power is smothering innovation.",
        "Unprecedented regulatory power is damaging the economy.",
        "This is an organic comment about the open internet.",
    ]
    top_phrases = ["unprecedented regulatory power"]

    purity = calculate_purity(texts, top_phrases)

    # 2 out of 3 comments contain the phrase (case-insensitive)
    assert round(purity, 4) == 0.6667


def test_calculate_purity_returns_zero_on_empty_inputs() -> None:
    assert calculate_purity([], ["phrase"]) == 0.0
    assert calculate_purity(["text"], []) == 0.0


def test_calculate_length_sanity_scores_ideal_comments_perfectly() -> None:
    # 200 chars - within the ideal range
    text_ideal = "a" * 200
    assert calculate_length_sanity(text_ideal) == 1.0


def test_calculate_length_sanity_penalizes_very_short_comments() -> None:
    # 25 chars - half of minimum 50
    text_short = "a" * 25
    assert calculate_length_sanity(text_short) == 0.5


def test_calculate_length_sanity_penalizes_extremely_long_comments() -> None:
    # 8000 chars - twice the maximum 4000
    text_long = "a" * 8000
    assert calculate_length_sanity(text_long) == 0.5
