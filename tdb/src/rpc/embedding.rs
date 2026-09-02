use std::time::Duration;

use reqwest::Client;
use serde::Deserialize;

use crate::rpc::gateway_backend::GatewayBackendError;

#[derive(Debug, Clone)]
pub struct EmbeddingConfig {
    pub enabled: bool,
    pub base_url: Option<String>,
    pub api_key: Option<String>,
    pub model: String,
    pub timeout_ms: u64,
    pub max_chars: usize,
    pub strict: bool,
}

impl EmbeddingConfig {
    /// Build config from environment variables plus hardcoded defaults.
    /// Backend-specific env vars win over shared TDB_EMBED_* defaults.
    pub fn from_env() -> Self {
        let timeout_secs =
            read_positive_f64_any(&["TDB_BACKEND_EMBED_TIMEOUT_SECS", "TDB_EMBED_TIMEOUT_SECS"])
                .unwrap_or(120.0);

        Self {
            enabled: read_bool_any(&["TDB_BACKEND_ENABLE_PGVECTOR", "TDB_ENABLE_PGVECTOR"])
                .unwrap_or(true),
            base_url: read_string_any(&[
                "TDB_BACKEND_EMBED_BASE_URL",
                "TDB_EMBED_BASE_URL",
                "OPENAI_BASE_URL",
            ])
            .map(|v| v.trim().to_string())
            .filter(|v| !v.is_empty()),
            api_key: read_string_any(&[
                "TDB_BACKEND_EMBED_API_KEY",
                "TDB_EMBED_API_KEY",
                "OPENAI_API_KEY",
            ])
            .map(|v| v.trim().to_string())
            .filter(|v| !v.is_empty()),
            model: read_string_any(&["TDB_BACKEND_EMBED_MODEL", "TDB_EMBED_MODEL"])
                .filter(|v| !v.is_empty())
                .unwrap_or_else(|| "qwen3-embedding:8b".into()),
            timeout_ms: (timeout_secs * 1000.0).round() as u64,
            max_chars: read_positive_usize_any(&[
                "TDB_BACKEND_VECTOR_DOC_MAX_CHARS",
                "TDB_VECTOR_DOC_MAX_CHARS",
            ])
            .unwrap_or(1000),
            strict: read_bool_any(&["TDB_BACKEND_EMBED_STRICT", "TDB_EMBED_STRICT"])
                .unwrap_or(true),
        }
    }
}

#[derive(Clone)]
pub struct EmbeddingClient {
    http: Client,
    config: EmbeddingConfig,
}

impl EmbeddingClient {
    pub fn new(config: EmbeddingConfig) -> Self {
        Self {
            http: Client::new(),
            config,
        }
    }

    pub fn model(&self) -> &str {
        &self.config.model
    }

    pub async fn generate(
        &self,
        query_text: &str,
    ) -> Result<Option<Vec<f64>>, GatewayBackendError> {
        if !self.config.enabled {
            return Ok(None);
        }

        let (base_url, api_key) = match (&self.config.base_url, &self.config.api_key) {
            (Some(base_url), Some(api_key)) => (base_url, api_key),
            _ if self.config.strict => {
                return Err(GatewayBackendError::internal(
                    "Embedding is enabled but baseUrl/apiKey is missing",
                ));
            }
            _ => return Ok(None),
        };

        let input = query_text
            .chars()
            .take(self.config.max_chars)
            .collect::<String>();
        let response = self
            .http
            .post(format!("{}/embeddings", base_url.trim_end_matches('/')))
            .bearer_auth(api_key)
            .json(&serde_json::json!({
                "model": self.config.model,
                "input": [input],
            }))
            .timeout(Duration::from_millis(self.config.timeout_ms))
            .send()
            .await
            .map_err(|err| {
                if self.config.strict {
                    GatewayBackendError::internal(format!("Embedding request failed: {err}"))
                } else {
                    GatewayBackendError::embedding_disabled()
                }
            })?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return if self.config.strict {
                Err(GatewayBackendError::internal(format!(
                    "Embedding request failed: status={status} body={body}"
                )))
            } else {
                Ok(None)
            };
        }

        let payload: EmbeddingResponse = response.json().await.map_err(|err| {
            if self.config.strict {
                GatewayBackendError::internal(format!("Embedding response decode failed: {err}"))
            } else {
                GatewayBackendError::embedding_disabled()
            }
        })?;

        let embedding = payload
            .data
            .into_iter()
            .next()
            .and_then(|item| item.embedding);
        if embedding
            .as_ref()
            .map(|values| values.is_empty())
            .unwrap_or(true)
        {
            return if self.config.strict {
                Err(GatewayBackendError::internal(
                    "Embedding response is missing vector",
                ))
            } else {
                Ok(None)
            };
        }

        Ok(embedding)
    }
}

#[derive(Debug, Deserialize)]
struct EmbeddingResponse {
    #[serde(default)]
    data: Vec<EmbeddingItem>,
}

#[derive(Debug, Deserialize)]
struct EmbeddingItem {
    embedding: Option<Vec<f64>>,
}

fn read_string_any(keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        std::env::var(key)
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    })
}

fn read_bool_any(keys: &[&str]) -> Option<bool> {
    keys.iter().find_map(|key| read_bool(key))
}

fn read_positive_usize_any(keys: &[&str]) -> Option<usize> {
    keys.iter().find_map(|key| read_positive_usize(key))
}

fn read_positive_f64_any(keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|key| read_positive_f64(key))
}

fn read_bool(key: &str) -> Option<bool> {
    std::env::var(key)
        .ok()
        .and_then(|value| match value.trim().to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Some(true),
            "0" | "false" | "no" | "off" => Some(false),
            _ => None,
        })
}

fn read_positive_usize(key: &str) -> Option<usize> {
    std::env::var(key)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
}

fn read_positive_f64(key: &str) -> Option<f64> {
    std::env::var(key)
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .filter(|value| *value > 0.0)
}
