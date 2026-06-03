package shop

// Repository defines the storage contract.
// goToImplementation on Repository should resolve to InMemoryRepository and PostgresRepository.
type Repository interface {
	SaveOrder(order *Order) error
	GetOrder(orderID string) (*Order, error)
	UpdateOrderStatus(orderID string, status OrderStatus) error
	GetProduct(sku string) (*Product, error)
	ListOrdersByUser(userID string) ([]*Order, error)
}

// InMemoryRepository is an in-memory implementation of Repository.
type InMemoryRepository struct {
	orders   map[string]*Order
	products map[string]*Product
}

// NewInMemoryRepository creates a new InMemoryRepository.
func NewInMemoryRepository() *InMemoryRepository {
	return &InMemoryRepository{
		orders:   make(map[string]*Order),
		products: make(map[string]*Product),
	}
}

// SaveOrder stores an order in memory.
func (r *InMemoryRepository) SaveOrder(order *Order) error {
	r.orders[order.OrderID] = order
	return nil
}

// GetOrder retrieves an order by ID.
func (r *InMemoryRepository) GetOrder(orderID string) (*Order, error) {
	order, ok := r.orders[orderID]
	if !ok {
		return nil, nil
	}
	return order, nil
}

// UpdateOrderStatus updates the status of an order.
func (r *InMemoryRepository) UpdateOrderStatus(orderID string, status OrderStatus) error {
	order, ok := r.orders[orderID]
	if !ok {
		return nil
	}
	order.Status = status
	return nil
}

// GetProduct retrieves a product by SKU.
func (r *InMemoryRepository) GetProduct(sku string) (*Product, error) {
	p, ok := r.products[sku]
	if !ok {
		return nil, nil
	}
	return p, nil
}

// ListOrdersByUser returns all orders for a given user.
func (r *InMemoryRepository) ListOrdersByUser(userID string) ([]*Order, error) {
	var result []*Order
	for _, order := range r.orders {
		if order.UserID == userID {
			result = append(result, order)
		}
	}
	return result, nil
}

// PostgresRepository is a simulated postgres-backed implementation.
type PostgresRepository struct {
	connStr  string
	orders   map[string]*Order
	products map[string]*Product
}

// NewPostgresRepository creates a new PostgresRepository.
func NewPostgresRepository(connStr string) *PostgresRepository {
	return &PostgresRepository{
		connStr:  connStr,
		orders:   make(map[string]*Order),
		products: make(map[string]*Product),
	}
}

// SaveOrder stores an order.
func (r *PostgresRepository) SaveOrder(order *Order) error {
	r.orders[order.OrderID] = order
	return nil
}

// GetOrder retrieves an order by ID.
func (r *PostgresRepository) GetOrder(orderID string) (*Order, error) {
	order, ok := r.orders[orderID]
	if !ok {
		return nil, nil
	}
	return order, nil
}

// UpdateOrderStatus updates order status.
func (r *PostgresRepository) UpdateOrderStatus(orderID string, status OrderStatus) error {
	order, ok := r.orders[orderID]
	if !ok {
		return nil
	}
	order.Status = status
	return nil
}

// GetProduct retrieves a product by SKU.
func (r *PostgresRepository) GetProduct(sku string) (*Product, error) {
	p, ok := r.products[sku]
	if !ok {
		return nil, nil
	}
	return p, nil
}

// ListOrdersByUser returns orders for a user.
func (r *PostgresRepository) ListOrdersByUser(userID string) ([]*Order, error) {
	var result []*Order
	for _, order := range r.orders {
		if order.UserID == userID {
			result = append(result, order)
		}
	}
	return result, nil
}
