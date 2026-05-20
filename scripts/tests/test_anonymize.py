"""Tests for the operator-identity scrubber."""
from signal_brain.anonymize import compile_scrubber


def test_empty_real_names_returns_identity():
    scrub = compile_scrubber([], "Thomas Martin")
    text = "Ugo wrote this. Hugo also wrote that. UGO is loud."
    assert scrub(text) == text


def test_single_token_replaced_with_first_word_of_name():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("Hey Ugo, how's it going?") == "Hey Thomas, how's it going?"


def test_multi_token_replaced_with_full_name():
    scrub = compile_scrubber(["Ugo Bataillard"], "Thomas Martin")
    assert scrub("Signed, Ugo Bataillard.") == "Signed, Thomas Martin."


def test_longest_match_first():
    """Multi-token patterns must win over single-token ones at the same position."""
    scrub = compile_scrubber(["Ugo", "Ugo Bataillard"], "Thomas Martin")
    # If "Ugo" matched first, we'd get "Thomas Bataillard" — wrong.
    assert scrub("From Ugo Bataillard today") == "From Thomas Martin today"


def test_case_preservation_lowercase():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("ugo répond") == "thomas répond"


def test_case_preservation_titlecase():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("Ugo répond") == "Thomas répond"


def test_case_preservation_uppercase():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("UGO RÉPOND") == "THOMAS RÉPOND"


def test_word_boundary_does_not_match_substring():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    # "Hugo" must NOT become "Hthomas".
    assert scrub("Hugo Pratt is unrelated.") == "Hugo Pratt is unrelated."


def test_word_boundary_with_punctuation():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("salut Ugo!") == "salut Thomas!"
    assert scrub("(Ugo)") == "(Thomas)"
    assert scrub("Ugo, viens") == "Thomas, viens"


def test_multiple_occurrences_in_one_string():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("Ugo et Ugo") == "Thomas et Thomas"


def test_french_diacritics_in_surroundings_do_not_break_boundary():
    """A French word right next to the match must not extend the match."""
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("très Ugo très") == "très Thomas très"


def test_empty_input_is_safe():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("") == ""
