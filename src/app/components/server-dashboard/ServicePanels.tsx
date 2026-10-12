import { useState } from "react";
import { Button } from "@vibe/button";
import { ArrowUpRight, Inbox, ShieldCheck } from "lucide-react";
import {
  verifyAnchor,
  type OperationsSnapshot,
  type ServiceRun,
  type ServicesSnapshot,
  type ServiceRuntime,
  type QueueTelemetry,
} from "../../services/operationsService";
import type { DashboardView } from "../ModelSidebar";

export const serviceLabels = {
  pygad: "PyGAD",
  laya: "LAYA",
  blockchain: "Blockchain",
};
const readable = (value?: string) => (value ? value.replaceAll("_", " ") : "—");
const number = (value?: number, digits = 1) =>
  value == null
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
const time = (value?: number | null) =>
  value == null
    ? "—"
    : new Date(value * 1000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
const elapsed = (run: ServiceRun) =>
  `${number(run.duration_ms == null ? Math.max(0, Date.now() / 1000 - (run.started_at ?? run.submitted_at)) : run.duration_ms / 1000, 2)}s`;
export function RunState({ run }: { run: ServiceRun }) {
  let label: string = readable(run.status),
    tone = "";
  if (run.status === "running") {
    label = run.metadata.tx_hash ? "Awaiting receipt" : "Running";
    tone = "blue";
  } else if (run.status === "failed") {
    label = "Failed";
    tone = "negative";
  } else if (run.status === "unconfirmed") label = "Confirmation unknown";
  else if (run.status === "completed") {
    if (run.service !== "blockchain") {
      label = "Completed";
      tone = "positive";
    } else if (run.metadata.simulated) label = "Simulated";
    else if (run.operation === "verify_on_chain") {
      label = run.metadata.valid ? "Hash matched" : "Hash not verified";
      tone = run.metadata.valid ? "positive" : "negative";
    } else if (
      run.operation.startsWith("anchor") &&
      run.metadata.block_number != null
    ) {
      label = "Confirmed";
      tone = "positive";
    } else label = "Completed";
  }
  return (
    <span className="status-text">
      <i className={`status-dot ${tone}`} />
      {label}
    </span>
  );
}
function NoRuns({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <Inbox size={27} strokeWidth={1.3} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
function MissingTelemetry({ online }: { online: boolean }) {
  return (
    <div className="panel">
      <NoRuns
        title={online ? "Service telemetry unavailable" : "Server offline"}
        detail={
          online
            ? "Waiting for service monitoring from the backend."
            : "Connect the server to see service activity."
        }
      />
    </div>
  );
}
function SessionFoot({ services }: { services: ServicesSnapshot }) {
  return (
    <p className="monitor-footnote">
      Current server session since {time(services.started_at)}. Up to{" "}
      {services.history_limit} recent runs per service; history resets when the
      server restarts.
    </p>
  );
}
function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail?: string;
}) {
  return (
    <div className="summary-stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

export function ServicesOverview({
  operations,
  onViewChange,
}: {
  operations: OperationsSnapshot | null;
  onViewChange: (view: DashboardView) => void;
}) {
  const services = operations?.services;
  const describe = (
    runtime?: ServiceRuntime,
    available = true,
    idle = "Available",
  ) =>
    !runtime
      ? "Unavailable"
      : runtime.running
        ? "Running"
        : runtime.waiting
          ? "Waiting"
          : !available
            ? "Unavailable"
            : idle;
  const workload = (runtime?: ServiceRuntime) =>
    runtime ? `${runtime.running} running · ${runtime.waiting} waiting` : "—";
  const rows = [
    {
      name: "AI inference",
      state: operations?.queue.worker_online
        ? operations.queue.processing
          ? "Processing"
          : "Ready"
        : "Unavailable",
      workload: operations
        ? `${operations.queue.processing} processing · ${operations.queue.waiting} waiting`
        : "—",
      last: operations?.inference?.recent_runs.at(-1)?.completed_at,
      detail: operations?.model.loaded ?? "Model loads on demand",
      view: "models" as DashboardView,
    },
    {
      name: "LAYA decisions",
      state: describe(services?.laya, true, "On demand"),
      workload: workload(services?.laya),
      last: services?.laya.recent_runs[0]?.completed_at,
      detail: services
        ? `${readable(services.laya.mode)} mode · ${services.laya.device}`
        : "No telemetry",
      view: "queue" as DashboardView,
    },
    {
      name: "PyGAD optimizer",
      state: describe(services?.pygad, services?.pygad.available),
      workload: workload(services?.pygad),
      last: services?.pygad.recent_runs[0]?.completed_at,
      detail: services
        ? `${readable(services.pygad.default_profile)} profile · CPU`
        : "No telemetry",
      view: "optimization" as DashboardView,
    },
    {
      name: "Polygon ledger",
      state: describe(
        services?.blockchain,
        services?.blockchain.available,
        services?.blockchain.mode === "simulation"
          ? "Simulation"
          : services?.rpc.state === "connected"
            ? "RPC connected"
            : "RPC not connected",
      ),
      workload: workload(services?.blockchain),
      last: services?.blockchain.recent_runs[0]?.completed_at,
      detail: services
        ? `${services.blockchain.network} · ${services.blockchain.mode}`
        : "No telemetry",
      view: "blockchain" as DashboardView,
    },
  ];
  return (
    <section className="services-overview">
      <div className="section-heading">
        <h2>Services</h2>
        <span className="subtle">Execution and availability</span>
      </div>
      <div className="panel table-scroll">
        <table className="server-table service-overview-table">
          <thead>
            <tr>
              <th>Service</th>
              <th>State</th>
              <th>Workload</th>
              <th>Last activity</th>
              <th>Configuration</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name}>
                <td>
                  <button
                    className="table-link"
                    onClick={() => onViewChange(row.view)}
                  >
                    {row.name}
                    <ArrowUpRight size={13} />
                  </button>
                </td>
                <td>{row.state}</td>
                <td>{row.workload}</td>
                <td>{time(row.last)}</td>
                <td className="subtle">{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ServiceWorkTable({
  runs,
  title = "No active service jobs",
  detail = "CPU optimization and ledger calls will appear here when requested.",
}: {
  runs: ServiceRun[];
  title?: string;
  detail?: string;
}) {
  return (
    <div className="panel table-scroll">
      {runs.length ? (
        <table className="server-table">
          <thead>
            <tr>
              <th>Service / run</th>
              <th>Operation</th>
              <th>Source</th>
              <th>State</th>
              <th>Progress</th>
              <th>Elapsed</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id}>
                <td>
                  <strong>{serviceLabels[run.service]}</strong>
                  <small className="table-secondary job-id">
                    {run.run_id.slice(0, 8)}
                  </small>
                </td>
                <td>{readable(run.operation)}</td>
                <td>
                  {run.origin === "decomposition"
                    ? "AI pipeline"
                    : "Standalone"}
                </td>
                <td>
                  <RunState run={run} />
                </td>
                <td>
                  {run.metadata.generation != null
                    ? `${run.metadata.generation} / ${run.metadata.generations} generations`
                    : run.metadata.tx_hash
                      ? "Transaction submitted"
                      : "—"}
                </td>
                <td>{elapsed(run)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <NoRuns title={title} detail={detail} />
      )}
    </div>
  );
}

function FitnessChart({ values }: { values: number[] }) {
  if (values.length < 2)
    return (
      <p className="field-help">
        Generation history appears after an optimization finishes.
      </p>
    );
  const low = Math.floor(Math.min(...values)),
    high = Math.max(low + 1, Math.ceil(Math.max(...values)));
  const path = values
    .map(
      (value, i) =>
        `${i ? "L" : "M"}${30 + (i / (values.length - 1)) * 570},${83 - ((value - low) / (high - low)) * 64}`,
    )
    .join(" ");
  return (
    <div className="fitness-chart">
      <svg
        viewBox="0 0 620 105"
        role="img"
        aria-label={`Best fitness over ${values.length} generations. First ${values[0]}, last ${values.at(-1)}.`}
      >
        <text x="24" y="22" textAnchor="end">
          {high}
        </text>
        <text x="24" y="86" textAnchor="end">
          {low}
        </text>
        <line x1="30" y1="83" x2="600" y2="83" stroke="#e8eaf1" />
        <path
          d={path}
          fill="none"
          stroke="var(--server-blue)"
          strokeWidth="2"
        />
        <text x="30" y="102">
          Generation 1
        </text>
        <text x="600" y="102" textAnchor="end">
          Generation {values.length}
        </text>
      </svg>
    </div>
  );
}

export function OptimizationPanel({
  services,
  online,
}: {
  services?: ServicesSnapshot;
  online: boolean;
}) {
  if (!services) return <MissingTelemetry online={online} />;
  const runtime = services.pygad;
  const latest = runtime.recent_runs.find((run) => run.status === "completed");
  const metrics = latest?.metadata.metrics;
  return (
    <>
      <div className="summary-grid">
        <Stat
          label="Running"
          value={runtime.running}
          detail="CPU work across both execution paths"
        />
        <Stat
          label="Waiting"
          value={runtime.waiting}
          detail="Standalone optimization requests"
        />
        <Stat
          label="Last fitness score"
          value={number(latest?.metadata.fitness_score, 2)}
          detail="Optimization objective score"
        />
        <Stat
          label="Last run duration"
          value={latest ? elapsed(latest) : "—"}
          detail={
            latest
              ? `Completed ${time(latest.completed_at)}`
              : "No completed optimization yet"
          }
        />
      </div>
      <div className="service-layout">
        <section className="panel">
          <div className="panel-header">
            <h2>Optimizer</h2>
            <span className="status-text">
              <i
                className={`status-dot ${runtime.available ? "positive" : "negative"}`}
              />
              {runtime.available ? "Available" : "Dependency unavailable"}
            </span>
          </div>
          <div className="panel-body">
            <div className="metric-line">
              <span>Default decomposition profile</span>
              <strong>{readable(runtime.default_profile)}</strong>
            </div>
            <div className="metric-line">
              <span>Last successful profile</span>
              <strong>{readable(latest?.metadata.profile)}</strong>
            </div>
            <div className="metric-line">
              <span>Last input size</span>
              <strong>
                {latest
                  ? `${latest.metadata.tasks} tasks · ${latest.metadata.employees} employees`
                  : "—"}
              </strong>
            </div>
            <p className="field-help">
              {runtime.execution} PyGAD is skipped when decomposition has no
              employee context.
            </p>
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Last optimization result</h2>
            <span className="subtle">
              {latest ? time(latest.completed_at) : "No result yet"}
            </span>
          </div>
          <div className="panel-body">
            <div className="result-metrics">
              <div>
                <span>Skill match</span>
                <strong>{number(metrics?.skill_match_score)}</strong>
              </div>
              <div>
                <span>Workload variance</span>
                <strong>{number(metrics?.workload_variance, 2)}</strong>
              </div>
              <div>
                <span>Schedule duration</span>
                <strong>
                  {metrics?.makespan_days == null
                    ? "—"
                    : `${number(metrics.makespan_days)} days`}
                </strong>
              </div>
              <div>
                <span>Source budget</span>
                <strong>{number(metrics?.total_budget, 2)}</strong>
              </div>
            </div>
            <FitnessChart values={latest?.metadata.generation_history ?? []} />
            <p className="field-help">
              Fitness measures the configured optimization objective. It is not
              AI confidence or a guarantee of plan quality.
            </p>
          </div>
        </section>
      </div>
      <div className="section-heading">
        <h2>Active work</h2>
        <span className="subtle">Live generation progress</span>
      </div>
      <ServiceWorkTable
        runs={runtime.active_runs}
        title="No optimization running"
        detail="Standalone requests and decomposition optimizations appear here."
      />
      <div className="section-heading">
        <h2>Recent optimization runs</h2>
        <span className="subtle">Completed, skipped, and failed</span>
      </div>
      <div className="panel table-scroll">
        {runtime.recent_runs.length ? (
          <table className="server-table">
            <thead>
              <tr>
                <th>Run / source</th>
                <th>Profile</th>
                <th>Input</th>
                <th>State</th>
                <th>Fitness</th>
                <th>Duration</th>
                <th>Finished</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {runtime.recent_runs.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <span className="job-id">{run.run_id.slice(0, 8)}</span>
                    <small className="table-secondary">
                      {run.origin === "decomposition"
                        ? "AI pipeline"
                        : "Standalone"}
                    </small>
                  </td>
                  <td>{readable(run.metadata.profile)}</td>
                  <td>
                    {run.metadata.tasks == null
                      ? "—"
                      : `${run.metadata.tasks} tasks / ${run.metadata.employees} staff`}
                  </td>
                  <td>
                    <RunState run={run} />
                  </td>
                  <td>{number(run.metadata.fitness_score, 2)}</td>
                  <td>{elapsed(run)}</td>
                  <td>{time(run.completed_at)}</td>
                  <td>
                    {run.error ? (
                      <span className="run-note">{run.error}</span>
                    ) : (
                      <details className="run-details">
                        <summary>Metrics</summary>
                        <p>
                          Skill match:{" "}
                          {number(run.metadata.metrics?.skill_match_score)}
                          <br />
                          Workload variance:{" "}
                          {number(run.metadata.metrics?.workload_variance, 2)}
                          <br />
                          Schedule:{" "}
                          {number(run.metadata.metrics?.makespan_days)} days
                        </p>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <NoRuns
            title="No optimization history yet"
            detail="Run an existing eFlow optimization or decomposition to see results."
          />
        )}
      </div>
      <SessionFoot services={services} />
    </>
  );
}

function explorer(run: ServiceRun, services: ServicesSnapshot) {
  const meta = run.metadata;
  if (
    meta.simulated ||
    meta.chain_id !== 80002 ||
    !/^0x[0-9a-fA-F]{64}$/.test(meta.tx_hash ?? "")
  )
    return null;
  if (services.blockchain.chain_id !== meta.chain_id) return null;
  return `https://amoy.polygonscan.com/tx/${meta.tx_hash}`;
}
export function BlockchainPanel({
  services,
  online,
  refresh,
}: {
  services?: ServicesSnapshot;
  online: boolean;
  refresh: () => Promise<void>;
}) {
  const [filter, setFilter] = useState("all");
  const [checking, setChecking] = useState<string | null>(null);
  const [verification, setVerification] = useState<{
    id: string;
    message: string;
  } | null>(null);
  if (!services) return <MissingTelemetry online={online} />;
  const chain = services.blockchain,
    rpc = services.rpc;
  const runs = chain.recent_runs.filter(
    (run) =>
      filter === "all" ||
      (filter === "anchors"
        ? run.operation.startsWith("anchor")
        : run.operation === "verify_on_chain"),
  );
  const verify = async (run: ServiceRun) => {
    if (!run.metadata.document_hash || !run.metadata.tx_hash) return;
    setChecking(run.run_id);
    setVerification(null);
    try {
      const result = await verifyAnchor(
        run.metadata.document_hash,
        run.metadata.tx_hash,
      );
      setVerification({
        id: run.run_id,
        message: result.simulated
          ? `Simulation check: ${result.valid ? "hash prefix matched" : "hash prefix did not match"}. No on-chain proof.`
          : result.error
            ? "Verification could not be completed. See the activity log."
            : result.valid
              ? `Hash matched${result.block_number ? ` in block ${result.block_number}` : "; transaction awaits confirmation"}.`
              : "Hash was not verified in this transaction.",
      });
      await refresh();
    } catch {
      setVerification({
        id: run.run_id,
        message:
          "Verification request failed. Check the server connection and activity log.",
      });
    } finally {
      setChecking(null);
    }
  };
  return (
    <>
      <div className="summary-grid">
        <Stat
          label="Execution mode"
          value={
            chain.mode === "simulation"
              ? "Simulation"
              : chain.mode === "live"
                ? "Live"
                : "Unavailable"
          }
          detail={`Configuration: ${chain.configured_mode}`}
        />
        <Stat
          label="Running / waiting"
          value={`${chain.running} / ${chain.waiting}`}
          detail="Single wallet executor"
        />
        <Stat
          label="RPC connectivity"
          value={
            rpc.state === "connected"
              ? "Connected"
              : rpc.state === "not_required"
                ? "Not used"
                : rpc.state === "not_checked"
                  ? "Checking"
                  : "Unavailable"
          }
          detail={
            rpc.checked_at ? `Checked ${time(rpc.checked_at)}` : rpc.message
          }
        />
        <Stat
          label="Recent anchors"
          value={
            chain.recent_runs.filter((run) =>
              run.operation.startsWith("anchor"),
            ).length
          }
          detail="Retained in this server session"
        />
      </div>
      <div className="service-layout">
        <section className="panel">
          <div className="panel-header">
            <h2>Polygon connection</h2>
          </div>
          <div className="panel-body">
            <div className="metric-line">
              <span>Configured network</span>
              <strong>{chain.network}</strong>
            </div>
            <div className="metric-line">
              <span>Chain ID</span>
              <strong>{chain.chain_id}</strong>
            </div>
            <div className="metric-line">
              <span>RPC host</span>
              <strong className="break-value">{chain.rpc_host ?? "—"}</strong>
            </div>
            <div className="metric-line">
              <span>Observed RPC chain / block</span>
              <strong>
                {rpc.chain_id == null
                  ? "—"
                  : `${rpc.chain_id} / ${rpc.block_number ?? "—"}`}
              </strong>
            </div>
            <div className="metric-line">
              <span>Wallet configuration</span>
              <strong>
                {chain.wallet_configured
                  ? "Key configured"
                  : "No key configured"}
              </strong>
            </div>
            <p className="field-help">{chain.problem ?? rpc.message}</p>
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Ledger activity</h2>
          </div>
          <div className="panel-body">
            <p className="field-help" style={{ marginTop: 0 }}>
              Proposal genesis, governance milestones, and archival seals are
              recorded as document hash anchors.
            </p>
            <p className="field-help">{chain.execution}</p>
            <p className="field-help">
              {chain.mode === "simulation"
                ? "Simulation receipts are local test results. They do not represent transactions or proof on Polygon."
                : "Submitted transactions remain unconfirmed until a mined receipt is returned. A confirmation timeout does not prove a transaction failed."}
            </p>
            <p className="field-help">
              Certificate generation assembles supplied receipts; verification
              is a separate operation.
            </p>
          </div>
        </section>
      </div>
      <div className="section-heading">
        <h2>Active ledger work</h2>
      </div>
      <ServiceWorkTable
        runs={chain.active_runs}
        title="No ledger work running"
        detail="Anchoring, verification, and certificate calls appear here."
      />
      <div className="section-heading">
        <h2>Recent ledger operations</h2>
        <label className="service-filter">
          Show
          <select
            aria-label="Ledger operation filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All operations</option>
            <option value="anchors">Anchors</option>
            <option value="verification">Verification</option>
          </select>
        </label>
      </div>
      <div className="panel table-scroll">
        {runs.length ? (
          <table className="server-table ledger-table">
            <thead>
              <tr>
                <th>Proposal / operation</th>
                <th>State</th>
                <th>Transaction / document hash</th>
                <th>Block</th>
                <th>Finished</th>
                <th>Verification</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const url = explorer(run, services);
                return (
                  <tr key={run.run_id}>
                    <td>
                      <strong className="break-value">
                        {run.metadata.proposal_id ?? "—"}
                      </strong>
                      <small className="table-secondary">
                        {readable(run.metadata.event_type ?? run.operation)}
                      </small>
                    </td>
                    <td>
                      <RunState run={run} />
                      {run.error && (
                        <small className="table-secondary run-note">
                          {run.error}
                        </small>
                      )}
                    </td>
                    <td>
                      {url ? (
                        <a
                          className="hash-link"
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={run.metadata.tx_hash}
                        >
                          {run.metadata.tx_hash?.slice(0, 12)}…
                          {run.metadata.tx_hash?.slice(-8)}
                          <ArrowUpRight size={12} />
                        </a>
                      ) : (
                        <span
                          className="hash-value"
                          title={run.metadata.tx_hash}
                        >
                          {run.metadata.tx_hash
                            ? `${run.metadata.tx_hash.slice(0, 20)}…`
                            : "—"}
                        </span>
                      )}
                      <small
                        className="table-secondary hash-value"
                        title={run.metadata.document_hash}
                      >
                        {run.metadata.document_hash
                          ? `${run.metadata.document_hash.slice(0, 12)}…${run.metadata.document_hash.slice(-8)}`
                          : "No document hash"}
                      </small>
                    </td>
                    <td>{run.metadata.block_number ?? "—"}</td>
                    <td>{time(run.completed_at)}</td>
                    <td>
                      {run.operation.startsWith("anchor") &&
                      run.metadata.document_hash &&
                      run.metadata.tx_hash &&
                      run.metadata.simulated ===
                        (chain.mode === "simulation") ? (
                        <>
                          <Button
                            kind="tertiary"
                            size="small"
                            disabled={checking != null || !online}
                            onClick={() => void verify(run)}
                            leftIcon={({ className }) => (
                              <ShieldCheck className={className} size={15} />
                            )}
                          >
                            {checking === run.run_id
                              ? "Checking…"
                              : run.metadata.simulated
                                ? "Check simulation"
                                : "Verify hash"}
                          </Button>
                          {verification?.id === run.run_id && (
                            <p className="verification-result" role="status">
                              {verification.message}
                            </p>
                          )}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <NoRuns
            title={
              filter === "all"
                ? "No ledger operations yet"
                : "No matching operations"
            }
            detail="Receipts and verification activity appear after requests reach this server."
          />
        )}
      </div>
      <SessionFoot services={services} />
    </>
  );
}

export function PipelineStages({
  progress,
  completed,
}: {
  progress?: NonNullable<QueueTelemetry["jobs"]>[number]["progress"];
  completed?: Record<string, string>;
}) {
  const history = progress?.history ?? [];
  const stages = history.map((item) => item.stage);
  if (
    !completed?.laya &&
    !completed?.pygad &&
    !stages.some((stage) =>
      [
        "reading_section",
        "breaking_down",
        "checking_departments",
        "assigning_team",
        "pygad_skipped",
      ].includes(stage),
    )
  )
    return null;
  const definitions = [
    {
      id: "deepseek",
      label: "AI extraction",
      keys: ["reading_section", "breaking_down", "checking_structure"],
    },
    { id: "laya", label: "LAYA", keys: ["checking_departments"] },
    { id: "pygad", label: "PyGAD", keys: ["assigning_team", "pygad_skipped"] },
    { id: "review", label: "Draft check", keys: ["checking_plan"] },
  ];
  return (
    <div className="pipeline-stages" aria-label="Decomposition stages">
      {definitions.map((stage) => {
        const visited = stage.keys.some((key) => stages.includes(key));
        const current = stage.keys.includes(progress?.stage ?? "");
        const skipped =
          stage.id === "pygad" &&
          (stages.includes("pygad_skipped") ||
            completed?.pygad?.startsWith("skipped"));
        const state = skipped
          ? "Skipped"
          : completed?.[stage.id] === "completed" ||
              (stage.id === "review" && completed?.deepseek === "completed")
            ? "Completed"
            : current
              ? "Active"
              : visited
                ? "Visited"
                : "Pending";
        return (
          <div
            key={stage.id}
            className={current && !skipped ? "is-current" : ""}
          >
            <span>{stage.label}</span>
            <small>{state}</small>
          </div>
        );
      })}
    </div>
  );
}
