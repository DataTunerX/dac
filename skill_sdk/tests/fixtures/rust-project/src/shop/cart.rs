use crate::shop::models::{OrderItem, Product};

/// Shopping cart abstraction.
///
/// goToDefinition on Cart resolves here.
/// findReferences on Cart finds usages in main.rs and service.rs.
pub struct Cart {
    user_id: String,
    items: Vec<OrderItem>,
}

impl Cart {
    pub fn new(user_id: String) -> Self {
        Self {
            user_id,
            items: Vec::new(),
        }
    }

    pub fn add_product(&mut self, product: Product, quantity: u32) {
        self.items.push(OrderItem { product, quantity });
    }

    pub fn raw_total(&self) -> f64 {
        self.items
            .iter()
            .map(|item| item.product.price * item.quantity as f64)
            .sum()
    }

    pub fn items(&self) -> &[OrderItem] {
        &self.items
    }
}
