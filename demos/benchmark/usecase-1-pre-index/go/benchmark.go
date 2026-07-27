package main

import (
	"bufio"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type Record struct {
	ID       string `json:"id"`
	Category string `json:"category"`
	Text     string `json:"text"`
}

type OutputRecord struct {
	ID            string `json:"id"`
	Mode          string `json:"mode"`
	Action        string `json:"action"`
	OriginalText  string `json:"original_text"`
	ProcessedText string `json:"processed_text"`
}

type Stats struct {
	Mode               string
	ChunksTotal        int
	ChunksKept         int
	ChunksMasked       int
	ChunksDropped      int
	ChunksRouted       int
	CharsIn            int
	CharsForwarded     int
	TokensInEst        int
	TokensForwardedEst int
	PreprocessMs       float64
	ChunksPerSec       float64
	EmbedCostUnitsEst  int
}

var (
	reEmail      = regexp.MustCompile(`([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})`)
	reSSN        = regexp.MustCompile(`\b(\d{3})-(\d{2})-(\d{4})\b`)
	rePhone      = regexp.MustCompile(`\b(\d{3})-(\d{3})-(\d{4})\b`)
	reAccountID  = regexp.MustCompile(`\bACC-\d{4}-\d{4}\b`)
	reHeader     = regexp.MustCompile(`(?im)^Welcome to .*`)
	reNav        = regexp.MustCompile(`(?im)^Navigation:.*`)
	reFooter     = regexp.MustCompile(`(?im)^Footer:.*`)
	reDisclaimer = regexp.MustCompile(`(?im)^Legal Disclaimer:.*`)
	reCookie     = regexp.MustCompile(`(?im)^Cookie Notice:.*`)
)

func tokenEstimate(s string) int { return len(strings.Fields(s)) }

func cleanBlankLines(s string) string {
	lines := strings.Split(s, "\n")
	out := make([]string, 0, len(lines))
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		out = append(out, line)
	}
	return strings.Join(out, "\n")
}

func transformTraditionalRE2(s string) (string, bool, bool) {
	original := s
	s = reEmail.ReplaceAllString(s, `[MASKED]@$2`)
	s = reSSN.ReplaceAllString(s, `XXX-XX-$3`)
	s = rePhone.ReplaceAllString(s, `XXX-XXX-$3`)
	s = reAccountID.ReplaceAllString(s, `[MASKED_ACCOUNT_ID]`)
	s = reHeader.ReplaceAllString(s, ``)
	s = reNav.ReplaceAllString(s, ``)
	s = reFooter.ReplaceAllString(s, ``)
	s = reDisclaimer.ReplaceAllString(s, ``)
	s = reCookie.ReplaceAllString(s, ``)
	s = cleanBlankLines(s)
	return s, s != original, strings.TrimSpace(s) == ""
}

func transformNol8Sim(s string) (string, string) {
	original := s
	s = reEmail.ReplaceAllString(s, `[MASKED]@$2`)
	s = reSSN.ReplaceAllString(s, `XXX-XX-$3`)
	s = rePhone.ReplaceAllString(s, `XXX-XXX-$3`)
	s = reAccountID.ReplaceAllString(s, `[MASKED_ACCOUNT_ID]`)
	s = reHeader.ReplaceAllString(s, ``)
	s = reNav.ReplaceAllString(s, ``)
	s = reFooter.ReplaceAllString(s, ``)
	s = reDisclaimer.ReplaceAllString(s, ``)
	s = reCookie.ReplaceAllString(s, ``)
	s = cleanBlankLines(s)
	if strings.TrimSpace(s) == "" {
		return "", "drop"
	}
	lower := strings.ToLower(s)
	if strings.Contains(lower, "confidential") && !strings.Contains(lower, "elastic") {
		return s, "route"
	}
	if s != original {
		return s, "mask"
	}
	return s, "keep"
}

func runMode(records []Record, mode string, outputPath string, listMatcher *ReferenceListMatcher) Stats {
	start := time.Now()
	stats := Stats{Mode: mode}

	// Per-engine API modes resolve their own endpoint so one run can compare
	// engines side by side (listMatch on Themis :443 vs Aergia :444).
	apiEndpoint := ""
	switch mode {
	case "themis_api":
		apiEndpoint = os.Getenv("THEMIS_ENDPOINT")
	case "aergia_api":
		apiEndpoint = os.Getenv("AERGIA_ENDPOINT")
	case "nol8_api":
		apiEndpoint = os.Getenv("NOL8_ENDPOINT")
	}

	outFile, err := os.Create(outputPath)
	if err != nil {
		panic(err)
	}
	defer outFile.Close()

	writer := bufio.NewWriter(outFile)
	defer writer.Flush()

	encoder := json.NewEncoder(writer)

	for _, r := range records {
		text := r.Text
		stats.ChunksTotal++
		stats.CharsIn += len(text)
		stats.TokensInEst += tokenEstimate(text)

		switch mode {
		case "nofilter":
			stats.ChunksKept++
			stats.CharsForwarded += len(text)
			stats.TokensForwardedEst += tokenEstimate(text)
			_ = encoder.Encode(OutputRecord{
				ID:            r.ID,
				Mode:          mode,
				Action:        "keep",
				OriginalText:  text,
				ProcessedText: text,
			})

		case "re2":
			out, masked, drop := transformTraditionalRE2(text)
			action := "keep"
			if drop {
				action = "drop"
			} else if masked {
				action = "mask"
			}

			_ = encoder.Encode(OutputRecord{
				ID:            r.ID,
				Mode:          mode,
				Action:        action,
				OriginalText:  text,
				ProcessedText: out,
			})

			if drop {
				stats.ChunksDropped++
				continue
			}
			if masked {
				stats.ChunksMasked++
			} else {
				stats.ChunksKept++
			}
			stats.CharsForwarded += len(out)
			stats.TokensForwardedEst += tokenEstimate(out)

		case "nol8sim":
			out, action := transformNol8Sim(text)
			_ = encoder.Encode(OutputRecord{
				ID:            r.ID,
				Mode:          mode,
				Action:        action,
				OriginalText:  text,
				ProcessedText: out,
			})

			switch action {
			case "drop":
				stats.ChunksDropped++
			case "route":
				stats.ChunksRouted++
			case "mask":
				stats.ChunksMasked++
				stats.CharsForwarded += len(out)
				stats.TokensForwardedEst += tokenEstimate(out)
			case "keep":
				stats.ChunksKept++
				stats.CharsForwarded += len(out)
				stats.TokensForwardedEst += tokenEstimate(out)
			}

		case "nol8_api", "themis_api", "aergia_api":
			out, action, err := callNol8APIEndpoint(text, apiEndpoint)
			if err != nil {
				action = "error"
			}

			_ = encoder.Encode(OutputRecord{
				ID:            r.ID,
				Mode:          mode,
				Action:        action,
				OriginalText:  text,
				ProcessedText: out,
			})

			if err != nil {
				stats.ChunksDropped++
				continue
			}

			switch action {
			case "drop":
				stats.ChunksDropped++
			case "route":
				stats.ChunksRouted++
			case "mask":
				stats.ChunksMasked++
				stats.CharsForwarded += len(out)
				stats.TokensForwardedEst += tokenEstimate(out)
			case "keep":
				stats.ChunksKept++
				stats.CharsForwarded += len(out)
				stats.TokensForwardedEst += tokenEstimate(out)
			}

		case "listmatch":
			if listMatcher == nil {
				panic("listmatch mode requires loaded reference lists")
			}

			out, action := listMatcher.Transform(text)
			_ = encoder.Encode(OutputRecord{
				ID:            r.ID,
				Mode:          mode,
				Action:        action,
				OriginalText:  text,
				ProcessedText: out,
			})

			switch action {
			case "drop":
				stats.ChunksDropped++
			case "route":
				stats.ChunksRouted++
			case "mask":
				stats.ChunksMasked++
				stats.CharsForwarded += len(out)
				stats.TokensForwardedEst += tokenEstimate(out)
			case "keep":
				stats.ChunksKept++
				stats.CharsForwarded += len(out)
				stats.TokensForwardedEst += tokenEstimate(out)
			}

		default:
			panic(fmt.Sprintf("unsupported mode %q", mode))
		}
	}

	elapsed := time.Since(start)
	stats.PreprocessMs = float64(elapsed.Microseconds()) / 1000.0
	if elapsed.Seconds() > 0 {
		stats.ChunksPerSec = float64(stats.ChunksTotal) / elapsed.Seconds()
	}
	stats.EmbedCostUnitsEst = stats.TokensForwardedEst
	return stats
}

func loadRecords(path string) ([]Record, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var records []Record
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		var r Record
		if err := json.Unmarshal(scanner.Bytes(), &r); err != nil {
			return nil, err
		}
		records = append(records, r)
	}
	return records, scanner.Err()
}

func writeCSV(path string, stats []Stats) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	w := csv.NewWriter(file)
	defer w.Flush()

	header := []string{"mode", "chunks_total", "chunks_kept", "chunks_masked", "chunks_dropped", "chunks_routed", "chars_in", "chars_forwarded", "tokens_in_est", "tokens_forwarded_est", "preprocess_ms", "chunks_per_sec", "embed_cost_units_est"}
	if err := w.Write(header); err != nil {
		return err
	}
	for _, s := range stats {
		row := []string{
			s.Mode,
			fmt.Sprintf("%d", s.ChunksTotal),
			fmt.Sprintf("%d", s.ChunksKept),
			fmt.Sprintf("%d", s.ChunksMasked),
			fmt.Sprintf("%d", s.ChunksDropped),
			fmt.Sprintf("%d", s.ChunksRouted),
			fmt.Sprintf("%d", s.CharsIn),
			fmt.Sprintf("%d", s.CharsForwarded),
			fmt.Sprintf("%d", s.TokensInEst),
			fmt.Sprintf("%d", s.TokensForwardedEst),
			fmt.Sprintf("%.3f", s.PreprocessMs),
			fmt.Sprintf("%.2f", s.ChunksPerSec),
			fmt.Sprintf("%d", s.EmbedCostUnitsEst),
		}
		if err := w.Write(row); err != nil {
			return err
		}
	}
	return nil
}

func main() {
	if len(os.Args) < 3 {
		fmt.Println("usage: go run benchmark.go <input.jsonl> <output.csv> [mode]")
		os.Exit(1)
	}

	outputPath := os.Args[2]
	records, err := loadRecords(os.Args[1])
	if err != nil {
		panic(err)
	}

	var modes []string
	if len(os.Args) >= 4 {
		modes = []string{os.Args[3]}
	} else {
		modes = []string{"nofilter", "re2", "listmatch", "nol8sim"}
	}

	allStats := make([]Stats, 0, len(modes))
	resultsDir := filepath.Dir(outputPath)
	var listMatcher *ReferenceListMatcher
	if containsMode(modes, "listmatch") {
		referenceListDir := os.Getenv("REFERENCE_LIST_DIR")
		if referenceListDir == "" {
			referenceListDir = filepath.Join(filepath.Dir(os.Args[1]), "reference_lists")
		}

		var err error
		listMatcher, err = LoadReferenceListMatcher(referenceListDir)
		if err != nil {
			panic(err)
		}
	}
	for _, mode := range modes {
		modeOutputPath := filepath.Join(resultsDir, fmt.Sprintf("%s_output.jsonl", mode))
		allStats = append(allStats, runMode(records, mode, modeOutputPath, listMatcher))
	}

	if err := writeCSV(outputPath, allStats); err != nil {
		panic(err)
	}
	fmt.Printf("wrote %s\n", outputPath)
	for _, s := range allStats {
		fmt.Printf("%s: forwarded_tokens=%d dropped=%d masked=%d kept=%d chunks_per_sec=%.2f\n", s.Mode, s.TokensForwardedEst, s.ChunksDropped, s.ChunksMasked, s.ChunksKept, s.ChunksPerSec)
	}
}

func containsMode(modes []string, want string) bool {
	for _, mode := range modes {
		if mode == want {
			return true
		}
	}
	return false
}
