"""Text similarity utilities for cognitive self-monitoring."""


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two word sets.

    Returns 0.0 if both sets are empty, otherwise |intersection| / |union|.
    """
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def text_to_words(text: str) -> set[str]:
    """Convert text to lowercase word set for similarity comparison."""
    return set(text.lower().split()) if text else set()
