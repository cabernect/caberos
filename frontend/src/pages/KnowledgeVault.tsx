import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Database } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";

export function KnowledgeVault() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    if (page === "settings") navigate("/settings");
    if (page === "skills") navigate("/skills");
    if (page === "vault") return;
    if (page === "scheduler") navigate("/scheduler");
    if (page === "mcps") navigate("/mcps");
    if (page === "channels") navigate("/channels");
    if (page === "observability") navigate("/observability");
    if (page === "traces") navigate("/traces");
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="vault"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        agentCount={0}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div
          className="px-8 py-5"
          style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}
        >
          <h1 className="text-[18px] font-semibold text-[var(--ink)]">Knowledge Vault</h1>
          <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
            Manage external documents for retrieval-augmented generation
          </p>
        </div>

        {/* Body — coming soon */}
        <div className="flex flex-1 flex-col items-center justify-center px-8 py-12">
          <div
            className="flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
          >
            <Database className="h-6 w-6" style={{ color: "var(--ink-3)" }} />
          </div>
          <p className="mt-4 text-[14px] font-medium text-[var(--ink-2)]">
            Coming Soon
          </p>
          <p className="mt-1 max-w-sm text-center text-[12px] text-[var(--ink-3)]">
            The Knowledge Vault will let you upload PDFs, markdown, and text files
            to surface them as retrieval-augmented context to your agents.
          </p>
          <span
            className="mt-4 rounded-full px-3 py-1 text-[11px] font-medium"
            style={{
              background: "var(--accent-bg)",
              color: "var(--accent)",
            }}
          >
            Planned for v0.2
          </span>
        </div>
      </div>
    </div>
  );
}
