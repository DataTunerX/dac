use crate::shop::discount::discount_strategy::DiscountStrategy;

/// PercentageDiscount applies a percentage-off reduction to the total.
///
/// hover docs: reduces the total by the configured percentage.
pub struct PercentageDiscount {
    percentage: f64,
}

impl PercentageDiscount {
    pub fn new(percentage: f64) -> Self {
        Self { percentage }
    }
}

impl DiscountStrategy for PercentageDiscount {
    fn apply(&self, total: f64) -> f64 {
        total * (1.0 - self.percentage / 100.0)
    }
}
