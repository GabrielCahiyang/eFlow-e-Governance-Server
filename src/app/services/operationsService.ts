import { fetchAuthKey } from './authKeyService';

const BASE = '/api';

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
};

export type TunnelSnapshot = {
  endpoint: string | null;
  status: 'online' | 'starting' | 'restarting' | 'offline' | 'unknown';
  message: string;
  heartbeat: string | null;
  endpoint_updated_at: string | null;
  rotation_pending: boolean;
};

async function authenticatedFetch(path: string, init?: RequestInit): Promise<Response> {
  const key = await fetchAuthKey();
  const headers = new Headers(init?.headers);
  if (key) headers.set('Authorization', `Bearer ${key}`);
  return fetch(`${BASE}${path}`, { ...init, headers });
}

async function readJson<T>(response: Response, label: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(`${label} failed (${response.status})${detail ? `: ${detail}` : ''}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchOperationsSnapshot(): Promise<OperationsSnapshot> {
  return readJson<OperationsSnapshot>(
    await authenticatedFetch('/operations'),
    'Operations telemetry',
  );
}

export async function fetchTunnelSnapshot(): Promise<TunnelSnapshot> {
  return readJson<TunnelSnapshot>(
    await authenticatedFetch('/tunnel/status'),
    'Tunnel status',
  );
}

export async function rotateTunnel(): Promise<{ requested_at: string; message: string }> {
  return readJson(
    await authenticatedFetch('/tunnel/rotate', { method: 'POST' }),
    'Tunnel rotation',
  );
}
