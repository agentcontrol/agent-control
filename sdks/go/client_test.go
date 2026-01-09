package agentcontrol

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestNewClient(t *testing.T) {
	// Default client
	c := NewClient()
	if c.baseURL != DefaultBaseURL {
		t.Errorf("expected baseURL %q, got %q", DefaultBaseURL, c.baseURL)
	}

	// With options
	c = NewClient(
		WithBaseURL("https://example.com"),
		WithTimeout(10*time.Second),
		WithAPIKey("test-key"),
	)
	if c.baseURL != "https://example.com" {
		t.Errorf("expected baseURL %q, got %q", "https://example.com", c.baseURL)
	}
	if c.apiKey != "test-key" {
		t.Errorf("expected apiKey %q, got %q", "test-key", c.apiKey)
	}
}

func TestHealthCheck(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/health" {
			t.Errorf("expected path /health, got %s", r.URL.Path)
		}
		json.NewEncoder(w).Encode(HealthResponse{Status: "ok"})
	}))
	defer server.Close()

	client := NewClient(WithBaseURL(server.URL))
	resp, err := client.HealthCheck(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.Status != "ok" {
		t.Errorf("expected status ok, got %s", resp.Status)
	}
}

func TestInitAgent(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents/initAgent" {
			t.Errorf("expected path /api/v1/agents/initAgent, got %s", r.URL.Path)
		}
		if r.Method != http.MethodPost {
			t.Errorf("expected POST, got %s", r.Method)
		}

		var req InitAgentRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("failed to decode request: %v", err)
		}
		if req.Agent.Name != "test-agent" {
			t.Errorf("expected agent name test-agent, got %s", req.Agent.Name)
		}

		json.NewEncoder(w).Encode(InitAgentResponse{Created: true})
	}))
	defer server.Close()

	client := NewClient(WithBaseURL(server.URL))
	agent := Agent{
		ID:   uuid.New(),
		Name: "test-agent",
	}

	resp, err := client.InitAgent(context.Background(), agent, nil, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !resp.Created {
		t.Error("expected Created to be true")
	}
}

func TestEvaluate(t *testing.T) {
	agentID := uuid.New()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/evaluation" {
			t.Errorf("expected path /api/v1/evaluation, got %s", r.URL.Path)
		}

		var req EvaluationRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("failed to decode request: %v", err)
		}
		if req.AgentUUID != agentID {
			t.Errorf("expected agent UUID %s, got %s", agentID, req.AgentUUID)
		}
		if req.CheckStage != PreCheck {
			t.Errorf("expected check stage pre, got %s", req.CheckStage)
		}

		json.NewEncoder(w).Encode(EvaluationResponse{
			IsSafe:     true,
			Confidence: 0.95,
		})
	}))
	defer server.Close()

	client := NewClient(WithBaseURL(server.URL))

	toolCall := ToolCall{
		ToolName:  "search",
		Arguments: map[string]interface{}{"query": "test"},
	}

	resp, err := client.Evaluate(context.Background(), agentID, toolCall, PreCheck)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !resp.IsSafe {
		t.Error("expected IsSafe to be true")
	}
	if resp.Confidence != 0.95 {
		t.Errorf("expected confidence 0.95, got %f", resp.Confidence)
	}
}

func TestAPIError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte(`{"detail": "Agent not found"}`))
	}))
	defer server.Close()

	client := NewClient(WithBaseURL(server.URL))
	_, err := client.GetAgent(context.Background(), uuid.New())

	if err == nil {
		t.Fatal("expected error, got nil")
	}

	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T", err)
	}
	if !apiErr.IsNotFound() {
		t.Errorf("expected IsNotFound to be true, status was %d", apiErr.StatusCode)
	}
}

func TestEvaluationResponse_IsConfident(t *testing.T) {
	resp := &EvaluationResponse{
		IsSafe:     true,
		Confidence: 0.85,
	}

	if !resp.IsConfident(0.8) {
		t.Error("expected IsConfident(0.8) to be true")
	}
	if resp.IsConfident(0.9) {
		t.Error("expected IsConfident(0.9) to be false")
	}
}
