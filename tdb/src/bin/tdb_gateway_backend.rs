use std::net::SocketAddr;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    dotenvy::dotenv().ok();

    let addr: SocketAddr = std::env::var("TDB_GATEWAY_BACKEND_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:50051".to_string())
        .parse()?;
    let database_url = std::env::var("DATABASE_URL").expect("DATABASE_URL must be set");
    let config = tdb::rpc::gateway_backend::GatewayBackendConfig::load()?;
    eprintln!(
        "[tdb_gateway_backend] listening_on={} {}",
        addr,
        config.embedding_startup_summary()
    );
    let service =
        tdb::rpc::gateway_backend::GatewayBackendService::from_config(&database_url, config)
            .await?;

    tdb::rpc::gateway_backend::serve_with_service(addr, service).await
}
