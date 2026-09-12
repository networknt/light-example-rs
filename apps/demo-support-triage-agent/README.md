# Support triage agent behind light-a2a

This Rust example implements the private `light-a2a-backend/v1` contract using
Light Fabric's `a2a-backend` crate. It classifies a support description as access,
billing, availability, or general, and returns a priority and suggested steps.
It does not call a model, create tickets, fetch URLs, or take automatic actions.

The backend has one skill alias, `support-triage`. It accepts text parts, completes
synchronously, and persists the result before responding. Capabilities advertise
status reconciliation, with streaming and cancellation disabled. Requests for
those unsupported operations fail explicitly.

## Run the verified Docker demo

Check out `light-example-rs` and `light-fabric` side by side. From `light-example-rs`:

```sh
cargo test --locked -p demo-support-triage-agent
./build.sh 0.1.0-local-triage --local --app demo-support-triage-agent
python3 apps/demo-support-triage-agent/scripts/smoke-demo.py
```

The smoke script creates an isolated container and volume, supplies disposable
signed test identities, sends a request, tests replay rejection and idempotent
retry, restarts the container, and retrieves its persisted result. It removes
only its own generated container and volume. It does not change Portal, publish
an A2A policy, or claim Gateway/sidecar qualification. These test identities are
not an alternative to production Portal authorization.

Expected result for “Production outage affecting all users”:

```json
{
  "category": "availability",
  "priority": "high",
  "suggestedNextSteps": [
    "Check the service status and recent changes.",
    "Escalate to the service owner with a sanitized error report."
  ],
  "automaticActionTaken": false,
  "classifier": "deterministic-demo-v1"
}
```

The process listens only on `127.0.0.1:9010`. Publishing that port through Docker
is deliberately not the access mechanism. The smoke uses `docker exec` to call
loopback; the production caller is the colocated `light-a2a` sidecar.

## Exercise the actual light-a2a router

With the sibling `portal-config-loc` checkout available, run from `light-example-rs`:

```sh
python3 apps/demo-support-triage-agent/scripts/test-sidecar.py
```

This provisions an isolated PostgreSQL container using the canonical operational
migration bundle, then runs the actual `light-a2a` router against the backend.
It verifies A2A message invocation, task persistence and retrieval after sidecar
state restart. The script deletes its own database container and temporary files.
It never accesses the running Portal database.

This is a debug-build integration fixture with an explicitly unsigned test Agent
Card and simulated Gateway-signed invocation. It verifies the real sidecar and
backend code, but does not test Config Server bootstrap, live Portal publication,
Agent Card signing or Gateway policy. Production deployment still requires the
normal signed publication described below. Release builds reject the fixture's
unsigned Agent Card.

## Deploy with the actual sidecar

`deploy/compose.yml` defines a pair on an existing Portal network. It does not
create the Portal instance, signing authority, or operational database. Complete
the [Portal tutorial](https://doc.lightapi.net/tutorial/light-a2a.html) first.
Its source is `light-portal-doc/src/tutorial/light-a2a.md` in the sibling checkout.

The `triage-network` infrastructure container owns the network namespace. Both
applications join with `network_mode: service:triage-network`; the sidecar waits
for backend health before starting. Independent application crashes/restarts
therefore leave the network namespace intact. Use Compose to restart or recreate
the infrastructure service and its dependents together. Only A2A
port 8448 is mapped to the host (8458 by default); port 9010 has no public mapping.
Gateway reaches `support-triage-a2a:8448` on the selected Portal network. Configure
the runtime's advertised address accordingly.

The backend's private JSON file pins the exact host, environment, agent, binding,
publication, policy digest, data-boundary digest, audience and context-key path.
Generate it from an exported **activated** A2A values JSON:

```sh
python3 apps/demo-support-triage-agent/scripts/prepare-backend.py \
  --values /absolute/private/active-a2a-values.json \
  --host-id YOUR_HOST_UUID \
  --agent-ref support-triage \
  --output /absolute/private/backend.json
```

Export a flat JSON object in one of these forms:

- Config Server values: `a2a.a2aPolicy.bindings` and `a2a.runtimePolicy.envTag`.
- Raw snapshot properties: `a2aPolicy.bindings` and `runtimePolicy.envTag`.

Bindings may be a JSON array or its encoded JSON string. Do not mix the forms.
The environment tag is required and preserved exactly; the helper never assumes
`dev`. If a snapshot relies on a template default, export the resolved Config
Server value explicitly before preparing the backend.

The helper reads publication data; it does not independently authenticate the
export or activate a policy. It refuses overwrites. When republishing, generate
a new file, review it and recreate both containers together so the sidecar and
backend agree on publication identity.

Supply the variables listed in `deploy/example.env` in a private env file:

```sh
docker compose --env-file /absolute/private/triage.env \
  -f apps/demo-support-triage-agent/deploy/compose.yml up -d --wait
```

Mount the same backend context key in both containers at
`/run/secrets/triage-context-key`. The sidecar also needs its own Gateway context
key and scoped database URL files; these are separate credentials. Only the
individual backend key file is mounted into the backend; the full secret
directory is mounted exclusively into the sidecar. Use protected
files readable by UID/GID 999. The backend and its state volume also run as 999.
No real keys or credentials are included in this repository.

## Extend the business logic

Start in `src/lib.rs::triage`. Keep platform authentication in the canonical
adapter. The adapter checks the HMAC, invocation expiry, exact published identity,
request digest, business identifiers, operation and persistent replay guard.
The backend additionally enforces skill selection, input/output budgets, task
ownership and idempotency conflicts.

Each task's result is atomically persisted and synced before acknowledgement.
The state directory is locked to one process. The demo allows at most 1,000 tasks
and 16 MiB of persisted results; it fails closed when full or corrupt. There is
no retention worker in this sample. For production replace the bounded file
store with transactional storage, retention and recovery appropriate to your
business. Do not share this state directory across replicas or erase it while
promising retry/recovery continuity.

For a slow or asynchronous model-backed agent, implement durable pending work,
status reconciliation and cancellation before advertising those capabilities.
Reusing the synchronous example unchanged does not provide that lifecycle.

## Optional local LLM mode

The default classifier is deterministic. To use a real model, add this object to
the backend JSON produced by `scripts/prepare-backend.py`:

```json
"llm": {
  "endpoint": "https://llm-gateway:8443/v1/chat/completions",
  "model": "assistant-dev",
  "tokenFile": "/run/triage-llm/user.jwt",
  "caFile": "/app/config/ca.pem"
}
```

Mount an authorized local operator credential and the gateway CA at those paths,
readable by the backend UID. The backend uses this separate credential; it never
forwards the incoming A2A caller token. Configure the AgentDefinition with the
same real model alias and publish a transport data-boundary digest describing
that model call. The local Portal gateway policy must authorize this operator
for `/v1/chat/completions@post` and the selected model alias.

LLM mode uses HTTPS, a 45-second timeout, bounded structured output, and validates
category, priority and suggested steps. It reports `classifier: llm-gateway` and
`automaticActionTaken: false`. Failures propagate as backend failures; no hidden
deterministic fallback occurs. The demo serializes requests while persisting its
small task store. It is intended for local experimentation, not throughput tests.

## Verify local container restart behavior

After deployment, run the explicit restart check with the actual container names:

```sh
bash apps/demo-support-triage-agent/scripts/verify-pair-restarts.sh \
  all-in-lt-triage-network-1 all-in-lt-demo-support-triage-agent-1 light-a2a
```

This restarts each application and signals the backend process to exercise its
automatic restart policy. It checks readiness and shared namespace identity after
each operation. It deliberately changes container state; run it on the local demo.
