# Stage 3 review preparation — no AWS execution authorized

## Concrete running-backend scope (2026-10-22)

After the fourteen-case real-transport integration passes, use
`prepare_stage3.py --integration <output> --out <fresh-output>` to bind a review
package to that evidence. The current concrete scope is
`artifacts/implementation/light-lambda/parity-stage3-review-20261022T224001Z/AWS-SCOPE.md`.
It contains the exact new names, artifacts, two dedicated configuration layers,
resolved narrow IAM policies and three executable CloudFormation JSON templates.
`validate_stage3.py <scope-output>` performs local structural/pin checks only.

The old `prepare.py` flow below is retained as earlier generic preparation.
The new scope requires fresh names and immutable backend `:1` output readback;
an unexpected version stops execution. Actual S3 VersionIds are pending until
approved upload and must never be guessed. No deployment/test/cleanup authority
is implied by generating this package. Cleanup remains a separate explicit
decision; no TTL, bucket lifecycle deletion or automatic teardown is installed.
Future stack creation must use `--on-failure DO_NOTHING` so a failed deployment
does not implicitly delete trial resources before a cleanup decision.

`prepare.py` only reads ZIPs and writes a fresh review directory. Both templates
are CloudFormation expressed as JSON (valid YAML). They have no public ingress,
resource-based Invoke permission, VPC, denied target or delay target. No command
in the local suite invokes AWS. These are unqualified deployment candidates.

Prepare the concrete artifact scope from repository root:

```sh
rtk proxy python3 -B deploy/lambda-parity/prepare.py \
  --account 964637446810 --region us-east-2 --profile YOUR_EXPLICIT_PROFILE \
  --prefix parity-YOUR-UNIQUE-TRIAL \
  --backend-zip /ABSOLUTE/backend.zip \
  --java-zip /ABSOLUTE/java-native.zip --rust-zip /ABSOLUTE/rust.zip \
  --out /home/steve/workspace/artifacts/implementation/light-lambda/FRESH-aws-review
```

Use a lowercase unique prefix. Review `review.json`, both templates, the local
per-case report, exact ZIP/code digests, IAM policies, selected AWS cases and
estimated regional charges with the owner before any uploads or AWS actions.
`deployable:false` is deliberate: unresolved versions/configuration and execution
evidence must not be inferred from a template. Example parameters contain
placeholders and cannot be used as a deployment manifest.

After separate authorization, the intended order is:

1. Verify STS account, explicit profile and region against the approved manifest.
   Upload reviewed ZIPs into a versioned trial-owned bucket; record object versions.
2. Create the separate backend stack from `backends.template.yaml`. Both identities
   use the same ZIP digest. Resolve and record immutable version outputs and actual
   CodeSha256, architecture, memory, timeout, environment and role policies. Directly
   prove modes before treating the backend as an oracle. Preserve failed evidence.
3. Prepare separate trial-only Java and Rust config layers mapping `/parity/a@post`
   and `/parity/b@post` to those exact versions. Adapt existing native and Rust
   packaging tools; do not copy an accepted deployment's private configuration.
   Start proxy-only with application authentication disabled and mark that scope.
   JWT profiles require a separate equivalent-claims credential plan. Confirm Java
   bootstrap passes its config directory property; the Rust directory environment
   variable alone does not configure Java. Pin config and layer digests/versions.
4. Review the completed gateway manifest, then create the gateway stack using
   `template.yaml`. Roles can invoke only the two qualified backend versions, plus
   write their own logs. No runner or deployment privilege belongs on those roles.
5. Use a separate runner role for exact qualified gateway/backend Invoke ARNs,
   configuration readback and the four trial log groups. Disable client retries.
   Recheck all pinned versions before and after the run. Record outer Invoke
   FunctionError independently from gateway HTTP status. Do not use the local
   stub runner as an AWS runner: stage 3 execution/collection adapters are pending.
6. For each side/case/attempt use new bounded synthetic IDs. Collect entry and
   completion records for up to 60 seconds. Deduplicate by backend execution request
   ID, not log line count. Prove delivery with an A/B positive control from the
   intended version/stream. No completion is expected for FunctionError or timeout.
   Missing log evidence yields inconclusive, never proof of zero execution.
7. Keep selected/total counts and unsupported inventory in the report. Run pet-store
   checks separately; this suite does not replace them. IAM denial/delay need their
   own scoped resources and authorization. Do not widen IAM to enable a case.

Manual cleanup requires owner confirmation at action time. Only the two named
trial stacks, their generated roles, four functions and trial-owned layers are in
scope. Logs and published versions have Retain policies, so stack deletion alone
does not clean them up. Inventory those exact retained ARNs before separately
approved deletion. Preserve evidence, original pet-store functions, accepted
gateways/configuration, shared buckets and shared IAM. Retained resources may incur
charges. No cleanup is automated here.


## Received-event observation candidate — no AWS execution authorized here

[Exact version2 update scope](/home/steve/workspace/artifacts/implementation/light-lambda/parity-backend-observations-20261022T234816Z/aws-update-review/AWS-SCOPE.md) and templates preserve all stage3 version1/layer resources and evidence. Candidate backend ZIP SHA-256 `471449cbb17f78547520c1f78b12a5dda94fe6f7c2cc0619aa9346ff38c41130`. Local actual-gateway/SDK/backend qualification passes; AWS validation/change sets, actual object versions and published:2 identity verification remain pending separate approval. Only dedicated stage3 resources are proposed for update; no accepted standalone gateways, public ingress, cleanup, deferred capability or JWKS scope. Never treat received-event records as SDK-wire evidence.
