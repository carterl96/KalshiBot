import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider, EngineProvider } from "@/lib/store";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "KalshiBot Admin",
  description: "Admin panel for the KalshiBot crypto trading engine",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <EngineProvider>
            <Shell>{children}</Shell>
          </EngineProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
