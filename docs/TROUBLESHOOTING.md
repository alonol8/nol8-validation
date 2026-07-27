# Troubleshooting

Operational runbook. Symptom first, then what to check, then the fix.

For *what we have found* rather than *how to fix it now*, see
[FINDINGS.md](FINDINGS.md).

---

## Read this before you restart anything

During the 2026-07-20 outage every readily available signal was wrong, and the
vendor troubleshooting guide's remedy - restart the services - had already been
tried three times without helping. The actual cause was a healthy engine
waiting for a policy, and the fix was one API call.

| signal | what it said | trust it? |
|---|---|---|
| `ARGUS_UPSTREAM_UNAVAILABLE ... no apollo response` | engine unreachable | **no** - says nothing about *why* |
| Vendor guide: "most probably a severe Apollo bug" | restart everything | **no** for this cause |
| `systemctl is-active ares-apollo` | `active` | **no** - active and paused are identical |
| `nolctl doctor` preflight section | `FAIL` on kernel params | **no** - false positive, see OPS-1 |
| Service status string | `data plane PAUSED` | **no** - set once at startup, never updated |
| `grep -c "Rules committed" apollo.log` | `0` | **yes** - this is the real signal |

**Deploy a policy before you restart anything.** It is cheap, non-destructive,
reversible, and the most common cause.

---

## Symptom: pre-flight fails, or every request returns HTTP 503

```
Pre-flight check failed, so no requests were sent.
```
```json
{"error": {"code": "ARGUS_UPSTREAM_UNAVAILABLE", ...
 "RESPONSE_WAIT: request timed out (no apollo response in >2s)"}}
```

### Most likely cause: the data plane is paused awaiting a policy

Apollo boots with its data plane **paused** and un-pauses only when a policy
commits. A host that was restarted without a subsequent deployment sits in this
state indefinitely, answering every request with 503.

From the client this is **indistinguishable** from a genuinely dead engine -
there is no health route and no distinct error code (THM-7).

### Fix - try this first

Any policy works. One rule is enough:

```bash
printf '%s\n' '"SSN" -> "[REDACTED]";' > /tmp/minimal.nol
curl -sS --insecure -X POST "$THEMIS_POLICY_ENDPOINT" \
  -H "Authorization: Bearer $THEMIS_TOKEN" --data-binary @/tmp/minimal.nol
```

Then restore the real ruleset, because the call above **replaced** it:

```bash
validate policy --file artifacts/evidence/reference/tenant-restore-policy.nol --target themis
```

Confirm service is back:

```bash
curl -sS -X POST "$THEMIS_PROCESS_ENDPOINT" \
  -H "Authorization: Bearer $THEMIS_TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"my SSN is here"}'
# expect: {"jid":...,"result":{"message":"my [REDACTED] is here"}}
```

Or simply re-run - the pre-flight probe will tell you.

### If that did not fix it

Now investigate on the Themis host. **Read-only commands:**

```bash
ssh themis-demo
nolctl status
nolctl doctor --full
systemctl show ares-apollo -p StatusText --value
sudo grep -c "Rules committed" /var/lib/ares/apollo/apollo.log   # 0 = never committed
sudo journalctl -u ares-apollo -n 40 --no-pager
sudo tail -40 /var/lib/ares/apollo/apollo.log
```

The line that actually tells you the truth:

```
[orchestrator] WARN: rules not committed (data plane may stay paused)
```

`nolctl status` does not surface it. `nolctl doctor` does not surface it.

**Do not restart services yourself.** The environment belongs to the user;
restarts are theirs to authorise. If it comes to that, the vendor guide's
sequence is:

```bash
sudo systemctl stop iris ares-apollo ares-policyd
sudo systemctl start iris ares-apollo ares-policyd
```

...and note it will come back **paused again** unless a policy is deployed
afterwards.

---

## Symptom: `nolctl doctor` reports FAIL on kernel parameters

```
FAIL cmdline: 2/6 required params present;
     missing hugepages=4, isolcpus=0-11, nohz_full=0-11, rcu_nocbs=0-11
     -> set in GRUB_CMDLINE_LINUX_DEFAULT, sudo update-grub, reboot
```

**Ignore it.** This is a false positive (OPS-1). Check the truth:

```bash
cat /proc/cmdline
# hugepages=16 isolcpus=2-13 nohz_full=2-13 rcu_nocbs=2-13  <- correct
```

`doctor` string-matches one expected topology rather than checking the
parameters are present and sane. **Do not reboot on the strength of this.**

---

## Symptom: report says INCONCLUSIVE, or records are not counted as passes

Expected. Introduced deliberately (FW-3).

When `--replacement-max-length` is in use, two replacement tokens sharing a
prefix within that limit collapse to the same string. A record where the wrong
rule fired then looks identical to one where the right rule fired, so it cannot
be scored as a pass.

Check which tokens collide:

```bash
jq '.stages.comparison.replacement_collisions' artifacts/runs/<RUN_ID>/manifest.json
```

**Fix:** give the affected rules replacements that differ within the first N
characters and regenerate. Or run `compare` without
`--replacement-max-length` - though every long token will then mismatch,
because the runtime truncates at 15 (THM-5).

---

## Symptom: comparison reports mismatches on every record

Almost certainly replacement truncation (THM-5 / KB-001), not a product defect.

The runtime truncates replacements to 15 characters, so
`[FINANCIAL:CREDIT_CARD_NUMBER]` comes back as `[FINANCIAL:CRED`. Compare
without normalization and every one of those is a mismatch.

```bash
validate compare --run <RUN_ID> --replacement-max-length 15
```

Running *without* the flag is the demo mode: it shows the truncation
limitation. It is not a bug in either system.

---

## Symptom: content mismatches on a subset of records

If a minority of records fail with corrupted output - replacement text
appearing at the wrong offset, preceding content destroyed - that is **THM-4
(ISSUE-004)**, the overlapping-match defect.

Check whether the workload contains overlapping literals:

```bash
jq '.overlapping_match_documents' artifacts/runs/<RUN_ID>/generated/generation-manifest.json
```

**Non-zero means the run is not a valid qualification** - it is exercising a
known product defect. Regenerate; current generation refuses to produce
overlapping catalogs.

Detail and reproduction:
[issues/internal/ISSUE-004-corruption-investigation.md](issues/internal/ISSUE-004-corruption-investigation.md)

---

## Symptom: policy deploy fails TLS verification

```
Policy deployment failed TLS verification against ...
```

The control plane presents a self-signed certificate named after an internal
address. Expected in this sandbox (OBS-1):

```bash
export THEMIS_ALLOW_INSECURE_TLS=1
```

It is set in `config/demo.env` and deliberately not hardcoded, so the exception
stays visible. **Not a security finding here** - VPC-only, one team, no
customer traffic.

Setting it on the command line works and overrides the config default (fixed in
FW-5), e.g. `THEMIS_ALLOW_INSECURE_TLS=0 validate policy ...`.

---

## Symptom: a long run dies partway through SSH

Detach it:

```bash
ssh nol8-demo 'cd /opt/nol8/nol8-validation && source .venv/bin/activate && \
  nohup setsid validate run --run <RUN_ID> --target themis \
  > /tmp/run.log 2>&1 &'
```

To poll, grep the log for a completion marker. **Do not use
`pgrep -f "validate run"`** - it matches its own command line and hangs.

```bash
ssh nol8-demo 'tail -3 /tmp/run.log'
```

Interrupted runs keep their evidence: output is appended durably, so completed
records survive.

---

## Symptom: `validate compare` refuses a limited run

`--limit N` produces a partial corpus, and `compare` requires a complete one.
Expected. Generate a smaller workload instead of limiting a large one.

---

## Where things run

| | address | runs |
|---|---|---|
| `nol8-demo` (`data-streamer`) | 10.8.10.40 | **nothing** - client box, our checkout at `/opt/nol8/nol8-validation` |
| `themis-demo` | 10.10.1.254 | iris, apollo, policyd |
| process endpoint | 10.8.11.254:443 | argus edge, `/v1/process` only |
| aergia control plane | 10.10.1.127 | |

`nol8-demo` has no containers and no Themis processes. If you are looking for
service logs, you want `themis-demo`.

**Treat `themis-demo` with care.** Policy deploys via the API are fine and are
the recovery path. Service restarts and system changes are the user's to make.

---

## Health check by hand

```bash
ssh nol8-demo 'cd /opt/nol8/nol8-validation && set -a && source .env && \
  source config/demo.env && set +a && \
  curl -sS --max-time 20 -w "\nHTTP %{http_code} | %{time_total}s\n" \
  -X POST "$THEMIS_PROCESS_ENDPOINT" -H "Authorization: Bearer $THEMIS_TOKEN" \
  -H "Content-Type: application/json" -d "{\"message\":\"hello\"}"'
```

| response | meaning |
|---|---|
| 200 with `result.message` | healthy |
| 503 `ARGUS_UPSTREAM_UNAVAILABLE` | paused awaiting policy, **or** engine down |
| 401 / 403 | credential rejected - check `.env` |
| 404 | wrong path; `/v1/process` is the only route |
| connection failure | not on the VPN, or wrong host |

There is no `/health` route. Sixteen candidates were tried; all 404 (THM-7).
