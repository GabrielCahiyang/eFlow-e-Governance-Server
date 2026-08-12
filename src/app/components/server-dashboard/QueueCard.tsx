import { CheckCircle2, Clock3, Layers3 } from 'lucide-react';
import type { QueueTelemetry } from '../../services/operationsService';
import { DashboardPanel } from './DashboardPanel';

export function QueueCard({ queue }: { queue: QueueTelemetry | null }) {
  const active = queue?.active_job;
  return (
    <DashboardPanel
      title="AI request queue"
      description="FIFO execution for the shared DeepSeek node"
      action={<span className={`h-2.5 w-2.5 rounded-full ${queue?.worker_online ? 'bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.12)]' : 'bg-red-500'}`} />}
    >
      <div className="p-5">
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl bg-neutral-950 p-3 text-white">
            <p className="m-0 text-[10px] uppercase tracking-[0.08em] text-neutral-400">Processing</p>
            <p className="mb-0 mt-2 text-2xl font-semibold">{queue?.processing ?? '--'}</p>
          </div>
          <div className="rounded-xl bg-amber-50 p-3 text-amber-950">
            <p className="m-0 text-[10px] uppercase tracking-[0.08em] text-amber-700">Waiting</p>
            <p className="mb-0 mt-2 text-2xl font-semibold">{queue?.waiting ?? '--'}</p>
          </div>
          <div className="rounded-xl bg-emerald-50 p-3 text-emerald-950">
            <p className="m-0 text-[10px] uppercase tracking-[0.08em] text-emerald-700">Completed</p>
            <p className="mb-0 mt-2 text-2xl font-semibold">{queue?.completed_retained ?? '--'}</p>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
          {active ? (
            <>
              <div className="flex items-center gap-2 text-xs font-semibold text-neutral-900"><Layers3 className="h-4 w-4 text-violet-600" />{active.model}</div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-neutral-200"><div className="h-full w-2/3 animate-pulse rounded-full bg-violet-600" /></div>
              <p className="mb-0 mt-2 flex items-center gap-1.5 text-[11px] text-neutral-500"><Clock3 className="h-3 w-3" />Running for {active.running_seconds}s · {queue?.waiting ?? 0} next in line</p>
            </>
          ) : (
            <p className="m-0 flex items-center gap-2 text-xs text-neutral-600"><CheckCircle2 className="h-4 w-4 text-emerald-600" />Queue is clear. The worker is ready for the next request.</p>
          )}
        </div>
      </div>
    </DashboardPanel>
  );
}
