# Grounded Module Chat Playbook

## Purpose

This document captures the BoundState pattern for building module chat that:

- answers directly
- stays grounded in retrieved evidence
- sounds like an experienced engineer, not a machine report
- knows the user's current workflow position
- says "I do not know" when the evidence does not support more

The target is simple: a user should feel like they are talking to a senior operator who knows the standards, understands the module, and refuses to bluff.

## Core Principles

### 1. Separate Evidence From Voice

The voice can feel experienced and plainspoken. The facts cannot be improvised.

- Retrieval decides what is allowed to be said.
- Planning decides what kind of answer is needed.
- Voice decides how to phrase it for the human on the other end.

Never let personality create facts.

### 2. Retrieve Evidence Bundles, Not Just Rules

A good answer usually needs more than one clause. The retriever should assemble a bundle with distinct roles:

- governing rule
- rationale
- scope or applicability note
- exception or condition
- definition or terminology crosswalk

If Oracle retrieves only the governing rule, it can answer `what is required`, but it will struggle on `why`, `does this apply here`, and `what are the limits`.

### 3. Keep Scope Honest

Many bad answers are not factually false. They are too broad.

If the retrieved rule is connector-specific, say that.
If the retrieved rule is for crew or vacuum environments, say that.
If the retrieved rule does not establish a blanket ban, say that.

### 4. Use One Voice Layer

Use one wording layer after deterministic planning. Do not chain multiple generative passes unless each pass has a distinct contract and validation gate.

Preferred pattern:

1. retrieval
2. deterministic answer planner
3. single summary layer
4. validation

### 5. Show the Boundary When the Source Does Not Explain Why

Users trust the system more when it says:

- `The selected clause prohibits it, but it does not explain why.`
- `A related rationale source explains the technical reason.`

That is stronger than pretending the governing rule itself contained the rationale.

## Evidence Layers

### Governing Rules

These are the authority-bearing statements.

Use for:

- `can we`
- `must we`
- `what does the standard require`

Examples:

- `shall`
- `must`
- `shall not`
- `must not`
- `is required`
- `are required`
- `is prohibited`
- `are prohibited`

### Rationale Corpus

This layer explains the engineering reason behind a governing rule when the governing rule does not carry the rationale inline.

Use for:

- `why`
- hazard mechanism questions
- materials and process explanation

The rationale corpus must remain cited and distinct from the governing source.

### Scope and Applicability

This layer says where the rule applies and where it does not.

Use for:

- `does this apply here`
- `is this connector-specific`
- `is this only for crew/vacuum/human-rated hardware`

### Exceptions and Conditions

This layer captures:

- `unless`
- `except`
- `when applicable`
- table notes
- appendix notes
- conditional requirements

### Terminology Crosswalk

This layer maps shorthand and synonyms.

Examples:

- `Cd` -> `cadmium`
- `Sn` -> `tin`
- `pure Sn` -> `pure tin`
- `spaceflight hardware` -> may need expansion into connector, mission-critical, crew, vacuum, or contamination-control contexts

## Extraction Pattern

### Pass 1: Explicit Obligations

Capture binding language directly from the text, including passive voice.

Examples:

- `Records shall be retained`
- `The report must be submitted`
- `Supplier records are required to be retained`
- `Cadmium-plated tools are prohibited in vacuum service`

Passive voice is not the real problem. Missing obligation keywords are the real problem.

### Pass 1c: Implicit Obligations

Capture genuinely binding statements that do not use standard obligation keywords.

Examples:

- `Reports are due quarterly`
- `Testing follows MIL-STD-810`
- `The system operates at 5V`

This pass must stay conservative. False positives are worse than false negatives.

### Rationale Extraction

Capture:

- inline `because`, `due to`, `since`
- nearby `Rationale`, `Basis`, `Note`, `Justification`
- appendix rationale linked to the governing rule

### Scope and Exception Extraction

Capture:

- applicability paragraphs
- definitions
- table notes
- appendix notes
- exception language
- conditional gates like `when applicable`

## Answer Planning Contract

Before phrasing the answer, classify the question.

### `why`

Required bundle:

- governing basis
- technical reason, or an explicit statement that the governing clauses do not explain why
- scope note if the rule is narrower than the question

Target response shape:

1. direct answer
2. governing basis
3. scope qualifier if needed
4. technical reason

### `can we` / `is it allowed`

Required bundle:

- governing basis
- limiting condition
- exception if present

### `does this apply`

Required bundle:

- governing basis
- applicability evidence
- scope boundary
- exception if present

### `what do I do next`

Required bundle:

- governing basis
- required actions
- artifacts or evidence needed
- role or ownership when known

## Voice Layer

The voice should feel like:

- senior
- calm
- precise
- non-academic
- usable by a non-expert

The voice should not feel like:

- a legal memo
- a machine report
- an AI assistant explaining its process
- a standards scholar performing for other standards scholars

Preferred style:

- short sentences
- plain words
- one idea per sentence
- direct answer first

Good:

`No. In the selected MSFC-STD-3012A clauses, cadmium-plated connector accessories cannot be used in spaceflight. Those clauses are connector-specific, so they do not establish a blanket ban on all cadmium uses. NASA-STD-6016C gives the technical reason: cadmium can sublime in vacuum and contaminate nearby surfaces.`

Bad:

`Advisory. The retrieved clauses prohibit the use, but they do not state the technical rationale. Scope note: ... Related engineering rationale: ...`

## Validation Gates

Every final answer should pass these checks:

- each claim maps to retrieved evidence
- scope is not broader than the retrieved rule
- rationale is clearly marked as governing or supporting
- no approval, certification, waiver, or sign-off language
- no hidden assumptions about the user's hardware, mission class, or environment

If the system cannot satisfy the contract, it must say what is missing.

## Module Context Pattern

For module chat inside tools like MIRA:

- send current step
- send active field
- send known inputs
- send blockers
- send recent results
- send module identity

The model should answer from the user's current place in the workflow, not from a generic global assistant stance.

## Build Checklist

1. Define the question types the module chat must answer.
2. Define the evidence bundle required for each question type.
3. Build retrieval for governing rules first.
4. Add rationale, scope, exceptions, and terminology as separate layers.
5. Add a deterministic answer planner.
6. Add one wording layer with a bounded expert voice.
7. Add validation against over-claiming and unsupported rationale.
8. Add golden tests for the ugliest real questions users ask.

## Golden Test Set

Always keep tests for:

- passive explicit obligations
- implicit obligations
- rationale present
- rationale missing
- scope mismatch
- connector-specific vs blanket-material questions
- exceptions in notes and appendices
- non-expert user wording
- shorthand and aliases
- "what do I do next" workflow questions

## Standard Failure Modes

- answer is technically grounded but sounds robotic
- answer is readable but overclaims scope
- answer cites the rule but misses the rationale
- answer retrieves the rationale but treats it like the governing source
- answer ignores the user's workflow position
- answer gives clause text instead of operator guidance

The fix is usually not "add more LLM." The fix is usually "retrieve the right evidence role and plan the answer before wording."
