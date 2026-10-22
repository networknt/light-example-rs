# Rust Lambda trial backend

Dedicated, nonpersistent business Lambda for Light Lambda qualification. It does
not replace the Java pet-store functions. No database, credentials, outbound
dependencies, public endpoint or request authentication implementation. AWS IAM
must limit who can invoke it. Deploy separately as a non-VPC Lambda, with no
Function URL, triggers or public invocation permissions.

The backend consumes the API Gateway proxy-shaped **business event** produced by
the gateway. This does not expand the gateway's ALB-shaped ingress support.
`body` is a JSON string containing exactly `mode` and `trialId`:

| Mode | Backend result | Purpose |
| --- | --- | --- |
| `success` | HTTP 200 with matching trialId | Dispatch and warm recovery |
| `application-error` | HTTP 500, TRIAL_BACKEND_ERROR | Backend application error propagation |
| `function-error` | Runtime API error submission | Real Lambda FunctionError mapping |

Invalid input returns HTTP 400/TRIAL_INVALID_COMMAND. Body limit is 1024 bytes;
trialId is 1–64 ASCII letters, digits, hyphens or underscores. Base64 bodies,
unknown modes, unknown command fields and non-string bodies are rejected. Each
execution emits one `trial_backend_execution` JSON record with the AWS request
ID, static mode and validated trial ID (omitted for invalid commands). It never
logs headers, tokens or payloads. AWS platform START/REPORT records provide
independent execution IDs after deployment. No sleeps, retries, persistence or
timeout/resource experiments are implemented.

## Build and test

Run from the repository root. Choose a fresh evidence path for each test:

```bash
rtk cargo test -p lambda-trial-backend --locked
rtk cargo clippy -p lambda-trial-backend --all-targets --locked -- -D warnings
rtk cargo build -p lambda-trial-backend --release --target x86_64-unknown-linux-musl --locked
rtk proxy python3 -B apps/lambda-trial-backend/test_runtime.py \
  --binary target/x86_64-unknown-linux-musl/release/lambda-trial-backend \
  --out /ABSOLUTE/FRESH/backend-runtime-evidence
rtk proxy python3 -B apps/lambda-trial-backend/package.py \
  --binary target/x86_64-unknown-linux-musl/release/lambda-trial-backend \
  --out /ABSOLUTE/FRESH/backend-package
```

Install the musl Rust target/toolchain if absent. The Runtime API test launches
the actual compiled backend against an owned loopback endpoint and checks five
events in one process: success → application error → FunctionError → warm
success → invalid command. It verifies distinct response IDs, one execution log
per event, privacy and process reaping. This is executable Runtime API evidence,
not RIE or AWS evidence. Packaging is deterministic for identical binary bytes;
it is not a claim of byte-identical compilation across toolchains. The packager
checks ELF architecture and ZIP layout; build the stated musl target and inspect
static linkage before deployment.

## Separate AWS qualification

The ZIP contains only executable `bootstrap`. Use a new function such as
`light-lambda-rust-direct-trial-error-backend`, x86_64, provided.al2023, handler
bootstrap. Suggested initial test settings: 128 MB, timeout 5 seconds. These are
trial settings, not established production resource bounds. Its execution role
needs only logs access to its own log group; no InvokeFunction permission or
access to business resources. Creating AWS resources and IAM grants is a
separate operation; these scripts perform neither.

Console Test events in `events/` directly invoke **this backend**. FunctionError
must be checked separately from HTTP 500: application-error is a successful
Lambda invocation containing a statusCode of 500, while function-error fails
the Lambda invocation itself. A warm success must follow both errors.

For gateway testing, use a separate qualification configuration/layer mapping
only the selected synthetic route to this new function, preserving the original
layer and four pet-store mappings. Keep security enabled. Send an ALB-shaped
gateway event with a fresh valid bearer token and the command as its body.
Never save the token in a shared test event or evidence. The gateway role needs
an explicitly scoped InvokeFunction grant on the actual new backend ARN before
testing; do not assume the existing four-function grant covers it. Require
gateway error mapping, no leakage of FunctionError details, request-correlated
backend counts and valid warm recovery. Rejections must have zero executions.
Do not claim this qualification until those application paths run in AWS.

Cleanup affects only the dedicated backend, its role/log group and separate
qualification resources after ownership verification. Manual cleanup only;
retained logs and resources can incur charges. No existing pet-store data exists
in this backend to delete. Validator, Router rewriting and paused precision
experiments remain excluded.

## 2026-10-22 deployment checkpoint

Deployed separately to account `964637446810`, region `us-east-2`, function
`light-lambda-rust-direct-trial-error-backend`, provided.al2023/x86_64,
handler `bootstrap`, 128 MB, timeout 5 seconds. Dedicated execution role
`light-lambda-rust-trial-backend-role` has only `TrialBackendOwnLogs`, scoped to
its own log group. No VPC or public endpoint was configured.

ZIP SHA-256: `58106f420cf81efa891ce1485d7be579139170bb41021751c89908a2a4da3ab1`.
AWS CodeSha256 matched. Four final-configuration AWS direct-Invoke checks passed:
success, application 500, FunctionError and warm success. Four initial checks
at an accidentally saved 35-second timeout are preserved separately; all modes
were rerun after correcting and verifying the intended five-second timeout.

Evidence: `/home/steve/workspace/artifacts/implementation/light-lambda/WP17-backend-deployment-20261022/REPORT.md`.
The accepted gateway remains unchanged. Gateway-through-backend qualification
and an attributable JWKS request count remain pending.
