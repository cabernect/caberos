import { X } from "lucide-react";
import { useState } from "react";
import type { Agent } from "@/lib/types";

interface SettingsOverlayProps {
  agent: Agent | null;
  open: boolean;
  onClose: () => void;
}

const TABS = ["General", "MCPs", "Skills", "Channels"] as const;
type Tab = (typeof TABS)[number];

export function SettingsOverlay({ agent, open, onClose }: SettingsOverlayProps) {
  const [tab, setTab] = useState<Tab>("General");

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.25)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg border shadow-xl"
        style={{
          background: "var(--white)",
          borderColor: "var(--border)",
          maxHeight: "80vh",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <h2 className="text-[16px] font-semibold text-[var(--ink)]">
            {agent?.name || "Agent"} Settings
          </h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-6" style={{ borderBottom: "1px solid var(--border)" }}>
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="border-b-2 px-3 py-2.5 text-[13px] transition"
              style={{
                borderColor:
                  tab === t ? "var(--accent)" : "transparent",
                color:
                  tab === t ? "var(--ink)" : "var(--ink-2)",
                background: "none",
                cursor: "pointer",
              }}
              onMouseEnter={(e) => {
                if (tab !== t) e.currentTarget.style.color = "var(--ink)";
              }}
              onMouseLeave={(e) => {
                if (tab !== t) e.currentTarget.style.color = "var(--ink-2)";
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="max-h-[60vh] overflow-y-auto p-6">
          {tab === "General" && <GeneralTab agent={agent} />}
          {tab === "MCPs" && (
            <EmptyTab message="No MCP servers connected. Connector integration comes in a later release." />
          )}
          {tab === "Skills" && (
            <EmptyTab message="No skills configured yet. Skills management comes in a later release." />
          )}
          {tab === "Channels" && <ChannelsTab />}
        </div>
      </div>
    </div>
  );
}

function GeneralTab({ agent }: { agent: Agent | null }) {
  if (!agent)
    return (
      <p className="text-[13px] text-[var(--ink-2)]">Loading...</p>
    );

  const fields: [string, string | null][] = [
    ["Name", agent.name],
    ["ID", agent.id],
    ["Model", agent.model],
    ["Provider ID", agent.provider_id],
    ["Soul", agent.soul],
    ["Persona", agent.persona],
    ["Task", agent.task],
    ["Enabled", agent.enabled ? "Yes" : "No"],
  ];

  return (
    <div className="space-y-4">
      <p className="text-[12px] text-[var(--ink-3)]">
        Read-only view. Agent editing comes in a later release.
      </p>
      {fields.map(([label, value]) => (
        <div key={label}>
          <label className="text-[12px] font-medium text-[var(--ink-2)]">
            {label}
          </label>
          <p
            className="mt-1 rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)]"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface)",
            }}
          >
            {value || "—"}
          </p>
        </div>
      ))}
    </div>
  );
}

function EmptyTab({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <p className="text-[13px] text-[var(--ink-2)]">{message}</p>
    </div>
  );
}

function ChannelsTab() {
  return (
    <div className="space-y-2">
      <div
        className="flex items-center justify-between rounded-[5px] border px-4 py-3"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <div>
          <p className="text-[13px] font-medium text-[var(--ink)]">Dashboard</p>
          <p className="text-[12px] text-[var(--ink-2)]">
            Built-in web chat channel
          </p>
        </div>
        <span
          className="rounded-full px-2 py-0.5 text-[11px] font-mono"
          style={{
            background: "rgba(22, 163, 74, 0.1)",
            color: "var(--success)",
          }}
        >
          Active
        </span>
      </div>
      <p className="pt-2 text-[12px] text-[var(--ink-3)]">
        More channels (Telegram, Slack, etc.) coming in a later release.
      </p>
    </div>
  );
}
