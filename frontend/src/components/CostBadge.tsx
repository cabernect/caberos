interface CostBadgeProps {
  tokensIn: number;
  tokensOut: number;
  cost: number;
}

export function CostBadge({ tokensIn, tokensOut, cost }: CostBadgeProps) {
  const totalTokens = tokensIn + tokensOut;
  if (totalTokens === 0) return null;

  const costStr = cost > 0
    ? `$${cost < 0.001 ? cost.toFixed(5) : cost.toFixed(3)}`
    : "";

  return (
    <span className="text-xs text-muted-foreground/70 font-mono">
      {totalTokens.toLocaleString()} tokens{costStr && ` · ${costStr}`}
    </span>
  );
}
