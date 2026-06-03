use fixture::core::default_processor::DefaultProcessor;
use fixture::core::handler::Handler;

use fixture::shop::cart::Cart;
use fixture::shop::discount::PercentageDiscount;
use fixture::shop::discount::FixedAmountDiscount;
use fixture::shop::discount::BogoDiscount;
use fixture::shop::gateway::StripeGateway;
use fixture::shop::models::Product;
use fixture::shop::repository::InMemoryRepository;
use fixture::shop::service::OrderService;

/// demo_core_run exercises core module symbols.
fn demo_core_run() {
    let proc = Box::new(DefaultProcessor::new());
    let handler = Handler::new(proc);
    let result = handler.process_request("hello");
    println!("Core demo: {}", result);

    let mut dp = DefaultProcessor::new();
    dp.configure_retries(5);
    println!("retries={}", dp.config().retries);
}

/// demo_shop_run exercises shop module symbols, triggering cross-module lookups.
fn demo_shop_run() {
    let laptop = Product {
        id: "LAP-001".into(),
        name: "Laptop Pro".into(),
        price: 1299.99,
        category: "electronics".into(),
        stock: 10,
    };
    let mouse = Product {
        id: "MOU-001".into(),
        name: "Wireless Mouse".into(),
        price: 29.99,
        category: "electronics".into(),
        stock: 50,
    };

    let mut cart = Cart::new("user_fixture_001".into());
    cart.add_product(laptop.clone(), 1);
    cart.add_product(mouse.clone(), 2);

    let pct = PercentageDiscount::new(10.0);
    let bogo = BogoDiscount::new();
    let flat = FixedAmountDiscount::new(5.0);

    let repo = InMemoryRepository::new();
    let gateway = StripeGateway::new("sk_test_fixture".into());

    let svc: OrderService<_, _> = OrderService::new(
        repo,
        gateway,
        vec![Box::new(pct), Box::new(bogo), Box::new(flat)],
    );

    let order = svc.place_order(cart, "ORD-0001".into());
    println!(
        "[done] order={} total={:.2} status={:?}",
        order.order_id, order.raw_total(), order.status
    );
}

fn main() {
    demo_core_run();
    demo_shop_run();
}
