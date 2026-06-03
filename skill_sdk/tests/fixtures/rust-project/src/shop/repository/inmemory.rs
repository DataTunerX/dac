use crate::shop::models::Order;
use crate::shop::repository::repository_trait::Repository;

use std::sync::Mutex;

pub struct InMemoryRepository {
    orders: Mutex<Vec<Order>>,
}

impl InMemoryRepository {
    pub fn new() -> Self {
        Self {
            orders: Mutex::new(Vec::new()),
        }
    }
}

impl Repository for InMemoryRepository {
    fn save(&self, order: &Order) -> bool {
        let mut orders = self.orders.lock().unwrap();
        orders.push(order.clone());
        true
    }

    fn find_by_id(&self, order_id: &str) -> Option<Order> {
        let orders = self.orders.lock().unwrap();
        orders.iter().find(|o| o.order_id == order_id).cloned()
    }
}
