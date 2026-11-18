//! Private HTTP transport. Bind only to loopback; OAuth/public ingress is separate.
use crate::TaskTools;
use anyhow::{bail, Context};
use axum::{
    extract::{Request, State},
    http::{header, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use rmcp::transport::streamable_http_server::{
    session::local::LocalSessionManager, StreamableHttpServerConfig, StreamableHttpService,
};
use std::{net::SocketAddr, sync::Arc};
use subtle::ConstantTimeEq;

pub struct HttpConfig {
    pub bind: SocketAddr,
    token: Arc<[u8]>,
}
impl HttpConfig {
    pub fn new(bind: SocketAddr, token: String) -> anyhow::Result<Self> {
        if !bind.ip().is_loopback() {
            bail!("MCP HTTP must bind to loopback; use a private tunnel or authenticated OAuth gateway for remote access");
        }
        let token = token.trim();
        if token.len() < 32
            || token.len() > 256
            || !token
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-_".contains(&c))
        {
            bail!("MCP bearer token must contain 32..256 ASCII letters/digits or -_; generate a random token with start-mcp-http.ps1");
        }
        Ok(Self {
            bind,
            token: Arc::from(token.as_bytes()),
        })
    }
    pub fn from_env() -> anyhow::Result<Self> {
        let bind = std::env::var("PERSONAL_ISLAND_MCP_BIND")
            .unwrap_or_else(|_| "127.0.0.1:18741".into())
            .parse()
            .context("Invalid PERSONAL_ISLAND_MCP_BIND")?;
        let token = match (std::env::var("PERSONAL_ISLAND_MCP_TOKEN"), std::env::var_os("PERSONAL_ISLAND_MCP_TOKEN_FILE")) {
            (Ok(_), Some(_)) => bail!("Set only one of PERSONAL_ISLAND_MCP_TOKEN or PERSONAL_ISLAND_MCP_TOKEN_FILE"),
            (Ok(token), None) => token,
            (Err(_), Some(path)) => std::fs::read_to_string(path).context("Could not read MCP token file")?,
            _ => bail!("MCP token is required; run scripts/start-mcp-http.ps1 or set PERSONAL_ISLAND_MCP_TOKEN_FILE"),
        };
        Self::new(bind, token)
    }
}

#[derive(Clone)]
struct Auth {
    token: Arc<[u8]>,
}
async fn authenticate(State(auth): State<Auth>, request: Request, next: Next) -> Response {
    let values = request.headers().get_all(header::AUTHORIZATION);
    let authorized = values.iter().count() == 1
        && values
            .iter()
            .next()
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.strip_prefix("Bearer "))
            .is_some_and(|token| bool::from(token.as_bytes().ct_eq(auth.token.as_ref())));
    if !authorized {
        return (
            StatusCode::UNAUTHORIZED,
            [(
                header::WWW_AUTHENTICATE,
                "Bearer realm=\"personal-island-local\"",
            )],
            "Authentication required",
        )
            .into_response();
    }
    // The private bridge accepts machine clients, not cross-site browser calls.
    if request.headers().contains_key(header::ORIGIN) {
        return (
            StatusCode::FORBIDDEN,
            "Browser origins are not enabled on this private bridge",
        )
            .into_response();
    }
    let mut response = next.run(request).await;
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, "no-store".parse().unwrap());
    response
}

pub fn router(tools: TaskTools, config: &HttpConfig) -> Router {
    let timezone = tools.timezone();
    let mcp: StreamableHttpService<TaskTools, LocalSessionManager> = StreamableHttpService::new(
        move || Ok(tools.clone()),
        Default::default(),
        StreamableHttpServerConfig::default()
            .with_legacy_session_mode(false)
            .with_json_response(true)
            .with_max_request_body_bytes(256 * 1024)
            .enforce_origin_validation(),
    );
    Router::new()
        .route("/health", get(move || { let timezone = timezone.clone(); async move { Json(serde_json::json!({"status":"ready","service":"personal-island-mcp","timezone":timezone,"public_access":false})) } }))
        .nest_service("/mcp", mcp)
        .layer(middleware::from_fn_with_state(Auth {token:config.token.clone()}, authenticate))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn public_binds_and_weak_or_header_injecting_tokens_are_rejected() {
        let strong = "a".repeat(64);
        assert!(HttpConfig::new("127.0.0.1:0".parse().unwrap(), strong.clone()).is_ok());
        assert!(HttpConfig::new("[::1]:18741".parse().unwrap(), strong.clone()).is_ok());
        for bind in ["0.0.0.0:18741", "[::]:18741", "192.168.1.5:18741"] {
            assert!(HttpConfig::new(bind.parse().unwrap(), strong.clone()).is_err());
        }
        for token in [
            "short".to_owned(),
            format!("{}\r\nHeader:value", strong),
            "a".repeat(257),
        ] {
            assert!(HttpConfig::new("127.0.0.1:18741".parse().unwrap(), token).is_err());
        }
    }
}
