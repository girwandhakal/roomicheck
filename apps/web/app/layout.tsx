import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RoomiCheck",
  description: "Build an explainable co-living preference profile.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
