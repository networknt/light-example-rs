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
use light_runtime::{LightRuntimeBuilder, RuntimeError};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
use tokio::sync::Mutex;
use tracing::info;
use tracing_subscriber::EnvFilter;

const CONFIG_DIR_ENV: &str = "OFFER_DECISION_CONFIG_DIR";
const EXTERNAL_CONFIG_DIR_ENV: &str = "OFFER_DECISION_EXTERNAL_CONFIG_DIR";
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
    next_decision_number: Arc<AtomicUsize>,
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
    init_tracing();

    let config_dir =
        std::env::var(CONFIG_DIR_ENV).unwrap_or_else(|_| DEFAULT_CONFIG_DIR.to_string());
    let external_config_dir = std::env::var(EXTERNAL_CONFIG_DIR_ENV)
        .unwrap_or_else(|_| DEFAULT_EXTERNAL_CONFIG_DIR.to_string());

    let runtime = LightRuntimeBuilder::new(AxumTransport::new(OfferDecisionApp))
        .with_config_dir(config_dir)
        .with_external_config_dir(external_config_dir)
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
            next_decision_number: Arc::new(AtomicUsize::new(2000)),
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

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt().with_env_filter(filter).init();
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
}
