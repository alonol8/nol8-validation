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
// Integrity: same policy, same corpus, same driver to every engine. By default
// the response is drained and only its status code checked, so the driver stays
// cheap enough not to become the bottleneck. --expected turns on checking every
// response against the oracle - see "response verification" below - at some cost
// in driver CPU, which is why it is opt-in rather than always on. If the driver ever does
// bound a run, the error/overflow columns and the operator notes are where that
// shows; do not over-read a run the driver bounded.

import (
	"bufio"
	"bytes"
	"crypto/md5"
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

// buckets builds the size bands with caller-set caps. The cap is the number of
// DISTINCT bodies held and round-robined per band - it is the fair-comparison
// knob: a small working set lets a software engine (RE2) serve the same inputs
// warm out of CPU cache, which the FPGA can't benefit from, so it silently
// favors RE2. Drive >= a few thousand unique bodies per band so the working set
// blows past any cache and neither engine gets a free ride.
func buckets(capSmall, capMedium, capLarge int) []bucket {
	return []bucket{
		{name: "small", lo: 0, hi: 4096, cap: capSmall},
		{name: "medium", lo: 4097, hi: 65536, cap: capMedium},
		// Upper bound below the ~1MB shared edge request-size cap: bodies at/over
		// it get a 413 on BOTH engines (measured), which would contaminate the
		// throughput numbers rather than measure either engine. Records above this
		// (the corpus "near_limit" band) are simply excluded from the sweep.
		{name: "large", lo: 65537, hi: 786432, cap: capLarge},
	}
}

type corpusBucket struct {
	name   string
	bodies [][]byte // pre-marshaled {"message": ...} request bodies
	// Corpus line number of each body. Bodies are filtered into size buckets,
	// so position within a bucket is not position in the file - and the
	// expected digests are keyed by the latter.
	indices    []int
	totalBytes int64 // sum of body sizes held (for the average)
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
	corpusIndex := -1
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		// Counted over non-blank records only, matching how expected-digests.py
		// numbers them.
		corpusIndex++
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
			cb.indices = append(cb.indices, corpusIndex)
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

// ---- response verification ----
//
// The driver measures how fast an engine answers, not whether the answer is
// right: a 200 carrying corrupted output counts as a success. That gap is wide
// enough to hide a real defect behind a good throughput number, so --expected
// checks every response against what the oracle says it should be.
//
// The expensive half is done once, outside: expected-digests.py walks the
// corpus through the oracle and writes two md5 sums per record, one per
// transformation contract, leaving the hot loop with a hash compare.
//
// Two digests because the engines disagree about overlapping matches and both
// are self-consistent - Aergia reproduces one-byte-one-match, Themis
// every-match-fires. A response is correct if it matches either, and the driver
// reports which, so the contract an engine implements is measured rather than
// assumed. Where a record has no overlaps the digests are identical.
//
// Only the processed message is hashed. The response envelope carries a
// per-request job id, so hashing the whole body would differ on every request
// and report every response as wrong.
type expectation struct {
	oneByteOne  string
	everyMatch  string
}

type verifier struct {
	enabled  bool
	expected []expectation

	checked    atomic.Int64
	matchedOne atomic.Int64 // matched one-byte-one-match where the two differ
	matchedAll atomic.Int64 // matched every-match-fires where the two differ
	agreed     atomic.Int64 // matched, on a record where both contracts agree
	wrong      atomic.Int64
	unparsable atomic.Int64

	sampleMu sync.Mutex
	sample   string
}

// processResponse is the shape the engines answer with; only the transformed
// message is of interest here.
type processResponse struct {
	Result struct {
		Message string `json:"message"`
	} `json:"result"`
}

func newVerifier(expected []expectation) *verifier {
	return &verifier{enabled: len(expected) > 0, expected: expected}
}

func (v *verifier) check(corpusIndex int, payload []byte) {
	if v == nil || !v.enabled || corpusIndex < 0 || corpusIndex >= len(v.expected) {
		return
	}
	want := v.expected[corpusIndex]
	if want.oneByteOne == "" && want.everyMatch == "" {
		return
	}

	var parsed processResponse
	if err := json.Unmarshal(payload, &parsed); err != nil {
		v.unparsable.Add(1)
		v.note(fmt.Sprintf("record %d: response was not JSON", corpusIndex))
		return
	}
	got := fmt.Sprintf("%x", md5.Sum([]byte(parsed.Result.Message)))
	v.checked.Add(1)

	switch {
	case want.oneByteOne == want.everyMatch:
		if got == want.oneByteOne {
			v.agreed.Add(1)
		} else {
			v.wrong.Add(1)
			v.note(fmt.Sprintf("record %d: expected %s, got %s",
				corpusIndex, want.oneByteOne, got))
		}
	case got == want.oneByteOne:
		v.matchedOne.Add(1)
	case got == want.everyMatch:
		v.matchedAll.Add(1)
	default:
		v.wrong.Add(1)
		v.note(fmt.Sprintf("record %d: matched neither contract (%s / %s), got %s",
			corpusIndex, want.oneByteOne, want.everyMatch, got))
	}
}

func (v *verifier) note(message string) {
	v.sampleMu.Lock()
	if v.sample == "" {
		v.sample = message
	}
	v.sampleMu.Unlock()
}

func (v *verifier) report() string {
	if !v.enabled {
		return ""
	}
	wrong := v.wrong.Load() + v.unparsable.Load()
	line := fmt.Sprintf("   verified %d responses: %d correct, %d WRONG",
		v.checked.Load(), v.agreed.Load()+v.matchedOne.Load()+v.matchedAll.Load(), wrong)
	if one, all := v.matchedOne.Load(), v.matchedAll.Load(); one+all > 0 {
		line += fmt.Sprintf(" (of the records where the contracts differ: "+
			"%d one-byte-one-match, %d every-match-fires)", one, all)
	}
	if wrong > 0 {
		line += "\n   !! " + v.sample
	}
	return line
}

// loadExpected reads the two-digest-per-record file written by
// expected-digests.py, in corpus order.
func loadExpected(path string) ([]expectation, error) {
	if path == "" {
		return nil, nil
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var out []expectation
	for _, line := range strings.Split(strings.TrimRight(string(raw), "\n"), "\n") {
		fields := strings.Fields(line)
		switch len(fields) {
		case 0:
			out = append(out, expectation{})
		case 1:
			out = append(out, expectation{fields[0], fields[0]})
		default:
			out = append(out, expectation{fields[0], fields[1]})
		}
	}
	return out, nil
}

func doRequest(client *http.Client, endpoint, token string, body []byte,
	corpusIndex int, v *verifier) error {
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
	// the handshake, not the engine. When verifying, the same drain keeps the
	// bytes instead of discarding them.
	if v != nil && v.enabled {
		payload, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			v.check(corpusIndex, payload)
		}
	} else {
		_, _ = io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	return nil
}

// ---- error classification (diagnostic) ----
//
// The `errors` counter is the number that gates a run; this breaks that same
// number down by cause so an error spike is interpretable (edge 5xx vs peer
// reset vs client timeout vs local dial/port failure) instead of opaque. It
// does NOT change what is measured or the CSV schema - it is a stdout-only
// annotation printed when a cell records errors.
type errClass struct {
	dial, timeout, reset, refused, eof, status4xx, status5xx, other int64
}

func (e *errClass) add(err error) {
	s := err.Error()
	switch {
	case strings.Contains(s, "timeout") || strings.Contains(s, "deadline exceeded"):
		atomic.AddInt64(&e.timeout, 1)
	case strings.Contains(s, "connection reset") || strings.Contains(s, "reset by peer"):
		atomic.AddInt64(&e.reset, 1)
	case strings.Contains(s, "connection refused"):
		atomic.AddInt64(&e.refused, 1)
	case strings.Contains(s, "EOF"):
		atomic.AddInt64(&e.eof, 1)
	// EADDRNOTAVAIL / DNS / dial failures = local-side (port exhaustion lives here).
	case strings.Contains(s, "assign requested address") || strings.Contains(s, "no such host") || strings.Contains(s, "dial "):
		atomic.AddInt64(&e.dial, 1)
	case strings.HasPrefix(s, "status 5"):
		atomic.AddInt64(&e.status5xx, 1)
	case strings.HasPrefix(s, "status 4"):
		atomic.AddInt64(&e.status4xx, 1)
	default:
		atomic.AddInt64(&e.other, 1)
	}
}

func (e *errClass) summary() string {
	return fmt.Sprintf("dial=%d timeout=%d reset=%d refused=%d eof=%d http4xx=%d http5xx=%d other=%d",
		e.dial, e.timeout, e.reset, e.refused, e.eof, e.status4xx, e.status5xx, e.other)
}

// ---- one measurement cell ----

type cellResult struct {
	Engine       string
	Concurrency  int
	Payload      string
	RecordsUsed  int
	AvgBytes     int
	DurationS    float64 // the ISSUING window (workers accept work for exactly this long); rps denominator
	WallElapsedS float64 // MEASURED wall-clock incl. post-deadline drain; > DurationS when requests stalled
	Completed    int64
	Errors       int64
	BytesSent    int64
	Hist         *latHist  // SUCCESS latencies only
	ErrHist      *latHist  // FAILED-request latencies (the stalls a success-only hist can't see)
	StallSeconds float64   // sum of failed-request durations — capacity spent on failures
	ErrClass     *errClass // diagnostic breakdown of Errors (nil if none)
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

// phaseResult carries everything one phase measured. Failed requests are NOT
// discarded: their latency goes into errHist and their duration into stallNanos,
// because a failed request still consumed a worker for its whole duration — time
// a success-only histogram cannot see (a ~3s stall that fails is invisible to it,
// yet it is exactly the capacity the error cost the run).
type phaseResult struct {
	okHist     *latHist
	errHist    *latHist
	completed  int64
	errors     int64
	bytesSent  int64
	stallNanos int64
	elapsed    time.Duration // measured wall-clock, for an honest rps denominator
}

// runPhase drives `concurrency` goroutines in closed loop until `dur` elapses.
// When measure is false (warm-up) it discards timings; the caller runs a warm-up
// phase, then a measured phase, on the same client so connections stay warm.
func runPhase(client *http.Client, endpoint, token string, bodies [][]byte,
	indices []int, concurrency int, dur time.Duration, measure bool,
	ec *errClass, v *verifier) phaseResult {

	phaseStart := time.Now()
	deadline := phaseStart.Add(dur)
	var next uint64
	var completed, errors, bytesSent, stallNanos int64
	okHists := make([]*latHist, concurrency)
	errHists := make([]*latHist, concurrency)

	var wg sync.WaitGroup
	for w := 0; w < concurrency; w++ {
		oh, eh := newLatHist(), newLatHist()
		okHists[w], errHists[w] = oh, eh
		wg.Add(1)
		go func(oh, eh *latHist) {
			defer wg.Done()
			for time.Now().Before(deadline) {
				i := atomic.AddUint64(&next, 1) - 1
				slot := int(i % uint64(len(bodies)))
				body := bodies[slot]
				corpusIndex := -1
				if slot < len(indices) {
					corpusIndex = indices[slot]
				}
				start := time.Now()
				err := doRequest(client, endpoint, token, body, corpusIndex, v)
				lat := time.Since(start)
				if err != nil {
					atomic.AddInt64(&errors, 1)
					if measure {
						atomic.AddInt64(&stallNanos, lat.Nanoseconds())
						eh.record(lat)
						if ec != nil {
							ec.add(err)
						}
					}
					continue
				}
				atomic.AddInt64(&completed, 1)
				atomic.AddInt64(&bytesSent, int64(len(body)))
				if measure {
					oh.record(lat)
				}
			}
		}(oh, eh)
	}
	wg.Wait()
	elapsed := time.Since(phaseStart)

	mergedOk, mergedErr := newLatHist(), newLatHist()
	for _, h := range okHists {
		mergedOk.merge(h)
	}
	for _, h := range errHists {
		mergedErr.merge(h)
	}
	return phaseResult{
		okHist: mergedOk, errHist: mergedErr,
		completed: completed, errors: errors, bytesSent: bytesSent,
		stallNanos: stallNanos, elapsed: elapsed,
	}
}

func runCell(client *http.Client, engine, endpoint, token string, cb *corpusBucket,
	concurrency int, warmup, steady time.Duration, v *verifier) cellResult {

	if warmup > 0 {
		runPhase(client, endpoint, token, cb.bodies, cb.indices, concurrency, warmup,
			false, nil, nil)
	}
	ec := &errClass{}
	pr := runPhase(client, endpoint, token, cb.bodies, cb.indices, concurrency, steady, true, ec, v)

	return cellResult{
		Engine:       engine,
		Concurrency:  concurrency,
		Payload:      cb.name,
		RecordsUsed:  len(cb.bodies),
		AvgBytes:     cb.avgBytes(),
		// rps/throughput use the ISSUING window (steady), not wall-clock: workers
		// accept work for exactly `steady`, so that is the interval the load was
		// applied over. Wall-clock includes post-deadline drain of stalled requests
		// (a single 4s straggler would otherwise halve a 4s cell's reported rps);
		// that lost capacity is reported honestly as StallSeconds instead.
		// Nuance: `completed` includes the few requests that finish DURING the drain
		// (issued before the deadline, completed just after), so rps slightly
		// overstates — on the order of 0.02% at 256 workers and ~3ms mean latency.
		DurationS:    steady.Seconds(),
		WallElapsedS: pr.elapsed.Seconds(),
		Completed:    pr.completed,
		Errors:       pr.errors,
		BytesSent:    pr.bytesSent,
		Hist:         pr.okHist,
		ErrHist:      pr.errHist,
		StallSeconds: float64(pr.stallNanos) / 1e9,
		ErrClass:     ec,
	}
}

// ---- output ----

// Column order is a stable contract: downstream parsers read by index (payload=2,
// errors=7, rps=8, request_mib_s=9, p99=12). New columns are APPENDED, never inserted.
// p50_ms..p999_ms/min/max/mean/tail_overflow are SUCCESS latencies only; failures are
// in err_p50_ms/err_p99_ms/stall_seconds_total. request_mib_s is REQUEST bytes only
// (bytesSent = request body size), not response bytes. duration_s is the ISSUING window
// (the rps denominator); wall_elapsed_s is measured wall-clock incl. stall drain.
var csvHeader = []string{
	"engine", "concurrency", "payload", "records_used", "avg_body_bytes",
	"duration_s", "completed", "errors", "rps", "request_mib_s",
	"p50_ms", "p95_ms", "p99_ms", "p999_ms", "min_ms", "max_ms", "mean_ms", "tail_overflow",
	"err_p50_ms", "err_p99_ms", "stall_seconds_total", "wall_elapsed_s",
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
		fmt.Sprintf("%.3f", ms(r.ErrHist.percentile(0.50))),
		fmt.Sprintf("%.3f", ms(r.ErrHist.percentile(0.99))),
		fmt.Sprintf("%.3f", r.StallSeconds),
		fmt.Sprintf("%.1f", r.WallElapsedS),
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
	expectedPath := flag.String("expected", "",
		"digest file from expected-digests.py; when given, every response is "+
			"checked against the oracle. Costs driver CPU, so a throughput "+
			"figure should state whether it was on")
	output := flag.String("output", "throughput.csv", "output CSV path")
	// Distinct bodies held per band (the fair-comparison / cache-defeat knob).
	capSmall := flag.Int("cap-small", 20000, "distinct small bodies to hold and round-robin")
	capMedium := flag.Int("cap-medium", 8000, "distinct medium bodies to hold and round-robin")
	capLarge := flag.Int("cap-large", 4000, "distinct large bodies to hold and round-robin")
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

	bks := buckets(*capSmall, *capMedium, *capLarge)
	corpus, err := loadCorpus(*input, bks)
	if err != nil {
		fmt.Fprintf(os.Stderr, "load corpus: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("DP4 throughput | engine=%s host=%s GOMAXPROCS=%d\n",
		lbl, hostOf(endpoint), runtime.GOMAXPROCS(0))
	for _, b := range bks {
		cb := corpus[b.name]
		short := ""
		if len(cb.bodies) < b.cap {
			short = fmt.Sprintf("  (WANTED %d - corpus is short on this band; generate more records)", b.cap)
		}
		fmt.Printf("  corpus %-6s: %d distinct bodies, avg %d bytes%s\n", b.name, len(cb.bodies), cb.avgBytes(), short)
	}

	expected, err := loadExpected(*expectedPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "cannot read --expected %s: %v\n", *expectedPath, err)
		os.Exit(1)
	}
	v := newVerifier(expected)
	if v.enabled {
		fmt.Printf("   checking every response against %d expected digests "+
			"(costs driver CPU)\n", len(expected))
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
			r := runCell(client, lbl, endpoint, token, cb, c, warmup, steady, v)
			rows = append(rows, r)
			// Success percentiles are labelled ok- so P99 is never read as
			// unconditional; failures are surfaced as their own p99 + total stall.
			fmt.Printf("rps=%.0f  ok-p50=%.2fms ok-p99=%.2fms  err=%d err-p99=%.2fms stall=%.1fs\n",
				r.rps(), ms(r.Hist.percentile(0.50)), ms(r.Hist.percentile(0.99)),
				r.Errors, ms(r.ErrHist.percentile(0.99)), r.StallSeconds)
			if line := v.report(); line != "" {
				fmt.Println(line)
			}
			if r.Errors > 0 && r.ErrClass != nil {
				fmt.Printf("   errbreak: %s\n", r.ErrClass.summary())
			}
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
