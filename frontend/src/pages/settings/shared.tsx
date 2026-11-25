// Shared building blocks for the settings tabs.

export function SettingsSection({
  id,
  title,
  subtitle,
  children,
}: {
  id: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id}>
      <h2 className="text-[14px] font-semibold text-[var(--ink)]">{title}</h2>
      <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">{subtitle}</p>
      <div
        className="rounded-xl p-5"
        style={{
          border: "1px solid var(--border-soft)",
          background: "var(--surface)",
        }}
      >
        {children}
      </div>
    </section>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-[var(--ink-2)]">
        {label}
      </label>
      {children}
    </div>
  );
}

export function ProviderTile({ name }: { name: string }) {
  return (
    <span
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-[13px] font-semibold"
      style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
    >
      {name.charAt(0).toUpperCase()}
    </span>
  );
}
