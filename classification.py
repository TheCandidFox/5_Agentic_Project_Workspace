from __future__ import annotations


VALID_CLASSES = {"public", "internal-non-sensitive", "sensitive"}


def classify(explicit: str | None = None) -> str:
    """
    v0.2.x is intentionally conservative and non-sensitive only.
    Explicit values are accepted; otherwise default to internal-non-sensitive.
    """
    value = explicit or "internal-non-sensitive"
    if value not in VALID_CLASSES:
        raise ValueError(f"invalid data classification: {value}")
    return value


def assert_v0_2_allowed(data_classification: str) -> None:
    if data_classification == "sensitive":
        raise PermissionError(
            "v0.2.x is not approved for sensitive data. "
            "Use only public or internal-non-sensitive tasks."
        )
