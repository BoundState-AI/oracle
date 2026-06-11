# Structured Logging Adoption — Design Spec (EVAL CASE: known-sound)

## Overview

Migrate the order service from print-style logging to structured JSON
logging using the platform's standard logging library, over two releases.

## Approach

Release 1 introduces the structured logger alongside existing log calls,
behind the `STRUCTURED_LOGS` environment flag (default off). All new code
uses the structured logger. Release 2 flips the default on after one week
of canary comparison, then removes legacy calls.

## Field policy

Log entries carry: timestamp (UTC, RFC 3339), level, service name, request
ID, and a message. Customer-identifying data (names, emails, payment data)
is prohibited in log fields; the linter rule `no-pii-logs` enforces this in
CI and the policy is re-checked in code review.

## Rollback

Setting `STRUCTURED_LOGS=false` reverts to legacy behavior instantly; no
deploy is needed. Legacy calls are only deleted after two clean weeks at
100% structured output.

## Verification

A golden log-schema test asserts every emitted entry parses against the
JSON schema. Canary dashboards compare log volume and error rates between
cohorts during Release 2.
