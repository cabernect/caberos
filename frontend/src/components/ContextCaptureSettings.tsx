import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Policy = {
  retention_days: number;
  max_bytes: number;
  max_payload_bytes: number;
  pinned: Record<string, boolean>;
};

/** Installation-wide request-capture retention — one policy for every
 * agent on this installation. Collapsed by default; the policy is only
 * fetched when the operator expands the section. */
export function ContextCaptureSettings() {
  const [open, setOpen] = useState(false);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [days, setDays] = useState("");
  const [mib, setMib] = useState("");
  const [perBodyKib, setPerBodyKib] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || policy !== null) return;
    let alive = true;
    api
      .getContextCapturePolicy()
      .then((p) => {
        if (!alive) return;
        setPolicy(p);
        setDays(String(p.retention_days));
        // Keep fractional MiB/KiB — floor would silently shrink a stored
        // byte budget on the next save.
        setMib(String(p.max_bytes / 1048576));
        setPerBodyKib(String(p.max_payload_bytes / 1024));
      })
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : "Failed to load");
      });
    return () => {
      alive = false;
    };
  }, [open, policy]);

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      // Number() — strict: "1.5", "1junk", "" all reject.
      const daysN = Number(days);
      const mibN = Number(mib);
      const kibN = Number(perBodyKib);
      if (!Number.isSafeInteger(daysN) || daysN < 1)
        throw new Error("Retention days must be a positive whole number");
      if (!Number.isFinite(mibN) || mibN <= 0)
        throw new Error("Total cap must be a positive number of MiB");
      if (!Number.isFinite(kibN) || kibN <= 0)
        throw new Error("Per-request cap must be a positive number of KiB");
      const bytesN = mibN * 1048576;
      const perBytesN = kibN * 1024;
      if (!Number.isSafeInteger(bytesN) || !Number.isSafeInteger(perBytesN))
        throw new Error("Byte limits must resolve to whole bytes");
      await api.updateContextCapturePolicy({
        retention_days: daysN,
        max_bytes: bytesN,
        max_payload_bytes: perBytesN,
      });
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "w-24 rounded-[5px] border px-2 py-1 text-[12px] outline-none";
  const inputStyle = {
    borderColor: "var(--border)",
    background: "var(--surface)",
  } as const;

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="text-[13px] font-medium text-[var(--ink)]"
      >
        {open ? "▾" : "▸"} Request capture retention
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] text-[var(--ink-3)]">
            Applies to every agent on this installation. Lowering limits can
            expire captured request bodies — conversations and receipts are
            never deleted.
          </p>
          {policy === null && error === null && (
            <p className="text-[11px] text-[var(--ink-3)]">Loading…</p>
          )}
          {policy !== null && (
            <div className="flex flex-wrap items-end gap-3">
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[var(--ink-2)]">
                  Retention (days)
                </span>
                <input
                  type="number"
                  min={1}
                  value={days}
                  title={policy.pinned.retention_days ? "Pinned by environment" : undefined}
                  disabled={policy.pinned.retention_days}
                  onChange={(e) => setDays(e.target.value)}
                  className={inputCls}
                  style={inputStyle}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[var(--ink-2)]">
                  Total cap (MiB)
                </span>
                <input
                  type="number"
                  min={1}
                  value={mib}
                  title={policy.pinned.max_bytes ? "Pinned by environment" : undefined}
                  disabled={policy.pinned.max_bytes}
                  onChange={(e) => setMib(e.target.value)}
                  className={inputCls}
                  style={inputStyle}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[var(--ink-2)]">
                  Per-request cap (KiB)
                </span>
                <input
                  type="number"
                  min={1}
                  value={perBodyKib}
                  title={policy.pinned.max_payload_bytes ? "Pinned by environment" : undefined}
                  disabled={policy.pinned.max_payload_bytes}
                  onChange={(e) => setPerBodyKib(e.target.value)}
                  className={inputCls}
                  style={inputStyle}
                />
              </label>
              <button
                onClick={save}
                disabled={saving}
                className="rounded-[6px] px-4 py-2 text-[13px] font-medium transition"
                style={{
                  background: "var(--ink)",
                  color: "var(--white)",
                  border: "1px solid var(--ink)",
                  cursor: saving ? "not-allowed" : "pointer",
                  opacity: saving ? 0.5 : 1,
                }}
              >
                Save
              </button>
            </div>
          )}
          {error && <p className="text-[11px] text-[var(--danger,#b91c1c)]">{error}</p>}
          {saved && <p className="text-[11px] text-[var(--olive,#4d7c0f)]">Saved.</p>}
        </div>
      )}
    </div>
  );
}
