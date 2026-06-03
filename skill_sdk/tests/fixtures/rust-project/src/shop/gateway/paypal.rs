use crate::shop::gateway::payment_gateway::{PaymentGateway, PaymentResult};

pub struct PayPalGateway {
    client_id: String,
}

impl PayPalGateway {
    pub fn new(client_id: String) -> Self {
        Self { client_id }
    }
}

impl PaymentGateway for PayPalGateway {
    fn charge(&self, amount: f64, order_id: &str) -> PaymentResult {
        PaymentResult {
            success: true,
            transaction_id: format!("PP_{}_{}", order_id, (amount * 100.0) as i64),
            message: format!("charged {:.2} via PayPal", amount),
        }
    }
}
