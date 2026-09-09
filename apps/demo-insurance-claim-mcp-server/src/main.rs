use anyhow::{Context, Result};
use async_trait::async_trait;
use axum::{
    Json, Router,
    body::Bytes,
    extract::DefaultBodyLimit,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use light_axum::{AxumApp, AxumTransport, ServerContext};
use light_runtime::{
    LightRuntimeBuilder, RuntimeError, ShutdownWatcher, TracingOptions, init_tracing,
};
use mcp_client::wire;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tracing::info;

const CONFIG_DIR_ENV: &str = "INSURANCE_CLAIM_MCP_CONFIG_DIR";
const EXTERNAL_CONFIG_DIR_ENV: &str = "INSURANCE_CLAIM_MCP_EXTERNAL_CONFIG_DIR";
const LOG_ANSI_ENV: &str = "INSURANCE_CLAIM_MCP_LOG_ANSI";
const DEFAULT_CONFIG_DIR: &str = "apps/demo-insurance-claim-mcp-server/config";
const DEFAULT_EXTERNAL_CONFIG_DIR: &str = "apps/demo-insurance-claim-mcp-server/config-cache";
const MCP_SESSION_ID: HeaderName = HeaderName::from_static("mcp-session-id");
const MCP_PROTOCOL_VERSION: HeaderName = HeaderName::from_static("mcp-protocol-version");
const DEFAULT_PROTOCOL_VERSION: &str = "2026-07-28";

#[derive(Clone, Default)]
struct InsuranceClaimMcpApp;

#[async_trait]
impl AxumApp for InsuranceClaimMcpApp {
    async fn router(&self, _context: ServerContext) -> std::result::Result<Router, RuntimeError> {
        Ok(build_router())
    }
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

    fn tool_not_found(name: &str) -> Self {
        Self {
            code: -32602,
            message: format!("tool `{name}` not found"),
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let watcher = ShutdownWatcher::install().context("failed to install shutdown handlers")?;
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
        .with_log_stream(tracing_guard.log_stream())
        .build();

    info!("demo insurance claim MCP server started");
    runtime
        .run_until_shutdown(watcher)
        .await
        .context("demo insurance claim MCP server lifecycle failed")?;

    Ok(())
}

fn build_router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/mcp", post(handle_mcp))
        .layer(DefaultBodyLimit::max(1024 * 1024))
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "UP",
        service: "demo-insurance-claim-mcp-server",
    })
}

async fn handle_mcp(headers: HeaderMap, body: Bytes) -> Response {
    if headers.get_all("content-type").iter().count() != 1
        || headers
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .is_none_or(|v| v.split(';').next().unwrap_or("").trim() != "application/json")
    {
        return StatusCode::UNSUPPORTED_MEDIA_TYPE.into_response();
    }
    let value: Value = match serde_json::from_slice(&body) {
        Ok(value) => value,
        Err(_) => return modern_error(Value::Null, -32700, "invalid JSON", None),
    };
    let id = value.get("id").cloned().unwrap_or(Value::Null);
    if !(id.is_string() || id.is_i64() || id.is_u64()) {
        return modern_error(
            Value::Null,
            -32600,
            "request id must be a string or integer",
            None,
        );
    }
    let request: JsonRpcRequest = match serde_json::from_value(value) {
        Ok(request) => request,
        Err(_) => return modern_error(id, -32600, "invalid request", None),
    };
    if request.jsonrpc.as_deref() != Some("2.0") || !request.params.is_object() {
        return modern_error(id, -32600, "invalid JSON-RPC request", None);
    }
    if headers.contains_key("origin") {
        return StatusCode::FORBIDDEN.into_response();
    }
    if headers.contains_key(MCP_SESSION_ID) {
        return modern_error(
            id,
            -32600,
            "stateless requests cannot contain a session",
            None,
        );
    }
    let version = header_str(&headers, &MCP_PROTOCOL_VERSION).unwrap_or("");
    if headers.get_all(MCP_PROTOCOL_VERSION).iter().count() != 1
        || version.is_empty()
        || version.len() != 10
        || !version.bytes().enumerate().all(|(i, b)| {
            if i == 4 || i == 7 {
                b == b'-'
            } else {
                b.is_ascii_digit()
            }
        })
    {
        return modern_error(id, -32020, "invalid MCP-Protocol-Version header", None);
    }
    if version != DEFAULT_PROTOCOL_VERSION {
        return modern_error(
            id,
            -32022,
            "unsupported protocol version",
            Some(json!({"requested":version,"supported":[DEFAULT_PROTOCOL_VERSION]})),
        );
    }
    let accept = headers
        .get_all("accept")
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|v| v.split(','))
        .map(|v| v.trim().to_ascii_lowercase())
        .collect::<Vec<_>>();
    if !["application/json", "text/event-stream"]
        .iter()
        .all(|required| accept.iter().any(|v| v == required))
    {
        return StatusCode::NOT_ACCEPTABLE.into_response();
    }
    if headers.get_all("mcp-method").iter().count() != 1
        || headers.get("mcp-method").and_then(|v| v.to_str().ok()) != Some(request.method.as_str())
    {
        return modern_error(id, -32020, "Mcp-Method mismatch", None);
    }
    let meta = &request.params["_meta"];
    if meta[wire::VERSION_META] != DEFAULT_PROTOCOL_VERSION {
        return modern_error(
            id,
            if meta.get(wire::VERSION_META).is_none() {
                -32602
            } else {
                -32020
            },
            "protocol metadata mismatch",
            None,
        );
    }
    if !meta[wire::CAPABILITIES_META].is_object() {
        return modern_error(
            id,
            -32602,
            "clientCapabilities metadata must be an object",
            None,
        );
    }
    if let Some(info) = meta.get(wire::CLIENT_META) {
        if !["name", "version"].iter().all(|key| {
            info[*key]
                .as_str()
                .is_some_and(|s| !s.is_empty() && s.len() <= 1024)
        }) {
            return modern_error(id, -32600, "invalid clientInfo", None);
        }
    }
    if request.method != "tools/call" && headers.contains_key("mcp-name") {
        return modern_error(id, -32020, "unexpected Mcp-Name", None);
    }
    if headers.keys().any(|k| k.as_str().starts_with("mcp-param-")) {
        return modern_error(id, -32020, "no parameter headers are declared", None);
    }
    let result = match request.method.as_str() {
        "server/discover" => {
            json!({"supportedVersions":[DEFAULT_PROTOCOL_VERSION],"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"demo-insurance-claim-mcp-server","version":env!("CARGO_PKG_VERSION")}},"capabilities":{"tools":{}},"ttlMs":30000,"cacheScope":"public"})
        }
        "tools/list" => json!({"tools":tool_definitions(),"ttlMs":30000,"cacheScope":"public"}),
        "tools/call" => {
            let Some(name) = request.params["name"].as_str() else {
                return modern_error(id, -32602, "tool name required", None);
            };
            if headers.get_all("mcp-name").iter().count() != 1
                || headers
                    .get("mcp-name")
                    .and_then(|v| v.to_str().ok())
                    .and_then(|v| wire::decode_header(v).ok())
                    .as_deref()
                    != Some(name)
            {
                return modern_error(id, -32020, "Mcp-Name mismatch", None);
            }
            if !tool_definitions().iter().any(|t| t["name"] == name) {
                return modern_error(id, -32602, "unknown tool", None);
            }
            if request
                .params
                .get("arguments")
                .is_some_and(|v| !v.is_object())
            {
                return modern_error(id, -32602, "arguments must be an object", None);
            }
            let mut result = match execute_tool_call(&request.params) {
                Ok(value) => value,
                Err(error) => {
                    json!({"content":[{"type":"text","text":error.message}],"isError":true})
                }
            };
            result["resultType"] = json!("complete");
            result
        }
        _ => return modern_error(id, -32601, "method not supported", None),
    };
    json_rpc_result_response(Some(id), result, Some(DEFAULT_PROTOCOL_VERSION), None)
}

fn modern_error(id: Value, code: i32, message: &str, data: Option<Value>) -> Response {
    let mut error = json!({"code":code,"message":message});
    if let Some(data) = data {
        error["data"] = data;
    }
    (
        if code == -32601 {
            StatusCode::NOT_FOUND
        } else {
            StatusCode::BAD_REQUEST
        },
        Json(json!({"jsonrpc":"2.0","id":id,"error":error})),
    )
        .into_response()
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

    #[tokio::test]
    async fn malformed_capabilities_have_no_required_capabilities_data() {
        for capabilities in [
            None,
            Some(Value::Null),
            Some(json!([])),
            Some(json!("invalid")),
            Some(json!({})),
        ] {
            let valid = capabilities.as_ref().is_some_and(Value::is_object);
            let mut meta = json!({wire::VERSION_META:DEFAULT_PROTOCOL_VERSION});
            if let Some(capabilities) = capabilities {
                meta[wire::CAPABILITIES_META] = capabilities;
            }
            let request =
                json!({"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":meta}});
            let response = build_router()
                .oneshot(
                    Request::builder()
                        .method("POST")
                        .uri("/mcp")
                        .header("content-type", "application/json")
                        .header("accept", "application/json, text/event-stream")
                        .header("mcp-method", "server/discover")
                        .header(MCP_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION)
                        .body(Body::from(serde_json::to_vec(&request).unwrap()))
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(
                response.status(),
                if valid {
                    StatusCode::OK
                } else {
                    StatusCode::BAD_REQUEST
                }
            );
            let body = response_json(response).await;
            if valid {
                assert!(body.get("error").is_none());
            } else {
                assert_eq!(body["error"]["code"], -32602);
                assert!(body["error"].get("data").is_none());
            }
        }
    }

    #[tokio::test]
    async fn semantic_name_and_protocol_header_regressions() {
        for (name, versions, expected) in [
            ("classifyLiability", vec![DEFAULT_PROTOCOL_VERSION], None),
            (
                "=?base64?Y2xhc3NpZnlMaWFiaWxpdHk=?=",
                vec![DEFAULT_PROTOCOL_VERSION],
                None,
            ),
            (
                "=?base64?!!?=",
                vec![DEFAULT_PROTOCOL_VERSION],
                Some(-32020),
            ),
            ("wrong", vec![DEFAULT_PROTOCOL_VERSION], Some(-32020)),
            ("classifyLiability", vec![], Some(-32020)),
            (
                "classifyLiability",
                vec![DEFAULT_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION],
                Some(-32020),
            ),
            ("classifyLiability", vec!["invalid"], Some(-32020)),
            ("classifyLiability", vec!["2025-11-25"], Some(-32022)),
        ] {
            let mut headers = HeaderMap::new();
            headers.insert("content-type", HeaderValue::from_static("application/json"));
            headers.insert(
                "accept",
                HeaderValue::from_static("application/json, text/event-stream"),
            );
            headers.insert("mcp-method", HeaderValue::from_static("tools/call"));
            headers.insert("mcp-name", HeaderValue::from_str(name).unwrap());
            for version in versions {
                headers.append(
                    MCP_PROTOCOL_VERSION,
                    HeaderValue::from_str(version).unwrap(),
                );
            }
            let body = json!({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"classifyLiability","arguments":{"claim":{}},"_meta":{wire::VERSION_META:DEFAULT_PROTOCOL_VERSION,wire::CAPABILITIES_META:{}}}});
            let response =
                handle_mcp(headers, Bytes::from(serde_json::to_vec(&body).unwrap())).await;
            assert_eq!(
                response.status(),
                if expected.is_some() {
                    StatusCode::BAD_REQUEST
                } else {
                    StatusCode::OK
                }
            );
            let value = response_json(response).await;
            assert_eq!(value["error"]["code"].as_i64(), expected);
        }
    }

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

    async fn start_example() -> (String, tokio::task::JoinHandle<()>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}/mcp", listener.local_addr().unwrap());
        let task = tokio::spawn(async move {
            axum::serve(listener, build_router()).await.unwrap();
        });
        (url, task)
    }

    #[tokio::test]
    async fn real_client_calls_all_five_tools_across_two_replicas_and_gateway() {
        let (first, first_task) = start_example().await;
        let (second, second_task) = start_example().await;
        let mut gateway_tools = Vec::new();
        for (index, tool) in tool_definitions().into_iter().enumerate() {
            let target = if index % 2 == 0 { &first } else { &second };
            gateway_tools.push(json!({"name":tool["name"],"description":tool["description"],"inputSchema":tool["inputSchema"],
                "apiType":"mcp","targetHost":target.trim_end_matches("/mcp"),"path":"/mcp","method":"POST",
                "backendMcpProtocol":"stateless","backendCredentialMode":"anonymous","backendResource":target,
                "sessionIndependent":true,"toolMetadata":{"runtime":{"allowPrivateTargetHost":true}}}));
        }
        let config=serde_json::from_value(json!({"enabled":true,"protocols":{"stateless":{"enabled":true}},"tools":gateway_tools})).unwrap();
        let gateway = std::sync::Arc::new(light_pingora::McpRouterRuntime::new(config).unwrap());
        let gateway_app = Router::new().route(
            "/mcp",
            post(move |headers: HeaderMap, body: Bytes| {
                let gateway = gateway.clone();
                async move {
                    let request = light_pingora::McpHttpRequest {
                        method: "POST".into(),
                        path: "/mcp".into(),
                        headers: headers
                            .iter()
                            .map(|(k, v)| (k.to_string(), v.to_str().unwrap().into()))
                            .collect(),
                        body: body.to_vec(),
                    };
                    let response = gateway
                        .handle_request_with_context(
                            request,
                            light_pingora::McpRequestContext {
                                anonymous_binding: Some("peer:127.0.0.1".into()),
                                ..Default::default()
                            },
                        )
                        .await
                        .unwrap()
                        .unwrap();
                    let mut builder = axum::http::Response::builder()
                        .status(response.status)
                        .header("content-type", response.content_type);
                    for (name, value) in &response.headers {
                        builder = builder.header(name, value);
                    }
                    builder
                        .body(Body::from(response.body.buffered().unwrap().to_vec()))
                        .unwrap()
                }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let gateway_url = format!("http://{}/mcp", listener.local_addr().unwrap());
        let gateway_task = tokio::spawn(async move {
            axum::serve(listener, gateway_app).await.unwrap();
        });
        let arguments = json!({"claim":sample_claim(),"policies":sample_policies(),"vehicle":{"covered":true},
            "priorClaims":{"priorClaimCount":1,"recentClaimCount":0},"coverage":{"coverageStatus":"covered"},"liability":{},
            "triage":{},"coverageReview":{},"documents":{},"settlement":{}});
        for target in [&first, &second, &gateway_url] {
            let client = mcp_client::McpGatewayClient::new(target).unwrap();
            let tools = client.list_tools(None).await.unwrap();
            assert_eq!(tools.len(), 5);
            for tool in tools {
                let allowed = tool.input_schema["properties"].as_object().unwrap();
                let args = arguments
                    .as_object()
                    .unwrap()
                    .iter()
                    .filter(|(name, _)| allowed.contains_key(*name))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect::<serde_json::Map<_, _>>();
                let result = client
                    .call_tool(None, &tool.name, Value::Object(args))
                    .await
                    .unwrap();
                assert!(!result.is_error, "{} on {}", tool.name, target);
                assert_eq!(result.result_type.as_deref(), Some("complete"));
                assert!(result.structured_content.unwrap().is_object());
            }
        }
        // Fresh clients alternate ordinary requests without initialization or shared sessions.
        for target in [&first, &second, &first, &second] {
            let client = mcp_client::McpGatewayClient::new(target).unwrap();
            assert!(
                !client
                    .call_tool(None, "listRequiredDocuments", json!({}))
                    .await
                    .unwrap()
                    .is_error
            );
        }
        first_task.abort();
        second_task.abort();
        gateway_task.abort();
    }

    #[tokio::test]
    async fn stateless_rejects_missing_contract_and_never_creates_sessions() {
        let response = build_router()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/mcp")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert!(!response.headers().contains_key(MCP_SESSION_ID));
        assert_eq!(response_json(response).await["error"]["code"], -32020);
    }
}
