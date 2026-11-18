use task_core::TaskStore;
use task_mcp::{
    http::{self, HttpConfig},
    TaskTools,
};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Validate transport configuration before touching the application database.
    let config = HttpConfig::from_env()?;
    let tools = TaskTools::from_env(TaskStore::open_default().await?, true)?;
    let listener = tokio::net::TcpListener::bind(config.bind).await?;
    eprintln!(
        "Personal Island private MCP listening at http://{}/mcp (authentication required)",
        listener.local_addr()?
    );
    axum::serve(listener, http::router(tools, &config))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}
