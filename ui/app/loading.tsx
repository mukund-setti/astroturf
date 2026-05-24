import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <>
      <div className="border-b border-rule">
        <div className="mx-auto max-w-6xl px-6 py-5 flex items-center justify-between">
          <Skeleton className="h-5 w-24 bg-muted" />
          <Skeleton className="h-3 w-40 bg-muted" />
        </div>
      </div>

      <section className="border-b border-rule">
        <div className="mx-auto max-w-6xl px-6 py-20 md:py-28 space-y-6">
          <Skeleton className="h-3 w-56 bg-muted" />
          <div className="space-y-3">
            <Skeleton className="h-14 md:h-20 w-3/4 bg-muted" />
            <Skeleton className="h-14 md:h-20 w-3/5 bg-muted" />
            <Skeleton className="h-14 md:h-20 w-2/3 bg-muted" />
          </div>
          <Skeleton className="h-6 w-1/2 bg-muted" />
          <Skeleton className="h-4 w-1/3 bg-muted" />
        </div>
      </section>

      <section className="border-b border-rule">
        <div className="mx-auto max-w-6xl px-6 py-12 grid grid-cols-2 md:grid-cols-4 gap-8">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="space-y-3">
              <Skeleton className="h-14 md:h-20 w-24 bg-muted" />
              <Skeleton className="h-3 w-32 bg-muted" />
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16 md:py-20 space-y-6">
        <Skeleton className="h-8 w-64 bg-muted" />
        <Skeleton className="h-10 w-full max-w-md bg-muted" />
        <Skeleton className="h-64 w-full bg-muted rounded-sm" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44 w-full bg-muted rounded-sm" />
          ))}
        </div>
      </section>
    </>
  );
}
