import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "ACCEDO | Consola Orbika",
  description: "Consola visual de cotizaciones Orbika para ACCEDO.",
  icons: {
    icon: "/accedo-icon.png",
    shortcut: "/accedo-icon.png",
    apple: "/accedo-icon.png",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
