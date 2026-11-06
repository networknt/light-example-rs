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


### Parity-suite stages 1–2 local continuation — 2026-10-22

[Code/results and remaining-gap table](/home/steve/workspace/artifacts/implementation/light-lambda/WP17-parity-stages12-20261022T214426Z/REPORT.md). Reused the existing Rust controlled backend and Java/Rust result-v1 runners; retained all11 prior local cases and expanded to14 selected/25 inventory cases (44 real application service steps,28 independent case-expectation passes). New coverage: binary/base64, repeated Set-Cookie order, opaque malformed-body passthrough, unknown-route zero-dispatch rejection and warm A/B recovery. Both gateways record21 local injected dependency calls; the separately executed backend records32 Runtime API requests/32 entries/30 completions, including real FunctionError runtime errors. This is local Init/service with injected clients, not gateway SDK dispatch into that backend executable or paired RIE/AWS qualification. Eleven deferred/unavailable inventory entries remain explicit.

A conformance-only header-declaration validator defect is repaired: names compare case-insensitively consistently with the existing differential comparator, while values/multiplicity/order and raw observations remain exact. No original fixture expectations or gateway production behavior changed. Checks:12 Python tests,4 backend Rust tests,19 contract tests,13 fixture/schema/canonical tests, strict conformance Clippy and focused formatting pass. Selected Validator remains non-green/unavailable with zero gateway service execution. Earlier runner/declaration/preflight failures are preserved in separate evidence directories. New debug/test binaries identified separately; deployed ZIPs/configuration and accepted ten-case AWS checkpoint unchanged. AWS cleanup remains a separate explicit decision. Validator, Router rewriting, paused experiments, observability promotion and full WP12/WP13/all-handler parity remain open.

Final whole-worktree diff-check note: exit2 at unrelated already-dirty `crates/light-security/Cargo.toml:29` (new blank line at EOF), not edited by this task. Scoped example/docs checks and touched conformance whitespace checks pass; affected tests/Clippy/formatting remain green.


### Gateway SDK to running parity backend — 2026-10-22

[Local integration report](/home/steve/workspace/artifacts/implementation/light-lambda/WP17-parity-integration-20261022T224001Z/REPORT.md), [prepared stage3 AWS scope](/home/steve/workspace/artifacts/implementation/light-lambda/parity-stage3-candidate-20261022T224001Z/AWS-SCOPE.md). All14 existing runnable cases pass through unchanged packaged Java/Rust executables, real SDK Invoke HTTP and two actual parity backend processes:28 independent case expectations/44 gateway requests/42 signed Invoke calls/42 backend executions and completions. Both unknown-route failures dispatch zero times and recover warm; echo-a38/echo-b4 executions, one gateway process per side, all four processes reaped. Full raw forwarding and response observations retain approved differences; all14 original expectations and the eleven deferred/unavailable inventory entries are unchanged. This is local owned Runtime API proof, not a new RIE or AWS run. Prior injected-client evidence/counts remain separate.

Native real-client Init required existing positive timeout settings and pinned layer3 config.yml/status.yml in separate test configuration; intermediate config/adapter failures are preserved. Seventeen Python tests and locked musl release build pass. Only the extra EOF blank line in light-security/Cargo.toml was removed; existing feature/dependency edits remain. Whole-worktree diff checks now pass. The new stage3 backend ZIP is7e274a5dbd17eba667a3a5d9235015f53bf0ffaede7b0d4b1794ebdbe92421dd (tested binary80b5151f…25e66), distinct from older backend package398197b3…7148a; accepted Java35122e39…77e7 and Rustd095e89c…756a ZIPs unchanged. New dedicated layers and exact four-function/narrow IAM scope are prepared only, with proposed :1 identities requiring actual readback/stop-on-drift after separate authorization. Local structural checks pass; cfn-lint unavailable, no AWS validation called. No AWS resources altered. Cleanup remains a separate explicit decision. Accepted ten-case AWS backend/JWKS counts stay unmeasured. Validator/rewrite, paused work, observability promotion, public ingress and full WP12/WP13/all-handler parity remain open.

Current stage3 approval package: [exact scope](/home/steve/workspace/artifacts/implementation/light-lambda/parity-stage3-review-20261022T224001Z/AWS-SCOPE.md), [review manifest](/home/steve/workspace/artifacts/implementation/light-lambda/parity-stage3-review-20261022T224001Z/review.json), review SHA-256 `8e06f9d3e72685a238936b167ba6fb4c4e71731d69f2e9c472378ebc875a074c`. It includes44 event files tied by digest to unchanged expectations. Existing candidate preparation remains historical. The tested release backend also passes32 independent direct Runtime API contract requests; do not merge these with42 gateway-to-backend executions. Future stack creation is proposed with on-failure DO_NOTHING to retain failures; cleanup still requires a separate decision. No AWS calls or resource changes.
