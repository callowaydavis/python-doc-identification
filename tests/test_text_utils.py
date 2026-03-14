from utils.text_utils import clean_text, word_count


def test_clean_text_collapses_whitespace():
    assert clean_text("hello   world") == "hello world"


def test_clean_text_replaces_non_printable_with_space():
    # \x00 is outside [\x20-\x7E\n], so it becomes " "; whitespace then collapses
    assert clean_text("hello\x00world") == "hello world"


def test_clean_text_normalizes_newlines():
    assert clean_text("line1\n\nline2") == "line1 line2"


def test_clean_text_strips_leading_trailing():
    assert clean_text("  hello  ") == "hello"


def test_word_count_basic():
    assert word_count("hello world") == 2


def test_word_count_empty():
    assert word_count("") == 0


def test_word_count_whitespace_only():
    assert word_count("   ") == 0


def test_word_count_extra_spaces():
    assert word_count("  a  b  ") == 2
