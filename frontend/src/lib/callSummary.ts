/** Humanized "what it did" summaries for tool calls — derived only from the
 * recorded args/result, never invented. Unknown capabilities fall back to a
 * compact arg preview. */

export function safeJson(text: string | null | undefined): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function asObj(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

export function hostOf(url: unknown): string | null {
  if (typeof url !== "string" || !url) return null;
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function quoted(s: string, max = 60): string {
  return s.length > max ? `"${s.slice(0, max)}…"` : `"${s}"`;
}

function truncate(s: string, max = 80): string {
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

/** One-line preview for capabilities with no humanizer: the first couple of
 * scalar args, e.g. `query="stocks", limit=5`. */
function argPreview(args: Record<string, unknown> | null): string {
  if (!args) return "";
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    if (parts.length >= 2) break;
    if (typeof v === "string") parts.push(`${k}=${quoted(v, 40)}`);
    else if (typeof v === "number" || typeof v === "boolean") parts.push(`${k}=${String(v)}`);
  }
  return parts.length ? ` (${parts.join(", ")}${Object.keys(args).length > 2 ? ", …" : ""})` : "";
}

export function describeCall(
  capability: string,
  argsRaw: unknown,
  resultRaw: unknown,
): string {
  const args = asObj(argsRaw);
  const result = asObj(resultRaw);
  switch (capability) {
    case "skills_load": {
      const name = str(args?.name);
      return name ? `Loaded the ${name} skill` : "Loaded a skill";
    }
    case "skills_list":
      return "Listed available skills";
    case "skills_read_resource": {
      const name = str(args?.name ?? args?.skill);
      const path = str(args?.path ?? args?.resource);
      return name && path ? `Read ${path} from the ${name} skill` : "Read a skill resource";
    }
    case "datetime_now": {
      const tz = str(args?.timezone);
      const weekday = str(result?.weekday);
      const time = str(result?.time);
      const when = weekday && time ? `: ${weekday}, ${time}` : "";
      return `Checked the time${tz ? ` in ${tz}` : ""}${when}`;
    }
    case "web_fetch": {
      const host = hostOf(result?.url ?? args?.url);
      const title = str(result?.title);
      const chars = num(result?.total_chars);
      const what = title ? quoted(title, 48) : "a page";
      return `Fetched ${what}${host ? ` from ${host}` : ""}${chars !== null ? ` (${chars.toLocaleString()} characters)` : ""}`;
    }
    case "web_search": {
      const q = str(args?.query);
      const results = Array.isArray(result?.results) ? result.results.length : null;
      return `Searched the web${q ? ` for ${quoted(q)}` : ""}${results !== null ? ` — ${results} results` : ""}`;
    }
    case "terminal": {
      const cmd = str(args?.command);
      return cmd ? `Ran ${truncate(cmd, 80)}` : "Ran a shell command";
    }
    case "read_terminal":
      return "Read terminal output";
    case "close_terminal":
      return "Closed a terminal session";
    case "read_file": {
      const path = str(args?.path);
      return path ? `Read ${path}` : "Read a file";
    }
    case "write_file": {
      const path = str(args?.path);
      return path ? `Wrote ${path}` : "Wrote a file";
    }
    case "search_files": {
      const mode = str(args?.mode);
      const target = str(args?.query ?? args?.pattern ?? args?.path);
      if (mode === "list") return `Listed files${target ? ` in ${target}` : ""}`;
      return `Searched files${target ? ` for ${quoted(target, 48)}` : ""}`;
    }
    case "memory_recall": {
      const q = str(args?.query);
      return `Recalled memory${q ? ` for ${quoted(q)}` : ""}`;
    }
    case "memory_store":
      return "Stored a memory snippet";
    case "memory_remember_fact": {
      const e = str(args?.entity);
      const p = str(args?.predicate);
      return e && p ? `Remembered: ${e} ${p}` : "Remembered a fact";
    }
    case "memory_query_facts":
      return "Queried memory facts";
    case "memory_update":
      return "Updated MEMORY.md";
    case "agent_ask_user": {
      const q = str(args?.question);
      return q ? `Asked: ${truncate(q, 90)}` : "Asked you a question";
    }
    case "run_subagent": {
      const name = str(args?.name ?? args?.task);
      return name ? `Spawned a sub-agent — ${truncate(name, 60)}` : "Spawned a sub-agent";
    }
    case "read_subagent":
      return "Checked a sub-agent's progress";
    case "artifact_create": {
      const title = str(args?.title ?? args?.path);
      return title ? `Created artifact ${quoted(title, 48)}` : "Created an artifact";
    }
    case "artifact_inspect":
      return "Inspected an artifact";
    case "artifact_revise":
      return "Revised an artifact";
    case "artifact_adopt":
      return "Adopted a workspace file as an artifact";
    case "artifact_history":
      return "Listed artifact revisions";
    case "artifact_restore":
      return "Restored an artifact revision";
    case "browser_open":
    case "browser_navigate": {
      const host = hostOf(args?.url);
      return host ? `Opened ${host} in the browser` : "Opened a browser page";
    }
    case "browser_snapshot":
      return "Read the browser page";
    case "browser_click":
      return "Clicked an element in the browser";
    case "browser_type":
      return "Typed into the browser";
    case "knowledge_search":
    case "vault_search": {
      const q = str(args?.query);
      return `Searched the vault${q ? ` for ${quoted(q)}` : ""}`;
    }
    default:
      return `Called ${capability}${argPreview(args)}`;
  }
}
