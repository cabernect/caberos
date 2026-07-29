import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Plus, Settings } from "lucide-react";
import { api } from "../lib/api";
import type { Agent } from "../lib/types";

export function AgentList() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.listAgents()
      .then(setAgents)
      .catch(() => {
        // If 401, redirect to login
        navigate("/login");
      })
      .finally(() => setLoading(false));
  }, [navigate]);

  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-4">
        <h1 className="text-xl font-bold text-[var(--color-text)]">CaberOS</h1>
        <div className="flex items-center gap-3">
          <button className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-cta)] px-4 py-2 text-sm text-[var(--color-cta)] transition hover:bg-[var(--color-surface)]">
            <Plus className="h-4 w-4" />
            Add Agent
          </button>
          <button className="cursor-pointer rounded-[var(--radius-md)] p-2 text-[var(--color-secondary)] transition hover:bg-[var(--color-surface)]">
            <Settings className="h-5 w-5" />
          </button>
        </div>
      </header>

      {/* Content */}
      <main className="px-6 py-8">
        <h2 className="mb-6 text-lg font-medium text-[var(--color-text)]">
          Your Agents
        </h2>

        {loading ? (
          <p className="text-sm text-[var(--color-secondary)]">Loading...</p>
        ) : agents.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} onClick={() => navigate(`/agents/${agent.id}/chat`)} />
            ))}
            <NewAgentCard />
          </div>
        )}
      </main>
    </div>
  );
}

function AgentCard({ agent, onClick }: { agent: Agent; onClick: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      className={`flex min-h-[160px] min-w-[280px] cursor-pointer flex-col gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 transition hover:border-[var(--color-cta)] hover:bg-[var(--color-surface-hover)] ${agent.enabled ? "" : "opacity-50"}`}
    >
      <div className="flex items-center gap-3">
        <Bot className="h-6 w-6 text-[var(--color-cta)]" />
        <span className="text-lg font-semibold text-[var(--color-text)]">
          {agent.name}
        </span>
      </div>
      <p className="text-sm text-[var(--color-secondary)]">
        {agent.model || "No model"}
      </p>
      {!agent.enabled && (
        <span className="text-xs text-[var(--color-secondary)]">disabled</span>
      )}
    </div>
  );
}

function NewAgentCard() {
  return (
    <div className="flex min-h-[160px] min-w-[280px] cursor-pointer flex-col items-center justify-center gap-2 rounded-[var(--radius-lg)] border border-dashed border-[var(--color-secondary)] p-6 text-[var(--color-secondary)] transition hover:border-[var(--color-cta)] hover:text-[var(--color-cta)]">
      <Plus className="h-8 w-8" />
      <span className="text-sm">New Agent</span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20">
      <Bot className="h-16 w-16 text-[var(--color-secondary)]" />
      <h3 className="text-2xl font-bold text-[var(--color-text)]">
        No agents yet.
      </h3>
      <p className="text-sm text-[var(--color-secondary)]">
        Create your first agent.
      </p>
      <button className="cursor-pointer rounded-[var(--radius-md)] bg-[var(--color-cta)] px-6 py-3 font-medium text-white transition hover:opacity-90">
        Create Agent
      </button>
    </div>
  );
}
