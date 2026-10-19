import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@/lib/theme";
import { api } from "@/lib/api";
import { Skills } from "./Skills";
import type { SkillInfo } from "@/lib/types";

vi.mock("@/lib/confirmHook", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true), toast: vi.fn() }),
}));

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});
vi.stubGlobal("matchMedia", (q: string) => ({
  matches: false,
  media: q,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  onchange: null,
  dispatchEvent: () => false,
}));

const mockSkill: SkillInfo = {
  id: "sk1",
  name: "pdf",
  description: "PDF helper",
  scope: "global",
  status: "published",
  owner_agent_id: null,
  owner_name: null,
  availability: "all",
  assigned_agent_ids: [],
  assigned_names: [],
  current_revision: 3,
  resource_count: 2,
  builder_session_id: null,
  updated_at: null,
  activation_count: 0,
  last_used_at: null,
};

beforeEach(() => {
  vi.spyOn(api, "listSkills").mockResolvedValue({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    skills: [mockSkill],
    count: 1,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Skills list activation labels", () => {
  it("shows 'Not recorded' when a skill has no activations", async () => {
    render(
      <MemoryRouter>
        <ThemeProvider>
          <Skills />
        </ThemeProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Not recorded")).toBeTruthy();
  });

  it("shows activation count and last used when recorded", async () => {
    vi.spyOn(api, "listSkills").mockResolvedValue({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
      skills: [
        { ...mockSkill, activation_count: 7, last_used_at: "2026-10-15T09:00:00" },
      ],
      count: 1,
    });
    render(
      <MemoryRouter>
        <ThemeProvider>
          <Skills />
        </ThemeProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Used 7 times")).toBeTruthy();
    expect(screen.getByText(/Last used/)).toBeTruthy();
  });
});
