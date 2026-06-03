/// DiscountStrategy trait for applying discounts.
///
/// goToImplementation on DiscountStrategy finds all implementations.
pub trait DiscountStrategy: Send + Sync {
    fn apply(&self, total: f64) -> f64;
}
