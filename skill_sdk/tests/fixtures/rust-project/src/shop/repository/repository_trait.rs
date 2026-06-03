use crate::shop::models::Order;

/// Repository trait for persisting orders.
pub trait Repository: Send + Sync {
    fn save(&self, order: &Order) -> bool;
    fn find_by_id(&self, order_id: &str) -> Option<Order>;
}
