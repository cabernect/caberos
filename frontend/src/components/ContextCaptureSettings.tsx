import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Policy = {
  retention_days: number;
  max_bytes: number;
  max_payload_bytes: number;
  pinned: Record<string, boolean>;
};

const FIELDS = [
  {
    key: "retention_days",
    label: "Retention window",
    hint: "Captured bodies older than this are deleted.",
    unit: "days",
  },
  {
    key: "max_bytes",
    label: "Total cap",
    hint: "Oldest captures expire first past this size.",
    unit: "MiB",
  },
  {
    key: "max_payload_bytes",
    label: "Per-request cap",
    hint: "Bodies larger than this are stored truncated.",
    unit: "KiB",
  },
] as const;

type FieldKey = (typeof FIELDS)[number]["key"];

/** Installation-wide request-capture retention — one policy for every
 * agent on this installation. */
export function ContextCaptureSettings() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [values, setValues] = useState<Record<FieldKey, string>>({
    retention_days: "",
    max_bytes: "",
    max_payload_bytes: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getContextCapturePolicy()
      .then((p) => {
        if (!alive) return;
        setPolicy(p);
        // Keep fractional MiB/KiB — floor would silently shrink a stored
        // byte budget on the next save.
        setValues({
          retention_days: String(p.retention_days),
          max_bytes: String(p.max_bytes / 1048576),
          max_payload_bytes: String(p.max_payload_bytes / 1024),
        });
      })
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : "Failed to load");
      });
    return () => {
      alive = false;
    };
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      // Number() — strict: "1.5", "1junk", "" all reject.
      const daysN = Number(values.retention_days);
      const mibN = Number(values.max_bytes);
      const kibN = Number(values.max_payload_bytes);
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

  return (
    <div>
      <p className="text-[12px] text-[var(--ink-3)]">
        Applies to every agent on this installation. Lowering limits can
        expire captured request bodies — conversations and receipts are
        never deleted.
      </p>

      {policy === null && error === null && (
        <p className="mt-3 text-[12px] text-[var(--ink-3)]">Loading…</p>
      )}

      {policy !== null && (
        <>
          <div
            className="mt-3 divide-y border-t"
            style={{ borderColor: "var(--border-soft)" }}
          >
            {FIELDS.map((f) => {
              const pinned = policy.pinned[f.key];
              return (
                <div
                  key={f.key}
                  className="flex items-center justify-between gap-4 py-3"
                  style={{ borderColor: "var(--border-soft)" }}
                >
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-[13px] font-medium text-[var(--ink)]">
                      {f.label}
                      {pinned && (
                        <span
                          className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                          style={{
                            background: "var(--warning-tint)",
                            color: "var(--warning)",
                          }}
                        >
                          Pinned by environment
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
                      {f.hint}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <input
                      type="number"
                      min={1}
                      aria-label={`${f.label} (${f.unit})`}
                      value={values[f.key]}
                      disabled={pinned}
                      onChange={(e) =>
                        setValues((v) => ({ ...v, [f.key]: e.target.value }))
                      }
                      className="w-[76px] rounded-md border px-2 py-1.5 text-center text-[13px] disabled:opacity-50"
                      style={{
                        borderColor: "var(--border)",
                        background: "var(--white)",
                        color: "var(--ink)",
                      }}
                    />
                    <span className="w-8 text-[12px] text-[var(--ink-3)]">
                      {f.unit}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex items-center justify-end gap-3">
            {error && (
              <p className="text-[12px]" style={{ color: "var(--danger)" }}>
                {error}
              </p>
            )}
            {saved && (
              <p className="text-[12px]" style={{ color: "var(--success)" }}>
                Saved.
              </p>
            )}
            <button
              onClick={save}
              disabled={saving}
              className="rounded-md px-4 py-1.5 text-[13px] font-medium transition hover:opacity-90 disabled:opacity-50"
              style={{
                background: "var(--ink)",
                color: "var(--white)",
                border: "1px solid var(--ink)",
              }}
            >
              Save
            </button>
          </div>
        </>
      )}

      {policy === null && error !== null && (
        <p className="mt-3 text-[12px]" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
    </div>
  );
}
