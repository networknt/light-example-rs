# Parity qualification matrix — 2026-10-24

**Current replacement priority:** [Rust replacement readiness](RUST-REPLACEMENT-READINESS.md) treats Java as a compatibility reference, not a correctness oracle. The additive Rust-only full trial-chain profile passes26/26 expectations,4 actual backend echo comparisons,18 executions/17 completions/18 bounded received records,8 zero-dispatch service rejections and1 measured JWKS GET; all5 owned processes reaped. Its initial single-identity reconciliation failure is preserved and corrected offline without rerunning the26 requests. This is owned Runtime API/production SDK evidence using unchanged Rust/backend ZIPs, not new RIE/AWS or paired/byte-identity evidence. Current83 Python tests pass. No original cases/declarations below are relabelled.

The native header candidate was subsequently built and stopped after5/5 functional gateway expectations at its effective-logging gate;15 requests remain unexecuted. [Preserved result](/home/steve/workspace/artifacts/implementation/light-lambda/native-transformer-qualification-20261024/REPORT.md). The prepared-only entry below is historical. That Java-only candidate gap is not a blocker for the supported Rust profile. Validator/rewrite activation/platform/provenance and ordinary Traceability proof remain open.

Current evidence is profile-specific. Approved-contract passes and raw byte identity are independent measurements. `cases.json` remains the unchanged25-case original runner selection inventory (14 default runnable /11 deferred-unavailable declarations). This matrix reconciles evidence from subsequent profiles without relabelling original fixtures or making the default runner execute unsupported adapters.

| Profile / evidence | Independent expectations | Approved-contract pairs | Raw byte identity | Execution / forwarding evidence |
|---|---|---|---|---|
| [Pet-store ten-case](/home/steve/workspace/artifacts/implementation/light-lambda/WP17-offline-parity-review-20261022T211639Z/REPORT.md) |20/20|10/10|0/10|backend/JWKS counts unmeasured in named comparison; independent pet-store log window is aggregate only|
| [Synthetic version2](/home/steve/workspace/artifacts/implementation/light-lambda/parity-received-aws-20261023T001101Z/REPORT.md) |44/44 gateway requests;28/28 case expectations|14/14 cases;22/22 steps|0/14 cases;0/22 steps|42 unique entries/completions/received-event records;42/42 independent per-gateway expectations; zero route-miss dispatch|
| [AWS IAM/deadline](/home/steve/workspace/artifacts/implementation/light-lambda/parity-timing-aws-20261023T024105Z/REPORT.md) |4 direct +4 primes +18 selected, all pass|9/9 paired selected steps|0/9|20/18 downstream including primes;16/14 selected; zero denied executions; actual platform timeouts/late completion; warm streams|
| [Status-format candidate envelope batch](/home/steve/workspace/artifacts/implementation/light-lambda/parity-java-status-format-20261023T061219Z/errors/report.json) |22/22; Java11/11, Rust11/11|11/11 frozen paired contracts|0/11|22 actual backend entries/20 completions; earlier wrong-type failure preserved historically; general shared-state defect open|
| [New local JWT composition](/home/steve/workspace/artifacts/implementation/light-lambda/parity-next-local-20261023T035300Z/jwt-explicit-native-trust/report.json) |28/28|14/14 side-specific step contracts; full field differential not claimed|see measured runtime-byte audit in new report|20 entries/18 completions/20 received records;1 JWKS fetch per side;8 auth/scope zero-dispatch rejections; actual packaged warm processes|
| [Local dynamic echo](/home/steve/workspace/artifacts/implementation/light-lambda/parity-dynamic-echo-20261024/REPORT.md) |14/14|7/7 side-specific contracts; not arbitrary-field equality|0/7|14 unique backend executions/completions/received records; separate independent echo-response and received-event expectations; bounded400/warm recovery; actual A/B/A identity/isolation|
| [Local target-route selection](/home/steve/workspace/artifacts/implementation/light-lambda/parity-routes-20261024/REPORT.md) |40/40 v2; original shared v1 remains34/40|20/20 v2 side-specific contracts|0/20|28 actual backend executions/completions;12 zero-dispatch rejections; declared/reversed textual configuration orders; explicit R-01a Java wildcard/Rust template difference; warm recovery|
| [Local middleware composition](/home/steve/workspace/artifacts/implementation/light-lambda/parity-composition-20261024/REPORT.md) |30/30 functional (Java10/Rust20), plus2/2 Java service-rejection-only|not claimed; native Transformer functionality unqualified|not measured|22 unique executions/completions;8 functional zero-dispatch rejections plus2 service gates; actual order contrasts/target mutation/error/warm proof; all nine processes reaped|
| [S5 AWS error/JWT scope, preserved failed aggregate](/home/steve/workspace/artifacts/implementation/light-lambda/parity-error-jwt-aws-20261023T072900Z/approved-amendment/confirmation-20261023/REPORT.md) |39/50; error profiles22/22, Rust JWT14/14, Java JWT3/14|14/25 aggregate; error subset11/11|0/25|32 backend executions/29 completions/1 JWKS against required42/38/2; Java TLS failure retained|
| [S6 Java PKIX trial, preserved failure](/home/steve/workspace/artifacts/implementation/light-lambda/java-pkix-rie-review-20261024T005609Z/S6-AWS-REPORT.md) |3/14;11 failures|not paired|not measured; single runner|13 actual JWKS platform executions,0 accepted fetch records; no observed backend execution; Java successful warm recovery failed|
| [S7 Java-only configuration recovery](/home/steve/workspace/artifacts/implementation/light-lambda/java-jwks-admission-local-20261024T020942Z/s7-completed-aws/REPORT.md) |14/14, once-only|not paired; Java-only expectations|not measured; single runner|10 unique backend executions/9 completions/10 received records;1 JWKS platform execution and accepted fetch/completion; one gateway stream and specified warm recovery; offline audit passed|

Rows overlap in capability coverage and must not be summed into a new parity total. S7 is a separate Java-only run; it neither repairs the historical S5/S6 counts nor creates a fresh paired comparison with S5 Rust. Java does not enforce issuer matching in this profile: the retained failed extra control reproduces the settled S-04a intentional difference. No issuer-enforcement repair or expectation amendment was made.

## Reconciliation of the eleven original open declarations

Covered means only the named profile/subset. Partial rows retain their remaining scope; do not count these as eleven newly passing cases.

| Original case ID | Current classification | Completed evidence | Remaining work / exact gate |
|---|---|---|---|
| PARITY-pet-store | covered-independent-profile | Four pet-store routes/auth/parser/warm comparison:20/20 expectations,10/10 approved pairs,0/10 byte-identical; counts unmeasured. Keep outside synthetic totals. | none for named ten-case subset; broader business/schema cases remain independent |
| PARITY-echo-dynamic | covered-local-profile | Additive dynamic_echo.py:14/14 gateway expectations,7/7 side-specific contracts,0/7 bytes;14 actual entries/completions/received records. Independent response/received goldens cover named synthetic fields, A/B/A identity and warm isolation, privacy canaries, bounded400 and recovery. First failed golden run preserved. | named local subset only; AWS dynamic echo and broader methods/base64 variants remain separate; no production changes or new default-runner availability claim |
| PARITY-function-error | covered-aws-profile | S5 error subset22/22 and11/11 frozen paired contracts qualify ordinary synthetic FunctionError/privacy/recovery. S7 independently requalifies Java500/ERR14004 after strict JWKS authentication; Rust502/ERR14014 remains a side-specific contract. Platform-timeout FunctionError is separately covered. | none for named shapes; preserve historical broader exchange-state finding |
| PARITY-invalid-envelopes | partial-production-defect | Approved typed status-format guard has local22/22 and S5 AWS error-subset22/22 expectations,11/11 frozen paired contracts,0/11 byte-identical. Missing/null status, privacy and recovery preserved. S5's aggregate JWT failure does not invalidate the separately measured passing error subset. | Broader shared exchange-state handling remains production work for nonmatching nested/unrelated parse errors; original historical assertions preserved. No further deployment implied. |
| PARITY-unknown-template-route | covered-local-profile | route_integration.py v2:40/40 expectations,20/20 side-specific contracts,28 executions/completions,12 zero-dispatch misses, warm recovery in both textual config orders. Literal/parameter/wildcard/method boundaries include retained R-01a native wildcard precedence. Shared v1 remains34/40, preserved. | finite local target-route subset only; additional shapes and AWS qualification separate; not Router rewriting |
| PARITY-middleware-composition | partial-composition-and-native-profile-gap | Existing JWT profiles retained. New correlation/header order contrasts pass Java10/Rust10; Rust full request/response Transformer order/path-before-target/combined-error/warm checks10/10.22 backend executions/completions total. Separate native404 ERR11406 service gate2/2 is not Transformer functional coverage. | equivalent native RuleExecutor/action provider/image profile is absent for selected recipes; broader compositions remain partial. No new paired JWT claim or Java issuer-enforcement claim |
| PARITY-iam-denied | covered-aws-profile | Valid denied:1 positive control; exact IAM excludes target for four gateway roles; denial returns Java400/ERR10086/Rust502/ERR14019,0 denied executions, warm recovery. | none for named subset; preserve evidence limits |
| PARITY-timing | covered-aws-profile | Delayed success, native SDK1s vs Rust1100ms deadline, actual backend4s platform timeout, late completion after gateway return and version-specific warm recovery qualified. | none for named subset; no freeze/thaw/concurrency/performance claim |
| PARITY-validator | platform-and-activation-gates | Application provider/lifecycle/precision wiring qualified non-child; default activation remains closed. | platform clearance unconfirmed; original bundle verifier failure/two missing parent binary provenance, reproducible immutable packaging/resource/semantic gates remain; no replacement-worker execution |
| PARITY-router-rewrite | platform-and-activation-gates | Provider/controller/backend lifecycle and fail-closed unavailable mapping qualified non-child in selected profile; forwarding evidence is separate. | platform clearance and worker provenance before actual rewrite execution; default rewrite activation remains closed and production bounds/loading/semantic gates remain |
| PARITY-invalid-outer | explicit-runtime-deferral | Rust lambda_runtime backend serializes JSON: returning a JSON string cannot prove malformed outer runtime bytes. Malformed nested body passthrough is already covered. | requires deliberate raw Runtime API test backend capability/new runtime profile for AWS proof; ordinary local Invoke fault stub can cover parser boundary separately; not evidence of a missing production gateway handler |

Reconciled categories:6 covered named profiles (3 AWS,1 independent pet-store,2 local echo/routes),1 partial composition/native-profile entry,1 partially covered production-defect entry,2 platform/activation-gated entries,1 runtime-capability deferral. The original runner availability remains14 local/8 deferred/3 unavailable; qualification attribution does not overwrite that selection contract.

## Existing fourteen default proxy cases

All retain the version2 response/forwarding/routing evidence above.

| Case ID | Family | Current qualification |
|---|---|---|
| PARITY-created | responses | qualified named version2 profile |
| PARITY-no-content | responses | qualified named version2 profile |
| PARITY-empty | responses | qualified named version2 profile |
| PARITY-application-error | responses | qualified named version2 profile |
| PARITY-body-absent | body | qualified named version2 profile |
| PARITY-body-null | body | qualified named version2 profile |
| PARITY-body-empty | body | qualified named version2 profile |
| PARITY-body-json | body | qualified named version2 profile |
| PARITY-body-unicode | body | qualified named version2 profile |
| PARITY-forwarding | forwarding | qualified named version2 profile |
| PARITY-routing-ab-recovery | recovery | qualified named version2 profile |
| PARITY-binary-cookies | responses | qualified named version2 profile |
| PARITY-malformed-body | responses | qualified named version2 profile |
| PARITY-unknown-route-recovery | routing | qualified named version2 profile |

## Highest-value next runnable work

FunctionError/finite invalid-envelope and JWT composition now have the named AWS subset evidence above. Do not repeat completed batches simply to consolidate reporting. The older default923ea10b candidate retains its21/22 local failure evidence; accepted defaults remain unchanged. The original S5/S6 failures and additional wrong-issuer control remain preserved.

Next runner-only additions: dynamic echo response binding, explicit target literal/template/method selection, then additional registered middleware compositions. Keep raw-outer-payload capability, Validator and rewriting separate. Original Java D03 assertion conflict, broader exchange-state defect and unmeasured SDK wire remain open. Cleanup requires a separate explicit decision.

Local dynamic echo, finite target-route boundaries and the selected middleware composition subset are qualified through existing Runtime/InvokeBridge; original fixtures/default selection/failures remain separate. Next exact gap is a supported native RuleExecutor/action profile for equivalent Transformer execution, plus additional independently scoped compositions. Service rejection does not close that gap. No AWS run, backend rebuild or production change accompanied these local profiles. Do not resume paused workers. Worker provenance review remains independently possible without execution; real Validator/rewriting execution still needs platform clearance.

### Status-format mitigation qualification — 2026-10-23

[Separate local candidate/results](/home/steve/workspace/artifacts/implementation/light-lambda/parity-java-status-format-20261023T061219Z/REPORT.md): approved patch0e148372…b5d96 changes only the native proxy's typed top-level Integer-status parsing failure. The22-request envelope batch and28-request JWT composition pass, plus12 packaged owned-stub checks and the preserved14-case/44-request/42-backend integration. Original Java D03 assertion conflict and nonmatching shared-state failures remain open. No AWS rerun or accepted release replacement. Explicit candidate selection uses Java ZIP122d03391f999aad4f6ccf022c0fb1188241c2218c670ff013aa884510033db7; raw byte identity remains0/11 error pairs and0/14 JWT step pairs.


## S5 AWS error/JWT scope — executed once, 2026-10-23

Separate new-resource deployment succeeded; qualification failed. Error-only Java/Rust profiles: 22/22 expectations and 11/11 response-contract pairs. Rust JWT: 14/14 expectations, 10 business executions, nine completions, one measured JWKS GET. Java JWT: 3/14 negative-response matches, 11 failures caused by native HTTPS trust-manager rejection before JWKS service execution; cryptographic/JWKS composition remains unqualified. Aggregate: 39/50 expectations, 14/25 response-contract pairs, 0/25 raw byte-identical pairs; independently observed 32 business executions, 29 completions and one JWKS execution against unchanged 42/38/two requirements. Four actual warm gateway log streams are recorded; Java JWT successful warm recovery failed.

The full once-only 50-request scope is non-green. No expectations were amended, requests retried, accepted releases replaced or resources deleted. Original D03 and broad exchange-state defects, SDK-wire measurement, deferred capabilities, Validator/rewrite/platform gates and separate single-runner counts remain open/unchanged. [Exact results and per-case dispositions](/home/steve/workspace/artifacts/implementation/light-lambda/parity-error-jwt-aws-20261023T072900Z/approved-amendment/confirmation-20261023/REPORT.md).


### Native Transformer provider/action scope — prepared, not executed

[Static inventory and exact local-only scope](/home/steve/workspace/artifacts/implementation/light-lambda/native-transformer-scope-20261024/README.md) recommends adding only two pinned production header-replace classes to a separate Java candidate, registering the existing MultiThreadRuleExecutor plus scoped native metadata, and qualifying actual header actions through the current harness. Base provider/DTO classes already exist; RuleConfig metadata is preserved. Header-only scope does not cover original path/query/body rewrites. Native response-input and missing-rule fall-through semantics, privacy gates and incomplete provider/action qualification are explicit.20 planned local requests/14 executions are unexecuted; no new passes, builds, AWS calls or source behavior changes. Original qualification counts and paused-worker boundaries remain unchanged.
