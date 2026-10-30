/** Minimal syntax-tinted JSON viewer — recursive, so values render as real
 * JSON (strings truncated past 140 chars with an honest char-count hint,
 * matching the trace mockups' `…" (1,074 chars)` treatment). */

const STR_CAP = 140;

function JStr({ v }: { v: string }) {
  const cut = v.length > STR_CAP;
  return (
    <span style={{ color: "var(--warning, #b08968)" }}>
      "{cut ? v.slice(0, STR_CAP) : v}
      {cut && <span style={{ color: "var(--ink-3)" }}>,…" ({v.length.toLocaleString()} chars)</span>}
      {!cut && '"'}
    </span>
  );
}

function JVal({ v, depth }: { v: unknown; depth: number }) {
  const pad = { paddingLeft: depth * 14 };
  if (v === null) return <span style={{ color: "var(--ink-3)" }}>null</span>;
  if (typeof v === "string") return <JStr v={v} />;
  if (typeof v === "number") return <span style={{ color: "var(--chart-2, #64748b)" }}>{String(v)}</span>;
  if (typeof v === "boolean") return <span style={{ color: "var(--chart-2, #64748b)" }}>{String(v)}</span>;
  if (Array.isArray(v)) {
    if (v.length === 0) return <span style={{ color: "var(--ink-2)" }}>[]</span>;
    return (
      <span style={{ color: "var(--ink-2)" }}>
        {"["}
        <div>
          {v.map((item, i) => (
            <div key={i} style={pad}>
              <JVal v={item} depth={depth + 1} />
              {i < v.length - 1 && ","}
            </div>
          ))}
        </div>
        {"]"}
      </span>
    );
  }
  if (typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>);
    if (entries.length === 0) return <span style={{ color: "var(--ink-2)" }}>{"{}"}</span>;
    return (
      <span style={{ color: "var(--ink-2)" }}>
        {"{"}
        <div>
          {entries.map(([k, val], i) => (
            <div key={k} style={pad}>
              <span style={{ color: "var(--ink-3)" }}>"{k}"</span>
              <span>: </span>
              <JVal v={val} depth={depth + 1} />
              {i < entries.length - 1 && ","}
            </div>
          ))}
        </div>
        {"}"}
      </span>
    );
  }
  return <span style={{ color: "var(--ink-2)" }}>{String(v)}</span>;
}

export function JsonBlock({ data }: { data: unknown }) {
  return (
    <div
      className="overflow-auto rounded-md p-3 font-mono text-[10.5px] leading-relaxed"
      style={{ background: "var(--ground)", maxHeight: 320 }}
    >
      <JVal v={data} depth={0} />
    </div>
  );
}
