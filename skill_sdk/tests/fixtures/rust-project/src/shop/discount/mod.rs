pub mod discount_strategy;
pub mod percentage;
pub mod fixed_amount;
pub mod bogo;

pub use discount_strategy::DiscountStrategy;
pub use percentage::PercentageDiscount;
pub use fixed_amount::FixedAmountDiscount;
pub use bogo::BogoDiscount;
