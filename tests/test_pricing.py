from kbcode.pricing import estimate_cost


def test_unknown_model_returns_none():
    assert estimate_cost("some-unknown-model", 1000, 1000) is None


def test_known_model_computes_expected_cost():
    cost = estimate_cost("claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert cost == 3.0 + 15.0


def test_zero_tokens_is_zero_cost_for_known_model():
    assert estimate_cost("claude-haiku", 0, 0) == 0.0


def test_case_insensitive_matching():
    a = estimate_cost("Claude-Opus-4", 1000, 1000)
    b = estimate_cost("claude-opus-4", 1000, 1000)
    assert a == b
    assert a is not None


def test_more_specific_substring_wins_when_listed_first():
    # "gpt-4o-mini" is listed before the plain "gpt-4o" entry, so a mini model
    # id must not accidentally match the (more expensive) non-mini price.
    mini = estimate_cost("gpt-4o-mini-2024-07-18", 1_000_000, 1_000_000)
    full = estimate_cost("gpt-4o-2024-08-06", 1_000_000, 1_000_000)
    assert mini == 0.15 + 0.60
    assert full == 2.50 + 10.0
    assert mini != full


def test_empty_model_name_returns_none():
    assert estimate_cost("", 100, 100) is None
    assert estimate_cost(None, 100, 100) is None
