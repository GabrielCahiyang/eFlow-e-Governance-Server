import { useState, useEffect, useRef } from "react";
import { Button } from "@vibe/button";
import { Toggle } from "@vibe/toggle";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  ChartNoAxesCombined,
  ChevronRight,
  Clock3,
  Cloud,
  Cpu,
  Inbox,
  ListOrdered,
  MemoryStick,
  RefreshCw,
  Server,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { useOperationsDashboard } from "../hooks/useOperationsDashboard";
import {
  cancelAiJob,
  type OperationsSnapshot,
  type QueueTelemetry,
} from "../services/operationsService";
import type {
  LogEntry,
  ServerStatus,
  UsageStats,
} from "../services/serverLogs";
import { navigation, type DashboardView, type Model } from "./ModelSidebar";
import { ServerLogsPanel } from "./ServerLogsPanel";
import { ApiKeyCard } from "./server-dashboard/ApiKeyCard";
import { TunnelCard } from "./server-dashboard/TunnelCard";
import {
  ServicesOverview,
  OptimizationPanel,
  BlockchainPanel,
  ServiceWorkTable,
  PipelineStages,
} from "./server-dashboard/ServicePanels";

type Props = {
  view: DashboardView;
  onViewChange: (view: DashboardView) => void;
  backendOnline: boolean;
  onToggleModel: (id: string) => void;
  logs: LogEntry[];
  serverStatus: ServerStatus;
  usageStats: UsageStats;
  onClearLogs: () => void;
  models: Model[];
  enabledModels: Set<string>;
};
const titles: Record<DashboardView, [string, string]> = {
  overview: [
    "Server overview",
    "Monitor AI, process optimization, blockchain, and server resources.",
  ],
  optimization: [
    "Process optimization",
    "Follow PyGAD assignments, scheduling, and optimization results.",
  ],
  blockchain: [
    "Blockchain ledger",
    "Monitor Polygon anchors, receipts, and verification activity.",
  ],
  models: ["AI models", "Manage model access and see what is loaded."],
  queue: ["Request queue", "Follow requests from submission to completion."],
  activity: ["Activity log", "Live server events, model activity, and errors."],
  settings: [
    "Connection settings",
    "Manage the public connection and private API credential.",
  ],
};
const nameOf = (tag?: string | null) =>
  tag === "deepseek-r1:8b"
    ? "DeepSeek R1 8B"
    : tag === "qwen3.5:2b"
      ? "Qwen3.5 2B"
      : tag === "qwen3.5:4b"
        ? "Qwen3.5 4B"
        : (tag ?? "None");
const endpointHost = (endpoint?: string | null) => {
  try {
    return endpoint ? new URL(endpoint).hostname : "No endpoint received";
  } catch {
    return "Invalid endpoint";
  }
};
const duration = (seconds: number) =>
  seconds < 60
    ? `${Math.round(seconds)}s`
    : seconds < 3600
      ? `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
      : `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
const timeOf = (seconds: number) =>
  new Date(seconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
function Status({ text, tone = "" }: { text: string; tone?: string }) {
  return (
    <span className="status-text">
      <i className={`status-dot ${tone}`} />
      {text}
    </span>
  );
}
function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <Inbox size={27} strokeWidth={1.3} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

type ResourceSample = Pick<
  OperationsSnapshot,
  "captured_at" | "system" | "gpus"
>;
function ResourceChart({ history }: { history: ResourceSample[] }) {
  const chart = useRef<HTMLDivElement>(null);
  const [chartSize, setChartSize] = useState(640);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) =>
      setChartSize(Math.max(250, entry.contentRect.width)),
    );
    if (chart.current) observer.observe(chart.current);
    return () => observer.disconnect();
  }, []);
  if (!history.length)
    return (
      <div className="resource-chart" ref={chart}>
        <div className="chart-empty">
          <ChartNoAxesCombined />
          <span>No resource samples yet</span>
        </div>
      </div>
    );
  const width = chartSize,
    height = 137,
    left = 36,
    top = 10;
  const chartWidth = width - left - 12,
    chartHeight = height - top - 18;
  const path = (getter: (item: ResourceSample) => number | null) => {
    let started = false;
    return history
      .map((item, index) => {
        const value = getter(item);
        if (value == null) {
          started = false;
          return "";
        }
        const x =
          left +
          (chartWidth * (item.captured_at - history[0].captured_at)) /
            Math.max(
              1,
              history[history.length - 1].captured_at - history[0].captured_at,
            );
        const y =
          top + chartHeight * (1 - Math.min(100, Math.max(0, value)) / 100);
        const command = started ? "L" : "M";
        started = true;
        return `${command}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  };
  return (
    <div className="resource-chart" ref={chart}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Recent GPU and CPU utilization samples"
      >
        {[0, 25, 50, 75, 100].map((value) => {
          const y = top + chartHeight * (1 - value / 100);
          return (
            <g key={value}>
              <line x1={left} x2={width - 12} y1={y} y2={y} stroke="#eceef5" />
              <text x={left - 8} y={y + 3} textAnchor="end">
                {value}%
              </text>
            </g>
          );
        })}
        <path
          d={path((item) => item.system.cpu_percent)}
          fill="none"
          stroke="var(--positive-color)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <path
          d={path((item) => item.gpus[0]?.utilization_percent ?? null)}
          fill="none"
          stroke="var(--primary-color)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <text x={left} y={height - 1}>
          {timeOf(history[0].captured_at)}
        </text>
        <text x={width - 12} y={height - 1} textAnchor="end">
          {timeOf(history[history.length - 1].captured_at)}
        </text>
      </svg>
    </div>
  );
}

function ModelsTable({
  models,
  enabledModels,
  loaded,
  online,
  onToggle,
}: {
  models: Model[];
  enabledModels: Set<string>;
  loaded: string | null;
  online: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="panel table-scroll">
      <table className="server-table">
        <thead>
          <tr>
            <th>Model</th>
            <th>Use case</th>
            <th>File size</th>
            <th>Runtime</th>
            <th>Access</th>
          </tr>
        </thead>
        <tbody>
          {models.map((model) => (
            <tr key={model.id}>
              <td>
                <div className="model-name">
                  <span className="model-symbol">
                    {model.category === "reasoning" ? (
                      <BrainCircuit size={19} />
                    ) : (
                      <Zap size={18} />
                    )}
                  </span>
                  <div>
                    <strong>{model.name}</strong>
                    <small>{model.modelTag}</small>
                  </div>
                </div>
              </td>
              <td>
                {model.category === "reasoning"
                  ? "Proposal & reasoning"
                  : "Tutorial candidate"}
              </td>
              <td>{model.vram.toFixed(2)} GB</td>
              <td>
                <Status
                  text={
                    !online
                      ? "Unavailable"
                      : loaded === model.modelTag
                        ? "Loaded"
                        : model.status === "unknown"
                          ? "Checking..."
                          : model.status === "loaded"
                            ? "On disk"
                            : "Not downloaded"
                  }
                  tone={online && loaded === model.modelTag ? "positive" : ""}
                />
              </td>
              <td>
                <div className="model-access">
                  <Toggle
                    size="small"
                    areLabelsHidden
                    isSelected={enabledModels.has(model.id)}
                    disabled={!online}
                    onChange={() => onToggle(model.id)}
                    aria-label={`Enable ${model.name}`}
                  />
                  <span>
                    {enabledModels.has(model.id) ? "Enabled" : "Disabled"}
                  </span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ControlDashboard({
  view,
  onViewChange,
  backendOnline,
  onToggleModel,
  logs,
  serverStatus,
  usageStats,
  onClearLogs,
  models,
  enabledModels,
}: Props) {
  const {
    operations,
    history,
    tunnel,
    error,
    rotating,
    requestRotation,
    refresh,
  } = useOperationsDashboard(backendOnline);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [queueFilter, setQueueFilter] = useState("all");
  const gpu = operations?.gpus[0];
  const queue = operations?.queue;
  const [title, subtitle] = titles[view];
  const cancel = async (id: string) => {
    setCancelling(id);
    setCancelError(null);
    try {
      await cancelAiJob(id);
      await refresh();
    } catch (err) {
      setCancelError(String(err));
    } finally {
      setCancelling(null);
    }
  };
  const jobs = queue?.jobs ?? [];
  const active = jobs.find((job) => job.status === "processing");
  const services = operations?.services;
  const showAi = queueFilter === "all" || queueFilter === "ai";
  const serviceJobs = services
    ? [services.pygad, services.blockchain]
        .flatMap((service) => service.active_runs)
        .filter((run) =>
          queueFilter === "all"
            ? run.origin === "standalone"
            : queueFilter === run.service,
        )
    : [];
  const serviceRecent = services
    ? [services.pygad, services.blockchain]
        .flatMap((service) => service.recent_runs)
        .filter((run) =>
          queueFilter === "all"
            ? run.origin === "standalone"
            : queueFilter === run.service,
        )
        .sort((a, b) => (b.completed_at ?? 0) - (a.completed_at ?? 0))
        .slice(0, 60)
    : [];
  const queueCounts = {
    processing:
      (showAi ? (queue?.processing ?? 0) : 0) +
      serviceJobs.filter((run) => run.status === "running").length,
    waiting:
      (showAi ? (queue?.waiting ?? 0) : 0) +
      serviceJobs.filter((run) => run.status === "waiting").length,
    completed:
      (showAi ? (queue?.completed_retained ?? 0) : 0) +
      serviceRecent.filter((run) => run.status === "completed").length,
    failed:
      (showAi ? (queue?.failed_retained ?? 0) : 0) +
      serviceRecent.filter((run) => run.status === "failed").length,
  };
  const gpuGb = gpu?.memory_used_mb == null ? null : gpu.memory_used_mb / 1024;
  return (
    <main className="server-main">
      <header className="server-topbar">
        <a
          className="mobile-brand"
          href="#overview"
          aria-label="eFlow server overview"
          onClick={(event) => {
            event.preventDefault();
            onViewChange("overview");
          }}
        >
          <img src="/eflow-logo.svg" alt="eFlow" />
          <span className="brand-caption">| Server</span>
        </a>
        <div className="breadcrumb">
          <span>Workspace</span>
          <ChevronRight size={13} />
          <strong>{view === "overview" ? "Server overview" : title}</strong>
        </div>
        <div className="topbar-right">
          <Status
            text={backendOnline ? "Server connected" : "Server offline"}
            tone={backendOnline ? "positive" : "negative"}
          />
          <Button
            kind="tertiary"
            size="small"
            leftIcon={({ className }) => (
              <RefreshCw className={className} size={16} />
            )}
            onClick={() => void refresh()}
            disabled={!backendOnline}
            aria-label="Refresh server telemetry"
          >
            Refresh
          </Button>
        </div>
      </header>
      <nav className="mobile-nav" aria-label="Mobile server navigation">
        <select
          aria-label="Server section"
          value={view}
          onChange={(event) =>
            onViewChange(event.target.value as DashboardView)
          }
        >
          {navigation.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </nav>
      <div className="server-content">
        <div className="page-heading">
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <span className="update-time">
            {operations
              ? `Last received ${timeOf(operations.captured_at)}`
              : "Waiting for telemetry"}
          </span>
        </div>
        {error && backendOnline && (
          <div className="dashboard-message" role="status">
            <TriangleAlert size={16} />
            Some telemetry is delayed. {error}
          </div>
        )}
        {cancelError && (
          <div className="dashboard-message" role="alert">
            {cancelError}
          </div>
        )}
        {view === "overview" && (
          <>
            <div className="summary-grid">
              <div className="summary-stat">
                <div className="stat-label">
                  <Activity size={15} />
                  GPU utilization
                </div>
                <div className="stat-value">
                  {gpu?.utilization_percent == null
                    ? "—"
                    : Math.round(gpu.utilization_percent)}
                  {gpu?.utilization_percent != null && <small>%</small>}
                </div>
                <div className="stat-detail">
                  {gpu?.name ?? "Awaiting GPU telemetry"}
                </div>
              </div>
              <div className="summary-stat">
                <div className="stat-label">
                  <MemoryStick size={15} />
                  GPU memory
                </div>
                <div className="stat-value">
                  {gpuGb == null ? "—" : gpuGb.toFixed(1)}
                  <small>
                    {gpuGb != null && gpu?.memory_total_mb != null
                      ? `/ ${(gpu.memory_total_mb / 1024).toFixed(0)} GB`
                      : ""}
                  </small>
                </div>
                <div className="stat-detail">
                  {gpu?.memory_percent == null
                    ? "Awaiting memory telemetry"
                    : `${Math.round(gpu.memory_percent)}% of available memory`}
                </div>
              </div>
              <div className="summary-stat">
                <div className="stat-label">
                  <Cpu size={15} />
                  CPU utilization
                </div>
                <div className="stat-value">
                  {operations ? Math.round(operations.system.cpu_percent) : "—"}
                  {operations && <small>%</small>}
                </div>
                <div className="stat-detail">
                  {operations
                    ? `${operations.system.memory_used_gb.toFixed(1)} / ${operations.system.memory_total_gb.toFixed(1)} GB system RAM`
                    : "Awaiting system telemetry"}
                </div>
              </div>
              <div className="summary-stat">
                <div className="stat-label">
                  <ListOrdered size={15} />
                  Requests waiting
                </div>
                <div className="stat-value">{queue?.waiting ?? "—"}</div>
                <div className="stat-detail">
                  {queue
                    ? `${queue.processing} processing · ${queue.completed_retained} completed`
                    : "Awaiting queue telemetry"}
                </div>
              </div>
            </div>
            <ServicesOverview
              operations={operations}
              onViewChange={onViewChange}
            />
            <div className="overview-grid">
              <section className="panel">
                <div className="panel-header">
                  <h2>Resource activity</h2>
                  <div className="chart-legend">
                    <span>
                      <i />
                      GPU
                    </span>
                    <span>
                      <i className="cpu" />
                      CPU
                    </span>
                  </div>
                </div>
                <ResourceChart history={history} />
                <div className="resource-details">
                  <div>
                    <span>GPU temperature</span>
                    <strong>
                      {gpu?.temperature_c == null
                        ? "—"
                        : `${Math.round(gpu.temperature_c)} °C`}
                    </strong>
                  </div>
                  <div>
                    <span>Power draw</span>
                    <strong>
                      {gpu?.power_draw_w == null
                        ? "—"
                        : `${Math.round(gpu.power_draw_w)} W`}
                    </strong>
                  </div>
                  <div>
                    <span>Server uptime</span>
                    <strong>
                      {operations ? duration(operations.uptime_seconds) : "—"}
                    </strong>
                  </div>
                </div>
              </section>
              <section className="panel">
                <div className="panel-header">
                  <h2>Request queue</h2>
                  <Status
                    text={
                      queue
                        ? queue.processing
                          ? "Processing"
                          : "Idle"
                        : "Unavailable"
                    }
                    tone={
                      queue?.processing
                        ? "blue"
                        : queue?.worker_online
                          ? "positive"
                          : ""
                    }
                  />
                </div>
                <div className="queue-stats">
                  <div>
                    <strong>{queue?.processing ?? "—"}</strong>
                    <span>Processing</span>
                  </div>
                  <div>
                    <strong>{queue?.waiting ?? "—"}</strong>
                    <span>Waiting</span>
                  </div>
                  <div>
                    <strong>{queue?.completed_retained ?? "—"}</strong>
                    <span>Completed</span>
                  </div>
                </div>
                {active ? (
                  <div className="active-request">
                    <div>
                      <strong>{nameOf(active.model)}</strong>
                      <span className="subtle">
                        {duration(
                          Date.now() / 1000 -
                            (active.started_at ?? active.submitted_at),
                        )}
                      </span>
                    </div>
                    <p>
                      {active.cancelled
                        ? "Cancelling request…"
                        : (active.progress?.message ?? "Preparing the AI.")}
                    </p>
                    <PipelineStages progress={active.progress} />
                    {active.progress?.current != null &&
                      active.progress.total != null &&
                      active.progress.total > 0 && (
                        <div className="progress-line">
                          <div
                            style={{
                              width: `${Math.min(100, (active.progress.current / active.progress.total) * 100)}%`,
                            }}
                          />
                        </div>
                      )}
                  </div>
                ) : (
                  <Empty
                    title={queue ? "No active requests" : "Queue unavailable"}
                    detail={
                      queue
                        ? "New AI requests will appear here."
                        : "Connect the server to see queued requests."
                    }
                  />
                )}
                <div className="queue-foot">
                  <span>
                    {queue?.capacity
                      ? `Capacity: ${queue.capacity} waiting requests`
                      : "Shared AI worker"}
                  </span>
                  <Button
                    kind="tertiary"
                    size="small"
                    onClick={() => onViewChange("queue")}
                    rightIcon={({ className }) => (
                      <ArrowRight className={className} size={16} />
                    )}
                  >
                    View queue
                  </Button>
                </div>
              </section>
            </div>
            <div className="section-heading">
              <h2>AI models</h2>
              <span className="subtle" style={{ fontSize: 11 }}>
                {enabledModels.size} of {models.length} enabled
              </span>
            </div>
            <ModelsTable
              models={models}
              enabledModels={enabledModels}
              loaded={operations?.model.loaded ?? null}
              online={backendOnline}
              onToggle={onToggleModel}
            />
            <div className="connection-strip">
              <Cloud size={20} />
              <div>
                <strong>Public connection</strong>
                <p>{endpointHost(tunnel?.endpoint)}</p>
              </div>
              <Status
                text={
                  tunnel?.status === "online"
                    ? "Connected"
                    : (tunnel?.status ?? "Unavailable")
                }
                tone={tunnel?.status === "online" ? "positive" : ""}
              />
              <span className="connection-action">
                <Button
                  kind="tertiary"
                  size="small"
                  onClick={() => onViewChange("settings")}
                  rightIcon={({ className }) => (
                    <ArrowRight className={className} size={16} />
                  )}
                >
                  Connection settings
                </Button>
              </span>
            </div>
          </>
        )}
        {view === "models" && (
          <>
            <ModelsTable
              models={models}
              enabledModels={enabledModels}
              loaded={operations?.model.loaded ?? null}
              online={backendOnline}
              onToggle={onToggleModel}
            />
            <div className="overview-grid" style={{ marginTop: 22 }}>
              <section className="panel">
                <div className="panel-header">
                  <h2>Inference runtime</h2>
                </div>
                <div className="panel-body">
                  <div className="metric-line">
                    <span>Loaded model</span>
                    <strong>
                      {operations?.model.loaded
                        ? nameOf(operations.model.loaded)
                        : "None"}
                    </strong>
                  </div>
                  <div className="metric-line">
                    <span>Worker process</span>
                    <strong>
                      {operations?.inference?.pid ?? "Starts on first request"}
                    </strong>
                  </div>
                  <div className="metric-line">
                    <span>Model format</span>
                    <strong>GGUF · Q4_K_M</strong>
                  </div>
                  <div className="metric-line">
                    <span>Worker restarts</span>
                    <strong>{operations?.inference?.restarts ?? "—"}</strong>
                  </div>
                </div>
              </section>
              <section className="panel">
                <div className="panel-header">
                  <h2>Model lifecycle</h2>
                </div>
                <div className="panel-body">
                  <p className="field-help" style={{ marginTop: 0 }}>
                    The worker keeps the current model loaded for reuse.
                    Switching models releases the previous model first.
                    Disabling access prevents new requests from using that
                    model.
                  </p>
                  <p className="field-help">
                    The tutorial models are installed. The dedicated tutorial
                    service and speech integration are still to be built.
                  </p>
                </div>
              </section>
            </div>
          </>
        )}
        {view === "queue" && (
          <>
            <div className="queue-toolbar">
              <label className="service-filter">
                Service
                <select
                  aria-label="Queue service filter"
                  value={queueFilter}
                  onChange={(event) => setQueueFilter(event.target.value)}
                >
                  <option value="all">All services</option>
                  <option value="ai">AI inference</option>
                  <option value="pygad">PyGAD optimization</option>
                  <option value="blockchain">Blockchain ledger</option>
                </select>
              </label>
              <span className="subtle">
                Independent workers · live execution state
              </span>
            </div>
            <div className="summary-grid">
              {[
                ["Running", operations ? queueCounts.processing : undefined],
                ["Waiting", operations ? queueCounts.waiting : undefined],
                [
                  "Completed retained",
                  operations ? queueCounts.completed : undefined,
                ],
                [
                  "Failed retained",
                  operations ? queueCounts.failed : undefined,
                ],
              ].map(([label, value]) => (
                <div className="summary-stat" key={String(label)}>
                  <div className="stat-label">{label}</div>
                  <div className="stat-value">{value ?? "—"}</div>
                </div>
              ))}
            </div>
            <p className="queue-description">
              AI requests run in submission order. Each user can have{" "}
              {queue?.per_user_limit ?? 2} outstanding requests. Cancelling an
              active request stops its inference worker before the next request
              starts. Standalone optimization and ledger work run separately.
              Decomposition stages remain attached to their AI request in the
              all-services view.
            </p>
            {showAi && (
              <>
                <div className="section-heading">
                  <h2>AI requests</h2>
                </div>
                <div className="panel table-scroll">
                  {jobs.length ? (
                    <table className="server-table">
                      <thead>
                        <tr>
                          <th>Request</th>
                          <th>Model</th>
                          <th>Status</th>
                          <th>Progress</th>
                          <th>Elapsed</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.map((job) => (
                          <tr key={job.job_id}>
                            <td>
                              <span className="job-id">
                                {job.job_id.slice(0, 8)}
                              </span>
                            </td>
                            <td>{nameOf(job.model)}</td>
                            <td>
                              <Status
                                text={
                                  job.cancelled
                                    ? "Cancelling"
                                    : job.status === "processing"
                                      ? "Processing"
                                      : "Waiting"
                                }
                                tone={job.status === "processing" ? "blue" : ""}
                              />
                            </td>
                            <td>
                              {job.progress?.message ?? "Waiting for its turn"}
                              <PipelineStages progress={job.progress} />
                            </td>
                            <td>
                              {duration(Date.now() / 1000 - job.submitted_at)}
                            </td>
                            <td>
                              <Button
                                kind="tertiary"
                                size="small"
                                color="negative"
                                disabled={
                                  job.cancelled || cancelling === job.job_id
                                }
                                onClick={() => void cancel(job.job_id)}
                              >
                                Cancel
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <Empty
                      title={queue ? "The queue is clear" : "Queue unavailable"}
                      detail={
                        queue
                          ? "There are no requests waiting or processing."
                          : "Connect the server to see request status."
                      }
                    />
                  )}
                </div>
              </>
            )}
            {(serviceJobs.length > 0 || !showAi) && (
              <>
                <div className="section-heading">
                  <h2>
                    {queueFilter === "all"
                      ? "Independent CPU and ledger work"
                      : "Active service work"}
                  </h2>
                </div>
                <ServiceWorkTable runs={serviceJobs} />
              </>
            )}
            {showAi && (
              <>
                <div className="section-heading">
                  <h2>Recent completions</h2>
                  <span className="subtle" style={{ fontSize: 11 }}>
                    Timing by stage
                  </span>
                </div>
                <div className="panel table-scroll">
                  {operations?.inference?.recent_runs.length ? (
                    <table className="server-table">
                      <thead>
                        <tr>
                          <th>Model</th>
                          <th>Model loading</th>
                          <th>Generation</th>
                          <th>Other processing</th>
                          <th>Tokens</th>
                          <th>Completed / stages</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...operations.inference.recent_runs]
                          .reverse()
                          .map((run, index) => (
                            <tr key={index}>
                              <td>{nameOf(run.model)}</td>
                              <td>{(run.model_load / 1000).toFixed(2)}s</td>
                              <td>{(run.inference / 1000).toFixed(2)}s</td>
                              <td>{(run.pipeline / 1000).toFixed(2)}s</td>
                              <td>{run.tokens}</td>
                              <td>
                                {timeOf(run.completed_at)}
                                <PipelineStages
                                  completed={run.pipeline_status}
                                />
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  ) : (
                    <Empty
                      title="No completed requests yet"
                      detail="Stage timings appear after an AI request finishes."
                    />
                  )}
                </div>
              </>
            )}
            {(serviceRecent.length > 0 || !showAi) && (
              <>
                <div className="section-heading">
                  <h2>Recent service runs</h2>
                  <span className="subtle">Current server session</span>
                </div>
                <ServiceWorkTable
                  runs={serviceRecent}
                  title="No completed service runs yet"
                  detail="Service results appear after requests reach the server."
                />
              </>
            )}
          </>
        )}
        {view === "optimization" && (
          <OptimizationPanel services={services} online={backendOnline} />
        )}
        {view === "blockchain" && (
          <BlockchainPanel
            services={services}
            online={backendOnline}
            refresh={refresh}
          />
        )}
        {view === "activity" && (
          <ServerLogsPanel
            logs={logs}
            serverStatus={serverStatus}
            usageStats={usageStats}
            onClear={onClearLogs}
          />
        )}
        {view === "settings" && (
          <div className="settings-grid">
            <TunnelCard
              tunnel={tunnel}
              rotating={rotating}
              onRotate={requestRotation}
            />
            <ApiKeyCard />
          </div>
        )}
      </div>
    </main>
  );
}
