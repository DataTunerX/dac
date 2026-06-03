package shop

// OrderService orchestrates the checkout flow — top-level entry point for incomingCalls.
type OrderService struct {
	Repo       Repository
	Gateway    PaymentGateway
	Strategies []DiscountStrategy
}

// NewOrderService creates an OrderService.
func NewOrderService(repo Repository, gateway PaymentGateway, strategies []DiscountStrategy) *OrderService {
	return &OrderService{
		Repo:       repo,
		Gateway:    gateway,
		Strategies: strategies,
	}
}

// PlaceOrder runs the full order flow — outgoingCalls target.
// Calls: cart.ToOrder, ApplyBestDiscount, cart.Checkout
func (s *OrderService) PlaceOrder(cart *Cart, orderID string) (*Order, error) {
	if len(s.Strategies) > 0 {
		order := cart.ToOrder(orderID, "")
		ApplyBestDiscount(order, s.Strategies)
		return cart.Checkout(orderID, s.Repo, s.Gateway, s.Strategies[0])
	}
	return cart.Checkout(orderID, s.Repo, s.Gateway, nil)
}

// CancelOrder cancels an order and updates its status.
// Calls: repo.GetOrder, repo.UpdateOrderStatus
func (s *OrderService) CancelOrder(orderID string) error {
	order, err := s.Repo.GetOrder(orderID)
	if err != nil || order == nil {
		return err
	}
	order.Status = StatusCancelled
	return s.Repo.UpdateOrderStatus(orderID, StatusCancelled)
}
