/// ProcessorConfig holds configuration for data processors.
#[derive(Debug, Clone)]
pub struct ProcessorConfig {
    pub timeout: u32,
    pub retries: u32,
}

impl Default for ProcessorConfig {
    fn default() -> Self {
        Self {
            timeout: 30,
            retries: 3,
        }
    }
}
