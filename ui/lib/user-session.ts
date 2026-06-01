// Anonymous, server-driven user identification for the consumer queue flow.
//
// We mint a UUID into an HTTP-only cookie (`astroturf_uid`) the first time a
// browser hits any API that calls `requireUserId`. The UID is opaque, stable
// across sessions and tabs, and never appears in client JS - there is no
// localStorage, no client-readable cookie. The badge component reads its
// list of recent requests via /api/user-requests, which uses this cookie
// server-side to filter analysis_requests.requested_by.

import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";

const COOKIE_NAME = "astroturf_uid";
const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

export interface UserSession {
  uid: string;
  /** True if this request created the cookie (caller should set it on the response). */
  isNew: boolean;
}

/**
 * Read the current user's UID, or mint a new one. Caller is responsible
 * for attaching the cookie to the outgoing response via
 * `applyUserCookie(response, session)` so that brand-new visitors get the
 * cookie back on this very response.
 */
export async function getOrCreateUserSession(): Promise<UserSession> {
  const store = await cookies();
  const existing = store.get(COOKIE_NAME)?.value;
  if (existing && isValidUid(existing)) {
    return { uid: existing, isNew: false };
  }
  return { uid: randomUUID(), isNew: true };
}

/**
 * Read the current user's UID without minting a new one. Returns null when
 * the browser has no cookie yet. Use this for read endpoints that should
 * return empty for unrecognised users instead of silently creating an
 * identity on a GET.
 */
export async function getUserId(): Promise<string | null> {
  const store = await cookies();
  const value = store.get(COOKIE_NAME)?.value;
  return value && isValidUid(value) ? value : null;
}

/**
 * Attach the user cookie to a Response. Only sets it when `isNew` is true
 * so we aren't re-writing the same cookie on every request.
 *
 * SameSite=Lax keeps the cookie out of cross-site POSTs (CSRF-safe for our
 * idempotent reads, and our writes also require a same-origin POST). Secure
 * is on when behind https in production. HttpOnly means client JS cannot
 * read it (the badge has to call our API to learn about the user's queue).
 */
export function applyUserCookie(response: Response, session: UserSession): Response {
  if (!session.isNew) return response;
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  response.headers.append(
    "Set-Cookie",
    `${COOKIE_NAME}=${session.uid}; Path=/; Max-Age=${ONE_YEAR_SECONDS}; HttpOnly; SameSite=Lax${secure}`,
  );
  return response;
}

function isValidUid(value: string): boolean {
  // Accept the UUID v4 format we mint. We reject everything else so a
  // forged or truncated cookie (or one set by a different app on the same
  // domain) doesn't silently identify someone as another user.
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value,
  );
}
