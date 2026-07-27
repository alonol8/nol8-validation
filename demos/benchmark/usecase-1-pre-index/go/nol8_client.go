package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"time"
)

type Nol8Request struct {
	Text string `json:"text"`
}

type Nol8Response struct {
	Action string `json:"action"`
	Text   string `json:"text"`
}

func nol8HTTPClient() *http.Client {
	timeoutMs := 2000
	if raw := os.Getenv("NOL8_TIMEOUT_MS"); raw != "" {
		if parsed, err := strconv.Atoi(raw); err == nil && parsed > 0 {
			timeoutMs = parsed
		}
	}
	return &http.Client{Timeout: time.Duration(timeoutMs) * time.Millisecond}
}

func callNol8API(text string) (string, string, error) {
	return callNol8APIEndpoint(text, os.Getenv("NOL8_ENDPOINT"))
}

// callNol8APIEndpoint sends one record to a specific endpoint. Used by the
// per-engine modes (themis_api -> THEMIS_ENDPOINT, aergia_api -> AERGIA_ENDPOINT)
// so a single run can compare engines side by side.
func callNol8APIEndpoint(text, endpoint string) (string, string, error) {
	if endpoint == "" {
		return "", "error", fmt.Errorf("endpoint is not set")
	}

	body, err := json.Marshal(Nol8Request{Text: text})
	if err != nil {
		return "", "error", err
	}

	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(body))
	if err != nil {
		return "", "error", err
	}
	req.Header.Set("Content-Type", "application/json")

	if apiKey := os.Getenv("NOL8_API_KEY"); apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiKey)
	}

	resp, err := nol8HTTPClient().Do(req)
	if err != nil {
		return "", "error", err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", "error", fmt.Errorf("nol8 API returned status %d", resp.StatusCode)
	}

	var out Nol8Response
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", "error", err
	}

	switch out.Action {
	case "keep", "mask", "drop", "route":
	default:
		return "", "error", fmt.Errorf("invalid nol8 action %q", out.Action)
	}

	return out.Text, out.Action, nil
}
