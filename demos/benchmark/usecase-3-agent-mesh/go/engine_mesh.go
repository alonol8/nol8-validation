package main

// Real-engine agent-to-agent control for Data Point 3, honest action model.
//
// NOL8 does deterministic literal REPLACEMENT only. That gives two honest families:
//   LIVE TODAY (NOL8 transforms the data): redact (-> [REDACT]), mask (-> XXXX <last4>),
//     drop (-> empty). These flow on; downstream receives the redacted message.
//   ROADMAP (NOL8 emits a signal; a control plane enforces): route (-> [ROUTE]),
//     block (-> [BLOCK]). NOL8 does not itself route/block/stop a message today; the
//     signalled text flows on. The report labels these Roadmap.
//
// So the mesh does NOT stop today. Every task flows through every hop (four handoffs, the
// tool call, the final output); at each hop NOL8 replaces matched literals and the harness
// derives which action fired from the resulting text plus mesh-actions.json. The payload
// each downstream recipient gets is the redacted text, which is why it shrinks.
//
// The same processor drives nocontrol (identity, no engine) and the engine modes
// (themis_api_mesh / aergia_api_mesh), so they are directly comparable.

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

// callEngineProcess sends one string through the engine's literal redaction and returns
// the processed text (policy replacements substituted in place).
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

// ---- action model ----

// MeshActions is loaded from mesh-actions.json (emitted by build_mesh_policy.py). It tells
// the harness how to label each hop from the engine output.
type MeshActions struct {
	Markers struct {
		Redact     string `json:"redact"`
		Route      string `json:"route"`
		Block      string `json:"block"`
		MaskPrefix string `json:"maskPrefix"`
	} `json:"markers"`
	DropLiterals []string `json:"dropLiterals"`
}

func loadMeshActions(path string) (MeshActions, error) {
	var a MeshActions
	raw, err := os.ReadFile(path)
	if err != nil {
		return a, fmt.Errorf("read mesh-actions %s: %w", path, err)
	}
	if err := json.Unmarshal(raw, &a); err != nil {
		return a, fmt.Errorf("parse mesh-actions %s: %w", path, err)
	}
	return a, nil
}

// deriveMeshAction labels a hop from its input and the engine's processed output. A
// marker-based action counts only when the marker is NEW this hop (a value redacted here,
// not one carried forward already redacted). Precedence: block > route > drop > mask >
// redact > allow. block/route are roadmap signals; the rest are live data actions.
func deriveMeshAction(input, processed string, a MeshActions) string {
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
		// drop = the value was present in the input and the engine removed it here.
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

type MeshStats struct {
	Mode                      string
	TasksTotal                int
	AgentMessages             int
	ToolCalls                 int
	FinalOutputs              int
	Redacted                  int
	Masked                    int
	Dropped                   int
	RouteSignals              int
	BlockSignals              int
	DownstreamTokensDelivered int
	PreprocessMs              float64
	EventsPerSec              float64
}

func (s *MeshStats) count(evType, action string) {
	switch evType {
	case "agent_message":
		s.AgentMessages++
	case "tool_call":
		s.ToolCalls++
	case "final_output":
		s.FinalOutputs++
	}
	switch action {
	case "redact":
		s.Redacted++
	case "mask":
		s.Masked++
	case "drop":
		s.Dropped++
	case "route":
		s.RouteSignals++
	case "block":
		s.BlockSignals++
	}
}

// ---- the run ----

// runMeshMode runs every task through the whole mesh with NO stopping (the honest today
// behavior). `process` transforms a hop's text: identity for nocontrol, the engine call
// for the api modes. The payload delivered downstream is the processed (redacted) text at
// every hop, which shrinks as NOL8 redacts/masks/drops.
func runMeshMode(tasks []TaskRecord, mode, outputDir string, actions MeshActions,
	process func(string) (string, error)) (MeshStats, error) {

	start := time.Now()
	stats := MeshStats{Mode: mode, TasksTotal: len(tasks)}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return stats, err
	}
	file, err := os.Create(filepath.Join(outputDir, mode+"_events.jsonl"))
	if err != nil {
		return stats, err
	}
	defer file.Close()
	enc := json.NewEncoder(file)

	stages := []struct{ name, source, target string }{
		{"triage", "user", "triage_agent"},
		{"research", "triage_agent", "research_agent"},
		{"decision", "research_agent", "decision_agent"},
		{"action", "decision_agent", "action_agent"},
	}

	timedProcess := func(text string) (string, error) {
		s := time.Now()
		out, err := process(text)
		stats.PreprocessMs += float64(time.Since(s).Microseconds()) / 1000.0
		return out, err
	}

	emit := func(ev EventRecord) {
		_ = enc.Encode(ev)
		stats.count(ev.EventType, ev.Action)
		stats.DownstreamTokensDelivered += tokenEstimate(ev.ProcessedText)
	}

	for _, task := range tasks {
		text := task.UserTask
		for _, st := range stages {
			processed, err := timedProcess(text)
			if err != nil {
				return stats, fmt.Errorf("task %s handoff %s: %w", task.TaskID, st.name, err)
			}
			action := deriveMeshAction(text, processed, actions)
			emit(EventRecord{TaskID: task.TaskID, Mode: mode, Stage: st.name,
				EventType: "agent_message", SourceAgent: st.source, TargetAgent: st.target,
				Action: action, OriginalText: text, ProcessedText: processed})
			text = processed
		}

		processed, err := timedProcess(text)
		if err != nil {
			return stats, fmt.Errorf("task %s tool: %w", task.TaskID, err)
		}
		toolAction := deriveMeshAction(text, processed, actions)
		emit(EventRecord{TaskID: task.TaskID, Mode: mode, Stage: "tool",
			EventType: "tool_call", SourceAgent: "action_agent", TargetAgent: "external_tool",
			ToolName: "external_send", Action: toolAction, OriginalText: text, ProcessedText: processed})
		text = processed

		finalText := modelOutput(task, text)
		finalProcessed, err := timedProcess(finalText)
		if err != nil {
			return stats, fmt.Errorf("task %s final: %w", task.TaskID, err)
		}
		finalAction := deriveMeshAction(finalText, finalProcessed, actions)
		emit(EventRecord{TaskID: task.TaskID, Mode: mode, Stage: "final",
			EventType: "final_output", SourceAgent: "final_agent", TargetAgent: "user",
			Action: finalAction, OriginalText: finalText, ProcessedText: finalProcessed})
	}

	elapsed := time.Since(start)
	if elapsed.Seconds() > 0 {
		stats.EventsPerSec = float64(stats.AgentMessages+stats.ToolCalls+stats.FinalOutputs) / elapsed.Seconds()
	}
	return stats, nil
}

func writeMeshCSV(path string, all []MeshStats) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	header := "mode,tasks_total,agent_messages,tool_calls,final_outputs,redacted,masked,dropped," +
		"route_signals,block_signals,downstream_tokens_delivered,preprocess_ms,events_per_sec\n"
	if _, err := file.WriteString(header); err != nil {
		return err
	}
	for _, s := range all {
		row := fmt.Sprintf("%s,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%.3f,%.2f\n",
			s.Mode, s.TasksTotal, s.AgentMessages, s.ToolCalls, s.FinalOutputs,
			s.Redacted, s.Masked, s.Dropped, s.RouteSignals, s.BlockSignals,
			s.DownstreamTokensDelivered, s.PreprocessMs, s.EventsPerSec)
		if _, err := file.WriteString(row); err != nil {
			return err
		}
	}
	return nil
}
