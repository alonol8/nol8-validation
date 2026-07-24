package main

// Data Point 4 - throughput at load.
//
// DP1-DP3 prove correctness, engine parity, and payload reduction one request
// at a time, where ~97% of a call is network + TLS and the engine sits inside
// the measurement noise. This driver does the opposite: it holds N requests in
// flight continuously against ONE engine and measures how much work it sustains
// and what the latency tail does as N climbs. Run it once per engine on the
// identical policy + corpus and lay the two curves side by side - that is where
// a fixed FPGA pipeline is expected to hold flat past where a CPU RE2 engine
// saturates. If the network dominates all the way up, the flat curves say so;
// either way the data is the finding.
//
// Model: closed-loop. `concurrency` goroutines each loop {pick next record ->
// POST /v1/process -> read+discard -> record latency} until the phase deadline.
// So exactly `concurrency` requests are in flight at all times, and sustained
// throughput = completed / elapsed. HTTP/1.1 keep-alive with a connection pool
// sized to the concurrency, so `concurrency` maps to real parallel connections
// (not HTTP/2 streams multiplexed onto one) and both engines are driven the
// same way. A warm-up phase (discarded) opens the pool and lets any RE2 warm-up
// / GC settle before the measured steady-state phase.
//
// Integrity: same policy, same corpus, same driver to every engine. We do NOT
// parse or validate the response body here (DP1-DP3 own correctness); we drain
// it and check the status code, so the driver stays cheap enough to not become
// the bottleneck. If it ever does, the error/overflow columns and the operator
// notes are where that shows - do not over-read a run the driver bounded.

import (
	"bufio"
	"bytes"
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// ---- payload buckets ----
//
// Records are classified by request-body size into three bands drawn from the
// enterprise-dlp size distribution, so a "large" cell really does push large
// bodies through the matcher (where fixed per-request overhead stops dominating).
type bucket struct {
	name string
	lo   int // inclusive lower bound, bytes
	hi   int // inclusive upper bound, bytes (0 = no upper bound)
	cap  int // max distinct bodies held (bounds driver memory; large bodies are big)
}

func defaultBuckets() []bucket {
	return []bucket{
		{name: "small", lo: 0, hi: 4096, cap: 8192},
		{name: "medium", lo: 4097, hi: 65536, cap: 2048},
		// Upper bound below the ~1MB shared edge request-size cap: bodies at/over
		// it get a 413 on BOTH engines (measured), which would contaminate the
		// throughput numbers rather than measure either engine. Records above this
		// (the corpus "near_limit" band) are simply excluded from the sweep.
		{name: "large", lo: 65537, hi: 786432, cap: 512},
	}
}

type corpusBucket struct {
	name       string
	bodies     [][]byte // pre-marshaled {"message": ...} request bodies
	totalBytes int64    // sum of body sizes held (for the average)
}

func (c *corpusBucket) avgBytes() int {
	if len(c.bodies) == 0 {
		return 0
	}
	return int(c.totalBytes / int64(len(c.bodies)))
}

type inputRecord struct {
	Message string `json:"message"`
}

// loadCorpus reads the generated input.jsonl, marshals each record into the
// engine's request body once, and files it into its size bucket up to that
// bucket's cap. Pre-marshaling keeps the hot loop free of JSON encoding.
func loadCorpus(path string, buckets []bucket) (map[string]*corpusBucket, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	out := make(map[string]*corpusBucket, len(buckets))
	for _, b := range buckets {
		out[b.name] = &corpusBucket{name: b.name}
	}

	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 1024*1024), 8*1024*1024) // records reach ~1MB
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var rec inputRecord
		if err := json.Unmarshal(line, &rec); err != nil {
			return nil, fmt.Errorf("parse input line: %w", err)
		}
		size := len(rec.Message)
		for _, b := range buckets {
			if size < b.lo || (b.hi > 0 && size > b.hi) {
				continue
			}
			cb := out[b.name]
			if len(cb.bodies) >= b.cap {
				break
			}
			body, err := json.Marshal(map[string]string{"message": rec.Message})
			if err != nil {
				return nil, err
			}
			cb.bodies = append(cb.bodies, body)
			cb.totalBytes += int64(len(body))
			break
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

// ---- transport ----

func buildClient(maxConc int, timeout time.Duration, insecure bool) *http.Client {
	tr := &http.Transport{
		MaxIdleConns:        maxConc * 2,
		MaxIdleConnsPerHost: maxConc, // keep every parallel connection alive between requests
		IdleConnTimeout:     120 * time.Second,
		// Force HTTP/1.1: `concurrency` must mean `concurrency` real connections,
		// not streams multiplexed over one HTTP/2 socket. Both engines get the
		// same treatment, so the comparison is clean.
		ForceAttemptHTTP2: false,
		TLSNextProto:      map[string]func(string, *tls.Conn) http.RoundTripper{},
	}
	if insecure {
		tr.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
	}
	return &http.Client{Transport: tr, Timeout: timeout}
}

func doRequest(client *http.Client, endpoint, token string, body []byte) error {
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	// Drain fully so the connection is returned to the pool for reuse; a
	// half-read body forces a new TLS handshake next time and would measure
	// the handshake, not the engine.
	_, _ = io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	return nil
}

// ---- one measurement cell ----

type cellResult struct {
	Engine      string
	Concurrency int
	Payload     string
	RecordsUsed int
	AvgBytes    int
	DurationS   float64
	Completed   int64
	Errors      int64
	BytesSent   int64
	Hist        *latHist
}

func (r cellResult) rps() float64 {
	if r.DurationS <= 0 {
		return 0
	}
	return float64(r.Completed) / r.DurationS
}

func (r cellResult) throughputMiBs() float64 {
	if r.DurationS <= 0 {
		return 0
	}
	return float64(r.BytesSent) / r.DurationS / (1024 * 1024)
}

// overflowCount is the number of samples that landed past the histogram's top
// resolved edge (60s) - surfaced so a tail beyond resolution can't hide.
func (r cellResult) overflow() int64 {
	if r.Hist == nil || len(r.Hist.buckets) == 0 {
		return 0
	}
	return r.Hist.buckets[len(r.Hist.buckets)-1]
}

// runPhase drives `concurrency` goroutines in closed loop until `dur` elapses.
// When measure is false (warm-up) it discards timings; the caller runs a warm-up
// phase, then a measured phase, on the same client so connections stay warm.
func runPhase(client *http.Client, endpoint, token string, bodies [][]byte,
	concurrency int, dur time.Duration, measure bool) (*latHist, int64, int64, int64) {

	deadline := time.Now().Add(dur)
	var next uint64
	var completed, errors, bytesSent int64
	hists := make([]*latHist, concurrency)

	var wg sync.WaitGroup
	for w := 0; w < concurrency; w++ {
		h := newLatHist()
		hists[w] = h
		wg.Add(1)
		go func(h *latHist) {
			defer wg.Done()
			for time.Now().Before(deadline) {
				i := atomic.AddUint64(&next, 1) - 1
				body := bodies[int(i%uint64(len(bodies)))]
				start := time.Now()
				err := doRequest(client, endpoint, token, body)
				lat := time.Since(start)
				if err != nil {
					atomic.AddInt64(&errors, 1)
					continue
				}
				atomic.AddInt64(&completed, 1)
				atomic.AddInt64(&bytesSent, int64(len(body)))
				if measure {
					h.record(lat)
				}
			}
		}(h)
	}
	wg.Wait()

	merged := newLatHist()
	for _, h := range hists {
		merged.merge(h)
	}
	return merged, completed, errors, bytesSent
}

func runCell(client *http.Client, engine, endpoint, token string, cb *corpusBucket,
	concurrency int, warmup, steady time.Duration) cellResult {

	if warmup > 0 {
		runPhase(client, endpoint, token, cb.bodies, concurrency, warmup, false)
	}
	hist, completed, errors, bytesSent := runPhase(
		client, endpoint, token, cb.bodies, concurrency, steady, true)

	return cellResult{
		Engine:      engine,
		Concurrency: concurrency,
		Payload:     cb.name,
		RecordsUsed: len(cb.bodies),
		AvgBytes:    cb.avgBytes(),
		DurationS:   steady.Seconds(),
		Completed:   completed,
		Errors:      errors,
		BytesSent:   bytesSent,
		Hist:        hist,
	}
}

// ---- output ----

var csvHeader = []string{
	"engine", "concurrency", "payload", "records_used", "avg_body_bytes",
	"duration_s", "completed", "errors", "rps", "throughput_mib_s",
	"p50_ms", "p95_ms", "p99_ms", "p999_ms", "min_ms", "max_ms", "mean_ms", "tail_overflow",
}

func ms(d time.Duration) float64 { return float64(d.Microseconds()) / 1000.0 }

func (r cellResult) row() []string {
	return []string{
		r.Engine,
		strconv.Itoa(r.Concurrency),
		r.Payload,
		strconv.Itoa(r.RecordsUsed),
		strconv.Itoa(r.AvgBytes),
		fmt.Sprintf("%.1f", r.DurationS),
		strconv.FormatInt(r.Completed, 10),
		strconv.FormatInt(r.Errors, 10),
		fmt.Sprintf("%.1f", r.rps()),
		fmt.Sprintf("%.2f", r.throughputMiBs()),
		fmt.Sprintf("%.3f", ms(r.Hist.percentile(0.50))),
		fmt.Sprintf("%.3f", ms(r.Hist.percentile(0.95))),
		fmt.Sprintf("%.3f", ms(r.Hist.percentile(0.99))),
		fmt.Sprintf("%.3f", ms(r.Hist.percentile(0.999))),
		fmt.Sprintf("%.3f", ms(r.Hist.min())),
		fmt.Sprintf("%.3f", ms(r.Hist.max())),
		fmt.Sprintf("%.3f", ms(r.Hist.mean())),
		strconv.FormatInt(r.overflow(), 10),
	}
}

func writeCSV(path string, rows []cellResult) error {
	var b strings.Builder
	b.WriteString(strings.Join(csvHeader, ",") + "\n")
	for _, r := range rows {
		b.WriteString(strings.Join(r.row(), ",") + "\n")
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}

// ---- driver ----

func parseIntList(s string) ([]int, error) {
	var out []int
	for _, p := range strings.Split(s, ",") {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		v, err := strconv.Atoi(p)
		if err != nil {
			return nil, fmt.Errorf("bad integer %q: %w", p, err)
		}
		out = append(out, v)
	}
	sort.Ints(out)
	return out, nil
}

func maxInt(xs []int) int {
	m := 0
	for _, x := range xs {
		if x > m {
			m = x
		}
	}
	return m
}

func main() {
	engine := flag.String("engine", "themis", "engine to drive: themis | aergia (selects endpoint/token env)")
	label := flag.String("label", "", "engine label for the CSV (default: --engine value)")
	input := flag.String("input", "input.jsonl", "generated corpus (input.jsonl with {message})")
	concStr := flag.String("concurrency", "1,8,32,128,512,1024", "concurrency levels to sweep")
	payloadStr := flag.String("payloads", "small,medium,large", "payload buckets to sweep")
	warmupS := flag.Int("warmup", 10, "warm-up seconds per cell (discarded)")
	durationS := flag.Int("duration", 30, "measured steady-state seconds per cell")
	timeoutMs := flag.Int("timeout-ms", 15000, "per-request timeout")
	insecure := flag.Bool("insecure", false, "skip TLS verification (internal certs)")
	output := flag.String("output", "throughput.csv", "output CSV path")
	flag.Parse()

	lbl := *label
	if lbl == "" {
		lbl = *engine
	}

	endpointEnv, tokenEnv := "THEMIS_ENDPOINT", "THEMIS_TOKEN"
	if *engine == "aergia" {
		endpointEnv, tokenEnv = "AERGIA_ENDPOINT", "AERGIA_TOKEN"
	}
	endpoint := strings.TrimSpace(os.Getenv(endpointEnv))
	if endpoint == "" {
		fmt.Fprintf(os.Stderr, "%s is required for engine %q\n", endpointEnv, *engine)
		os.Exit(1)
	}
	token := strings.TrimSpace(os.Getenv(tokenEnv))

	concurrency, err := parseIntList(*concStr)
	if err != nil || len(concurrency) == 0 {
		fmt.Fprintf(os.Stderr, "bad --concurrency: %v\n", err)
		os.Exit(1)
	}
	wantPayloads := strings.Split(*payloadStr, ",")

	buckets := defaultBuckets()
	corpus, err := loadCorpus(*input, buckets)
	if err != nil {
		fmt.Fprintf(os.Stderr, "load corpus: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("DP4 throughput | engine=%s host=%s GOMAXPROCS=%d\n",
		lbl, hostOf(endpoint), runtime.GOMAXPROCS(0))
	for _, b := range buckets {
		cb := corpus[b.name]
		fmt.Printf("  corpus %-6s: %d bodies held, avg %d bytes\n", b.name, len(cb.bodies), cb.avgBytes())
	}

	client := buildClient(maxInt(concurrency), time.Duration(*timeoutMs)*time.Millisecond, *insecure)
	warmup := time.Duration(*warmupS) * time.Second
	steady := time.Duration(*durationS) * time.Second

	var rows []cellResult
	for _, pName := range wantPayloads {
		pName = strings.TrimSpace(pName)
		cb, ok := corpus[pName]
		if !ok {
			fmt.Fprintf(os.Stderr, "unknown payload bucket %q; skipping\n", pName)
			continue
		}
		if len(cb.bodies) == 0 {
			fmt.Fprintf(os.Stderr, "payload bucket %q is empty in this corpus; skipping\n", pName)
			continue
		}
		for _, c := range concurrency {
			fmt.Printf(">> %s | conc=%-4d payload=%-6s (warm %ds + measure %ds) ... ", lbl, c, pName, *warmupS, *durationS)
			r := runCell(client, lbl, endpoint, token, cb, c, warmup, steady)
			rows = append(rows, r)
			fmt.Printf("rps=%.0f  p50=%.2fms p99=%.2fms p99.9=%.2fms  err=%d\n",
				r.rps(), ms(r.Hist.percentile(0.50)), ms(r.Hist.percentile(0.99)),
				ms(r.Hist.percentile(0.999)), r.Errors)
			// Rewrite after every cell so a long sweep that is interrupted still
			// leaves the cells it did finish.
			if err := writeCSV(*output, rows); err != nil {
				fmt.Fprintf(os.Stderr, "write csv: %v\n", err)
				os.Exit(1)
			}
		}
	}
	fmt.Printf(">> wrote %s (%d cells)\n", *output, len(rows))
}

func hostOf(endpoint string) string {
	s := endpoint
	if i := strings.Index(s, "://"); i >= 0 {
		s = s[i+3:]
	}
	if i := strings.IndexAny(s, "/"); i >= 0 {
		s = s[:i]
	}
	return s
}
