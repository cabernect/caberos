import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { RunTimeline } from "./RunTimeline";
import type { RunDetail, TimelineEvent } from "@/lib/types";

// jsdom has no layout scrolling
Element.prototype.scrollIntoView = vi.fn();

function ev(over: Partial<TimelineEvent>): TimelineEvent {
  return {
    id: "e1",
    type: "tool_call",
    at: "2024-01-01T00:00:01Z",
    call_id: null,
    sub_agent_id: null,
    parent_id: null,
    status: "complete",
    data: {},
    redacted: false,
    truncated: false,
    estimated_time: false,
    ...over,
  };
}

const RUN: RunDetail = {
  id: "run-1",
  agent_id: "a1",
  agent_name: "Caber",
  session_id: "s1",
  status: "completed",
  trigger: "dashboard",
  tokens_in: 500,
  tokens_out: 120,
  cost: 0.05,
  latency_ms: 6441,
  is_test: false,
  started_at: "2024-01-01T00:00:00Z",
  completed_at: "2024-01-01T00:00:06.441Z",
  error: null,
  context_tokens: 0,
  max_context_tokens: 0,
  context_breakdown: {},
  loaded_capabilities: [],
  manifest: null,
  messages: [],
  audit_records: [],
  model_calls: [],
  timeline: [],
} as unknown as RunDetail;

const PROVIDERS = { "p-uuid-123": "OpenAI" };

const MODEL = ev({
  id: "m1",
  type: "model_call",
  status: "ok",
  data: {
    provider_id: "p-uuid-123",
    model_name: "gpt-6",
    tokens_in: 12508,
    tokens_out: 262,
    thinking_tokens: null,
    cost: 0.01,
    latency_ms: 6357,
    streamed: true,
  },
});

const TOOL = ev({
  id: "tool:-:c1",
  type: "tool_call",
  at: "2024-01-01T00:00:02Z",
  call_id: "c1",
  status: "complete",
  data: {
    capability: "doc_search",
    args: { query: "deploy notes" },
    result: { count: 2, trace: { fusion: "hybrid" } },
    latency_ms: 120,
  },
});

const CHILD = ev({
  id: "child-1",
  type: "retrieval",
  at: "2024-01-01T00:00:02.5Z",
  parent_id: "tool:-:c1",
  status: "ok",
  data: { query: "deploy notes", count: 2 },
});

describe("RunTimeline — trace workspace", () => {
  it("renders root + model rows with aligned bars and friendly labels", () => {
    render(<RunTimeline events={[MODEL]} run={RUN} providerNames={PROVIDERS} />);
    expect(screen.getByTestId("trace-span-bar-trace-root")).toBeInTheDocument();
    expect(screen.getByTestId("trace-span-bar-m1")).toBeInTheDocument();
    // provider name resolves, UUID never primary (row label + inspector header)
    expect(screen.getAllByText(/Generation OpenAI \/ gpt-6/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/p-uuid-123/)).not.toBeInTheDocument();
  });

  it("inspector defaults to the first model call with real token counts", () => {
    render(<RunTimeline events={[MODEL]} run={RUN} providerNames={PROVIDERS} />);
    expect(screen.queryByText("unlinked")).not.toBeInTheDocument();
    const inspector = screen.getByTestId("trace-inspector");
    expect(within(inspector).getByText("12,508")).toBeInTheDocument();
    expect(within(inspector).getByText("262")).toBeInTheDocument();
    // null thinking is distinct from 0 (thinking + cached both report it)
    expect(within(inspector).getAllByText("Not reported").length).toBeGreaterThan(0);
  });

  it("explicit 0 thinking renders 0, not Not reported", () => {
    const m0 = ev({
      id: "m0",
      type: "model_call",
      data: { provider_id: "p-uuid-123", model_name: "gpt-6", tokens_in: 1, tokens_out: 2, thinking_tokens: 0, cost: 0 },
    });
    render(<RunTimeline events={[m0]} run={RUN} providerNames={PROVIDERS} />);
    const inspector = screen.getByTestId("trace-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Overview" }));
    const rows = within(inspector).getByText("Thinking tokens").parentElement!;
    expect(rows.textContent).toContain("0");
    expect(rows.textContent).not.toContain("Not reported");
  });

  it("tool selection shows projected Input/Output, not the whole payload", () => {
    render(<RunTimeline events={[TOOL, CHILD]} run={RUN} providerNames={PROVIDERS} />);
    fireEvent.click(screen.getByTestId("trace-row-tool:-:c1"));
    const inspector = screen.getByTestId("trace-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Input" }));
    expect(within(inspector).getByText("deploy notes")).toBeInTheDocument();
    fireEvent.click(within(inspector).getByRole("button", { name: "Output" }));
    expect(within(inspector).getAllByText(/hybrid/).length).toBeGreaterThan(0);
  });

  it("model Input/Output is honest about missing per-call capture", () => {
    const onViewMessages = vi.fn();
    render(
      <RunTimeline events={[MODEL]} run={RUN} providerNames={PROVIDERS} onViewMessages={onViewMessages} />,
    );
    const inspector = screen.getByTestId("trace-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Input" }));
    expect(within(inspector).getByText(/was not recorded/)).toBeInTheDocument();
    fireEvent.click(within(inspector).getByRole("button", { name: "View run messages" }));
    expect(onViewMessages).toHaveBeenCalled();
    expect(within(inspector).queryByText("deploy notes")).not.toBeInTheDocument();
  });

  it("nested children collapse/re-expand and parent jump selects the parent", () => {
    render(<RunTimeline events={[TOOL, CHILD]} run={RUN} providerNames={PROVIDERS} />);
    expect(screen.getByTestId("trace-row-child-1")).toBeInTheDocument();
    fireEvent.click(screen.getAllByLabelText("Collapse")[0]);
    expect(screen.queryByTestId("trace-row-child-1")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByLabelText("Expand")[0]);
    const child = screen.getByTestId("trace-row-child-1");
    expect(child).toBeInTheDocument();
    fireEvent.click(within(child).getByLabelText(/Jump to parent/));
    expect(screen.getByTestId("trace-row-tool:-:c1")).toHaveAttribute("aria-selected", "true");
  });

  it("unknown-time rows get a label, never a zero-width fake bar", () => {
    render(
      <RunTimeline
        events={[ev({ id: "x", at: null, estimated_time: true })]}
        run={RUN}
        providerNames={PROVIDERS}
      />,
    );
    expect(screen.getAllByText("Unknown time").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("trace-span-bar-x")).not.toBeInTheDocument();
  });

  it("Show events reveals envelope rows hidden by default", () => {
    render(
      <RunTimeline
        events={[MODEL, ev({ id: "ms", type: "manifest" }), ev({ id: "rs", type: "run_started" })]}
        run={RUN}
        providerNames={PROVIDERS}
      />,
    );
    expect(screen.queryByTestId("trace-row-ms")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getAllByText("manifest").length).toBeGreaterThan(0);
    expect(screen.getAllByText("run started").length).toBeGreaterThan(0);
  });

  it("search keeps matching rows plus their ancestors", () => {
    render(<RunTimeline events={[TOOL, CHILD]} run={RUN} providerNames={PROVIDERS} />);
    fireEvent.change(screen.getByLabelText(/Search trace spans/), { target: { value: "retrieval" } });
    expect(screen.getByTestId("trace-row-child-1")).toBeInTheDocument();
    // ancestor retained even though it doesn't match the query
    expect(screen.getByTestId("trace-row-tool:-:c1")).toBeInTheDocument();
    expect(screen.getByTestId("trace-row-trace-root")).toBeInTheDocument();
  });

  it("arrow keys move the selection through visible rows", () => {
    render(<RunTimeline events={[TOOL, CHILD]} run={RUN} providerNames={PROVIDERS} />);
    const tree = screen.getByRole("tree");
    // default selection is the first tool call — Up goes to root
    fireEvent.keyDown(tree, { key: "ArrowUp" });
    expect(screen.getByTestId("trace-row-trace-root")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    expect(screen.getByTestId("trace-row-tool:-:c1")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    expect(screen.getByTestId("trace-row-child-1")).toHaveAttribute("aria-selected", "true");
  });

  it("empty run renders a human empty state", () => {
    render(<RunTimeline events={[]} run={RUN} />);
    expect(screen.getByText(/No trace events recorded/)).toBeInTheDocument();
  });
});

const RUN_WITH_MSG = {
  ...RUN,
  messages: [
    { id: "m-u", run_id: "run-1", role: "user", content: "hello agent", seq: 0, created_at: "2024-01-01T00:00:00Z", subagent_id: null },
    { id: "m-a", run_id: "run-1", role: "assistant", content: "hi back", seq: 1, created_at: "2024-01-01T00:00:05Z", subagent_id: null },
  ],
  manifest: {
    agent_version_id: "v1",
    agent_version_number: 3,
    model_provider_id: "p-uuid-123",
    model_name: "gpt-6",
    plan_revision_id: null,
    schedule_revision_id: null,
    skill_revision_ids: {},
    retrieval_profile_revision_id: null,
    knowledge_snapshot_ids: [],
    browser_profile_id: null,
    artifact_base_revision_ids: [],
  },
} as unknown as RunDetail;

describe("RunTimeline — corrections", () => {
  it("flags pills surface redacted/truncated on the selected span", () => {
    render(<RunTimeline events={[ev({ id: "r1", redacted: true, truncated: true })]} run={RUN} />);
    const inspector = screen.getByTestId("trace-inspector");
    expect(within(inspector).getByText("redacted")).toBeInTheDocument();
    expect(within(inspector).getByText("truncated")).toBeInTheDocument();
  });

  it("capability_load Output shows the backend 'capabilities' key", () => {
    render(
      <RunTimeline
        events={[ev({ id: "cl", type: "capability_load", data: { capabilities: ["read_file", "web_fetch"] } })]}
        run={RUN}
      />,
    );
    fireEvent.click(screen.getByTestId("trace-row-cl"));
    const inspector = screen.getByTestId("trace-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Output" }));
    expect(within(inspector).getAllByText(/read_file/).length).toBeGreaterThan(0);
  });

  it("approval_decision Output shows the real decision status", () => {
    render(
      <RunTimeline
        events={[ev({ id: "ad", type: "approval_decision", status: "denied", data: { decided_by: "admin" } })]}
        run={RUN}
      />,
    );
    fireEvent.click(screen.getByTestId("trace-row-ad"));
    const inspector = screen.getByTestId("trace-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Output" }));
    expect(within(inspector).getAllByText("denied").length).toBeGreaterThan(0);
  });

  it("root Input/Output show actual run messages labelled as such", () => {
    render(<RunTimeline events={[MODEL]} run={RUN_WITH_MSG} providerNames={PROVIDERS} />);
    // select the root row
    fireEvent.click(screen.getByTestId("trace-row-trace-root"));
    const inspector = screen.getByTestId("trace-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Input" }));
    expect(within(inspector).getByText("hello agent")).toBeInTheDocument();
    expect(within(inspector).getByText(/not the full model request/)).toBeInTheDocument();
    fireEvent.click(within(inspector).getByRole("button", { name: "Output" }));
    expect(within(inspector).getByText("hi back")).toBeInTheDocument();
  });

  it("model IO placeholder never copies run messages", () => {
    render(<RunTimeline events={[MODEL]} run={RUN_WITH_MSG} providerNames={PROVIDERS} />);
    const inspector = screen.getByTestId("trace-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Input" }));
    expect(within(inspector).getByText(/was not recorded/)).toBeInTheDocument();
    expect(within(inspector).queryByText("hello agent")).not.toBeInTheDocument();
  });

  it("root ArrowLeft collapses children; ArrowRight re-expands", () => {
    render(<RunTimeline events={[TOOL, CHILD]} run={RUN} />);
    const tree = screen.getByRole("tree");
    fireEvent.keyDown(tree, { key: "ArrowUp" }); // root
    fireEvent.keyDown(tree, { key: "ArrowLeft" });
    expect(screen.queryByTestId("trace-row-tool:-:c1")).not.toBeInTheDocument();
    fireEvent.keyDown(tree, { key: "ArrowRight" });
    expect(screen.getByTestId("trace-row-tool:-:c1")).toBeInTheDocument();
  });

  it("search matches inside collapsed parents and hides nothing visible", () => {
    render(<RunTimeline events={[TOOL, CHILD]} run={RUN} />);
    // collapse tool root, then search for the child — it must surface
    fireEvent.click(screen.getAllByLabelText("Collapse")[0]);
    expect(screen.queryByTestId("trace-row-child-1")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Search trace spans/), { target: { value: "retrieval" } });
    expect(screen.getByTestId("trace-row-child-1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Search trace spans/), { target: { value: "zzzz-nothing" } });
    expect(screen.getByText(/No matching observations/)).toBeInTheDocument();
  });

  it("a hidden selection falls back to a visible row", () => {
    render(<RunTimeline events={[TOOL, CHILD]} run={RUN} />);
    fireEvent.click(screen.getByTestId("trace-row-child-1")); // select child
    fireEvent.change(screen.getByLabelText(/Search trace spans/), { target: { value: "doc_search" } });
    // child no longer visible — inspector must show the tool row, not the hidden child
    // fallback prefers the first visible span (the matching tool root)
    expect(screen.getByTestId("trace-row-tool:-:c1")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("trace-inspector")).toHaveTextContent("doc_search");
  });

  it("unlinked legacy rows carry the dashed hint and inspector origin", () => {
    render(
      <RunTimeline
        events={[ev({ id: "leg", call_id: null, at: null, estimated_time: true, data: { audit_id: "au-9" } })]}
        run={RUN}
      />,
    );
    expect(screen.getByText("unlinked")).toBeInTheDocument();
    const inspector = screen.getByTestId("trace-inspector");
    expect(within(inspector).getByText("Audit record")).toBeInTheDocument();
  });
});
