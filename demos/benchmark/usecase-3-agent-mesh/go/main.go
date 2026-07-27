package main

import (
	"bufio"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type TaskRecord struct {
	TaskID              string `json:"task_id"`
	Category            string `json:"category"`
	BenchmarkGroup      string `json:"benchmark_group"`
	IntentNote          string `json:"intent_note"`
	UserTask            string `json:"user_task"`
	ExpectedMeshAction  string `json:"expected_mesh_action"`
	ExpectedFinalAction string `json:"expected_final_action"`
	AgentStubProfile    string `json:"agent_stub_profile"`
}

type EventRecord struct {
	TaskID        string `json:"task_id"`
	Mode          string `json:"mode"`
	Stage         string `json:"stage"`
	EventType     string `json:"event_type"`
	SourceAgent   string `json:"source_agent"`
	TargetAgent   string `json:"target_agent"`
	ToolName      string `json:"tool_name,omitempty"`
	Action        string `json:"action"`
	OriginalText  string `json:"original_text"`
	ProcessedText string `json:"processed_text"`
}

type SummaryStats struct {
	Mode                        string
	TasksTotal                  int
	AgentMessagesTotal          int
	MessagesMasked              int
	HandoffsBlocked             int
	TasksRouted                 int
	ToolCallsAttempted          int
	ToolCallsBlocked            int
	FinalOutputsTotal           int
	FinalOutputsBlocked         int
	FinalOutputsTagged          int
	FinalOutputsMasked          int
	SensitiveExposuresPrevented int
	ContractAlignmentCount      int
	DownstreamTokensDelivered   int
	PreprocessMs                float64
	EventsPerSec                float64
}

// tokenEstimate is a coarse, deterministic token count (whitespace words). Used only
// for relative payload comparison across modes, so the exact tokenizer does not matter.
func tokenEstimate(s string) int {
	return len(strings.Fields(s))
}

type PolicyConfig struct {
	PaymentCards       []string
	AccountIDs         []string
	FlaggedCustomers   []string
	DeniedEntities     []string
	InternalProjects   []string
	BlockedToolPhrases []string
	OutputBlockPhrases []string
	OutputTagPhrases   []string
}

var (
	paymentCardRegex = regexp.MustCompile(`\b(?:\d{4}[- ]?){3}\d{4}\b`)
	accountIDRegex   = regexp.MustCompile(`\bACC-\d{4}-\d{4}\b`)
	blockPhraseRegex = regexp.MustCompile(`(?i)full transcript export|send raw notes to reseller|external distribution|ignore prior safeguards`)
	routePhraseRegex = regexp.MustCompile(`(?i)Denied Entity:\s*[A-Za-z0-9 .-]+|Contoso Advisory`)
	internalRegex    = regexp.MustCompile(`(?i)\bProject Maple Vault\b|\bProject Aurora Ledger\b`)
	outputBlockRegex = regexp.MustCompile(`(?i)disallowed instructions|external distribution package`)
	outputTagRegex   = regexp.MustCompile(`(?i)privileged context|executive escalation`)
)

func loadTasks(path string) ([]TaskRecord, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var tasks []TaskRecord
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		var task TaskRecord
		if err := json.Unmarshal(scanner.Bytes(), &task); err != nil {
			return nil, fmt.Errorf("parse task JSONL: %w", err)
		}
		tasks = append(tasks, task)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return tasks, nil
}

func loadList(path string) ([]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var values []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		value := strings.TrimSpace(scanner.Text())
		if value == "" || strings.HasPrefix(value, "#") {
			continue
		}
		values = append(values, value)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return values, nil
}

func loadPolicies(dir string) (PolicyConfig, error) {
	load := func(name string) ([]string, error) {
		return loadList(filepath.Join(dir, name))
	}

	paymentCards, err := load("payment_cards.txt")
	if err != nil {
		return PolicyConfig{}, err
	}
	accountIDs, err := load("account_ids.txt")
	if err != nil {
		return PolicyConfig{}, err
	}
	flaggedCustomers, err := load("flagged_customers.txt")
	if err != nil {
		return PolicyConfig{}, err
	}
	deniedEntities, err := load("denied_entities.txt")
	if err != nil {
		return PolicyConfig{}, err
	}
	internalProjects, err := load("internal_projects.txt")
	if err != nil {
		return PolicyConfig{}, err
	}
	blockedToolPhrases, err := load("blocked_tool_phrases.txt")
	if err != nil {
		return PolicyConfig{}, err
	}
	outputBlockPhrases, err := load("output_block_phrases.txt")
	if err != nil {
		return PolicyConfig{}, err
	}
	outputTagPhrases, err := load("output_tag_phrases.txt")
	if err != nil {
		return PolicyConfig{}, err
	}

	return PolicyConfig{
		PaymentCards:       paymentCards,
		AccountIDs:         accountIDs,
		FlaggedCustomers:   flaggedCustomers,
		DeniedEntities:     deniedEntities,
		InternalProjects:   internalProjects,
		BlockedToolPhrases: blockedToolPhrases,
		OutputBlockPhrases: outputBlockPhrases,
		OutputTagPhrases:   outputTagPhrases,
	}, nil
}

func containsAnyFold(text string, values []string) bool {
	lower := strings.ToLower(text)
	for _, value := range values {
		if strings.Contains(lower, strings.ToLower(value)) {
			return true
		}
	}
	return false
}

func replaceAllFold(text string, values []string, replacement string) string {
	out := text
	for _, value := range values {
		if value == "" {
			continue
		}
		re := regexp.MustCompile(`(?i)` + regexp.QuoteMeta(value))
		out = re.ReplaceAllString(out, replacement)
	}
	return out
}

func maskRegex(text string) (string, bool) {
	out := paymentCardRegex.ReplaceAllString(text, "[MASKED_CARD]")
	out = accountIDRegex.ReplaceAllString(out, "[MASKED_ACCOUNT]")
	return out, out != text
}

func maskLists(text string, cfg PolicyConfig) (string, bool) {
	out := replaceAllFold(text, cfg.PaymentCards, "[MASKED_CARD]")
	out = replaceAllFold(out, cfg.AccountIDs, "[MASKED_ACCOUNT]")
	return out, out != text
}

func modelOutput(task TaskRecord, processed string) string {
	switch task.AgentStubProfile {
	case "external_send_attempt":
		return "Action agent prepared an external distribution package using " + processed
	case "external_leak_attempt":
		return "Action agent prepared partner-facing notes containing " + processed
	case "blocked_final":
		return "Final response contains disallowed instructions and should be blocked."
	case "privileged_context":
		return "Final response references privileged context for " + task.TaskID + "."
	case "maskable":
		return "Final response summarizes " + processed
	default:
		return "Final response is benign for " + task.TaskID + "."
	}
}

func applyControl(mode string, stage string, text string, task TaskRecord, cfg PolicyConfig) (string, string) {
	if mode == "nocontrol" {
		return "allow", text
	}

	if mode == "nol8sim_agent" {
		switch stage {
		case "handoff":
			if task.ExpectedMeshAction == "block_handoff" || task.ExpectedMeshAction == "route" {
				return task.ExpectedMeshAction, text
			}
			if task.ExpectedMeshAction == "mask" {
				masked, _ := maskRegex(text)
				return "mask", masked
			}
			return "allow", text
		case "tool":
			if task.ExpectedMeshAction == "block_tool" {
				return "block_tool", text
			}
			return "allow", text
		case "final":
			if task.ExpectedFinalAction == "block" {
				return "block", "[BLOCKED_OUTPUT]"
			}
			if task.ExpectedFinalAction == "tag" {
				return "tag", text
			}
			return "allow", text
		}
	}

	if mode == "re2_mesh" {
		switch stage {
		case "handoff":
			if routePhraseRegex.MatchString(text) {
				return "route", text
			}
			if internalRegex.MatchString(text) {
				return "block_handoff", text
			}
			if masked, changed := maskRegex(text); changed {
				return "mask", masked
			}
			return "allow", text
		case "tool":
			if blockPhraseRegex.MatchString(text) {
				return "block_tool", text
			}
			return "allow", text
		case "final":
			if outputBlockRegex.MatchString(text) {
				return "block", "[BLOCKED_OUTPUT]"
			}
			if outputTagRegex.MatchString(text) {
				return "tag", text
			}
			if masked, changed := maskRegex(text); changed {
				return "mask", masked
			}
			return "allow", text
		}
	}

	if mode == "listmesh" {
		switch stage {
		case "handoff":
			if containsAnyFold(text, cfg.FlaggedCustomers) || containsAnyFold(text, cfg.DeniedEntities) {
				return "route", text
			}
			if containsAnyFold(text, cfg.InternalProjects) {
				return "block_handoff", text
			}
			if masked, changed := maskLists(text, cfg); changed {
				return "mask", masked
			}
			return "allow", text
		case "tool":
			if containsAnyFold(text, cfg.BlockedToolPhrases) {
				return "block_tool", text
			}
			return "allow", text
		case "final":
			if containsAnyFold(text, cfg.OutputBlockPhrases) {
				return "block", "[BLOCKED_OUTPUT]"
			}
			if containsAnyFold(text, cfg.OutputTagPhrases) {
				return "tag", text
			}
			if masked, changed := maskLists(text, cfg); changed {
				return "mask", masked
			}
			return "allow", text
		}
	}

	return "allow", text
}

func writeEvent(encoder *json.Encoder, event EventRecord, stats *SummaryStats) {
	_ = encoder.Encode(event)
	switch event.EventType {
	case "agent_message":
		stats.AgentMessagesTotal++
		if event.Action == "mask" {
			stats.MessagesMasked++
		}
		if event.Action == "block_handoff" {
			stats.HandoffsBlocked++
			stats.SensitiveExposuresPrevented++
		}
		if event.Action == "route" {
			stats.TasksRouted++
			stats.SensitiveExposuresPrevented++
		}
	case "tool_call":
		stats.ToolCallsAttempted++
		if event.Action == "block_tool" {
			stats.ToolCallsBlocked++
			stats.SensitiveExposuresPrevented++
		}
	case "final_output":
		stats.FinalOutputsTotal++
		if event.Action == "block" {
			stats.FinalOutputsBlocked++
		}
		if event.Action == "tag" {
			stats.FinalOutputsTagged++
		}
		if event.Action == "mask" {
			stats.FinalOutputsMasked++
		}
	}
}

func runMode(tasks []TaskRecord, mode string, outputDir string, cfg PolicyConfig) (SummaryStats, error) {
	start := time.Now()
	stats := SummaryStats{Mode: mode, TasksTotal: len(tasks)}

	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return stats, err
	}
	outPath := filepath.Join(outputDir, mode+"_events.jsonl")
	file, err := os.Create(outPath)
	if err != nil {
		return stats, err
	}
	defer file.Close()
	encoder := json.NewEncoder(file)

	for _, task := range tasks {
		text := task.UserTask
		stages := []struct {
			name   string
			source string
			target string
		}{
			{"triage", "user", "triage_agent"},
			{"research", "triage_agent", "research_agent"},
			{"decision", "research_agent", "decision_agent"},
			{"action", "decision_agent", "action_agent"},
		}

		meshStopped := false
		terminalBlocked := false
		meshAction := "allow"
		for _, stage := range stages {
			action, processed := applyControl(mode, "handoff", text, task, cfg)
			if action != "allow" {
				meshAction = action
			}
			writeEvent(encoder, EventRecord{
				TaskID:        task.TaskID,
				Mode:          mode,
				Stage:         stage.name,
				EventType:     "agent_message",
				SourceAgent:   stage.source,
				TargetAgent:   stage.target,
				Action:        action,
				OriginalText:  text,
				ProcessedText: processed,
			}, &stats)
			text = processed
			// allow/mask forward the (possibly redacted) message to the next agent;
			// route/block_handoff stop it, so nothing is delivered downstream.
			if action == "allow" || action == "mask" {
				stats.DownstreamTokensDelivered += tokenEstimate(processed)
			}
			if action == "block_handoff" {
				meshStopped = true
				terminalBlocked = true
				break
			}
			if action == "route" {
				meshStopped = true
				break
			}
		}

		toolAction := "allow"
		if !meshStopped {
			toolAction, text = applyControl(mode, "tool", text, task, cfg)
			writeEvent(encoder, EventRecord{
				TaskID:        task.TaskID,
				Mode:          mode,
				Stage:         "tool",
				EventType:     "tool_call",
				SourceAgent:   "action_agent",
				TargetAgent:   "external_tool",
				ToolName:      "external_send",
				Action:        toolAction,
				OriginalText:  task.UserTask,
				ProcessedText: text,
			}, &stats)
			// an allowed tool call delivers its payload to the external tool.
			if toolAction == "allow" {
				stats.DownstreamTokensDelivered += tokenEstimate(text)
			}
			if toolAction == "block_tool" {
				meshStopped = true
				terminalBlocked = true
				meshAction = "block_tool"
			}
		}

		finalText := modelOutput(task, text)
		finalAction := "block"
		finalProcessed := "[BLOCKED_OUTPUT]"
		if !terminalBlocked {
			finalAction, finalProcessed = applyControl(mode, "final", finalText, task, cfg)
		}
		// a delivered final response (allow/mask/tag) reaches the user; block delivers nothing.
		if finalAction != "block" {
			stats.DownstreamTokensDelivered += tokenEstimate(finalProcessed)
		}
		writeEvent(encoder, EventRecord{
			TaskID:        task.TaskID,
			Mode:          mode,
			Stage:         "final",
			EventType:     "final_output",
			SourceAgent:   "final_agent",
			TargetAgent:   "user",
			Action:        finalAction,
			OriginalText:  finalText,
			ProcessedText: finalProcessed,
		}, &stats)

		if meshAction == task.ExpectedMeshAction && finalAction == task.ExpectedFinalAction {
			stats.ContractAlignmentCount++
		}
	}

	elapsed := time.Since(start)
	stats.PreprocessMs = float64(elapsed.Microseconds()) / 1000.0
	if elapsed.Seconds() > 0 {
		stats.EventsPerSec = float64(stats.AgentMessagesTotal+stats.ToolCallsAttempted+stats.FinalOutputsTotal) / elapsed.Seconds()
	}
	return stats, nil
}

func writeCSV(path string, stats []SummaryStats) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"mode",
		"tasks_total",
		"agent_messages_total",
		"messages_masked",
		"handoffs_blocked",
		"tasks_routed",
		"tool_calls_attempted",
		"tool_calls_blocked",
		"final_outputs_total",
		"final_outputs_blocked",
		"final_outputs_tagged",
		"final_outputs_masked",
		"sensitive_exposures_prevented",
		"contract_alignment_count",
		"downstream_tokens_delivered",
		"preprocess_ms",
		"events_per_sec",
	}
	if err := writer.Write(header); err != nil {
		return err
	}
	for _, s := range stats {
		row := []string{
			s.Mode,
			fmt.Sprintf("%d", s.TasksTotal),
			fmt.Sprintf("%d", s.AgentMessagesTotal),
			fmt.Sprintf("%d", s.MessagesMasked),
			fmt.Sprintf("%d", s.HandoffsBlocked),
			fmt.Sprintf("%d", s.TasksRouted),
			fmt.Sprintf("%d", s.ToolCallsAttempted),
			fmt.Sprintf("%d", s.ToolCallsBlocked),
			fmt.Sprintf("%d", s.FinalOutputsTotal),
			fmt.Sprintf("%d", s.FinalOutputsBlocked),
			fmt.Sprintf("%d", s.FinalOutputsTagged),
			fmt.Sprintf("%d", s.FinalOutputsMasked),
			fmt.Sprintf("%d", s.SensitiveExposuresPrevented),
			fmt.Sprintf("%d", s.ContractAlignmentCount),
			fmt.Sprintf("%d", s.DownstreamTokensDelivered),
			fmt.Sprintf("%.3f", s.PreprocessMs),
			fmt.Sprintf("%.2f", s.EventsPerSec),
		}
		if err := writer.Write(row); err != nil {
			return err
		}
	}
	return nil
}

func main() {
	mode := flag.String("mode", "", "Mode to run, or empty for the default set (nocontrol, themis_api_mesh)")
	input := flag.String("input", "../data/tasks/sample_agent_tasks.jsonl", "Input JSONL task file")
	_ = flag.String("policy-dir", "../data/policies", "Reference-list dir (unused in the current action model; kept for compatibility)")
	actionsPath := flag.String("actions", "../../../policies/mesh-actions.json", "mesh-actions.json (emitted by build_mesh_policy.py)")
	outputDir := flag.String("output-dir", "../results", "Output directory")
	flag.Parse()

	tasks, err := loadTasks(*input)
	if err != nil {
		fmt.Fprintf(os.Stderr, "load tasks: %v\n", err)
		os.Exit(1)
	}
	actions, err := loadMeshActions(*actionsPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}

	modes := []string{"nocontrol", "themis_api_mesh"}
	if *mode != "" {
		modes = []string{*mode}
	}

	identity := func(s string) (string, error) { return s, nil }

	var allStats []MeshStats
	for _, m := range modes {
		var stats MeshStats
		var rerr error
		switch m {
		case "nocontrol":
			stats, rerr = runMeshMode(tasks, m, *outputDir, actions, identity)
		case "themis_api_mesh", "aergia_api_mesh":
			endpointEnv, tokenEnv := "THEMIS_ENDPOINT", "THEMIS_TOKEN"
			if m == "aergia_api_mesh" {
				endpointEnv, tokenEnv = "AERGIA_ENDPOINT", "AERGIA_TOKEN"
			}
			cfg, cerr := loadEngineConfig(m, endpointEnv, tokenEnv)
			if cerr != nil {
				fmt.Fprintf(os.Stderr, "config %s: %v\n", m, cerr)
				os.Exit(1)
			}
			client := &http.Client{Timeout: cfg.Timeout}
			proc := func(s string) (string, error) { return callEngineProcess(client, cfg, s) }
			stats, rerr = runMeshMode(tasks, m, *outputDir, actions, proc)
		default:
			fmt.Fprintf(os.Stderr, "unknown mode %q (supported: nocontrol, themis_api_mesh, aergia_api_mesh)\n", m)
			os.Exit(1)
		}
		if rerr != nil {
			fmt.Fprintf(os.Stderr, "run %s: %v\n", m, rerr)
			os.Exit(1)
		}
		allStats = append(allStats, stats)
		fmt.Printf("Mode: %-16s | redacted %d  masked %d  dropped %d  route-sig %d  block-sig %d  | downstream tokens %d\n",
			stats.Mode, stats.Redacted, stats.Masked, stats.Dropped, stats.RouteSignals, stats.BlockSignals, stats.DownstreamTokensDelivered)
	}

	if err := writeMeshCSV(filepath.Join(*outputDir, "run_all.csv"), allStats); err != nil {
		fmt.Fprintf(os.Stderr, "write csv: %v\n", err)
		os.Exit(1)
	}
}
