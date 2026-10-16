import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { TraceInspector } from "./TraceInspector";
import { api } from "@/lib/api";
import type { TraceRow } from "@/lib/traceLayout";
import type { TimelineEvent } from "@/lib/types";

const ROW = (event: TimelineEvent | null, over: Partial<TraceRow> = {}): TraceRow =>
  ({
    id: event?.id ?? "root",
    event,
    parent_id: null,
    depth: 0,
    hasChildren: false,
    timing: "recorded",
    estimated_time: false,
    ...over,
  }) as unknown as TraceRow;

const MODEL_EVENT = (_id: string, callId: string): TimelineEvent =>
  ({
    id: `model_call:${callId}`,
    type: "model_call",
    at: "2024-01-01T00:00:00Z",
    call_id: null,
    sub_agent_id: null,
    parent_id: null,
    status: "ok",
    data: { model_name: "gpt-6", tokens_in: 10, tokens_out: 4 },
    redacted: false,
    truncated: false,
    estimated_time: false,
  }) as unknown as TimelineEvent;

const CTX = (callId: string, state = "available") => ({
  call_id: callId,
  state,
  surface: "chat",
  redacted: true,
  truncated: false,
  reason: null,
  metadata: { agent_id: "a1", run_id: "r1", turn: 0, purpose: "reasoning" },
  payload: {
    rendered_context: { messages: [{ role: "user", content: "hi" }], tools: [] },
    dispatch_input: { model: "gpt-6", messages: [{ role: "user", content: "hi" }] },
  },
  label:
    "Captured at CaberOS's SDK boundary after request preparation and redaction; not a native provider wire capture.",
});

afterEach(() => vi.restoreAllMocks());

describe("TraceInspector model-call input", () => {
  it("fetches the captured dispatch input for the selected call", async () => {
    const getCtx = vi.spyOn(api, "getModelCallContext").mockResolvedValue(CTX("call-A"));
    render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    await waitFor(() => expect(getCtx).toHaveBeenCalledWith("call-A"));
    expect(await screen.findByText(/Dispatch input/)).toBeInTheDocument();
    expect(screen.getByText(/SDK boundary after request preparation/)).toBeInTheDocument();
  });

  it("never renders a response for a different call", async () => {
    vi.spyOn(api, "getModelCallContext").mockResolvedValue(CTX("call-OTHER"));
    render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    expect(await screen.findByText(/Capture unavailable for this call/)).toBeInTheDocument();
  });

  it("shows per-state labels: expired body is honest, not reconstructed", async () => {
    vi.spyOn(api, "getModelCallContext").mockResolvedValue({
      ...CTX("call-A", "expired"),
      payload: null,
      reason: "age_limit",
    });
    render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    expect(await screen.findByText("expired")).toBeInTheDocument();
    expect(screen.getByText(/expired by retention policy/i)).toBeInTheDocument();
    expect(screen.queryByText(/Dispatch input/)).not.toBeInTheDocument();
  });

  it("renders collapsible tool schemas when present", async () => {
    vi.spyOn(api, "getModelCallContext").mockResolvedValue({
      ...CTX("call-A"),
      payload: {
        rendered_context: {
          messages: [],
          tools: [{ type: "function", function: { name: "web_fetch" } }],
        },
        dispatch_input: { model: "gpt-6", messages: [] },
      },
    });
    render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    expect(await screen.findByText(/Tool schemas/)).toBeInTheDocument();
  });

  it("Output tab is honest: response bodies are not recorded", async () => {
    vi.spyOn(api, "getModelCallContext").mockResolvedValue(CTX("call-A"));
    render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Output" }));
    expect(
      await screen.findByText(/Response bodies are not recorded/),
    ).toBeInTheDocument();
  });
});

describe("TraceInspector selection guard + states", () => {
  it("out-of-order A→B fetch never renders A's body under B", async () => {
    const resolvers: Record<string, (v: unknown) => void> = {};
    vi.spyOn(api, "getModelCallContext").mockImplementation(
      (callId: string) =>
        new Promise((res) => {
          resolvers[callId] = res as (v: unknown) => void;
        }),
    );
    const { rerender } = render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    // Switch selection to B before A resolves.
    rerender(
      <TraceInspector row={ROW(MODEL_EVENT("m2", "call-B"))} providerNames={{}} />,
    );
    // B resolves first.
    resolvers["call-B"]({ ...CTX("call-B"), state: "available" });
    expect(await screen.findByText(/Dispatch input/)).toBeInTheDocument();
    // A resolves late — must NOT overwrite B's rendered body.
    resolvers["call-A"]({ ...CTX("call-A"), state: "expired" });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/expired by retention/)).not.toBeInTheDocument();
    expect(screen.getByText(/Dispatch input/)).toBeInTheDocument();
  });

  it.each([
    ["failed", /Capture failed before the request body was saved/],
    ["not_applicable", /not captured/],
    ["not_recorded", /No request body recorded/],
  ])("state %s is honest", async (state, pattern) => {
    vi.spyOn(api, "getModelCallContext").mockResolvedValue({
      ...CTX("call-A", state),
      payload: null,
      reason: "save_failed",
    });
    render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    expect(await screen.findByText(pattern)).toBeInTheDocument();
  });

  it("shows metadata refs + rendered context when present", async () => {
    vi.spyOn(api, "getModelCallContext").mockResolvedValue({
      ...CTX("call-A"),
      metadata: {
        agent_id: "a1",
        core_revision_id: "rev-9",
        summary_version: 3,
        source_message_ids_total: 42,
        component_budget: { history: 1200, tools: 340 },
      },
      payload: {
        rendered_context: {
          messages: [{ role: "user", content: "rendered hi" }],
          tools: [],
        },
        dispatch_input: { model: "gpt-6", messages: [] },
      },
    });
    render(
      <TraceInspector row={ROW(MODEL_EVENT("m1", "call-A"))} providerNames={{}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Input" }));
    expect(await screen.findByText("rev-9")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/Rendered context/)).toBeInTheDocument();
    expect(screen.getByText(/Context breakdown/)).toBeInTheDocument();
  });
});
