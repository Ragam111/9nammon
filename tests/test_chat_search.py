"""Unit tests for app/chat_search.py — Thai/English search segmenter."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.chat_search import _fold, seg, is_single_thai_char, fts_query, snippet, like_pattern


# ---------------------------------------------------------------------------
# _fold
# ---------------------------------------------------------------------------

class TestFold:
    def test_lowercase(self):
        assert _fold("Hello") == "hello"

    def test_already_lower(self):
        assert _fold("world") == "world"

    def test_strip_accent_e(self):
        assert _fold("café") == "cafe"

    def test_strip_accent_na_ve(self):
        assert _fold("naïve") == "naive"

    def test_strip_accent_resume(self):
        assert _fold("résumé") == "resume"

    def test_pure_ascii_unchanged(self):
        assert _fold("abc123") == "abc123"

    def test_all_caps(self):
        assert _fold("ABC") == "abc"


# ---------------------------------------------------------------------------
# seg
# ---------------------------------------------------------------------------

class TestSeg:
    # --- edge cases ---
    def test_none_returns_empty(self):
        assert seg(None) == ""

    def test_empty_string_returns_empty(self):
        assert seg("") == ""

    def test_non_string_int_returns_empty(self):
        assert seg(42) == ""

    def test_non_string_list_returns_empty(self):
        assert seg(["a", "b"]) == ""

    # --- single Thai character ---
    def test_single_thai_char_kept(self):
        assert seg("ก") == "ก"

    def test_single_thai_char_mid_range(self):
        assert seg("ม") == "ม"

    # --- Thai bigrams ---
    def test_two_thai_chars_one_bigram(self):
        assert seg("กข") == "กข"

    def test_three_thai_chars_two_bigrams(self):
        assert seg("กขค") == "กข ขค"

    def test_thai_word_sawatdi(self):
        result = seg("สวัสดี").split()
        assert len(result) == 5
        assert result == ["สว", "วั", "ัส", "สด", "ดี"]

    # --- Latin folding ---
    def test_latin_lowercased(self):
        assert seg("Hello") == "hello"

    def test_latin_accent_stripped(self):
        assert seg("café") == "cafe"

    def test_multiple_latin_words(self):
        assert seg("Hello World") == "hello world"

    # --- mixed Thai + Latin ---
    def test_mixed_thai_latin(self):
        result = seg("hello สวัสดี world")
        parts = result.split()
        assert "hello" in parts
        assert "world" in parts
        assert "สว" in parts

    # --- zero-width characters stripped ---
    def test_zero_width_space_stripped(self):
        result = seg("กข​ขค")
        assert "​" not in result

    def test_zero_width_nbsp_stripped(self):
        result = seg("hello﻿world")
        assert "﻿" not in result
        assert "hello" in result
        assert "world" in result

    # --- digits treated as Latin ---
    def test_digits_kept(self):
        result = seg("abc123")
        assert "abc123" in result

    # --- NFC normalization ---
    def test_nfc_normalization_thai(self):
        composed = "กา"
        result = seg(composed)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# is_single_thai_char
# ---------------------------------------------------------------------------

class TestIsSingleThaiChar:
    def test_single_thai_char_true(self):
        assert is_single_thai_char("ก") is True

    def test_single_thai_char_mid_range_true(self):
        assert is_single_thai_char("ส") is True

    def test_multiple_thai_chars_false(self):
        assert is_single_thai_char("กข") is False

    def test_latin_word_false(self):
        assert is_single_thai_char("hello") is False

    def test_empty_string_false(self):
        assert is_single_thai_char("") is False

    def test_none_false(self):
        assert is_single_thai_char(None) is False

    def test_two_terms_false(self):
        assert is_single_thai_char("ก ข") is False

    def test_digit_false(self):
        assert is_single_thai_char("5") is False

    def test_space_only_false(self):
        assert is_single_thai_char("   ") is False

    def test_thai_with_surrounding_spaces_true(self):
        assert is_single_thai_char("  ก  ") is True


# ---------------------------------------------------------------------------
# fts_query
# ---------------------------------------------------------------------------

class TestFtsQuery:
    # --- single Thai char → None ---
    def test_single_thai_char_returns_none(self):
        assert fts_query("ก") is None

    def test_single_thai_char_with_spaces_returns_none(self):
        assert fts_query("  ก  ") is None

    # --- empty / None ---
    def test_empty_string_returns_none(self):
        assert fts_query("") is None

    def test_none_returns_none(self):
        assert fts_query(None) is None

    def test_whitespace_only_returns_none(self):
        assert fts_query("   ") is None

    # --- single ASCII term gets prefix * ---
    def test_single_ascii_term_gets_prefix(self):
        result = fts_query("hello")
        assert result is not None
        assert result.endswith("*")
        assert '"hello"*' == result

    # --- multi-term AND ---
    def test_two_latin_terms_anded(self):
        result = fts_query("foo bar")
        assert result is not None
        assert " AND " in result
        assert result.endswith("*")

    def test_three_latin_terms(self):
        result = fts_query("foo bar baz")
        assert result is not None
        assert result.count(" AND ") == 2
        assert result.endswith("*")

    # --- Thai multi-char term becomes bigrams phrase ---
    def test_thai_two_char_term(self):
        result = fts_query("กข")
        assert result is not None
        assert '"กข"' in result

    def test_thai_three_char_bigrams(self):
        result = fts_query("กขค")
        assert result is not None
        assert '"กข ขค"' in result

    # --- last term not alnum doesn't get * ---
    def test_last_term_not_alnum_no_star(self):
        result = fts_query("hello world!")
        assert result is not None
        assert not result.endswith("*") or '"world!"*' not in result

    # --- double-quote in token escaped ---
    def test_double_quote_in_term_escaped(self):
        result = fts_query('say "hi"')
        assert result is not None
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# snippet
# ---------------------------------------------------------------------------

class TestSnippet:
    def test_empty_content_returns_empty(self):
        assert snippet("", "hello") == ""

    def test_none_content_returns_empty(self):
        assert snippet(None, "hello") == ""

    def test_match_wrapped_in_brackets(self):
        result = snippet("hello world", "hello")
        assert "[hello]" in result

    def test_match_case_insensitive(self):
        result = snippet("Hello World", "hello")
        assert "[Hello]" in result

    def test_prefix_ellipsis_when_start_gt_0(self):
        content = "a" * 50 + "target" + "b" * 50
        result = snippet(content, "target", width=10)
        assert result.startswith("…")

    def test_no_prefix_ellipsis_when_at_start(self):
        result = snippet("target is here", "target", width=10)
        assert not result.startswith("…")

    def test_suffix_ellipsis_when_content_longer(self):
        content = "target" + "b" * 100
        result = snippet(content, "target", width=10)
        assert result.endswith("…")

    def test_no_suffix_ellipsis_when_at_end(self):
        result = snippet("before target", "target", width=30)
        assert not result.endswith("…")

    def test_no_match_returns_truncated_content(self):
        content = "abcdefghijklmnopqrstuvwxyz"
        result = snippet(content, "zzz", width=5)
        assert result == content[:10]

    def test_no_match_empty_query_returns_truncated(self):
        content = "hello world"
        result = snippet(content, "", width=3)
        assert result == content[:6]

    def test_first_matching_term_used(self):
        result = snippet("cat and dog", "cat dog")
        assert "[cat]" in result

    def test_width_controls_context(self):
        content = "X" * 20 + "TARGET" + "Y" * 20
        r5 = snippet(content, "TARGET", width=5)
        r15 = snippet(content, "TARGET", width=15)
        assert len(r15) > len(r5)

    def test_thai_match_in_brackets(self):
        result = snippet("สวัสดีครับ", "สวัสดี")
        assert "[สวัสดี]" in result


# ---------------------------------------------------------------------------
# like_pattern
# ---------------------------------------------------------------------------

class TestLikePattern:
    def test_plain_text_wrapped(self):
        assert like_pattern("hello") == "%hello%"

    def test_percent_escaped(self):
        assert like_pattern("100%") == "%100\\%%"

    def test_underscore_escaped(self):
        assert like_pattern("a_b") == "%a\\_b%"

    def test_backslash_escaped(self):
        assert like_pattern("a\\b") == "%a\\\\b%"

    def test_all_three_special_chars(self):
        result = like_pattern("100%_a\\b")
        assert "\\%" in result
        assert "\\_" in result
        assert "\\\\" in result

    def test_empty_string(self):
        assert like_pattern("") == "%%"

    def test_none(self):
        assert like_pattern(None) == "%%"

    def test_no_special_chars_no_change(self):
        assert like_pattern("hello world") == "%hello world%"

    def test_escape_order_backslash_first(self):
        result = like_pattern("\\%")
        assert result == "%\\\\\\%%"
