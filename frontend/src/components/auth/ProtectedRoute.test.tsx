import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "../../auth/AuthContext";
import { ProtectedRoute } from "./ProtectedRoute";

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div>login page</div>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<div>protected content</div>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  it("redirects to /login when there is no stored token", async () => {
    localStorage.clear();
    renderApp();

    await waitFor(() => expect(screen.getByText("login page")).toBeInTheDocument());
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });
});
