# Service monitoring

The local console includes a Services table, Process optimization page, and
Blockchain ledger page. `/controlpanelEflow/api/operations` returns an additive
`services` snapshot behind the existing private API authentication.

## Execution and history

- Standalone PyGAD optimization uses its existing single CPU executor. Optimizer
  runs inside decomposition execute in the inference process and forward their
  status, generation progress, and results over the existing IPC connection.
- LAYA decision activity is observed in the inference process. Configuration is
  reported separately from the actual decision engine used on each call.
- Blockchain calls share the existing single wallet executor. Waiting and running
  calls are reported separately from the GPU queue.
- Cancelling an HTTP caller does not mark an executing thread idle. Its slot and
  running status remain occupied until the actual function finishes. Cancellation
  of a waiting request removes its monitoring record from active work.
- Stopping/crashing the inference process closes unfinished stage records. Model
  and pipeline APIs retain their existing response bodies and contracts; progress
  history and final pipeline status are additive metadata.

Each service retains 60 terminal records and aggregate counters for the current
server process. Recent history is in memory and resets on restart. It is not a
database ledger or an import of historical receipts from the client. The queue's
all-services view attaches decomposition stages to their AI request instead of
counting those stages as independent requests.

Only operational metadata is retained: input counts, profiles, numeric objective
metrics, up to 200 generation scores, proposal references, document/transaction
hashes, and receipt block numbers. Task/document bodies, employee identities,
prompts, wallet keys, and full RPC URLs are excluded. Monitoring errors contain
generic operational messages. Existing endpoint error logs remain available.

## Polygon states

Simulation receipts are explicitly marked and never presented as confirmed chain
transactions. The dashboard does not provide transaction-signing controls.
Verification is an explicit read-only action against a retained anchor; simulation
checks are labeled as simulation checks.

Live anchoring records the transaction hash immediately after submission, before
waiting for the mined receipt. A receipt timeout becomes **Confirmation unknown**,
not proof of a failed transaction. A mined reverted receipt is treated as failed.
Certificates assemble caller-supplied receipts; they are not independent proof
that every anchor has been verified.

Connectivity checks read only `eth_chainId` and `eth_blockNumber`. They run in the
background once per minute with five-second request timeouts, reuse the shared
HTTP connection pool, and do not delay dashboard polling. Simulation mode skips
RPC checks. Actual RPC chain IDs are compared with the configured chain ID; a
wrong network is reported separately. Only the RPC hostname is displayed.

Service monitoring does not import or load an LLM, LAYA model, or Web3 at dashboard
refresh time. Native model ownership and the single inference queue are unchanged.

## Validation

Run `server/.venv/Scripts/python.exe -B server/run_tests.py`, `npm run typecheck`,
and `npm run build`. Monitoring regressions cover bounded/redacted history,
thread completion after caller cancellation, waiting cancellation, real Windows
child-process events and cancellation, simulation behavior, RPC chain mismatch and
failures, authenticated API snapshots, and thread-originated SSE logs. Automated
tests use fake RPC responses and simulated Polygon calls; they send no transactions.
