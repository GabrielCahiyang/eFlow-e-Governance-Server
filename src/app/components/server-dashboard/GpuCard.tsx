import { Cpu, Gauge, MemoryStick, Thermometer, Zap } from 'lucide-react';
import type { GpuTelemetry, OperationsSnapshot } from '../../services/operationsService';
import { DashboardPanel } from './DashboardPanel';
import { GaugeRing } from './GaugeRing';

function value(value: number | null, suffix: string) {
  return value == null ? 'Unavailable' : `${value.toLocaleString()}${suffix}`;
}

function TelemetryRow({ icon: Icon, label, reading }: { icon: typeof Cpu; label: string; reading: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-neutral-100 py-3 last:border-0">
      <span className="flex items-center gap-2 text-xs text-neutral-500"><Icon className="h-3.5 w-3.5" />{label}</span>
      <span className="text-xs font-semibold text-neutral-900">{reading}</span>
    </div>
  );
}

export function GpuCard({ gpu, operations }: { gpu: GpuTelemetry | null; operations: OperationsSnapshot | null }) {
  return (
    <DashboardPanel
      title="GPU workload"
      description={gpu?.name ?? 'Waiting for NVIDIA telemetry from the server'}
      action={<span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${gpu ? 'bg-emerald-50 text-emerald-700' : 'bg-neutral-100 text-neutral-500'}`}>{gpu ? 'Detected' : 'Unavailable'}</span>}
      className="lg:col-span-2"
    >
      <div className="grid gap-5 p-5 md:grid-cols-[auto_1fr_1fr] md:items-center">
        <GaugeRing value={gpu?.utilization_percent ?? null} label="GPU use" />
        <div>
          <TelemetryRow icon={MemoryStick} label="VRAM allocated" reading={gpu ? `${((gpu.memory_used_mb ?? 0) / 1024).toFixed(1)} / ${((gpu.memory_total_mb ?? 0) / 1024).toFixed(1)} GB` : 'Unavailable'} />
          <TelemetryRow icon={Thermometer} label="GPU temperature" reading={value(gpu?.temperature_c ?? null, ' °C')} />
          <TelemetryRow icon={Zap} label="Power draw" reading={value(gpu?.power_draw_w ?? null, ' W')} />
        </div>
        <div>
          <TelemetryRow icon={Gauge} label="System CPU" reading={operations ? `${operations.system.cpu_percent}%` : 'Unavailable'} />
          <TelemetryRow icon={MemoryStick} label="System memory" reading={operations ? `${operations.system.memory_used_gb} / ${operations.system.memory_total_gb} GB` : 'Unavailable'} />
          <TelemetryRow icon={Cpu} label="AI process memory" reading={operations ? `${operations.process.memory_mb.toLocaleString()} MB` : 'Unavailable'} />
        </div>
      </div>
    </DashboardPanel>
  );
}
