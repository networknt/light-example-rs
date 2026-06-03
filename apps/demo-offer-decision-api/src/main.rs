use anyhow::{Context, Result};
use async_trait::async_trait;
use axum::{
    Json, Router,
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use light_axum::{AxumApp, AxumTransport, ServerContext};
use light_runtime::{LightRuntimeBuilder, RuntimeError, TracingOptions, init_tracing};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::HashMap,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
use tokio::sync::Mutex;
use tracing::info;

const CONFIG_DIR_ENV: &str = "OFFER_DECISION_CONFIG_DIR";
const EXTERNAL_CONFIG_DIR_ENV: &str = "OFFER_DECISION_EXTERNAL_CONFIG_DIR";
const LOG_ANSI_ENV: &str = "OFFER_DECISION_LOG_ANSI";
const DEFAULT_CONFIG_DIR: &str = "apps/demo-offer-decision-api/config";
const DEFAULT_EXTERNAL_CONFIG_DIR: &str = "apps/demo-offer-decision-api/config-cache";
const IDEMPOTENCY_KEY_HEADER: &str = "idempotency-key";

#[derive(Clone, Default)]
struct OfferDecisionApp;

#[async_trait]
impl AxumApp for OfferDecisionApp {
    async fn router(&self, _context: ServerContext) -> std::result::Result<Router, RuntimeError> {
        Ok(build_router())
    }
}

#[derive(Clone)]
struct AppState {
    offers: Arc<Vec<Offer>>,
    decisions: Arc<Mutex<HashMap<String, OfferDecisionResponse>>>,
    settlement_recommendations: Arc<Mutex<HashMap<String, SettlementRecommendationResponse>>>,
    next_decision_number: Arc<AtomicUsize>,
    next_settlement_number: Arc<AtomicUsize>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct Offer {
    offer_id: String,
    title: String,
    segment: String,
    state: String,
    category: String,
    priority: u8,
    active: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct OfferQuery {
    segment: Option<String>,
    state: Option<String>,
    category: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct OfferDecisionRequest {
    customer_id: String,
    offer_id: String,
    channel: String,
    source: String,
    reason: String,
    #[serde(default)]
    idempotency_key: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct OfferDecisionResponse {
    decision_id: String,
    customer_id: String,
    offer_id: String,
    decision: String,
    created_at: String,
    audit_ref: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ClaimTriageRequest {
    claim: Value,
    customer: Value,
    policies: Value,
    vehicle: Value,
    prior_claims: Value,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct ClaimTriageResponse {
    severity: String,
    risk_level: String,
    recommended_path: String,
    requires_adjuster_review: bool,
    requires_siu_review: bool,
    estimated_loss: u32,
    reason_codes: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct SettlementRecommendationRequest {
    claim: Value,
    coverage_review: Value,
    triage: Value,
    approval: Value,
    #[serde(default)]
    idempotency_key: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct SettlementRecommendationResponse {
    decision_id: String,
    recommended_path: String,
    settlement_amount: u32,
    deductible: u32,
    customer_summary: String,
    next_actions: Vec<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ErrorResponse {
    code: &'static str,
    message: String,
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    code: &'static str,
    message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            code: "INVALID_DECISION_REQUEST",
            message: message.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(ErrorResponse {
                code: self.code,
                message: self.message,
            }),
        )
            .into_response()
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let tracing_guard = init_tracing(
        TracingOptions::new("demo-offer-decision-api").with_legacy_ansi_env(LOG_ANSI_ENV),
    )
    .context("failed to initialize tracing")?;

    let config_dir =
        std::env::var(CONFIG_DIR_ENV).unwrap_or_else(|_| DEFAULT_CONFIG_DIR.to_string());
    let external_config_dir = std::env::var(EXTERNAL_CONFIG_DIR_ENV)
        .unwrap_or_else(|_| DEFAULT_EXTERNAL_CONFIG_DIR.to_string());

    let runtime = LightRuntimeBuilder::new(AxumTransport::new(OfferDecisionApp))
        .with_config_dir(config_dir)
        .with_external_config_dir(external_config_dir)
        .with_logging_control(tracing_guard.logging_control())
        .build();

    let running = runtime
        .start()
        .await
        .context("failed to start demo offer decision API")?;

    info!("demo offer decision API started");

    tokio::signal::ctrl_c()
        .await
        .context("failed to listen for shutdown signal")?;

    running
        .shutdown()
        .await
        .context("failed to shut down demo offer decision API")?;

    Ok(())
}

fn build_router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/offers", get(search_offers))
        .route("/offer-decisions", post(record_offer_decision))
        .route("/claim-triage", post(triage_claim))
        .route("/settlement-recommendations", post(recommend_settlement))
        .with_state(AppState::seeded())
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "UP",
        service: "demo-offer-decision-api",
    })
}

async fn search_offers(
    State(state): State<AppState>,
    Query(query): Query<OfferQuery>,
) -> Json<Vec<Offer>> {
    Json(state.search_offers(&query))
}

async fn record_offer_decision(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(request): Json<OfferDecisionRequest>,
) -> std::result::Result<Json<OfferDecisionResponse>, ApiError> {
    if !state.offer_exists(&request.offer_id) {
        return Err(ApiError::bad_request(format!(
            "offer {} is not active or does not exist",
            request.offer_id
        )));
    }

    let idempotency_key = request
        .idempotency_key
        .clone()
        .or_else(|| header_value(&headers, IDEMPOTENCY_KEY_HEADER))
        .unwrap_or_else(|| {
            format!(
                "{}:{}:{}",
                request.customer_id, request.offer_id, request.channel
            )
        });

    Ok(Json(state.record_decision(request, idempotency_key).await))
}

async fn triage_claim(
    Json(request): Json<ClaimTriageRequest>,
) -> std::result::Result<Json<ClaimTriageResponse>, ApiError> {
    if claim_string(&request.claim, "customerId").is_none()
        && claim_string(&request.customer, "customerId").is_none()
    {
        return Err(ApiError::bad_request(
            "claim.customerId or customer.customerId is required",
        ));
    }

    Ok(Json(ClaimTriageResponse::from_request(&request)))
}

async fn recommend_settlement(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(request): Json<SettlementRecommendationRequest>,
) -> std::result::Result<Json<SettlementRecommendationResponse>, ApiError> {
    if claim_string(&request.claim, "customerId").is_none() {
        return Err(ApiError::bad_request("claim.customerId is required"));
    }

    let idempotency_key = request
        .idempotency_key
        .clone()
        .or_else(|| header_value(&headers, IDEMPOTENCY_KEY_HEADER))
        .or_else(|| claim_string(&request.claim, "claimId"))
        .unwrap_or_else(|| {
            format!(
                "{}:{}",
                claim_string(&request.claim, "customerId").unwrap_or_else(|| "UNKNOWN".to_string()),
                string_or_default(&request.triage, "recommendedPath", "review")
            )
        });

    Ok(Json(
        state
            .record_settlement_recommendation(request, idempotency_key)
            .await,
    ))
}

impl AppState {
    fn seeded() -> Self {
        Self {
            offers: Arc::new(vec![
                Offer::new(
                    "OFFER-TRAVEL-01",
                    "Premium travel credit",
                    "premium",
                    "ON",
                    "travel",
                    1,
                    true,
                ),
                Offer::new(
                    "OFFER-CASHBACK-01",
                    "Premium shopping cashback",
                    "premium",
                    "BC",
                    "shopping",
                    2,
                    true,
                ),
                Offer::new(
                    "OFFER-EXPIRED-01",
                    "Expired welcome credit",
                    "premium",
                    "ON",
                    "travel",
                    9,
                    false,
                ),
            ]),
            decisions: Arc::new(Mutex::new(HashMap::new())),
            settlement_recommendations: Arc::new(Mutex::new(HashMap::new())),
            next_decision_number: Arc::new(AtomicUsize::new(2000)),
            next_settlement_number: Arc::new(AtomicUsize::new(3000)),
        }
    }

    fn search_offers(&self, query: &OfferQuery) -> Vec<Offer> {
        let mut matches: Vec<Offer> = self
            .offers
            .iter()
            .filter(|offer| offer.active)
            .filter(|offer| optional_match(query.segment.as_deref(), offer.segment.as_str()))
            .filter(|offer| optional_match(query.state.as_deref(), offer.state.as_str()))
            .filter(|offer| optional_match(query.category.as_deref(), offer.category.as_str()))
            .cloned()
            .collect();
        matches.sort_by_key(|offer| offer.priority);
        matches
    }

    fn offer_exists(&self, offer_id: &str) -> bool {
        self.offers
            .iter()
            .any(|offer| offer.active && offer.offer_id == offer_id)
    }

    async fn record_decision(
        &self,
        request: OfferDecisionRequest,
        idempotency_key: String,
    ) -> OfferDecisionResponse {
        let mut decisions = self.decisions.lock().await;
        if let Some(existing) = decisions.get(&idempotency_key) {
            return existing.clone();
        }

        let response = self.new_decision_response(&request);
        decisions.insert(idempotency_key, response.clone());
        response
    }

    async fn record_settlement_recommendation(
        &self,
        request: SettlementRecommendationRequest,
        idempotency_key: String,
    ) -> SettlementRecommendationResponse {
        let mut recommendations = self.settlement_recommendations.lock().await;
        if let Some(existing) = recommendations.get(&idempotency_key) {
            return existing.clone();
        }

        let response = self.new_settlement_recommendation(&request);
        recommendations.insert(idempotency_key, response.clone());
        response
    }

    fn new_decision_response(&self, request: &OfferDecisionRequest) -> OfferDecisionResponse {
        let decision_id =
            if request.customer_id == "CUST-1001" && request.offer_id == "OFFER-TRAVEL-01" {
                "DEC-1001".to_string()
            } else {
                let next = self.next_decision_number.fetch_add(1, Ordering::SeqCst);
                format!("DEC-{next}")
            };

        OfferDecisionResponse {
            decision_id,
            customer_id: request.customer_id.clone(),
            offer_id: request.offer_id.clone(),
            decision: "approved".to_string(),
            created_at: "2026-05-25T14:12:00Z".to_string(),
            audit_ref: format!(
                "AUD-{}",
                format!("{}{}", request.source, request.reason)
                    .chars()
                    .filter(|ch| ch.is_ascii_alphanumeric())
                    .take(8)
                    .collect::<String>()
                    .to_ascii_uppercase()
            ),
        }
    }

    fn new_settlement_recommendation(
        &self,
        request: &SettlementRecommendationRequest,
    ) -> SettlementRecommendationResponse {
        let customer_id = claim_string(&request.claim, "customerId").unwrap_or_default();
        let approval = string_or_default(&request.approval, "decision", "");
        let triage_path = string_or_default(&request.triage, "recommendedPath", "repair");
        let estimated_loss = u32_or_default(&request.triage, "estimatedLoss", 3200);
        let deductible = u32_or_default(&request.coverage_review, "deductible", 500);
        let rejected = approval.eq_ignore_ascii_case("REJECTED");

        let decision_id = if customer_id == "CUST-1001" {
            "DEC-1001".to_string()
        } else {
            let next = self.next_settlement_number.fetch_add(1, Ordering::SeqCst);
            format!("DEC-{next}")
        };

        if rejected {
            return SettlementRecommendationResponse {
                decision_id,
                recommended_path: "deny".to_string(),
                settlement_amount: 0,
                deductible,
                customer_summary:
                    "The claim requires denial or additional review before settlement.".to_string(),
                next_actions: vec!["notify_customer".to_string()],
            };
        }

        let settlement_amount = estimated_loss.saturating_sub(deductible);
        let recommended_path = if triage_path.is_empty() {
            "repair".to_string()
        } else {
            triage_path
        };

        SettlementRecommendationResponse {
            decision_id,
            recommended_path,
            settlement_amount,
            deductible,
            customer_summary: "Repair is recommended after the deductible.".to_string(),
            next_actions: vec!["schedule_repair".to_string(), "send_photos".to_string()],
        }
    }
}

impl ClaimTriageResponse {
    fn from_request(request: &ClaimTriageRequest) -> Self {
        let customer_id = claim_string(&request.claim, "customerId")
            .or_else(|| claim_string(&request.customer, "customerId"))
            .unwrap_or_default();
        let injury_reported = bool_or_default(&request.claim, "injuryReported", false);
        let vehicle_drivable = bool_or_default(&request.claim, "vehicleDrivable", true);
        let recent_claim_count = u32_or_default(&request.prior_claims, "recentClaimCount", 0);
        let policy_active = policies_include_active_policy(&request.policies);
        let vehicle_covered = bool_or_default(&request.vehicle, "covered", false);
        let consent = bool_or_default(&request.customer, "consent", true);

        let mut reason_codes = Vec::new();
        if !policy_active {
            reason_codes.push("POLICY_NOT_ACTIVE".to_string());
        }
        if !vehicle_covered {
            reason_codes.push("VEHICLE_NOT_COVERED".to_string());
        }
        if injury_reported {
            reason_codes.push("INJURY_REPORTED".to_string());
        }
        if !vehicle_drivable {
            reason_codes.push("VEHICLE_NOT_DRIVABLE".to_string());
        }
        if recent_claim_count > 1 {
            reason_codes.push("RECENT_PRIOR_CLAIMS".to_string());
        }
        if !consent || customer_id == "CUST-3003" {
            reason_codes.push("CUSTOMER_CONSENT_REQUIRED".to_string());
        }

        let requires_siu_review = recent_claim_count > 1 || customer_id == "CUST-2002";
        let requires_adjuster_review =
            injury_reported || !vehicle_drivable || !policy_active || !vehicle_covered || !consent;
        let risk_level = if requires_siu_review {
            "high"
        } else if requires_adjuster_review {
            "medium"
        } else {
            "low"
        };
        let severity = if injury_reported {
            "high"
        } else if !vehicle_drivable {
            "medium"
        } else {
            "low"
        };
        let recommended_path = if requires_siu_review {
            "siu_review"
        } else if !policy_active || !vehicle_covered {
            "manual_review"
        } else {
            "repair"
        };
        let estimated_loss = if !policy_active || !vehicle_covered {
            0
        } else if injury_reported {
            12000
        } else if !vehicle_drivable {
            3200
        } else {
            1800
        };

        Self {
            severity: severity.to_string(),
            risk_level: risk_level.to_string(),
            recommended_path: recommended_path.to_string(),
            requires_adjuster_review,
            requires_siu_review,
            estimated_loss,
            reason_codes,
        }
    }
}

impl Offer {
    fn new(
        offer_id: &str,
        title: &str,
        segment: &str,
        state: &str,
        category: &str,
        priority: u8,
        active: bool,
    ) -> Self {
        Self {
            offer_id: offer_id.to_string(),
            title: title.to_string(),
            segment: segment.to_string(),
            state: state.to_string(),
            category: category.to_string(),
            priority,
            active,
        }
    }
}

fn optional_match(expected: Option<&str>, actual: &str) -> bool {
    expected.is_none_or(|expected| expected.eq_ignore_ascii_case(actual))
}

fn header_value(headers: &HeaderMap, name: &str) -> Option<String> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn claim_string(value: &Value, field: &str) -> Option<String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn string_or_default(value: &Value, field: &str, default: &str) -> String {
    claim_string(value, field).unwrap_or_else(|| default.to_string())
}

fn bool_or_default(value: &Value, field: &str, default: bool) -> bool {
    value.get(field).and_then(Value::as_bool).unwrap_or(default)
}

fn u32_or_default(value: &Value, field: &str, default: u32) -> u32 {
    value
        .get(field)
        .and_then(Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
        .unwrap_or(default)
}

fn policies_include_active_policy(value: &Value) -> bool {
    let policies = value.get("policies").unwrap_or(value);
    policies.as_array().is_some_and(|policies| {
        policies.iter().any(|policy| {
            policy
                .get("status")
                .and_then(Value::as_str)
                .is_some_and(|status| status.eq_ignore_ascii_case("active"))
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::{Body, to_bytes},
        http::{Request, StatusCode, header},
    };
    use tower::ServiceExt;

    #[test]
    fn search_returns_active_matching_offer_only() {
        let state = AppState::seeded();
        let query = OfferQuery {
            segment: Some("premium".to_string()),
            state: Some("ON".to_string()),
            category: Some("travel".to_string()),
        };

        let offers = state.search_offers(&query);

        assert_eq!(offers.len(), 1);
        assert_eq!(offers[0].offer_id, "OFFER-TRAVEL-01");
    }

    #[tokio::test]
    async fn idempotency_key_returns_same_decision() {
        let state = AppState::seeded();
        let request = OfferDecisionRequest {
            customer_id: "CUST-2002".to_string(),
            offer_id: "OFFER-TRAVEL-01".to_string(),
            channel: "portal".to_string(),
            source: "workflow".to_string(),
            reason: "retry safety".to_string(),
            idempotency_key: None,
        };

        let first = state
            .record_decision(request, "wf-123:OFFER-TRAVEL-01".to_string())
            .await;
        let second = state
            .record_decision(
                OfferDecisionRequest {
                    customer_id: "CUST-2002".to_string(),
                    offer_id: "OFFER-TRAVEL-01".to_string(),
                    channel: "portal".to_string(),
                    source: "workflow".to_string(),
                    reason: "retry safety".to_string(),
                    idempotency_key: None,
                },
                "wf-123:OFFER-TRAVEL-01".to_string(),
            )
            .await;

        assert_eq!(first, second);
    }

    #[tokio::test]
    async fn offers_route_returns_matching_offer_array() {
        let response = build_router()
            .oneshot(
                Request::builder()
                    .uri("/offers?segment=premium&state=ON&category=travel")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let offers: Vec<Offer> = serde_json::from_slice(&body).expect("offers json");

        assert_eq!(offers.len(), 1);
        assert_eq!(offers[0].offer_id, "OFFER-TRAVEL-01");
    }

    #[tokio::test]
    async fn offer_decision_route_records_expected_demo_decision() {
        let body = serde_json::json!({
            "customerId": "CUST-1001",
            "offerId": "OFFER-TRAVEL-01",
            "channel": "portal",
            "source": "workflow",
            "reason": "demo"
        });

        let response = build_router()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/offer-decisions")
                    .header(header::CONTENT_TYPE, "application/json")
                    .header(IDEMPOTENCY_KEY_HEADER, "wf-demo-1001")
                    .body(Body::from(body.to_string()))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let decision: OfferDecisionResponse = serde_json::from_slice(&body).expect("decision json");

        assert_eq!(decision.decision_id, "DEC-1001");
        assert_eq!(decision.offer_id, "OFFER-TRAVEL-01");
    }

    #[tokio::test]
    async fn claim_triage_route_returns_deterministic_review_result() {
        let body = serde_json::json!({
            "claim": {
                "claimId": "CLM-1001",
                "customerId": "CUST-1001",
                "vehicleId": "VEH-1001",
                "injuryReported": false,
                "vehicleDrivable": false
            },
            "customer": {
                "customerId": "CUST-1001",
                "segment": "premium",
                "state": "ON"
            },
            "policies": {
                "policies": [
                    {
                        "policyId": "POL-AUTO-1001",
                        "status": "active"
                    }
                ]
            },
            "vehicle": {
                "vehicleId": "VEH-1001",
                "covered": true
            },
            "priorClaims": {
                "priorClaimCount": 1,
                "recentClaimCount": 0
            }
        });

        let response = build_router()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/claim-triage")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(body.to_string()))
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let triage: ClaimTriageResponse = serde_json::from_slice(&body).expect("triage json");

        assert_eq!(triage.risk_level, "medium");
        assert!(triage.requires_adjuster_review);
        assert!(!triage.requires_siu_review);
        assert_eq!(triage.estimated_loss, 3200);
        assert_eq!(triage.reason_codes, vec!["VEHICLE_NOT_DRIVABLE"]);
    }

    #[tokio::test]
    async fn settlement_route_returns_idempotent_recommendation() {
        let body = serde_json::json!({
            "claim": {
                "claimId": "CLM-1001",
                "customerId": "CUST-1001"
            },
            "coverageReview": {
                "deductible": 500
            },
            "triage": {
                "recommendedPath": "repair",
                "estimatedLoss": 3200
            },
            "approval": {
                "decision": "APPROVED"
            }
        });

        let request = || {
            Request::builder()
                .method("POST")
                .uri("/settlement-recommendations")
                .header(header::CONTENT_TYPE, "application/json")
                .header(IDEMPOTENCY_KEY_HEADER, "claim-demo-1001")
                .body(Body::from(body.to_string()))
                .expect("request")
        };

        let app = build_router();
        let first_response = app.clone().oneshot(request()).await.expect("response");
        let second_response = app.oneshot(request()).await.expect("response");

        assert_eq!(first_response.status(), StatusCode::OK);
        assert_eq!(second_response.status(), StatusCode::OK);

        let first_body = to_bytes(first_response.into_body(), usize::MAX)
            .await
            .expect("body");
        let second_body = to_bytes(second_response.into_body(), usize::MAX)
            .await
            .expect("body");
        let first: SettlementRecommendationResponse =
            serde_json::from_slice(&first_body).expect("first settlement json");
        let second: SettlementRecommendationResponse =
            serde_json::from_slice(&second_body).expect("second settlement json");

        assert_eq!(first, second);
        assert_eq!(first.decision_id, "DEC-1001");
        assert_eq!(first.settlement_amount, 2700);
        assert_eq!(first.next_actions, vec!["schedule_repair", "send_photos"]);
    }
}
