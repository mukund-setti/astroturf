/**
 * Server-side fetch helper for our own API routes. Builds an absolute URL
 * (server components require absolute fetch URLs) and threads Next.js cache
 * options so route responses are reused for an hour after first hit.
 */

export function apiBase(): string {
  if (process.env.VERCEL_URL) {
    return `https://${process.env.VERCEL_URL}`;
  }
  return process.env.NEXT_PUBLIC_BASE_URL ?? "http://localhost:3000";
}

export async function fetchJson<T>(
  path: string,
  revalidateSeconds = 3600,
): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    next: { revalidate: revalidateSeconds },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`GET ${path} failed: ${res.status} ${body}`);
  }
  return (await res.json()) as T;
}
