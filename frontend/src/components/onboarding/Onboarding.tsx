import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { Agent, Operator } from "@/lib/types";
import {
  dismissAllIntros,
  setTourState,
  setWizardState,
} from "@/components/guidance/guidanceState";
import {
  CenteredStage,
  StepTransition,
  StepperShell,
  type StepDef,
} from "./OnboardingShell";
import {
  StepAgents,
  StepPassword,
  StepPermissions,
  StepProvider,
  StepReady,
  StepRuntime,
  StepWelcome,
  TOOL_ROWS,
  buildGrantList,
  type ProviderResult,
  type ToolChoice,
} from "./steps";

/** First-run onboarding per docs/plans/v0.2/fe_example — full-screen flow:
 * welcome → (password if default login) → runtime → provider → permissions
 * → agents → ready. Completing offers the Today spotlight tour via
 * guidanceState. Mounted only while the wizard flag is pending AND server
 * state says setup is actually needed (GuidanceHost decides). */
interface Props {
  operator: Operator | null;
  agents: Agent[];
  onComplete: () => void;
  onImport: () => void;
}

export function Onboarding({
  operator,
  agents,
  onComplete,
  onImport,
}: Props) {
  const navigate = useNavigate();
  const needsPassword = operator?.must_change_password === true;

  const steps: StepDef[] = useMemo(() => {
    const list: StepDef[] = [];
    if (needsPassword)
      list.push({ key: "password", label: "Protect your workspace" });
    list.push(
      { key: "runtime", label: "Get your machine ready" },
      { key: "provider", label: "Connect an AI" },
      { key: "permissions", label: "Choose what agents may do" },
      { key: "agents", label: "Meet your agents" },
    );
    return list;
  }, [needsPassword]);

  // stage: -1 welcome · 0..steps.length-1 stepper steps · steps.length ready
  const [stage, setStage] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [op, setOp] = useState<Operator | null>(operator);
  const [providerResult, setProviderResult] = useState<ProviderResult | null>(null);
  const [permissionsCustom, setPermissionsCustom] = useState(false);
  const [passwordSet, setPasswordSet] = useState(!needsPassword);

  const stepIndex = stage; // index into steps when 0..steps.length-1
  const currentKey = stage >= 0 && stage < steps.length ? steps[stage].key : null;

  const finish = (go?: { path: string }) => {
    setWizardState("done");
    setTourState("active");
    if (go) navigate(go.path);
    onComplete();
  };

  const skipAll = () => {
    setWizardState("skipped");
    setTourState("skipped");
    dismissAllIntros();
    onComplete();
  };

  if (stage === -1) {
    return (
      <CenteredStage>
        <StepWelcome onStart={() => setStage(0)} onImport={onImport} />
      </CenteredStage>
    );
  }

  if (stage >= steps.length) {
    const firstAgent = agents[0];
    return (
      <CenteredStage>
        <StepReady
          summary={{
            protected_: passwordSet ? "Password set" : "Default login kept",
            ai: providerResult?.provider?.name ?? (providerResult?.skipped ? "Decide later" : "Not connected"),
            permissions: permissionsCustom ? "Custom" : "Recommended",
            agents: agents.length
              ? `${agents.map((a) => a.name).join(" and ")}${agents.every((a) => a.model && a.provider_id) ? "" : " — some need a model"}`
              : "None yet",
          }}
          firstAgentName={firstAgent?.name ?? null}
          onChat={() => firstAgent && finish({ path: `/agents/${firstAgent.id}/chat` })}
          onToday={() => finish({ path: "/" })}
        />
      </CenteredStage>
    );
  }

  const back = () => setStage((s) => s - 1);
  const next = () => setStage((s) => s + 1);

  const applyModel = async (result: ProviderResult) => {
    if (!result.provider || !result.model) return;
    const targets = agents.filter((a) => !a.provider_id || !a.model);
    for (const agent of targets) {
      await api.updateAgent(agent.id, {
        provider_id: result.provider.id,
        model_name: result.model,
      });
    }
  };

  const applyPermissions = async (choices: Record<string, ToolChoice>) => {
    const all = await api.listCapabilities();
    const grants = buildGrantList(all, choices);
    for (const agent of agents) {
      await api.updateAgent(agent.id, { capabilities: grants });
    }
  };

  const openChat = (agentId: string, prompt?: string) => {
    const q = prompt ? `?prompt=${encodeURIComponent(prompt)}` : "";
    finish({ path: `/agents/${agentId}/chat${q}` });
  };

  return (
    <StepperShell
      steps={steps}
      current={stepIndex}
      asideFooter={
        <button
          type="button"
          onClick={skipAll}
          className="mt-2 block text-[11.5px] text-[var(--ink-3)] underline"
          style={{ background: "none", border: "none", cursor: "pointer" }}
        >
          Skip setup
        </button>
      }
    >
      <StepTransition step={stepIndex}>
        {currentKey === "password" && (
        <StepPassword
          operator={op}
          busy={busy}
          setBusy={setBusy}
          onBack={back}
          onSkip={next}
          onDone={(o) => {
            setOp(o);
            setPasswordSet(true);
            next();
          }}
        />
      )}
      {currentKey === "runtime" && <StepRuntime onBack={back} onDone={next} />}
      {currentKey === "provider" && (
        <StepProvider
          onBack={back}
          onDone={(r) => {
            setProviderResult(r);
            void applyModel(r)
              .catch(() => {})
              .finally(next);
          }}
        />
      )}
      {currentKey === "permissions" && (
        <StepPermissions
          onBack={back}
          onDone={(choices) => {
            const recommended = TOOL_ROWS.every(
              (r) => choices[r.key] === r.recommended,
            );
            setPermissionsCustom(!recommended);
            void applyPermissions(choices)
              .catch(() => {})
              .finally(next);
          }}
        />
      )}
      {currentKey === "agents" && (
        <StepAgents agents={agents} onOpenChat={openChat} onBack={back} onDone={next} />
      )}
      </StepTransition>
    </StepperShell>
  );
}
