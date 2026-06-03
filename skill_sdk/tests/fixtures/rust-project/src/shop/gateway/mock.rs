use crate::shop::gateway::payment_gateway::{PaymentGateway, PaymentResult};

pub struct MockGateway {
    should_succeed: bool,
}

impl MockGateway {
    pub fn new(should_succeed: bool) -> Self {
        Self { should_succeed }
    }
}

impl PaymentGateway for MockGateway {
    fn charge(&self, amount: f64, order_id: &str) -> PaymentResult {
        PaymentResult {
            success: self.should_succeed,
            transaction_id: format!("MOCK_{}", order_id),
            message: if self.should_succeed {
                "mock success".to_string()
            } else {
                "mock failure".to_string()
            },
        }
    }
}
