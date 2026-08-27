import type { Agent, Provider } from "@/lib/types";

export function needsOnboarding(
  providers: Array<Pick<Provider, "has_key">>,
  agents: Array<Pick<Agent, "id">>,
) {
  return !providers.some((provider) => provider.has_key) || agents.length === 0;
}
