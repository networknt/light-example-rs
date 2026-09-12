//! Deterministic business logic behind the canonical Light A2A adapter.
use a2a_backend::{
    AgentBackend, BackendAuthorizedInvocation, BackendCapabilities, BusinessError,
    BusinessEventStream, BusinessRequest, BusinessResponse, BusinessState, CONTRACT_VERSION,
    request_digest,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
use tokio::sync::Mutex;
use uuid::Uuid;
mod llm;
pub use llm::{LlmConfig, LlmTriage};

pub const SKILL: &str = "support-triage";
const MAX_TASKS: usize = 1000;
const MAX_STATE_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Clone, Serialize, Deserialize)]
struct Task {
    host: Uuid,
    principal: String,
    context: Uuid,
    binding: Uuid,
    input_digest: String,
    response: BusinessResponse,
}

/// One process per state directory. Results survive restart; capacity is bounded.
/// For a production agent replace this store with transactional persistence.
pub struct TriageBackend {
    path: PathBuf,
    tasks: Mutex<BTreeMap<Uuid, Task>>,
    _lock: File,
    llm: Option<LlmTriage>,
}

fn error(code: &str, message: &str) -> BusinessError {
    BusinessError {
        code: code.into(),
        message: message.into(),
        retryable: false,
    }
}

impl TriageBackend {
    pub fn open(directory: &Path) -> anyhow::Result<Self> {
        anyhow::ensure!(directory.is_absolute(), "state directory must be absolute");
        fs::create_dir_all(directory)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(directory, fs::Permissions::from_mode(0o700))?;
        }
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(directory.join("process.lock"))?;
        lock.try_lock()?;
        let path = directory.join("tasks.json");
        let tasks: BTreeMap<Uuid, Task> = if path.exists() {
            anyhow::ensure!(
                fs::metadata(&path)?.len() <= MAX_STATE_BYTES,
                "state file is too large"
            );
            serde_json::from_slice(&fs::read(&path)?)?
        } else {
            BTreeMap::new()
        };
        anyhow::ensure!(tasks.len() <= MAX_TASKS, "too many persisted tasks");
        Ok(Self {
            path,
            tasks: Mutex::new(tasks),
            _lock: lock,
            llm: None,
        })
    }

    pub fn with_llm(mut self, llm: LlmTriage) -> Self {
        self.llm = Some(llm);
        self
    }

    fn save(&self, tasks: &BTreeMap<Uuid, Task>) -> anyhow::Result<()> {
        let bytes = serde_json::to_vec(tasks)?;
        anyhow::ensure!(
            bytes.len() as u64 <= MAX_STATE_BYTES,
            "task store capacity exceeded"
        );
        let temp = self.path.with_extension("tmp");
        let mut file = File::create(&temp)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        fs::rename(temp, &self.path)?;
        File::open(self.path.parent().expect("absolute state path"))?.sync_all()?;
        Ok(())
    }

    fn owns(task: &Task, context: &BackendAuthorizedInvocation) -> bool {
        task.host == context.host_id
            && task.principal == context.principal_subject
            && task.context == context.context_id
            && task.binding == context.binding_id
    }
}

/// Accept only text parts; no tools, model calls, URLs or caller credentials.
pub fn triage(message: &Value) -> Result<Value, BusinessError> {
    let parts = message
        .get("parts")
        .and_then(Value::as_array)
        .filter(|parts| !parts.is_empty() && parts.len() <= 16)
        .ok_or_else(|| error("INVALID_INPUT", "provide one to sixteen text parts"))?;
    let mut text = String::new();
    for part in parts {
        if part.get("kind").and_then(Value::as_str) != Some("text") {
            return Err(error(
                "UNSUPPORTED_CONTENT",
                "only text parts are supported",
            ));
        }
        let value = part
            .get("text")
            .and_then(Value::as_str)
            .ok_or_else(|| error("INVALID_INPUT", "each text part requires text"))?;
        text.push_str(value);
        text.push(' ');
    }
    if text.trim().is_empty() || text.len() > 8192 {
        return Err(error(
            "INVALID_INPUT",
            "description must contain 1 to 8192 bytes of text",
        ));
    }
    let text = text.to_lowercase();
    let (category, steps) = if ["password", "login", "sign in", "locked out"]
        .iter()
        .any(|word| text.contains(word))
    {
        (
            "access",
            vec![
                "Check the account status.",
                "Use the approved account recovery process.",
            ],
        )
    } else if ["invoice", "billing", "payment", "charged"]
        .iter()
        .any(|word| text.contains(word))
    {
        (
            "billing",
            vec![
                "Collect the invoice reference without payment credentials.",
                "Ask the billing team to review the charge.",
            ],
        )
    } else if ["outage", "unavailable", "error", "timeout"]
        .iter()
        .any(|word| text.contains(word))
    {
        (
            "availability",
            vec![
                "Check the service status and recent changes.",
                "Escalate to the service owner with a sanitized error report.",
            ],
        )
    } else {
        (
            "general",
            vec![
                "Collect reproduction steps and the affected service.",
                "Route to the support queue.",
            ],
        )
    };
    let priority = if ["outage", "all users", "production down"]
        .iter()
        .any(|word| text.contains(word))
    {
        "high"
    } else {
        "normal"
    };
    Ok(
        json!({"category": category, "priority": priority, "suggestedNextSteps": steps,
        "automaticActionTaken": false, "classifier": "deterministic-demo-v1"}),
    )
}

#[async_trait]
impl AgentBackend for TriageBackend {
    fn capabilities(&self) -> BackendCapabilities {
        BackendCapabilities {
            contract_version: CONTRACT_VERSION.into(),
            streaming: false,
            cancellation: false,
            status_reconciliation: true,
            accepted_content_modes: ["text/plain".into()].into(),
            maximum_artifact_bytes: 65536,
        }
    }

    async fn invoke(
        &self,
        context: BackendAuthorizedInvocation,
        request: BusinessRequest,
    ) -> Result<BusinessResponse, BusinessError> {
        if request
            .skill_id
            .as_deref()
            .is_some_and(|skill| skill != SKILL)
        {
            return Err(error("UNKNOWN_SKILL", "unsupported skill"));
        }
        let bytes =
            serde_json::to_vec(&request).map_err(|_| error("INVALID_INPUT", "invalid request"))?;
        if bytes.len() as u64 > context.budget.maximum_input_bytes {
            return Err(error("INPUT_LIMIT", "input exceeds invocation budget"));
        }
        let digest = request_digest(&bytes);
        let mut tasks = self.tasks.lock().await;
        if let Some(task) = tasks.get(&request.task_id) {
            if !Self::owns(task, &context) || task.input_digest != digest {
                return Err(error(
                    "TASK_CONFLICT",
                    "task identity already used by another request",
                ));
            }
            let size = serde_json::to_vec(&task.response)
                .expect("serializable response")
                .len();
            if size as u64 > context.budget.maximum_output_bytes {
                return Err(error("OUTPUT_LIMIT", "result exceeds invocation budget"));
            }
            return Ok(task.response.clone());
        }
        if tasks.len() >= MAX_TASKS {
            return Err(error("STORE_FULL", "demo task capacity reached"));
        }
        let mut result = triage(&request.message)?;
        if let Some(llm) = &self.llm {
            result = llm.classify(&request.message).await?;
        }
        let response = BusinessResponse {
            state: BusinessState::Completed,
            backend_operation_id: Some(request.task_id.to_string()),
            result: Some(result),
            error: None,
            artifacts: vec![],
        };
        if serde_json::to_vec(&response)
            .expect("serializable response")
            .len() as u64
            > context.budget.maximum_output_bytes
        {
            return Err(error("OUTPUT_LIMIT", "result exceeds invocation budget"));
        }
        let mut candidate = tasks.clone();
        candidate.insert(
            request.task_id,
            Task {
                host: context.host_id,
                principal: context.principal_subject,
                context: context.context_id,
                binding: context.binding_id,
                input_digest: digest,
                response: response.clone(),
            },
        );
        self.save(&candidate)
            .map_err(|_| error("STORE_UNAVAILABLE", "could not persist task result"))?;
        *tasks = candidate;
        Ok(response)
    }

    async fn status(
        &self,
        context: BackendAuthorizedInvocation,
        request: BusinessRequest,
    ) -> Result<BusinessResponse, BusinessError> {
        let tasks = self.tasks.lock().await;
        let task = tasks
            .get(&request.task_id)
            .filter(|task| Self::owns(task, &context))
            .filter(|_| {
                context.backend_operation_id.as_deref()
                    == Some(request.task_id.to_string().as_str())
            })
            .ok_or_else(|| error("TASK_NOT_FOUND", "task not found for this caller"))?;
        if serde_json::to_vec(&task.response)
            .expect("serializable response")
            .len() as u64
            > context.budget.maximum_output_bytes
        {
            return Err(error("OUTPUT_LIMIT", "result exceeds invocation budget"));
        }
        Ok(task.response.clone())
    }

    async fn cancel(
        &self,
        _: BackendAuthorizedInvocation,
        _: BusinessRequest,
    ) -> Result<BusinessResponse, BusinessError> {
        Err(error(
            "UNSUPPORTED_OPERATION",
            "synchronous triage does not support cancellation",
        ))
    }

    async fn invoke_stream(
        &self,
        _: BackendAuthorizedInvocation,
        _: BusinessRequest,
    ) -> Result<BusinessEventStream, BusinessError> {
        Err(error(
            "UNSUPPORTED_OPERATION",
            "synchronous triage does not support streaming",
        ))
    }
}
