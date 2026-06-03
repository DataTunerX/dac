package shop

import "fmt"

// PaymentResult represents the outcome of a payment attempt.
type PaymentResult struct {
	Success       bool
	TransactionID string
	Message       string
}

// PaymentGateway defines the payment processing contract.
// goToImplementation on PaymentGateway should resolve to StripeGateway, PayPalGateway, MockGateway.
type PaymentGateway interface {
	Charge(amount float64, currency string) (*PaymentResult, error)
	Refund(transactionID string) (*PaymentResult, error)
}

// StripeGateway implements PaymentGateway via Stripe.
type StripeGateway struct {
	apiKey string
}

// NewStripeGateway creates a StripeGateway.
func NewStripeGateway(apiKey string) *StripeGateway {
	return &StripeGateway{apiKey: apiKey}
}

// Charge processes a payment through Stripe.
func (g *StripeGateway) Charge(amount float64, currency string) (*PaymentResult, error) {
	return &PaymentResult{
		Success:       true,
		TransactionID: fmt.Sprintf("stripe_ch_%d", hashFloat(amount)),
		Message:       fmt.Sprintf("Charged %.2f %s", amount, currency),
	}, nil
}

// Refund processes a refund through Stripe.
func (g *StripeGateway) Refund(transactionID string) (*PaymentResult, error) {
	return &PaymentResult{
		Success:       true,
		TransactionID: fmt.Sprintf("stripe_ref_%s", transactionID),
		Message:       fmt.Sprintf("Refunded transaction %s", transactionID),
	}, nil
}

// PayPalGateway implements PaymentGateway via PayPal.
type PayPalGateway struct {
	clientID     string
	clientSecret string
}

// NewPayPalGateway creates a PayPalGateway.
func NewPayPalGateway(clientID, clientSecret string) *PayPalGateway {
	return &PayPalGateway{clientID: clientID, clientSecret: clientSecret}
}

// Charge processes a payment through PayPal.
func (g *PayPalGateway) Charge(amount float64, currency string) (*PaymentResult, error) {
	return &PaymentResult{
		Success:       true,
		TransactionID: fmt.Sprintf("pp_ch_%d", hashFloat(amount)),
		Message:       fmt.Sprintf("PayPal charge %.2f %s", amount, currency),
	}, nil
}

// Refund processes a refund through PayPal.
func (g *PayPalGateway) Refund(transactionID string) (*PaymentResult, error) {
	return &PaymentResult{
		Success:       true,
		TransactionID: fmt.Sprintf("pp_ref_%s", transactionID),
		Message:       fmt.Sprintf("PayPal refund %s", transactionID),
	}, nil
}

// MockGateway implements PaymentGateway for testing.
type MockGateway struct {
	callCount int
}

// NewMockGateway creates a MockGateway.
func NewMockGateway() *MockGateway {
	return &MockGateway{}
}

// Charge simulates a payment.
func (g *MockGateway) Charge(amount float64, currency string) (*PaymentResult, error) {
	g.callCount++
	return &PaymentResult{
		Success:       true,
		TransactionID: fmt.Sprintf("mock_tx_%d", g.callCount),
		Message:       fmt.Sprintf("Mock charge %.2f %s", amount, currency),
	}, nil
}

// Refund simulates a refund.
func (g *MockGateway) Refund(transactionID string) (*PaymentResult, error) {
	return &PaymentResult{
		Success:       true,
		TransactionID: fmt.Sprintf("mock_ref_%s", transactionID),
		Message:       fmt.Sprintf("Mock refund %s", transactionID),
	}, nil
}

func hashFloat(f float64) int {
	return int(f * 100)
}
