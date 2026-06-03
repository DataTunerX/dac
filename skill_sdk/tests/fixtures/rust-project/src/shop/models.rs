/// E-commerce domain models.
///
/// goToDefinition on Product/Order/OrderStatus resolves here.

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum OrderStatus {
    Pending,
    Confirmed,
    Shipped,
    Delivered,
    Cancelled,
}

impl OrderStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            OrderStatus::Pending => "pending",
            OrderStatus::Confirmed => "confirmed",
            OrderStatus::Shipped => "shipped",
            OrderStatus::Delivered => "delivered",
            OrderStatus::Cancelled => "cancelled",
        }
    }
}

#[derive(Debug, Clone)]
pub struct Product {
    pub id: String,
    pub name: String,
    pub price: f64,
    pub category: String,
    pub stock: u32,
}

#[derive(Debug, Clone)]
pub struct OrderItem {
    pub product: Product,
    pub quantity: u32,
}

#[derive(Debug, Clone)]
pub struct Order {
    pub order_id: String,
    pub items: Vec<OrderItem>,
    pub status: OrderStatus,
    pub raw_total_value: f64,
}

impl Order {
    pub fn raw_total(&self) -> f64 {
        self.raw_total_value
    }
}
