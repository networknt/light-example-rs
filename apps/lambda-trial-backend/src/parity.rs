//! Versioned, bounded synthetic modes. Never serialize an incoming event wholesale.
use lambda_runtime::Error;
use serde_json::{Map, Value, json};

pub const TABLE: &str = "parity-modes/v1";
pub const MAX_BODY: usize = 4096;
const HEADERS: &[&str] = &[
    "x-parity-case",
    "x-parity-run",
    "x-parity-id",
    "x-parity-attempt",
    "x-synthetic",
    "content-type",
];

pub fn selected(event: &Value) -> bool {
    ["headers", "multiValueHeaders"].iter().any(|map| {
        event[*map]
            .as_object()
            .is_some_and(|m| m.keys().any(|k| k.eq_ignore_ascii_case("x-parity-case")))
    })
}

fn control(event: &Value, name: &str) -> Option<String> {
    let mut values = Vec::new();
    for map in ["headers", "multiValueHeaders"] {
        if let Some(headers) = event[map].as_object() {
            let mut matched = false;
            for (key, value) in headers {
                if key.eq_ignore_ascii_case(name) {
                    if matched {
                        return None;
                    }
                    matched = true;
                    if let Some(value) = value.as_str() {
                        values.push(value);
                    } else {
                        let array = value.as_array()?;
                        if array.len() != 1 {
                            return None;
                        }
                        values.push(array[0].as_str()?);
                    }
                }
            }
        }
    }
    if values.is_empty() || values.len() > 2 || values.iter().any(|v| *v != values[0]) {
        return None;
    }
    let value = values[0];
    (1..=64).contains(&value.len()).then_some(())?;
    value
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
        .then(|| value.to_owned())
}

fn envelope(status: u16, body: String) -> Value {
    json!({"statusCode":status,"headers":{"content-type":"application/json"},"body":body,"isBase64Encoded":false})
}

fn echo(event: &Value, identity: &str, version: &str) -> Option<Value> {
    // Fixed field allowlist; requestContext (principals), cookies and arbitrary query
    // names are intentionally excluded. Test queries use only q and empty.
    let mut out = Map::new();
    for key in [
        "httpMethod",
        "path",
        "resource",
        "pathParameters",
        "body",
        "isBase64Encoded",
    ] {
        if let Some(value) = event.get(key) {
            if value.to_string().len() > MAX_BODY * 2 {
                return None;
            }
            out.insert(key.into(), value.clone());
        }
    }
    for key in ["queryStringParameters", "multiValueQueryStringParameters"] {
        if let Some(value) = event.get(key) {
            let mut safe = Map::new();
            if let Some(map) = value.as_object() {
                for name in ["q", "empty"] {
                    if let Some(value) = map.get(name) {
                        if value.to_string().len() > 1024 {
                            return None;
                        }
                        safe.insert(name.into(), value.clone());
                    }
                }
            }
            out.insert(key.into(), Value::Object(safe));
        }
    }
    for map in ["headers", "multiValueHeaders"] {
        if let Some(headers) = event[map].as_object() {
            if headers.len() > 32 {
                return None;
            }
            let mut safe = Map::new();
            for (name, value) in headers {
                if HEADERS
                    .iter()
                    .any(|allowed| name.eq_ignore_ascii_case(allowed))
                {
                    if value.to_string().len() > 512 {
                        return None;
                    }
                    safe.insert(name.to_ascii_lowercase(), value.clone());
                }
            }
            out.insert(map.into(), Value::Object(safe));
        }
    }
    out.insert("backendIdentity".into(), json!(identity));
    out.insert("backendVersion".into(), json!(version));
    Some(Value::Object(out))
}

pub async fn handle(event: &Value, request_id: &str) -> Result<Value, Error> {
    let identity = std::env::var("PARITY_BACKEND_IDENTITY").unwrap_or_else(|_| "echo-a".into());
    let version = std::env::var("AWS_LAMBDA_FUNCTION_VERSION").unwrap_or_else(|_| "local".into());
    let invalid = || envelope(400, r#"{"code":"PARITY_INVALID_CONTROL"}"#.into());
    let ids: Option<Vec<String>> = ["x-parity-run", "x-parity-id", "x-parity-attempt"]
        .iter()
        .map(|k| control(event, k))
        .collect();
    let ids_valid = ids.is_some();
    let ids = ids.unwrap_or_else(|| vec!["invalid".into(); 3]);
    let requested_mode = control(event, "x-parity-case").unwrap_or_default();
    if !["echo-a", "echo-b", "delay", "denied"].contains(&identity.as_str())
        || version.len() > 64
        || request_id.len() > 128
    {
        return Ok(invalid());
    }
    let echoed = echo(event, &identity, &version);
    let known = [
        "echo",
        "created",
        "no-content",
        "application-error",
        "function-error",
        "empty",
        "binary",
        "cookies",
        "wrong-type",
        "missing-status",
        "invalid-base64",
        "malformed-json",
    ];
    let valid = ids_valid
        && echoed.is_some()
        && !event["body"].as_str().is_some_and(|s| s.len() > MAX_BODY)
        && known.contains(&requested_mode.as_str());
    let mode = if valid {
        requested_mode.as_str()
    } else {
        "invalid-control"
    };
    let record = |phase: &str| json!({"schema":"parity-execution/v1","phase":phase,"runId":ids[0],"caseId":ids[1],"attemptId":ids[2],"backendIdentity":identity,"backendVersion":version,"executionRequestId":request_id,"modeTable":TABLE,"mode":mode});
    eprintln!("{}", record("entry"));
    let result = match mode {
        "invalid-control" => invalid(),
        "echo" => envelope(200, echoed.expect("validated echo").to_string()),
        "created" => envelope(201, r#"{"result":"created"}"#.into()),
        "no-content" => envelope(204, String::new()),
        "empty" => envelope(200, String::new()),
        "application-error" => envelope(500, r#"{"code":"PARITY_APPLICATION_ERROR"}"#.into()),
        "function-error" => {
            return Err(std::io::Error::other("synthetic parity function error").into());
        }
        "binary" => {
            json!({"statusCode":200,"headers":{"content-type":"application/octet-stream"},"body":"AP9B","isBase64Encoded":true})
        }
        "cookies" => {
            json!({"statusCode":200,"headers":{},"multiValueHeaders":{"set-cookie":["synthetic=a; Secure","synthetic=b; Secure"]},"body":"cookies","isBase64Encoded":false})
        }
        "wrong-type" => json!({"statusCode":"two hundred","body":"invalid"}),
        "missing-status" => json!({"body":"invalid"}),
        "invalid-base64" => {
            json!({"statusCode":200,"headers":{},"body":"%%%","isBase64Encoded":true})
        }
        "malformed-json" => envelope(200, "{broken".into()),
        _ => unreachable!(),
    };
    eprintln!("{}", record("completion"));
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn event(mode: &str) -> Value {
        json!({"httpMethod":"POST","path":"/parity/a","headers":{"x-parity-case":mode,"x-parity-run":"run","x-parity-id":"case","x-parity-attempt":"java-1","authorization":"never-echo","cookie":"never-echo","x-private":"never-echo"},"queryStringParameters":{"token":"never-echo","q":"a+b"},"body":"synthetic"})
    }
    #[tokio::test]
    async fn finite_modes_privacy_and_real_error() {
        let value = handle(&event("echo"), "req").await.unwrap();
        assert!(!value.to_string().contains("never-echo"));
        assert_eq!(value["statusCode"], 200);
        assert_eq!(
            handle(&event("application-error"), "req").await.unwrap()["statusCode"],
            500
        );
        assert!(handle(&event("function-error"), "req").await.is_err());
        assert_eq!(
            handle(&event("unknown"), "req").await.unwrap()["statusCode"],
            400
        );
        assert_eq!(
            handle(&event("echo"), "recovery").await.unwrap()["statusCode"],
            200
        );
    }
    #[tokio::test]
    async fn rejects_empty_controls_and_case_duplicate_names() {
        for name in [
            "x-parity-case",
            "x-parity-run",
            "x-parity-id",
            "x-parity-attempt",
        ] {
            let mut mirrored = event("created");
            mirrored["multiValueHeaders"] = json!({name: []});
            assert_eq!(
                handle(&mirrored, "req").await.unwrap()["statusCode"],
                400,
                "empty mirror accepted for {name}"
            );

            let mut duplicate = event("created");
            let value = duplicate["headers"][name].clone();
            duplicate["headers"].as_object_mut().unwrap().remove(name);
            duplicate["multiValueHeaders"] = json!({name: [value], name.to_ascii_uppercase(): []});
            assert_eq!(
                handle(&duplicate, "req").await.unwrap()["statusCode"],
                400,
                "case-duplicate name accepted for {name}"
            );
        }
        let mut valid = event("created");
        valid["multiValueHeaders"] = json!({"x-parity-case": ["created"]});
        assert_eq!(handle(&valid, "req").await.unwrap()["statusCode"], 201);
    }

    #[tokio::test]
    async fn duplicates_bounds_and_presence() {
        let mut e = event("echo");
        e["multiValueHeaders"] = json!({"X-Parity-Case":["created"]});
        assert_eq!(handle(&e, "req").await.unwrap()["statusCode"], 400);
        e.as_object_mut().unwrap().remove("multiValueHeaders");
        e["body"] = json!("x".repeat(MAX_BODY + 1));
        assert_eq!(handle(&e, "req").await.unwrap()["statusCode"], 400);
        for body in [None, Some(Value::Null), Some(json!(""))] {
            let mut e = event("echo");
            e.as_object_mut().unwrap().remove("body");
            if let Some(body) = body.clone() {
                e["body"] = body;
            }
            let result = handle(&e, "req").await.unwrap();
            let echoed: Value = serde_json::from_str(result["body"].as_str().unwrap()).unwrap();
            assert_eq!(echoed.get("body"), body.as_ref());
        }
    }
}
