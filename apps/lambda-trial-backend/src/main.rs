use lambda_runtime::{Error, LambdaEvent, service_fn};
use serde::Deserialize;
use serde_json::{Value, json};

mod parity;

const MAX_BODY_BYTES: usize = 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Command {
    mode: Mode,
    #[serde(rename = "trialId")]
    trial_id: String,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "kebab-case")]
enum Mode {
    Success,
    ApplicationError,
    FunctionError,
}

impl Mode {
    fn label(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::ApplicationError => "application-error",
            Self::FunctionError => "function-error",
        }
    }
}

fn response(status: u16, body: Value) -> Value {
    json!({
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "isBase64Encoded": false,
        "body": body.to_string()
    })
}

fn command(event: &Value) -> Option<Command> {
    // This is the business Lambda's API Gateway proxy envelope, not gateway ingress.
    if event.get("isBase64Encoded").is_some_and(|v| v != false) {
        return None;
    }
    let body = event.get("body")?.as_str()?;
    if body.len() > MAX_BODY_BYTES {
        return None;
    }
    let cmd: Command = serde_json::from_str(body).ok()?;
    if cmd.trial_id.is_empty()
        || cmd.trial_id.len() > 64
        || !cmd
            .trial_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_".contains(&b))
    {
        return None;
    }
    Some(cmd)
}

async fn handle(event: LambdaEvent<Value>) -> Result<Value, Error> {
    if parity::selected(&event.payload) {
        return parity::handle(&event.payload, &event.context.request_id).await;
    }
    let Some(cmd) = command(&event.payload) else {
        // Never log input, headers, tokens, malformed values or error payloads.
        eprintln!(
            "{}",
            json!({"event":"trial_backend_execution", "request_id":event.context.request_id, "mode":"invalid-command"})
        );
        return Ok(response(400, json!({"code":"TRIAL_INVALID_COMMAND"})));
    };
    eprintln!(
        "{}",
        json!({"event":"trial_backend_execution", "request_id":event.context.request_id, "trial_id":cmd.trial_id, "mode":cmd.mode.label()})
    );
    match cmd.mode {
        Mode::Success => Ok(response(200, json!({"trialId":cmd.trial_id,"result":"ok"}))),
        Mode::ApplicationError => Ok(response(500, json!({"code":"TRIAL_BACKEND_ERROR"}))),
        Mode::FunctionError => Err(std::io::Error::other("synthetic trial function error").into()),
    }
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    lambda_runtime::run(service_fn(handle)).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_unsafe_or_ambiguous_commands() {
        for body in [
            r#"{"mode":"success","trialId":"line\nbreak"}"#,
            r#"{"mode":"success","trialId":""}"#,
            r#"{"mode":"success","trialId":"safe","extra":true}"#,
            r#"{"mode":"unknown","trialId":"safe"}"#,
        ] {
            assert!(command(&json!({"body":body})).is_none());
        }
        assert!(command(&json!({"body":"x".repeat(MAX_BODY_BYTES + 1)})).is_none());
        assert!(command(&json!({"body":{"mode":"success","trialId":"safe"}})).is_none());
        assert!(
            command(
                &json!({"body":r#"{"mode":"success","trialId":"safe"}"#, "isBase64Encoded":true})
            )
            .is_none()
        );
    }
}
