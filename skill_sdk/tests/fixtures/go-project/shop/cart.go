package shop

import "time"

// Cart is a transient shopping cart before conversion to an Order.
type Cart struct {
	UserID string
	Items  []OrderItem
}

// AddProduct adds a product to the cart.
func (c *Cart) AddProduct(product *Product, quantity int) {
	c.Items = append(c.Items, OrderItem{
		Product:   product,
		Quantity:  quantity,
		UnitPrice: product.Price,
	})
}

// RemoveItem removes an item by index.
func (c *Cart) RemoveItem(index int) {
	if index >= 0 && index < len(c.Items) {
		c.Items = append(c.Items[:index], c.Items[index+1:]...)
	}
}

// CartTotal returns the sum of item subtotals.
func (c *Cart) CartTotal() float64 {
	var total float64
	for _, item := range c.Items {
		total += item.Subtotal()
	}
	return total
}

// ToOrder converts the cart to an Order entity.
func (c *Cart) ToOrder(orderID, discountCode string) *Order {
	items := make([]OrderItem, len(c.Items))
	copy(items, c.Items)
	return &Order{
		OrderID:      orderID,
		UserID:       c.UserID,
		Items:        items,
		Status:       StatusPending,
		CreatedAt:    time.Now(),
		DiscountCode: discountCode,
	}
}

// Checkout runs the full checkout pipeline.
// This is the call-hierarchy centrepiece — outgoingCalls on Checkout should
// list ToOrder, discount.Apply, gateway.Charge, repo.SaveOrder, repo.UpdateOrderStatus.
func (c *Cart) Checkout(
	orderID string,
	repo Repository,
	gateway PaymentGateway,
	discount DiscountStrategy,
) (*Order, error) {
	order := c.ToOrder(orderID, "")

	finalAmount := order.RawTotal()
	if discount != nil {
		finalAmount = discount.Apply(order)
	}

	result, err := gateway.Charge(finalAmount, "USD")
	if err != nil {
		return nil, err
	}
	if result.Success {
		order.Status = StatusPaid
	}

	if err := repo.SaveOrder(order); err != nil {
		return nil, err
	}
	if err := repo.UpdateOrderStatus(order.OrderID, order.Status); err != nil {
		return nil, err
	}
	return order, nil
}
