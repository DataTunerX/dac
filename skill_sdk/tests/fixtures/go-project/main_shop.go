package main

import (
	"fmt"

	"example.com/fixture/shop"
)

func init() {
	_ = demoShopRun()
}

// demoShopRun wires and exercises the e-commerce subpackage so gopls indexes
// all symbols, references, and call chains across the shop/ tree.
func demoShopRun() string {
	// --- seed repository ---
	repo := shop.NewInMemoryRepository()
	gateway := shop.NewStripeGateway("sk_test_fixture")

	laptop := &shop.Product{SKU: "LAP-001", Name: "Laptop Pro", Price: 1299.99, Category: "electronics", Stock: 10}
	mouse := &shop.Product{SKU: "MOU-001", Name: "Wireless Mouse", Price: 29.99, Category: "electronics", Stock: 50}

	// --- cart ---
	cart := &shop.Cart{UserID: "user_fixture_001"}
	cart.AddProduct(laptop, 1)
	cart.AddProduct(mouse, 2)

	discount := shop.NewPercentageDiscount(10)

	svc := shop.NewOrderService(repo, gateway, []shop.DiscountStrategy{discount})
	order, err := svc.PlaceOrder(cart, "ORD-0001")
	if err != nil {
		return fmt.Sprintf("error: %v", err)
	}

	result := fmt.Sprintf("[done] order=%s total=%.2f status=%d", order.OrderID, order.RawTotal(), order.Status)
	return result
}
