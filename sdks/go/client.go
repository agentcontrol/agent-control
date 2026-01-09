package agentcontrol

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

const (
	// DefaultBaseURL is the default Agent Control server URL.
	DefaultBaseURL = "http://localhost:8000"

	// DefaultTimeout is the default request timeout.
	DefaultTimeout = 30 * time.Second

	// APIKeyEnvVar is the environment variable name for the API key.
	APIKeyEnvVar = "AGENT_CONTROL_API_KEY"
)

// Client is the Agent Control HTTP client.
type Client struct {
	baseURL    string
	httpClient *http.Client
	apiKey     string
}

// ClientOption configures the Client.
type ClientOption func(*Client)

// WithBaseURL sets the base URL for the client.
func WithBaseURL(url string) ClientOption {
	return func(c *Client) {
		c.baseURL = url
	}
}

// WithTimeout sets the request timeout.
func WithTimeout(timeout time.Duration) ClientOption {
	return func(c *Client) {
		c.httpClient.Timeout = timeout
	}
}

// WithAPIKey sets the API key for authentication.
func WithAPIKey(key string) ClientOption {
	return func(c *Client) {
		c.apiKey = key
	}
}

// WithHTTPClient sets a custom HTTP client.
func WithHTTPClient(client *http.Client) ClientOption {
	return func(c *Client) {
		c.httpClient = client
	}
}

// NewClient creates a new Agent Control client.
//
// By default, it uses:
//   - Base URL: http://localhost:8000
//   - Timeout: 30 seconds
//   - API key from AGENT_CONTROL_API_KEY environment variable (if set)
//
// Example:
//
//	client := agentcontrol.NewClient()
//	client := agentcontrol.NewClient(agentcontrol.WithBaseURL("https://api.example.com"))
//	client := agentcontrol.NewClient(agentcontrol.WithAPIKey("my-api-key"))
func NewClient(opts ...ClientOption) *Client {
	c := &Client{
		baseURL:    DefaultBaseURL,
		httpClient: &http.Client{Timeout: DefaultTimeout},
		apiKey:     os.Getenv(APIKeyEnvVar),
	}

	for _, opt := range opts {
		opt(c)
	}

	return c
}

// doRequest performs an HTTP request and decodes the JSON response.
func (c *Client) doRequest(ctx context.Context, method, path string, body interface{}, result interface{}) error {
	var bodyReader io.Reader
	if body != nil {
		jsonBody, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("failed to marshal request body: %w", err)
		}
		bodyReader = bytes.NewReader(jsonBody)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, bodyReader)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("X-API-Key", c.apiKey)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode >= 400 {
		return &APIError{
			StatusCode: resp.StatusCode,
			Message:    string(respBody),
		}
	}

	if result != nil && len(respBody) > 0 {
		if err := json.Unmarshal(respBody, result); err != nil {
			return fmt.Errorf("failed to decode response: %w", err)
		}
	}

	return nil
}

// HealthCheck verifies the server is healthy.
func (c *Client) HealthCheck(ctx context.Context) (*HealthResponse, error) {
	var result HealthResponse
	if err := c.doRequest(ctx, http.MethodGet, "/health", nil, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

// APIError represents an error response from the API.
type APIError struct {
	StatusCode int
	Message    string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("agent-control API error (status %d): %s", e.StatusCode, e.Message)
}

// IsNotFound returns true if the error is a 404 Not Found.
func (e *APIError) IsNotFound() bool {
	return e.StatusCode == http.StatusNotFound
}

// IsBadRequest returns true if the error is a 400 Bad Request.
func (e *APIError) IsBadRequest() bool {
	return e.StatusCode == http.StatusBadRequest
}

// IsUnprocessable returns true if the error is a 422 Unprocessable Entity.
func (e *APIError) IsUnprocessable() bool {
	return e.StatusCode == http.StatusUnprocessableEntity
}
