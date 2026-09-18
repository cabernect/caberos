/** File-type tile for non-image attachments — the extension badge reads
    like Drive/Slack file chips, honest where no real thumbnail exists. */
export function FileTypeTile({ filename }: { filename: string }) {
  const ext = filename.includes(".")
    ? filename.split(".").pop()!.toUpperCase()
    : "";
  const label = ext && ext.length <= 5 ? ext : "FILE";
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[4px] border border-[var(--border)] bg-[var(--surface)]">
      <span
        className="font-mono font-bold tracking-tight text-[var(--accent)]"
        style={{ fontSize: label.length > 4 ? "7px" : "9px" }}
      >
        {label}
      </span>
    </span>
  );
}
