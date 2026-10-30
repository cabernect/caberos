import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PageIntro } from "./PageIntro";
import { INTRO_BY_KEY } from "./tourStops";
import { getSeenIntros, introsDismissed } from "./guidanceState";

describe("PageIntro", () => {
  beforeEach(() => localStorage.clear());

  it("renders the olive card with eyebrow, title, sub and three facts", () => {
    render(<PageIntro def={INTRO_BY_KEY.agents} />);
    expect(screen.getByText("Agents")).toBeTruthy();
    expect(
      screen.getByText("Agents are assistants with their own job"),
    ).toBeTruthy();
    expect(
      screen.getByText("AgentBuilder creates new ones"),
    ).toBeTruthy();
    expect(screen.getByText("Got it")).toBeTruthy();
    expect(screen.getByText("Learn more")).toBeTruthy();
    expect(screen.getByText("Don't show hints again")).toBeTruthy();
  });

  it("'Got it' marks just this page seen", () => {
    render(<PageIntro def={INTRO_BY_KEY.scheduler} />);
    fireEvent.click(screen.getByText("Got it"));
    expect(getSeenIntros().has("scheduler")).toBe(true);
    expect(introsDismissed()).toBe(false);
  });

  it("the × dismisses the card the same way", () => {
    render(<PageIntro def={INTRO_BY_KEY.traces} />);
    fireEvent.click(screen.getByLabelText(/Dismiss .* hint/));
    expect(getSeenIntros().has("traces")).toBe(true);
  });

  it("'Don't show hints again' suppresses every intro", () => {
    render(<PageIntro def={INTRO_BY_KEY.vault} />);
    fireEvent.click(screen.getByText("Don't show hints again"));
    expect(introsDismissed()).toBe(true);
  });

  it("renders nothing once seen or globally dismissed", () => {
    const { rerender, container } = render(
      <PageIntro def={INTRO_BY_KEY.channels} />,
    );
    fireEvent.click(screen.getByText("Got it"));
    rerender(<PageIntro def={INTRO_BY_KEY.channels} />);
    expect(container.innerHTML).toBe("");
  });
});
