export type SetupGuidePhase = 0 | 1 | 2 | 3;

const GUIDE_PHASE_KEY = "caberos_setup_guide_phase";
const GUIDE_AGENT_KEY = "caberos_setup_guide_agent";
const GUIDE_DISMISSED_KEY = "caberos_setup_guide_dismissed";

export function getSetupGuidePhase(): SetupGuidePhase {
  try {
    const value = Number(localStorage.getItem(GUIDE_PHASE_KEY));
    return value >= 0 && value <= 3 ? value as SetupGuidePhase : 0;
  } catch {
    return 0;
  }
}

export function setSetupGuideAgentId(agentId: string) {
  try { localStorage.setItem(GUIDE_AGENT_KEY, agentId); } catch {}
}

export function getSetupGuideAgentId() {
  try { return localStorage.getItem(GUIDE_AGENT_KEY) || "caber"; } catch { return "caber"; }
}

export function setSetupGuidePhase(phase: SetupGuidePhase) {
  try {
    localStorage.setItem(GUIDE_PHASE_KEY, String(phase));
    localStorage.removeItem(GUIDE_DISMISSED_KEY);
  } catch {}
  window.dispatchEvent(new Event("caberos-setup-guide-change"));
}

export function dismissSetupGuide() {
  try { localStorage.setItem(GUIDE_DISMISSED_KEY, "true"); } catch {}
  window.dispatchEvent(new Event("caberos-setup-guide-change"));
}

export function isSetupGuideDismissed() {
  try { return localStorage.getItem(GUIDE_DISMISSED_KEY) === "true"; } catch { return false; }
}

export function shouldShowSetupGuide(hasUsableProvider: boolean) {
  const phase = getSetupGuidePhase();
  if (hasUsableProvider && phase < 2) return false;
  try {
    return localStorage.getItem(GUIDE_DISMISSED_KEY) !== "true";
  } catch {
    return true;
  }
}
