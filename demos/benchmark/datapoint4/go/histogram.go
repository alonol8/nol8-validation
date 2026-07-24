package main

// A dependency-free latency histogram for percentile estimation.
//
// We can't `go get` an HDR library on the offline hosts and, more importantly,
// we want every number here to come from code we can read. This is a
// log-scaled histogram: bucket edges grow geometrically (1% apart), so a fixed
// ~1,800 buckets cover 1us..60s at 1% relative precision on any percentile -
// far tighter than we need to tell "flat p99" from "kneed p99". Each load
// goroutine keeps its own copy (a few KB) and they are merged at the end, so
// there is no shared counter to contend on at high concurrency (a shared mutex
// or atomic-per-sample would make the *driver* the bottleneck we are trying to
// measure the engine past).

import (
	"math"
	"time"
)

const (
	histMinNs  = 1000.0 // 1us: samples at or below land in bucket 0
	histGrowth = 1.01   // 1% wider per bucket -> ~1% percentile precision
	histMaxNs  = 60e9   // 60s: the top resolved edge; beyond it is overflow
)

// histBucketCount is the number of geometric buckets from histMinNs to histMaxNs.
var histBucketCount = func() int {
	return int(math.Log(histMaxNs/histMinNs)/math.Log(histGrowth)) + 2
}()

type latHist struct {
	buckets []int64
	count   int64
	sumNs   float64
	minNs   int64
	maxNs   int64
}

func newLatHist() *latHist {
	return &latHist{buckets: make([]int64, histBucketCount), minNs: math.MaxInt64}
}

func bucketIndex(ns int64) int {
	if ns <= int64(histMinNs) {
		return 0
	}
	idx := int(math.Log(float64(ns)/histMinNs)/math.Log(histGrowth)) + 1
	if idx >= histBucketCount {
		return histBucketCount - 1
	}
	return idx
}

// bucketRepNs is the representative latency of a bucket: the geometric midpoint
// of its edges, so percentile readouts sit inside the bucket they fall in.
func bucketRepNs(idx int) float64 {
	if idx <= 0 {
		return histMinNs
	}
	return histMinNs * math.Pow(histGrowth, float64(idx)-0.5)
}

func (h *latHist) record(d time.Duration) {
	ns := int64(d)
	if ns < 0 {
		ns = 0
	}
	h.count++
	h.sumNs += float64(ns)
	if ns < h.minNs {
		h.minNs = ns
	}
	if ns > h.maxNs {
		h.maxNs = ns
	}
	h.buckets[bucketIndex(ns)]++
}

func (h *latHist) merge(o *latHist) {
	for i := range h.buckets {
		h.buckets[i] += o.buckets[i]
	}
	h.count += o.count
	h.sumNs += o.sumNs
	if o.minNs < h.minNs {
		h.minNs = o.minNs
	}
	if o.maxNs > h.maxNs {
		h.maxNs = o.maxNs
	}
}

// percentile returns the p-quantile (0..1). The exact max is used for the top
// bucket so the tail is never understated by bucket rounding.
func (h *latHist) percentile(p float64) time.Duration {
	if h.count == 0 {
		return 0
	}
	target := int64(math.Ceil(p * float64(h.count)))
	if target < 1 {
		target = 1
	}
	var cum int64
	for i, c := range h.buckets {
		cum += c
		if cum >= target {
			rep := bucketRepNs(i)
			if rep > float64(h.maxNs) {
				return time.Duration(h.maxNs)
			}
			return time.Duration(int64(rep))
		}
	}
	return time.Duration(h.maxNs)
}

func (h *latHist) mean() time.Duration {
	if h.count == 0 {
		return 0
	}
	return time.Duration(int64(h.sumNs / float64(h.count)))
}

func (h *latHist) min() time.Duration {
	if h.count == 0 {
		return 0
	}
	return time.Duration(h.minNs)
}

func (h *latHist) max() time.Duration {
	return time.Duration(h.maxNs)
}
