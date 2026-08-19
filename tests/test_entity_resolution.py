"""Entity resolution — duplicate groups from name / city / tax id."""
from services.entity_resolution import find_duplicate_groups, ngram_similarity, resolve_columns


def test_resolves_name_city_tax_columns():
    cols = resolve_columns(["Customer Name", "City", "VAT ID", "Email"])
    assert cols["name"] == "Customer Name"
    assert cols["city"] == "City"
    assert cols["taxId"] == "VAT ID"


def test_same_tax_id_is_a_high_confidence_duplicate():
    payload = find_duplicate_groups(
        ["Name", "City", "Tax"],
        [
            (2, ["ACME Inc", "Berlin", "DE123"]),
            (3, ["Beta GmbH", "Munich", "DE999"]),
            (4, ["ACME Incorporated", "Berlin", "DE123"]),
        ],
    )
    assert payload["groupCount"] == 1
    group = payload["groups"][0]
    assert group["confidence"] == "high"
    assert group["reason"] == "Same tax id"
    names = {row["name"] for row in group["rows"]}
    assert names == {"ACME Inc", "ACME Incorporated"}


def test_similar_name_same_city_without_tax():
    payload = find_duplicate_groups(
        ["Customer Name", "ORT01"],
        [
            (2, ["Globex Trading GmbH", "Hamburg"]),
            (3, ["Globex Trading LLC", "Hamburg"]),
            (4, ["Unrelated Foods", "Hamburg"]),
        ],
    )
    assert payload["groupCount"] == 1
    names = {row["name"] for row in payload["groups"][0]["rows"]}
    assert "Globex Trading GmbH" in names
    assert "Globex Trading LLC" in names
    assert "Unrelated Foods" not in names


def test_skips_when_no_entity_columns():
    payload = find_duplicate_groups(
        ["Email", "Amount"],
        [(2, ["a@x.com", "10"])],
    )
    assert payload["groupCount"] == 0
    assert payload["skippedReason"]


def test_ngram_similarity_legal_form_names():
    from services.entity_resolution import _entity_key

    assert ngram_similarity(_entity_key("ACME Inc"), _entity_key("ACME Incorporated")) > 0.9
