use anyhow::{Context, Result};
use async_trait::async_trait;
use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
};
use light_axum::{AxumApp, AxumTransport, ServerContext};
use light_runtime::{LightRuntimeBuilder, RuntimeError};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tracing::info;
use tracing_subscriber::EnvFilter;

const CONFIG_DIR_ENV: &str = "CUSTOMER_PROFILE_CONFIG_DIR";
const EXTERNAL_CONFIG_DIR_ENV: &str = "CUSTOMER_PROFILE_EXTERNAL_CONFIG_DIR";
const LOG_ANSI_ENV: &str = "CUSTOMER_PROFILE_LOG_ANSI";
const DEFAULT_CONFIG_DIR: &str = "apps/demo-customer-profile-api/config";
const DEFAULT_EXTERNAL_CONFIG_DIR: &str = "apps/demo-customer-profile-api/config-cache";

#[derive(Clone, Default)]
struct CustomerProfileApp;

#[async_trait]
impl AxumApp for CustomerProfileApp {
    async fn router(&self, _context: ServerContext) -> std::result::Result<Router, RuntimeError> {
        Ok(build_router())
    }
}

#[derive(Clone)]
struct AppState {
    customers: HashMap<String, CustomerRecord>,
}

#[derive(Debug, Clone)]
struct CustomerRecord {
    profile: CustomerProfile,
    preferences: CustomerPreferences,
    policies: PolicyResponse,
    vehicles: HashMap<String, Vehicle>,
    prior_claims: PriorClaimsResponse,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct CustomerProfile {
    customer_id: String,
    display_name: String,
    segment: String,
    state: String,
    account_status: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct CustomerPreferences {
    customer_id: String,
    consent: bool,
    preferred_categories: Vec<String>,
    preferred_contact_channel: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PreferencesQuery {
    #[serde(default = "default_channel")]
    channel: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct PreferencesResponse {
    customer_id: String,
    channel: String,
    consent: bool,
    preferred_categories: Vec<String>,
    preferred_contact_channel: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct PolicyResponse {
    customer_id: String,
    policies: Vec<Policy>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct Policy {
    policy_id: String,
    status: String,
    effective_date: String,
    expiry_date: String,
    province: String,
    coverages: Vec<Coverage>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct Coverage {
    coverage_type: String,
    deductible: u32,
    limit: u32,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct Vehicle {
    customer_id: String,
    vehicle_id: String,
    vin: String,
    year: u16,
    make: String,
    model: String,
    covered: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct PriorClaimsResponse {
    customer_id: String,
    prior_claim_count: u32,
    recent_claim_count: u32,
    claims: Vec<PriorClaim>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct PriorClaim {
    claim_id: String,
    incident_date: String,
    status: String,
    paid_amount: u32,
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
    fn not_found(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            code,
            message: message.into(),
        }
    }

    fn customer_not_found(customer_id: &str) -> Self {
        Self::not_found(
            "CUSTOMER_NOT_FOUND",
            format!("customer {customer_id} was not found"),
        )
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

    let runtime = LightRuntimeBuilder::new(AxumTransport::new(CustomerProfileApp))
        .with_config_dir(config_dir)
        .with_external_config_dir(external_config_dir)
        .build();

    let running = runtime
        .start()
        .await
        .context("failed to start demo customer profile API")?;

    info!("demo customer profile API started");

    tokio::signal::ctrl_c()
        .await
        .context("failed to listen for shutdown signal")?;

    running
        .shutdown()
        .await
        .context("failed to shut down demo customer profile API")?;

    Ok(())
}

fn build_router() -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/customers/{customer_id}", get(get_customer))
        .route(
            "/customers/{customer_id}/preferences",
            get(get_customer_preferences),
        )
        .route(
            "/customers/{customer_id}/policies",
            get(get_customer_policies),
        )
        .route(
            "/customers/{customer_id}/vehicles/{vehicle_id}",
            get(get_covered_vehicle),
        )
        .route(
            "/customers/{customer_id}/prior-claims",
            get(get_prior_claims),
        )
        .with_state(AppState::seeded())
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "UP",
        service: "demo-customer-profile-api",
    })
}

async fn get_customer(
    State(state): State<AppState>,
    Path(customer_id): Path<String>,
) -> std::result::Result<Json<CustomerProfile>, ApiError> {
    state
        .find_profile(&customer_id)
        .map(Json)
        .ok_or_else(|| ApiError::customer_not_found(&customer_id))
}

async fn get_customer_preferences(
    State(state): State<AppState>,
    Path(customer_id): Path<String>,
    Query(query): Query<PreferencesQuery>,
) -> std::result::Result<Json<PreferencesResponse>, ApiError> {
    state
        .find_preferences(&customer_id, &query.channel)
        .map(Json)
        .ok_or_else(|| ApiError::customer_not_found(&customer_id))
}

async fn get_customer_policies(
    State(state): State<AppState>,
    Path(customer_id): Path<String>,
) -> std::result::Result<Json<PolicyResponse>, ApiError> {
    state
        .find_policies(&customer_id)
        .map(Json)
        .ok_or_else(|| ApiError::customer_not_found(&customer_id))
}

async fn get_covered_vehicle(
    State(state): State<AppState>,
    Path((customer_id, vehicle_id)): Path<(String, String)>,
) -> std::result::Result<Json<Vehicle>, ApiError> {
    if !state.customer_exists(&customer_id) {
        return Err(ApiError::customer_not_found(&customer_id));
    }

    state
        .find_vehicle(&customer_id, &vehicle_id)
        .map(Json)
        .ok_or_else(|| {
            ApiError::not_found(
                "VEHICLE_NOT_FOUND",
                format!("vehicle {vehicle_id} was not found for customer {customer_id}"),
            )
        })
}

async fn get_prior_claims(
    State(state): State<AppState>,
    Path(customer_id): Path<String>,
) -> std::result::Result<Json<PriorClaimsResponse>, ApiError> {
    state
        .find_prior_claims(&customer_id)
        .map(Json)
        .ok_or_else(|| ApiError::customer_not_found(&customer_id))
}

impl AppState {
    fn seeded() -> Self {
        let records = [
            CustomerRecord::new(
                "CUST-1001",
                "Avery Chen",
                "premium",
                "ON",
                "active",
                true,
                ["travel"],
                "portal",
                vec![Policy::new(
                    "POL-AUTO-1001",
                    "active",
                    "2025-01-01",
                    "2027-01-01",
                    "ON",
                    vec![Coverage::new("collision", 500, 50000)],
                )],
                vec![Vehicle::new(
                    "CUST-1001",
                    "VEH-1001",
                    "DEMO-VIN-1001",
                    2022,
                    "Toyota",
                    "RAV4",
                    true,
                )],
                PriorClaimsResponse::new(
                    "CUST-1001",
                    0,
                    vec![PriorClaim::new(
                        "CLM-OLD-1001",
                        "2024-08-12",
                        "closed",
                        1800,
                    )],
                ),
            ),
            CustomerRecord::new(
                "CUST-2002",
                "Blake Morgan",
                "standard",
                "ON",
                "active",
                true,
                ["travel"],
                "portal",
                vec![Policy::new(
                    "POL-AUTO-2002",
                    "expired",
                    "2023-01-01",
                    "2025-01-01",
                    "ON",
                    vec![Coverage::new("collision", 1000, 25000)],
                )],
                vec![Vehicle::new(
                    "CUST-2002",
                    "VEH-2002",
                    "DEMO-VIN-2002",
                    2017,
                    "Honda",
                    "Civic",
                    false,
                )],
                PriorClaimsResponse::new(
                    "CUST-2002",
                    1,
                    vec![
                        PriorClaim::new("CLM-OLD-2002", "2023-11-03", "closed", 2400),
                        PriorClaim::new("CLM-RECENT-2002", "2026-02-18", "closed", 1250),
                    ],
                ),
            ),
            CustomerRecord::new(
                "CUST-3003",
                "Casey Patel",
                "premium",
                "ON",
                "active",
                false,
                ["travel"],
                "portal",
                vec![Policy::new(
                    "POL-AUTO-3003",
                    "active",
                    "2025-06-01",
                    "2027-06-01",
                    "ON",
                    vec![Coverage::new("collision", 500, 50000)],
                )],
                vec![Vehicle::new(
                    "CUST-3003",
                    "VEH-3003",
                    "DEMO-VIN-3003",
                    2020,
                    "Subaru",
                    "Outback",
                    true,
                )],
                PriorClaimsResponse::new("CUST-3003", 0, vec![]),
            ),
        ];

        Self {
            customers: records
                .into_iter()
                .map(|record| (record.profile.customer_id.clone(), record))
                .collect(),
        }
    }

    fn find_profile(&self, customer_id: &str) -> Option<CustomerProfile> {
        self.customers
            .get(customer_id)
            .map(|record| record.profile.clone())
    }

    fn find_preferences(&self, customer_id: &str, channel: &str) -> Option<PreferencesResponse> {
        self.customers
            .get(customer_id)
            .map(|record| record.preferences.for_channel(channel))
    }

    fn find_policies(&self, customer_id: &str) -> Option<PolicyResponse> {
        self.customers
            .get(customer_id)
            .map(|record| record.policies.clone())
    }

    fn find_vehicle(&self, customer_id: &str, vehicle_id: &str) -> Option<Vehicle> {
        self.customers
            .get(customer_id)
            .and_then(|record| record.vehicles.get(vehicle_id).cloned())
    }

    fn find_prior_claims(&self, customer_id: &str) -> Option<PriorClaimsResponse> {
        self.customers
            .get(customer_id)
            .map(|record| record.prior_claims.clone())
    }

    fn customer_exists(&self, customer_id: &str) -> bool {
        self.customers.contains_key(customer_id)
    }
}

impl CustomerRecord {
    fn new(
        customer_id: &str,
        display_name: &str,
        segment: &str,
        state: &str,
        account_status: &str,
        consent: bool,
        preferred_categories: [&str; 1],
        preferred_contact_channel: &str,
        policies: Vec<Policy>,
        vehicles: Vec<Vehicle>,
        prior_claims: PriorClaimsResponse,
    ) -> Self {
        let customer_id = customer_id.to_string();
        Self {
            profile: CustomerProfile {
                customer_id: customer_id.clone(),
                display_name: display_name.to_string(),
                segment: segment.to_string(),
                state: state.to_string(),
                account_status: account_status.to_string(),
            },
            preferences: CustomerPreferences {
                customer_id: customer_id.clone(),
                consent,
                preferred_categories: preferred_categories
                    .into_iter()
                    .map(str::to_string)
                    .collect(),
                preferred_contact_channel: preferred_contact_channel.to_string(),
            },
            policies: PolicyResponse {
                customer_id,
                policies,
            },
            vehicles: vehicles
                .into_iter()
                .map(|vehicle| (vehicle.vehicle_id.clone(), vehicle))
                .collect(),
            prior_claims,
        }
    }
}

impl Policy {
    fn new(
        policy_id: &str,
        status: &str,
        effective_date: &str,
        expiry_date: &str,
        province: &str,
        coverages: Vec<Coverage>,
    ) -> Self {
        Self {
            policy_id: policy_id.to_string(),
            status: status.to_string(),
            effective_date: effective_date.to_string(),
            expiry_date: expiry_date.to_string(),
            province: province.to_string(),
            coverages,
        }
    }
}

impl Coverage {
    fn new(coverage_type: &str, deductible: u32, limit: u32) -> Self {
        Self {
            coverage_type: coverage_type.to_string(),
            deductible,
            limit,
        }
    }
}

impl Vehicle {
    fn new(
        customer_id: &str,
        vehicle_id: &str,
        vin: &str,
        year: u16,
        make: &str,
        model: &str,
        covered: bool,
    ) -> Self {
        Self {
            customer_id: customer_id.to_string(),
            vehicle_id: vehicle_id.to_string(),
            vin: vin.to_string(),
            year,
            make: make.to_string(),
            model: model.to_string(),
            covered,
        }
    }
}

impl PriorClaimsResponse {
    fn new(customer_id: &str, recent_claim_count: u32, claims: Vec<PriorClaim>) -> Self {
        Self {
            customer_id: customer_id.to_string(),
            prior_claim_count: claims.len() as u32,
            recent_claim_count,
            claims,
        }
    }
}

impl PriorClaim {
    fn new(claim_id: &str, incident_date: &str, status: &str, paid_amount: u32) -> Self {
        Self {
            claim_id: claim_id.to_string(),
            incident_date: incident_date.to_string(),
            status: status.to_string(),
            paid_amount,
        }
    }
}

impl CustomerPreferences {
    fn for_channel(&self, channel: &str) -> PreferencesResponse {
        PreferencesResponse {
            customer_id: self.customer_id.clone(),
            channel: channel.to_string(),
            consent: self.consent,
            preferred_categories: self.preferred_categories.clone(),
            preferred_contact_channel: self.preferred_contact_channel.clone(),
        }
    }
}

fn default_channel() -> String {
    "portal".to_string()
}

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let use_ansi = std::env::var(LOG_ANSI_ENV)
        .ok()
        .map(|value| value.trim().to_lowercase())
        .map(|value| value == "true" || value == "1" || value == "yes" || value == "on");

    let subscriber = tracing_subscriber::fmt().with_env_filter(filter);
    match use_ansi {
        Some(use_ansi) => subscriber.with_ansi(use_ansi).init(),
        None => subscriber.init(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::{Body, to_bytes},
        http::{Request, StatusCode},
    };
    use tower::ServiceExt;

    #[test]
    fn seeded_state_returns_premium_customer_profile() {
        let state = AppState::seeded();

        let profile = state.find_profile("CUST-1001").expect("profile");

        assert_eq!(profile.segment, "premium");
        assert_eq!(profile.state, "ON");
    }

    #[test]
    fn preferences_include_requested_channel() {
        let state = AppState::seeded();

        let preferences = state
            .find_preferences("CUST-3003", "portal")
            .expect("preferences");

        assert!(!preferences.consent);
        assert_eq!(preferences.channel, "portal");
    }

    #[test]
    fn seeded_state_returns_insurance_context() {
        let state = AppState::seeded();

        let policies = state.find_policies("CUST-1001").expect("policies");
        let vehicle = state
            .find_vehicle("CUST-1001", "VEH-1001")
            .expect("vehicle");
        let prior_claims = state.find_prior_claims("CUST-1001").expect("prior claims");

        assert_eq!(policies.policies[0].status, "active");
        assert_eq!(policies.policies[0].coverages[0].deductible, 500);
        assert!(vehicle.covered);
        assert_eq!(prior_claims.prior_claim_count, 1);
        assert_eq!(prior_claims.recent_claim_count, 0);
    }

    #[tokio::test]
    async fn customer_route_returns_profile_json() {
        let response = build_router()
            .oneshot(
                Request::builder()
                    .uri("/customers/CUST-1001")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let profile: CustomerProfile = serde_json::from_slice(&body).expect("profile json");

        assert_eq!(profile.customer_id, "CUST-1001");
        assert_eq!(profile.segment, "premium");
    }

    #[tokio::test]
    async fn preferences_route_returns_channel_specific_json() {
        let response = build_router()
            .oneshot(
                Request::builder()
                    .uri("/customers/CUST-1001/preferences?channel=portal")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let preferences: PreferencesResponse =
            serde_json::from_slice(&body).expect("preferences json");

        assert!(preferences.consent);
        assert_eq!(preferences.preferred_categories, vec!["travel"]);
    }

    #[tokio::test]
    async fn insurance_routes_return_policy_vehicle_and_claims() {
        let policy_response = build_router()
            .oneshot(
                Request::builder()
                    .uri("/customers/CUST-1001/policies")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(policy_response.status(), StatusCode::OK);
        let body = to_bytes(policy_response.into_body(), usize::MAX)
            .await
            .expect("body");
        let policies: PolicyResponse = serde_json::from_slice(&body).expect("policies json");
        assert_eq!(policies.policies[0].policy_id, "POL-AUTO-1001");

        let vehicle_response = build_router()
            .oneshot(
                Request::builder()
                    .uri("/customers/CUST-2002/vehicles/VEH-2002")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(vehicle_response.status(), StatusCode::OK);
        let body = to_bytes(vehicle_response.into_body(), usize::MAX)
            .await
            .expect("body");
        let vehicle: Vehicle = serde_json::from_slice(&body).expect("vehicle json");
        assert!(!vehicle.covered);

        let prior_claims_response = build_router()
            .oneshot(
                Request::builder()
                    .uri("/customers/CUST-2002/prior-claims")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");

        assert_eq!(prior_claims_response.status(), StatusCode::OK);
        let body = to_bytes(prior_claims_response.into_body(), usize::MAX)
            .await
            .expect("body");
        let prior_claims: PriorClaimsResponse =
            serde_json::from_slice(&body).expect("prior claims json");
        assert_eq!(prior_claims.recent_claim_count, 1);
    }
}
