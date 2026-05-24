import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <>
      <div className="border-b border-rule">
        <div className="mx-auto max-w-6xl px-6 py-5 flex items-center justify-between">
          <Skeleton className="h-5 w-24 bg-muted" />
          <Skeleton className="h-3 w-32 bg-muted" />
        </div>
      </div>

      <section className="border-b border-rule">
        <div className="mx-auto max-w-6xl px-6 py-16 md:py-20 space-y-10">
          <Skeleton className="h-3 w-64 bg-muted" />
          <div className="space-y-3">
            <Skeleton className="h-12 md:h-20 w-3/4 bg-muted" />
            <Skeleton className="h-12 md:h-20 w-1/2 bg-muted" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-6 max-w-3xl">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-3 w-24 bg-muted" />
                <Skeleton className="h-4 w-48 bg-muted" />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-12 md:py-16">
        <Skeleton className="h-3 w-48 bg-muted mb-6" />
        <div className="bg-brand-soft border-l-[3px] border-l-brand p-8 md:p-12 space-y-3">
          <Skeleton className="h-5 w-full bg-background" />
          <Skeleton className="h-5 w-full bg-background" />
          <Skeleton className="h-5 w-3/4 bg-background" />
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-12 md:py-16 space-y-4">
        <Skeleton className="h-8 w-64 bg-muted mb-4" />
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="border-t border-rule pt-6 grid grid-cols-12 gap-6"
          >
            <div className="col-span-2 space-y-2">
              <Skeleton className="h-3 w-20 bg-muted" />
              <Skeleton className="h-3 w-24 bg-muted" />
            </div>
            <div className="col-span-10 space-y-2">
              <Skeleton className="h-4 w-full bg-muted" />
              <Skeleton className="h-4 w-2/3 bg-muted" />
            </div>
          </div>
        ))}
      </section>
    </>
  );
}
