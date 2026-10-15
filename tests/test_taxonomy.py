from __future__ import annotations

from osmos.taxonomy import CATEGORY_DESCRIPTIONS, Category


def test_every_category_has_a_nonempty_description() -> None:
    for category in Category:
        assert category in CATEGORY_DESCRIPTIONS
        assert CATEGORY_DESCRIPTIONS[category]


def test_other_is_present_as_the_fallback_bucket() -> None:
    assert Category.OTHER in CATEGORY_DESCRIPTIONS
