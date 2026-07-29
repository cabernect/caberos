import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Plus, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";

export function AgentList() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .listAgents()
      .then(setAgents)
      .catch(() => navigate("/login"))
      .finally(() => setLoading(false));
  }, [navigate]);

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-4">
        <h1 className="text-xl font-bold text-foreground">CaberOS</h1>
        <div className="flex items-center gap-3">
          <Button variant="outline" size="lg">
            <Plus className="h-4 w-4" />
            Add Agent
          </Button>
          <Button variant="ghost" size="icon-lg">
            <Settings className="h-5 w-5" />
          </Button>
        </div>
      </header>

      {/* Content */}
      <main className="px-6 py-8">
        <h2 className="mb-6 text-lg font-medium text-foreground">Your Agents</h2>

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : agents.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onClick={() => navigate(`/agents/${agent.id}/chat`)}
              />
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
    <Card
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      className={`flex min-h-[160px] min-w-[280px] cursor-pointer flex-col gap-3 p-6 transition hover:border-primary hover:bg-accent ${agent.enabled ? "" : "opacity-50"}`}
    >
      <div className="flex items-center gap-3">
        <Bot className="h-6 w-6 text-primary" />
        <span className="text-lg font-semibold text-foreground">{agent.name}</span>
      </div>
      <p className="text-sm text-muted-foreground">{agent.model || "No model"}</p>
      {!agent.enabled && (
        <span className="text-xs text-muted-foreground">disabled</span>
      )}
    </Card>
  );
}

function NewAgentCard() {
  return (
    <div className="flex min-h-[160px] min-w-[280px] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-muted-foreground p-6 text-muted-foreground transition hover:border-primary hover:text-primary">
      <Plus className="h-8 w-8" />
      <span className="text-sm">New Agent</span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20">
      <Bot className="h-16 w-16 text-muted-foreground" />
      <h3 className="text-2xl font-bold text-foreground">No agents yet.</h3>
      <p className="text-sm text-muted-foreground">Create your first agent.</p>
      <Button size="lg">Create Agent</Button>
    </div>
  );
}
