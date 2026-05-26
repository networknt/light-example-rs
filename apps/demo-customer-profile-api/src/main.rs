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
    fn not_found(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            code: "CUSTOMER_NOT_FOUND",
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
        .ok_or_else(|| ApiError::not_found(format!("customer {customer_id} was not found")))
}

async fn get_customer_preferences(
    State(state): State<AppState>,
    Path(customer_id): Path<String>,
    Query(query): Query<PreferencesQuery>,
) -> std::result::Result<Json<PreferencesResponse>, ApiError> {
    state
        .find_preferences(&customer_id, &query.channel)
        .map(Json)
        .ok_or_else(|| ApiError::not_found(format!("customer {customer_id} was not found")))
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
    ) -> Self {
        Self {
            profile: CustomerProfile {
                customer_id: customer_id.to_string(),
                display_name: display_name.to_string(),
                segment: segment.to_string(),
                state: state.to_string(),
                account_status: account_status.to_string(),
            },
            preferences: CustomerPreferences {
                customer_id: customer_id.to_string(),
                consent,
                preferred_categories: preferred_categories
                    .into_iter()
                    .map(str::to_string)
                    .collect(),
                preferred_contact_channel: preferred_contact_channel.to_string(),
            },
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
}
