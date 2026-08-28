import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, Upload, Trash2, FileText, Search, Package } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { SkillInfo } from "@/lib/types";

export function Skills() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { confirm } = useConfirm();

  const loadSkills = async () => {
    try {
      setLoading(true);
      const data = await api.listSkills();
      setSkills(data.skills);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load skills");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSkills();
  }, []);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    if (page === "settings") navigate("/settings");
    if (page === "vault") navigate("/vault");
    if (page === "skills") return;
    if (page === "scheduler") navigate("/scheduler");
    if (page === "mcps") navigate("/mcps");
    if (page === "channels") navigate("/channels");
    if (page === "observability") navigate("/observability");
    if (page === "traces") navigate("/traces");
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportMsg(null);
    try {
      const result = await api.importSkillZip(file);
      setImportMsg(`Imported "${result.name}" (${result.files} files)`);
      await loadSkills();
    } catch (err) {
      setImportMsg(`Import failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (name: string) => {
    const ok = await confirm({
      title: "Delete skill?",
      message: `Delete skill "${name}"? This cannot be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteSkill(name);
      setSkills(skills.filter((s) => s.name !== name));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete skill");
    }
  };

  const filtered = skills.filter(
    (s) =>
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.description.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="skills"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div
          className="flex items-center justify-between px-8 py-5"
          style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}
        >
          <div className="flex items-start gap-2">
            <Sparkles className="mt-0.5 h-5 w-5" style={{ color: "var(--accent)" }} />
            <div>
            <h1 className="text-[18px] font-semibold text-[var(--ink)]">Skills</h1>
            <p className="text-[13px] text-[var(--ink-2)] mt-0.5">
              {skills.length} skill{skills.length !== 1 ? "s" : ""} installed
            </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              onChange={handleImport}
              style={{ display: "none" }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importing}
              className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] font-medium transition"
              style={{
                background: "var(--ink)",
                color: "var(--white)",
                border: "1px solid var(--ink)",
                cursor: "pointer",
                opacity: importing ? 0.6 : 1,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.opacity = importing ? "0.6" : "0.85")}
              onMouseLeave={(e) => (e.currentTarget.style.opacity = importing ? "0.6" : "1")}
            >
              <Upload className="h-4 w-4" />
              {importing ? "Importing..." : "Import .zip"}
            </button>
          </div>
        </div>

        {/* Import message */}
        {importMsg && (
          <div
            className="mx-8 mt-4 rounded-lg px-4 py-3 text-[13px]"
            style={{
              background: importMsg.startsWith("Import failed")
                ? "rgba(220, 38, 38, 0.1)"
                : "rgba(34, 197, 94, 0.1)",
              color: importMsg.startsWith("Import failed") ? "#dc2626" : "#22c55e",
            }}
          >
            {importMsg}
          </div>
        )}

        {error && (
          <div
            className="mx-8 mt-4 rounded-lg px-4 py-3 text-[13px]"
            style={{ background: "rgba(220, 38, 38, 0.1)", color: "#dc2626" }}
          >
            {error}
          </div>
        )}

        {/* Search bar */}
        <div className="px-8 py-4">
          <div className="relative max-w-md">
            <Search
              className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
              style={{ color: "var(--ink-3)" }}
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search skills..."
              className="w-full rounded-lg py-2 pl-10 pr-4 text-[13px]"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--ink)",
              }}
            />
          </div>
        </div>

        {/* Skills grid */}
        <div className="flex-1 overflow-y-auto px-8 pb-8">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <p className="text-[14px] text-[var(--ink-3)]">Loading skills...</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20">
              <Package className="h-12 w-12 mb-3" style={{ color: "var(--ink-3)" }} />
              <p className="text-[14px] text-[var(--ink-3)]">
                {search ? "No skills match your search" : "No skills installed yet"}
              </p>
              {!search && (
                <p className="text-[13px] text-[var(--ink-3)] mt-1">
                  Import a .zip or use the skill-creator skill in chat
                </p>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filtered.map((skill) => (
                <div
                  key={skill.name}
                  className="group rounded-xl p-5 transition-shadow hover:shadow-md"
                  style={{
                    background: "var(--sidebar)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-5 w-5" style={{ color: "var(--accent)" }} />
                      <h3 className="text-[14px] font-semibold text-[var(--ink)]">
                        {skill.name}
                      </h3>
                    </div>
                    <button
                      onClick={() => handleDelete(skill.name)}
                      className="opacity-0 transition-opacity group-hover:opacity-100"
                      style={{ color: "var(--ink-3)" }}
                      title="Delete skill"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>

                  <p
                    className="mt-2 text-[13px] leading-relaxed"
                    style={{ color: "var(--ink-2)" }}
                  >
                    {skill.description || "No description"}
                  </p>

                  <div
                    className="mt-4 flex items-center gap-3 text-[12px]"
                    style={{ color: "var(--ink-3)" }}
                  >
                    <span className="flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      {skill.resource_count} resource{skill.resource_count !== 1 ? "s" : ""}
                    </span>
                    <span
                      className="rounded px-1.5 py-0.5"
                      style={{
                        background: "var(--surface)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      {skill.source}
                    </span>
                    {skill.license && (
                      <span className="truncate" title={skill.license}>
                        {skill.license}
                      </span>
                    )}
                  </div>

                  {/* Slash command hint */}
                  <div
                    className="mt-3 rounded-lg px-3 py-2 font-mono text-[12px]"
                    style={{
                      background: "var(--surface)",
                      color: "var(--ink-3)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    /{skill.name} your message here
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
