# Oracle v1.3 Proposal — Patch-Based Coordinator

**Status:** Design note, not scheduled.
**Author:** Dr. Joseph Wilde / Beth (Claude Opus 4.6)
**Date:** 2026-04-14
**Motivates:** Beth truncation on large-document rewrites
  (see `ORACLE_BETH_MAX_TOKENS` in `oracle/oracle2.py`).

---

## Problem

Today's Oracle coordinator (Beth) emits the **entire revised draft**
as a single JSON field every round.  This has two failure modes that
compound on large documents:

1. **Output-token ceiling.**  Opus 4.6 caps output at 64,000 tokens.
   The adaptive-thinking budget eats 8–16K of that, the JSON envelope
   eats another 1–2K, and everything else is the draft.  A mature
   design doc above ~150K characters hits the ceiling mid-draft and
   gets truncated — the symptom is `Unbalanced braces — attempting
   truncated recovery` in the Beth log line.  We saw this on the
   FORGE-MFG Frontend UX Spec v1.2 merged review
   (session `20260414-053538`): Beth emitted 53,627 chars of
   `revised_draft` and ran out mid-Section 5.4.

2. **Output cost and latency.**  Every round re-emits the full
   document even when 90 % of it is unchanged.  Opus output is
   $75 / M tokens; a 15K-token full rewrite per round is ~$1.12
   and runs 8–12 minutes of wall time under adaptive thinking.
   Three rounds × big doc × full rewrite = real money and real
   minutes for no reviewer-visible improvement on unchanged sections.

Raising `max_tokens` (we bumped 32K → 64K in the v1.2.1 patch) buys
one or two more revisions of a big doc before the ceiling returns.
It does not solve the scaling problem.

## Proposed design

**Round 1** is unchanged.  Reviewers read the full draft; Beth emits
the first revised draft as today.  This seeds the "current draft"
state on the server.

**Rounds 2+** switch Beth from "emit revised_draft" to **"emit patch
list"**.  A patch is a structured change keyed to a document anchor:

```json
{
  "revision_decisions": [...],
  "patches": [
    {
      "finding_id": "R1-ISSUE-001",
      "operation": "insert_after_heading",
      "anchor": "# 6.4 Offline Behavior",
      "content": "# 6.5 Integration Contracts\n\n...markdown..."
    },
    {
      "finding_id": "R1-ISSUE-013",
      "operation": "global_find_replace",
      "find": "qamanager",
      "replace": "qa_manager"
    },
    {
      "finding_id": "R2-ISSUE-003",
      "operation": "replace_section",
      "anchor": "## 5.3.1 Work Order State Machine",
      "until_heading": "## 5.3.2",
      "content": "...new section body..."
    },
    {
      "finding_id": "R3-ISSUE-004",
      "operation": "replace_in_section",
      "anchor": "### 5.4.8 API Response Shape",
      "find": "\"predecessors\": [\"...\"],",
      "replace": "\"predecessors\": [\"...\"],\n  \"predecessor_summaries\": [...]"
    }
  ],
  "open_questions": [...]
}
```

The server-side patch applier performs the edits against the current
draft and produces the next round's baseline.  Reviewers in Round N+1
receive that applied draft plus the patch list for Round N so they can
verify fixes landed and scan for regressions.

### Patch operations (Phase 1 set)

Minimum viable patch vocabulary:

| Operation | Semantics |
|-----------|-----------|
| `insert_after_heading` | Insert new content immediately after the heading's block and before the next heading at the same or higher level. |
| `insert_before_heading` | Symmetric. |
| `replace_section` | Replace the entire block from `anchor` heading through (but not including) `until_heading`. |
| `delete_section` | Delete the entire block from `anchor` through `until_heading`. |
| `replace_in_section` | Within the block identified by `anchor`, perform a literal find / replace.  Fails if `find` occurs zero or more than one time. |
| `global_find_replace` | Document-wide literal find / replace.  Used for renames (e.g., `qamanager` → `qa_manager`).  Fails if `find` has zero occurrences. |
| `append_to_section` | Append content to the end of the section identified by `anchor`. |

Patches that fail (anchor not found, find-string ambiguous or absent)
surface as a structured error in the coordinator response so the
system can fall back to a full-doc rewrite for just the failed patches
if needed.

### Coordinator output schema

```
{
  "revision_decisions": [ ... as today ... ],
  "revised_sections": [ ... as today ... ],
  "patches": [ ... new in v1.3 ... ],
  "open_questions": [ ... as today ... ]
  // revised_draft is no longer emitted on rounds 2+;
  // it is computed server-side by applying patches to the prior draft.
}
```

Round 1 still emits `revised_draft` for backwards compatibility and
to seed the server's current-draft state.  A feature flag
`ORACLE_PATCH_MODE=enabled` gates the behavior; default off during
rollout.

### Regression tracking

The coordinator maintains a "finding registry" keyed by `finding_id`.
If a reviewer in Round N+1 surfaces a finding whose description
closely matches a Round N addressed finding, the referee flags it as
`regression` rather than `new`.  This gives operators visibility when
a patch failed to cleanly resolve an issue.

## Benefits

- **Scales indefinitely.**  A 300-page doc with five targeted patches
  emits ~5K tokens of output.  Beth never truncates on rewrite again.
- **Cheaper per round.**  On mature docs with small diffs, output
  volume drops 10–20×.  Cost follows linearly.
- **Faster per round.**  Smaller output → faster completion → shorter
  adaptive-thinking budget.  Round latency should drop from ~12 min
  to ~2–3 min for small-patch rounds.
- **Finding traceability.**  Every patch links to a `finding_id`.
  The finding → patch → applied-output chain is inspectable.
- **Cleaner convergence.**  "No patches this round" is a stronger
  signal than "no new findings this round" (which is noisy when
  reviewers re-flag issues Beth already addressed).

## Tradeoffs

- **Patch applier complexity.**  ~150–300 lines of Python for the
  anchor-aware markdown patcher.  Must be robust against heading
  renames, inline edits that cross heading boundaries, and
  whitespace drift between rounds.  Anchors use the heading text
  verbatim; a Round-N patch that renames its own heading must use
  `replace_section` (which replaces the heading line itself), not
  `append_to_section` with the old name.
- **Beth prompt grows.**  Beth must be taught the patch operation
  vocabulary and the failure-recovery rules.  The existing prompt
  stays most of the way intact — only the output-format section
  changes.
- **Reviewer context unchanged.**  Reviewers still receive the full
  current draft.  Input-token cost does not decrease; the win is
  output-side.

## Migration plan

1. **Implement the patch applier as a standalone module** with its own
   unit tests.  Publish the operation vocabulary.  No coordinator
   change yet; this is pure library code.
2. **Add `ORACLE_PATCH_MODE=dual`**: the coordinator emits BOTH a
   full `revised_draft` AND a `patches` array.  The server applies
   the patches and cross-checks against the emitted draft (string
   equality after canonicalization).  Any mismatch is logged but
   the full draft wins.  This validates the patch applier against
   Beth's ground truth before cutting over.
3. **After a stability window**, flip default to
   `ORACLE_PATCH_MODE=enabled`: coordinator emits patches only,
   server-applies against the prior draft.  Full-draft fallback
   remains available via env var for debugging.

## Not this proposal

- **Reviewers working from diffs.**  Reviewers still see the full
  current draft each round; diff-only review produces brittle
  findings (reviewers can't flag the section they can't see).
  This is a coordinator-side change, not a reviewer-side change.
- **Round-1 patches.**  Round 1 still emits the full revised draft.
  There is nothing to patch against before Round 1.

---

## Implementation sketch

```python
# oracle/patch_applier.py

@dataclass
class Patch:
    finding_id: str
    operation: str
    anchor: str | None = None
    until_heading: str | None = None
    find: str | None = None
    replace: str | None = None
    content: str | None = None

class PatchApplyError(Exception):
    """Raised when a patch cannot be applied deterministically."""
    def __init__(self, patch: Patch, reason: str):
        super().__init__(f"{patch.finding_id}: {reason}")
        self.patch = patch

def apply_patches(draft: str, patches: list[Patch]) -> tuple[str, list[PatchApplyError]]:
    """Apply patches in declaration order.  Return (new_draft, errors).

    Errors collect rather than raise — the coordinator gets to see
    every failure in one pass and can choose to fall back to a
    full rewrite for those sections.
    """
    current = draft
    errors: list[PatchApplyError] = []
    for p in patches:
        try:
            current = _apply_one(current, p)
        except PatchApplyError as exc:
            errors.append(exc)
    return current, errors
```

The headline:  *patches are the right architecture for a doc-
rewriting coordinator, full rewrites are a stopgap.*
