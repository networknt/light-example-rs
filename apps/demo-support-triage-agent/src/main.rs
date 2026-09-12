use a2a_backend::{
    AdapterConfig, BackendExpectation, BackendOperation, FileReplayStore, adapter_router,
};
use demo_support_triage_agent::{LlmConfig, LlmTriage, TriageBackend};
use serde::Deserialize;
use std::{path::PathBuf, sync::Arc};
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Config {
    audience: String,
    host_id: Uuid,
    environment: String,
    agent_ref: String,
    binding_id: Uuid,
    publication_id: Uuid,
    policy_digest: String,
    data_boundary_digest: String,
    context_key_file: PathBuf,
    state_directory: PathBuf,
    #[serde(default)]
    llm: Option<LlmConfig>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    if std::env::args().any(|arg| arg == "--contract-digest") {
        println!("{}", a2a_backend::contract_digest_value());
        return Ok(());
    }
    let path = std::env::var("TRIAGE_CONFIG").unwrap_or_else(|_| "/app/config/backend.json".into());
    let config: Config = serde_json::from_slice(&std::fs::read(path)?)?;
    anyhow::ensure!(
        config.context_key_file.is_absolute(),
        "contextKeyFile must be absolute"
    );
    let key = std::fs::read(config.context_key_file)?;
    anyhow::ensure!(key.len() >= 32, "context key must have at least 32 bytes");
    for value in [&config.audience, &config.environment, &config.agent_ref] {
        anyhow::ensure!(!value.trim().is_empty(), "backend identity cannot be empty");
    }
    for value in [&config.policy_digest, &config.data_boundary_digest] {
        anyhow::ensure!(
            value.len() == 71
                && value.starts_with("sha256:")
                && value[7..]
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()),
            "invalid publication digest"
        );
    }
    let mut backend = TriageBackend::open(&config.state_directory)?;
    if let Some(llm) = config.llm {
        backend = backend.with_llm(LlmTriage::new(llm)?);
    }
    let replay_store = Arc::new(FileReplayStore::new(
        config.state_directory.join("replay.json"),
        10000,
    )?);
    let router = adapter_router(
        backend,
        AdapterConfig {
            expectation: BackendExpectation {
                audience: config.audience,
                host_id: config.host_id,
                environment: config.environment,
                target_agent_ref: config.agent_ref,
                binding_id: config.binding_id,
                publication_id: config.publication_id,
                policy_digest: config.policy_digest,
                data_boundary_digest: config.data_boundary_digest,
                operation: BackendOperation::Invoke,
                skill_id: None,
            },
            key: Arc::new(key),
            maximum_request_bytes: 16384,
            replay_store,
        },
    );
    // This is a private sidecar interface, never a public listener.
    let listener = tokio::net::TcpListener::bind("127.0.0.1:9010").await?;
    println!("Support triage backend listening on loopback port 9010");
    axum::serve(listener, router)
        .with_graceful_shutdown(async {
            let mut term =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                    .expect("SIGTERM handler");
            tokio::select! { _ = tokio::signal::ctrl_c() => {}, _ = term.recv() => {} }
        })
        .await?;
    Ok(())
}
