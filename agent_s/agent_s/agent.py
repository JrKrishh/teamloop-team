"""Task ids for new tasks on the board. (Agent S's chat turn used to live here; the app's agents now run their own
tool loop on each laptop, one model step at a time through the hub's /v1/llm.)"""

from __future__ import annotations


def next_id(existing: set[str]) -> str:
    """The next free id in the board's own scheme: T-21 and T-22 on the board -> T-23. Empty board -> T-1."""
    nums: dict[str, int] = {}
    for t in existing:
        prefix, _, n = t.rpartition("-")
        nums[prefix] = max(nums.get(prefix, 0), int(n))
    prefix = max(nums, key=lambda p: (sum(t.startswith(p + "-") for t in existing), nums[p])) if nums else "T"
    return f"{prefix}-{nums.get(prefix, 0) + 1}"
