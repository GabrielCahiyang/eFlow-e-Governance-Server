import type { LucideIcon } from 'lucide-react';

type Tone = 'emerald' | 'blue' | 'amber' | 'violet';

const toneClasses: Record<Tone, { icon: string; surface: string }> = {
  emerald: { icon: 'text-emerald-700', surface: 'bg-emerald-50' },
  blue: { icon: 'text-blue-700', surface: 'bg-blue-50' },
  amber: { icon: 'text-amber-700', surface: 'bg-amber-50' },
  violet: { icon: 'text-violet-700', surface: 'bg-violet-50' },
};

type Props = {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone: Tone;
};

export function MetricCard({ label, value, detail, icon: Icon, tone }: Props) {
  const colors = toneClasses[tone];
  return (
    <article className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
      <div className="flex items-start justify-between gap-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${colors.surface}`}>
          <Icon className={`h-4 w-4 ${colors.icon}`} />
        </div>
        <span className="rounded-full bg-neutral-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-neutral-500">
          Live
        </span>
      </div>
      <p className="mb-0 mt-4 text-[11px] font-medium uppercase tracking-[0.08em] text-neutral-500">{label}</p>
      <p className="mb-0 mt-1 text-2xl font-semibold tracking-[-0.04em] text-neutral-950">{value}</p>
      <p className="mb-0 mt-1 truncate text-xs text-neutral-500" title={detail}>{detail}</p>
    </article>
  );
}
