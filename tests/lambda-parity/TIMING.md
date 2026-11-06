# Local IAM/timing parity batch

This additive batch uses `timing-v1.json`, `timing_integration.py` and `timing_backend.py`, reusing `integration.py` Runtime, packaged configuration/layer tooling and Invoke bridge. Original `cases.json`, fixtures, version-2 AWS qualification and the eleven deferred/unavailable entries are unchanged. New capabilities remain separate from that inventory until their AWS gates are satisfied.

Finite delay modes require both identity `delay` and startup `PARITY_BACKEND_TIMING=bounded-v1`. Durations are fixed250/2500/6000ms; events cannot choose arbitrary sleep/resource limits. Backend platform timeout is4s. Java fast SDK cap is1s; Rust fast uses real ingress1350ms/request1100ms/response1250ms with SDK caps10s. Patient caps10s allow the backend4s limit to fire first. Timing windows and per-side error codes are declared before execution in the JSON contract.

Local tests use synthetic credentials, owned Invoke HTTP and actual packaged Java/Rust application Init/service/SDK plus actual backend executables. IAM HTTP403 and Lambda platform timeout are **explicit simulations**. Platform timeout instrumentation terminates and reaps the actual synthetic backend, records its identity, and emits clearly labelled simulated platform error bytes. This is not real AWS IAM or Lambda-timeout proof. A gateway timeout does not stop the actual delayed backend: late completion is required before the test finishes.

```bash
cd /home/steve/workspace/light-example-rs
rtk cargo build --locked --release --target x86_64-unknown-linux-musl -p lambda-trial-backend
rtk proxy python3 tests/lambda-parity/timing_backend.py \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/timing-direct-NEW
rtk proxy python3 tests/lambda-parity/timing_integration.py \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/timing-paired-NEW
```

Use fresh output directories. Current qualification is **17/18 expectations**, Rust9/9 and Java8/9. The integration command correctly exits1: Java TIMING-backend-timeout-recovery step1 returns an outer exchange-state error rather than declared500/ERR14004. Recovery itself succeeds. Do not retry automatically, relabel this difference or change expectations. See the exact proposed narrow native guard and one decision in the evidence package below.

Four priming requests are counted separately from18 selected steps. Selected steps require16 backend entries/14 normal completions (two platform timeouts), with zero executions for the two denied calls. Including priming:22 SDK sends,20 entries,18 completions. Each gateway profile remains one real process, and every owned process is reaped. Raw responses, backend records, send IDs, simulation boundaries and timing observations remain available.

Offline AWS preparation only:

```bash
rtk proxy python3 deploy/lambda-parity/prepare_timing.py \
  --evidence /home/steve/workspace/artifacts/implementation/light-lambda/parity-timing-local-20261023T011243Z \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/timing-scope-NEW
```

This emits two new-resource templates, four isolated configuration layers, exact hashes/IAM/event plan and a non-ready review manifest. The separately written authoritative AWS-SCOPE.md and decision are under `/home/steve/workspace/artifacts/implementation/light-lambda/parity-timing-local-20261023T011243Z/`. No AWS call, deployment or cleanup is performed. A Java repair and newly qualified/pinned candidate remain required before an executable deployment approval.


Approved proxy-mitigation candidate: [report](/home/steve/workspace/artifacts/implementation/light-lambda/parity-java-proxy-mitigation-20261023T020303Z/REPORT.md). Explicit --java-zip plus --candidate-manifest selects ZIP923ea10b…a7728d;18/18 timing and existing14-case integration pass. Accepted default ZIP pins still select the original behavior. The broad original characterization retains one exception-assertion conflict; explicit test-only proxy-missing-status-v1 passes the versioned contract without altering original fixture expectations. Shared exchange APIs remain unchanged; no AWS deployment authorization.
