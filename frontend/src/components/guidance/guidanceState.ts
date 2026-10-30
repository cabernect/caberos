/** Guidance state — three independent flags, all localStorage-backed.
 * Whether guidance *content* is needed derives from server truth
 * (providers/agents in setupData) — these flags only record what the
 * operator has seen or dismissed.
 *
 *   wizard: "pending" shows the setup wizard while setup is incomplete
 *   tour:   "offered" after the wizard — spotlight sequence runs while
 *           "active"; "done"/"skipped" end it permanently
 *   intros: per-page intro cards, one per page, each dismissed once seen
 */
export type WizardState = "pending" | "done" | "skipped";
export type TourState = "offered" | "active" | "done" | "skipped";

const WIZARD_KEY = "caberos_guidance_wizard";
const TOUR_KEY = "caberos_guidance_tour";
const INTROS_KEY = "caberos_guidance_intros_seen";

const CHANGE_EVENT = "caberos-guidance-change";

function emit() {
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function getWizardState(): WizardState {
  try {
    const v = localStorage.getItem(WIZARD_KEY);
    return v === "done" || v === "skipped" ? v : "pending";
  } catch {
    return "pending";
  }
}

export function setWizardState(state: WizardState) {
  try {
    localStorage.setItem(WIZARD_KEY, state);
  } catch {}
  emit();
}

export function getTourState(): TourState {
  try {
    const v = localStorage.getItem(TOUR_KEY);
    return v === "offered" || v === "active" || v === "done" || v === "skipped"
      ? v
      : "offered";
  } catch {
    return "offered";
  }
}

export function setTourState(state: TourState) {
  try {
    localStorage.setItem(TOUR_KEY, state);
  } catch {}
  emit();
}

export function getSeenIntros(): Set<string> {
  try {
    const raw = localStorage.getItem(INTROS_KEY);
    const list: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? (list as string[]) : []);
  } catch {
    return new Set();
  }
}

export function markIntroSeen(pageKey: string) {
  const seen = getSeenIntros();
  seen.add(pageKey);
  try {
    localStorage.setItem(INTROS_KEY, JSON.stringify([...seen]));
  } catch {}
  emit();
}

export function dismissAllIntros() {
  try {
    localStorage.setItem(INTROS_KEY, JSON.stringify(["*"]));
  } catch {}
  emit();
}

export function introsDismissed(): boolean {
  return getSeenIntros().has("*");
}

/** Re-arm only the page intro cards — Settings → Appearance "Show page
 * hints". Leaves wizard/tour flags alone. */
export function resetIntroFlags() {
  try {
    localStorage.removeItem(INTROS_KEY);
  } catch {}
  emit();
}

/** Re-arm everything — used by Settings "Replay tour" and data reset. */
export function resetGuidance() {
  try {
    localStorage.removeItem(WIZARD_KEY);
    localStorage.removeItem(TOUR_KEY);
    localStorage.removeItem(INTROS_KEY);
  } catch {}
  emit();
}

export function onGuidanceChange(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  return () => window.removeEventListener(CHANGE_EVENT, listener);
}
