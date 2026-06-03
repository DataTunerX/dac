/// DataProcessor trait defines the contract for data processing.
///
/// goToDefinition on DataProcessor should resolve here.
/// findReferences on DataProcessor should find all usages across core/ and shop/.
/// goToImplementation on DataProcessor should resolve to DefaultProcessor.
pub trait DataProcessor: Send + Sync {
    /// Process applies the data processing pipeline.
    /// hover on Process should show this documentation comment.
    fn process(&self, data: &str) -> Result<String, String>;

    /// Validate checks whether the provided data is valid.
    fn validate(&self, data: &str) -> bool;
}
