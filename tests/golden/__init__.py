"""Golden-case evaluation harness for the ORACLE consensus path.

Each fixture in fixtures/ is a scripted multi-oracle transcript replayed
through the real orchestration code (oracle2.run_review, the adapter, the
findings report, and the server endpoints). The tests encode the DESIRED
behavior of the consensus path per AUDIT.md — when first committed, G1-G5
fail by design; each Phase 2 fix commit flips exactly one of them green.
"""
