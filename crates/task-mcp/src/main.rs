use rmcp::{transport::stdio, ServiceExt};
use task_core::TaskStore;
use task_mcp::TaskTools;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // stdout belongs exclusively to MCP JSON-RPC.
    let store = TaskStore::open_default().await?;
    let require_key = std::env::args()
        .skip(1)
        .any(|arg| arg == "--require-request-key");
    let service = TaskTools::from_env(store, require_key)?
        .serve(stdio())
        .await?;
    service.waiting().await?;
    Ok(())
}
