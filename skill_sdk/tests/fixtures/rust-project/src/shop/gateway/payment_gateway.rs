/// Payment gateway interface.
///
/// goToImplementation on PaymentGateway finds Stripe/PayPal/Mock.
#[derive(Debug, Clone)]
pub struct PaymentResult {
    pub success: bool,
    pub transaction_id: String,
    pub message: String,
}

pub trait PaymentGateway: Send + Sync {
    fn charge(&self, amount: f64, order_id: &str) -> PaymentResult;
}
