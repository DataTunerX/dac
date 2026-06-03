use crate::shop::discount::discount_strategy::DiscountStrategy;

/// FixedAmountDiscount subtracts a fixed dollar amount from the total.
pub struct FixedAmountDiscount {
    amount: f64,
}

impl FixedAmountDiscount {
    pub fn new(amount: f64) -> Self {
        Self { amount }
    }
}

impl DiscountStrategy for FixedAmountDiscount {
    fn apply(&self, total: f64) -> f64 {
        let result = total - self.amount;
        if result > 0.0 { result } else { 0.0 }
    }
}
