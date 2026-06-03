use crate::shop::discount::discount_strategy::DiscountStrategy;

/// BogoDiscount applies a buy-one-get-one-free on every other application.
pub struct BogoDiscount {
    apply_count: u32,
}

impl BogoDiscount {
    pub fn new() -> Self {
        Self { apply_count: 0 }
    }
}

impl DiscountStrategy for BogoDiscount {
    fn apply(&self, total: f64) -> f64 {
        if self.apply_count % 2 == 0 {
            total / 2.0
        } else {
            total
        }
    }
}
