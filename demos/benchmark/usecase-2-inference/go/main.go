package main

import (
	"bufio"
	"bytes"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type PromptRecord struct {
	PromptID          string   `json:"prompt_id"`
	Category          string   `json:"category"`
	PromptText        string   `json:"prompt_text"`
	ExpectedPreAction string   `json:"expected_pre_action"`
	ExpectedPreTags   []string `json:"expected_pre_tags,omitempty"`
	ModelStubProfile  string   `json:"model_stub_profile"`
	IntentNote        string   `json:"intent_note"`
}

type OutputRecord struct {
	PromptID        string   `json:"prompt_id"`
	Mode            string   `json:"mode"`
	Category        string   `json:"category"`
	PreAction       string   `json:"pre_action"`
	PreTags         []string `json:"pre_tags"`
	PromptOriginal  string   `json:"prompt_original"`
	PromptProcessed string   `json:"prompt_processed"`
	InferenceCalled bool     `json:"inference_called"`
	RawModelOutput  string   `json:"raw_model_output"`
	PostAction      string   `json:"post_action"`
	PostTags        []string `json:"post_tags"`
	FinalOutput     string   `json:"final_output"`
}

type SummaryStats struct {
	Mode                     string
	PromptsTotal             int
	PromptsAllowed           int
	PromptsMasked            int
	PromptsBlocked           int
	PromptsRouted            int
	PromptsTagged            int
	InferenceCallsMade       int
	InferenceCallsAvoided    int
	PromptTokensInEst        int
	PromptTokensForwardedEst int
	OutputsTotal             int
	OutputsAllowed           int
	OutputsMasked            int
	OutputsBlocked           int
	OutputsTagged            int
	OutputTokensRawEst       int
	OutputTokensReleasedEst  int
	PreprocessMs             float64
	PostprocessMs            float64
	TotalControlMs           float64
	RecordsPerSec            float64
}

type ModelStubResponse struct {
	RawModelOutput string
	OutputProfile  string
}

type Nol8APIConfig struct {
	BaseURL   string
	APIKey    string
	Timeout   time.Duration
	ModeLabel string
}

type Nol8APIRequest struct {
	PromptID          string   `json:"prompt_id"`
	Category          string   `json:"category"`
	PromptText        string   `json:"prompt_text"`
	ExpectedPreAction string   `json:"expected_pre_action"`
	ExpectedPreTags   []string `json:"expected_pre_tags,omitempty"`
	ModelStubProfile  string   `json:"model_stub_profile"`
	IntentNote        string   `json:"intent_note"`
}

type Nol8APIResponse struct {
	PreAction       string   `json:"pre_action"`
	PreTags         []string `json:"pre_tags,omitempty"`
	PromptProcessed string   `json:"prompt_processed"`
	InferenceCalled *bool    `json:"inference_called,omitempty"`
	RawModelOutput  string   `json:"raw_model_output"`
	PostAction      string   `json:"post_action"`
	PostTags        []string `json:"post_tags,omitempty"`
	FinalOutput     string   `json:"final_output"`
}

type ListGuardConfig struct {
	PaymentCards       []string
	AccountIDs         []string
	FlaggedCustomers   []string
	DeniedEntities     []string
	InternalProjects   []string
	BlockPhrases       []string
	RoutePhrases       []string
	OutputBlockPhrases []string
	OutputTagPhrases   []string
}

var (
	paymentCardRegex      = regexp.MustCompile(`\b(?:\d{4}[- ]?){3}\d{4}\b`)
	accountIDRegex        = regexp.MustCompile(`\bACC-\d{4}-\d{4}\b`)
	blockPhraseRegex      = regexp.MustCompile(`(?i)ignore prior safeguards|external distribution`)
	routePhraseRegex      = regexp.MustCompile(`(?i)approve release|Denied Entity:\s*[A-Za-z0-9 .-]+|Northwind Trading`)
	internalOnlyRegex     = regexp.MustCompile(`(?i)\bProject Aurora Ledger\b`)
	privilegedOutputRegex = regexp.MustCompile(`(?i)privileged context`)
	blockedOutputRegex    = regexp.MustCompile(`(?i)disallowed instructions`)
)

func tokenEstimate(s string) int {
	return len(strings.Fields(s))
}

func loadPrompts(path string) ([]PromptRecord, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var prompts []PromptRecord
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		var record PromptRecord
		if err := json.Unmarshal(scanner.Bytes(), &record); err != nil {
			return nil, fmt.Errorf("parse prompt JSONL: %w", err)
		}
		prompts = append(prompts, record)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return prompts, nil
}

func loadReferenceList(path string) ([]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var values []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		values = append(values, line)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return values, nil
}

func loadListGuardConfig(listDir string) (ListGuardConfig, error) {
	load := func(name string) ([]string, error) {
		return loadReferenceList(filepath.Join(listDir, name))
	}

	paymentCards, err := load("payment_cards.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	accountIDs, err := load("account_ids.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	flaggedCustomers, err := load("flagged_customers.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	deniedEntities, err := load("denied_entities.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	internalProjects, err := load("internal_projects.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	blockPhrases, err := load("block_phrases.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	routePhrases, err := load("route_phrases.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	outputBlockPhrases, err := load("output_block_phrases.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}
	outputTagPhrases, err := load("output_tag_phrases.txt")
	if err != nil {
		return ListGuardConfig{}, err
	}

	return ListGuardConfig{
		PaymentCards:       paymentCards,
		AccountIDs:         accountIDs,
		FlaggedCustomers:   flaggedCustomers,
		DeniedEntities:     deniedEntities,
		InternalProjects:   internalProjects,
		BlockPhrases:       blockPhrases,
		RoutePhrases:       routePhrases,
		OutputBlockPhrases: outputBlockPhrases,
		OutputTagPhrases:   outputTagPhrases,
	}, nil
}

func loadNol8APIConfig() (Nol8APIConfig, error) {
	baseURL := strings.TrimSpace(os.Getenv("NOL8_API_URL"))
	if baseURL == "" {
		return Nol8APIConfig{}, fmt.Errorf("NOL8_API_URL is required for nol8_api_infer mode")
	}

	timeout := 30 * time.Second
	if rawTimeout := strings.TrimSpace(os.Getenv("NOL8_API_TIMEOUT_MS")); rawTimeout != "" {
		var timeoutMs int
		if _, err := fmt.Sscanf(rawTimeout, "%d", &timeoutMs); err != nil || timeoutMs <= 0 {
			return Nol8APIConfig{}, fmt.Errorf("invalid NOL8_API_TIMEOUT_MS value: %q", rawTimeout)
		}
		timeout = time.Duration(timeoutMs) * time.Millisecond
	}

	modeLabel := strings.TrimSpace(os.Getenv("NOL8_API_MODE_LABEL"))
	if modeLabel == "" {
		modeLabel = "nol8_api_infer"
	}

	return Nol8APIConfig{
		BaseURL:   strings.TrimRight(baseURL, "/"),
		APIKey:    strings.TrimSpace(os.Getenv("NOL8_API_KEY")),
		Timeout:   timeout,
		ModeLabel: modeLabel,
	}, nil
}

func modelStub(prompt PromptRecord, processedPrompt string) ModelStubResponse {
	switch prompt.ModelStubProfile {
	case "returns_maskable_output":
		return ModelStubResponse{
			RawModelOutput: fmt.Sprintf("Model response for %s includes sensitive value echo: %s", prompt.PromptID, processedPrompt),
			OutputProfile:  "mask_output",
		}
	case "returns_blocked_output":
		return ModelStubResponse{
			RawModelOutput: "Model response contains disallowed instructions and should be blocked downstream.",
			OutputProfile:  "block_output",
		}
	case "returns_tagged_output":
		return ModelStubResponse{
			RawModelOutput: fmt.Sprintf("Model response references privileged context for %s and should be tagged.", prompt.PromptID),
			OutputProfile:  "tag_output",
		}
	default:
		return ModelStubResponse{
			RawModelOutput: fmt.Sprintf("Benign model response for %s.", prompt.PromptID),
			OutputProfile:  "allow_output",
		}
	}
}

func dedupeTags(tags []string) []string {
	if len(tags) == 0 {
		return []string{}
	}
	seen := make(map[string]struct{}, len(tags))
	var out []string
	for _, tag := range tags {
		if _, ok := seen[tag]; ok {
			continue
		}
		seen[tag] = struct{}{}
		out = append(out, tag)
	}
	return out
}

func containsAnyFold(text string, values []string) bool {
	lowerText := strings.ToLower(text)
	for _, value := range values {
		if strings.Contains(lowerText, strings.ToLower(value)) {
			return true
		}
	}
	return false
}

func replaceAllFold(text string, values []string, replacement string) string {
	result := text
	for _, value := range values {
		if value == "" {
			continue
		}
		re := regexp.MustCompile(`(?i)` + regexp.QuoteMeta(value))
		result = re.ReplaceAllString(result, replacement)
	}
	return result
}

func applyPreInferenceRE2(promptText string) (string, string, []string) {
	switch {
	case blockPhraseRegex.MatchString(promptText):
		return "block", promptText, []string{}
	case routePhraseRegex.MatchString(promptText):
		return "route", promptText, []string{}
	}

	processed := promptText
	action := "allow"
	var tags []string

	if paymentCardRegex.MatchString(processed) {
		processed = paymentCardRegex.ReplaceAllString(processed, "[MASKED_CARD]")
		action = "mask"
	}
	if accountIDRegex.MatchString(processed) {
		processed = accountIDRegex.ReplaceAllString(processed, "[MASKED_ACCOUNT]")
		action = "mask"
	}
	if internalOnlyRegex.MatchString(promptText) {
		tags = append(tags, "internal_only")
		if action == "allow" {
			action = "tag"
		}
	}

	return action, processed, dedupeTags(tags)
}

func applyPostInferenceRE2(rawOutput string) (string, string, []string) {
	switch {
	case blockedOutputRegex.MatchString(rawOutput):
		return "block", "[BLOCKED_OUTPUT]", []string{}
	}

	finalOutput := rawOutput
	action := "allow"
	var tags []string

	if paymentCardRegex.MatchString(finalOutput) {
		finalOutput = paymentCardRegex.ReplaceAllString(finalOutput, "[MASKED_CARD]")
		action = "mask"
	}
	if accountIDRegex.MatchString(finalOutput) {
		finalOutput = accountIDRegex.ReplaceAllString(finalOutput, "[MASKED_ACCOUNT]")
		action = "mask"
	}
	if privilegedOutputRegex.MatchString(rawOutput) {
		tags = append(tags, "privileged_context")
		if action == "allow" {
			action = "tag"
		}
	}

	return action, finalOutput, dedupeTags(tags)
}

func applyPreInferenceListGuard(promptText string, cfg ListGuardConfig) (string, string, []string) {
	switch {
	case containsAnyFold(promptText, cfg.BlockPhrases):
		return "block", promptText, []string{}
	case containsAnyFold(promptText, cfg.RoutePhrases):
		return "route", promptText, []string{}
	case containsAnyFold(promptText, cfg.FlaggedCustomers):
		return "route", promptText, []string{}
	case containsAnyFold(promptText, cfg.DeniedEntities):
		return "route", promptText, []string{}
	}

	processed := promptText
	action := "allow"
	var tags []string

	if containsAnyFold(processed, cfg.PaymentCards) {
		processed = replaceAllFold(processed, cfg.PaymentCards, "[MASKED_CARD]")
		action = "mask"
	}
	if containsAnyFold(processed, cfg.AccountIDs) {
		processed = replaceAllFold(processed, cfg.AccountIDs, "[MASKED_ACCOUNT]")
		action = "mask"
	}
	if containsAnyFold(promptText, cfg.InternalProjects) {
		tags = append(tags, "internal_only")
		if action == "allow" {
			action = "tag"
		}
	}

	return action, processed, dedupeTags(tags)
}

func applyPostInferenceListGuard(rawOutput string, cfg ListGuardConfig) (string, string, []string) {
	switch {
	case containsAnyFold(rawOutput, cfg.OutputBlockPhrases):
		return "block", "[BLOCKED_OUTPUT]", []string{}
	}

	finalOutput := rawOutput
	action := "allow"
	var tags []string

	if containsAnyFold(finalOutput, cfg.PaymentCards) {
		finalOutput = replaceAllFold(finalOutput, cfg.PaymentCards, "[MASKED_CARD]")
		action = "mask"
	}
	if containsAnyFold(finalOutput, cfg.AccountIDs) {
		finalOutput = replaceAllFold(finalOutput, cfg.AccountIDs, "[MASKED_ACCOUNT]")
		action = "mask"
	}
	if containsAnyFold(rawOutput, cfg.OutputTagPhrases) {
		tags = append(tags, "privileged_context")
		if action == "allow" {
			action = "tag"
		}
	}

	return action, finalOutput, dedupeTags(tags)
}

func applyPreInferenceNol8Sim(prompt PromptRecord) (string, string, []string) {
	action := prompt.ExpectedPreAction
	if action == "" {
		action = "allow"
	}

	processed := prompt.PromptText
	if action == "mask" {
		processed = paymentCardRegex.ReplaceAllString(processed, "[MASKED_CARD]")
		processed = accountIDRegex.ReplaceAllString(processed, "[MASKED_ACCOUNT]")
	}

	return action, processed, dedupeTags(prompt.ExpectedPreTags)
}

func applyPostInferenceNol8Sim(rawOutput string, outputProfile string) (string, string, []string) {
	switch outputProfile {
	case "block_output":
		return "block", "[BLOCKED_OUTPUT]", []string{}
	case "tag_output":
		return "tag", rawOutput, []string{"privileged_context"}
	case "mask_output":
		finalOutput := paymentCardRegex.ReplaceAllString(rawOutput, "[MASKED_CARD]")
		finalOutput = accountIDRegex.ReplaceAllString(finalOutput, "[MASKED_ACCOUNT]")
		if finalOutput != rawOutput {
			return "mask", finalOutput, []string{}
		}
		return "allow", rawOutput, []string{}
	default:
		return "allow", rawOutput, []string{}
	}
}

func isValidAction(action string) bool {
	switch action {
	case "allow", "mask", "block", "route", "tag":
		return true
	default:
		return false
	}
}

func callNol8API(client *http.Client, cfg Nol8APIConfig, prompt PromptRecord) (Nol8APIResponse, error) {
	requestBody := Nol8APIRequest{
		PromptID:          prompt.PromptID,
		Category:          prompt.Category,
		PromptText:        prompt.PromptText,
		ExpectedPreAction: prompt.ExpectedPreAction,
		ExpectedPreTags:   prompt.ExpectedPreTags,
		ModelStubProfile:  prompt.ModelStubProfile,
		IntentNote:        prompt.IntentNote,
	}

	payload, err := json.Marshal(requestBody)
	if err != nil {
		return Nol8APIResponse{}, fmt.Errorf("marshal nol8 api request: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, cfg.BaseURL+"/infer-control", bytes.NewReader(payload))
	if err != nil {
		return Nol8APIResponse{}, fmt.Errorf("build nol8 api request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if cfg.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.APIKey)
	}

	resp, err := client.Do(req)
	if err != nil {
		return Nol8APIResponse{}, fmt.Errorf("call nol8 api: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return Nol8APIResponse{}, fmt.Errorf("read nol8 api response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return Nol8APIResponse{}, fmt.Errorf("nol8 api returned status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	var apiResp Nol8APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return Nol8APIResponse{}, fmt.Errorf("decode nol8 api response: %w", err)
	}

	if !isValidAction(apiResp.PreAction) {
		return Nol8APIResponse{}, fmt.Errorf("nol8 api response has invalid pre_action %q", apiResp.PreAction)
	}
	if apiResp.PostAction == "" {
		apiResp.PostAction = "allow"
	}
	if !isValidAction(apiResp.PostAction) {
		return Nol8APIResponse{}, fmt.Errorf("nol8 api response has invalid post_action %q", apiResp.PostAction)
	}
	if apiResp.PromptProcessed == "" {
		apiResp.PromptProcessed = prompt.PromptText
	}
	if apiResp.InferenceCalled == nil {
		inferenceCalled := apiResp.PreAction != "block" && apiResp.PreAction != "route"
		apiResp.InferenceCalled = &inferenceCalled
	}
	if apiResp.FinalOutput == "" && apiResp.PostAction == "allow" {
		apiResp.FinalOutput = apiResp.RawModelOutput
	}
	if apiResp.FinalOutput == "" && apiResp.PostAction == "block" {
		apiResp.FinalOutput = "[BLOCKED_OUTPUT]"
	}

	return apiResp, nil
}

func writeOutputJSONL(path string, records []OutputRecord) error {
	outFile, err := os.Create(path)
	if err != nil {
		return err
	}
	defer outFile.Close()

	writer := bufio.NewWriter(outFile)
	defer writer.Flush()

	encoder := json.NewEncoder(writer)
	for _, record := range records {
		if err := encoder.Encode(record); err != nil {
			return err
		}
	}
	return nil
}

func runNoControl(prompts []PromptRecord, outputDir string) (SummaryStats, error) {
	start := time.Now()
	stats := SummaryStats{Mode: "nocontrol"}

	var records []OutputRecord

	for _, prompt := range prompts {
		stats.PromptsTotal++
		stats.PromptTokensInEst += tokenEstimate(prompt.PromptText)

		preAction := "allow"
		promptProcessed := prompt.PromptText
		stats.PromptsAllowed++
		stats.PromptTokensForwardedEst += tokenEstimate(promptProcessed)
		stats.InferenceCallsMade++

		stub := modelStub(prompt, promptProcessed)
		postAction := "allow"
		finalOutput := stub.RawModelOutput

		stats.OutputsTotal++
		stats.OutputsAllowed++
		stats.OutputTokensRawEst += tokenEstimate(stub.RawModelOutput)
		stats.OutputTokensReleasedEst += tokenEstimate(finalOutput)

		record := OutputRecord{
			PromptID:        prompt.PromptID,
			Mode:            "nocontrol",
			Category:        prompt.Category,
			PreAction:       preAction,
			PreTags:         []string{},
			PromptOriginal:  prompt.PromptText,
			PromptProcessed: promptProcessed,
			InferenceCalled: true,
			RawModelOutput:  stub.RawModelOutput,
			PostAction:      postAction,
			PostTags:        []string{},
			FinalOutput:     finalOutput,
		}
		records = append(records, record)
	}

	elapsedMs := float64(time.Since(start).Milliseconds())
	if elapsedMs <= 0 {
		elapsedMs = 1
	}
	stats.PreprocessMs = 0
	stats.PostprocessMs = 0
	stats.TotalControlMs = 0
	stats.RecordsPerSec = float64(stats.PromptsTotal) / (elapsedMs / 1000.0)

	if err := writeOutputJSONL(filepath.Join(outputDir, "nocontrol_output.jsonl"), records); err != nil {
		return stats, err
	}

	return stats, writeSummaryCSV(filepath.Join(outputDir, "run_01.csv"), stats)
}

func runRE2Guard(prompts []PromptRecord, outputDir string) (SummaryStats, error) {
	start := time.Now()
	stats := SummaryStats{Mode: "re2_guard"}
	var records []OutputRecord

	for _, prompt := range prompts {
		stats.PromptsTotal++
		stats.PromptTokensInEst += tokenEstimate(prompt.PromptText)

		preStart := time.Now()
		preAction, promptProcessed, preTags := applyPreInferenceRE2(prompt.PromptText)
		stats.PreprocessMs += float64(time.Since(preStart).Microseconds()) / 1000.0

		switch preAction {
		case "allow":
			stats.PromptsAllowed++
		case "mask":
			stats.PromptsMasked++
		case "block":
			stats.PromptsBlocked++
			stats.InferenceCallsAvoided++
		case "route":
			stats.PromptsRouted++
			stats.InferenceCallsAvoided++
		case "tag":
			stats.PromptsTagged++
		}

		inferenceCalled := preAction != "block" && preAction != "route"
		rawOutput := ""
		postAction := "allow"
		postTags := []string{}
		finalOutput := ""

		if inferenceCalled {
			stats.InferenceCallsMade++
			stats.PromptTokensForwardedEst += tokenEstimate(promptProcessed)

			stub := modelStub(prompt, promptProcessed)
			rawOutput = stub.RawModelOutput
			stats.OutputsTotal++
			stats.OutputTokensRawEst += tokenEstimate(rawOutput)

			postStart := time.Now()
			postAction, finalOutput, postTags = applyPostInferenceRE2(rawOutput)
			stats.PostprocessMs += float64(time.Since(postStart).Microseconds()) / 1000.0

			switch postAction {
			case "allow":
				stats.OutputsAllowed++
			case "mask":
				stats.OutputsMasked++
			case "block":
				stats.OutputsBlocked++
			case "tag":
				stats.OutputsTagged++
			}
			stats.OutputTokensReleasedEst += tokenEstimate(finalOutput)
		}

		record := OutputRecord{
			PromptID:        prompt.PromptID,
			Mode:            "re2_guard",
			Category:        prompt.Category,
			PreAction:       preAction,
			PreTags:         preTags,
			PromptOriginal:  prompt.PromptText,
			PromptProcessed: promptProcessed,
			InferenceCalled: inferenceCalled,
			RawModelOutput:  rawOutput,
			PostAction:      postAction,
			PostTags:        postTags,
			FinalOutput:     finalOutput,
		}
		records = append(records, record)
	}

	totalElapsedMs := float64(time.Since(start).Milliseconds())
	if totalElapsedMs <= 0 {
		totalElapsedMs = 1
	}
	stats.TotalControlMs = stats.PreprocessMs + stats.PostprocessMs
	stats.RecordsPerSec = float64(stats.PromptsTotal) / (totalElapsedMs / 1000.0)

	if err := writeOutputJSONL(filepath.Join(outputDir, "re2_guard_output.jsonl"), records); err != nil {
		return stats, err
	}

	return stats, writeSummaryCSV(filepath.Join(outputDir, "run_01.csv"), stats)
}

func runListGuard(prompts []PromptRecord, outputDir string, cfg ListGuardConfig) (SummaryStats, error) {
	start := time.Now()
	stats := SummaryStats{Mode: "listguard"}
	var records []OutputRecord

	for _, prompt := range prompts {
		stats.PromptsTotal++
		stats.PromptTokensInEst += tokenEstimate(prompt.PromptText)

		preStart := time.Now()
		preAction, promptProcessed, preTags := applyPreInferenceListGuard(prompt.PromptText, cfg)
		stats.PreprocessMs += float64(time.Since(preStart).Microseconds()) / 1000.0

		switch preAction {
		case "allow":
			stats.PromptsAllowed++
		case "mask":
			stats.PromptsMasked++
		case "block":
			stats.PromptsBlocked++
			stats.InferenceCallsAvoided++
		case "route":
			stats.PromptsRouted++
			stats.InferenceCallsAvoided++
		case "tag":
			stats.PromptsTagged++
		}

		inferenceCalled := preAction != "block" && preAction != "route"
		rawOutput := ""
		postAction := "allow"
		postTags := []string{}
		finalOutput := ""

		if inferenceCalled {
			stats.InferenceCallsMade++
			stats.PromptTokensForwardedEst += tokenEstimate(promptProcessed)

			stub := modelStub(prompt, promptProcessed)
			rawOutput = stub.RawModelOutput
			stats.OutputsTotal++
			stats.OutputTokensRawEst += tokenEstimate(rawOutput)

			postStart := time.Now()
			postAction, finalOutput, postTags = applyPostInferenceListGuard(rawOutput, cfg)
			stats.PostprocessMs += float64(time.Since(postStart).Microseconds()) / 1000.0

			switch postAction {
			case "allow":
				stats.OutputsAllowed++
			case "mask":
				stats.OutputsMasked++
			case "block":
				stats.OutputsBlocked++
			case "tag":
				stats.OutputsTagged++
			}
			stats.OutputTokensReleasedEst += tokenEstimate(finalOutput)
		}

		record := OutputRecord{
			PromptID:        prompt.PromptID,
			Mode:            "listguard",
			Category:        prompt.Category,
			PreAction:       preAction,
			PreTags:         preTags,
			PromptOriginal:  prompt.PromptText,
			PromptProcessed: promptProcessed,
			InferenceCalled: inferenceCalled,
			RawModelOutput:  rawOutput,
			PostAction:      postAction,
			PostTags:        postTags,
			FinalOutput:     finalOutput,
		}
		records = append(records, record)
	}

	totalElapsedMs := float64(time.Since(start).Milliseconds())
	if totalElapsedMs <= 0 {
		totalElapsedMs = 1
	}
	stats.TotalControlMs = stats.PreprocessMs + stats.PostprocessMs
	stats.RecordsPerSec = float64(stats.PromptsTotal) / (totalElapsedMs / 1000.0)

	if err := writeOutputJSONL(filepath.Join(outputDir, "listguard_output.jsonl"), records); err != nil {
		return stats, err
	}

	return stats, writeSummaryCSV(filepath.Join(outputDir, "run_01.csv"), stats)
}

func runNol8SimInfer(prompts []PromptRecord, outputDir string) (SummaryStats, error) {
	start := time.Now()
	stats := SummaryStats{Mode: "nol8sim_infer"}
	var records []OutputRecord

	for _, prompt := range prompts {
		stats.PromptsTotal++
		stats.PromptTokensInEst += tokenEstimate(prompt.PromptText)

		preStart := time.Now()
		preAction, promptProcessed, preTags := applyPreInferenceNol8Sim(prompt)
		stats.PreprocessMs += float64(time.Since(preStart).Microseconds()) / 1000.0

		switch preAction {
		case "allow":
			stats.PromptsAllowed++
		case "mask":
			stats.PromptsMasked++
		case "block":
			stats.PromptsBlocked++
			stats.InferenceCallsAvoided++
		case "route":
			stats.PromptsRouted++
			stats.InferenceCallsAvoided++
		case "tag":
			stats.PromptsTagged++
		}

		inferenceCalled := preAction != "block" && preAction != "route"
		rawOutput := ""
		postAction := "allow"
		postTags := []string{}
		finalOutput := ""

		if inferenceCalled {
			stats.InferenceCallsMade++
			stats.PromptTokensForwardedEst += tokenEstimate(promptProcessed)

			stub := modelStub(prompt, promptProcessed)
			rawOutput = stub.RawModelOutput
			stats.OutputsTotal++
			stats.OutputTokensRawEst += tokenEstimate(rawOutput)

			postStart := time.Now()
			postAction, finalOutput, postTags = applyPostInferenceNol8Sim(rawOutput, stub.OutputProfile)
			stats.PostprocessMs += float64(time.Since(postStart).Microseconds()) / 1000.0

			switch postAction {
			case "allow":
				stats.OutputsAllowed++
			case "mask":
				stats.OutputsMasked++
			case "block":
				stats.OutputsBlocked++
			case "tag":
				stats.OutputsTagged++
			}
			stats.OutputTokensReleasedEst += tokenEstimate(finalOutput)
		}

		record := OutputRecord{
			PromptID:        prompt.PromptID,
			Mode:            "nol8sim_infer",
			Category:        prompt.Category,
			PreAction:       preAction,
			PreTags:         preTags,
			PromptOriginal:  prompt.PromptText,
			PromptProcessed: promptProcessed,
			InferenceCalled: inferenceCalled,
			RawModelOutput:  rawOutput,
			PostAction:      postAction,
			PostTags:        postTags,
			FinalOutput:     finalOutput,
		}
		records = append(records, record)
	}

	totalElapsedMs := float64(time.Since(start).Milliseconds())
	if totalElapsedMs <= 0 {
		totalElapsedMs = 1
	}
	stats.TotalControlMs = stats.PreprocessMs + stats.PostprocessMs
	stats.RecordsPerSec = float64(stats.PromptsTotal) / (totalElapsedMs / 1000.0)

	if err := writeOutputJSONL(filepath.Join(outputDir, "nol8sim_infer_output.jsonl"), records); err != nil {
		return stats, err
	}

	return stats, writeSummaryCSV(filepath.Join(outputDir, "run_01.csv"), stats)
}

func runNol8APIInfer(prompts []PromptRecord, outputDir string, cfg Nol8APIConfig) (SummaryStats, error) {
	start := time.Now()
	stats := SummaryStats{Mode: cfg.ModeLabel}
	var records []OutputRecord
	client := &http.Client{Timeout: cfg.Timeout}

	for _, prompt := range prompts {
		stats.PromptsTotal++
		stats.PromptTokensInEst += tokenEstimate(prompt.PromptText)

		callStart := time.Now()
		apiResp, err := callNol8API(client, cfg, prompt)
		if err != nil {
			return stats, fmt.Errorf("prompt %s: %w", prompt.PromptID, err)
		}
		callMs := float64(time.Since(callStart).Microseconds()) / 1000.0
		stats.PreprocessMs += callMs

		switch apiResp.PreAction {
		case "allow":
			stats.PromptsAllowed++
		case "mask":
			stats.PromptsMasked++
		case "block":
			stats.PromptsBlocked++
			stats.InferenceCallsAvoided++
		case "route":
			stats.PromptsRouted++
			stats.InferenceCallsAvoided++
		case "tag":
			stats.PromptsTagged++
		}

		inferenceCalled := false
		if apiResp.InferenceCalled != nil {
			inferenceCalled = *apiResp.InferenceCalled
		}
		if inferenceCalled {
			stats.InferenceCallsMade++
			stats.PromptTokensForwardedEst += tokenEstimate(apiResp.PromptProcessed)
			stats.OutputsTotal++
			stats.OutputTokensRawEst += tokenEstimate(apiResp.RawModelOutput)

			switch apiResp.PostAction {
			case "allow":
				stats.OutputsAllowed++
			case "mask":
				stats.OutputsMasked++
			case "block":
				stats.OutputsBlocked++
			case "tag":
				stats.OutputsTagged++
			}
			stats.OutputTokensReleasedEst += tokenEstimate(apiResp.FinalOutput)
		}

		record := OutputRecord{
			PromptID:        prompt.PromptID,
			Mode:            cfg.ModeLabel,
			Category:        prompt.Category,
			PreAction:       apiResp.PreAction,
			PreTags:         dedupeTags(apiResp.PreTags),
			PromptOriginal:  prompt.PromptText,
			PromptProcessed: apiResp.PromptProcessed,
			InferenceCalled: inferenceCalled,
			RawModelOutput:  apiResp.RawModelOutput,
			PostAction:      apiResp.PostAction,
			PostTags:        dedupeTags(apiResp.PostTags),
			FinalOutput:     apiResp.FinalOutput,
		}
		records = append(records, record)
	}

	totalElapsedMs := float64(time.Since(start).Milliseconds())
	if totalElapsedMs <= 0 {
		totalElapsedMs = 1
	}
	stats.PostprocessMs = 0
	stats.TotalControlMs = stats.PreprocessMs
	stats.RecordsPerSec = float64(stats.PromptsTotal) / (totalElapsedMs / 1000.0)

	if err := writeOutputJSONL(filepath.Join(outputDir, cfg.ModeLabel+"_output.jsonl"), records); err != nil {
		return stats, err
	}

	return stats, writeSummaryCSV(filepath.Join(outputDir, "run_01.csv"), stats)
}

func writeSummaryCSV(path string, stats SummaryStats) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"mode",
		"prompts_total",
		"prompts_allowed",
		"prompts_masked",
		"prompts_blocked",
		"prompts_routed",
		"prompts_tagged",
		"inference_calls_made",
		"inference_calls_avoided",
		"prompt_tokens_in_est",
		"prompt_tokens_forwarded_est",
		"outputs_total",
		"outputs_allowed",
		"outputs_masked",
		"outputs_blocked",
		"outputs_tagged",
		"output_tokens_raw_est",
		"output_tokens_released_est",
		"preprocess_ms",
		"postprocess_ms",
		"total_control_ms",
		"records_per_sec",
	}
	if err := writer.Write(header); err != nil {
		return err
	}

	row := []string{
		stats.Mode,
		fmt.Sprintf("%d", stats.PromptsTotal),
		fmt.Sprintf("%d", stats.PromptsAllowed),
		fmt.Sprintf("%d", stats.PromptsMasked),
		fmt.Sprintf("%d", stats.PromptsBlocked),
		fmt.Sprintf("%d", stats.PromptsRouted),
		fmt.Sprintf("%d", stats.PromptsTagged),
		fmt.Sprintf("%d", stats.InferenceCallsMade),
		fmt.Sprintf("%d", stats.InferenceCallsAvoided),
		fmt.Sprintf("%d", stats.PromptTokensInEst),
		fmt.Sprintf("%d", stats.PromptTokensForwardedEst),
		fmt.Sprintf("%d", stats.OutputsTotal),
		fmt.Sprintf("%d", stats.OutputsAllowed),
		fmt.Sprintf("%d", stats.OutputsMasked),
		fmt.Sprintf("%d", stats.OutputsBlocked),
		fmt.Sprintf("%d", stats.OutputsTagged),
		fmt.Sprintf("%d", stats.OutputTokensRawEst),
		fmt.Sprintf("%d", stats.OutputTokensReleasedEst),
		fmt.Sprintf("%.3f", stats.PreprocessMs),
		fmt.Sprintf("%.3f", stats.PostprocessMs),
		fmt.Sprintf("%.3f", stats.TotalControlMs),
		fmt.Sprintf("%.2f", stats.RecordsPerSec),
	}
	return writer.Write(row)
}

func main() {
	inputPath := flag.String("input", "../data/prompts/sample_prompts.jsonl", "Path to prompt JSONL input")
	mode := flag.String("mode", "", "Mode to run, or empty for the default set (nocontrol, themis_api_infer)")
	outputDir := flag.String("output-dir", "../results", "Directory for benchmark outputs")
	_ = flag.String("list-dir", "../data/reference_lists", "Reference-list dir (unused in the current action model)")
	actionsPath := flag.String("actions", "../../../policies/boundary-actions.json", "boundary-actions.json (from build_boundary_policy.py)")
	flag.Parse()

	if err := os.MkdirAll(*outputDir, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "create output dir: %v\n", err)
		os.Exit(1)
	}
	prompts, err := loadPrompts(*inputPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "load prompts: %v\n", err)
		os.Exit(1)
	}
	actions, err := loadBoundaryActions(*actionsPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}

	modes := []string{"nocontrol", "themis_api_infer"}
	if *mode != "" {
		modes = []string{*mode}
	}
	identity := func(s string) (string, error) { return s, nil }

	var allStats []BoundaryStats
	for _, m := range modes {
		var stats BoundaryStats
		var rerr error
		switch m {
		case "nocontrol":
			stats, rerr = runEngineInfer(prompts, m, *outputDir, actions, identity)
		case "themis_api_infer", "aergia_api_infer":
			endpointEnv, tokenEnv := "THEMIS_ENDPOINT", "THEMIS_TOKEN"
			if m == "aergia_api_infer" {
				endpointEnv, tokenEnv = "AERGIA_ENDPOINT", "AERGIA_TOKEN"
			}
			cfg, cerr := loadEngineConfig(m, endpointEnv, tokenEnv)
			if cerr != nil {
				fmt.Fprintf(os.Stderr, "config %s: %v\n", m, cerr)
				os.Exit(1)
			}
			client := &http.Client{Timeout: cfg.Timeout}
			proc := func(s string) (string, error) { return callEngineProcess(client, cfg, s) }
			stats, rerr = runEngineInfer(prompts, m, *outputDir, actions, proc)
		default:
			fmt.Fprintf(os.Stderr, "unknown mode %q (supported: nocontrol, themis_api_infer, aergia_api_infer)\n", m)
			os.Exit(1)
		}
		if rerr != nil {
			fmt.Fprintf(os.Stderr, "run %s: %v\n", m, rerr)
			os.Exit(1)
		}
		allStats = append(allStats, stats)
		fmt.Printf("Mode: %-18s | pre: redact %d mask %d route-sig %d block-sig %d | post: redact %d mask %d block-sig %d | prompt tokens %d->%d, output %d->%d\n",
			stats.Mode, stats.PromptsRedacted, stats.PromptsMasked, stats.PromptRouteSignals, stats.PromptBlockSignals,
			stats.OutputsRedacted, stats.OutputsMasked, stats.OutputBlockSignals,
			stats.PromptTokensIn, stats.PromptTokensForwarded, stats.OutputTokensRaw, stats.OutputTokensReleased)
	}

	if err := writeBoundaryCSV(filepath.Join(*outputDir, "run_01.csv"), allStats); err != nil {
		fmt.Fprintf(os.Stderr, "write csv: %v\n", err)
		os.Exit(1)
	}
}
