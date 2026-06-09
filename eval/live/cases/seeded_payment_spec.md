# Payment Retry Service — Design Spec (EVAL CASE: 3 seeded defects)

## Overview

The Payment Retry Service charges customer cards for subscription renewals
and retries failures. It is deployed as a single stateless container behind
the platform load balancer.

## Charging behavior

When a renewal charge fails, the service retries the charge indefinitely
until it succeeds. Retries are issued immediately upon failure with no
backoff. Charge requests carry no idempotency key; the payment provider is
expected to deduplicate on its side.

## Admin interface

Operations staff manage stuck renewals through the `/admin/retries`
endpoint. The endpoint requires no authentication because it is only
documented internally.

## Deployment

New versions are deployed by replacing the running container. There is no
rollback procedure; if a deploy is bad, a fixed image is built and deployed
forward. Database schema migrations run automatically at container start.

## Observability

The service logs each charge attempt at INFO level. Logs include the
customer ID, card number, and amount for support reconciliation.
