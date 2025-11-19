package types

// LoginRequest represents the login request payload
type LoginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// User represents user information
type User struct {
	ID          string  `json:"id"`
	Username    string  `json:"username"`
	LastLoginAt *string `json:"last_login_at,omitempty"`
	CreatedAt   string  `json:"created_at"`
}

// LoginData represents the data returned after successful login
type LoginData struct {
	Token  string `json:"token"`
	Expire string `json:"expire"`
	User   *User  `json:"user"`
}
