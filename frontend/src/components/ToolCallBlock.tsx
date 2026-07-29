import { useState, useEffect } from "react";
import { ChevronRight, ChevronDown, Clock, Loader2, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ToolCallData {
  id: string;
  capability: string;
  args: Record<string, unknown>;
  status: "pending" | "running" | "complete" | "denied";
  result?: unknown;
}

interface ToolCallBlockProps {
  call: ToolCallData;
}

export function ToolCallBlock({ call }: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(
    call.status === "pending" || call.status === "running"
  );

  // Auto-expand during execution, auto-collapse on completion
  useEffect(() => {
    if (call.status === "pending" || call.status === "running") {
      setExpanded(true);
    } else {
      setExpanded(false);
    }
  }, [call.status]);

  const statusConfig = {
    pending: {
      icon: <Clock className="h-3.5 w-3.5 text-warning" />,
      label: "waiting...",
      color: "text-warning",
    },
    running: {
      icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />,
      label: call.capability === "shell.run"
        ? "running in sandbox..."
        : "executing...",
      color: "text-primary",
    },
    complete: {
      icon: <Check className="h-3.5 w-3.5 text-success" />,
      label: "done",
      color: "text-success",
    },
    denied: {
      icon: <X className="h-3.5 w-3.5 text-destructive" />,
      label: "denied",
      color: "text-destructive",
    },
  };

  const config = statusConfig[call.status];
  const argsStr = formatArgs(call.capability, call.args);

  return (
    <div className="rounded-md border border-border bg-card/50 my-1">
      {/* Header — clickable to toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        {config.icon}
        <code className="font-mono text-sm text-foreground">
          {call.capability}({argsStr})
        </code>
        <span className={cn("ml-auto text-xs", config.color)}>
          {config.label}
        </span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-border px-3 py-2">
          {call.status === "complete" && call.result != null && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Output:</p>
              <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-background p-2 font-mono text-xs text-foreground">
                {formatResult(call.result)}
              </pre>
            </div>
          )}
          {call.status === "denied" && (
            <p className="font-mono text-xs text-destructive">
              {typeof call.result === "string"
                ? call.result
                : "Call was denied by the syscall layer."}
            </p>
          )}
          {call.status === "pending" && (
            <p className="font-mono text-xs text-muted-foreground">
              Preparing to execute...
            </p>
          )}
          {call.status === "running" && (
            <p className="font-mono text-xs text-muted-foreground">
              Executing...
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function formatArgs(capability: string, args: Record<string, unknown>): string {
  if (capability === "shell.run" && args.command) {
    return `"${args.command}"`;
  }
  if (capability.startsWith("file.")) {
    const parts: string[] = [];
    if (args.path) parts.push(`"${args.path}"`);
    if (args.content) {
      const c = String(args.content);
      parts.push(`"${c.length > 50 ? c.slice(0, 50) + "..." : c}"`);
    }
    return parts.join(", ");
  }
  return JSON.stringify(args).slice(0, 80);
}

function formatResult(result: unknown): string {
  if (typeof result === "string") return result;
  if (result && typeof result === "object") {
    const obj = result as Record<string, unknown>;
    // For shell.run, show stdout/stderr nicely
    if ("stdout" in obj || "stderr" in obj) {
      const lines: string[] = [];
      if (obj.stdout) lines.push(String(obj.stdout));
      if (obj.stderr) lines.push(String(obj.stderr));
      if ("exit_code" in obj) lines.push(`[exit code: ${obj.exit_code}]`);
      return lines.join("\n");
    }
    // For file.list, show entries
    if ("entries" in obj && Array.isArray(obj.entries)) {
      return (obj.entries as Array<{ name: string; type: string; size: number }>)
        .map((e) => `${e.type === "dir" ? "📁" : "📄"} ${e.name} (${e.size} bytes)`)
        .join("\n");
    }
  }
  return JSON.stringify(result, null, 2);
}
