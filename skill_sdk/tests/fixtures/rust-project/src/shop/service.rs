use crate::shop::cart::Cart;
use crate::shop::discount::discount_strategy::DiscountStrategy;
use crate::shop::gateway::payment_gateway::PaymentGateway;
use crate::shop::models::{Order, OrderStatus};
use crate::shop::repository::repository_trait::Repository;

/// OrderService handles order placement.
///
/// PlaceOrder is the main entry point for order creation.
/// outgoingCalls on place_order reveals: save → charge → discount.apply
pub struct OrderService<R: Repository, G: PaymentGateway> {
    repo: R,
    gateway: G,
    discounts: Vec<Box<dyn DiscountStrategy>>,
}

impl<R: Repository, G: PaymentGateway> OrderService<R, G> {
    pub fn new(repo: R, gateway: G, discounts: Vec<Box<dyn DiscountStrategy>>) -> Self {
        Self {
            repo,
            gateway,
            discounts,
        }
    }

    pub fn place_order(&self, cart: Cart, order_id: String) -> Order {
        let mut order = Order {
            order_id: order_id.clone(),
            items: cart.items().to_vec(),
            status: OrderStatus::Pending,
            raw_total_value: 0.0,
        };

        let mut total = cart.raw_total();

        for d in &self.discounts {
            total = d.apply(total);
        }
        order.raw_total_value = total;

        let payment = self.gateway.charge(total, &order_id);
        if payment.success {
            order.status = OrderStatus::Confirmed;
            println!("Payment OK: {}", payment.transaction_id);
        } else {
            order.status = OrderStatus::Cancelled;
            println!("Payment FAILED: {}", payment.message);
        }

        if !self.repo.save(&order) {
            order.status = OrderStatus::Cancelled;
        }

        order
    }
}
