package shop

import "time"

// OrderStatus represents possible states for an order.
type OrderStatus int

const (
	StatusPending   OrderStatus = iota
	StatusPaid
	StatusShipped
	StatusDelivered
	StatusCancelled
)

// Product represents an item available for purchase.
type Product struct {
	SKU      string
	Name     string
	Price    float64
	Category string
	Stock    int
}

// IsInStock checks whether the product has available inventory.
func (p *Product) IsInStock() bool {
	return p.Stock > 0
}

// OrderItem is a single line item within an order.
type OrderItem struct {
	Product   *Product
	Quantity  int
	UnitPrice float64
}

// Subtotal returns the line-item total.
func (i *OrderItem) Subtotal() float64 {
	return i.UnitPrice * float64(i.Quantity)
}

// Order is a customer order.
type Order struct {
	OrderID      string
	UserID       string
	Items        []OrderItem
	Status       OrderStatus
	CreatedAt    time.Time
	DiscountCode string
}

// RawTotal sums all item subtotals before discounts.
func (o *Order) RawTotal() float64 {
	var total float64
	for _, item := range o.Items {
		total += item.Subtotal()
	}
	return total
}

// ApplyDiscount returns the discounted total.
func (o *Order) ApplyDiscount(multiplier float64) float64 {
	return o.RawTotal() * multiplier
}
