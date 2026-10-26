/** Tour + page-intro content per docs/plans/v0.2/fe_example.
 *
 * Tour: three spotlight steps on the Today page — the dim+ring cutout lands
 * on whole regions (sidebar, Needs-you panel, composer), not nav items.
 *
 * Page intros: an inline card at the top of each page on first visit —
 * "above the content, pushing it down, never over it" (spec image). */

export interface TourStep {
  /** data-tour attribute on the highlighted region. */
  anchor: string;
  eyebrow: string;
  title: string;
  body: string;
  /** Preferred side of the region for the tailed card. */
  cardSide: "right" | "above" | "below";
}

export const TOUR_STEPS: TourStep[] = [
  {
    anchor: "sidebar",
    eyebrow: "1 of 3",
    title: "This is your map",
    body: "Today shows what needs you. Agents, Capabilities and Observability hold everything else.",
    cardSide: "right",
  },
  {
    anchor: "needs-you",
    eyebrow: "2 of 3",
    title: "What needs you shows up here",
    body: "Approvals, errors and setup tasks wait here until you handle them.",
    cardSide: "below",
  },
  {
    anchor: "composer",
    eyebrow: "3 of 3",
    title: "Ask anything from here",
    body: "Type a request — the run opens in the agent's chat so you can watch it work.",
    cardSide: "above",
  },
];

export interface PageIntroDef {
  /** Page key used for seen/dismiss tracking. */
  key: string;
  /** Route prefix the card attaches to. */
  routePrefix: string;
  /** Uppercase eyebrow label (the section name). */
  eyebrow: string;
  title: string;
  sub: string;
  /** Three check-marked facts — one column each. */
  facts: [string, string, string];
}

/** The seven pages that carry intro cards (spec: "Page intro cards · copy
 * for each page"). Today is covered by the spotlight tour instead. */
export const PAGE_INTROS: PageIntroDef[] = [
  {
    key: "agents",
    routePrefix: "/agents",
    eyebrow: "Agents",
    title: "Agents are assistants with their own job",
    sub: "Each one has its own tools, memory and permissions.",
    facts: [
      "Caber is your general agent",
      "AgentBuilder creates new ones",
      "Each agent has its own rules",
    ],
  },
  {
    key: "scheduler",
    routePrefix: "/scheduler",
    eyebrow: "Scheduler",
    title: "The Scheduler wakes agents on a timer",
    sub: "Use it for routine work that should happen on its own.",
    facts: [
      "Schedules run a task at set times",
      "A heartbeat repeats one prompt",
      "Every run has its own history",
    ],
  },
  {
    key: "mcps",
    routePrefix: "/mcps",
    eyebrow: "MCP servers",
    title: "MCP servers connect agents to outside tools",
    sub: "Add tools like web search or Notion, then decide what each may do.",
    facts: [
      "Some run on this machine, some online",
      "Some need a key or a sign-in",
      "Each tool has Allow, Ask or Block",
    ],
  },
  {
    key: "skills",
    routePrefix: "/skills",
    eyebrow: "Skills",
    title: "Skills teach your agents how to do things",
    sub: "A skill is a set of instructions an agent loads when it needs it.",
    facts: [
      "Built-in skills are ready to use",
      "Add your own from a URL or .zip",
      "Agents only use skills you turn on",
    ],
  },
  {
    key: "channels",
    routePrefix: "/channels",
    eyebrow: "Channels",
    title: "Channels let you chat from other apps",
    sub: "Talk to an agent from Telegram or Zalo, not only inside CaberOS.",
    facts: [
      "Choose which agent replies",
      "Limit who can message it",
      "Paused channels read nothing",
    ],
  },
  {
    key: "vault",
    routePrefix: "/vault",
    eyebrow: "Knowledge Vault",
    title: "The Vault is what your agents can read",
    sub: "Documents are indexed on this machine and stay here.",
    facts: [
      "Shared knowledge goes to every agent",
      "Agent scopes stay private",
      "Add files or paste a URL",
    ],
  },
  {
    key: "traces",
    routePrefix: "/traces",
    eyebrow: "Traces",
    title: "Traces are the record of every run",
    sub: "Open any run to see its steps, cost and what left this machine.",
    facts: [
      "See each tool call and result",
      "Spot failures quickly",
      "Copy a run as JSON",
    ],
  },
];

export const INTRO_BY_KEY: Record<string, PageIntroDef> = Object.fromEntries(
  PAGE_INTROS.map((d) => [d.key, d]),
);

/** Conversation views live under /agents/:id/chat but are a different
 * surface — intros only attach to the nav destinations themselves. */
const EXCLUDED = [/^\/agents\/[^/]+\/chat/];

export function introForPath(pathname: string): PageIntroDef | undefined {
  if (EXCLUDED.some((re) => re.test(pathname))) return undefined;
  return PAGE_INTROS.find((s) => pathname.startsWith(s.routePrefix));
}
