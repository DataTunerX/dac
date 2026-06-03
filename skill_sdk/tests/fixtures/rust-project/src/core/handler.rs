use crate::core::data_processor::DataProcessor;
use crate::core::helper::new_helper;

/// Handler processes incoming API requests.
///
/// Cross-file: process_request calls new_helper → handle_request.
/// goToDefinition on NewHelper from handler call resolves to helper.rs.
pub struct Handler {
    processor: Box<dyn DataProcessor>,
}

impl Handler {
    pub fn new(processor: Box<dyn DataProcessor>) -> Self {
        Self { processor }
    }

    /// ProcessRequest handles an API request end-to-end.
    /// Calls new_helper then handle_request.
    pub fn process_request(&self, payload: &str) -> String {
        println!("Processing request: {}", payload);

        let helper = new_helper(&*self.processor);
        helper.handle_request(payload)
    }

    /// HealthCheck reports the handler health status.
    pub fn health_check(&self) -> bool {
        true
    }
}
