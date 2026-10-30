import type { Notification } from "./types";

/** Entity-type → list page, used when a notification has no action_path
 *  or its deep link's target is gone (pages ignore unknown query params
 *  and render their list view — graceful degradation, no extra probe). */
const ENTITY_FALLBACK: Record<string, string> = {
  agent: "/agents",
  session: "/agents",
  run: "/agents",
  schedule: "/scheduler",
  skill: "/skills",
  artifact: "/agents",
  index_generation: "/vault",
  provider: "/settings",
  mcp_server: "/mcps",
  app: "/settings",
};

export function notificationTarget(n: Notification): string {
  if (n.action_path) return n.action_path;
  if (n.entity_type && ENTITY_FALLBACK[n.entity_type]) {
    return ENTITY_FALLBACK[n.entity_type];
  }
  return "/notifications";
}
