/** Mirror of backend services.tool_status.tool_event_status — syscall
 * outcome → display status. `error` is `failed`, NOT `denied`: policy
 * outcomes and runtime outcomes stay distinct. Unknown outcomes fail
 * closed. */
export function toolEventStatus(outcome: string | null | undefined): string {
  switch (outcome) {
    case "ok":
      return "complete";
    case "denied":
      return "denied";
    case "error":
      return "failed";
    case "timeout":
      return "timeout";
    case "interrupted":
      return "interrupted";
    default:
      return "failed";
  }
}
