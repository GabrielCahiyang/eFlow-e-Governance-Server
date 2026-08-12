import { useState } from 'react';
import { Activity, ChevronDown, ChevronUp, Clock3, Flame, MemoryStick, Radio, Server, Thermometer, Users } from 'lucide-react';
import { useOperationsDashboard } from '../hooks/useOperationsDashboard';
import type { LogEntry, ServerStatus, UsageStats } from '../services/serverLogs';
import type { Model } from './ModelSidebar';
import { ServerLogsPanel } from './ServerLogsPanel';
import { ApiKeyCard } from './server-dashboard/ApiKeyCard';
import { GpuCard } from './server-dashboard/GpuCard';
import { MetricCard } from './server-dashboard/MetricCard';
import { PerformanceCard } from './server-dashboard/PerformanceCard';
import { QueueCard } from './server-dashboard/QueueCard';
import { TunnelCard } from './server-dashboard/TunnelCard';

type Props = {
  logs: LogEntry[];
  serverStatus: ServerStatus;
  usageStats: UsageStats;
  onClearLogs: () => void;
  models: Model[];
  enabledModels: Set<string>;
};

function formatDuration(totalSeconds: number | undefined) {
  if (totalSeconds == null) return 'Waiting for telemetry';
  const days = Math.floor(totalSeconds / 86_400);
  const hours = Math.floor((totalSeconds % 86_400) / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  if (days) return `${days}d ${hours}h ${minutes}m`;
  return `${hours}h ${minutes}m`;
}

export function ControlDashboard({ logs, serverStatus, usageStats, onClearLogs, models, enabledModels }: Props) {
  const [logsExpanded, setLogsExpanded] = useState(true);
  const { operations, tunnel, error, rotating, requestRotation } = useOperationsDashboard(serverStatus === 'online');
  const gpu = operations?.gpus[0] ?? null;
  const memoryUsedGb = gpu?.memory_used_mb == null ? null : gpu.memory_used_mb / 1024;
  const memoryTotalGb = gpu?.memory_total_mb == null ? null : gpu.memory_total_mb / 1024;
  const statusOnline = serverStatus === 'online';

  return (
    <main className="min-w-0 flex-1 overflow-y-auto bg-[#f7f7f6]">
      <div className="mx-auto max-w-[1500px] px-5 py-5 sm:px-7 lg:px-9 lg:py-7">
        <header className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-neutral-400">
              <Server className="h-3.5 w-3.5" /> Infrastructure / AI operations
            </div>
            <h1 className="m-0 text-2xl font-semibold tracking-[-0.04em] text-neutral-950">Server overview</h1>
            <p className="mb-0 mt-1 text-sm text-neutral-500">Monitor the machine, shared AI queue, public endpoint, and model workload.</p>
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-white px-3 py-2 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
            <span className={`h-2.5 w-2.5 rounded-full ${statusOnline ? 'bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.12)]' : 'bg-red-500'}`} />
            <div>
              <p className="m-0 text-xs font-semibold text-neutral-900">{statusOnline ? 'AI node operational' : 'AI node offline'}</p>
              <p className="m-0 mt-0.5 text-[10px] text-neutral-500">Live telemetry refreshes every 4 seconds</p>
            </div>
          </div>
        </header>

        {error && statusOnline && (
          <div className="mb-5 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
            <Radio className="h-4 w-4" />Some live telemetry is delayed: {error}
          </div>
        )}

        <section className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="GPU utilization" value={gpu?.utilization_percent == null ? '--' : `${Math.round(gpu.utilization_percent)}%`} detail={gpu?.name ?? 'NVIDIA telemetry unavailable'} icon={Activity} tone="emerald" />
          <MetricCard label="VRAM usage" value={memoryUsedGb == null ? '--' : `${memoryUsedGb.toFixed(1)} GB`} detail={memoryTotalGb == null ? 'Capacity unavailable' : `${memoryTotalGb.toFixed(1)} GB total capacity`} icon={MemoryStick} tone="blue" />
          <MetricCard label="GPU temperature" value={gpu?.temperature_c == null ? '--' : `${Math.round(gpu.temperature_c)} °C`} detail={gpu?.temperature_c == null ? 'Temperature unavailable' : gpu.temperature_c < 80 ? 'Within operating range' : 'Thermal load is elevated'} icon={Thermometer} tone="amber" />
          <MetricCard label="Queued requests" value={`${operations?.queue.waiting ?? 0}`} detail={operations?.queue.processing ? `1 processing · ${operations.queue.depth} total` : 'Worker is ready'} icon={Users} tone="violet" />
        </section>

        <section className="mb-5 grid gap-5 lg:grid-cols-3">
          <GpuCard gpu={gpu} operations={operations} />
          <QueueCard queue={operations?.queue ?? null} />
        </section>

        <section className="mb-5 grid gap-5 lg:grid-cols-3">
          <TunnelCard tunnel={tunnel} rotating={rotating} onRotate={requestRotation} />
          <ApiKeyCard />
        </section>

        <section className="mb-5 grid gap-5 lg:grid-cols-3">
          <PerformanceCard usage={usageStats} />
          <div className="rounded-2xl border border-neutral-200 bg-neutral-950 p-5 text-white shadow-[0_1px_2px_rgba(0,0,0,0.04)] lg:col-span-2">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="m-0 text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-500">Runtime</p>
                <h2 className="mb-0 mt-2 text-base font-semibold">Private AI node</h2>
              </div>
              <Flame className="h-5 w-5 text-emerald-400" />
            </div>
            <div className="mt-7 grid gap-5 sm:grid-cols-3">
              <div><p className="m-0 text-[10px] uppercase tracking-[0.1em] text-neutral-500">Uptime</p><p className="mb-0 mt-2 text-xl font-semibold">{formatDuration(operations?.uptime_seconds)}</p></div>
              <div><p className="m-0 text-[10px] uppercase tracking-[0.1em] text-neutral-500">Loaded model</p><p className="mb-0 mt-2 truncate text-xl font-semibold" title={operations?.model.loaded ?? undefined}>{operations?.model.loaded ?? 'Idle'}</p></div>
              <div><p className="m-0 text-[10px] uppercase tracking-[0.1em] text-neutral-500">Model access</p><p className="mb-0 mt-2 text-xl font-semibold">{enabledModels.size} / {models.length}</p></div>
            </div>
            <div className="mt-6 flex items-center gap-2 border-t border-white/10 pt-4 text-[11px] text-neutral-400"><Clock3 className="h-3.5 w-3.5" />Session counters reset when the private AI process restarts.</div>
          </div>
        </section>

        <section className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
          <button onClick={() => setLogsExpanded((current) => !current)} className="flex w-full items-center gap-3 border-0 bg-white px-5 py-4 text-left hover:bg-neutral-50">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-neutral-950 text-white"><Radio className="h-3.5 w-3.5" /></span>
            <div><p className="m-0 text-sm font-semibold text-neutral-900">Live server activity</p><p className="m-0 mt-0.5 text-[11px] text-neutral-500">{logs.length} buffered events · errors, requests, model loading, and health</p></div>
            <span className="ml-auto text-neutral-400">{logsExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}</span>
          </button>
          {logsExpanded && <div className="h-[360px] border-t border-neutral-100"><ServerLogsPanel logs={logs} serverStatus={serverStatus} usageStats={usageStats} onClear={onClearLogs} /></div>}
        </section>
      </div>
    </main>
  );
}
