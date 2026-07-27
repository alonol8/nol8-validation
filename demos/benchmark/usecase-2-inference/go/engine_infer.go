package main

// Real-engine pre/post-inference control for Data Point 2, honest action model.
//
// NOL8 does deterministic literal REPLACEMENT only. Two honest families:
//   LIVE TODAY (NOL8 transforms the data): redact (-> [REDACT]), mask (-> XXXX <last4>).
//   ROADMAP (NOL8 emits a signal a control plane enforces): route (-> [ROUTE]),
//     block (-> [BLOCK]). NOL8 does not stop a prompt reaching the model, or withhold an
//     output, today; it redacts/masks the text and emits the signal, and the text flows on.
//
// So there is NO stopping today: the model is always called, but on a prompt with known
// secrets redacted/masked. The live win is that secrets never reach the model or the
// response. The same processor drives nocontrol (identity) and the engine modes
// (themis_api_infer / aergia_api_infer), so they are directly comparable.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ---- engine transport ----

type EngineConfig struct {
	Endpoint  string
	Token     string
	Timeout   time.Duration
	ModeLabel string
}

func loadEngineConfig(modeLabel, endpointEnv, tokenEnv string) (EngineConfig, error) {
	endpoint := strings.TrimSpace(os.Getenv(endpointEnv))
	if endpoint == "" {
		return EngineConfig{}, fmt.Errorf("%s is required for %s mode", endpointEnv, modeLabel)
	}
	timeout := 30 * time.Second
	if raw := strings.TrimSpace(os.Getenv("ENGINE_TIMEOUT_MS")); raw != "" {
		var ms int
		if _, err := fmt.Sscanf(raw, "%d", &ms); err == nil && ms > 0 {
			timeout = time.Duration(ms) * time.Millisecond
		}
	}
	return EngineConfig{Endpoint: endpoint, Token: strings.TrimSpace(os.Getenv(tokenEnv)),
		Timeout: timeout, ModeLabel: modeLabel}, nil
}

func callEngineProcess(client *http.Client, cfg EngineConfig, text string) (string, error) {
	payload, err := json.Marshal(map[string]string{"message": text})
	if err != nil {
		return "", err
	}
	req, err := http.NewRequest(http.MethodPost, cfg.Endpoint, bytes.NewReader(payload))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if cfg.Token != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Token)
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("engine returned status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	var parsed struct {
		Result struct {
			Message string `json:"message"`
		} `json:"result"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		return "", fmt.Errorf("decode engine response: %w", err)
	}
	return parsed.Result.Message, nil
}

// ---- action model (shared shape with DP3's mesh-actions.json) ----

type BoundaryActions struct {
	Markers struct {
		Redact     string `json:"redact"`
		Route      string `json:"route"`
		Block      string `json:"block"`
		MaskPrefix string `json:"maskPrefix"`
	} `json:"markers"`
	DropLiterals []string `json:"dropLiterals"`
}

func loadBoundaryActions(path string) (BoundaryActions, error) {
	var a BoundaryActions
	raw, err := os.ReadFile(path)
	if err != nil {
		return a, fmt.Errorf("read boundary-actions %s: %w", path, err)
	}
	if err := json.Unmarshal(raw, &a); err != nil {
		return a, fmt.Errorf("parse boundary-actions %s: %w", path, err)
	}
	return a, nil
}

// deriveAction labels a control point from its input and the engine's processed output. A
// marker-based action counts only when the marker is NEW here. Precedence:
// block > route > drop > mask > redact > allow. block/route are roadmap signals.
func deriveAction(input, processed string, a BoundaryActions) string {
	newMarker := func(m string) bool {
		return m != "" && strings.Contains(processed, m) && !strings.Contains(input, m)
	}
	if newMarker(a.Markers.Block) {
		return "block"
	}
	if newMarker(a.Markers.Route) {
		return "route"
	}
	li, lp := strings.ToLower(input), strings.ToLower(processed)
	for _, d := range a.DropLiterals {
		if d == "" {
			continue
		}
		ld := strings.ToLower(d)
		if strings.Contains(li, ld) && !strings.Contains(lp, ld) {
			return "drop"
		}
	}
	if newMarker(a.Markers.MaskPrefix) {
		return "mask"
	}
	if newMarker(a.Markers.Redact) {
		return "redact"
	}
	return "allow"
}

// ---- stats ----

type BoundaryStats struct {
	Mode                  string
	PromptsTotal          int
	PromptsRedacted       int
	PromptsMasked         int
	PromptRouteSignals    int
	PromptBlockSignals    int
	OutputsRedacted       int
	OutputsMasked         int
	OutputBlockSignals    int
	PromptTokensIn        int
	PromptTokensForwarded int
	OutputTokensRaw       int
	OutputTokensReleased  int
	PreprocessMs          float64
	PostprocessMs         float64
}

func (s *BoundaryStats) countPre(action string) {
	switch action {
	case "redact":
		s.PromptsRedacted++
	case "mask":
		s.PromptsMasked++
	case "route":
		s.PromptRouteSignals++
	case "block":
		s.PromptBlockSignals++
	}
}

func (s *BoundaryStats) countPost(action string) {
	switch action {
	case "redact":
		s.OutputsRedacted++
	case "mask":
		s.OutputsMasked++
	case "block":
		s.OutputBlockSignals++
	}
}

// ---- the run ----

// runEngineInfer governs both edges of the model boundary with NO stopping (the honest
// today behavior). `process` transforms text: identity for nocontrol, the engine call for
// the api modes. The model is always called, on the redacted/masked prompt.
func runEngineInfer(prompts []PromptRecord, mode, outputDir string, actions BoundaryActions,
	process func(string) (string, error)) (BoundaryStats, error) {

	stats := BoundaryStats{Mode: mode, PromptsTotal: len(prompts)}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return stats, err
	}
	var records []OutputRecord

	for _, prompt := range prompts {
		stats.PromptTokensIn += tokenEstimate(prompt.PromptText)

		// Pre-inference: NOL8 redacts/masks the prompt (live) and emits route/block signals.
		preStart := time.Now()
		preProcessed, err := process(prompt.PromptText)
		if err != nil {
			return stats, fmt.Errorf("prompt %s pre: %w", prompt.PromptID, err)
		}
		stats.PreprocessMs += float64(time.Since(preStart).Microseconds()) / 1000.0
		preAction := deriveAction(prompt.PromptText, preProcessed, actions)
		stats.countPre(preAction)
		stats.PromptTokensForwarded += tokenEstimate(preProcessed)

		// The model is always called (no stopping today), on the redacted prompt.
		stub := modelStub(prompt, preProcessed)
		rawOutput := stub.RawModelOutput
		stats.OutputTokensRaw += tokenEstimate(rawOutput)

		// Post-inference: NOL8 redacts/masks the output (live) and emits block signals.
		postStart := time.Now()
		postProcessed, err := process(rawOutput)
		if err != nil {
			return stats, fmt.Errorf("prompt %s post: %w", prompt.PromptID, err)
		}
		stats.PostprocessMs += float64(time.Since(postStart).Microseconds()) / 1000.0
		postAction := deriveAction(rawOutput, postProcessed, actions)
		stats.countPost(postAction)
		stats.OutputTokensReleased += tokenEstimate(postProcessed)

		records = append(records, OutputRecord{
			PromptID:        prompt.PromptID,
			Mode:            mode,
			Category:        prompt.Category,
			PreAction:       preAction,
			PromptOriginal:  prompt.PromptText,
			PromptProcessed: preProcessed,
			InferenceCalled: true,
			RawModelOutput:  rawOutput,
			PostAction:      postAction,
			FinalOutput:     postProcessed,
		})
	}

	if err := writeOutputJSONL(filepath.Join(outputDir, mode+"_output.jsonl"), records); err != nil {
		return stats, err
	}
	return stats, nil
}

func writeBoundaryCSV(path string, all []BoundaryStats) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	header := "mode,prompts_total,prompts_redacted,prompts_masked,prompt_route_signals,prompt_block_signals," +
		"outputs_redacted,outputs_masked,output_block_signals,prompt_tokens_in,prompt_tokens_forwarded," +
		"output_tokens_raw,output_tokens_released,preprocess_ms,postprocess_ms\n"
	if _, err := file.WriteString(header); err != nil {
		return err
	}
	for _, s := range all {
		row := fmt.Sprintf("%s,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%.3f,%.3f\n",
			s.Mode, s.PromptsTotal, s.PromptsRedacted, s.PromptsMasked, s.PromptRouteSignals,
			s.PromptBlockSignals, s.OutputsRedacted, s.OutputsMasked, s.OutputBlockSignals,
			s.PromptTokensIn, s.PromptTokensForwarded, s.OutputTokensRaw, s.OutputTokensReleased,
			s.PreprocessMs, s.PostprocessMs)
		if _, err := file.WriteString(row); err != nil {
			return err
		}
	}
	return nil
}
