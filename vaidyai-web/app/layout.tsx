import "./globals.css";
import { ReactNode } from "react";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body suppressHydrationWarning className="bg-soft-medical min-h-screen text-slate-100">
        {children}
      </body>
    </html>
  );
}
