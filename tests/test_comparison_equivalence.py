"""Direct tests for comparison value equivalence — no HTTP or S3."""
from services.comparison_engine import canonical_key_part, classify_difference, values_equivalent


def test_leading_zeros_are_the_same_number():
    assert values_equivalent("100045", "0000100045")
    assert values_equivalent("1000", "0000001000")
    assert values_equivalent("0", "0000")
    assert classify_difference("100045", "0000100045") is None


def test_excel_apostrophe_and_currency_and_unicode_minus_are_ignored():
    assert values_equivalent("100045", "'0000100045")
    assert values_equivalent("1000", "$1,000.00")
    assert values_equivalent("1000", "€1.000,00")
    assert values_equivalent("-250.5", "250.50-")
    assert values_equivalent("-250.5", "(250.50)")
    assert values_equivalent("-250.5", "\u2212250.5")


def test_date_and_decimal_spellings_match():
    assert values_equivalent("2024-01-05", "05.01.2024")
    assert values_equivalent("2024-01-05", "2024-01-05 00:00:00")
    assert values_equivalent("1000", "1,000.00")
    assert values_equivalent("1000", "1 000")


def test_zero_padded_keys_join():
    assert canonical_key_part("100045") == canonical_key_part("0000100045")
    assert canonical_key_part("'0000100045") == canonical_key_part("100045")


def test_real_changes_are_not_swallowed():
    assert values_equivalent("1000", "1000.01") is False
    assert values_equivalent("0", "") is False
    assert values_equivalent("100045", "100046") is False
    assert classify_difference("1000", "1000.01") == "VALUE_MISMATCH"
    assert classify_difference("john@x.com", "JOHN@X.COM") == "FORMAT_CHANGE"
