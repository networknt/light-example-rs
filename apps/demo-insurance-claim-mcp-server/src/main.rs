use anyhow::{Context, Result};
use async_trait::async_trait;
use axum::{
    Json, Router,
    extract::State,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use light_axum::{AxumApp, AxumTransport, ServerContext};
use light_runtime::{LightRuntimeBuilder, RuntimeError, TracingOptions, init_tracing};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    sync::{
        Arc, RwLock,
        atomic::{AtomicU64, Ordering},
    },
};
use tracing::info;

const CONFIG_DIR_ENV: &str = "INSURANCE_CLAIM_MCP_CONFIG_DIR";
const EXTERNAL_CONFIG_DIR_ENV: &str = "INSURANCE_CLAIM_MCP_EXTERNAL_CONFIG_DIR";
const LOG_ANSI_ENV: &str = "INSURANCE_CLAIM_MCP_LOG_ANSI";
const DEFAULT_CONFIG_DIR: &str = "apps/demo-insurance-claim-mcp-server/config";
const DEFAULT_EXTERNAL_CONFIG_DIR: &str = "apps/demo-insurance-claim-mcp-server/config-cache";
const MCP_SESSION_ID: HeaderName = HeaderName::from_static("mcp-session-id");
const MCP_PROTOCOL_VERSION: HeaderName = HeaderName::from_static("mcp-protocol-version");
const DEFAULT_PROTOCOL_VERSION: &str = "2025-06-18";

#[derive(Clone, Default)]
struct InsuranceClaimMcpApp;

#[async_trait]
impl AxumApp for InsuranceClaimMcpApp {
    async fn router(&self, _context: ServerContext) -> std::result::Result<Router, RuntimeError> {
        Ok(build_router())
    }
}

#[derive(Clone)]
struct AppState {
    sessions: Arc<RwLock<HashMap<String, McpSession>>>,
    next_session: Arc<AtomicU64>,
}

#[derive(Clone)]
struct McpSession {
    protocol_version: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
}

#[derive(Debug, Deserialize)]
struct JsonRpcRequest {
    jsonrpc: Option<String>,
    method: String,
    #[serde(default)]
    params: Value,
    #[serde(default)]
    id: Option<Value>,
}

#[derive(Debug, Serialize)]
struct JsonRpcResponse {
    jsonrpc: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<JsonRpcError>,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<Value>,
}

#[derive(Debug, Serialize)]
struct JsonRpcError {
    code: i32,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    data: Option<Value>,
}

#[derive(Debug)]
struct McpError {
    code: i32,
    message: String,
}

impl McpError {
    fn invalid_params(message: impl Into<String>) -> Self {
        Self {
            code: -32602,
            message: message.into(),
        }
    }

    fn method_not_found(method: &str) -> Self {
        Self {
            code: -32601,
            message: format!("method `{method}` not found"),
        }
    }

    fn tool_not_found(name: &str) -> Self {
        Self {
            code: -32602,
            message: format!("tool `{name}` not found"),
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let tracing_guard = init_tracing(
        TracingOptions::new("demo-insurance-claim-mcp-server").with_legacy_ansi_env(LOG_ANSI_ENV),
    )
    .context("failed to initialize tracing")?;

    let config_dir =
        std::env::var(CONFIG_DIR_ENV).unwrap_or_else(|_| DEFAULT_CONFIG_DIR.to_string());
    let external_config_dir = std::env::var(EXTERNAL_CONFIG_DIR_ENV)
        .unwrap_or_else(|_| DEFAULT_EXTERNAL_CONFIG_DIR.to_string());

    let runtime = LightRuntimeBuilder::new(AxumTransport::new(InsuranceClaimMcpApp))
        .with_config_dir(config_dir)
        .with_external_config_dir(external_config_dir)
        .with_logging_control(tracing_guard.logging_control())
        .build();

    let running = runtime
        .start()
        .await
        .context("failed to start demo insurance claim MCP server")?;

    info!("demo insurance claim MCP server started");

    tokio::signal::ctrl_c()
        .await
        .context("failed to listen for shutdown signal")?;

    running
        .shutdown()
        .await
        .context("failed to shut down demo insurance claim MCP server")?;

    Ok(())
}

fn build_router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/mcp", post(handle_mcp).delete(delete_mcp_session))
        .with_state(AppState {
            sessions: Arc::new(RwLock::new(HashMap::new())),
            next_session: Arc::new(AtomicU64::new(1)),
        })
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "UP",
        service: "demo-insurance-claim-mcp-server",
    })
}

async fn handle_mcp(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(request): Json<JsonRpcRequest>,
) -> Response {
    if request.jsonrpc.as_deref() != Some("2.0") {
        return json_rpc_error_response(request.id, -32600, "invalid JSON-RPC version");
    }

    if request.method == "initialize" {
        return initialize_session(state, request).await;
    }

    let session = match require_session(&state, &headers) {
        Ok(session) => session,
        Err(error) => {
            return json_rpc_error_response(request.id, error.code, error.message);
        }
    };

    if request.id.is_none() && request.method == "notifications/initialized" {
        return accepted_response(Some(session.protocol_version.as_str()));
    }

    let id = request.id.clone();
    let result = match request.method.as_str() {
        "tools/list" => Ok(json!({ "tools": tool_definitions() })),
        "tools/call" => execute_tool_call(&request.params),
        method => Err(McpError::method_not_found(method)),
    };

    match result {
        Ok(result) => json_rpc_result_response(
            id,
            result,
            Some(session.protocol_version.as_str()),
            None::<&str>,
        ),
        Err(error) => json_rpc_error_response(id, error.code, error.message),
    }
}

async fn delete_mcp_session(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let Some(session_id) = header_str(&headers, &MCP_SESSION_ID) else {
        return json_rpc_error_response(None, -32602, "missing Mcp-Session-Id");
    };
    let removed = state
        .sessions
        .write()
        .expect("session store lock poisoned")
        .remove(session_id);
    accepted_response(
        removed
            .as_ref()
            .map(|session| session.protocol_version.as_str()),
    )
}

async fn initialize_session(state: AppState, request: JsonRpcRequest) -> Response {
    let requested_protocol = request
        .params
        .get("protocolVersion")
        .and_then(Value::as_str)
        .unwrap_or(DEFAULT_PROTOCOL_VERSION);
    let protocol_version = if requested_protocol.trim().is_empty() {
        DEFAULT_PROTOCOL_VERSION
    } else {
        requested_protocol
    };
    let session_number = state.next_session.fetch_add(1, Ordering::Relaxed);
    let session_id = format!("demo-insurance-claim-mcp-{session_number}");
    state
        .sessions
        .write()
        .expect("session store lock poisoned")
        .insert(
            session_id.clone(),
            McpSession {
                protocol_version: protocol_version.to_string(),
            },
        );

    json_rpc_result_response(
        request.id,
        json!({
            "protocolVersion": protocol_version,
            "capabilities": {
                "tools": {
                    "listChanged": false
                }
            },
            "serverInfo": {
                "name": "demo-insurance-claim-mcp-server",
                "version": env!("CARGO_PKG_VERSION")
            }
        }),
        Some(protocol_version),
        Some(session_id.as_str()),
    )
}

fn require_session(
    state: &AppState,
    headers: &HeaderMap,
) -> std::result::Result<McpSession, McpError> {
    let session_id = header_str(headers, &MCP_SESSION_ID)
        .ok_or_else(|| McpError::invalid_params("missing Mcp-Session-Id"))?;
    state
        .sessions
        .read()
        .expect("session store lock poisoned")
        .get(session_id)
        .cloned()
        .ok_or_else(|| McpError::invalid_params("unknown Mcp-Session-Id"))
}

fn execute_tool_call(params: &Value) -> std::result::Result<Value, McpError> {
    let name = params
        .get("name")
        .and_then(Value::as_str)
        .ok_or_else(|| McpError::invalid_params("tools/call requires params.name"))?;
    let arguments = params
        .get("arguments")
        .filter(|value| value.is_object())
        .unwrap_or(&Value::Null);
    let structured = match name {
        "evaluateCoverage" => evaluate_coverage(arguments),
        "classifyLiability" => classify_liability(arguments),
        "scoreClaimRisk" => score_claim_risk(arguments),
        "listRequiredDocuments" => list_required_documents(arguments),
        "generateCustomerSummary" => generate_customer_summary(arguments),
        _ => Err(McpError::tool_not_found(name)),
    }?;
    Ok(tool_result(structured))
}

fn evaluate_coverage(arguments: &Value) -> std::result::Result<Value, McpError> {
    let claim = required_arg(arguments, "claim")?;
    let policies = required_arg(arguments, "policies")?;
    let vehicle = required_arg(arguments, "vehicle")?;
    let incident_date = required_string_field(claim, "incidentDate")?;
    let vehicle_id = required_string_field(claim, "vehicleId")?;

    let active_policy = policy_items(policies)
        .into_iter()
        .find(|policy| string_field(policy, "status").eq_ignore_ascii_case("active"));
    let vehicle_covered = bool_field(vehicle, "covered", false);

    let (coverage_status, policy_id, deductible, coverage_type, reason) = if !vehicle_covered {
        (
            "not-covered",
            String::new(),
            0,
            String::new(),
            format!("vehicle {vehicle_id} is not covered by an active policy"),
        )
    } else if let Some(policy) = active_policy {
        (
            "covered",
            string_field(policy, "policyId"),
            first_deductible(policy).unwrap_or(500),
            first_coverage_type(policy).unwrap_or_else(|| "collision".to_string()),
            format!("active policy covers incident date {incident_date}"),
        )
    } else {
        (
            "policy-inactive",
            String::new(),
            0,
            String::new(),
            "no active policy was found for the claim".to_string(),
        )
    };

    Ok(json!({
        "coverageStatus": coverage_status,
        "policyId": policy_id,
        "coverageType": coverage_type,
        "deductible": deductible,
        "requiresAdjusterReview": coverage_status != "covered",
        "reason": reason
    }))
}

fn classify_liability(arguments: &Value) -> std::result::Result<Value, McpError> {
    let claim = required_arg(arguments, "claim")?;
    let description = required_string_field(claim, "accidentDescription")?.to_lowercase();
    let vehicle_drivable = required_bool_field(claim, "vehicleDrivable")?;
    let injury_reported = required_bool_field(claim, "injuryReported")?;

    let (liability_status, requires_adjuster_review, reason) = if injury_reported {
        (
            "unclear",
            true,
            "injury was reported, so liability requires adjuster review",
        )
    } else if description.contains("rear-ended") || description.contains("rear ended") {
        (
            "likely-not-at-fault",
            !vehicle_drivable,
            "rear-end collision suggests the claimant is likely not at fault",
        )
    } else if description.contains("single vehicle") {
        (
            "unclear",
            true,
            "single vehicle incident requires liability review",
        )
    } else {
        (
            "clear",
            false,
            "claim facts are sufficient for standard liability handling",
        )
    };

    Ok(json!({
        "liabilityStatus": liability_status,
        "requiresAdjusterReview": requires_adjuster_review,
        "reason": reason
    }))
}

fn score_claim_risk(arguments: &Value) -> std::result::Result<Value, McpError> {
    let claim = required_arg(arguments, "claim")?;
    let prior_claims = required_arg(arguments, "priorClaims")?;
    let coverage = arguments.get("coverage").unwrap_or(&Value::Null);
    let liability = arguments.get("liability").unwrap_or(&Value::Null);

    let injury_reported = required_bool_field(claim, "injuryReported")?;
    let vehicle_drivable = required_bool_field(claim, "vehicleDrivable")?;
    let prior_claim_count = required_u64_field(prior_claims, "priorClaimCount")?;
    let recent_claim_count = required_u64_field(prior_claims, "recentClaimCount")?;
    let coverage_status = string_field(coverage, "coverageStatus");
    let liability_status = string_field(liability, "liabilityStatus");

    let mut reason_codes = Vec::new();
    if injury_reported {
        reason_codes.push("INJURY_REPORTED");
    }
    if !vehicle_drivable {
        reason_codes.push("VEHICLE_NOT_DRIVABLE");
    }
    if recent_claim_count > 0 {
        reason_codes.push("RECENT_PRIOR_CLAIM");
    }
    if coverage_status != "covered" {
        reason_codes.push("COVERAGE_REVIEW_REQUIRED");
    }
    if liability_status == "unclear" {
        reason_codes.push("UNCLEAR_LIABILITY");
    }

    let risk_level = if injury_reported || recent_claim_count >= 2 || coverage_status != "covered" {
        "high"
    } else if !vehicle_drivable || recent_claim_count == 1 || liability_status == "unclear" {
        "medium"
    } else {
        "low"
    };
    let estimated_loss = if injury_reported {
        12_500
    } else if !vehicle_drivable {
        3_200
    } else {
        900
    };

    Ok(json!({
        "riskLevel": risk_level,
        "estimatedLoss": estimated_loss,
        "requiresSiuReview": risk_level == "high" || prior_claim_count >= 3,
        "requiresAdjusterReview": risk_level != "low",
        "reasonCodes": reason_codes,
        "reason": format!("risk scored {risk_level} from deterministic demo claim rules")
    }))
}

fn list_required_documents(arguments: &Value) -> std::result::Result<Value, McpError> {
    let claim = arguments.get("claim").unwrap_or(&Value::Null);
    let recommended_path = arguments
        .get("recommendedPath")
        .and_then(Value::as_str)
        .or_else(|| {
            arguments
                .get("triage")
                .and_then(|triage| triage.get("recommendedPath"))
                .and_then(Value::as_str)
        })
        .unwrap_or("repair");

    let mut documents = match recommended_path {
        "total-loss-review" => vec!["damage_photos", "tow_report", "vehicle_valuation"],
        "denial-draft" => vec!["denial_reason", "policy_review_notes"],
        "more-information" => vec!["claimant_statement", "damage_photos"],
        _ => vec!["repair_estimate", "damage_photos"],
    };
    if bool_field(claim, "policeReportFiled", false) {
        documents.push("police_report");
    }

    Ok(json!({
        "recommendedPath": recommended_path,
        "documents": documents,
        "reason": "documents selected from deterministic demo claim rules"
    }))
}

fn generate_customer_summary(arguments: &Value) -> std::result::Result<Value, McpError> {
    let claim = required_arg(arguments, "claim")?;
    let coverage = arguments.get("coverageReview").unwrap_or(&Value::Null);
    let triage = arguments.get("triage").unwrap_or(&Value::Null);
    let documents = arguments.get("documents").unwrap_or(&Value::Null);
    let settlement = arguments.get("settlement").unwrap_or(&Value::Null);

    let customer_id = required_string_field(claim, "customerId")?;
    let recommended_path = string_field_with_fallback(
        settlement,
        "recommendedPath",
        string_field(triage, "recommendedPath").as_str(),
    );
    let deductible = u64_field(coverage, "deductible", 0);
    let estimated_loss = u64_field(triage, "estimatedLoss", 0);
    let document_list = documents
        .get("documents")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        })
        .unwrap_or_else(|| "repair_estimate, damage_photos".to_string());

    Ok(json!({
        "customerId": customer_id,
        "recommendedPath": recommended_path,
        "customerSummary": format!(
            "Your claim is recommended for {recommended_path}. The estimated loss is ${estimated_loss}, and the applicable deductible is ${deductible}."
        ),
        "nextActions": [
            format!("Provide required documents: {document_list}"),
            "A claims representative will review the submitted materials."
        ]
    }))
}

fn tool_result(structured: Value) -> Value {
    let text = serde_json::to_string(&structured).unwrap_or_else(|_| "{}".to_string());
    json!({
        "content": [
            {
                "type": "text",
                "text": text
            }
        ],
        "structuredContent": structured,
        "isError": false
    })
}

fn tool_definitions() -> Vec<Value> {
    vec![
        tool(
            "evaluateCoverage",
            "Evaluate policy and vehicle coverage for an insurance claim.",
            json!({
                "type": "object",
                "required": ["claim", "policies", "vehicle"],
                "properties": {
                    "claim": { "type": "object" },
                    "policies": { "type": "object" },
                    "vehicle": { "type": "object" }
                }
            }),
        ),
        tool(
            "classifyLiability",
            "Classify liability from first-notice-of-loss claim facts.",
            json!({
                "type": "object",
                "required": ["claim"],
                "properties": {
                    "claim": { "type": "object" }
                }
            }),
        ),
        tool(
            "scoreClaimRisk",
            "Score claim risk and determine adjuster or SIU review needs.",
            json!({
                "type": "object",
                "required": ["claim", "priorClaims"],
                "properties": {
                    "claim": { "type": "object" },
                    "priorClaims": { "type": "object" },
                    "coverage": { "type": "object" },
                    "liability": { "type": "object" }
                }
            }),
        ),
        tool(
            "listRequiredDocuments",
            "List documents needed for the recommended claim path.",
            json!({
                "type": "object",
                "properties": {
                    "claim": { "type": "object" },
                    "recommendedPath": { "type": "string" },
                    "triage": { "type": "object" }
                }
            }),
        ),
        tool(
            "generateCustomerSummary",
            "Generate a deterministic customer-facing claim summary.",
            json!({
                "type": "object",
                "required": ["claim"],
                "properties": {
                    "claim": { "type": "object" },
                    "coverageReview": { "type": "object" },
                    "triage": { "type": "object" },
                    "documents": { "type": "object" },
                    "settlement": { "type": "object" }
                }
            }),
        ),
    ]
}

fn tool(name: &str, description: &str, input_schema: Value) -> Value {
    json!({
        "name": name,
        "description": description,
        "inputSchema": input_schema
    })
}

fn required_arg<'a>(arguments: &'a Value, name: &str) -> std::result::Result<&'a Value, McpError> {
    arguments
        .get(name)
        .ok_or_else(|| McpError::invalid_params(format!("missing required argument `{name}`")))
}

fn required_string_field(value: &Value, name: &str) -> std::result::Result<String, McpError> {
    value
        .get(name)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(str::to_string)
        .ok_or_else(|| McpError::invalid_params(format!("missing required field `{name}`")))
}

fn required_bool_field(value: &Value, name: &str) -> std::result::Result<bool, McpError> {
    value
        .get(name)
        .and_then(Value::as_bool)
        .ok_or_else(|| McpError::invalid_params(format!("missing required field `{name}`")))
}

fn required_u64_field(value: &Value, name: &str) -> std::result::Result<u64, McpError> {
    value
        .get(name)
        .and_then(Value::as_u64)
        .ok_or_else(|| McpError::invalid_params(format!("missing required field `{name}`")))
}

fn policy_items(value: &Value) -> Vec<&Value> {
    if let Some(items) = value.as_array() {
        return items.iter().collect();
    }
    value
        .get("policies")
        .and_then(Value::as_array)
        .map(|items| items.iter().collect())
        .unwrap_or_default()
}

fn first_deductible(policy: &Value) -> Option<u64> {
    policy
        .get("coverages")
        .and_then(Value::as_array)
        .and_then(|coverages| coverages.first())
        .and_then(|coverage| coverage.get("deductible"))
        .and_then(Value::as_u64)
}

fn first_coverage_type(policy: &Value) -> Option<String> {
    policy
        .get("coverages")
        .and_then(Value::as_array)
        .and_then(|coverages| coverages.first())
        .and_then(|coverage| coverage.get("coverageType"))
        .and_then(Value::as_str)
        .map(str::to_string)
}

fn string_field(value: &Value, name: &str) -> String {
    value
        .get(name)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

fn string_field_with_fallback(value: &Value, name: &str, fallback: &str) -> String {
    value
        .get(name)
        .and_then(Value::as_str)
        .unwrap_or(fallback)
        .to_string()
}

fn bool_field(value: &Value, name: &str, default: bool) -> bool {
    value.get(name).and_then(Value::as_bool).unwrap_or(default)
}

fn u64_field(value: &Value, name: &str, default: u64) -> u64 {
    value.get(name).and_then(Value::as_u64).unwrap_or(default)
}

fn header_str<'a>(headers: &'a HeaderMap, name: &HeaderName) -> Option<&'a str> {
    headers.get(name).and_then(|value| value.to_str().ok())
}

fn json_rpc_result_response(
    id: Option<Value>,
    result: Value,
    protocol_version: Option<&str>,
    session_id: Option<&str>,
) -> Response {
    let mut response = Json(JsonRpcResponse {
        jsonrpc: "2.0",
        result: Some(result),
        error: None,
        id,
    })
    .into_response();
    if let Some(protocol_version) = protocol_version {
        insert_header(&mut response, &MCP_PROTOCOL_VERSION, protocol_version);
    }
    if let Some(session_id) = session_id {
        insert_header(&mut response, &MCP_SESSION_ID, session_id);
    }
    response
}

fn json_rpc_error_response(id: Option<Value>, code: i32, message: impl Into<String>) -> Response {
    Json(JsonRpcResponse {
        jsonrpc: "2.0",
        result: None,
        error: Some(JsonRpcError {
            code,
            message: message.into(),
            data: None,
        }),
        id,
    })
    .into_response()
}

fn accepted_response(protocol_version: Option<&str>) -> Response {
    let mut response = StatusCode::ACCEPTED.into_response();
    if let Some(protocol_version) = protocol_version {
        insert_header(&mut response, &MCP_PROTOCOL_VERSION, protocol_version);
    }
    response
}

fn insert_header(response: &mut Response, name: &HeaderName, value: &str) {
    if let Ok(value) = HeaderValue::from_str(value) {
        response.headers_mut().insert(name, value);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::{Body, to_bytes};
    use axum::http::Request;
    use tower::ServiceExt;

    fn sample_claim() -> Value {
        json!({
            "claimId": "CLM-CUST-1001",
            "customerId": "CUST-1001",
            "vehicleId": "VEH-1001",
            "incidentDate": "2026-05-30",
            "accidentDescription": "Rear-ended at an intersection. No injuries reported.",
            "injuryReported": false,
            "vehicleDrivable": false,
            "policeReportFiled": true
        })
    }

    fn sample_policies() -> Value {
        json!({
            "policies": [
                {
                    "policyId": "POL-AUTO-1001",
                    "status": "active",
                    "coverages": [
                        {
                            "coverageType": "collision",
                            "deductible": 500,
                            "limit": 50000
                        }
                    ]
                }
            ]
        })
    }

    async fn response_json(response: Response) -> Value {
        let body = to_bytes(response.into_body(), 1024 * 1024)
            .await
            .expect("response body");
        serde_json::from_slice(&body).expect("json response")
    }

    #[test]
    fn coverage_tool_returns_covered_for_active_policy_and_vehicle() {
        let result = evaluate_coverage(&json!({
            "claim": sample_claim(),
            "policies": sample_policies(),
            "vehicle": {
                "vehicleId": "VEH-1001",
                "covered": true
            }
        }))
        .expect("coverage result");

        assert_eq!(result["coverageStatus"], "covered");
        assert_eq!(result["deductible"], 500);
        assert_eq!(result["requiresAdjusterReview"], false);
    }

    #[test]
    fn risk_tool_flags_medium_review_for_not_drivable_vehicle() {
        let result = score_claim_risk(&json!({
            "claim": sample_claim(),
            "priorClaims": {
                "priorClaimCount": 1,
                "recentClaimCount": 0
            },
            "coverage": {
                "coverageStatus": "covered"
            },
            "liability": {
                "liabilityStatus": "likely-not-at-fault"
            }
        }))
        .expect("risk result");

        assert_eq!(result["riskLevel"], "medium");
        assert_eq!(result["requiresAdjusterReview"], true);
        assert_eq!(result["estimatedLoss"], 3200);
    }

    #[test]
    fn coverage_tool_rejects_missing_required_claim_fields() {
        let error = evaluate_coverage(&json!({
            "claim": {
                "customerId": "CUST-1001"
            },
            "policies": sample_policies(),
            "vehicle": {
                "vehicleId": "VEH-1001",
                "covered": true
            }
        }))
        .expect_err("missing incident date should fail");

        assert_eq!(error.code, -32602);
        assert_eq!(error.message, "missing required field `incidentDate`");
    }

    #[tokio::test]
    async fn mcp_requires_session_after_initialize() {
        let app = build_router();
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/mcp")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let json = response_json(response).await;
        assert_eq!(json["error"]["code"], -32602);
        assert_eq!(json["error"]["message"], "missing Mcp-Session-Id");
    }

    #[tokio::test]
    async fn initialize_returns_session_header() {
        let app = build_router();
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/mcp")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        assert!(response.headers().contains_key(MCP_SESSION_ID));
    }

    #[tokio::test]
    async fn tools_list_accepts_initialized_session() {
        let app = build_router();
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/mcp")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        let session_id = response
            .headers()
            .get(MCP_SESSION_ID)
            .expect("session header")
            .to_str()
            .expect("session header string")
            .to_string();

        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/mcp")
                    .header("content-type", "application/json")
                    .header("mcp-session-id", session_id)
                    .body(Body::from(
                        r#"{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}"#,
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
    }
}
