use a2a_backend::*;
use chrono::Utc;
use demo_support_triage_agent::{SKILL, TriageBackend, triage};
use serde_json::json;
use std::{path::Path, sync::Arc, time::Duration};
use uuid::Uuid;

fn context() -> BackendAuthorizedInvocation {
    let now = Utc::now();
    BackendAuthorizedInvocation {
        contract_version: CONTRACT_VERSION.into(),
        invocation_id: Uuid::now_v7(),
        issuer: "light-a2a".into(),
        audience: "support-triage-backend".into(),
        host_id: Uuid::now_v7(),
        environment: "dev".into(),
        principal_subject: "user:alice".into(),
        caller_agent_ref: "support-client".into(),
        target_agent_ref: "support-triage".into(),
        binding_id: Uuid::now_v7(),
        publication_id: Uuid::now_v7(),
        selected_skill_id: Some(SKILL.into()),
        operation: BackendOperation::Invoke,
        task_id: Uuid::now_v7(),
        context_id: Uuid::now_v7(),
        idempotency_key: "first-message".into(),
        backend_operation_id: None,
        policy_digest: format!("sha256:{}", "a".repeat(64)),
        data_boundary_digest: format!("sha256:{}", "b".repeat(64)),
        request_digest: String::new(),
        budget: InvocationBudget {
            maximum_input_bytes: 16384,
            maximum_output_bytes: 16384,
            maximum_artifact_bytes: 65536,
        },
        traceparent: None,
        issued_at: now,
        deadline: now + chrono::Duration::minutes(2),
        expires_at: now + chrono::Duration::minutes(1),
    }
}

fn request(context: &BackendAuthorizedInvocation) -> BusinessRequest {
    BusinessRequest {
        task_id: context.task_id,
        context_id: context.context_id,
        idempotency_key: context.idempotency_key.clone(),
        skill_id: context.selected_skill_id.clone(),
        message: json!({"role":"user","parts":[{"kind":"text","text":"Production outage affecting all users"}]}),
        metadata: json!({}),
    }
}

fn fresh(context: &mut BackendAuthorizedInvocation, request: &BusinessRequest) {
    context.invocation_id = Uuid::now_v7();
    context.request_digest = request_digest(&serde_json::to_vec(request).unwrap());
}

async fn start(
    path: &Path,
    context: &BackendAuthorizedInvocation,
    key: Arc<Vec<u8>>,
) -> (BackendClient, String, tokio::task::JoinHandle<()>) {
    let backend = TriageBackend::open(path).unwrap();
    let router = adapter_router(
        backend,
        AdapterConfig {
            expectation: BackendExpectation {
                audience: context.audience.clone(),
                host_id: context.host_id,
                environment: context.environment.clone(),
                target_agent_ref: context.target_agent_ref.clone(),
                binding_id: context.binding_id,
                publication_id: context.publication_id,
                policy_digest: context.policy_digest.clone(),
                data_boundary_digest: context.data_boundary_digest.clone(),
                operation: BackendOperation::Invoke,
                skill_id: None,
            },
            key: key.clone(),
            maximum_request_bytes: 16384,
            replay_store: Arc::new(FileReplayStore::new(path.join("replay.json"), 10000).unwrap()),
        },
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}/", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let client = BackendClient::new(
        BackendEndpoint::parse(&origin).unwrap(),
        key,
        Duration::from_secs(5),
        65536,
    )
    .unwrap();
    (client, origin, handle)
}

#[test]
fn deterministic_text_only_classification() {
    for (text, category) in [
        ("password reset", "access"),
        ("invoice is wrong", "billing"),
        ("service timeout", "availability"),
        ("how do I", "general"),
    ] {
        let value = triage(&json!({"parts":[{"kind":"text","text":text}]})).unwrap();
        assert_eq!(value["category"], category);
        assert_eq!(value["automaticActionTaken"], false);
    }
    assert!(
        triage(&json!({"parts":[{"kind":"file","file":{"uri":"https://example.com"}}]})).is_err()
    );
    assert!(triage(&json!({"parts":[{"kind":"text","text":" "}]})).is_err());
}

#[tokio::test]
async fn real_http_contract_security_retry_and_restart() {
    let directory = tempfile::tempdir().unwrap();
    let key = Arc::new(vec![b'k'; 32]);
    let mut context = context();
    let mut request = request(&context);
    fresh(&mut context, &request);
    let (client, origin, server) = start(directory.path(), &context, key.clone()).await;
    let caps = client.capabilities().await.unwrap();
    assert!(caps.status_reconciliation);
    assert!(!caps.streaming && !caps.cancellation);
    assert_eq!(
        reqwest::get(format!("{origin}health/ready"))
            .await
            .unwrap()
            .status(),
        204
    );
    assert_eq!(
        reqwest::get(format!("{origin}v1/capabilities"))
            .await
            .unwrap()
            .status(),
        401
    );
    let result = client.call(&context, &request).await.unwrap();
    assert_eq!(result.state, BusinessState::Completed);
    assert_eq!(result.result.as_ref().unwrap()["priority"], "high");
    assert!(
        client.call(&context, &request).await.is_err(),
        "signed invocation replay must fail"
    );
    fresh(&mut context, &request);
    assert_eq!(
        serde_json::to_value(client.call(&context, &request).await.unwrap()).unwrap(),
        serde_json::to_value(&result).unwrap()
    );

    let mut wrong = context.clone();
    wrong.host_id = Uuid::now_v7();
    fresh(&mut wrong, &request);
    assert!(client.call(&wrong, &request).await.is_err());
    wrong = context.clone();
    wrong.expires_at = Utc::now() - chrono::Duration::seconds(1);
    fresh(&mut wrong, &request);
    assert!(client.call(&wrong, &request).await.is_err());
    wrong = context.clone();
    wrong.principal_subject = "user:bob".into();
    fresh(&mut wrong, &request);
    assert!(
        client.call(&wrong, &request).await.is_err(),
        "another owner cannot reuse a task"
    );

    let mut modified = request.clone();
    modified.message = json!({"parts":[{"kind":"text","text":"invoice"}]});
    fresh(&mut context, &modified);
    assert!(
        client.call(&context, &modified).await.is_err(),
        "idempotency conflict"
    );
    // Sign the original body, send a modified body; the adapter rejects tampering.
    fresh(&mut context, &request);
    let (encoded, signature) =
        sign_invocation(&context, &serde_json::to_vec(&request).unwrap(), &key).unwrap();
    let tampered = reqwest::Client::new()
        .post(format!("{origin}v1/invoke"))
        .header(CONTEXT_HEADER, encoded)
        .header(SIGNATURE_HEADER, signature)
        .header(CONTRACT_DIGEST_HEADER, contract_digest_value())
        .json(&modified)
        .send()
        .await
        .unwrap();
    assert_eq!(tampered.status(), 401);

    // Persisted replay protection and business results both survive a server restart.
    let replay = context.clone();
    client.call(&context, &request).await.unwrap();
    server.abort();
    let _ = server.await;
    let (client, _, server) = start(directory.path(), &context, key).await;
    assert!(client.call(&replay, &request).await.is_err());
    context.operation = BackendOperation::Status;
    context.backend_operation_id = result.backend_operation_id.clone();
    request.message = json!(null);
    request.idempotency_key = "status-1".into();
    context.idempotency_key = request.idempotency_key.clone();
    fresh(&mut context, &request);
    assert_eq!(
        client.call(&context, &request).await.unwrap().result,
        result.result
    );
    wrong = context.clone();
    wrong.principal_subject = "user:bob".into();
    fresh(&mut wrong, &request);
    assert!(client.call(&wrong, &request).await.is_err());
    context.budget.maximum_output_bytes = 1;
    fresh(&mut context, &request);
    assert!(client.call(&context, &request).await.is_err());
    context.budget.maximum_output_bytes = 16384;
    context.operation = BackendOperation::Cancel;
    fresh(&mut context, &request);
    assert!(client.call(&context, &request).await.is_err());
    context.operation = BackendOperation::InvokeStream;
    fresh(&mut context, &request);
    assert!(client.call_stream(&context, &request).await.is_err());
    server.abort();
    let _ = server.await;
}

#[test]
fn state_directory_is_exclusive_and_corruption_fails_closed() {
    let directory = tempfile::tempdir().unwrap();
    let backend = TriageBackend::open(directory.path()).unwrap();
    assert!(TriageBackend::open(directory.path()).is_err());
    drop(backend);
    std::fs::write(directory.path().join("tasks.json"), b"broken").unwrap();
    assert!(TriageBackend::open(directory.path()).is_err());
}
