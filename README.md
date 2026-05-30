# light-example-rs

Rust example applications for Light-Fabric.

## Demo Workflow Orchestration APIs

This repository contains two small `light-axum` services for the skill and
workflow orchestration demo:

| App | Service id | Default port | Endpoints |
| --- | --- | ---: | --- |
| `demo-customer-profile-api` | `com.networknt.demo.customer-profile-1.0.0` | `8085` | `GET /customers/{customerId}`, `GET /customers/{customerId}/preferences`, `GET /customers/{customerId}/policies`, `GET /customers/{customerId}/vehicles/{vehicleId}`, `GET /customers/{customerId}/prior-claims`, `GET /health` |
| `demo-offer-decision-api` | `com.networknt.demo.offer-decision-1.0.0` | `8086` | `GET /offers`, `POST /offer-decisions`, `POST /claim-triage`, `POST /settlement-recommendations`, `GET /health` |

Both apps use `LightRuntimeBuilder` with `AxumTransport`, so they can load
configuration from config-server and register with controller through
`portal-registry`.

Local config defaults keep controller registration disabled so the services can
run without a portal stack. Config-server examples under `config-registry/`
enable controller registration for a full demo environment.

## Run Locally

From the repository root:

```sh
cargo run -p demo-customer-profile-api
cargo run -p demo-offer-decision-api
```

Smoke checks:

```sh
curl -s http://127.0.0.1:8085/customers/CUST-1001
curl -s "http://127.0.0.1:8085/customers/CUST-1001/preferences?channel=portal"
curl -s http://127.0.0.1:8085/customers/CUST-1001/policies
curl -s http://127.0.0.1:8085/customers/CUST-1001/vehicles/VEH-1001
curl -s http://127.0.0.1:8085/customers/CUST-1001/prior-claims
curl -s "http://127.0.0.1:8086/offers?segment=premium&state=ON&category=travel"
curl -s -X POST http://127.0.0.1:8086/offer-decisions \
  -H 'content-type: application/json' \
  -H 'idempotency-key: wf-demo-1001' \
  -d '{"customerId":"CUST-1001","offerId":"OFFER-TRAVEL-01","channel":"portal","source":"workflow","reason":"demo"}'
curl -s -X POST http://127.0.0.1:8086/claim-triage \
  -H 'content-type: application/json' \
  -d '{"claim":{"claimId":"CLM-1001","customerId":"CUST-1001","vehicleId":"VEH-1001","injuryReported":false,"vehicleDrivable":false},"customer":{"customerId":"CUST-1001","segment":"premium","state":"ON"},"policies":{"policies":[{"policyId":"POL-AUTO-1001","status":"active"}]},"vehicle":{"vehicleId":"VEH-1001","covered":true},"priorClaims":{"priorClaimCount":1,"recentClaimCount":0}}'
curl -s -X POST http://127.0.0.1:8086/settlement-recommendations \
  -H 'content-type: application/json' \
  -H 'idempotency-key: claim-demo-1001' \
  -d '{"claim":{"claimId":"CLM-1001","customerId":"CUST-1001"},"coverageReview":{"deductible":500},"triage":{"recommendedPath":"repair","estimatedLoss":3200},"approval":{"decision":"APPROVED"}}'
```

Insurance claim demo records are deterministic:

- `CUST-1001`: active Ontario auto policy, covered `VEH-1001`, low/medium risk repair path.
- `CUST-2002`: expired policy and uncovered `VEH-2002`, review/SIU path.
- `CUST-3003`: active policy and covered vehicle, but consent is disabled for customer-info branches.
- unknown customers return `404` for profile and insurance context endpoints.

## OpenAPI Specifications

Upload these files in the API version form to create endpoint records:

```text
apps/demo-customer-profile-api/openapi.yaml
apps/demo-offer-decision-api/openapi.yaml
```

## Config-Server And Controller

The runtime config templates are in each app's `config/` directory:

```text
startup.yml
server.yml
portal-registry.yml
client.yml
values.yml
```

For a full portal demo, publish values equivalent to:

```text
config-registry/demo-customer-profile-api/values.yml
config-registry/demo-offer-decision-api/values.yml
```

The important values are:

```yaml
server.enableRegistry: true
server.advertisedAddress: demo-customer-profile-api
portalRegistry.portalUrl: https://controller.lightapi.svc.cluster.local:8438
light-config-server-uri: https://config-server.lightapi.svc.cluster.local:8435
```

Set `LIGHT_CONFIG_SERVER_URI` and `LIGHT_PORTAL_AUTHORIZATION` before starting
the apps. `LIGHT_CONFIG_SERVER_URI` is used during bootstrap to fetch
config-server values, including `server.httpPort`; `LIGHT_PORTAL_AUTHORIZATION`
is used for config-server access and controller registration. After startup,
the control panel should show both services in service discovery with
environment `demo`.

## Docker Images

Prerequisites for publishing:

- Docker daemon running
- `docker login` completed for the target Docker Hub namespace

Build both Docker images locally:

```sh
./build.sh 0.1.0 --local
```

Publish both images to Docker Hub:

```sh
./build.sh 0.1.0
```

The default Docker Hub namespace is `networknt`, producing:

```text
networknt/demo-customer-profile-api:0.1.0
networknt/demo-offer-decision-api:0.1.0
```

Use `DOCKER_ORG` or `--image-org` to publish under another namespace. Use
`--app demo-customer-profile-api` or `--app demo-offer-decision-api` to build
one image.

The Docker build context is the parent workspace directory because this repo
uses local path dependencies from `../light-fabric`.

## GitHub Binary Release

Prerequisites for publishing:

- GitHub CLI `gh` installed and authenticated
- `rustup` installed
- `musl-tools` and `pkg-config` installed for the `x86_64-unknown-linux-musl`
  target

Build Linux release archives locally:

```sh
./release.sh v0.1.0 --local
```

Create or update a GitHub release with the archives:

```sh
./release.sh v0.1.0
```

The release archives include both binaries plus their config templates:

```text
bin/demo-customer-profile-api
bin/demo-offer-decision-api
config/demo-customer-profile-api/
config/demo-offer-decision-api/
```
