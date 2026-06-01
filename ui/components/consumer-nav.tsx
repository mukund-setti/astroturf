import Link from "next/link";
import { UserRequestsBadge } from "@/components/user-requests-badge";

export function ConsumerNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-rule/60 bg-background/85 backdrop-blur-md">
      <div className="mx-auto max-w-3xl px-6 py-3.5 flex items-center justify-between gap-4">
        <Link
          href="/"
          className="group flex items-center gap-2 font-display text-lg tracking-tight text-foreground shrink-0"
        >
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full bg-brand transition-transform duration-200 group-hover:scale-125"
          />
          <span className="group-hover:text-brand transition-colors">
            Astroturf
          </span>
        </Link>
        <nav className="flex items-center gap-4 text-sm text-muted-foreground">
          <Link href="/explore" className="hover:text-brand transition-colors">
            explore
          </Link>
          <Link href="/learn-more" className="hover:text-brand transition-colors">
            learn more
          </Link>
          <Link href="/advanced" className="hover:text-brand transition-colors">
            advanced
          </Link>
          <UserRequestsBadge />
        </nav>
      </div>
    </header>
  );
}
