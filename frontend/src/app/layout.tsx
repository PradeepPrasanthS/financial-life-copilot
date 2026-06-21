import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Financial Life Copilot | AI-Powered Multi-Agent Wealth Advisor",
  description: "Secure, cloud-native financial planning platform powered by Google ADK, Gemini 2.5, and Model Context Protocol (MCP).",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
