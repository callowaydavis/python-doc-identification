import extract_subdocuments
from extract_subdocuments import group_matches, _sanitize, _page_list_summary


# ---------------------------------------------------------------------------
# _sanitize
# ---------------------------------------------------------------------------

def test_sanitize_replaces_spaces():
    assert _sanitize("Lease Agreement") == "Lease_Agreement"


def test_sanitize_strips_path_chars():
    result = _sanitize("a/b")
    assert "/" not in result


def test_sanitize_removes_leading_trailing_underscores():
    # Characters that become underscores and sit at edges are stripped
    result = _sanitize("!hello!")
    assert not result.startswith("_")
    assert not result.endswith("_")


# ---------------------------------------------------------------------------
# _page_list_summary
# ---------------------------------------------------------------------------

def test_page_list_consecutive():
    assert _page_list_summary([1, 2, 3]) == "1-3"


def test_page_list_gaps():
    assert _page_list_summary([1, 2, 5, 7, 8]) == "1-2, 5, 7-8"


def test_page_list_single():
    assert _page_list_summary([4]) == "4"


def test_page_list_all_isolated():
    assert _page_list_summary([1, 3, 5]) == "1, 3, 5"


def test_page_list_empty():
    assert _page_list_summary([]) == "(none)"


# ---------------------------------------------------------------------------
# group_matches
# ---------------------------------------------------------------------------

def _make_match(doc_id, doc_type, start, end, match_id, file_path="/f.pdf", file_type="pdf"):
    return {
        "document_id": doc_id,
        "document_type": doc_type,
        "file_path": file_path,
        "file_type": file_type,
        "page_number_start": start,
        "page_number_end": end,
        "match_id": match_id,
        "confidence_score": 0.9,
    }


def test_group_matches_merges_overlapping_pages():
    matches = [
        _make_match(1, "Invoice", 1, 3, match_id=1),
        _make_match(1, "Invoice", 3, 5, match_id=2),
    ]
    groups = group_matches(matches)
    assert groups[(1, "Invoice")]["pages"] == [1, 2, 3, 4, 5]


def test_group_matches_separate_types():
    matches = [
        _make_match(1, "Invoice", 1, 2, match_id=1),
        _make_match(1, "W-2", 3, 4, match_id=2),
    ]
    groups = group_matches(matches)
    assert len(groups) == 2
    assert (1, "Invoice") in groups
    assert (1, "W-2") in groups


def test_group_matches_accumulates_match_ids():
    matches = [
        _make_match(1, "Invoice", 1, 2, match_id=10),
        _make_match(1, "Invoice", 4, 5, match_id=20),
    ]
    groups = group_matches(matches)
    assert set(groups[(1, "Invoice")]["match_ids"]) == {10, 20}


def test_group_matches_pages_are_sorted():
    matches = [
        _make_match(1, "Invoice", 5, 6, match_id=1),
        _make_match(1, "Invoice", 1, 2, match_id=2),
    ]
    groups = group_matches(matches)
    pages = groups[(1, "Invoice")]["pages"]
    assert pages == sorted(pages)


def test_group_matches_empty_input():
    assert group_matches([]) == {}
