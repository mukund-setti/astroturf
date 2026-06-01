import { ConsumerNav } from "@/components/consumer-nav";

interface SiteHeaderProps {
  backHref?: string;
  backLabel?: string;
}

export function SiteHeader(props: SiteHeaderProps) {
  void props;
  return <ConsumerNav />;
}
