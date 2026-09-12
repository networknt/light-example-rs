#![cfg(feature = "sidecar-test")]
//! Real light-a2a router and PostgreSQL; test-only publication authority.
use a2a_backend::{
    AdapterConfig, AgentBackend, BackendExpectation, BackendOperation, FileReplayStore,
    adapter_router,
};
use a2a_core::{
    AuthorizedInvocation, Direction, canonical_projection_digest, sign_authorized_invocation,
};
use chrono::Utc;
use demo_support_triage_agent::TriageBackend;
use light_a2a::{A2aConfig, A2aState};
use serde_json::{Value, json};
use std::{path::PathBuf, sync::Arc};
use uuid::Uuid;

#[tokio::test]
#[ignore = "run scripts/test-sidecar.py to provision a disposable PostgreSQL database"]
async fn a2a_router_invokes_real_backend_and_recovers_task() {
    let fixture = PathBuf::from(
        std::env::var("TRIAGE_SIDECAR_FIXTURE").expect("disposable fixture required"),
    );
    let environment: Value =
        serde_json::from_slice(&std::fs::read(fixture.join("fixture.json")).unwrap()).unwrap();
    let host: Uuid = serde_json::from_value(environment["hostId"].clone()).unwrap();
    let binding = Uuid::now_v7();
    let publication = Uuid::now_v7();
    let policy = format!("sha256:{}", "a".repeat(64));
    let boundary = format!("sha256:{}", "b".repeat(64));
    let key = vec![b'k'; 32];
    std::fs::write(fixture.join("backend-key"), &key).unwrap();
    std::fs::write(fixture.join("gateway-key"), &key).unwrap();
    let backend = TriageBackend::open(&fixture.join("business-state")).unwrap();
    let capabilities = backend.capabilities();
    let backend_listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let backend_origin = format!("http://{}/", backend_listener.local_addr().unwrap());
    let backend_router = adapter_router(
        backend,
        AdapterConfig {
            expectation: BackendExpectation {
                audience: "support-triage-backend".into(),
                host_id: host,
                environment: "dev".into(),
                target_agent_ref: "support-triage".into(),
                binding_id: binding,
                publication_id: publication,
                policy_digest: policy.clone(),
                data_boundary_digest: boundary.clone(),
                operation: BackendOperation::Invoke,
                skill_id: None,
            },
            key: Arc::new(key.clone()),
            maximum_request_bytes: 16384,
            replay_store: Arc::new(
                FileReplayStore::new(fixture.join("business-state/replay.json"), 10000).unwrap(),
            ),
        },
    );
    let backend_server =
        tokio::spawn(async move { axum::serve(backend_listener, backend_router).await.unwrap() });
    let now = Utc::now();
    let bindings = json!([{"agentRef":"support-triage","bindingId":binding,"publicationId":publication,
        "policyDigest":policy,"directions":["INBOUND"],"backendKind":"EXTERNAL_SIDECAR","backendBindingId":Uuid::now_v7(),
        "backendTransport":{"contractVersion":"light-a2a-backend/v1","contractDigest":a2a_backend::contract_digest_value(),
            "origin":backend_origin,"audience":"support-triage-backend","contextKeyFile":fixture.join("backend-key"),
            "dataBoundaryDigest":boundary,"requestTimeoutMs":5000,"maximumRequestBytes":16384,"maximumResponseBytes":16384,
            "capabilities":capabilities},
        "protocolProfile":{"version":"0.3","maximumExtensionCount":0,"maximumExtensionBytes":0},"allowedOperations":["SEND_MESSAGE","GET_TASK","GET_AGENT_CARD"],
        "allowedSkillIds":["support-triage"],"allowedPrincipalPrefixes":["user:"],
        "publicUrl":"https://agents.example/a2a/support-triage",
        "agentCard":{"name":"Support triage","url":"https://agents.example/a2a/support-triage","skills":[]},
        "artifactRetention":{"profileId":Uuid::now_v7().to_string(),"taskRetentionDays":1,"artifactRetentionDays":1,
            "maximumArtifactBytes":65536,"accessPolicyRef":"demo"}}]);
    let content_digest = canonical_projection_digest(&json!({"bindings":bindings})).unwrap();
    let mut config: A2aConfig=serde_json::from_value(json!({
        "runtimePolicy":{"publicationId":publication,"releaseVersion":1,"policySnapshotId":publication,
            "policyVersion":1,"policyDigest":content_digest,"audience":"light-a2a","host":"dev.lightapi.net",
            "serviceId":"com.networknt.light-a2a-1.0.0","envTag":"dev","contentDigest":content_digest,
            "sourceEventSequence":1,"schemaVersion":1,"createdAt":(now-chrono::Duration::minutes(2)).to_rfc3339(),
            "validFrom":(now-chrono::Duration::minutes(1)).to_rfc3339(),"refreshAfter":(now+chrono::Duration::minutes(10)).to_rfc3339(),
            "expiresAt":(now+chrono::Duration::minutes(20)).to_rfc3339(),"revocationEpoch":0,"compatibilityGeneration":1},
        "operationalStore":{"contractVersion":2,"bindingId":environment["bindingId"],"bindingDigest":environment["bindingDigest"],
            "hostId":host,"environment":"dev","serverHost":"127.0.0.1","port":environment["port"],"tlsMode":"DISABLE",
            "serviceOwner":"light-a2a","schema":"a2a_ops","expectedDatabase":"operations","minimumSchemaGeneration":2,
            "databaseUrlFile":fixture.join("a2a-url"),"credentialGeneration":1},
        "managedArtifactStore":{"bindingId":environment["bindingId"],"bindingDigest":environment["bindingDigest"],
            "minimumSchemaGeneration":2,"databaseUrlFile":fixture.join("artifact-url"),"rootDirectory":fixture.join("artifacts"),
            "scanProfileId":"demo","allowedMediaTypes":["text/plain"]},
        "authorizationContextKeyFile":fixture.join("gateway-key"),"maximumDatabaseConnections":2,
        "maximumRequestBytes":16384,"maximumResponseBytes":65536,"requestTimeoutMs":5000,
        "allowUnsignedAgentCards":true,"bindings":bindings})).unwrap();
    config.runtime_policy.content_digest =
        canonical_projection_digest(&json!({"bindings": config.bindings})).unwrap();
    config.runtime_policy.policy_digest = config.runtime_policy.content_digest.clone();
    // Unsigned authority is explicitly test-only and is rejected in release builds.
    config
        .validate("dev.lightapi.net", "com.networknt.light-a2a-1.0.0", "dev")
        .unwrap();
    let state = Arc::new(A2aState::build(config.clone()).await.unwrap());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let router = light_a2a::router(state.clone());
    let sidecar = tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
    assert_eq!(
        reqwest::get(format!("{origin}/_a2a/ready"))
            .await
            .unwrap()
            .status(),
        200
    );
    let task = Uuid::now_v7();
    let body = json!({"jsonrpc":"2.0","id":1,"method":"message/send","params":{
        "taskId":task,"contextId":Uuid::now_v7(),"message":{"role":"user","messageId":"demo-1",
        "metadata":{"skillId":"support-triage"},"parts":[{"kind":"text","text":"Production outage affecting all users"}]}}});
    let mut invocation = AuthorizedInvocation {
        host_id: host,
        audience: "light-a2a".into(),
        principal_subject: "user:demo".into(),
        caller_agent_ref: "test-gateway".into(),
        target_agent_ref: "support-triage".into(),
        binding_id: binding,
        policy_digest: policy,
        publication_id: publication,
        direction: Direction::Inbound,
        idempotency_key: "demo-1".into(),
        request_digest: String::new(),
        outbound: None,
        issued_at: now,
        expires_at: now + chrono::Duration::minutes(2),
    };
    let result = rpc(&origin, &body, &mut invocation, &key).await;
    assert_eq!(result["result"]["state"], "COMPLETED", "{result}");
    assert!(result.to_string().contains("availability"), "{result}");
    sidecar.abort();
    let _ = sidecar.await;
    state.pool().close().await;
    state.artifact_pool().close().await;
    drop(state);
    let state = Arc::new(A2aState::build(config).await.unwrap());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let router = light_a2a::router(state.clone());
    let sidecar = tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
    let get = json!({"jsonrpc":"2.0","id":2,"method":"tasks/get","params":{"id":task}});
    invocation.idempotency_key = "get-1".into();
    let recovered = rpc(&origin, &get, &mut invocation, &key).await;
    assert_eq!(recovered["result"], result["result"], "{recovered}");
    sidecar.abort();
    let _ = sidecar.await;
    backend_server.abort();
    let _ = backend_server.await;
    state.pool().close().await;
    state.artifact_pool().close().await;
}

async fn rpc(
    origin: &str,
    body: &Value,
    invocation: &mut AuthorizedInvocation,
    key: &[u8],
) -> Value {
    let body = serde_json::to_vec(body).unwrap();
    invocation.request_digest = a2a_core::request_digest(&body);
    let (context, signature) = sign_authorized_invocation(invocation, &body, key).unwrap();
    reqwest::Client::new()
        .post(format!("{origin}/a2a/support-triage"))
        .header("content-type", "application/json")
        .header("x-light-a2a-context", context)
        .header("x-light-a2a-signature", signature)
        .body(body)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap()
}
