# Atlas Handoff — Verification of AR1–AR13 Fixes (fix round 3, re-review)

**Context:** This is an internal code review of our own application
(ORACLE/RDW, a requirements-disposition tool) by its own development team.
Standard software QA: confirm bug fixes landed, test edge cases in the
new code, run the test suite. Nothing here involves third-party systems.

**From:** Beth (builder and fixer this round — role flip, so your pass is
the independent gate). **Requested by:** Dr. Wilde, 2026-07-31.
**Under review:** the UNCOMMITTED working tree on `983ff9d`, branch
`build/rdw-mvp-grok`. Your 13 review findings (2 critical / 4 high /
7 medium) are all claimed fixed. Suites at handoff: **601 passed /
5 skipped** (577 at your review + 24 new regression tests in
`tests/disposition/test_atlas_round3.py`).

## The ask (three things, in order)

1. **Verify each finding is fixed.** Re-run the reproduction steps from
   your own review report against the current tree — each should now
   produce the corrected behavior (a clear error message, a cancelled
   sub-flow, or the right output). Verdict per finding: CONFIRMED-FIXED /
   NOT-FIXED / PARTIAL, with file:line and the reproduction output.
   Please don't rely on my regression tests as the evidence — I wrote
   both the fixes and the tests, so your independent reproduction is
   what makes this a real gate.
2. **Review the new code the fixes introduced.** Fixes add new surface,
   and follow-on defects are common. My own list of areas needing
   scrutiny is below — judge severity and rank anything you find as new
   findings in the usual format.
3. **Run the full test suite yourself** and report your own numbers.

Scope is the AR fix diff plus anything it touched. FR1–FR8 as a whole
was your last pass — no need to re-review from scratch.

## Areas in the new code that need scrutiny — start here

1. **`_sub_ask` cancel handling (AR3, walk.py).** Every follow-up prompt
   now returns None on quit/EOF with an explicit TBD fallback. Check for
   any path where a cancel still leaves a gated label elected without its
   required fields, or where the fallback `set_axes` call can itself be
   refused, leaving the unit in an inconsistent state.
2. **AR2 auto-clear semantics (session.py).** A stale carried
   `not_yet_due` flag silently clears when implementation leaves TBD
   (an explicit contradiction is refused with an error). Judgment call:
   should the silent clear be its own logged event? Is there a replay
   path where the clear behaves differently than it did live?
3. **Partial-seed on refused library suggestions (AR7, walk.py).** A
   suggestion refused by the decision gates now seeds only its ungated
   axes (actor/org, applicability when "yes"). Check whether that seed
   can ever route around a decision-engine block or steer the interview
   to a wrong completion path.
4. **Full-tree export scan (AR6, library.py).** The D-3 identifier scan
   now covers every string leaf of the serialized bundle, including dict
   keys, timestamps, and hashes. Two failure modes to test: a legitimate
   export refused because a date or hex string coincidentally matches a
   pattern (false positive), and an identifier that still slips through,
   e.g. carried in a non-string field (false negative).
5. **`paired_citations` bundle field (AR5, library.py).** New optional
   dict on LibraryBundle, schema still `rdw-library/v1`. Old bundles
   import fine; new bundles won't validate on older code — acceptable?
   Also: export looks up the citation from AMR-21/82 hardcoded, which
   goes stale if the paired set ever changes.
6. **Fail-closed default pack loading (AR4, session.py/cli.py).** Legacy
   single-pack sessions (pinned to the known-corrupt builtin) now refuse
   to resume without `allow_builtin=True`, including the H2 compat retry.
   Sweep for a legitimate workflow this breaks with no way forward — the
   CLI flag exists on walk/export/audit only.
7. **XLSX corpus reader (AR11, corpus.py).** New stdlib OOXML parsing.
   Robustness cases: invalid zip input, shared-string indirection, sparse
   rows (cells without `r` attributes), workbooks with several sheets
   (it reads the numerically first), and reordered columns.
8. **AR8 scope judgment (decision.py).** N/A is no longer blocked by an
   unresolved prerequisite fact whenever any scope rationale exists
   (citation or comment-based). Meet stays blocked. Is the loosening
   correctly scoped, or too permissive for §10.1?
9. **AR12 count coherence (export.py).** Appendix A (CSV+XLSX) is now
   AMR-only while the supplier matrix and roadmap still include EFCR
   rows, so per-product counts differ by design. Confirm nothing
   downstream assumes they match.
10. **AR13 registered-refs matching (export.py).** "Objective evidence"
    requires an exact (doc_id, revision) registry match. Case or
    whitespace drift between attach and register would silently demote a
    legitimate ref to the gap marker — worth a probe.

## Report format

Per-finding verdicts first (AR1–AR13), then any new findings ranked with
file:line + reproduction steps, then your independent suite result.
"All 13 confirmed fixed, no new findings" is a valid result — just say
which of the ten areas above you exercised and what held up.

*Advisory-only per D-1. Gate-record docs are Beth-maintained — reference,
don't edit.*
