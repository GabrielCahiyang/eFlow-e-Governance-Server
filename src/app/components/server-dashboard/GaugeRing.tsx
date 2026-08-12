type Props = {
  value: number | null;
  label: string;
  suffix?: string;
};

export function GaugeRing({ value, label, suffix = '%' }: Props) {
  const normalized = Math.max(0, Math.min(100, value ?? 0));
  const accent = normalized >= 90 ? '#dc2626' : normalized >= 75 ? '#d97706' : '#059669';
  return (
    <div className="relative h-32 w-32 shrink-0 rounded-full p-[10px]" style={{ background: `conic-gradient(${accent} ${normalized * 3.6}deg, #e5e7eb 0deg)` }}>
      <div className="flex h-full w-full flex-col items-center justify-center rounded-full bg-white shadow-inner">
        <span className="text-2xl font-semibold tracking-[-0.04em] text-neutral-950">
          {value == null ? '--' : Math.round(value)}{value == null ? '' : suffix}
        </span>
        <span className="mt-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-400">{label}</span>
      </div>
    </div>
  );
}
