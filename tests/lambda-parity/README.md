# Lambda gateway parity — current qualification

For the Rust replacement decision, use [RUST-REPLACEMENT-READINESS.md](RUST-REPLACEMENT-READINESS.md). The additive Rust-only full pet-store trial-chain acceptance profile uses the unchanged qualified ZIP, synthetic RS256 keys and owned running backends:26/26 expectations,18 executions/17 completions,8 zero-dispatch rejections and1 measured JWKS GET. Run `rtk proxy python3 tests/lambda-parity/rust_petstore_acceptance.py --out /home/steve/workspace/artifacts/implementation/light-lambda/rust-petstore-rerun-01` from light-example-rs with a fresh output directory. This is local owned Runtime API/SDK proof, not a new AWS/RIE run. Java defects are documented independently rather than copied into Rust.

Current per-case evidence and the reconciliation of all eleven original open declarations are in [QUALIFICATION-MATRIX.md](QUALIFICATION-MATRIX.md) and [qualification-v1.json](qualification-v1.json). The original25-case inventory and14-case default selection remain unchanged; later local/AWS profiles are attributed separately. Historical implementation checkpoints below are not the current AWS status.

Current AWS evidence: synthetic version2 response/forwarding/routing44/44 requests,14/14 contract case pairs,0 byte-identical,42 actual received-event/execution/completion IDs; timing/IAM4/4 direct +4/4 primes +18/18 selected,9/9 contract step pairs,0/9 byte-identical,20/18 downstream including primes. The original ten-case pet-store comparison remains independent with unmeasured backend/JWKS counts.

## Approved status-format candidate — local only

[Qualification report](/home/steve/workspace/artifacts/implementation/light-lambda/parity-java-status-format-20261023T061219Z/REPORT.md). The additional approved guard is qualified through the new candidate ZIP SHA-256 `122d03391f999aad4f6ccf022c0fb1188241c2218c670ff013aa884510033db7`. Explicit selection below passes22/22 error requests and28/28 JWT composition requests; default pins remain unchanged, so the older command without these arguments still reproduces the retained21/22 result. No AWS deployment or accepted artifact replacement occurred.

```bash
rtk proxy python3 -B tests/lambda-parity/error_integration.py \
  --java-zip /home/steve/workspace/artifacts/implementation/light-lambda/parity-java-status-format-20261023T061219Z/java-native-status-format-candidate.zip \
  --candidate-manifest /home/steve/workspace/artifacts/implementation/light-lambda/parity-java-status-format-20261023T061219Z/candidate-manifest.json \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/NEW-status-format-errors
rtk proxy python3 -B tests/lambda-parity/jwt_integration.py \
  --java-zip /home/steve/workspace/artifacts/implementation/light-lambda/parity-java-status-format-20261023T061219Z/java-native-status-format-candidate.zip \
  --candidate-manifest /home/steve/workspace/artifacts/implementation/light-lambda/parity-java-status-format-20261023T061219Z/candidate-manifest.json \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/NEW-status-format-jwt
```

Original Java D03 assertion conflict and broader exchange/chain defect remain open. Nonmatching nested/unrelated parse errors are rethrown unchanged; only the approved top-level status format is mitigated. Older checkpoints below retain their original evidence and counts.

## New local error and JWT composition profiles

These reuse existing Runtime/InvokeBridge, actual packaged Java/Rust Init/service/SDK paths and the running parity backend. They pin the separately identified Java proxy candidate923ea10b…7728d and accepted Rust ZIPd095e89c…756a; they never deploy or rebuild accepted artifacts implicitly.

```bash
# Expected exit1:21/22 assertions; preserve the Java wrongly typed status defect.
rtk proxy python3 -B tests/lambda-parity/error_integration.py --out /home/steve/workspace/artifacts/implementation/light-lambda/NEW-errors
# Expected exit0:28/28 assertions; actual JWKS and backend counts, synthetic RSA only.
rtk proxy python3 -B tests/lambda-parity/jwt_integration.py --out /home/steve/workspace/artifacts/implementation/light-lambda/NEW-jwt
```

Use fresh output directories. The error profile records22 backend entries/20 completions and distinguishes genuine FunctionError from application500, missing/wrong status and invalid base64 with warm recovery. The Java wrong-type case remains an outer runtime failure against unchanged500/ERR14004 expectations; a narrow production patch is proposed, not applied. The native invalid-base64 mode preserves its explicitly empty header map; the runner does not invent Content-Type.

The JWT profile composes Specification->JWT/scope->proxy, observes20 backend entries/18 completions/20 received-event records, eight zero-dispatch authentication/scope rejections and one actual local JWKS GET per gateway. Its private keys and synthetic JWTs remain in memory; persisted Invoke receipts exclude credential fields and raw credential-bearing bytes. Native Caffeine cache/JKS bootstrap configuration is separate from Rust's supported cache/PEM configuration; both use owned loopback dependencies. Missing credentials use an explicit empty scalar map, and synthetic Authorization has matching scalar/multivalue representations. This qualifies the selected supported profile, not arbitrary ingress compatibility or AWS JWT/JWKS counts.

[New report, historical failures, exact adaptations and one production decision](/home/steve/workspace/artifacts/implementation/light-lambda/parity-next-local-20261023T035300Z/REPORT.md). All35 Python tests pass. Shared exchange/ChainExecutor behavior, the historical Java D03 assertion conflict, unmeasured AWS SDK-wire behavior, Validator/rewriting activation and paused work remain open. [Cleanup inventory](/home/steve/workspace/artifacts/implementation/light-lambda/parity-next-local-20261023T035300Z/CLEANUP-INVENTORY.md) is retained for a separate decision; no deletion or AWS action was taken here.

## Historical initial local batch

## Running-backend integration profile

`integration.py` connects the **unchanged packaged Java native and Rust gateways**
through their real SDK Invoke HTTP transport to two running parity backend
executables. The owned Invoke adapter forwards actual request/response bytes;
it does not construct mode replies or inject a gateway client. It reuses this
suite's fourteen runnable cases, expectations and result-v1 comparator.

```bash
rtk python3 -B /home/steve/workspace/light-example-rs/tests/lambda-parity/integration.py --out "/home/steve/workspace/artifacts/implementation/light-lambda/parity-integration-$(rtk proxy date -u +%Y%m%dT%H%M%SZ)"
```

The local prerequisite is the release musl `lambda-trial-backend` binary; build
it with `rtk cargo build --locked --release --target x86_64-unknown-linux-musl -p
lambda-trial-backend`. The gateway ZIP pins and native layer3 config/status
catalogue pins are enforced. Existing gateway ZIPs are never rebuilt by this
command. It uses the existing `serverless-conformance` executable for validation
and comparison. Repeated `--case ID` selects a subset.

Qualified evidence: 14 contract-conforming pairs, 44 gateway requests, 42 signed
Invoke calls and 42 actual backend execution/completion records; two route misses
make zero calls. One gateway process per side proves local warm reuse, with all
four gateway/backend processes reaped. This profile is **packaged executable +
owned Runtime API on the local host**, not a new RIE/container or AWS test.
`run.py` below remains the separate injected-client profile; do not combine its
backend counts with this profile. The eleven deferred/unavailable entries remain
unchanged, including dynamic echo and FunctionError gateway adapters.

Native transport configuration adds the already qualified positive SDK timeout
settings and pinned `config.yml`/`status.yml` (absent from injected fixtures).
Only the dedicated integration configuration changes; native fixtures and their
per-side expectations remain exact. Actual responses, wire requests, API versus
backend execution IDs, process identities and cleanup are saved separately.

`deploy/lambda-parity/prepare_stage3.py --integration <successful-output> --out
<fresh-evidence-directory>` prepares a **new-resource AWS approval scope only**.
It packages the exact tested backend executable, reuses the accepted gateway
ZIPs, builds dedicated config layers and pins proposed echo A/B version1 targets.
It never contacts AWS. See the generated `AWS-SCOPE.md` for resources, IAM,
costs, cases, publication/readback gates and separately authorized cleanup.

Evidence/report:
`artifacts/implementation/light-lambda/WP17-parity-integration-20261022T224001Z/REPORT.md`.

## Current local continuation (2026-10-22)

Stages 1–2 now have **14 runnable cases out of 25 inventory entries**. The
original 11 remain covered. Added binary bytes/base64, ordered repeated
Set-Cookie, opaque malformed-body passthrough, and unknown-route zero-dispatch
rejection with warm A/B recovery. The other 11 entries are explicitly
deferred/unavailable, not passes. The details below describe the earlier batch;
`cases.json` is the current capability inventory.

The backend is the existing `apps/lambda-trial-backend`, mode table
`parity-modes/v1`. Its real executable is tested through an owned Runtime API,
including genuine `/error` submissions. Gateway fixtures then use these verified
finite replies through the existing Java ConformanceRunnerMain and Rust
serverless-conformance real Init/service paths with injected dependencies.
**This is not gateway-SDK-to-running-backend, RIE, or AWS execution proof.**
Backend Runtime API counts and gateway injected-call counts are separate.

Build prerequisites (no AWS operations):

```bash
rtk cargo build --locked --manifest-path /home/steve/workspace/light-example-rs/Cargo.toml -p lambda-trial-backend
rtk cargo build --locked --manifest-path /home/steve/workspace/light-fabric-light-lambda/Cargo.toml -p serverless-conformance
rtk mvn -f /home/steve/workspace/light-lambda-native-conformance/pom.xml -q test-compile dependency:build-classpath -Dmdep.outputFile=target/conformance-cp.txt
```

Rerun all runnable cases into a new evidence directory:

```bash
rtk python3 -B /home/steve/workspace/light-example-rs/tests/lambda-parity/run.py run --out "/home/steve/workspace/artifacts/implementation/light-lambda/parity-local-$(rtk proxy date -u +%Y%m%dT%H%M%SZ)"
```

Use repeated `--case ID` for an explicit subset. Selecting an unavailable or
deferred entry returns nonzero. There are no automatic retries. Failed commands
also make the run non-green even if comparison files happen to report passes.
Raw observations, per-side expectations and historical failures are preserved.
The existing comparator matches header names case-insensitively while retaining
exact values, multiplicity and order; static validation now follows that same
rule. No existing fixture expectation was amended.

The accepted ten-case pet-store AWS checkpoint remains independent: 20/20 gateway
expectation passes, 10/10 contract-conforming pairs, 0/10 byte-identical pairs;
backend/JWKS execution counts unmeasured. No deployments, resource deletion,
observability promotion or paused precision experiments are part of this suite.
AWS cleanup requires a separate explicit decision.

## Earlier initial batch notes

Implements the first assignment in
`light-fabric/docs/src/product/light-lambda/parity-test-suite.md`: backend contract,
an initial executable local pair batch, and stage 3 IaC/review preparation without
deployment. This is a selected proxy-only batch, not full parity or WP12/WP13
closure. No original fixtures, pet-store functions, gateway code or deployments
are modified. Validator/rewrite worker execution remains unavailable.

## Reused execution paths

The backend is `apps/lambda-trial-backend`; its original body-command modes remain
supported. Local gateway execution reuses:

* Java `light-lambda-native-conformance` test classes, `ConformanceRunnerMain`,
  real `LambdaApp` and its injected owned Invoke dependency.
* Rust `light-fabric-light-lambda`'s `serverless-conformance` binary and real
  Init/service application path, existing fixture validation, independent
  expectations, result-v1 validation and exact differential comparison.
* Existing E-03 fixture configuration and E-04/E-10/E-12/E-13 ledger contracts.

No alternate gateway implementation exists here. The thin runner emits existing
fixture-v1 files and retains existing result-v1 files unchanged. Suite metadata
is in a digest-linked, schema-validated report sidecar. Java and Rust receive
identical multi-value ALB-shaped synthetic ingress, pinned separately under
`events/java` and `events/rust`. This discriminator does not imply a real ALB.

The local dependency replies are injected by the established runners. Before
running gateways, the actual compiled backend is invoked via owned Runtime API
endpoints, once as each identity. Each injected reply must equal that tested
artifact's response for the mode. This proves a backend-bound local oracle and
real gateway paths; **it does not prove end-to-end gateway SDK invocation of the
backend runtime**, IAM or AWS execution counts. Raw `backendCalls` are local
dependency observations. Per-side call count/target and forwarded fields are
asserted; AWS request IDs cannot be inferred from these local calls.

## Inventory and initial matrix

`cases.json` is schema-validated and contains 23 cases: 11 local and 12 explicitly
deferred/unavailable entries. No pet-store run is included in synthetic totals.
The default selects the 11 local cases (13 steps per gateway).

| Family | Local cases | Expected contract |
| --- | --- | --- |
| Responses | created, no-content, empty, application-error | exact status/body/encoding and content type; application 500 is successful Lambda execution |
| Body | absent, null, empty, JSON with large integer, Unicode | exact forwarded bytes; Java omits absent/null body, Rust retains null |
| Forwarding | repeated headers; repeated/empty query, Unicode, percent and literal plus | E-04 percent decode once in Rust; Java preserves encoded query; order exact |
| Recovery/routing | A success → B application error → A success | exact target sequence and one dispatch per step, no stale target/body/header |

Independent Java/Rust expectations are generated before execution. The existing
ledger's exact `backendCalls` difference is declared per fixture and checked for
unexpected/stale differences. Native omitted metadata and Rust generated context
are preserved in raw results; no global body/number/header normalization occurs.
Gateway bodies compare as exact strings, including large JSON integer text.

`cases.json` records the remaining families and reasons. Dynamic echo gateway
callbacks, invalid envelopes/FunctionError gateway mapping, binary/cookie gateway
responses, template/unknown routes, JWT/full-chain composition, denied IAM and
timing require subsequent declared adapter/profile batches. Backend modes for
those response failures are already directly tested. Selecting any unavailable
or deferred case is non-green. A listing or offline preparation is not a pass.

## Backend contract

`x-parity-case` selects a finite mode. `x-parity-run`, `x-parity-id` and
`x-parity-attempt` are required, 1–64 ASCII alphanumerics/dot/hyphen/underscore.
Only one logical value is allowed. Equal mirrors in single/multi-value maps are
accepted; multiple values, case-duplicate names or conflicting mirrors are
rejected. Body maximum is 4096 bytes. Headers/query echoes have independent bounds.
Limits and response scripts cannot be supplied by a request.

| Mode | Result |
| --- | --- |
| echo | allowlisted method/path/resource/path parameters, q/empty query maps, synthetic headers, body/flag and fixed identity/version |
| created / no-content / empty | finite 201 / 204 / empty 200 envelopes |
| application-error | envelope 500 / PARITY_APPLICATION_ERROR |
| function-error | actual runtime error submission; no completion record |
| binary / cookies | fixed binary base64 / ordered two Set-Cookie values |
| wrong-type / missing-status | syntactically valid JSON with invalid envelope shape |
| invalid-base64 / malformed-json | fixed invalid encoded body / invalid nested JSON |

Unknown/ambiguous/oversized inputs return 400/PARITY_INVALID_CONTROL. Backend
headers Authorization, Cookie, arbitrary headers, query names and requestContext
are excluded before serialization. Body/path data must be synthetic. No secrets,
identity claims or incoming event dumps belong in fixtures or logs. Correlation
logs contain only validated IDs, static mode, fixed identity/version and runtime
execution ID; invalid control uses a fixed label. Completion is omitted on real
FunctionError. The runtime test checks entry cardinality, distinct execution IDs,
privacy canaries and process reaping for both identities. It also runs recovery
after errors. Delay and invalid outer runtime bytes are not implemented.

## Commands

Run from `light-example-rs`. Requirements: Rust toolchain, musl target, Python 3
with `jsonschema>=4.10,<5`, JDK 25/Maven for the existing native conformance checkout,
and sibling Light Lambda/conformance checkouts. The runner performs no dependency
installation, Maven build, deployment or AWS invocation implicitly.

```sh
rtk cargo test -p lambda-trial-backend --locked
rtk cargo clippy -p lambda-trial-backend --all-targets --locked -- -D warnings
rtk cargo build -p lambda-trial-backend --release --target x86_64-unknown-linux-musl --locked
rtk proxy python3 -B -m unittest discover -s tests/lambda-parity -p test_suite.py -v
rtk proxy python3 -B tests/lambda-parity/run.py inventory
```

Build the existing runners separately, in their own repositories:

```sh
rtk cargo build --manifest-path ../light-fabric-light-lambda/Cargo.toml --locked -p serverless-conformance
rtk mvn -f ../light-lambda-native-conformance/pom.xml -q test-compile dependency:build-classpath -Dmdep.outputFile=target/conformance-cp.txt
```

Always choose fresh evidence directories; scripts refuse existing paths. Do not
reuse these literal placeholders. Evidence lives below
`/home/steve/workspace/artifacts/implementation/light-lambda/`.

```sh
# Offline paired-event generation only; no gateway initialization or network.
rtk proxy python3 -B tests/lambda-parity/run.py prepare \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/FRESH-prepared

# Direct backend contract only (32 invocations, two reaped local processes).
rtk proxy python3 -B tests/lambda-parity/test_backend_runtime.py \
  --binary target/x86_64-unknown-linux-musl/release/lambda-trial-backend \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/FRESH-backend

# Backend contract plus real Java/Rust gateway paths and existing comparison.
rtk proxy python3 -B tests/lambda-parity/run.py run \
  --backend-binary target/x86_64-unknown-linux-musl/release/lambda-trial-backend \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/FRESH-paired

# Read back a saved run; verify sealed evidence digests before reporting.
rtk proxy python3 -B tests/lambda-parity/run.py compare \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/FRESH-paired

# Explicit subset; unsupported selection cannot become a green skipped run.
rtk proxy python3 -B tests/lambda-parity/run.py run --case PARITY-created \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/FRESH-subset
```

Use `--fabric`, `--java`, `--rust-runner` and `--backend-binary` for explicit
checkout/artifact paths. Timeout/command failures and prior runs are retained;
there are no runner retries. Each run captures source revisions, compiled class
and binary digests, fixture/event bytes, backend records, command exits, full
result-v1 observations, existing coverage and the report's evidence digests.
Local single-process sequential steps do not prove AWS environment reuse.

For existing package/RIE qualification, use the sibling
`apps/light-lambda/tests/l2/run.py --package ZIP --out FRESH` documented in that
checkout. The new paired cases have **not** run through RIE; this batch is local
Init/service/Runtime API evidence. RIE, freeze/thaw, platform timeouts and AWS are
separate gates. No existing historical timing assertion is changed.

Backend ZIP preparation reuses the original deterministic packager:

```sh
rtk proxy python3 -B apps/lambda-trial-backend/package.py \
  --binary target/x86_64-unknown-linux-musl/release/lambda-trial-backend \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/FRESH-package
```

See [AWS review runbook](../../deploy/lambda-parity/runbook.md) for two isolated
CloudFormation candidates, offline artifact review preparation, unresolved
configuration/evidence gates and cleanup scope. Live execution and log collection
are stage 3 work requiring exact owner authorization, not hidden modes of this
local runner.


## Actual backend-received observation profile

The existing running-backend integration accepts `--backend-observations`. This opts in only the two backend processes and compares their actual records with separate independent per-gateway `received-contracts.json` expectations. Original fixture expectations,14 local cases and11 deferred/unavailable entries are unchanged. Backend observations remain separate from actual local SDK HTTP captures; they do not establish SDK-wire evidence in AWS.

```bash
rtk proxy python3 tests/lambda-parity/integration.py --backend-observations --backend-binary /home/steve/workspace/artifacts/implementation/light-lambda/parity-backend-observations-20261022T234816Z/lambda-trial-backend --out /home/steve/workspace/artifacts/implementation/light-lambda/parity-backend-observations-rerun
```

Use a fresh output directory. Qualified locally:14/14 original differential pairs,44 gateway requests,42 actual executions and receiving-backend observations; all42 match independent expectations, and both zero-dispatch cases retain existing transport/entry-count checks. All four processes reaped. [Full report and review-only AWS update](/home/steve/workspace/artifacts/implementation/light-lambda/parity-backend-observations-20261022T234816Z/REPORT.md). No AWS updates/deletion or paused work; JWKS counts excluded.


Local IAM/timing batch: see [TIMING.md](/home/steve/workspace/light-example-rs/tests/lambda-parity/TIMING.md). Fixed delays require startup bounded-v1 opt-in and delay identity. New local results17/18 (Java backend-timeout defect remains); this does not alter prior version-2 qualification or authorize AWS deployment.


## Local dynamic echo — 2026-10-24

Additive profile through real packaged Java/Rust Init/service/SDK, existing owned Invoke bridge and two actual compiled backend processes. No injected handler response, backend/gateway source change, rebuild, AWS calls or paused-worker execution. Original cases.json/fixtures/default selection remain unchanged.

```sh
cd /home/steve/workspace/light-example-rs
rtk proxy python3 tests/lambda-parity/dynamic_echo.py --out /home/steve/workspace/artifacts/implementation/light-lambda/parity-dynamic-echo-20261024/rerun-01
```

Use a fresh output directory. Defaults pin separately qualified Java candidate122d0339…3db7, unchanged Rustd095e89c…756a and existing backend ZIP4e0bb9cc…cd974 (local backend version1; not an AWS version assertion). Original accepted default pins in integration.py are unchanged. This proxy-only profile does not qualify the S7 TLS/JWT configuration.

Seven steps per gateway cover absent/empty/Unicode/large-integer-text bodies, duplicate query/header values, A/B/A warm identity/isolation, bounded backend400 and successful warm recovery. Static response goldens and original independently declared received-event goldens are checked separately: backend echo maps a present null query map to an empty object while received-event evidence retains null. Controls bind only send-ledger IDs, never observed response data. Synthetic authorization/cookie/private canaries must not appear in echoes.

Measured local-02:14/14 gateway expectations,7/7 side-specific contract pairs,0/7 raw byte-identical,14 unique backend executions/completions/received records,one process per gateway and all four owned processes reaped. These are local SDK bridge/Runtime API observations, not AWS execution or raw SDK-wire measurement; JWKS remains outside this profile. local-01 remains a failed9/14 run with the initial response-golden null-map error; source-grounded correction changed only the new adapter golden, not original fixture expectations or observed outputs.

Focused seven regressions and all45 Python harness tests pass. Report: /home/steve/workspace/artifacts/implementation/light-lambda/parity-dynamic-echo-20261024/REPORT.md. Next distinct scope is route literal/template/method boundaries. Validator/rewriting execution, paused experiments, original Java conflicts and broader exchange-state defect remain separate.


## Local target routes — 2026-10-24

```sh
rtk proxy python3 /home/steve/workspace/light-example-rs/tests/lambda-parity/route_integration.py --out /home/steve/workspace/artifacts/implementation/light-lambda/parity-routes-20261024/rerun-01
```

Use a fresh output directory. Existing Java/Rust/backend pins and real Init/service/SDK/InvokeBridge are reused unchanged; no AWS calls or rebuilds. Two textual route-table orders exercise literal/parameter/wildcard/deep-template selection, method-specific targets, HEAD/GET/POST boundaries, outside-prefix rejection and warm recovery. v2:40/40 expectations,20/20 side-specific contracts,0/20 raw byte-identical,28 actual backend executions/completions and12 zero-dispatch rejections. All six owned processes reaped;7 focused/52 total Python tests pass.

The preserved v1/common golden run remains34/40: six native wildcard selections reflect the already-approved R-01a Java wildcard versus Rust longest-template difference. v1 and failed evidence are unchanged; additive routes-v2.json explicitly declares per-side targets. No production behavior or observations were normalized. Target routing is not Router rewriting; further shapes/AWS qualification remain separate. Report: /home/steve/workspace/artifacts/implementation/light-lambda/parity-routes-20261024/REPORT.md.


## Local middleware composition — 2026-10-24

```sh
rtk proxy python3 /home/steve/workspace/light-example-rs/tests/lambda-parity/composition_integration.py --out /home/steve/workspace/artifacts/implementation/light-lambda/parity-composition-20261024/rerun-01
```

Fresh output directory required. Uses the same pinned Java122d0339/Rustd095e89c/backend4e0bb9cc packages and production factory/Init/service/SDK paths. No rebuild, AWS calls or paused workers.30/30 functional checks:Java10 correlation/header-order and Rust20 header/full-Transformer checks; separately2/2 native missing-RuleExecutor404 ERR11406 service gates.22 actual executions/completions,8 functional zero-dispatch cases plus2 service gates; warm isolation/order contrasts/path changes before target dispatch/combined errors verified. All nine owned processes reaped.9 focused/61 total Python tests pass.

Native service rejection does not establish native Transformer action functionality. Selected equivalent Java fixture actions are characterization classes absent from the candidate fat JAR and no real provider is configured; a qualified native provider/action profile remains needed. No runner substitutes action logic. The two incomplete earlier attempts remain in local-01/local-02; explicit service.yml from the existing missing-executor fixture and a real Rust rule for shared layer validation fix adapter configuration only. Source fixtures and expectations unchanged. Report: /home/steve/workspace/artifacts/implementation/light-lambda/parity-composition-20261024/REPORT.md.
