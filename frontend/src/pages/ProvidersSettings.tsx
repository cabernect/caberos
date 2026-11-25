import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Settings,
  Server,
  Cpu,
  Wrench,
  Globe,
  HardDrive,
  Info,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { Operator, Provider } from "@/lib/types";
import {
  DashboardSidebar,
  NAV_ROUTES,
  type NavKey,
} from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { GeneralTab } from "./settings/general";
import { ProvidersTab } from "./settings/providers";
import { ModelsTab } from "./settings/models";
import { BrowserTab } from "./settings/browser";
import { MigrationTab } from "./settings/migration";
import { AboutTab } from "./settings/about";
import { ToolsTab } from "./settings/tools";

export { ToolsTab } from "./settings/tools";

type SettingsTab =
  "general" | "providers" | "models" | "tools" | "browser" | "migration" | "about";

const SETTINGS_TABS: SettingsTab[] = [
  "general", "providers", "models", "tools", "browser", "migration", "about",
];

export function ProvidersSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [operator, setOperator] = useState<Operator | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [searchParams] = useSearchParams();
  const initialTab = searchParams.get("tab");
  const [activeTab, setActiveTab] = useState<SettingsTab>(
    SETTINGS_TABS.includes(initialTab as SettingsTab)
      ? (initialTab as SettingsTab)
      : "general",
  );
  const navigate = useNavigate();
  const { confirm, toast } = useConfirm();

  const load = useCallback(async () => {
    try {
      const [provs, me] = await Promise.all([api.listProviders(), api.me()]);
      setProviders(provs);
      setOperator(me);
    } catch {
      navigate("/login");
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    load();
  }, [load]);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    navigate(NAV_ROUTES[page]);
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm({
      title: "Delete provider?",
      message: "Agents using it will need to be reconfigured.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteProvider(id);
      load();
    } catch (e) {
      toast(String(e));
    }
  };

  const tabs: { key: SettingsTab; label: string; icon: typeof Settings }[] = [
    { key: "general", label: "General", icon: Settings },
    { key: "providers", label: "Providers", icon: Server },
    { key: "models", label: "Models", icon: Cpu },
    { key: "tools", label: "Tools", icon: Wrench },
    { key: "browser", label: "Browser", icon: Globe },
    { key: "migration", label: "Migration", icon: HardDrive },
    { key: "about", label: "About", icon: Info },
  ];

  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: "var(--ground)" }}
    >
      <DashboardSidebar
        active="settings"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[
            { label: "Settings" },
            {
              label: tabs.find((t) => t.key === activeTab)?.label ?? "General",
            },
          ]}
          title="Settings"
          subtitle="Manage your CaberOS configuration."
        />

        {/* Tabs */}
        <div className="px-8 pb-3">
          <FilterPills
            pills={tabs.map((t) => ({ key: t.key, label: t.label }))}
            active={activeTab}
            onChange={(k) => setActiveTab(k as SettingsTab)}
            variant="segmented"
          />
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {activeTab === "general" && (
            <GeneralTab
              operator={operator}
              loading={loading}
              onLogout={handleLogout}
              onOperatorChanged={setOperator}
            />
          )}

          {activeTab === "providers" && (
            <ProvidersTab
              providers={providers}
              loading={loading}
              onChanged={load}
              onDelete={handleDelete}
            />
          )}

          {activeTab === "models" && (
            <ModelsTab
              providers={providers}
              loading={loading}
              onChanged={load}
            />
          )}

          {activeTab === "tools" && <ToolsTab providers={providers} />}

          {activeTab === "browser" && <BrowserTab />}

          {activeTab === "migration" && <MigrationTab />}

          {activeTab === "about" && <AboutTab />}
        </div>
      </div>
    </div>
  );
}
