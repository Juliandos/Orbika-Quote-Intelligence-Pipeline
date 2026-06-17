import { DashboardPayload, QuoteSummary, TaskRecord } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

export async function getDashboard(): Promise<DashboardPayload> {
  const response = await fetch(`${API_BASE}/api/dashboard`, { cache: "no-store" });
  if (!response.ok) throw new Error("No se pudo cargar el dashboard");
  return response.json();
}

export async function getQuotes(): Promise<QuoteSummary[]> {
  const response = await fetch(`${API_BASE}/api/quotes`, { cache: "no-store" });
  if (!response.ok) throw new Error("No se pudo cargar la lista de cotizaciones");
  return response.json();
}

export async function getQuote(quoteKey: string): Promise<any> {
  const response = await fetch(`${API_BASE}/api/quotes/${quoteKey}`, { cache: "no-store" });
  if (!response.ok) throw new Error("No se pudo cargar la cotización");
  return response.json();
}

export async function getTasks(): Promise<TaskRecord[]> {
  const response = await fetch(`${API_BASE}/api/tasks`, { cache: "no-store" });
  if (!response.ok) throw new Error("No se pudo cargar el estado de tareas");
  return response.json();
}

export async function postJson<T>(path: string, payload: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`La acción falló: ${path}`);
  }
  return response.json();
}

export function apiBase() {
  return API_BASE;
}
