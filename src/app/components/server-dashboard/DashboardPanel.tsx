import type { ReactNode } from 'react';

type Props = {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function DashboardPanel({ title, description, action, children, className = '' }: Props) {
  return (
    <section className={`rounded-2xl border border-neutral-200 bg-white shadow-[0_1px_2px_rgba(0,0,0,0.03)] ${className}`}>
      <div className="flex items-start justify-between gap-4 border-b border-neutral-100 px-5 py-4">
        <div>
          <h2 className="m-0 text-sm font-semibold tracking-[-0.01em] text-neutral-900">{title}</h2>
          {description && <p className="mt-1 text-xs leading-5 text-neutral-500">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
