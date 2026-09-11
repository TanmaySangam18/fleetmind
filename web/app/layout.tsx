import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "FleetMind — Private AI Infrastructure for the Enterprise",
  description:
    "Turn your corporate phone fleet into a private AI compute cluster. No new hardware. No cloud subscriptions. One-time fee.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} h-full`}>
      <body className="min-h-full bg-[#0a0a0a] text-white antialiased font-sans">
        {children}
      </body>
    </html>
  );
}
