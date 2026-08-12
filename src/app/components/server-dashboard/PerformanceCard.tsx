import { Activity, Clock3, Gauge, Sparkles } from 'lucide-react';
import type { UsageStats } from '../../services/serverLogs';
import { DashboardPanel } from './DashboardPanel';

export function PerformanceCard({ usage }: { usage: UsageStats }) {
  const items = [
    { label: 'Requests', value: usage.totalRequests.toLocaleString(), icon: Activity },
    { label: 'Generated tokens', value: usage.totalTokens.toLocaleString(), icon: Sparkles },
    { label: 'Average latency', value: usage.avgLatencyMs ? `${usage.avgLatencyMs} ms` : 'No data', icon: Clock3 },
    { label: 'Generation speed', value: usage.tokensPerSecond ? `${usage.tokensPerSecond} tok/s` : 'No data', icon: Gauge },
  ];
  return (
    <DashboardPanel title="Workload performance" description="Session totals calculated from live AI request logs">
      <div className="divide-y divide-neutral-100 px-5 py-1">
        {items.map(({ label, value, icon: Icon }) => (
          <div key={label} className="flex items-center justify-between gap-4 py-3.5">
            <span className="flex items-center gap-2 text-xs text-neutral-500"><Icon className="h-3.5 w-3.5" />{label}</span>
            <span className="text-xs font-semibold text-neutral-900">{value}</span>
          </div>
        ))}
      </div>
    </DashboardPanel>
  );
}
