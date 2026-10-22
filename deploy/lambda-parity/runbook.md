# Stage 3 review preparation — no AWS execution authorized

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
