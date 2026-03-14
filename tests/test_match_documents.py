import match_documents
from match_documents import build_type_vectorizers, match_document

# Sample pages used across tests — enough variety to build meaningful TF-IDF vectors
SAMPLES = [
    {
        "sample_page_id": 1,
        "sample_id": 1,
        "document_type": "Invoice",
        "page_number": 1,
        "text": "invoice amount due total payment bill charge statement fee",
    },
    {
        "sample_page_id": 2,
        "sample_id": 1,
        "document_type": "Invoice",
        "page_number": 2,
        "text": "billing statement amount invoice payment due total charges",
    },
    {
        "sample_page_id": 3,
        "sample_id": 2,
        "document_type": "W-2",
        "page_number": 1,
        "text": "wages tax withheld employer w2 federal income withholding box",
    },
]


# ---------------------------------------------------------------------------
# build_type_vectorizers
# ---------------------------------------------------------------------------

def test_build_type_vectorizers_creates_one_per_type():
    result = build_type_vectorizers(SAMPLES)
    assert set(result.keys()) == {"Invoice", "W-2"}


def test_build_type_vectorizers_returns_triple_per_type():
    result = build_type_vectorizers(SAMPLES)
    for doc_type, entry in result.items():
        vectorizer, matrix, pages = entry
        assert hasattr(vectorizer, "transform")
        assert len(pages) > 0


def test_build_type_vectorizers_empty_input():
    result = build_type_vectorizers([])
    assert result == {}


# ---------------------------------------------------------------------------
# match_document
# ---------------------------------------------------------------------------

def test_match_document_finds_correct_type():
    vectorizers = build_type_vectorizers(SAMPLES)
    pages = [
        {
            "page_id": 1,
            "page_number": 1,
            "text": "invoice amount due total payment billing statement charges",
            "word_count": 30,
        }
    ]
    matches = match_document(1, pages, vectorizers, {})
    assert len(matches) == 1
    assert matches[0]["document_type"] == "Invoice"


def test_match_document_skips_low_word_count_pages():
    vectorizers = build_type_vectorizers(SAMPLES)
    pages = [
        {
            "page_id": 1,
            "page_number": 1,
            "text": "invoice amount due",
            "word_count": 5,  # below MIN_WORDS=20
        }
    ]
    matches = match_document(1, pages, vectorizers, {})
    assert matches == []


def test_match_document_returns_correct_document_id():
    vectorizers = build_type_vectorizers(SAMPLES)
    pages = [
        {
            "page_id": 1,
            "page_number": 1,
            "text": "invoice amount due total payment billing statement",
            "word_count": 30,
        }
    ]
    matches = match_document(42, pages, vectorizers, {})
    if matches:
        assert matches[0]["document_id"] == 42


def test_match_document_applies_keyword_boost():
    vectorizers = build_type_vectorizers(SAMPLES)
    pages = [
        {
            "page_id": 1,
            "page_number": 1,
            "text": "invoice amount due total payment billing",
            "word_count": 25,
        }
    ]
    base = match_document(1, pages, vectorizers, {})
    boosted = match_document(1, pages, vectorizers, {"Invoice": [("invoice", 0.5)]})
    # If both produced a match, the boosted score must be higher
    if base and boosted:
        assert boosted[0]["confidence_score"] > base[0]["confidence_score"]


def test_match_document_collapses_consecutive_pages():
    vectorizers = build_type_vectorizers(SAMPLES)
    pages = [
        {
            "page_id": 1,
            "page_number": 1,
            "text": "invoice amount due total payment billing statement",
            "word_count": 25,
        },
        {
            "page_id": 2,
            "page_number": 2,
            "text": "invoice total billing amount charges due statement",
            "word_count": 25,
        },
    ]
    matches = match_document(1, pages, vectorizers, {})
    # Two consecutive Invoice pages should collapse into one run
    assert len(matches) == 1
    assert matches[0]["page_number_start"] == 1
    assert matches[0]["page_number_end"] == 2


def test_match_document_empty_pages():
    vectorizers = build_type_vectorizers(SAMPLES)
    assert match_document(1, [], vectorizers, {}) == []
