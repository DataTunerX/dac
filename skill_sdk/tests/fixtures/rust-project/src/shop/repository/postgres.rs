use crate::shop::models::Order;
use crate::shop::repository::repository_trait::Repository;

pub struct PostgresRepository {
    conn_string: String,
}

impl PostgresRepository {
    pub fn new(conn_string: String) -> Self {
        Self { conn_string }
    }
}

impl Repository for PostgresRepository {
    fn save(&self, order: &Order) -> bool {
        println!("[PG] saving order {} via {}", order.order_id, self.conn_string);
        true
    }

    fn find_by_id(&self, _order_id: &str) -> Option<Order> {
        None
    }
}
