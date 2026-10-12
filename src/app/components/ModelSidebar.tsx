import {
  Boxes,
  LayoutDashboard,
  ListOrdered,
  Settings2,
  Terminal,
  Workflow,
  Link2,
} from "lucide-react";

export type Model = {
  id: string;
  name: string;
  modelTag?: string;
  category: "chat" | "reasoning" | "coding" | "fast" | "embedding";
  status: "loaded" | "unloaded" | "unknown";
  vram: number;
  speed: "fast" | "medium" | "slow";
  description: string;
  supportsVision: boolean;
};
export type DashboardView =
  | "overview"
  | "models"
  | "queue"
  | "optimization"
  | "blockchain"
  | "activity"
  | "settings";

export const navigation = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "models", label: "AI models", icon: Boxes },
  { id: "optimization", label: "Process optimization", icon: Workflow },
  { id: "queue", label: "Request queue", icon: ListOrdered },
  { id: "blockchain", label: "Blockchain ledger", icon: Link2 },
  { id: "activity", label: "Activity log", icon: Terminal },
  { id: "settings", label: "Connection settings", icon: Settings2 },
] as const;

export function ModelSidebar({
  view,
  onViewChange,
}: {
  view: DashboardView;
  onViewChange: (view: DashboardView) => void;
}) {
  return (
    <aside className="server-sidebar">
      <a
        className="server-brand"
        href="#overview"
        aria-label="eFlow server overview"
        onClick={(e) => {
          e.preventDefault();
          onViewChange("overview");
        }}
      >
        <img src="/eflow-logo.svg" alt="eFlow" />
        <span className="brand-caption">| Server</span>
      </a>
      <nav aria-label="Server navigation">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`server-nav-item ${view === id ? "is-active" : ""}`}
            onClick={() => onViewChange(id)}
            aria-current={view === id ? "page" : undefined}
          >
            <Icon size={19} strokeWidth={1.7} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
