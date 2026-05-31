import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Astroturf — Coordinated comment campaigns in federal rulemaking",
  description:
    "Detecting coordinated public comment campaigns in federal rulemaking.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {children}
      </body>
    </html>
  );
}
