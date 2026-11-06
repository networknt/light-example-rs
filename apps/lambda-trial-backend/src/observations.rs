//! Opt-in, bounded synthetic received-event observations; never SDK-wire proof.
use serde_json::{Map, Value, json};

pub const PROFILE: &str = "synthetic-v1";
pub const MAX_RECORD_BYTES: usize = 4096;
const MAX_VALUES: usize = 8;
const MAX_BODY_BYTES: usize = 128;

fn scalar(value: Option<&Value>, allowed: impl Fn(&Value) -> bool) -> Value {
    match value {
        None => json!({"state":"absent"}),
        Some(Value::Null) => json!({"state":"null"}),
        Some(value) if allowed(value) => json!({"state":"value","value":value}),
        Some(_) => json!({"state":"redacted"}),
    }
}

fn safe_values(value: &Value, multi: bool, allowed: &[&str]) -> bool {
    let safe = |v: &Value| v.as_str().is_some_and(|s| allowed.contains(&s));
    if multi {
        value
            .as_array()
            .is_some_and(|v| v.len() <= MAX_VALUES && v.iter().all(safe))
    } else {
        safe(value)
    }
}

fn selected_map(event: &Value, key: &str, multi: bool, headers: bool) -> Value {
    let map = match event.get(key) {
        None => return json!({"state":"absent"}),
        Some(Value::Null) => return json!({"state":"null"}),
        Some(Value::Object(map)) if map.len() <= 32 => map,
        Some(_) => return json!({"state":"redacted"}),
    };
    let mut values = Map::new();
    for (name, value) in map {
        let allowed: Option<&[&str]> = if headers {
            if name.eq_ignore_ascii_case("x-synthetic") {
                Some(&["first", "second", "synthetic"])
            } else if name.eq_ignore_ascii_case("content-type") {
                Some(&["application/json", "application/octet-stream", "text/plain"])
            } else {
                None
            }
        } else {
            match name.as_str() {
                "q" => Some(&["a+b", "+", "%2B", "雪", "", "synthetic"]),
                "empty" => Some(&[""]),
                _ => None,
            }
        };
        if let Some(allowed) = allowed {
            // Retain original name/case, namespace, presence and array order.
            values.insert(
                name.clone(),
                if safe_values(value, multi, allowed) {
                    json!({"state":"value","value":value})
                } else {
                    json!({"state":"redacted"})
                },
            );
        }
    }
    json!({"state":"object","values":values})
}

fn body(event: &Value) -> Value {
    match event.get("body") {
        None => json!({"state":"absent"}),
        Some(Value::Null) => json!({"state":"null"}),
        Some(Value::String(value))
            if value.len() <= MAX_BODY_BYTES
                && ([
                    "",
                    "synthetic",
                    "雪 café",
                    "雪 synthetic",
                    "{\"n\":9007199254740993}",
                    "c3ludGhldGlj",
                    "AP9B",
                ]
                .contains(&value.as_str())
                    || value.bytes().all(|b| b == b'x')) =>
        {
            let hex: String = value
                .as_bytes()
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect();
            json!({"state":"string","utf8Hex":hex,"byteLength":value.len()})
        }
        Some(_) => json!({"state":"redacted"}),
    }
}

/// Values are selected from a closed synthetic domain, never arbitrary input.
pub fn observation(event: &Value) -> Value {
    json!({
        "httpMethod":scalar(event.get("httpMethod"), |v| v.as_str().is_some_and(|s| ["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"].contains(&s))),
        "path":scalar(event.get("path"), |v| v.as_str().is_some_and(|s| ["/parity/a","/parity/b","/parity/missing"].contains(&s))),
        "queryStringParameters":selected_map(event,"queryStringParameters",false,false),
        "multiValueQueryStringParameters":selected_map(event,"multiValueQueryStringParameters",true,false),
        "headers":selected_map(event,"headers",false,true),
        "multiValueHeaders":selected_map(event,"multiValueHeaders",true,true),
        "body":body(event),
        "isBase64Encoded":scalar(event.get("isBase64Encoded"),Value::is_boolean)
    })
}

pub fn record(enabled: bool, event: &Value, metadata: &Value) -> Option<String> {
    if !enabled {
        return None;
    }
    // Metadata is constructed by the caller from the existing bounded control IDs
    // and runtime identity. No requestContext, credential or input map is copied.
    let mut value = metadata.clone();
    value["schema"] = json!("parity-request-observation/v1");
    value["phase"] = json!("received-event");
    value["observation"] = observation(event);
    let record = value.to_string();
    (record.len() <= MAX_RECORD_BYTES).then_some(record)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn body_presence_bytes_and_base64_are_independent() {
        assert_eq!(observation(&json!({}))["body"], json!({"state":"absent"}));
        assert_eq!(
            observation(&json!({"body":null}))["body"],
            json!({"state":"null"})
        );
        for (text, hex) in [
            ("", ""),
            ("雪 café", "e99baa20636166c3a9"),
            ("AP9B", "41503942"),
        ] {
            for flag in [false, true] {
                let got = observation(&json!({"body":text,"isBase64Encoded":flag}));
                assert_eq!(
                    got["body"],
                    json!({"state":"string","utf8Hex":hex,"byteLength":text.len()})
                );
                assert_eq!(
                    got["isBase64Encoded"],
                    json!({"state":"value","value":flag})
                );
            }
        }
        for flag in [json!(null), json!("secret"), json!({"secret":"token"})] {
            let got = observation(&json!({"isBase64Encoded":flag}));
            assert!(!got.to_string().contains("secret"));
        }
    }

    #[test]
    fn privacy_is_closed_even_inside_allowed_fields() {
        let secret = "private-credential-canary";
        let event = json!({"httpMethod":secret,"path":secret,"headers":{"Authorization":secret,"Cookie":secret,"X-Synthetic":secret,"content-type":{"nested":secret}},"multiValueHeaders":{"authorization":[secret],"x-synthetic":["first",secret]},"queryStringParameters":{"token":secret,"q":secret},"multiValueQueryStringParameters":{"authorization":[secret],"q":["a+b",secret]},"body":secret,"requestContext":{"authorizer":secret}});
        let got = observation(&event);
        let text = got.to_string();
        for forbidden in [
            secret,
            "Authorization",
            "authorization",
            "Cookie",
            "requestContext",
            "authorizer",
            "token",
        ] {
            assert!(!text.contains(forbidden), "{forbidden}");
        }
        assert_eq!(
            got["headers"]["values"]["X-Synthetic"],
            json!({"state":"redacted"})
        );
        assert!(record(false, &event, &json!({})).is_none());
    }

    #[test]
    fn multiplicity_case_and_bounded_values() {
        let event = json!({"multiValueQueryStringParameters":{"q":["a+b","%2B","雪",""],"empty":[""]},"headers":{"X-Synthetic":"second"},"multiValueHeaders":{"X-Synthetic":["first","second"]}});
        let got = observation(&event);
        assert_eq!(
            got["multiValueQueryStringParameters"]["values"]["q"]["value"],
            json!(["a+b", "%2B", "雪", ""])
        );
        assert_eq!(
            got["multiValueHeaders"]["values"]["X-Synthetic"]["value"],
            json!(["first", "second"])
        );
        assert!(
            got["multiValueHeaders"]["values"]
                .get("x-synthetic")
                .is_none()
        );
        for (n, state) in [(8, "value"), (9, "redacted")] {
            let got =
                observation(&json!({"multiValueQueryStringParameters":{"q":vec!["synthetic";n]}}));
            assert_eq!(
                got["multiValueQueryStringParameters"]["values"]["q"]["state"],
                state
            );
        }
        for (n, state) in [(128, "string"), (129, "redacted")] {
            assert_eq!(
                observation(&json!({"body":"x".repeat(n)}))["body"]["state"],
                state
            );
        }
        let metadata = json!({"executionRequestId":"r".repeat(128),"runId":"r".repeat(64),"caseId":"c".repeat(64),"attemptId":"a".repeat(64),"backendIdentity":"echo-a","backendVersion":"1"});
        assert!(record(true, &event, &metadata).unwrap().len() <= MAX_RECORD_BYTES);
    }
}
