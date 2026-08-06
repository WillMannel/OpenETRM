import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSelection } from "./useSelection";

describe("useSelection", () => {
  it("throws when used outside a SelectionProvider", () => {
    expect(() => renderHook(() => useSelection())).toThrow(/SelectionProvider/);
  });
});
