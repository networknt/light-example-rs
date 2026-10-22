# Initial parity delivery, 2026-10-22

## Review corrections, 2026-10-22

Both P2 findings were reproduced by failing regression tests before repair.
Evidence digests now exclude only the top-level generated report.json/report.md;
nested backend reports are sealed. The saved-run CLI rejects modified backend
execution counts even when passed remains true. Control parsing validates each
matching entry's cardinality and rejects case-duplicate names independently of
extracted values. Empty arrays are rejected, including mirrors of valid single
controls; matching nonempty single/multi mirrors remain supported.

Updated validation: eight Python tests, four Rust tests, strict backend Clippy,
focused rustfmt and diff checks pass. Fresh local run
`parity-review-fixes-20261022/report.json` passes all 11 selected cases, with
32 actual backend Runtime API invocations and 26 local gateway steps. Saved-run
comparison passes; changing backend counts in a temporary copy fails with
`saved evidence changed: backend/report.json`. Earlier runs remain historical
evidence with the old seal behavior. RIE and AWS qualification were not attempted.

The initial delivery record below describes the earlier artifact and test counts.

Scope: initial stages 1/2; stage 3 offline review candidates only. No AWS calls,
public ingress, deployment, commits or changes to accepted gateway artifacts.

## Results

- 11/23 inventory cases selected, all 11 intentional-difference-pass under the
  existing conformance comparator. 13 steps per gateway, 26 gateway executions.
- 32 actual packaged-backend Runtime API invocations across echo-a/echo-b,
  32 entry records and 30 completions (two genuine FunctionErrors).
- Original five-event trial contract also passes on the same final musl binary.
- Three Rust unit tests, seven Python suite tests, strict backend Clippy and
  focused rustfmt pass. Workspace-wide fmt detects an unrelated existing
  formatting discrepancy in demo-insurance-claim-mcp-server; it was preserved.
- Explicit Validator selection is non-green: one unavailable, 22 not-selected.
- Saved comparison verifies all sealed evidence hashes before readback.

## Evidence

Paired run: `parity-local-verified-20261022/report.json` and `report.md`.
Negative selection: `parity-unavailable-selection-20261022/report.json`.
Original compatibility: `parity-original-release-runtime-20261022/`.
Backend package: `parity-backend-package-20261022/`.
AWS review: `parity-aws-review-20261022/review.json` (deployable=false).
Earlier failures are retained under parity-local-first/loopback/contract paths.

Final backend binary SHA-256:
`2a7923b3897b9687a543c7a71454d2734421d814f8b194f5b8ae12299244704b`.
Backend ZIP SHA-256:
`398197b3f6d03cdcd5d430144f85dfd81ad1d3679ac728de27d8b3e27817148a`.

## Boundaries and remaining gates

This is proxy-only, application-authentication-disabled local evidence using the
existing injected dependencies. Their replies are bound to independently tested
backend results; there is no end-to-end gateway SDK to backend runtime claim.
Full original result-v1 files and full local dependency calls remain preserved.
The differences follow existing ledger contracts, including E-04 query decoding;
no production gateway defect was repaired or newly waived. Initial runner
expectation/default and sandbox errors were corrected in additive fresh runs.

Twelve inventory entries remain deferred/unavailable, with reasons in cases.json.
Paired RIE, AWS runtime/IAM/counting, templates/unknown routes, JWT/full-chain,
binary/cookie and malformed-envelope gateway profiles, timing and pet-store
qualification remain separate gates. No WP12/WP13 closure is claimed.

The four proposed function names are:
- `parity-20261022-review-echo-a`
- `parity-20261022-review-echo-b`
- `parity-20261022-review-java-gateway`
- `parity-20261022-review-rust-gateway`

Account 964637446810/us-east-2 is a review target only. The profile name is an
explicit placeholder, not a verified AWS session. Config layers, qualified
versions, regional charge estimates and execution/collection adapters remain
pending before owner authorization and any live work.
