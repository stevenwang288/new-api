# Dispatcher Lane Recovery

## Purpose

The dispatcher keeps each lane independently available for round-robin requests. A lane that has exhausted quota or is temporarily rate limited is removed from selection until its recovery time, then automatically becomes eligible again.

## Classification Rules

- `QUOTA_EXHAUSTED` requires an upstream quota signal and an HTTP response in the rate-limit range, normally `429`.
- Generic `429` without an explicit quota signal is `COOLDOWN`.
- Network failures are `NETWORK_ERROR`; authentication failures are `AUTH_ERROR`; other upstream failures are `UNKNOWN_ERROR`.
- A keyword by itself is not sufficient. The classifier must use the status code and an explicit quota/exhaustion field or message.

## Recovery Time

The dispatcher stores an absolute Unix timestamp called `recovery_at`.

1. If the upstream supplies `Retry-After`, reset, resume, or an equivalent absolute timestamp, use it and mark `recovery_source` as `upstream`.
2. If the upstream supplies a duration such as hours, minutes, or seconds, calculate `recovery_at` from the time the response was received plus that duration. Mark it as `upstream` because the duration came from the upstream response.
3. If no recovery information exists, use the configured fallback cooldown and mark it as `estimated`.

The frontend never decrements and persists a counter. It calculates `max(0, recovery_at - current_time)` once per second, so the countdown stays correct after navigation, refreshes, and elapsed time.

## Automatic Re-entry

When `recovery_at` has passed, the lane is eligible for the next round-robin attempt. A successful request changes it to `READY`. A failed recovery request creates a new state and recovery timestamp from the new response. State is independent per lane, even when two lanes share a proxy IP.

## NewAPI Page

The admin-only `/dispatcher-status` page proxies the private dispatcher `/status` endpoint through `GET /api/channel/dispatcher/status`. It displays every returned lane dynamically:

- lane/container identifier;
- request, success, and error totals;
- current state;
- pause reason;
- absolute recovery time;
- live remaining countdown;
- whether recovery time is upstream-provided or estimated.

The page polls the API every five seconds and updates the countdown every second. NewAPI does not reclassify upstream errors; the dispatcher remains the source of truth.

## Operational Verification

Check the dispatcher status endpoint and confirm each lane includes `state`, `recovery_at`, and `recovery_source`. Triggering a controlled rate-limit response should remove only that lane from rotation. After the timestamp passes, the next successful request should return the lane to `READY`.
