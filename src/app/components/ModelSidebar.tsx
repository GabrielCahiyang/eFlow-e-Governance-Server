import { Boxes, BrainCircuit, CheckCircle2, CircleOff, Cpu, Sparkles } from 'lucide-react';
import { Switch } from './ui/switch';

export type Model = {
  id: string;
  name: string;
  modelTag?: string;
  category: 'chat' | 'reasoning' | 'coding' | 'fast' | 'embedding';
  status: 'loaded' | 'unloaded';
  vram: number;
  speed: 'fast' | 'medium' | 'slow';
  description: string;
  supportsVision: boolean;
};

const categoryLabels: Record<Model['category'], string> = {
  chat: 'Chat',
  reasoning: 'Reasoning',
  coding: 'Coding',
  fast: 'Fast',
  embedding: 'Embedding',
};

type Props = {
  models: Model[];
  enabledModels: Set<string>;
  onToggleModel: (modelId: string) => void;
  backendOnline?: boolean;
};

function ModelRow({ model, enabled, onToggle }: { model: Model; enabled: boolean; onToggle: () => void }) {
  return (
    <article className={`rounded-xl border p-3 transition ${enabled ? 'border-neutral-200 bg-white shadow-[0_1px_2px_rgba(0,0,0,0.03)]' : 'border-transparent bg-neutral-100/70 opacity-65'}`}>
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${enabled ? 'bg-neutral-950 text-white' : 'bg-neutral-200 text-neutral-500'}`}>
          <BrainCircuit className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="m-0 truncate text-xs font-semibold text-neutral-900">{model.name}</p>
          <p className="mb-0 mt-0.5 truncate text-[10px] text-neutral-500">{model.description}</p>
        </div>
        <Switch checked={enabled} onCheckedChange={onToggle} aria-label={`Toggle ${model.name}`} />
      </div>
      <div className="mt-3 flex items-center gap-2 pl-11 text-[9px] font-semibold uppercase tracking-[0.06em]">
        <span className="rounded-full bg-violet-50 px-2 py-1 text-violet-700">{categoryLabels[model.category]}</span>
        <span className={`flex items-center gap-1 ${model.status === 'loaded' ? 'text-emerald-700' : 'text-neutral-400'}`}>
          {model.status === 'loaded' ? <CheckCircle2 className="h-3 w-3" /> : <CircleOff className="h-3 w-3" />}
          {model.status === 'loaded' ? 'Ready' : 'Not downloaded'}
        </span>
      </div>
    </article>
  );
}

export function ModelSidebar({ models, enabledModels, onToggleModel, backendOnline = false }: Props) {
  const downloaded = models.filter((model) => model.status === 'loaded').length;
  return (
    <aside className="hidden h-screen w-[278px] shrink-0 flex-col border-r border-neutral-200 bg-[#f1f1ef] lg:flex">
      <div className="border-b border-neutral-200 px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center overflow-hidden rounded-xl bg-neutral-950 text-white shadow-sm">
            <span className="text-lg font-bold tracking-[-0.08em]">e</span>
            <span className="absolute bottom-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-emerald-400" />
          </div>
          <div>
            <p className="m-0 text-sm font-semibold tracking-[-0.02em] text-neutral-950">eFlow Server Side</p>
            <p className="m-0 mt-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-neutral-500">AI operations console</p>
          </div>
        </div>
      </div>

      <div className="px-4 pb-2 pt-4">
        <div className="rounded-xl border border-neutral-200 bg-white p-3 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-xs font-semibold text-neutral-800"><Cpu className="h-3.5 w-3.5" />Private AI node</span>
            <span className={`h-2 w-2 rounded-full ${backendOnline ? 'bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.12)]' : 'bg-red-500'}`} />
          </div>
          <p className="mb-0 mt-2 text-[10px] leading-4 text-neutral-500">{backendOnline ? 'Online and accepting authenticated eFlow requests.' : 'Offline. The supervisor will restart the service automatically.'}</p>
        </div>
      </div>

      <div className="flex items-center justify-between px-5 pb-2 pt-3">
        <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-500"><Boxes className="h-3.5 w-3.5" />Model access</span>
        <span className="text-[10px] font-semibold text-neutral-500">{enabledModels.size}/{models.length}</span>
      </div>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3">
        {models.map((model) => <ModelRow key={model.id} model={model} enabled={enabledModels.has(model.id)} onToggle={() => onToggleModel(model.id)} />)}
      </div>

      <div className="border-t border-neutral-200 p-4">
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-xl bg-neutral-200/60 p-3"><p className="m-0 text-[9px] font-semibold uppercase tracking-[0.08em] text-neutral-500">Downloaded</p><p className="mb-0 mt-1 flex items-center gap-1.5 text-sm font-semibold text-neutral-900"><Sparkles className="h-3.5 w-3.5" />{downloaded}</p></div>
          <div className="rounded-xl bg-neutral-200/60 p-3"><p className="m-0 text-[9px] font-semibold uppercase tracking-[0.08em] text-neutral-500">Enabled</p><p className="mb-0 mt-1 text-sm font-semibold text-neutral-900">{enabledModels.size}</p></div>
        </div>
      </div>
    </aside>
  );
}
