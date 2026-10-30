import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { Agent, Operator, Provider } from "@/lib/types";
import {
  getTourState,
  getWizardState,
  onGuidanceChange,
  setWizardState,
} from "./guidanceState";
import { TourSpotlight } from "./TourSpotlight";
import { Onboarding } from "@/components/onboarding/Onboarding";
import { NotificationPermissionBanner } from "@/components/NotificationPermissionBanner";

/** Mounts the guidance layer — first-run onboarding and the Today spotlight
 * tour — deriving *whether guidance is needed* from server truth (operator
 * + providers + agents), not from what was clicked before. localStorage
 * only records dismissals: onboarding never re-arms itself, and replay
 * explicitly clears those flags.
 *
 * Page intro cards are NOT here — each page mounts its own inline card
 * (PageIntro) at the top of its content, per the fe_example design. */
interface Props {
  operator: Operator | null;
  providers: Provider[];
  agents: Agent[];
  onSetupRefresh: () => void;
}

/** A provider counts as configured when it holds a key, carries credential
 * fields (Azure/Bedrock), or is a keyless local runtime like Ollama. */
function providerReady(p: Provider): boolean {
  return p.has_key || p.credential_fields.length > 0 || p.type === "ollama";
}

export function GuidanceHost({
  operator,
  providers,
  agents,
  onSetupRefresh,
}: Props) {
  const [, setTick] = useState(0);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => onGuidanceChange(() => setTick((t) => t + 1)), []);

  const needsCredentials = operator?.must_change_password === true;
  const setupIncomplete =
    needsCredentials ||
    providers.every((p) => !providerReady(p)) ||
    agents.length === 0 ||
    agents.some((a) => !a.provider_id || !a.model);

  const showOnboarding = getWizardState() === "pending" && setupIncomplete;
  const tourActive = getTourState() === "active" && location.pathname === "/";

  return (
    <>
      {showOnboarding && (
        <Onboarding
          operator={operator}
          agents={agents}
          onComplete={onSetupRefresh}
          onImport={() => {
            // Migrating from another machine skips first-run ceremony —
            // the import flow restores a complete install.
            setWizardState("skipped");
            navigate("/settings?tab=migration");
            onSetupRefresh();
          }}
        />
      )}
      {tourActive && <TourSpotlight />}
      {/* The OS-notification opt-in card must never float over guidance
          overlays — it lives here so onboarding/tour suppress it. */}
      {!showOnboarding && !tourActive && <NotificationPermissionBanner />}
    </>
  );
}
