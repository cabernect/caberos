import { createContext } from "react";
import type { ConfirmOptions } from "./confirmTypes";

export interface ConfirmContextValue {
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
  toast: (message: string) => void;
}

export const ConfirmContext = createContext<ConfirmContextValue | null>(null);
