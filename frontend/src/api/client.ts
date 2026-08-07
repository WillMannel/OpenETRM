import createClient from "openapi-fetch";

import { getStoredToken } from "../auth/tokenStorage";
import type { paths } from "./generated/types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const apiClient = createClient<paths>({ baseUrl: API_BASE_URL });

// Attaches the stored bearer token (if any) to every request. /auth/login and
// /auth/register don't need one -- the backend just ignores the header on those routes
// -- so there's no need to special-case them here.
apiClient.use({
  onRequest({ request }) {
    const token = getStoredToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },
});
