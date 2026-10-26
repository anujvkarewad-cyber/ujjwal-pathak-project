"""The three group buckets, from the Students sheet's own words.

Shared by the submissions roster (routers/test_history.py) and the group leaderboards, so
a student can never be in one board for one purpose and another board for another.

The rule the owner set on 17-Oct-2026: the sheet's Group cell is one of three mutually
exclusive buckets - Group 1, Group 2, Both. `Both` is its own bucket, never the union, and
a student is never shown as "Group 1 + Group 2". Anything the sheet cannot place is "" -
which means "not established", never "everyone".
"""

from __future__ import annotations

GROUP_BUCKETS = ("Group 1", "Group 2", "Both")


def bucket_of(raw) -> str:
    """Which bucket a sheet value (or a test's audience) belongs to. "" = not establishable.

    Deliberately narrow: anything that is not clearly one of the three values returns ""
    so it matches nothing rather than matching everything, and the UI can say "group not
    set in the sheet" instead of inventing an audience.
    """
    text = str(raw or "").strip().casefold().replace("/", " ").replace("+", " ")
    flat = text.replace(" ", "")
    if not flat:
        return ""
    if "both" in flat or "combined" in flat or flat in ("all", "allgroups", "group1group2"):
        return "Both"
    has1 = "group1" in flat or flat in ("1", "one", "g1", "brb1")
    has2 = "group2" in flat or flat in ("2", "two", "g2", "brb2")
    if has1 and has2:
        return "Both"
    if has1:
        return "Group 1"
    if has2:
        return "Group 2"
    return ""


def group_text_of(raw) -> str:
    """How a student's group is DISPLAYED: the sheet's own words, never an expansion."""
    return str(raw or "").strip()


def bucket_label(bucket: str) -> str:
    """The label a board is titled with."""
    return {"Both": "Both Groups"}.get(bucket, bucket or "no group set")
