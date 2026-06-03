package shop

import "math"

// DiscountStrategy is the contract for pluggable discount calculation.
// findReferences on DiscountStrategy should locate all implementors: PercentageDiscount,
// FixedAmountDiscount, BogoDiscount.
type DiscountStrategy interface {
	Apply(order *Order) float64
}

// PercentageDiscount applies a percentage off the raw total.
type PercentageDiscount struct {
	Percent float64
}

// NewPercentageDiscount creates a PercentageDiscount.
func NewPercentageDiscount(percent float64) *PercentageDiscount {
	return &PercentageDiscount{Percent: percent}
}

// Apply subtracts the percentage from the total.
func (d *PercentageDiscount) Apply(order *Order) float64 {
	return order.RawTotal() * (1.0 - d.Percent/100.0)
}

// FixedAmountDiscount subtracts a fixed amount (floored at zero).
type FixedAmountDiscount struct {
	Amount float64
}

// NewFixedAmountDiscount creates a FixedAmountDiscount.
func NewFixedAmountDiscount(amount float64) *FixedAmountDiscount {
	return &FixedAmountDiscount{Amount: amount}
}

// Apply subtracts the fixed amount.
func (d *FixedAmountDiscount) Apply(order *Order) float64 {
	return math.Max(0, order.RawTotal()-d.Amount)
}

// BogoDiscount gives the cheapest item free.
type BogoDiscount struct{}

// Apply makes the cheapest item free.
func (d *BogoDiscount) Apply(order *Order) float64 {
	if len(order.Items) < 2 {
		return order.RawTotal()
	}
	cheapest := order.Items[0].Subtotal()
	for _, item := range order.Items[1:] {
		if s := item.Subtotal(); s < cheapest {
			cheapest = s
		}
	}
	return order.RawTotal() - cheapest
}

// ApplyBestDiscount tries several strategies and returns the lowest price.
func ApplyBestDiscount(order *Order, strategies []DiscountStrategy) float64 {
	best := order.RawTotal()
	for _, s := range strategies {
		if v := s.Apply(order); v < best {
			best = v
		}
	}
	return best
}
