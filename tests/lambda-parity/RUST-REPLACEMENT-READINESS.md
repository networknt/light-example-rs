# Rust replacement readiness — 2026-10-24

The unchanged Rust candidate is qualified for the named supported direct-Invoke subsets below. Java is a compatibility reference, not a correctness oracle. A Java-only defect or candidate build failure is not automatically a Rust release blocker. Full WP12/WP13, full native/sample compatibility and production readiness remain incomplete.

Current Rust ZIP: `/home/steve/workspace/artifacts/implementation/light-lambda/WP13-D08e-release-20261021T155728Z/release-package/bootstrap.zip`, SHA-256 `d095e89c07f6079823d6d07395b8716f280add5e7e09f7a75b1d03e121af756a`. It was verified and reused without rebuilding or replacing it. The observability candidate is not promoted.

## Intended configuration and boundary

The concrete supported configuration is `light-fabric-light-lambda/apps/light-lambda/deploy/l3/config`, the owner-selected direct-Invoke trial layer for account 964637446810/us-east-2. `lambda-petstore` is the example **backend**, not something that must be migrated or rewritten to call it. This is not customer-configuration qualification or full qualification of the native sample. Native full-sample admin/Validator requirements are retained separately rather than silently removed.

Requests use the existing supported ALB-shaped event JSON through direct Lambda Invoke. No ALB is created, and API Gateway-shaped input compatibility is not claimed. Function identities remain the four owner-approved unqualified ARNs (`$LATEST` on AWS):

| Route | Function suffix after `arn:aws:lambda:us-east-2:964637446810:function:` | OpenAPI scope |
|---|---|---|
| GET `/v1/pets` | `PetsGetFunction` | `portal.r` |
| GET `/v1/pets/{petId}` | `PetsPetIdGetFunction` | `portal.r` |
| POST `/v1/pets` | `PetsPostFunction` | `portal.r`, `portal.w` with existing ANY-match behavior |
| DELETE `/v1/pets/{petId}` | `PetsPetIdDeleteFunction` | `portal.w` |

The `/v1` server prefix is normalized for specification lookup; original prefixed paths are forwarded. Router rewriting is unnecessary for this path relationship. The scope implementation accepts any configured scope; consequently POST with `portal.r` alone succeeds. The existing behavior is explicitly characterized, not changed or presented as requiring both scopes. Whether a future write-only/AND policy is needed is a separate security-policy change.

Actual request chain: metrics → limit → correlation → requestCors → requestHeader → requestTransformer → audit → router → specification → security → sanitizer; default terminal proxy; response chain responseHeader → responseCors → responseTransformer. Admin paths and declarations are preserved. Token is configured disabled and is not inserted into this request chain. Transformers remain enabled only for `/x`, so pet-store requests do not execute their rules. Router has empty rewrite rules/direct registry. Validator is absent from this supported trial profile; schema validation is not claimed. In particular, parser rejection of malformed JSON does not demonstrate schema rejection of `{}` or required fields/headers.

## Requirement matrix

Rows overlap; do not add their counts into a full-suite or parity total.

| Requirement / handler | Pinned Rust evidence | Current conclusion and remaining gap |
|---|---|---|
| Bootstrap/package/configuration admission | Handoff: reproducible bootstrap-only candidate; layer validation; baseline/composed/LoggerSet RIE | Supported package identity unchanged. Offline Init is configuration coverage, not service proof. New local layer preserves the chain/spec and passes real admission. |
| Four pet-store mappings and supported direct event shape | Existing named AWS ten-case comparison: Rust10/10, Java10/10,10/10 approved pairs,0 byte-identical; new four actual backend echoes | Named AWS subset qualifies invocation of the example business functions. Its exact backend/JWKS counts remain unmeasured. New local counts do not retroactively measure AWS. |
| Specification → Unified Security → proxy | New local full-chain26/26; synthetic RS256; exact existing issuer/audience strings;1 measured JWKS GET | Local composition gap closed. S5 Rust JWT14/14 separately measures10 AWS business executions/9 completions/1 JWKS execution for its smaller profile. No new AWS run of this exact full chain. |
| JWT issuer/audience/signature/expiry | New full-chain rejection and subsequent recovery checks; original security/component evidence | Rust rejects wrong issuer, wrong audience, invalid signature and expiry without dispatch. Do not copy Java's S-04a issuer limitation. Portal live-provider fetch/cache counts remain unmeasured; no live credentials used here. |
| Scope enforcement | Four route scopes above, unrelated-scope and DELETE-reader zero-dispatch checks, explicit POST-reader characterization | Current ANY policy is preserved and disclosed. No AND/write-only guarantee. |
| Proxy success, application500, FunctionError and recovery | New full-chain sequence; prior local error batch and S5 AWS22/22 paired error expectations | Rust FunctionError remains502/ERR14014; Java's500/ERR14004 is a disposed difference. Invalid envelopes/IAM/deadlines retain existing Rust contracts; no Java shared-exchange defect was copied. |
| Correlation, requestHeader, responseHeader | New actual forwarded/request/response witnesses and fresh correlation; pinned composed RIE | Meaningful new execution evidence. Last clean warm request has no prior witness/query. |
| Request/response Transformers | Prior Rust composition10/10 action/order/error/warm checks, pinned composed RIE | Existing admitted fixed CEL/action profile only. New pet-store chain skips `/x` rules; no new transformation coverage or arbitrary native plugin parity claimed. Java header candidate's logging stop is independent. |
| HTTP Router forwarding | Five retained forwarding comparisons, factory failed-state proof, pinned composed RIE5 HTTP calls | Forwarding is separate from rewriting. New pet-store profile passes through to Lambda proxy and is not new HTTP transport proof. |
| CORS, limits, sanitizer, metrics, Audit | Prior pinned composed RIE26 requests/7 Invoke/5 HTTP/2 OAuth/1 JWKS; new chain remains intact | Retain existing meaningful branch evidence. New batch does not requalify preflight, limit exhaustion, sanitizer attack inputs or every telemetry field. |
| OAuth Token | Prior pinned composed RIE2 OAuth calls | Not required/enabled by this trial. Do not count its disabled declaration as new execution coverage. |
| Health, Info, GetLogger | Pinned composed/admin RIE | Restricted supported local admin profiles. No new AWS admin batch. |
| SetLogger | Pinned opt-in RIE24 service requests,0 Invoke,2 JWKS | Partial X-04 ROOT INFO/DEBUG/TRACE only; startup gate + logger.enabled + verified-JWT admin authorization. Not enabled by this trial. |
| Basic/API-key | Original-ZIP RIE/component evidence | Not needed by current trial. Candidate-specific RIE needed if selected; do not transfer evidence between binaries. |
| Traceability | Component/comparison and separately instrumented package | Ordinary candidate private-state proof remains unqualified; instrumented evidence stays separate. Not required by the trial chain. |
| Validator | Completed non-child wiring/accounting/metadata; compiled real-child acceptance test; [new offline provenance](/home/steve/workspace/artifacts/implementation/light-lambda/validator-provenance-20261024/REPORT.md): two identical new worker builds, verified reusable parents and pinned archive e8120c57…97508 | Default activation closed; schema validation unavailable in the qualified release. New compile-only candidate needs identity adoption; original v6 gap/invalid verifier remain historical. Integrity-enforced executable loading/resource/semantic/lifecycle gates remain. Platform clearance is unconfirmed; valid→invalid{}→valid real-child acceptance must not run. |
| Router rewriting | Completed approved non-child provider/controller/backend wiring and fail-closed mapping | Default activation closed; nonempty ordinary rewrite rules reject Init. Worker provenance, platform clearance, real execution and production loading/resource/semantic gates remain. |
| CacheExplorer/SWT/general logger/deferred variants | Existing native inventory/deferrals | Unavailable or outside partial support; preserve bindings if required. Full native sample compatibility cannot be claimed. |
| Operational production/public ingress | Existing finite direct-Invoke AWS trials only | Public HTTP ingress, production bounds/performance/concurrency/freeze-thaw/availability and full WP17–WP19 remain independent. No new resources or AWS calls. |

## New local acceptance result

[Report](/home/steve/workspace/artifacts/implementation/light-lambda/rust-replacement-readiness-20261024/REPORT.md), [offline reconciled result](/home/steve/workspace/artifacts/implementation/light-lambda/rust-replacement-readiness-20261024/local-03/offline-reconciled-report.json), [frozen plan](rust-petstore-v1.json).

26/26 gateway expectations;4 full backend echo comparisons;18 unique backend entries/17 normal completions/18 bounded received records;8 zero-dispatch service rejections;1 measured JWKS GET. One actual warm gateway process; all five owned processes reaped. No admission-only request counted as handler execution.83 Python harness tests pass, including14 focused tests.

The four unchanged target ARNs are routed only by the owned InvokeBridge into four local instances of the unchanged controlled backend binary. Echo identities use its supported echo-a/echo-b labels, with per-process and per-attempt joins. Local version1 identities are not claims about the mutable AWS `$LATEST` functions. This exercises real application Init/factory/service/SDK, not injected rule executors or fabricated gateway responses. It is a local owned Runtime API run, not a new RIE or AWS qualification. SDK wire remains unmeasured.

The original failed summaries remain: local-01 stopped before gateway execution on the evidence-writer misuse; local-02 rejected an inconsistent test gateway identity before execution; local-03 ran all26 expectations but initially used a reconciliation helper hard-coded to echo-a. The latter was corrected **offline against the predeclared A/B map**, without another gateway request, normalization, expectation amendments or overwriting the failed summary.

Only the copied values.yml key endpoint URL/path/HTTP2 and copied lambda-proxy.yml endpointOverride change for owned loopback dependencies. Original handlers, rule programs, specification, routes, issuer/audience and all source files remain unchanged. No tokens/private keys are saved. Local layer ZIP SHA-256 `045587395dd2ccf02481203fa65e65f06cb9e29daa2091bd24ca4e3e39c74f1d`; it contains ephemeral loopback addresses and is not a deployable AWS layer.

Rerun from any directory using a fresh evidence path:

```bash
rtk proxy python3 /home/steve/workspace/light-example-rs/tests/lambda-parity/rust_petstore_acceptance.py --out /home/steve/workspace/artifacts/implementation/light-lambda/rust-petstore-rerun-01
```

## Decisions and next work

No newly discovered Rust production defect or new contract decision blocks this named supported local profile. The current Rust candidate has substantial tested-subset AWS qualification; it is not a claim that every required production capability is available. Java full candidate Transformer qualification and its native logging repair are not prerequisites for this supported Rust subset.

The next deployment task, if selected, is a **separately reviewed Rust-only AWS scope for this exact combined-chain profile**, reusing qualified immutable controlled backend versions where possible and measuring downstream/JWKS counts independently. Its remote synthetic JWKS/signing lifecycle, narrowly scoped target grants, final layer hashes, resource identities and retention ownership must be concrete before approval; the ephemeral local layer must not be uploaded. Existing accepted deployments and all retained resources stay unchanged.

The offline Validator provenance step is now completed for a separate compile-only candidate: [report and exact artifact review](/home/steve/workspace/artifacts/implementation/light-lambda/validator-provenance-20261024/REPORT.md). It preserves the historical v6 gap/invalid verifier rather than refreshing their pins. Next gates are new candidate identity adoption, distinct platform clearance for actual-child qualification, and production integrity-enforced executable loading/resource/semantic/lifecycle work before activation. Router rewriting remains separate. Do not reopen settled failure mappings or copy Java defects to obtain equality. Retain original D-08/H-04/Java L-02 failures, Java D03/shared-exchange findings, bundle verification failure and failed S5/S6 batches. Cleanup of retained/chargeable trial resources, including public JWKS endpoints, requires a separate explicit decision.
