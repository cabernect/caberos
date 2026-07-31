interface CostBadgeProps {
  tokensIn: number;
  tokensOut: number;
  cost: number;
}

export function CostBadge({ tokensIn, tokensOut, cost }: CostBadgeProps) {
  const totalTokens = tokensIn + tokensOut;
  if (totalTokens === 0) return null;

  const costStr =
    cost > 0
      ? `$${cost < 0.001 ? cost.toFixed(5) : cost.toFixed(3)}`
      : "";

  return (
    <div className="mt-2 flex items-center gap-3">
      <span className="font-mono text-[11px] text-[var(--ink-3)]">
        {totalTokens.toLocaleString()} tokens
      </span>
      {costStr && (
        <span className="font-mono text-[11px] text-[var(--ink-3)]">
          {costStr}
        </span>
      )}
    </div>
  );
}
