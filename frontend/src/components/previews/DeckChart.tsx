import type { DeckBlock } from "@/lib/types";

/** Bounded semantic charts; geometry is renderer-owned, never authored CSS. */
export function DeckChart({block}: {block: DeckBlock}) {
  const categories = block.categories ?? [], series = block.series ?? [];
  if (!categories.length || !series.length) return null;
  const values = series.flatMap(s => s.values);
  const min = Math.min(0, ...values), max = Math.max(1, ...values);
  const y = (n: number) => 210 - (n - min) / (max - min) * 180;
  const color = (index: number) => ["var(--accent)", "#347c86", "#a45d36", "#727042", "#625b78", "#555e69"][index % 6];
  const description = series.map(s => `${s.name}: ${categories.map((c, i) => `${c} ${s.values[i]}`).join(", ")}`).join("; ");
  let angle = -Math.PI / 2;
  return <svg viewBox="0 0 900 290" role="img" aria-label={`${block.chart_type ?? "bar"} chart. ${description}`} style={{display: "block", width: "100%", maxHeight: 300, margin: "12px 0", overflow: "hidden"}}>
    <title>{description}</title>
    {block.chart_type === "pie" ? series[0].values.map((value, i) => {
      const fraction = value / series[0].values.reduce((a, b) => a + b, 0);
      const start = angle; angle += fraction * Math.PI * 2;
      const x1 = 240 + 100 * Math.cos(start), y1 = 140 + 100 * Math.sin(start);
      const x2 = 240 + 100 * Math.cos(angle), y2 = 140 + 100 * Math.sin(angle);
      return <g key={i}>
        {fraction >= 0.99999 ? <circle cx={240} cy={140} r={100} fill={color(i)} /> : <path d={`M 240 140 L ${x1} ${y1} A 100 100 0 ${fraction > 0.5 ? 1 : 0} 1 ${x2} ${y2} Z`} fill={color(i)} />}
        <text x={390} y={35 + i * 20} fill="currentColor" fontSize={14}>{categories[i].slice(0, 35)}: {value}</text>
      </g>;
    }) : <>
      <line x1={45} x2={870} y1={y(0)} y2={y(0)} stroke="currentColor" opacity={0.4} />
      {[min, max].map((v, i) => <text key={i} x={40} y={y(v)} textAnchor="end" fontSize={12} fill="currentColor">{Number(v.toPrecision(4))}</text>)}
      {series.map((s, si) => <g key={si}>
        {block.chart_type === "line" ? <>
          <polyline fill="none" stroke={color(si)} strokeWidth={3} points={s.values.map((v, i) => `${60 + (i + 0.5) * 800 / categories.length},${y(v)}`).join(" ")} />
          {s.values.map((v, i) => <circle key={i} cx={60 + (i + 0.5) * 800 / categories.length} cy={y(v)} r={4} fill={color(si)} />)}
        </> : s.values.map((v, i) => {
          const width = 800 / categories.length / (series.length + 1);
          return <rect key={i} x={60 + i * 800 / categories.length + si * width} y={Math.min(y(0), y(v))} width={Math.max(1, width - 2)} height={Math.abs(y(v) - y(0))} fill={color(si)} />;
        })}
        <rect x={55 + si * 135} y={267} width={12} height={10} fill={color(si)} />
        <text x={73 + si * 135} y={277} fill="currentColor" fontSize={12}>{s.name.slice(0, 17)}</text>
      </g>)}
      {categories.map((c, i) => <text key={i} x={60 + (i + 0.5) * 800 / categories.length} y={239} fill="currentColor" textAnchor="middle" fontSize={categories.length > 12 ? 9 : 12}>{c.slice(0, categories.length > 12 ? 5 : 12)}</text>)}
    </>}
  </svg>;
}
