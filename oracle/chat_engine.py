"""
Module: oracle.chat_engine
Purpose: Deterministic Oracle-native pack chat over registered rule packs.

__safety_critical__: bool = True — routes compliance queries against rule packs

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import json
import logging
import os
import re
from dataclasses import dataclass, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from oracle.chat_contract import OracleChatEnvelope, OracleEvidenceItem
from oracle.chat_formatter import format_chat_response
from oracle.chat_grader import PROHIBITED_DECISION_LANGUAGE_PATTERN, grade_chat_response
from oracle.cli import load_pack as cli_load_pack

LOGGER = logging.getLogger("oracle.chat")

# WHY: "Sn" is the chemical symbol for tin. Users may search for
# "Sn compatibility" meaning tin.
_TOKEN_ALIASES = {
    "sn": "tin",
    "cd": "cadmium",
}

_MATERIAL_QUERY_TERMS = frozenset(
    {
        "tin",
        "cadmium",
        "lead",
        "zinc",
    }
)
_QUERY_TERM_EXPANSIONS = {
    "spaceflight": {"space", "flight"},
}

# WHY these tokens: they indicate mechanism, hazard, or causal engineering
# rationale rather than a generic section heading. They are used to reject
# low-signal pack text like "material restrictions for space flight connectors"
# while keeping real technical reasons such as contamination, sublimation,
# toxicity, whiskers, embrittlement, or corrosion.
_RATIONALE_SIGNAL_TOKENS = frozenset(
    {
        "because",
        "due",
        "since",
        "toxic",
        "toxicity",
        "sublime",
        "sublimation",
        "outgassing",
        "outgas",
        "contaminate",
        "contamination",
        "embrittlement",
        "whisker",
        "whiskers",
        "corrosion",
        "reactive",
        "reactivity",
        "hazard",
        "risk",
        "ignite",
        "ignition",
        "flammability",
        "volatile",
        "vacuum",
        "red",
        "plague",
    }
)

# WHY this path: The secondary rationale corpus is a first-class asset shipped
# with Oracle.  It contains grounded engineering rationale extracted from
# NASA-STD-6016C (e.g., WHY cadmium is prohibited — it sublimes in vacuum).
# Oracle only uses this corpus after a governing pack match already exists, so
# the rationale broadens explanation coverage without changing the primary
# authority source.  ORACLE_SECONDARY_RATIONALE_JSON env var overrides this.
_DEFAULT_SECONDARY_RATIONALE_JSON = (
    Path(__file__).resolve().parent / "rationale" / "nasa_std_6016c_rationale.json"
)

# WHY these terms: they identify connector-specific clauses that should not be
# presented as blanket material bans when the user asks a broader "can we use
# cadmium?" question.
_CONNECTOR_SCOPE_TERMS = frozenset(
    {
        "connector",
        "connectors",
        "accessory",
        "accessories",
        "backshell",
        "backshells",
        "contact",
        "contacts",
        "jackscrew",
        "jackscrews",
        "cap",
        "caps",
        "jam",
        "nut",
        "nuts",
    }
)

# ---------------------------------------------------------------------------
# Stop words: removed during tokenization so they don't pollute keyword
# matching against rule-pack content.
#
# WHY these specific words:
#   - Standard English stop words (a, an, the, of, in, etc.) add no
#     discriminative value when matching user queries to rule text.
#   - Domain-structural words (section, clause, paragraph, table, part)
#     appear in nearly every rule and would dominate similarity scoring
#     without contributing to topical relevance.
#   - Query-action verbs (show, tell, say, compare, finish) express user
#     intent, not rule content.  Intent is handled by dedicated pattern
#     matchers below; keeping these in the token stream would create false
#     keyword hits.
#
# Known false-positive risk: "standard" is a stop word here, which means a
# query about a specific standard (e.g. "NASA-STD-6016C") must rely on the
# hyphenated token surviving tokenization rather than the bare word.
# Known false-negative risk: none identified — removing noise words only
# improves recall of meaningful tokens.
# ---------------------------------------------------------------------------
_STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "can",
    "clause",
    "compare",
    "comparison",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "paragraph",
    "part",
    "say",
    "section",
    "show",
    "standard",
    "selected",
    "table",
    "tell",
    "the",
    "this",
    "to",
    "vs",
    "what",
    "which",
    "with",
    "why",
    "finish",
    "finishes",
}

# ---------------------------------------------------------------------------
# Section reference pattern: detects explicit clause/section citations in the
# user query (e.g. "section 4.2.1", "para 3.1a(2)").
#
# WHY: When a user cites a specific section, the engine can bypass keyword
# search entirely and do a direct lookup against the rule pack's section
# index.  This is the highest-confidence routing path — if a section ref is
# found, it should dominate the response.
#
# False-positive risk: abbreviations like "sec." could collide with "sec"
# as "second", but the trailing digit requirement makes this unlikely.
# False-negative risk: section references using non-standard delimiters
# (e.g. "Section 4-2-1" with hyphens) will not match.
# ---------------------------------------------------------------------------
_SECTION_PATTERN = re.compile(
    r"\b(?:section|sec\.?|clause|paragraph|para\.?)\s+([A-Z]?\d+(?:\.\d+)*(?:[a-z](?:\(\d+\))?)?)\b",
    re.IGNORECASE,
)
# ---------------------------------------------------------------------------
# Table note pattern: detects references to specific notes within tables
# (e.g. "Table III note 2", "table 5 note 1").
#
# WHY: Table notes in NASA/aerospace standards often contain critical
# applicability conditions and exceptions.  Users frequently ask about a
# specific table note, and this pattern lets the engine locate the exact
# note rather than returning the entire table.
#
# False-positive risk: minimal — the "table ... note" structure is
# unambiguous in standards documents.
# False-negative risk: informal references like "the note under table 5"
# or "footnote 2 in table III" will miss.
# ---------------------------------------------------------------------------
_TABLE_NOTE_PATTERN = re.compile(
    r"\btable\s+([IVXLCDM]+|\d+)\s+note\s+(\d+)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Compare pattern: detects cross-reference / comparison queries
# (e.g. "compare 6001B vs 6016C", "comparison of section 4 versus 5").
#
# WHY: Comparison queries require fundamentally different response
# formatting — side-by-side evidence from multiple sources rather than a
# single-source answer.  The router uses this to set compare_only mode on
# the envelope, which the formatter and grader enforce.
#
# False-positive risk: low — these are explicit comparison verbs.
# False-negative risk: implicit comparisons ("how does X differ from Y",
# "what changed between revisions") will not trigger this pattern.
# ---------------------------------------------------------------------------
_COMPARE_PATTERN = re.compile(r"\b(?:compare|comparison|versus|vs\.?)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Action-query pattern: detects "what should I do" / "next steps" queries
# (e.g. "what do I do about this finding", "how should we handle it").
#
# WHY: Action queries need prescriptive remediation guidance rather than
# informational rule lookups.  The router uses this to switch the formatter
# into step-by-step remediation mode with role-specific actions.
#
# False-positive risk: low — phrases are explicit action-seeking language.
# False-negative risk: vague queries like "help" or "any advice" won't match.
# ---------------------------------------------------------------------------
_ACTION_QUERY_PATTERN = re.compile(
    r"\b(?:what (?:do|should) (?:i|we) do|what to do|what now|how (?:do|should) (?:i|we)|next steps?|do about it|handle it)\b",
    re.IGNORECASE,
)
_WHY_QUERY_PATTERN = re.compile(
    r"\b(?:why|how come|what(?:'s| is) the reason)\b",
    re.IGNORECASE,
)
_PURE_TIN_QUERY_PATTERN = re.compile(r"\bpure\s+(?:tin|sn)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Approval pattern: detects queries that request the system to make or
# endorse an engineering decision (e.g. "approve this", "sign off",
# "waive requirement").
#
# WHY: The Oracle must NEVER act as a decision authority.  Queries matching
# this pattern are routed to a REFUSE response with the MUA authority
# boundary disclaimer.  This is a safety-critical gate — if it misses a
# query, the system could appear to endorse an engineering disposition.
#
# False-positive risk: a user asking "who can approve this?" (informational)
# will trigger a refusal.  Acceptable — false-positive refusals are safer
# than false-negative approvals.
# False-negative risk: oblique phrasing like "is this acceptable?" or
# "can we proceed?" may slip through.  The grader's prohibited-language
# check provides a second safety net on the output side.
# ---------------------------------------------------------------------------
_APPROVAL_PATTERN = re.compile(
    r"\b(?:approve\s+this|certify|sign\s+off|waive|final\s+disposition)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Clause lookup pattern: detects queries requesting verbatim rule text
# (e.g. "show me section 4.2", "quote the exact clause", "table 3").
#
# WHY: Verbatim-lookup queries should return the raw rule text with minimal
# interpretation.  This pattern sets the response mode to direct quotation
# rather than synthesis, reducing hallucination risk.
#
# False-positive risk: "show" and "note" are common words that could match
# non-lookup queries.  Mitigated by combining this with other signals
# (e.g. presence of a section reference).
# False-negative risk: queries like "what does 4.2.1 say?" rely on
# _SECTION_PATTERN instead, which is fine — the section ref alone triggers
# direct lookup.
# ---------------------------------------------------------------------------
_CLAUSE_LOOKUP_PATTERN = re.compile(
    r"\b(?:show|quote|exact|text|verbatim|section|sec\.?|clause|paragraph|para\.?|table|note)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Yes/no pattern: detects binary questions that start with an auxiliary verb
# (e.g. "Is titanium allowed in LOX service?", "Can we use PTFE here?").
#
# WHY: Yes/no questions require a definitive compliance determination
# backed by specific rule citations.  The engine structures the response
# as: answer (YES/NO/CONDITIONAL) + governing rule + evidence.  This
# avoids the common LLM failure mode of hedging without commitment.
#
# False-positive risk: rhetorical questions ("Would it help to review
# section 5?") are rare in compliance contexts.
# False-negative risk: yes/no questions that don't start with an auxiliary
# (e.g. "Titanium in LOX — allowed?") will not match.
# ---------------------------------------------------------------------------
_YES_NO_PATTERN = re.compile(r"^(?:if|is|are|can|could|does|do|would|will|should)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Compliance risk pattern: detects queries about rule violations, allowed
# usage, and requirement status.
#
# WHY: These queries need the engine to evaluate a material/process/design
# against specific rules and return a compliance determination with
# citations.  This is the core use case for Oracle chat — "is X compliant
# with Y?" — and the pattern captures the vocabulary of compliance inquiry.
#
# False-positive risk: "ok" and "okay" could match casual conversation,
# but Oracle chat is a professional tool where these words almost always
# mean "is this acceptable per the standard?"
# False-negative risk: domain-specific compliance language (e.g. "red-lined",
# "non-conformance") is not captured here.
# ---------------------------------------------------------------------------
_COMPLIANCE_RISK_PATTERN = re.compile(
    r"\b(?:against|violate|violation|non-?compliant|compliant|allowed|permit|permitted|ok|okay|require|required|must)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Scope pattern: detects queries about document scope, changes, and
# revisions (e.g. "what changed in revision C?", "scope of section 5").
#
# WHY: Scope and revision queries require the engine to pull metadata
# about the standard itself (revision history, applicability scope) rather
# than individual rules.  This enables delta-analysis responses.
#
# False-positive risk: "change" is common in rule text ("change in
# temperature"); combining with other signals reduces false triggers.
# False-negative risk: queries using "difference" or "delta" without
# scope-specific terms will not match.
# ---------------------------------------------------------------------------
_SCOPE_PATTERN = re.compile(r"\b(?:scope|change|insert|added?|modify|revision)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Funding pattern: detects queries about cost, budget, and financial
# identifiers (CWBS = Contract Work Breakdown Structure, PSID = Project
# Structure Identifier).
#
# WHY: Funding questions require a completely different evidence set —
# contract/financial data rather than technical rules.  Detecting this
# early lets the router either redirect to the appropriate data source
# or return a clear "out of scope for this rule pack" response.
#
# False-positive risk: "cost" appears in technical contexts ("cost of
# testing"); low impact since funding-mode responses are informational.
# False-negative risk: informal budget language ("how much", "price") is
# not captured.
# ---------------------------------------------------------------------------
_FUNDING_PATTERN = re.compile(
    r"\b(?:fund|funding|unfunded|cost|budget|charge code|cwbs|psid)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Vague term pattern: detects weasel words and subjective qualifiers that
# indicate a poorly-specified requirement or an ambiguous user query.
#
# WHY: Two purposes: (1) When found in rule text, these terms flag
# requirements that lack measurable acceptance criteria — the engine can
# warn that the rule is vague.  (2) When found in a user query, they
# signal that the question may need clarification before a meaningful
# compliance answer can be given.
#
# False-positive risk: "support" is overloaded (structural support vs.
# organizational support); context usually disambiguates.
# False-negative risk: domain-specific vagueness ("suitable", "compatible")
# is not captured here but may be in domain-specific packs.
# ---------------------------------------------------------------------------
_VAGUE_TERM_PATTERN = re.compile(
    r"\b(?:appropriate|adequate|sufficient|timely|reasonable|as needed|as appropriate|where possible|support|supports|optimi[sz]e|minimi[sz]e|robust|user-friendly|efficient)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Owner pattern: detects references to organizational roles and responsible
# parties in contract/requirements language.
#
# WHY: Identifying the responsible party is critical for obligation
# analysis — "the contractor shall" vs "the government shall" assigns
# completely different ownership.  This pattern enables the engine to
# extract WHO is obligated, not just WHAT the obligation is.  The short
# acronyms (COR, CO, TM, RA, TI) are standard NASA/DoD contract roles:
#   COR = Contracting Officer's Representative
#   CO  = Contracting Officer
#   TM  = Technical Monitor
#   RA  = Responsible Authority
#   TI  = Technical Inspector
#
# False-positive risk: two-letter acronyms (co, tm, ra, ti) can collide
# with common words in case-insensitive mode.  Mitigated by combining
# with obligation verbs (_ACTION_PATTERN).
# False-negative risk: non-standard role titles ("lead analyst",
# "designated approver") will not match.
# ---------------------------------------------------------------------------
_OWNER_PATTERN = re.compile(
    r"\b(?:contractor|government|team|program|office|manager|engineer|reviewer|operator|system|supplier|vendor|customer|cor|co|tm|ra|ti)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Action pattern: detects obligation and directive verbs — the core verbs
# that turn prose into enforceable requirements.
#
# WHY: These verbs are the spine of any "shall statement."  Matching them
# lets the engine identify which rules are actionable obligations vs.
# informational background.  Combined with _OWNER_PATTERN, they enable
# full WHO-SHALL-WHAT decomposition of requirements.
#
# The verb hierarchy follows NASA/DoD standards convention:
#   shall/must = mandatory | will = declaration of intent
#   should = recommendation | provide/deliver/submit/etc. = action verbs
#
# False-positive risk: "review" and "document" are both nouns and verbs;
# context (presence of a subject + shall) disambiguates.
# False-negative risk: passive constructions ("shall be provided") are
# captured because "shall" triggers independently of "provide."
# ---------------------------------------------------------------------------
_ACTION_PATTERN = re.compile(
    r"\b(?:shall|must|will|should|provide|deliver|submit|update|maintain|complete|implement|notify|document|record|verify|validate|review)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Measure pattern: detects quantitative criteria, deadlines, and evidence
# artifacts that make a requirement testable/verifiable.
#
# WHY: A requirement without a measurable acceptance criterion is
# unenforceable.  This pattern identifies the verification side of
# obligations — deadlines ("within 30 days"), thresholds ("at least 95%"),
# evidence types ("test", "inspection", "deliverable").  Used with
# _ACTION_PATTERN to score requirement completeness.
#
# False-positive risk: bare numbers (\d+) will match version numbers,
# section numbers, etc.  Acceptable — this is a signal, not a classifier.
# False-negative risk: implicit measures ("prior to CDR", "before ATP")
# use milestone names rather than time units and will not match.
# ---------------------------------------------------------------------------
_MEASURE_PATTERN = re.compile(
    r"\b(?:within|no later than|at least|at most|maximum|min(?:imum)?|threshold|metric|acceptance|evidence|artifact|deliverable|report|log|record|trace|test|inspection|review criteria|\d+%?|\d+\s*(?:day|days|hour|hours|week|weeks|month|months))\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Change control pattern: detects modification/revision actions in contract
# and requirements management contexts.
#
# WHY: Change-control queries ("can I modify section 5?", "what happens if
# we revise this requirement?") need the engine to surface change-authority
# rules, configuration management procedures, and impact-assessment
# requirements — a distinct evidence set from normal compliance queries.
#
# Overlaps with _SCOPE_PATTERN by design: scope detection identifies the
# query topic, while change-control detection identifies the governance
# process around modifications.
#
# False-positive risk: "update" and "replace" appear in normal technical
# instructions; combining with _IMPACT_PATTERN sharpens the signal.
# False-negative risk: domain jargon ("ECR", "ECP", "red-line") is not
# captured.
# ---------------------------------------------------------------------------
_CHANGE_CONTROL_PATTERN = re.compile(
    r"\b(?:change|scope|insert|modify|revision|revise|update|delete|replace|addition)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Impact pattern: detects terms associated with programmatic impact
# assessment — cost, schedule, configuration, and contract artifacts.
#
# WHY: When a change or scope query is detected, the engine needs to
# identify what dimensions of impact are relevant.  This pattern captures
# the vocabulary of impact analysis (cost, schedule, interface, baseline)
# plus the artifacts that must be updated (documents, drawings, approvals).
# CWBS/PSID are NASA/DoD financial tracking identifiers.
#
# False-positive risk: "document" and "approval" appear in many contexts;
# this pattern is only meaningful when combined with _CHANGE_CONTROL_PATTERN.
# False-negative risk: program-specific impact categories (e.g. "mass
# budget", "power allocation") are not captured.
# ---------------------------------------------------------------------------
_IMPACT_PATTERN = re.compile(
    r"\b(?:cost|fund|funding|schedule|interface|baseline|configuration|document|drawing|approval|impact|cwbs|psid|artifact)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Review governance pattern: detects authorization and concurrence language.
#
# WHY: Queries about who must approve, authorize, or sign off on actions
# need the engine to surface governance chains and approval authorities
# from the rule pack — a distinct response structure from technical
# compliance queries.
#
# False-positive risk: "accept" could match acceptance testing contexts;
# mitigated by checking for governance-context co-signals.
# False-negative risk: informal governance terms ("green-light", "thumbs
# up") are not captured (nor should they be in formal standards).
# ---------------------------------------------------------------------------
_REVIEW_GOVERNANCE_PATTERN = re.compile(
    r"\b(?:approval|approve|accept|sign-?off|concurrence|waiver|authorize|authorized)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Prohibited decision language: catches LLM output (or user-echo) that
# would imply the Oracle is making or endorsing an engineering decision.
#
# WHY: Safety-critical gate.  The Oracle must never appear to approve,
# certify, waive, or accept anything.  This pattern is used on the OUTPUT
# side (in the grader) to catch and reject responses that contain decision
# language.  Canonical definition lives in chat_grader.py; imported here
# to avoid drift between the two copies.
#
# Previously duplicated inline — now uses the canonical import from
# oracle.chat_grader.PROHIBITED_DECISION_LANGUAGE_PATTERN.
# ---------------------------------------------------------------------------
_PROHIBITED_DECISION_LANGUAGE_PATTERN = PROHIBITED_DECISION_LANGUAGE_PATTERN


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


# ---------------------------------------------------------------------------
# Minimal suffix-stripping stemmer for query-to-rule keyword matching.
#
# WHY these specific rules (and not a full stemmer like Porter/Snowball):
#   1. Domain vocabulary is narrow and predictable — aerospace/compliance
#      terms rarely need aggressive stemming.
#   2. Full stemmers introduce unpredictable mutations that break exact
#      matching (e.g. Porter stems "processing" -> "process" but also
#      "universe" -> "univers", "policy" -> "polici").
#   3. These five suffix rules cover the most common English inflections
#      in standards language while preserving root readability:
#        -ies -> -y   : "boundaries" -> "boundary", "properties" -> "property"
#        -ing -> stem  : "testing" -> "test", "welding" -> "weld"
#        -ed  -> stem  : "required" -> "requir" (close enough for matching)
#        -es  -> stem  : "processes" -> "process", "stresses" -> "stress"
#        -s   -> stem  : "materials" -> "material", "requirements" -> "requirement"
#
# Length guards (len > 3/4/5) prevent over-stemming short words:
#   "is" -> "is" (not "i"), "bed" -> "bed" (not "b"), "sing" -> "sing"
#
# Known failure modes:
#   - Double-suffix words: "classified" -> "classifi" (not "classify")
#   - Irregular verbs: "ran", "built", "met" are not stemmed at all
#   - -tion/-sion words: "inspection" -> "inspection" (no rule fires,
#     which is actually correct — the noun IS the root form)
#   - "dies" (len 4) won't trigger -ies rule due to length guard
# ---------------------------------------------------------------------------
def _normalize_token(value: str) -> str:
    token = value.lower().strip("._-")
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("es") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 3:
        token = token[:-1]
    token = _TOKEN_ALIASES.get(token, token)
    return token


def _tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value.lower())
    out: list[str] = []
    for token in tokens:
        token = _normalize_token(token)
        if token in _STOP_WORDS:
            continue
        if len(token) <= 1:
            continue
        out.append(token)
    return out


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_normalize_space(item) for item in value if _normalize_space(item)]
    return []


def _coerce_page(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = _normalize_space(value)
    if not text:
        return None
    match = re.match(r"(\d+)", text)
    return int(match.group(1)) if match else None


def _slug_terms(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(_tokenize(value.replace("_", " ").replace("-", " ")))


def _query_terms(raw_query: str) -> set[str]:
    terms = set(_tokenize(raw_query))
    for term in list(terms):
        terms.update(_QUERY_TERM_EXPANSIONS.get(term, set()))
    if _FUNDING_PATTERN.search(raw_query):
        terms.update({"fund", "funding", "cost", "budget", "cwbs", "psid"})
    if _SCOPE_PATTERN.search(raw_query):
        terms.update({"scope", "change", "revision", "tocr"})
    if _COMPLIANCE_RISK_PATTERN.search(raw_query):
        terms.update({"violate", "prohibit", "mandatory", "must", "required"})
    return terms


def _query_material_terms(raw_query: str) -> set[str]:
    return {term for term in _query_terms(raw_query) if term in _MATERIAL_QUERY_TERMS}


def _phrase_score(query_terms: set[str], phrase: str) -> int:
    phrase_terms = set(_tokenize(phrase))
    if not phrase_terms:
        return 0
    overlap = query_terms.intersection(phrase_terms)
    if not overlap:
        return 0
    score = len(overlap) * 2
    if overlap == phrase_terms:
        score += 2
    return score


def _has_strong_rule_anchor(
    *,
    query_terms: set[str],
    rule: ChatRule,
    raw_query: str,
    section_match: re.Match[str] | None,
    table_note_match: re.Match[str] | None,
) -> bool:
    if section_match or table_note_match:
        return True
    if _phrase_score(query_terms, rule.subject) >= 4:
        return True
    if _phrase_score(query_terms, rule.requirement) >= 4:
        return True
    if any(_phrase_score(query_terms, keyword) >= 4 for keyword in rule.keywords):
        return True
    if rule.subject and rule.subject.lower() in raw_query.lower():
        return True
    return False


def _is_yes_no_query(query: str) -> bool:
    return bool(_YES_NO_PATTERN.search(query.strip()) or _COMPLIANCE_RISK_PATTERN.search(query))


def _is_action_query(query: str) -> bool:
    return bool(_ACTION_QUERY_PATTERN.search(query))


def _is_why_query(query: str) -> bool:
    return bool(_WHY_QUERY_PATTERN.search(query))


def _is_clause_lookup_query(query: str) -> bool:
    return bool(
        _CLAUSE_LOOKUP_PATTERN.search(query)
        or _SECTION_PATTERN.search(query)
        or _TABLE_NOTE_PATTERN.search(query)
    )


def _is_scope_funding_query(query: str) -> bool:
    return bool(_SCOPE_PATTERN.search(query) and _FUNDING_PATTERN.search(query))


def _is_pure_tin_query(query: str) -> bool:
    query_terms = _query_terms(query)
    return bool(_PURE_TIN_QUERY_PATTERN.search(query) or {"pure", "tin"}.issubset(query_terms))


def _is_pure_tin_action_query(query: str) -> bool:
    return _is_action_query(query) and _is_pure_tin_query(query)


def _wants_exact_text(query: str) -> bool:
    return bool(re.search(r"\b(show|quote|exact|verbatim|full text)\b", query, re.IGNORECASE))


@dataclass(frozen=True)
class ChatRule:
    pack_slug: str
    standard_id: str
    standard_title: str
    rule_id: str
    section: str
    page: int | None
    obligation_type: str
    obligation_keyword: str
    statement_text: str
    subject: str
    requirement: str
    justification: str
    keywords: tuple[str, ...]
    applies_to: tuple[str, ...]


@dataclass(frozen=True)
class ChatPack:
    pack_slug: str
    standard_id: str
    standard_title: str
    rules: tuple[ChatRule, ...]


@dataclass(frozen=True)
class SecondaryRationale:
    standard_id: str
    standard_title: str
    section: str
    page: int | None
    statement_text: str
    justification: str
    keywords: tuple[str, ...]
    applies_to: tuple[str, ...]


def load_chat_pack(pack_name: str, pack_dir: Path) -> ChatPack:
    pack_data, resolved = cli_load_pack(pack_name, pack_dir)
    schema_version = str(pack_data.get("schema_version") or "")
    pack_slug = resolved
    standard_id = _normalize_space(pack_data.get("standard_id") or resolved)
    standard_title = _normalize_space(
        pack_data.get("standard_title") or pack_data.get("source_document") or standard_id
    )
    rules: list[ChatRule] = []

    if schema_version == "gpcm_rulepack/v1" or pack_data.get("requirements"):
        for requirement in pack_data.get("requirements", []):
            if not isinstance(requirement, dict):
                continue
            text = _normalize_space(requirement.get("shall_text"))
            if not text:
                continue
            rules.append(
                ChatRule(
                    pack_slug=pack_slug,
                    standard_id=standard_id,
                    standard_title=standard_title,
                    rule_id=_normalize_space(requirement.get("id")) or "unknown",
                    section=_normalize_space(requirement.get("section")),
                    page=_coerce_page(requirement.get("page")),
                    obligation_type="mandatory",
                    obligation_keyword="shall",
                    statement_text=text,
                    subject=_normalize_space(requirement.get("subject")),
                    requirement=_normalize_space(requirement.get("requirement")),
                    justification=_normalize_space(requirement.get("justification")),
                    keywords=tuple(_as_str_list(requirement.get("keywords"))),
                    applies_to=tuple(_as_str_list(requirement.get("applies_to"))),
                )
            )
    elif schema_version == "far_rulepack/v1" or pack_data.get("parts"):
        for part_key, part_rules in pack_data.get("parts", {}).items():
            if not isinstance(part_rules, list):
                continue
            for item in part_rules:
                if not isinstance(item, dict):
                    continue
                text = _normalize_space(item.get("statement_text"))
                if not text:
                    continue
                section = _normalize_space(item.get("section")) or f"Part {part_key}"
                rules.append(
                    ChatRule(
                        pack_slug=pack_slug,
                        standard_id=standard_id,
                        standard_title=standard_title,
                        rule_id=_normalize_space(item.get("id")) or "unknown",
                        section=section,
                        page=_coerce_page(item.get("page")),
                        obligation_type=_normalize_space(item.get("obligation_type")).lower() or "mandatory",
                        obligation_keyword=_normalize_space(item.get("obligation_keyword")).lower() or "shall",
                        statement_text=text,
                        subject=_normalize_space(item.get("subject")),
                        requirement=_normalize_space(item.get("requirement")),
                        justification=_normalize_space(item.get("justification")),
                        keywords=tuple(_as_str_list(item.get("keywords"))),
                        applies_to=tuple(_as_str_list(item.get("applies_to"))),
                    )
                )
    else:
        for item in pack_data.get("rules", []):
            if not isinstance(item, dict):
                continue
            text = _normalize_space(item.get("statement_text"))
            if not text:
                continue
            rules.append(
                ChatRule(
                    pack_slug=pack_slug,
                    standard_id=standard_id,
                    standard_title=standard_title,
                    rule_id=_normalize_space(item.get("rule_id")) or "unknown",
                    section=_normalize_space(item.get("section")),
                    page=_coerce_page(item.get("page")),
                    obligation_type=_normalize_space(item.get("obligation_type")).lower() or "mandatory",
                    obligation_keyword=_normalize_space(item.get("obligation_keyword")).lower() or "shall",
                    statement_text=text,
                    subject=_normalize_space(item.get("subject")),
                    requirement=_normalize_space(item.get("requirement")),
                    justification=_normalize_space(item.get("justification")),
                    keywords=tuple(_as_str_list(item.get("keywords"))),
                    applies_to=tuple(_as_str_list(item.get("applies_to"))),
                )
            )

    return ChatPack(
        pack_slug=pack_slug,
        standard_id=standard_id,
        standard_title=standard_title,
        rules=tuple(rules),
    )


def _secondary_rationale_corpus_path() -> Path | None:
    """Return the configured secondary rationale corpus path, if enabled.

    WHY: tests and deployments need an explicit way to disable or override the
    shared rationale corpus so Oracle behavior stays deterministic per
    environment. A blank env var means "disable secondary rationale."
    """
    configured = os.environ.get("ORACLE_SECONDARY_RATIONALE_JSON")
    if configured is not None:
        configured_path = _normalize_space(configured)
        return Path(configured_path).expanduser() if configured_path else None
    if _DEFAULT_SECONDARY_RATIONALE_JSON.is_file():
        return _DEFAULT_SECONDARY_RATIONALE_JSON
    return None


@lru_cache(maxsize=8)
def _load_secondary_rationale_entries(path_text: str) -> tuple[SecondaryRationale, ...]:
    path = Path(path_text)
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed to load secondary rationale corpus from %s: %s", path, exc)
        return ()

    statements = payload.get("statements", []) if isinstance(payload, dict) else []
    standard_id = _normalize_space(payload.get("standard_id")) if isinstance(payload, dict) else ""
    source_file = _normalize_space(payload.get("source_file")) if isinstance(payload, dict) else ""
    standard_id = standard_id or "NASA-STD-6016C"
    standard_title = source_file or standard_id
    entries: list[SecondaryRationale] = []

    for item in statements:
        if not isinstance(item, dict):
            continue
        statement_text = _normalize_space(item.get("statement_text"))
        justification = _normalize_space(item.get("justification"))
        if not statement_text:
            continue
        if not justification and not _has_inline_rationale(statement_text):
            continue
        entries.append(
            SecondaryRationale(
                standard_id=standard_id,
                standard_title=standard_title,
                section=_normalize_space(item.get("section")),
                page=_coerce_page(item.get("page")),
                statement_text=statement_text,
                justification=justification,
                keywords=tuple(_as_str_list(item.get("keywords"))),
                applies_to=tuple(_as_str_list(item.get("applies_to"))),
            )
        )
    return tuple(entries)


def _secondary_rationale_entries() -> tuple[SecondaryRationale, ...]:
    path = _secondary_rationale_corpus_path()
    if path is None:
        return ()
    return _load_secondary_rationale_entries(str(path))


def _citation(rule: ChatRule) -> str:
    section = f" section {rule.section}" if rule.section else ""
    page = f" (p. {rule.page})" if rule.page else ""
    return f"{rule.standard_id}{section}{page}"


def _secondary_rationale_citation(entry: SecondaryRationale) -> str:
    section = f" section {entry.section}" if entry.section else ""
    page = f" (p. {entry.page})" if entry.page else ""
    return f"{entry.standard_id}{section}{page}"


def _rank_rules(raw_query: str, rules: tuple[ChatRule, ...]) -> list[tuple[ChatRule, int]]:
    query_tokens = _query_terms(raw_query)
    material_terms = _query_material_terms(raw_query)
    section_match = _SECTION_PATTERN.search(raw_query)
    table_note_match = _TABLE_NOTE_PATTERN.search(raw_query)
    ranked: list[tuple[ChatRule, int]] = []
    yes_no_query = _is_yes_no_query(raw_query)
    why_query = _is_why_query(raw_query)
    scope_funding_query = _is_scope_funding_query(raw_query)

    for rule in rules:
        searchable_parts = [
            rule.statement_text,
            rule.subject,
            rule.requirement,
            rule.section,
            *rule.keywords,
            *rule.applies_to,
        ]
        rule_tokens = set(_tokenize(" ".join(searchable_parts)))
        if material_terms and not material_terms.intersection(rule_tokens):
            continue
        haystack_tokens = query_tokens.intersection(rule_tokens)
        score = len(haystack_tokens) * 3
        score += _phrase_score(query_tokens, rule.subject)
        score += _phrase_score(query_tokens, rule.requirement)
        score += sum(_phrase_score(query_tokens, keyword) for keyword in rule.keywords)
        score += sum(_phrase_score(query_tokens, applies) for applies in rule.applies_to)

        if section_match:
            requested = _normalize_space(section_match.group(1)).lower()
            if requested and requested in rule.section.lower():
                score += 8

        if table_note_match:
            requested = f"table {table_note_match.group(1)} note {table_note_match.group(2)}".lower()
            if requested in rule.section.lower():
                score += 10

        if rule.section and rule.section.lower() in raw_query.lower():
            score += 4
        if rule.subject and rule.subject.lower() in raw_query.lower():
            score += 4
        if rule.obligation_type == "prohibition" and any(
            token in raw_query.lower() for token in ("avoid", "prohibit", "shall not", "not use")
        ):
            score += 2
        if yes_no_query and rule.obligation_type in {"mandatory", "prohibition"}:
            score += 2
        if why_query and _rule_has_rationale(rule):
            # WHY +6: for "why" questions, a rationale-bearing rule is materially
            # more useful than an equivalent bare prohibition.
            score += 6
        if scope_funding_query:
            applies_to_terms = set(_slug_terms(" ".join(rule.applies_to)))
            rule_terms = set(_tokenize(" ".join([rule.subject, rule.requirement, *rule.keywords])))
            if {"scope", "change"}.intersection(rule_terms.union(applies_to_terms)):
                score += 6
            if {"fund", "funding", "cost", "cwbs", "psid"}.intersection(rule_terms.union(applies_to_terms)):
                score += 6
            if "tocr" in rule_terms.union(applies_to_terms):
                score += 4

        if score > 0:
            strong_anchor = _has_strong_rule_anchor(
                query_terms=query_tokens,
                rule=rule,
                raw_query=raw_query,
                section_match=section_match,
                table_note_match=table_note_match,
            )
            if len(haystack_tokens) < 2 and not strong_anchor:
                continue
            ranked.append((rule, score))

    ranked.sort(
        key=lambda item: (
            -item[1],
            item[0].page if item[0].page is not None else 10_000,
            item[0].section,
            item[0].rule_id,
        )
    )
    return ranked


def _dedupe_rules(matches: list[tuple[ChatRule, int]], limit: int) -> list[tuple[ChatRule, int]]:
    seen: set[str] = set()
    deduped: list[tuple[ChatRule, int]] = []
    for rule, score in matches:
        key = f"{rule.section}|{rule.requirement}|{rule.statement_text}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append((rule, score))
        if len(deduped) >= limit:
            break
    return deduped


def _summarize_rule(rule: ChatRule) -> str:
    requirement = _normalize_space(rule.requirement)
    statement = _normalize_space(rule.statement_text)
    if not requirement:
        return statement.rstrip(".") + "."

    requirement_tokens = _tokenize(requirement)
    if len(requirement_tokens) < 4 or re.match(r"^(?:not\s+be|be)\b", requirement, re.IGNORECASE):
        if statement:
            return statement.rstrip(".") + "."

    if statement and rule.subject and rule.subject.lower() not in requirement.lower():
        if "because" in statement.lower() or "due to" in statement.lower():
            return statement.rstrip(".") + "."
        if re.match(
            r"^(?:shall|must|should|may|can|cannot|must not|shall not)\b",
            requirement,
            re.IGNORECASE,
        ):
            normalized_requirement = requirement[0].lower() + requirement[1:] if requirement else requirement
            return f"{rule.subject} {normalized_requirement.rstrip('.')}" + "."

    return requirement.rstrip(".") + "."


def _rule_topic(rule: ChatRule) -> str:
    return rule.subject or rule.requirement or rule.statement_text


def _rule_stance(rule: ChatRule) -> str:
    text = " ".join(
        part for part in [rule.obligation_type, rule.obligation_keyword, rule.statement_text, rule.requirement] if part
    ).lower()
    if any(token in text for token in ("shall not", "must not", "prohibit", "not be used", "not use")):
        return "prohibits"
    if rule.obligation_type == "recommendation" or rule.obligation_keyword == "should":
        return "recommends"
    if rule.obligation_type == "permission" or rule.obligation_keyword == "may":
        return "allows"
    return "requires"


def _rule_text(rule: ChatRule) -> str:
    searchable_parts = [
        rule.statement_text,
        rule.subject,
        rule.requirement,
        rule.justification,
        rule.section,
        *rule.keywords,
        *rule.applies_to,
    ]
    return " ".join(_normalize_space(part) for part in searchable_parts if _normalize_space(part)).lower()


def _normalized_sentence(text: str) -> str:
    """Return a normalized sentence with stable trailing punctuation.

    WHY: Oracle merges retrieved requirement text and retrieved rationale into a
    single operator-facing answer. Stable punctuation keeps the merged output
    deterministic and avoids awkward double periods.
    """
    cleaned = _normalize_space(text)
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _has_inline_rationale(text: str) -> bool:
    """True when a rule embeds its rationale directly in the rule sentence.

    WHY: Standards often explain a prohibition inline with clause joiners like
    "because" or "due to". When that happens, the safest answer is to reuse the
    exact grounded sentence rather than paraphrase the reason.
    """
    lowered = _normalize_space(text).lower()
    return any(marker in lowered for marker in (" because ", " due to ", " since "))


def _is_low_signal_rationale(rule: ChatRule, rationale: str) -> bool:
    """Reject topic labels that are too generic to answer a why-question.

    WHY: Some packs carry section labels or topical headers in nearby fields.
    Those strings look like rationale at the schema level but they are not
    technical explanations. If the text adds no mechanism/hazard tokens and is
    mostly just a restatement of the rule topic, Oracle should suppress it.
    """
    rationale_tokens = set(_tokenize(rationale))
    if not rationale_tokens:
        return True
    if rationale_tokens.intersection(_RATIONALE_SIGNAL_TOKENS):
        return False
    topic_tokens = set(
        _tokenize(
            " ".join(
                [
                    rule.subject,
                    rule.requirement,
                    rule.statement_text,
                    *rule.keywords,
                    *rule.applies_to,
                ]
            )
        )
    )
    overlap_count = len(rationale_tokens.intersection(topic_tokens))
    # WHY 0.75: when three quarters or more of the rationale tokens are already
    # present in the topic text, the field is usually just a heading or label.
    return overlap_count / max(len(rationale_tokens), 1) >= 0.75


def _rule_rationale(rule: ChatRule) -> str:
    """Return the grounded technical rationale attached to a rule, if present.

    WHY: "Why" questions must be answered from retrieved evidence, not model
    memory. Oracle therefore prefers inline causal text first, then the pack's
    explicit justification field, and otherwise treats the rule as a bare
    prohibition with no stated rationale.
    """
    if _has_inline_rationale(rule.statement_text):
        return _normalized_sentence(rule.statement_text)
    if rule.justification:
        normalized = _normalized_sentence(rule.justification)
        if normalized and not _is_low_signal_rationale(rule, normalized):
            return normalized
    return ""


def _rule_has_rationale(rule: ChatRule) -> bool:
    """Return True when the rule includes an explicit technical explanation."""
    return bool(_rule_rationale(rule))


def _secondary_rationale_text(entry: SecondaryRationale) -> str:
    text = entry.justification or entry.statement_text
    return _normalized_sentence(text)


def _score_secondary_rationale(query: str, lead_rule: ChatRule, entry: SecondaryRationale) -> int:
    query_terms = _query_terms(query)
    material_terms = _query_material_terms(query)
    statement_terms = set(_tokenize(entry.statement_text))
    anchor_terms = statement_terms.union(set(_tokenize(" ".join([*entry.keywords, *entry.applies_to]))))
    if material_terms and not material_terms.intersection(anchor_terms):
        return 0

    focus_terms = query_terms.union(set(_tokenize(" ".join([lead_rule.subject, lead_rule.statement_text]))))
    full_text = " ".join([entry.statement_text, entry.justification, *entry.keywords, *entry.applies_to])
    full_terms = set(_tokenize(full_text))
    score = len(focus_terms.intersection(full_terms)) * 2
    score += _phrase_score(material_terms or query_terms, entry.statement_text)
    score += _phrase_score(material_terms or query_terms, entry.justification)
    if material_terms.intersection(statement_terms):
        score += 4
    if any(marker in entry.statement_text.lower() for marker in ("shall not", "must not")):
        score += 2
    if set(_tokenize(entry.justification)).intersection(_RATIONALE_SIGNAL_TOKENS):
        score += 4
    return score


def _retrieve_secondary_rationale(query: str, lead_rule: ChatRule) -> SecondaryRationale | None:
    best_entry: SecondaryRationale | None = None
    best_score = 0
    for entry in _secondary_rationale_entries():
        score = _score_secondary_rationale(query, lead_rule, entry)
        if score > best_score:
            best_entry = entry
            best_score = score
    # WHY 8: a single material hit is not enough to cite a cross-standard
    # rationale. Oracle only uses secondary rationale when the match includes
    # the material anchor plus additional phrase or signal support.
    return best_entry if best_score >= 8 else None


def _material_scope_label(material_terms: set[str]) -> str:
    ordered = sorted(material_terms)
    if not ordered:
        return "the broader material topic"
    if len(ordered) == 1:
        return f"all {ordered[0]} uses"
    return "all uses of " + ", ".join(ordered[:-1]) + f", and {ordered[-1]}"


def _scope_note(query: str, pack: ChatPack, lead_rule: ChatRule) -> str:
    query_terms = _query_terms(query)
    if query_terms.intersection(_CONNECTOR_SCOPE_TERMS):
        return ""
    rule_terms = set(
        _tokenize(" ".join([lead_rule.statement_text, lead_rule.subject, *lead_rule.keywords, *lead_rule.applies_to]))
    )
    if not rule_terms.intersection(_CONNECTOR_SCOPE_TERMS):
        return ""
    material_label = _material_scope_label(_query_material_terms(query))
    return (
        f"The retrieved {pack.standard_id} clauses here are specific to connectors and connector accessories; "
        f"they do not establish a blanket ban on {material_label}."
    )


def _build_why_context(query: str, pack: ChatPack, top_matches: list[tuple[ChatRule, int]]) -> dict[str, Any]:
    if not _is_why_query(query) or not top_matches:
        return {}

    lead_rule = top_matches[0][0]
    context: dict[str, Any] = {}
    scope_note = _scope_note(query, pack, lead_rule)
    if scope_note:
        context["scope_note"] = scope_note

    if any(_rule_has_rationale(rule) for rule, _score in top_matches):
        return context

    secondary = _retrieve_secondary_rationale(query, lead_rule)
    if secondary is None:
        return context

    context["secondary_rationale"] = {
        "standard_id": secondary.standard_id,
        "standard_title": secondary.standard_title,
        "section": secondary.section,
        "page": secondary.page,
        "statement_text": secondary.statement_text,
        "justification": secondary.justification,
        "display_citation": _secondary_rationale_citation(secondary),
    }
    return context


def _append_why_context_lines(lines: list[str], why_context: dict[str, Any] | None) -> None:
    if not why_context:
        return

    scope_note = _normalize_space(why_context.get("scope_note"))
    if scope_note:
        lines.extend(["", f"Scope note: {scope_note}"])

    secondary = why_context.get("secondary_rationale")
    if not isinstance(secondary, dict):
        return
    rationale_text = _secondary_rationale_text(_secondary_rationale_from_context(secondary))
    standard_id = _normalize_space(secondary.get("standard_id"))
    if rationale_text and standard_id:
        lines.extend(["", f"Related engineering rationale from {standard_id}: {rationale_text}"])


def _append_why_context_evidence(
    citations: list[str],
    evidence: list[OracleEvidenceItem],
    why_context: dict[str, Any] | None,
) -> None:
    if not why_context:
        return
    secondary = why_context.get("secondary_rationale")
    if not isinstance(secondary, dict):
        return

    citation = _normalize_space(secondary.get("display_citation"))
    if not citation or citation in citations:
        return

    citations.append(citation)
    summary = _secondary_rationale_text(_secondary_rationale_from_context(secondary))
    evidence.append(
        OracleEvidenceItem(
            citation=citation,
            summary=f"Related engineering rationale: {summary}" if summary else "",
            statement_text=_normalize_space(secondary.get("statement_text")),
            standard_id=_normalize_space(secondary.get("standard_id")),
        )
    )


def _secondary_rationale_from_context(payload: dict[str, Any]) -> SecondaryRationale:
    return SecondaryRationale(
        standard_id=_normalize_space(payload.get("standard_id")),
        standard_title=_normalize_space(payload.get("standard_title")),
        section=_normalize_space(payload.get("section")),
        page=_coerce_page(payload.get("page")),
        statement_text=_normalize_space(payload.get("statement_text")),
        justification=_normalize_space(payload.get("justification")),
        keywords=tuple(_as_str_list(payload.get("keywords"))),
        applies_to=tuple(_as_str_list(payload.get("applies_to"))),
    )


def _is_pure_tin_rule(rule: ChatRule) -> bool:
    text = _rule_text(rule)
    return (
        "pure tin" in text
        or "tin whisker" in text
        or ("3% lead" in text and "tin" in text)
        or ("3 percent lead" in text and "tin" in text)
    )


def _first_matching_rule(
    matches: list[tuple[ChatRule, int]],
    predicate: Any,
) -> tuple[ChatRule, int] | None:
    for rule, score in matches:
        if predicate(rule):
            return rule, score
    return None


def _topic_answer_sentence(query: str, pack: ChatPack, top_matches: list[tuple[ChatRule, int]]) -> str:
    lead_rule = top_matches[0][0]
    lead_summary = _summarize_rule(lead_rule)
    stance = _rule_stance(lead_rule)
    topic = _normalize_space(_rule_topic(lead_rule))

    if _is_scope_funding_query(query):
        return (
            f"{pack.standard_id} routes this kind of scope-and-funding change into formal change control. "
            f"Lead requirement: {lead_summary}"
        )
    if _is_why_query(query):
        why_rule = next((rule for rule, _score in top_matches if _rule_has_rationale(rule)), lead_rule)
        why_stance = _rule_stance(why_rule)
        why_summary = _summarize_rule(why_rule)
        rationale = _rule_rationale(why_rule)

        if _has_inline_rationale(why_rule.statement_text):
            if why_stance == "prohibits":
                return f"No. {rationale}"
            if why_stance == "allows":
                return f"Yes, within the cited limits. {rationale}"
            return f"The cited reason in {pack.standard_id} is: {rationale}"

        if rationale:
            if why_stance == "prohibits":
                return f"No. {why_summary} The cited rationale is: {rationale}"
            if why_stance == "allows":
                return f"Yes, within the cited limits. {why_summary} The cited rationale is: {rationale}"
            return f"The cited reason in {pack.standard_id} is: {rationale}"

        if stance == "prohibits":
            return (
                f"No. {lead_summary} "
                "The retrieved clauses prohibit the use, but they do not state the technical rationale."
            )
        if stance == "allows":
            return (
                f"Yes, within the cited limits. {lead_summary} "
                "The retrieved clauses do not include a separate technical rationale."
            )
        return (
            f"The cited reason in {pack.standard_id} is not explicit in the retrieved clauses. "
            f"Lead requirement: {lead_summary}"
        )
    if _is_yes_no_query(query):
        if stance == "prohibits":
            return f"No. {lead_summary}"
        if stance == "allows":
            return f"Yes, within the limits of the cited clause. {lead_summary}"
        return f"The selected standard does not read as an informal yes. It {stance} the following: {lead_summary}"
    if _is_clause_lookup_query(query):
        if topic:
            return f"On {topic}, {pack.standard_id} says: {lead_summary}"
        return f"{pack.standard_id} says: {lead_summary}"
    return f"{pack.standard_id} answers this topic with: {lead_summary}"


def _render_pure_tin_guidance(
    *,
    pack: ChatPack,
    top_matches: list[tuple[ChatRule, int]],
) -> str:
    pure_tin_matches = [(rule, score) for rule, score in top_matches if _is_pure_tin_rule(rule)]

    prohibition_match = _first_matching_rule(pure_tin_matches, lambda rule: _rule_stance(rule) == "prohibits")
    test_match = _first_matching_rule(
        pure_tin_matches,
        lambda rule: "tested internally and externally for pure tin" in _rule_text(rule),
    )
    lot_test_match = _first_matching_rule(
        pure_tin_matches,
        lambda rule: (
            "tested internally and externally for pure tin" in _rule_text(rule)
            and "non qpl" in _rule_text(rule)
        ),
    )
    mitigation_match = _first_matching_rule(
        pure_tin_matches,
        lambda rule: any(token in _rule_text(rule) for token in ("solder dip", "ipc j-std-001es", "mitigat")),
    )
    lead_threshold_match = _first_matching_rule(
        pure_tin_matches,
        lambda rule: any(token in _rule_text(rule) for token in ("3% lead", "3 percent lead")),
    )

    lines = [
        f"{pack.standard_id} treats pure tin as a hazard-avoidance issue, not a routine use-as-is condition.",
        "",
        "What to do next:",
    ]

    if prohibition_match:
        lines.append(
            "- Check whether this part family or finish falls under the pack's pure-tin prohibition. If it does, do not use it as-is."
        )
    if test_match:
        lines.append(
            "- If pure tin is not already precluded by the governing spec or control document, test internally and externally for pure tin."
        )
    if lot_test_match:
        lines.append(
            "- For non-QPL/QML/QPD lots, the DPA samples also need internal and external pure-tin testing."
        )
    if mitigation_match:
        lines.append(
            "- If the finish fails the cited 3% lead threshold, follow the pack's mitigation path before use; the preferred path is solder dip, with the cited workmanship mitigation as the fallback."
        )
    elif lead_threshold_match:
        lines.append(
            "- Confirm whether the finish meets the cited 3% lead threshold before treating it as usable."
        )

    lines.extend(
        [
            "",
            "Do not treat pure Sn as automatically usable. Use the cited clauses to determine whether the finish is prohibited outright, requires pure-tin testing, or needs documented mitigation before use.",
        ]
    )
    return "\n".join(lines).strip()


def _render_grounded_pack_answer(
    *,
    query: str,
    pack: ChatPack,
    top_matches: list[tuple[ChatRule, int]],
    why_context: dict[str, Any] | None = None,
) -> str:
    pure_tin_matches = [(rule, score) for rule, score in top_matches if _is_pure_tin_rule(rule)]
    if _is_pure_tin_action_query(query) and len(pure_tin_matches) >= 2:
        return _render_pure_tin_guidance(pack=pack, top_matches=top_matches)

    lines = [_topic_answer_sentence(query, pack, top_matches)]
    _append_why_context_lines(lines, why_context)
    related_summaries: list[str] = []
    lead_summary = _summarize_rule(top_matches[0][0])
    for rule, _score in top_matches[1:3]:
        summary = _summarize_rule(rule)
        if summary != lead_summary and summary not in related_summaries:
            related_summaries.append(summary)

    if related_summaries:
        lines.append("")
        if len(related_summaries) == 1:
            lines.append("Also relevant here:")
        else:
            lines.append("Two related clauses also matter here:")
        for summary in related_summaries:
            lines.append(f"- {summary}")

    if _is_scope_funding_query(query):
        lines.append("")
        lines.append("That points you into formal TOCR/change-control handling rather than an informal scope insert.")
    return "\n".join(lines).strip()


def _render_compare_answer(
    *,
    query: str,
    packs: list[ChatPack],
    findings: list[dict[str, Any]],
) -> str:
    lines = ["Comparison across selected standards.", ""]
    for finding in findings:
        pack = finding["pack"]
        matches = finding["matches"]
        if not matches:
            lines.append(f"{pack.standard_id}: No grounded requirement match found for this topic.")
            lines.append("")
            continue

        lead_rule = matches[0][0]
        lines.append(f"{pack.standard_id}: {_topic_answer_sentence(query, pack, matches)}")
        for rule, _score in matches[:2]:
            lines.append(f"- {_summarize_rule(rule)} ({_citation(rule)})")
        lines.append("")
    return "\n".join(lines).strip()


def _review_only_findings(query: str) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []

    if _VAGUE_TERM_PATTERN.search(query):
        findings.append(
            (
                "ambiguity",
                "The wording uses vague qualifiers like 'appropriate', 'sufficient', or 'as needed' without a measurable boundary.",
            )
        )

    if _ACTION_PATTERN.search(query) and not _OWNER_PATTERN.search(query):
        findings.append(
            (
                "omission",
                "The draft names an action but not a clear accountable actor, so ownership is easy to dispute later.",
            )
        )

    if _ACTION_PATTERN.search(query) and not _MEASURE_PATTERN.search(query):
        findings.append(
            (
                "testability",
                "The requirement is hard to verify because it does not name acceptance criteria, a deadline, or an observable artifact.",
            )
        )

    if _REVIEW_GOVERNANCE_PATTERN.search(query):
        findings.append(
            (
                "governance",
                "The text invokes approval or acceptance, but it should also name the approving role and the entry or exit criteria for that decision.",
            )
        )

    if _CHANGE_CONTROL_PATTERN.search(query) and not _IMPACT_PATTERN.search(query):
        findings.append(
            (
                "scope",
                "The text changes scope or baselines without saying what downstream approvals, artifacts, funding, cost, or schedule impacts must be updated.",
            )
        )

    return findings


def _answer_review_only(query: str, compare_only: bool) -> dict[str, Any]:
    if compare_only:
        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query=query,
                intent="review_only",
                selected_packs=[],
                compare_only=False,
                review_only=True,
                missing_inputs=[
                    "Turn off review-only mode if you want a standards comparison.",
                ],
                follow_ups=[
                    "Turn off review-only and compare the selected packs.",
                    "Paste two draft clauses and ask which one is tighter.",
                ],
                draft_answer_text=(
                    "Review-only mode does not compare authority packs. Switch back to authority-grounded mode to compare standards, "
                    "or paste two draft clauses and ask for a wording comparison."
                ),
            )
        )

    findings = _review_only_findings(query)
    if not findings:
        return _emit_envelope(
            OracleChatEnvelope(
                status="PASS",
                query=query,
                intent="review_only",
                selected_packs=[],
                compare_only=False,
                review_only=True,
                follow_ups=[
                    "Review this requirement for ambiguity and missing acceptance criteria: <paste text>",
                    "Rewrite this clause so it is testable and names the responsible actor.",
                ],
                draft_answer_text=(
                    "Review-only assessment. No authority packs were applied. I do not see a strong defect signal from the text you sent, "
                    "but review-only mode is much stronger when you paste the actual requirement, paragraph, or approval language to inspect."
                ),
            )
        )

    top_findings = findings[:3]
    lines = [
        "Review-only assessment. No authority packs were applied.",
        "",
        "Top issues in the draft wording:",
    ]
    for idx, (_category, detail) in enumerate(top_findings, start=1):
        lines.append(f"{idx}. {detail}")
    lines.extend(
        [
            "",
            "Bottom line:",
            "This reads more like direction than an enforceable requirement. Tighten the actor, trigger, measurable outcome, and any approval or change-control gates.",
        ]
    )

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=query,
            intent="review_only",
            selected_packs=[],
            compare_only=False,
            review_only=True,
            citations=[f"review-only/{category}" for category, _detail in top_findings],
            evidence=[
                OracleEvidenceItem(citation=f"review-only/{category}", summary=detail)
                for category, detail in top_findings
            ],
            follow_ups=[
                "Rewrite this requirement in a tighter, testable form.",
                "Show me the missing approvals, artifacts, and acceptance criteria in this draft.",
            ],
            draft_answer_text="\n".join(lines).strip(),
        )
    )


def _chat_result(
    *,
    status: str,
    response: str,
    citations: list[str],
    follow_ups: list[str],
    selected_packs: list[str],
    compare_only: bool,
    review_only: bool,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ordered_stage_keys = ["gatekeeper", "retrieval", "reasoning", "summary"]
    stages_completed = []
    if stage_artifacts:
        stages_completed = [key for key in ordered_stage_keys if key in stage_artifacts]
    merged_diagnostics = {
        "fallback_used": False,
        "fallback_reason": None,
        "validation_failures": [],
        "stages_completed": stages_completed,
    }
    if diagnostics:
        merged_diagnostics.update(diagnostics)
        if "stages_completed" not in diagnostics:
            merged_diagnostics["stages_completed"] = stages_completed

    result = {
        "envelope_version": "1.0",
        "status": status,
        "answer_text": response,
        "response": response,
        "evidence_assessment": evidence_assessment,
        "citations": citations,
        "follow_ups": follow_ups,
        "selected_packs": selected_packs,
        "compare_only": compare_only,
        "review_only": review_only,
        "advisory_only": True,
        "diagnostics": merged_diagnostics,
    }
    if stage_artifacts:
        result["stage_artifacts"] = _json_safe_artifact(stage_artifacts)
    return result


def _evidence_item(
    *,
    rule: ChatRule,
    score: int | None = None,
) -> OracleEvidenceItem:
    return OracleEvidenceItem(
        citation=_citation(rule),
        summary=_summarize_rule(rule),
        statement_text=rule.statement_text,
        topic=rule.subject,
        standard_id=rule.standard_id,
        score=score,
    )


def _serialize_chat_pack(pack: ChatPack) -> dict[str, Any]:
    return {
        "pack_slug": pack.pack_slug,
        "standard_id": pack.standard_id,
        "standard_title": pack.standard_title,
        "rule_count": len(pack.rules),
    }


def _json_safe_artifact(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, ChatPack):
        return _serialize_chat_pack(value)
    if isinstance(value, ChatRule):
        return _serialize_rule(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_artifact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_artifact(item) for item in value]
    if isinstance(value, tuple):
        if len(value) == 2 and isinstance(value[0], ChatRule):
            return _serialize_rule(value[0], value[1])
        return [_json_safe_artifact(item) for item in value]
    if is_dataclass(value):
        return _json_safe_artifact(value.__dict__)
    return str(value)


def _emit_envelope(envelope: OracleChatEnvelope) -> dict[str, Any]:
    formatted = format_chat_response(envelope, allow_draft_answer=True)
    grade = grade_chat_response(formatted, envelope)

    diagnostics = dict(envelope.diagnostics or {})
    validation_failures = list(diagnostics.get("validation_failures", []))
    if not grade.passed:
        validation_failures.extend(grade.failures)
        diagnostics["fallback_used"] = True
        diagnostics["fallback_reason"] = diagnostics.get("fallback_reason") or "formatter_grader_failure"
        diagnostics["validation_failures"] = validation_failures
        formatted = format_chat_response(envelope, allow_draft_answer=False)
    elif "validation_failures" not in diagnostics:
        diagnostics["validation_failures"] = validation_failures

    return _chat_result(
        status=envelope.status,
        response=formatted,
        citations=envelope.citations_or_authority(),
        follow_ups=envelope.follow_ups,
        selected_packs=envelope.selected_packs,
        compare_only=envelope.compare_only,
        review_only=envelope.review_only,
        evidence_assessment=envelope.evidence_assessment,
        diagnostics=diagnostics,
        stage_artifacts=envelope.stage_artifacts,
    )


def _chat_model_provider() -> str | None:
    explicit = _normalize_space(os.environ.get("ORACLE_CHAT_PROVIDER"))
    if explicit:
        return explicit.lower()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def _reasoning_model_name(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("ORACLE_REASONING_MODEL", "gpt-5.4")
    return os.environ.get("ORACLE_REASONING_MODEL", "claude-sonnet-4-6")


def _summary_model_name(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("ORACLE_SUMMARY_MODEL", "gpt-5.4-mini")
    return os.environ.get("ORACLE_SUMMARY_MODEL", "claude-haiku-4-5-20251001")


def _extract_text_blocks(blocks: Any) -> str:
    text_parts: list[str] = []
    if isinstance(blocks, str):
        return blocks.strip()
    for block in blocks or []:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            text_parts.append(str(block.text))
    return "\n".join(part.strip() for part in text_parts if part.strip()).strip()


def _call_model_json(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
) -> dict[str, Any]:
    if provider == "anthropic":
        import httpx
        from anthropic import Anthropic

        client = Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = _extract_text_blocks(response.content)
    elif provider == "openai":
        import httpx
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if model.startswith(("gpt-5", "o3", "o4")):
            kwargs["max_completion_tokens"] = max_tokens
            kwargs["reasoning_effort"] = os.environ.get("ORACLE_CHAT_REASONING_EFFORT", "medium")
            kwargs["verbosity"] = os.environ.get("ORACLE_CHAT_VERBOSITY", "medium")
        else:
            kwargs["temperature"] = 0.0
            kwargs["max_tokens"] = max_tokens
        response = client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
    else:
        raise RuntimeError(f"Unsupported chat provider: {provider}")

    if not text:
        raise RuntimeError("Chat model returned empty response.")
    return json.loads(text)


def _serialize_rule(rule: ChatRule, score: int | None = None) -> dict[str, Any]:
    payload = {
        "pack_slug": rule.pack_slug,
        "standard_id": rule.standard_id,
        "standard_title": rule.standard_title,
        "rule_id": rule.rule_id,
        "section": rule.section,
        "page": rule.page,
        "obligation_type": rule.obligation_type,
        "statement_text": rule.statement_text,
        "requirement": rule.requirement,
        "justification": rule.justification,
        "subject": rule.subject,
        "keywords": list(rule.keywords),
        "applies_to": list(rule.applies_to),
        "display_citation": _citation(rule),
    }
    if score is not None:
        payload["score"] = score
    return payload


def _llm_reasoning_system_prompt() -> str:
    return (
        "You are the Oracle reasoning stage. "
        "You reason only over the retrieved rules provided by the caller. "
        "Do not invent requirements. Do not issue approval, waiver, certification, or sign-off decisions. "
        "If a retrieved rule includes justification or inline rationale, use that for why-questions. "
        "If the retrieved rules only prohibit something without explaining why, say that explicitly instead of inventing a rationale. "
        "Return strict JSON with keys: direct_answer, bottom_line, why, governing_citations, gaps, follow_ups, per_pack_findings. "
        "governing_citations must only contain exact display_citation strings from the input payload. "
        "why and gaps must be arrays of concise strings. "
        "per_pack_findings must be an array of objects with keys standard_id, finding, citations."
    )


def _llm_summary_system_prompt() -> str:
    return (
        "You are the Oracle summary stage. "
        "Convert the reasoning payload into concise operator guidance. "
        "Lead with the direct answer or bottom line. "
        "Do not invent claims or citations. "
        "Return strict JSON with keys: answer_text, citations, follow_ups. "
        "citations must be a subset of the provided governing citations. "
        "follow_ups must be short operator prompts."
    )


def _allowed_citations_from_retrieval(retrieval: dict[str, Any]) -> set[str]:
    citations: set[str] = set()
    if retrieval.get("compare_mode"):
        for finding in retrieval.get("pack_findings", []):
            for rule, _score in finding.get("matches", []):
                citations.add(_citation(rule))
    else:
        for rule, _score in retrieval.get("matches", []):
            citations.add(_citation(rule))
    return citations


def _maybe_run_llm_reasoning(
    *,
    query: str,
    gatekeeper: dict[str, Any],
    retrieval: dict[str, Any],
) -> dict[str, Any] | None:
    provider = _chat_model_provider()
    if not provider:
        return None

    payload: dict[str, Any] = {
        "query": query,
        "intent": gatekeeper["intent"],
        "compare_mode": gatekeeper["compare_mode"],
        "filters": gatekeeper["filters"],
        "packs_queried": retrieval["packs_queried"],
    }
    if retrieval.get("compare_mode"):
        payload["matches_by_pack"] = [
            {
                "pack_slug": finding["pack"].pack_slug,
                "standard_id": finding["pack"].standard_id,
                "matches": [_serialize_rule(rule, score) for rule, score in finding["matches"]],
            }
            for finding in retrieval.get("pack_findings", [])
        ]
    else:
        payload["matches"] = [
            _serialize_rule(rule, score) for rule, score in retrieval.get("matches", [])
        ]

    try:
        result = _call_model_json(
            provider=provider,
            model=_reasoning_model_name(provider),
            system_prompt=_llm_reasoning_system_prompt(),
            user_message=json.dumps(payload, indent=2),
            max_tokens=int(os.environ.get("ORACLE_CHAT_REASONING_MAX_TOKENS", "2400")),
        )
    except Exception as exc:
        LOGGER.warning("Oracle reasoning model failed; using deterministic reasoning: %s", exc)
        return None

    allowed_citations = _allowed_citations_from_retrieval(retrieval)
    governing = [
        item for item in result.get("governing_citations", []) if isinstance(item, str) and item in allowed_citations
    ]
    if not governing:
        return None

    return {
        "provider": provider,
        "model": _reasoning_model_name(provider),
        "direct_answer": _normalize_space(result.get("direct_answer")),
        "bottom_line": _normalize_space(result.get("bottom_line")),
        "why": [item for item in result.get("why", []) if _normalize_space(item)],
        "gaps": [item for item in result.get("gaps", []) if _normalize_space(item)],
        "governing_citations": governing,
        "follow_ups": [item for item in result.get("follow_ups", []) if _normalize_space(item)][:3],
        "per_pack_findings": [
            {
                "standard_id": _normalize_space(item.get("standard_id")),
                "finding": _normalize_space(item.get("finding")),
                "citations": [
                    citation
                    for citation in item.get("citations", [])
                    if isinstance(citation, str) and citation in allowed_citations
                ],
            }
            for item in result.get("per_pack_findings", [])
            if isinstance(item, dict)
        ],
    }


def _maybe_run_llm_summary(
    *,
    query: str,
    gatekeeper: dict[str, Any],
    llm_reasoning: dict[str, Any],
) -> dict[str, Any] | None:
    provider = _chat_model_provider()
    if not provider:
        return None

    payload = {
        "query": query,
        "intent": gatekeeper["intent"],
        "compare_mode": gatekeeper["compare_mode"],
        "reasoning": llm_reasoning,
    }
    try:
        result = _call_model_json(
            provider=provider,
            model=_summary_model_name(provider),
            system_prompt=_llm_summary_system_prompt(),
            user_message=json.dumps(payload, indent=2),
            max_tokens=int(os.environ.get("ORACLE_CHAT_SUMMARY_MAX_TOKENS", "1200")),
        )
    except Exception as exc:
        LOGGER.warning("Oracle summary model failed; using deterministic summary: %s", exc)
        return None

    allowed = set(llm_reasoning["governing_citations"])
    citations = [
        item for item in result.get("citations", []) if isinstance(item, str) and item in allowed
    ]
    answer_text = _normalize_space(result.get("answer_text"))
    if not answer_text or not citations:
        return None
    return {
        "provider": provider,
        "model": _summary_model_name(provider),
        "answer_text": answer_text,
        "citations": citations,
        "follow_ups": [
            item for item in result.get("follow_ups", []) if _normalize_space(item)
        ][:3],
    }


def _validate_llm_reasoning_output(
    llm_reasoning: dict[str, Any],
    retrieval: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if not _normalize_space(llm_reasoning.get("direct_answer")) and not _normalize_space(
        llm_reasoning.get("bottom_line")
    ):
        failures.append("stage_3_missing_answer")

    allowed_citations = _allowed_citations_from_retrieval(retrieval)
    governing = llm_reasoning.get("governing_citations", [])
    if not governing:
        failures.append("stage_3_missing_citations")
    elif any(citation not in allowed_citations for citation in governing):
        failures.append("stage_3_unknown_citation")

    for field in ("why", "gaps", "follow_ups"):
        value = llm_reasoning.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            failures.append(f"stage_3_invalid_{field}")

    per_pack = llm_reasoning.get("per_pack_findings", [])
    if per_pack and not isinstance(per_pack, list):
        failures.append("stage_3_invalid_per_pack_findings")
    elif isinstance(per_pack, list):
        for item in per_pack:
            if not isinstance(item, dict):
                failures.append("stage_3_invalid_per_pack_findings")
                break
            citations = item.get("citations", [])
            if not isinstance(citations, list) or any(citation not in allowed_citations for citation in citations):
                failures.append("stage_3_invalid_per_pack_citations")
                break

    return failures


def _validate_llm_summary_output(
    llm_summary: dict[str, Any],
    llm_reasoning: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    answer_text = _normalize_space(llm_summary.get("answer_text"))
    if not answer_text:
        failures.append("stage_4_missing_answer")
    elif _PROHIBITED_DECISION_LANGUAGE_PATTERN.search(answer_text):
        failures.append("stage_4_prohibited_decision_language")

    allowed_citations = set(llm_reasoning.get("governing_citations", []))
    citations = llm_summary.get("citations", [])
    if not citations:
        failures.append("stage_4_missing_citations")
    elif any(citation not in allowed_citations for citation in citations):
        failures.append("stage_4_unknown_citation")

    follow_ups = llm_summary.get("follow_ups", [])
    if follow_ups and (
        not isinstance(follow_ups, list) or any(not isinstance(item, str) for item in follow_ups)
    ):
        failures.append("stage_4_invalid_follow_ups")

    return failures


def _gatekeep_query(query: str, pack_names: list[str], compare_only: bool) -> dict[str, Any]:
    if _APPROVAL_PATTERN.search(query):
        return {
            "status": "REFUSE",
            "intent": None,
            "normalized_query": query,
            "selected_packs": list(pack_names),
            "compare_mode": compare_only,
            "filters": {
                "section": _SECTION_PATTERN.search(query).group(1)
                if _SECTION_PATTERN.search(query)
                else None,
                "table_note": (
                    f"table {_TABLE_NOTE_PATTERN.search(query).group(1)} note {_TABLE_NOTE_PATTERN.search(query).group(2)}"
                    if _TABLE_NOTE_PATTERN.search(query)
                    else None
                ),
            },
            "refusal_category": "approval",
            "refusal_reason": (
                "Oracle can surface governing clauses and evidence paths, but it does not issue final approval, "
                "certification, waiver, or sign-off decisions."
            ),
        }

    if not pack_names:
        return {
            "status": "INSUFFICIENT_DATA",
            "intent": None,
            "normalized_query": query,
            "selected_packs": [],
            "compare_mode": compare_only,
            "filters": {"section": None, "table_note": None},
            "refusal_category": None,
            "refusal_reason": None,
            "error": "Select at least one authority pack before chatting. Oracle stays grounded in the packs you pick.",
        }

    intent = "general"
    if compare_only or _COMPARE_PATTERN.search(query):
        intent = "comparison"
    elif _is_clause_lookup_query(query):
        intent = "clause_lookup"
    elif _is_yes_no_query(query):
        intent = "yes_no"

    section_match = _SECTION_PATTERN.search(query)
    table_note_match = _TABLE_NOTE_PATTERN.search(query)

    return {
        "status": "PASS",
        "intent": intent,
        "normalized_query": query,
        "selected_packs": list(pack_names),
        "compare_mode": bool(compare_only or intent == "comparison"),
        "filters": {
            "section": _normalize_space(section_match.group(1)) if section_match else None,
            "table_note": (
                f"table {table_note_match.group(1)} note {table_note_match.group(2)}"
                if table_note_match
                else None
            ),
        },
        "refusal_category": None,
        "refusal_reason": None,
    }


def _retrieve_chat_context(gatekeeper: dict[str, Any], pack_dir: Path) -> dict[str, Any]:
    selected_packs = gatekeeper["selected_packs"]
    query = gatekeeper["normalized_query"]
    compare_mode = bool(gatekeeper["compare_mode"])
    packs_queried: list[dict[str, Any]] = []
    loaded_packs: list[ChatPack] = []

    for pack_name in selected_packs:
        try:
            pack = load_chat_pack(pack_name, pack_dir)
        except Exception as exc:
            packs_queried.append(
                {
                    "pack_slug": pack_name,
                    "load_status": "error",
                    "load_error": str(exc),
                }
            )
            continue

        loaded_packs.append(pack)
        packs_queried.append(
            {
                "pack_slug": pack.pack_slug,
                "standard_id": pack.standard_id,
                "standard_title": pack.standard_title,
                "load_status": "ok",
            }
        )

    if not loaded_packs:
        return {
            "status": "INSUFFICIENT_DATA",
            "error": "None of the selected packs could be loaded for Oracle chat.",
            "packs_queried": packs_queried,
            "compare_mode": compare_mode,
        }

    if len(loaded_packs) > 1 and not compare_mode:
        return {
            "status": "INSUFFICIENT_DATA",
            "error": (
                "Multiple packs are selected. Narrow to one pack for clause lookup or turn on compare mode to chat across selected standards."
            ),
            "packs_queried": packs_queried,
            "compare_mode": compare_mode,
            "loaded_packs": loaded_packs,
        }

    if compare_mode:
        pack_findings: list[dict[str, Any]] = []
        for pack in loaded_packs[:2]:
            matches = _dedupe_rules(_rank_rules(query, pack.rules), 3)
            pack_findings.append({"pack": pack, "matches": matches})

        if not any(item["matches"] for item in pack_findings):
            return {
                "status": "INSUFFICIENT_DATA",
                "error": "I did not find grounded requirement matches for that topic in the selected standards.",
                "packs_queried": packs_queried,
                "compare_mode": True,
                "pack_findings": pack_findings,
            }

        return {
            "status": "PASS",
            "packs_queried": packs_queried,
            "compare_mode": True,
            "pack_findings": pack_findings,
        }

    pack = loaded_packs[0]
    matches = _rank_rules(query, pack.rules)
    if not matches:
        return {
            "status": "INSUFFICIENT_DATA",
            "error": (
                f"I found {pack.standard_id}, but I did not find a grounded requirement match for that topic. "
                "Narrow this by section, table note, appendix, or part family."
            ),
            "packs_queried": packs_queried,
            "compare_mode": False,
            "pack": pack,
            "matches": [],
        }

    return {
        "status": "PASS",
        "packs_queried": packs_queried,
        "compare_mode": False,
        "pack": pack,
        "matches": matches,
    }


def _reason_about_chat_context(query: str, gatekeeper: dict[str, Any], retrieval: dict[str, Any]) -> dict[str, Any]:
    if retrieval["compare_mode"]:
        pack_reasoning: list[dict[str, Any]] = []
        for finding in retrieval["pack_findings"]:
            pack = finding["pack"]
            top_matches = finding["matches"]
            pack_reasoning.append(
                {
                    "pack": pack,
                    "top_matches": top_matches,
                    "evidence_assessment": "supported" if top_matches else "insufficient_data",
                    "bottom_line": (
                        f"{pack.standard_id} contains grounded rules for this topic."
                        if top_matches
                        else f"{pack.standard_id} did not surface grounded rules for this topic."
                    ),
                }
            )
        return {
            "status": "PASS",
            "answer_type": "comparison",
            "pack_reasoning": pack_reasoning,
            "retrieval_coverage": "partial"
            if any(item.get("load_status") == "error" for item in retrieval["packs_queried"])
            else "complete",
        }

    pack = retrieval["pack"]
    matches = retrieval["matches"]
    top_matches = _dedupe_rules(
        matches,
        5 if gatekeeper["intent"] == "clause_lookup" or _is_pure_tin_action_query(query) or _is_why_query(query) else 3,
    )
    return {
        "status": "PASS",
        "answer_type": "lookup" if gatekeeper["intent"] == "clause_lookup" else gatekeeper["intent"],
        "pack": pack,
        "top_matches": top_matches,
        "evidence_assessment": "supported",
        "retrieval_coverage": "complete",
        "bottom_line": (
            "If the scope insertion changes the work and carries cost or funding consequences, the retrieved rules point you into formal TOCR handling."
            if _is_scope_funding_query(query)
            else (
                f"{pack.standard_id} contains grounded rules that answer this question."
                if gatekeeper["intent"] != "clause_lookup"
                else f"{pack.standard_id} contains grounded governing clauses for this topic."
            )
        ),
        "gaps": (
            ["The question does not say whether the cost impact was formally documented."]
            if _is_scope_funding_query(query)
            else []
        ),
    }


def _build_single_pack_synthesis(
    query: str,
    pack: ChatPack,
    matches: list[tuple[ChatRule, int]],
    *,
    why_context: dict[str, Any] | None = None,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pure_tin_action = _is_pure_tin_action_query(query)
    top_matches = _dedupe_rules(matches, 5 if pure_tin_action or _is_why_query(query) else 3)
    citations = [_citation(rule) for rule, _score in top_matches]
    evidence = [_evidence_item(rule=rule, score=score) for rule, score in top_matches]
    _append_why_context_evidence(citations, evidence, why_context)
    if pure_tin_action and len([rule for rule, _score in top_matches if _is_pure_tin_rule(rule)]) >= 2:
        follow_ups = [
            f"Show me the pure tin avoidance clause in {pack.standard_id}.",
            f"List the test and mitigation steps for pure tin under {pack.standard_id}.",
        ]
    elif why_context and _normalize_space((why_context.get("secondary_rationale") or {}).get("display_citation")):
        follow_ups = [
            f"Show me the exact clause text for {citations[0]}.",
            (
                "Show me the related engineering rationale from "
                f"{_normalize_space((why_context.get('secondary_rationale') or {}).get('display_citation'))}."
            ),
        ]
    else:
        follow_ups = [
            f"Show me the exact clause text for {citations[0]}.",
            f"What would make this compliant under {pack.standard_id}?",
        ]
    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=query,
            intent="lookup",
            selected_packs=[pack.pack_slug],
            compare_only=False,
            review_only=False,
            authority_basis=[pack.standard_id],
            citations=citations,
            evidence=evidence,
            follow_ups=follow_ups,
            draft_answer_text=_render_grounded_pack_answer(
                query=query,
                pack=pack,
                top_matches=top_matches,
                why_context=why_context,
            ),
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
            metadata={
                "gaps": (
                    ["The question may need a narrower clause or section reference if your facts differ from the matched rule topic."]
                    if not _is_yes_no_query(query)
                    else []
                ),
            },
            wants_exact_text=_wants_exact_text(query),
        )
    )


def _compare_packs(
    message: str,
    packs: list[ChatPack],
    *,
    pack_findings: list[dict[str, Any]] | None = None,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    citations: list[str] = []
    findings = pack_findings or [{"pack": pack, "matches": _dedupe_rules(_rank_rules(message, pack.rules), 3)} for pack in packs]
    for finding in findings:
        for rule, _score in finding["matches"]:
            citation = _citation(rule)
            citations.append(citation)
    first = packs[0]
    follow_ups = [
        f"Which clause is stricter between {packs[0].standard_id} and {packs[1].standard_id}?",
        f"Show the exact governing text from {first.standard_id}.",
    ]
    evidence: list[OracleEvidenceItem] = []
    for finding in findings:
        pack = finding["pack"]
        matches = finding["matches"]
        for rule, score in matches[:2]:
            evidence.append(_evidence_item(rule=rule, score=score))
        if not matches:
            evidence.append(
                OracleEvidenceItem(
                    citation=pack.standard_id,
                    summary="No grounded requirement match found for this topic.",
                    standard_id=pack.standard_id,
                )
            )

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS" if citations else "INSUFFICIENT_DATA",
            query=message,
            intent="comparison",
            selected_packs=[pack.pack_slug for pack in packs],
            compare_only=True,
            review_only=False,
            authority_basis=[pack.standard_id for pack in packs],
            citations=citations or [pack.standard_id for pack in packs],
            evidence=evidence,
            follow_ups=follow_ups,
            draft_answer_text=_render_compare_answer(
                query=message,
                packs=packs,
                findings=findings,
            ),
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
        )
    )


def _build_clause_lookup_answer(
    query: str,
    pack: ChatPack,
    top_matches: list[tuple[ChatRule, int]],
    *,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    citations: list[str] = []
    for rule, _score in top_matches:
        citation = _citation(rule)
        citations.append(citation)

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=query,
            intent="clause_lookup",
            selected_packs=[pack.pack_slug],
            compare_only=False,
            review_only=False,
            authority_basis=[pack.standard_id],
            citations=citations,
            evidence=[_evidence_item(rule=rule, score=score) for rule, score in top_matches],
            follow_ups=[
                f"Show the exact requirement text from {citations[0]}.",
                f"List the top requirements in {pack.standard_id} for this topic.",
            ],
            draft_answer_text=_render_grounded_pack_answer(
                query=query,
                pack=pack,
                top_matches=top_matches,
            ),
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
            wants_exact_text=_wants_exact_text(query),
        )
    )


def _build_llm_guided_answer(
    *,
    llm_reasoning: dict[str, Any],
    llm_summary: dict[str, Any] | None,
    selected_packs: list[str],
    compare_only: bool,
    evidence_assessment: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    stage_artifacts: dict[str, Any],
) -> dict[str, Any]:
    response_lines: list[str] = []
    if llm_summary:
        response_lines.append(llm_summary["answer_text"])
    else:
        if llm_reasoning.get("direct_answer"):
            response_lines.append(llm_reasoning["direct_answer"])
        if llm_reasoning.get("bottom_line"):
            response_lines.append(llm_reasoning["bottom_line"])
        if llm_reasoning.get("why"):
            response_lines.append("")
            response_lines.append("Why:")
            for item in llm_reasoning["why"][:3]:
                response_lines.append(f"- {item}")
        if llm_reasoning.get("gaps"):
            response_lines.append("")
            response_lines.append("Gaps:")
            for item in llm_reasoning["gaps"][:2]:
                response_lines.append(f"- {item}")
        if compare_only and llm_reasoning.get("per_pack_findings"):
            response_lines.append("")
            response_lines.append("Per pack:")
            for item in llm_reasoning["per_pack_findings"]:
                if item.get("standard_id") and item.get("finding"):
                    response_lines.append(f"- {item['standard_id']}: {item['finding']}")

    citations = list(llm_summary["citations"] if llm_summary else llm_reasoning["governing_citations"])
    follow_ups = (
        llm_summary["follow_ups"]
        if llm_summary and llm_summary.get("follow_ups")
        else llm_reasoning.get("follow_ups", [])
    )
    evidence: list[OracleEvidenceItem] = []
    retrieval = (stage_artifacts or {}).get("retrieval", {})
    why_context = retrieval.get("why_context") if isinstance(retrieval, dict) else None
    match_groups = retrieval.get("matches_by_pack") or []
    for group in match_groups:
        for item in group.get("matches", [])[:2]:
            evidence.append(
                OracleEvidenceItem(
                    citation=item.get("display_citation", ""),
                    summary=item.get("requirement") or item.get("statement_text") or "",
                    statement_text=item.get("statement_text", ""),
                    topic=item.get("subject", ""),
                    standard_id=item.get("standard_id", ""),
                    score=item.get("score"),
                )
            )
    _append_why_context_evidence(citations, evidence, why_context)

    draft_answer = "\n".join(line for line in response_lines if line is not None).strip()
    if why_context:
        draft_lines = [draft_answer] if draft_answer else []
        _append_why_context_lines(draft_lines, why_context)
        draft_answer = "\n".join(draft_lines).strip()

    return _emit_envelope(
        OracleChatEnvelope(
            status="PASS",
            query=(stage_artifacts or {}).get("gatekeeper", {}).get("normalized_query", ""),
            intent="comparison" if compare_only else "lookup",
            selected_packs=selected_packs,
            compare_only=compare_only,
            review_only=False,
            authority_basis=[],
            citations=citations,
            evidence=evidence,
            follow_ups=follow_ups,
            draft_answer_text=draft_answer,
            evidence_assessment=evidence_assessment,
            diagnostics=diagnostics or {},
            stage_artifacts=stage_artifacts or {},
        )
    )


def answer_query(
    *,
    message: str,
    pack_names: list[str],
    pack_dir: Path,
    compare_only: bool = False,
    review_only: bool = False,
) -> dict[str, Any]:
    query = _normalize_space(message)
    if not query:
        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query="",
                intent="review_only" if review_only else "lookup",
                selected_packs=pack_names,
                compare_only=compare_only,
                review_only=review_only,
                missing_inputs=[
                    "A question, requirement, or draft clause to inspect.",
                ],
                draft_answer_text=(
                    "Oracle needs a question, requirement, or draft clause to inspect."
                    if review_only
                    else "Oracle needs a standards question to answer."
                ),
            )
        )

    if review_only:
        return _answer_review_only(query, compare_only)

    gatekeeper = _gatekeep_query(query, pack_names, compare_only)
    if gatekeeper["status"] == "REFUSE":
        return _emit_envelope(
            OracleChatEnvelope(
                status="REFUSE",
                query=query,
                intent="refusal",
                selected_packs=gatekeeper["selected_packs"],
                compare_only=bool(gatekeeper["compare_mode"]),
                review_only=False,
                draft_answer_text=gatekeeper["refusal_reason"],
                diagnostics={},
                stage_artifacts={"gatekeeper": gatekeeper},
            )
        )
    if gatekeeper["status"] == "INSUFFICIENT_DATA":
        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query=query,
                intent="lookup",
                selected_packs=gatekeeper["selected_packs"],
                compare_only=bool(gatekeeper["compare_mode"]),
                review_only=False,
                missing_inputs=[
                    "Select at least one authority pack for authority-grounded chat."
                ],
                draft_answer_text=gatekeeper["error"],
                stage_artifacts={"gatekeeper": gatekeeper},
            )
        )

    retrieval = _retrieve_chat_context(gatekeeper, pack_dir)
    if retrieval["status"] == "INSUFFICIENT_DATA":
        loaded_packs = retrieval.get("loaded_packs", [])
        follow_ups: list[str] = []
        citations: list[str] = []
        if loaded_packs:
            follow_ups = [
                f"Compare {loaded_packs[0].standard_id} and {loaded_packs[1].standard_id}.",
                f"Limit this question to {loaded_packs[0].standard_id}.",
            ]
            citations = [pack.standard_id for pack in loaded_packs[:2]]
        elif retrieval.get("pack"):
            pack = retrieval["pack"]
            follow_ups = [
                f"Show me the exact section in {pack.standard_id}.",
                f"List the top requirements in {pack.standard_id} for this topic.",
            ]
            citations = [pack.standard_id]

        return _emit_envelope(
            OracleChatEnvelope(
                status="INSUFFICIENT_DATA",
                query=query,
                intent=gatekeeper["intent"],
                selected_packs=gatekeeper["selected_packs"],
                compare_only=bool(gatekeeper["compare_mode"]),
                review_only=False,
                authority_basis=citations,
                citations=citations,
                missing_inputs=[
                    "A narrower topic, section, table note, appendix, or a different selected pack."
                ],
                follow_ups=follow_ups,
                draft_answer_text=retrieval["error"],
                stage_artifacts={"gatekeeper": gatekeeper, "retrieval": retrieval},
            )
        )

    reasoning = _reason_about_chat_context(query, gatekeeper, retrieval)
    stage_artifacts = {
        "gatekeeper": gatekeeper,
        "retrieval": {
            "compare_mode": retrieval["compare_mode"],
            "packs_queried": retrieval["packs_queried"],
            "matches": [
                _serialize_rule(rule, score) for rule, score in retrieval.get("matches", [])
            ],
            "matches_by_pack": [
                {
                    "pack_slug": finding["pack"].pack_slug,
                    "standard_id": finding["pack"].standard_id,
                    "matches": [_serialize_rule(rule, score) for rule, score in finding["matches"]],
                }
                for finding in retrieval.get("pack_findings", [])
            ],
        },
        "reasoning": {
            "answer_type": reasoning["answer_type"],
            "retrieval_coverage": reasoning["retrieval_coverage"],
            "evidence_assessment": reasoning.get("evidence_assessment"),
        },
    }
    diagnostics: dict[str, Any] = {
        "fallback_used": False,
        "fallback_reason": None,
        "validation_failures": [],
    }
    chat_provider = _chat_model_provider()

    llm_reasoning = None
    llm_summary = None
    if gatekeeper["intent"] != "clause_lookup":
        llm_reasoning = _maybe_run_llm_reasoning(
            query=query,
            gatekeeper=gatekeeper,
            retrieval=retrieval,
        )
        if llm_reasoning:
            reasoning_failures = _validate_llm_reasoning_output(llm_reasoning, retrieval)
            if reasoning_failures:
                diagnostics["fallback_used"] = True
                diagnostics["fallback_reason"] = "stage_3_validation_failure"
                diagnostics["validation_failures"].extend(reasoning_failures)
                llm_reasoning = None
            else:
                stage_artifacts["reasoning"]["llm_provider"] = llm_reasoning["provider"]
                stage_artifacts["reasoning"]["llm_model"] = llm_reasoning["model"]
                llm_summary = _maybe_run_llm_summary(
                    query=query,
                    gatekeeper=gatekeeper,
                    llm_reasoning=llm_reasoning,
                )
                if llm_summary:
                    summary_failures = _validate_llm_summary_output(llm_summary, llm_reasoning)
                    if summary_failures:
                        diagnostics["fallback_used"] = True
                        diagnostics["fallback_reason"] = "stage_4_validation_failure"
                        diagnostics["validation_failures"].extend(summary_failures)
                        llm_summary = None
                    else:
                        stage_artifacts["summary"] = {
                            "llm_provider": llm_summary["provider"],
                            "llm_model": llm_summary["model"],
                        }
                else:
                    diagnostics["fallback_used"] = True
                    diagnostics["fallback_reason"] = "stage_4_failure"
        elif chat_provider:
            diagnostics["fallback_used"] = True
            diagnostics["fallback_reason"] = "stage_3_failure"

    if reasoning["answer_type"] == "comparison":
        if llm_reasoning:
            return _build_llm_guided_answer(
                llm_reasoning=llm_reasoning,
                llm_summary=llm_summary,
                selected_packs=gatekeeper["selected_packs"][:2],
                compare_only=True,
                evidence_assessment=reasoning.get("evidence_assessment"),
                diagnostics=diagnostics,
                stage_artifacts=stage_artifacts,
            )
        return _compare_packs(
            query,
            [item["pack"] for item in reasoning["pack_reasoning"]],
            pack_findings=[
                {"pack": item["pack"], "matches": item["top_matches"]}
                for item in reasoning["pack_reasoning"]
            ],
            evidence_assessment=reasoning.get("evidence_assessment"),
            diagnostics=diagnostics,
            stage_artifacts=stage_artifacts,
        )

    pack = reasoning["pack"]
    top_matches = reasoning["top_matches"]
    why_context = _build_why_context(query, pack, top_matches)
    if why_context:
        stage_artifacts["retrieval"]["why_context"] = why_context
    if gatekeeper["intent"] == "clause_lookup":
        return _build_clause_lookup_answer(
            query,
            pack,
            top_matches,
            evidence_assessment=reasoning.get("evidence_assessment"),
            diagnostics=diagnostics,
            stage_artifacts=stage_artifacts,
        )

    if llm_reasoning:
        return _build_llm_guided_answer(
            llm_reasoning=llm_reasoning,
            llm_summary=llm_summary,
            selected_packs=[pack.pack_slug],
            compare_only=False,
            evidence_assessment=reasoning.get("evidence_assessment"),
            diagnostics=diagnostics,
            stage_artifacts=stage_artifacts,
        )

    return _build_single_pack_synthesis(
        query,
        pack,
        top_matches,
        why_context=why_context,
        evidence_assessment=reasoning.get("evidence_assessment"),
        diagnostics=diagnostics,
        stage_artifacts=stage_artifacts,
    )
