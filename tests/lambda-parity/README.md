# Lambda gateway parity, initial local batch

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
