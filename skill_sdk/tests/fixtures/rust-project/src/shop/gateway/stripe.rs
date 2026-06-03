use crate::shop::gateway::payment_gateway::{PaymentGateway, PaymentResult};

pub struct StripeGateway {
    api_key: String,
}

impl StripeGateway {
    pub fn new(api_key: String) -> Self {
        Self { api_key }
    }
}

impl PaymentGateway for StripeGateway {
    fn charge(&self, amount: f64, order_id: &str) -> PaymentResult {
        PaymentResult {
            success: true,
            transaction_id: format!("ch_stripe_{}_{}", order_id, (amount * 100.0) as i64),
            message: format!("charged {:.2} via Stripe (key={}...)", amount, &self.api_key[..8.min(self.api_key.len())]),
        }
    }
}
