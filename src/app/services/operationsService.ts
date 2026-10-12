import { fetchAuthKey } from "./authKeyService";

const BASE = "/api";

export type ServiceName = "pygad" | "laya" | "blockchain";
export type ServiceRun = {
  run_id: string;
  service: ServiceName;
  operation: string;
  origin: string;
  status:
    | "waiting"
    | "running"
    | "completed"
    | "failed"
    | "cancelled"
    | "skipped"
    | "unconfirmed";
  submitted_at: number;
  started_at: number | null;
  completed_at: number | null;
  duration_ms?: number;
  wait_ms?: number;
  error?: string;
  metadata: {
    profile?: string;
    tasks?: number;
    employees?: number;
    generation?: number;
    generations?: number;
    fitness_score?: number;
    generation_history?: number[];
    metrics?: {
      skill_match_score?: number;
      workload_variance?: number;
      makespan_days?: number;
      total_budget?: number;
    };
    proposal_id?: string;
    event_type?: string;
    tx_hash?: string;
    document_hash?: string;
    chain_id?: number;
    block_number?: number;
    simulated?: boolean;
    valid?: boolean;
    engine?: string;
  };
};
export type ServiceRuntime = {
  running: number;
  waiting: number;
  counts: Record<
    "completed" | "failed" | "cancelled" | "skipped" | "unconfirmed",
    number
  >;
  active_runs: ServiceRun[];
  recent_runs: ServiceRun[];
};
export type ServicesSnapshot = {
  started_at: number;
  history_limit: number;
  pygad: ServiceRuntime & {
    available: boolean;
    default_profile: string;
    execution: string;
  };
  laya: ServiceRuntime & { mode: string; device: string; execution: string };
  blockchain: ServiceRuntime & {
    mode: string;
    configured_mode: string;
    available: boolean;
    chain_id: number;
    network: string;
    rpc_host: string | null;
    wallet_configured: boolean;
    problem: string | null;
    execution: string;
  };
  rpc: {
    state: string;
    checked_at: number | null;
    chain_id: number | null;
    block_number: number | null;
    message: string;
  };
};

export type GpuTelemetry = {
  index: number;
  name: string;
  utilization_percent: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  memory_percent: number | null;
  temperature_c: number | null;
  power_draw_w: number | null;
  power_limit_w: number | null;
  fan_percent: number | null;
};

export type QueueTelemetry = {
  depth: number;
  waiting: number;
  processing: number;
  worker_online: boolean;
  active_job: {
    job_id: string;
    model: string;
    running_seconds: number;
  } | null;
  oldest_wait_seconds: number;
  completed_retained: number;
  failed_retained: number;
  capacity?: number;
  per_user_limit?: number;
  jobs?: Array<{
    job_id: string;
    model: string;
    status: string;
    submitted_at: number;
    started_at: number | null;
    cancelled: boolean;
    progress: {
      stage: string;
      message: string;
      current?: number;
      total?: number;
      history?: Array<{ stage: string; message: string; updated_at: number }>;
    } | null;
  }>;
};

export type OperationsSnapshot = {
  captured_at: number;
  uptime_seconds: number;
  system: {
    cpu_percent: number;
    memory_percent: number;
    memory_used_gb: number;
    memory_total_gb: number;
  };
  process: {
    cpu_percent: number;
    memory_mb: number;
  };
  gpu_available: boolean;
  gpus: GpuTelemetry[];
  queue: QueueTelemetry;
  model: {
    loaded: string | null;
    registered: number;
    enabled: number;
  };
  inference?: {
    pid: number | null;
    restarts: number;
    timeout_seconds: number;
    recent_runs: Array<{
      model: string;
      completed_at: number;
      tokens: number;
      model_load: number;
      inference: number;
      pipeline: number;
      total: number;
      first_token_ms: number | null;
      pipeline_status?: Record<string, string>;
    }>;
  };
  services?: ServicesSnapshot;
};

export type TunnelSnapshot = {
  endpoint: string | null;
  status: "online" | "starting" | "restarting" | "offline" | "unknown";
  message: string;
  heartbeat: string | null;
  endpoint_updated_at: string | null;
  rotation_pending: boolean;
};

async function authenticatedFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const key = await fetchAuthKey();
  const headers = new Headers(init?.headers);
  if (key) headers.set("Authorization", `Bearer ${key}`);
  return fetch(`${BASE}${path}`, {
    signal: AbortSignal.timeout(10_000),
    ...init,
    headers,
  });
}

export async function cancelAiJob(id: string): Promise<void> {
  await readJson(
    await authenticatedFetch(`/operations/jobs/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
    "Request cancellation",
  );
}

export async function verifyAnchor(
  documentHash: string,
  txHash: string,
): Promise<{
  valid: boolean;
  simulated: boolean;
  block_number: number | null;
  message: string;
  error?: string;
}> {
  return readJson(
    await authenticatedFetch(
      `/blockchain/verify/${encodeURIComponent(documentHash)}?tx_hash=${encodeURIComponent(txHash)}`,
      { signal: AbortSignal.timeout(45_000) },
    ),
    "Anchor verification",
  );
}

async function readJson<T>(response: Response, label: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `${label} failed (${response.status})${detail ? `: ${detail}` : ""}`,
    );
  }
  return response.json() as Promise<T>;
}

export async function fetchOperationsSnapshot(): Promise<OperationsSnapshot> {
  return readJson<OperationsSnapshot>(
    await authenticatedFetch("/operations"),
    "Operations telemetry",
  );
}

export async function fetchTunnelSnapshot(): Promise<TunnelSnapshot> {
  return readJson<TunnelSnapshot>(
    await authenticatedFetch("/tunnel/status"),
    "Tunnel status",
  );
}

export async function rotateTunnel(): Promise<{
  requested_at: string;
  message: string;
}> {
  return readJson(
    await authenticatedFetch("/tunnel/rotate", { method: "POST" }),
    "Tunnel rotation",
  );
}
