use crate::core::data_processor::DataProcessor;
use crate::core::finalize_output::finalize_output;

/// Helper bridges the processor with external systems.
///
/// goToDefinition from handler.rs NewHelper call resolves here.
pub struct Helper<'a> {
    processor: &'a dyn DataProcessor,
}

impl<'a> Helper<'a> {
    /// HandleRequest processes a request through the pipeline.
    ///
    /// outgoingCalls on HandleRequest shows calls to validate, process, finalize_output.
    pub fn handle_request(&self, input: &str) -> String {
        if !self.processor.validate(input) {
            return format!("validation failed for: {}", input);
        }

        match self.processor.process(input) {
            Ok(raw) => finalize_output(&raw),
            Err(e) => format!("process error: {}", e),
        }
    }
}

/// NewHelper creates a helper bound to a processor.
///
/// goToDefinition from handler.rs call site resolves to this function.
pub fn new_helper(processor: &dyn DataProcessor) -> Helper {
    Helper { processor }
}
