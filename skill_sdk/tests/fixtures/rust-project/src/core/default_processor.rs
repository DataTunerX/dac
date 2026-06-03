use crate::core::data_processor::DataProcessor;
use crate::core::processor_config::ProcessorConfig;

/// DefaultProcessor is the primary implementation of DataProcessor.
///
/// goToImplementation on DataProcessor should list this struct.
pub struct DefaultProcessor {
    config: ProcessorConfig,
}

impl DefaultProcessor {
    pub fn new() -> Self {
        Self {
            config: ProcessorConfig::default(),
        }
    }

    pub fn with_config(config: ProcessorConfig) -> Self {
        Self { config }
    }

    pub fn configure_retries(&mut self, retries: u32) {
        self.config.retries = retries;
    }

    pub fn config(&self) -> &ProcessorConfig {
        &self.config
    }

    fn transform_data(&self, data: &str) -> String {
        format!("processed: {}", data)
    }
}

impl DataProcessor for DefaultProcessor {
    fn process(&self, data: &str) -> Result<String, String> {
        if !self.validate(data) {
            return Err(format!("invalid data: {}", data));
        }
        Ok(self.transform_data(data))
    }

    fn validate(&self, data: &str) -> bool {
        !data.is_empty() && data.len() < 1024
    }
}
