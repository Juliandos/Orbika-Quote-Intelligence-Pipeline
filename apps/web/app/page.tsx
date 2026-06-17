"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BellRing,
  Bot,
  Gauge,
  Mail,
  PanelRightClose,
  Play,
  RefreshCw,
  Square,
  Wrench,
  X,
} from "lucide-react";
import { getDashboard, getQuote, getQuotes, getTasks, postJson } from "@/components/api";
import { useEventStream } from "@/components/use-event-stream";
import { DashboardPayload, QuoteSummary, TaskRecord } from "@/components/types";

type TabKey = "overview" | "parts" | "matches" | "agentic";
type OverlayKey = "operations" | "pipeline" | "activity" | null;

const statusTone: Record<string, string> = {
  loaded: "bg-emerald-100 text-emerald-800",
  partial: "bg-amber-100 text-amber-800",
  failed_after_retries: "bg-rose-100 text-rose-800",
};

export default function Page() {
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null);
  const [quotes, setQuotes] = useState<QuoteSummary[]>([]);
  const [selectedQuoteKey, setSelectedQuoteKey] = useState<string | null>(null);
  const [selectedQuote, setSelectedQuote] = useState<any | null>(null);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [activeOverlay, setActiveOverlay] = useState<OverlayKey>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [selectedQuoteKeys, setSelectedQuoteKeys] = useState<string[]>([]);

  const refreshAll = async () => {
    const [dashboardPayload, quotesPayload, tasksPayload] = await Promise.all([
      getDashboard(),
      getQuotes(),
      getTasks(),
    ]);
    setDashboard(dashboardPayload);
    setQuotes(quotesPayload);
    setTasks(tasksPayload);
    if (!selectedQuoteKey && quotesPayload[0]?.quote_key) {
      setSelectedQuoteKey(quotesPayload[0].quote_key);
    }
  };

  const loadQuote = async (quoteKey: string) => {
    setSelectedQuoteKey(quoteKey);
    const payload = await getQuote(quoteKey);
    setSelectedQuote(payload);
  };

  const toggleQuoteSelection = (quoteKey: string) => {
    setSelectedQuoteKeys((current) =>
      current.includes(quoteKey) ? current.filter((item) => item !== quoteKey) : [...current, quoteKey],
    );
  };

  useEffect(() => {
    refreshAll().catch((error) => setLogs((prev) => [`Error inicial: ${String(error)}`, ...prev]));
  }, []);

  useEffect(() => {
    if (!selectedQuoteKey) return;
    loadQuote(selectedQuoteKey).catch((error) =>
      setLogs((prev) => [`No se pudo cargar la cotización: ${String(error)}`, ...prev]),
    );
  }, [selectedQuoteKey]);

  useEventStream({
    onDashboard: () => {
      refreshAll().catch(() => {});
      if (selectedQuoteKey) {
        loadQuote(selectedQuoteKey).catch(() => {});
      }
    },
    onTasks: () => {
      getTasks().then(setTasks).catch(() => {});
    },
    onQuoteNew: (payload) => {
      const subject = payload?.quote?.subject ?? "Nueva cotización";
      setLogs((prev) => [`Nueva cotización detectada: ${subject}`, ...prev].slice(0, 120));
    },
    onLog: (payload) => {
      const line = payload?.line ?? payload?.message ?? JSON.stringify(payload);
      setLogs((prev) => [String(line), ...prev].slice(0, 120));
    },
  });

  const runningRunner = tasks.find(
    (task) => task.singleton_key === "incremental_runner" && ["starting", "running"].includes(task.status),
  );

  const matchingSummary = useMemo(() => {
    const summary = selectedQuote?.supplier_matching?.summary ?? {};
    return [
      { label: "Repuestos", value: summary.parts_total ?? 0 },
      { label: "Con match", value: summary.parts_with_matches ?? 0 },
      { label: "Exactos", value: summary.exact_reference_matches ?? 0 },
    ];
  }, [selectedQuote]);

  const runAction = async (path: string, payload: Record<string, unknown> = {}) => {
    try {
      setIsBusy(true);
      await postJson(path, payload);
      await refreshAll();
    } catch (error) {
      setLogs((prev) => [`Error ejecutando acción: ${String(error)}`, ...prev]);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <main className="min-h-screen px-4 py-6 md:px-8 xl:h-screen xl:overflow-hidden">
      <div className="mx-auto flex max-w-[1880px] items-center justify-between gap-4 pb-4">
        <div>
          <p className="text-xs uppercase tracking-[0.28em] text-olive">Orbika Console</p>
          <h1 className="mt-1 text-3xl font-semibold text-pine">Vista operativa de cotizaciones</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="rounded-full border border-clay bg-white px-3 py-2 text-sm text-ink transition hover:border-olive"
            onClick={() => refreshAll()}
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <TopDockButton
            icon={<Mail className="h-4 w-4" />}
            label="Operación"
            active={activeOverlay === "operations"}
            onClick={() => setActiveOverlay((current) => (current === "operations" ? null : "operations"))}
          />
          <TopDockButton
            icon={<Gauge className="h-4 w-4" />}
            label="Pipeline"
            active={activeOverlay === "pipeline"}
            onClick={() => setActiveOverlay((current) => (current === "pipeline" ? null : "pipeline"))}
          />
          <TopDockButton
            icon={<PanelRightClose className="h-4 w-4" />}
            label="Actividad"
            active={activeOverlay === "activity"}
            onClick={() => setActiveOverlay((current) => (current === "activity" ? null : "activity"))}
          />
        </div>
      </div>

      <div className="mx-auto grid max-w-[1880px] gap-6 xl:h-[calc(100vh-9rem)] xl:grid-cols-[420px_minmax(0,1fr)] xl:overflow-hidden">
        <aside className="flex min-h-0 flex-col gap-4">
          <section className="rounded-3xl bg-white/80 p-4 shadow-panel backdrop-blur">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
              <MetricCard icon={<Gauge className="h-5 w-5" />} label="Cotizaciones" value={dashboard?.counts.quotes_total ?? 0} compact />
              <MetricCard icon={<Play className="h-5 w-5" />} label="Loaded" value={dashboard?.counts.loaded_quotes ?? 0} compact />
              <MetricCard icon={<Wrench className="h-5 w-5" />} label="Partial" value={dashboard?.counts.partial_quotes ?? 0} compact />
              <MetricCard icon={<BellRing className="h-5 w-5" />} label="Failed" value={dashboard?.counts.failed_quotes ?? 0} compact />
            </div>
          </section>

          <section className="flex min-h-0 flex-1 flex-col rounded-[2rem] bg-white/85 p-5 shadow-panel backdrop-blur">
            <p className="text-xs uppercase tracking-[0.25em] text-olive">Cotizaciones</p>
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-sm text-ink/60">Marcadas: {selectedQuoteKeys.length}</p>
              <p className="text-sm text-ink/60">{quotes.length} totales</p>
            </div>
            <div className="mt-4 space-y-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
              {quotes.map((quote) => (
                <div
                  key={quote.quote_key}
                  className={`rounded-3xl border p-4 transition ${
                    selectedQuoteKey === quote.quote_key
                      ? "border-pine bg-pine text-white shadow-lg"
                      : "border-clay bg-white hover:border-olive"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={selectedQuoteKeys.includes(quote.quote_key)}
                      onChange={() => toggleQuoteSelection(quote.quote_key)}
                      className="mt-1 h-4 w-4 rounded border-clay"
                    />
                    <button className="min-w-0 flex-1 text-left" onClick={() => setSelectedQuoteKey(quote.quote_key)}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="max-h-12 overflow-hidden break-words text-base font-semibold">
                            {quote.subject ?? quote.quote_key}
                          </p>
                          <p className="mt-2 text-sm opacity-80">
                            {quote.placa ?? "Sin placa"} · aviso {quote.aviso_id ?? "n/a"}
                          </p>
                          <p className="mt-1 text-xs opacity-70">
                            {quote.marca ?? "Marca n/a"} {quote.linea ?? ""}
                          </p>
                        </div>
                        <span className="rounded-full bg-white/20 px-3 py-1 text-xs">
                          {quote.parts_with_matches}/{quote.repuestos_count}
                        </span>
                      </div>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </aside>

        <section className="flex min-h-0 flex-col gap-4">
          {selectedQuote ? (
            <div className="flex min-h-0 flex-1 flex-col rounded-3xl bg-white/80 p-5 shadow-panel backdrop-blur xl:overflow-hidden">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <p className="text-xs uppercase tracking-[0.25em] text-olive">Cotización seleccionada</p>
                  <h2 className="mt-1 break-words text-2xl font-semibold text-pine">
                    {selectedQuote.source?.subject ?? selectedQuote.quote_key}
                  </h2>
                  <p className="mt-2 text-sm text-ink/70">
                    {selectedQuote.orbika?.placa ?? "Sin placa"} · {selectedQuote.orbika?.marca ?? "Marca n/a"} {selectedQuote.orbika?.linea ?? ""}
                  </p>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-medium ${statusTone[selectedQuote.orbika?.load_status] ?? "bg-slate-100 text-slate-800"}`}>
                  {selectedQuote.orbika?.load_status ?? "unknown"}
                </span>
              </div>

              <div className="mt-6 flex gap-2 border-b border-clay pb-3">
                {[
                  ["overview", "Resumen"],
                  ["parts", "Repuestos"],
                  ["matches", "Matches"],
                  ["agentic", "Agentic"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setActiveTab(key as TabKey)}
                    className={`rounded-full px-4 py-2 text-sm ${
                      activeTab === key ? "bg-pine text-white" : "bg-sand text-ink"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {activeTab === "overview" && (
                <div className="mt-6 grid gap-6 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1 lg:grid-cols-2">
                  <InfoPanel
                    title="Base"
                    rows={[
                      ["Aviso", selectedQuote.orbika?.aviso_id],
                      ["Recibido", selectedQuote.source?.received_at],
                      ["Placa", selectedQuote.orbika?.placa],
                      ["URL", selectedQuote.quote_url_masked],
                    ]}
                  />
                  <InfoPanel
                    title="Vehículo"
                    rows={[
                      ["Marca", selectedQuote.orbika?.marca],
                      ["Línea", selectedQuote.orbika?.linea],
                      ["Versión", selectedQuote.orbika?.version],
                      ["Año", selectedQuote.orbika?.ano],
                      ["VIN", selectedQuote.orbika?.vin],
                    ]}
                  />
                  <InfoPanel
                    title="Taller"
                    rows={[
                      ["Nombre", selectedQuote.orbika?.nombre_comercial],
                      ["Entrega", selectedQuote.orbika?.taller_entrega],
                      ["Ciudad", selectedQuote.orbika?.ciudad],
                      ["Dirección", selectedQuote.orbika?.direccion],
                    ]}
                  />
                  <InfoPanel
                    title="Matching"
                    rows={matchingSummary.map((item) => [item.label, String(item.value)])}
                  />
                </div>
              )}

              {activeTab === "parts" && (
                <div className="mt-6 grid gap-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
                  {selectedQuote.orbika?.parts?.map((part: any, index: number) => (
                    <div key={`${part.name}-${index}`} className="rounded-2xl border border-clay bg-white p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="font-medium">{part.name}</p>
                          <p className="text-sm text-ink/60">
                            Cantidad: {part.quantity ?? "n/a"} · Total: {part.total_value ?? "n/a"}
                          </p>
                        </div>
                        <span className="rounded-full bg-sand px-2 py-1 text-xs">{part.raw_status ?? "n/a"}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === "matches" && (
                <div className="mt-6 space-y-4 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
                  {selectedQuote.supplier_matching?.parts?.map((part: any) => (
                    <div key={part.part_name} className="rounded-2xl border border-clay bg-white p-4">
                      <div className="mb-3 flex items-center justify-between">
                        <div>
                          <p className="font-medium">{part.part_name}</p>
                          <p className="text-sm text-ink/60">
                            Mejor score: {part.best_score_percent ?? 0}% · {part.best_provider_id ?? "sin proveedor"}
                          </p>
                        </div>
                      </div>
                      <div className="grid gap-3">
                        {part.matches?.map((match: any, index: number) => (
                          <div key={`${part.part_name}-${match.provider_id}-${index}`} className="rounded-xl bg-mist/80 p-3">
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="font-medium">{match.product_name}</p>
                                <p className="text-sm text-ink/60">
                                  {match.provider_name} · {match.match_type} · {match.score_percent}%
                                </p>
                              </div>
                              <a className="text-sm text-pine underline" href={match.detail_url} target="_blank" rel="noreferrer">
                                Ver
                              </a>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === "agentic" && (
                <div className="mt-6 space-y-4 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
                  {selectedQuote.agentic_supplier_matching?.parts?.map((part: any) => (
                    <div key={part.part_name} className="rounded-2xl border border-clay bg-white p-4">
                      <div className="mb-3">
                        <p className="font-medium">{part.part_name}</p>
                        <p className="text-sm text-ink/60">
                          Top proveedor: {part.top_provider_id ?? "n/a"} · Score: {part.top_score_percent ?? 0}%
                        </p>
                      </div>
                      <div className="grid gap-3">
                        {part.selected_matches?.map((match: any) => (
                          <div key={`${part.part_name}-${match.rank}-${match.provider_id}`} className="rounded-xl bg-mist/80 p-3">
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="font-medium">#{match.rank} · {match.product_name}</p>
                                <p className="text-sm text-ink/60">
                                  {match.provider_name} · {match.match_type} · {match.score_percent}%
                                </p>
                                <p className="mt-1 text-sm text-olive">{match.agentic_comment}</p>
                              </div>
                              <a className="text-sm text-pine underline" href={match.detail_url} target="_blank" rel="noreferrer">
                                Ver
                              </a>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-3xl bg-white/80 p-10 text-center shadow-panel">Selecciona una cotización para verla.</div>
          )}
        </section>
      </div>

      <OverlayPanel
        open={activeOverlay === "operations"}
        title="Operación funcional"
        subtitle="Acciones de ejecución para el pipeline y reprocesos."
        onClose={() => setActiveOverlay(null)}
      >
        <div className="grid gap-3">
          <ActionButton
            icon={<Mail className="h-4 w-4" />}
            title={runningRunner ? "Runner activo" : "Esperar correos"}
            description={runningRunner ? "El pipeline está escuchando nuevos correos." : "Inicia el runner incremental en modo espera."}
            onClick={() => runAction("/api/tasks/incremental-runner/start", { poll_seconds: 300, max_results: 50 })}
            disabled={Boolean(runningRunner) || isBusy}
          />
          <ActionButton
            icon={<Square className="h-4 w-4" />}
            title="Detener runner"
            description="Finaliza el proceso de espera actual."
            onClick={() => runningRunner && runAction(`/api/tasks/${runningRunner.id}/stop`)}
            disabled={!runningRunner || isBusy}
          />
          <ActionButton
            icon={<Wrench className="h-4 w-4" />}
            title="Recalcular matching"
            description="Reprocesa supplier matching para todas las cotizaciones."
            onClick={() => runAction("/api/tasks/supplier-matching/run", { limit_per_part: 5 })}
            disabled={isBusy}
          />
          <ActionButton
            icon={<Wrench className="h-4 w-4" />}
            title="Matching selección"
            description="Ejecuta supplier matching solo sobre las cotizaciones marcadas."
            onClick={() =>
              runAction("/api/tasks/supplier-matching/run", {
                limit_per_part: 5,
                quote_keys: selectedQuoteKeys,
              })
            }
            disabled={isBusy || selectedQuoteKeys.length === 0}
          />
          <ActionButton
            icon={<Bot className="h-4 w-4" />}
            title="Agentic review"
            description="Ejecuta revisión agentic sobre todas las cotizaciones."
            onClick={() => runAction("/api/tasks/agentic-review/run", { limit_per_part: 5, disable_traces: false })}
            disabled={isBusy}
          />
          <ActionButton
            icon={<Bot className="h-4 w-4" />}
            title="Agentic selección"
            description="Ejecuta revisión agentic solo sobre las cotizaciones marcadas."
            onClick={() =>
              runAction("/api/tasks/agentic-review/run", {
                limit_per_part: 5,
                disable_traces: false,
                quote_keys: selectedQuoteKeys,
              })
            }
            disabled={isBusy || selectedQuoteKeys.length === 0}
          />
        </div>
      </OverlayPanel>

      <OverlayPanel
        open={activeOverlay === "pipeline"}
        title="Estado del pipeline"
        subtitle="Resumen rápido del runner y del último ciclo ejecutado."
        onClose={() => setActiveOverlay(null)}
      >
        <div className="space-y-2 text-sm">
          <StateRow label="Runner" value={runningRunner ? "Esperando correos" : "Detenido"} />
          <StateRow label="Etapa actual" value={String(dashboard?.current?.stage ?? "idle")} />
          <StateRow label="Última corrida" value={String(dashboard?.last_run?.finished_at ?? "n/a")} />
        </div>
      </OverlayPanel>

      <OverlayPanel
        open={activeOverlay === "activity"}
        title="Actividad"
        subtitle="Registro en vivo de tareas, SSE y eventos del pipeline."
        onClose={() => setActiveOverlay(null)}
        wide
      >
        <div className="h-[55vh] overflow-y-auto rounded-2xl bg-ink p-3 text-xs text-mist">
          {logs.map((line, index) => (
            <pre key={`${line}-${index}`} className="whitespace-pre-wrap font-mono">
              {line}
            </pre>
          ))}
        </div>
      </OverlayPanel>
    </main>
  );
}

function MetricCard({
  icon,
  label,
  value,
  compact,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  compact?: boolean;
}) {
  return (
    <div className={`rounded-3xl bg-white/80 shadow-panel backdrop-blur ${compact ? "p-4" : "p-5"}`}>
      <div className="flex items-center justify-between text-olive">{icon}<span className="text-xs uppercase tracking-[0.25em]">{label}</span></div>
      <p className={`font-semibold text-pine ${compact ? "mt-3 text-2xl" : "mt-4 text-3xl"}`}>{value}</p>
    </div>
  );
}

function ActionButton({
  icon,
  title,
  description,
  onClick,
  disabled,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className="rounded-2xl border border-clay bg-sand p-4 text-left transition hover:border-olive disabled:cursor-not-allowed disabled:opacity-50"
    >
      <div className="flex items-center gap-3 text-pine">
        {icon}
        <p className="font-medium">{title}</p>
      </div>
      <p className="mt-2 text-sm text-ink/70">{description}</p>
    </button>
  );
}

function InfoPanel({ title, rows }: { title: string; rows: [string, string | undefined | null][] }) {
  return (
    <section className="rounded-2xl border border-clay bg-white p-4">
      <p className="mb-4 text-sm font-semibold text-pine">{title}</p>
      <div className="space-y-3 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
            <span className="text-ink/60">{label}</span>
            <span className="break-words">{value ?? "n/a"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function StateRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-sand px-3 py-2">
      <span className="text-ink/60">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

function TopDockButton({
  icon,
  label,
  active,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm transition ${
        active ? "border-pine bg-pine text-white" : "border-clay bg-white text-ink hover:border-olive"
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function OverlayPanel({
  open,
  title,
  subtitle,
  onClose,
  children,
  wide,
}: {
  open: boolean;
  title: string;
  subtitle: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-end bg-ink/20 p-4 backdrop-blur-sm">
      <div className={`mt-20 w-full overflow-hidden rounded-[2rem] border border-clay bg-white shadow-2xl ${wide ? "max-w-3xl" : "max-w-xl"}`}>
        <div className="flex items-start justify-between gap-4 border-b border-clay px-6 py-5">
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-olive">{title}</p>
            <p className="mt-2 text-sm text-ink/70">{subtitle}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-clay bg-white p-2 text-ink transition hover:border-olive"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-6">{children}</div>
      </div>
    </div>
  );
}
