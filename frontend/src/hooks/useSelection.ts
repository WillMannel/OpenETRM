import { createContext, useContext } from "react";

/** Shared "which book / as-of date am I looking at" state, so the Blotter, Curve
 * Viewer, and Risk Dashboard pages stay in sync without prop-drilling or a router
 * query-string scheme -- overkill for a 3-page v1 slice. */
export interface SelectionState {
  bookId: string | undefined;
  setBookId: (id: string | undefined) => void;
  asOfDate: string;
  setAsOfDate: (date: string) => void;
}

export const SelectionContext = createContext<SelectionState | undefined>(undefined);

export function useSelection(): SelectionState {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used within a SelectionProvider");
  return ctx;
}
