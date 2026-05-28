import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ContractAlpha",
  description: "Government contract and hiring signals backtested against market returns.",
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
