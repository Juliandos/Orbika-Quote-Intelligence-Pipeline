"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BellRing,
  Bot,
  CarFront,
  ClipboardList,
  Clock3,
  Gauge,
  Layers3,
  Mail,
  PanelRightClose,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
  TriangleAlert,
  Wrench,
  X,
} from "lucide-react";
import { getDashboard, getQuote, getQuotes, getTasks, postJson } from "@/components/api";
import { useEventStream } from "@/components/use-event-stream";
import { DashboardPayload, QuoteSummary, TaskRecord } from "@/components/types";

type TabKey = "overview" | "parts" | "matches" | "agentic";
type OverlayKey = "operations" | "pipeline" | "activity" | null;
type QueueFilter = "all" | "needs_attention" | "with_agentic" | "loaded" | "failed";

const statusTone: Record<string, string> = {
  loaded: "bg-emerald-100 text-emerald-800",
  partial: "bg-amber-100 text-amber-800",
  failed_after_retries: "bg-rose-100 text-rose-800",
};

const statusLabel: Record<string, string> = {
  loaded: "Lista",
  partial: "Parcial",
  failed_after_retries: "Fallida",
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
  const [searchText, setSearchText] = useState("");
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");

  const deferredSearchText = useDeferredValue(searchText);

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
      setLogs((prev) => [`No se pudo cargar la cotizacion: ${String(error)}`, ...prev]),
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
      const subject = payload?.quote?.subject ?? "Nueva cotizacion";
      setLogs((prev) => [`Nueva cotizacion detectada: ${subject}`, ...prev].slice(0, 120));
    },
    onLog: (payload) => {
      const line = payload?.line ?? payload?.message ?? JSON.stringify(payload);
      setLogs((prev) => [String(line), ...prev].slice(0, 120));
    },
  });

  const runningRunner = tasks.find(
    (task) => task.singleton_key === "incremental_runner" && ["starting", "running"].includes(task.status),
  );

  const queueStats = useMemo(() => ({
    all: quotes.length,
    needs_attention: quotes.filter((quote) => quote.load_status !== "loaded").length,
    with_agentic: quotes.filter((quote) => quote.parts_with_agentic_matches > 0).length,
    loaded: quotes.filter((quote) => quote.load_status === "loaded").length,
    failed: quotes.filter((quote) => quote.load_status === "failed_after_retries").length,
  }), [quotes]);

  const filteredQuotes = useMemo(() => {
    const needle = deferredSearchText.trim().toLowerCase();
    return quotes.filter((quote) => {
      const matchesFilter =
        queueFilter === "all" ||
        (queueFilter === "needs_attention" && quote.load_status !== "loaded") ||
        (queueFilter === "with_agentic" && quote.parts_with_agentic_matches > 0) ||
        (queueFilter === "loaded" && quote.load_status === "loaded") ||
        (queueFilter === "failed" && quote.load_status === "failed_after_retries");

      if (!matchesFilter) return false;
      if (!needle) return true;

      const haystack = [quote.subject, quote.aviso_id, quote.placa, quote.marca, quote.linea, quote.quote_key]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return haystack.includes(needle);
    });
  }, [deferredSearchText, queueFilter, quotes]);

  const selectedQuoteSummary = useMemo(() => {
    const matchingSummary = selectedQuote?.supplier_matching?.summary ?? {};
    const agenticSummary = selectedQuote?.agentic_supplier_matching?.summary ?? {};
    const partCount = selectedQuote?.orbika?.parts?.length ?? 0;
    return [
      { label: "Repuestos", value: String(partCount), hint: "extraidos de Orbika", tone: "neutral" as const },
      { label: "Con proveedor", value: String(matchingSummary.parts_with_matches ?? 0), hint: `${matchingSummary.parts_total ?? partCount} revisados`, tone: "good" as const },
      { label: "Con agentic", value: String(agenticSummary.parts_with_agentic_matches ?? 0), hint: `${agenticSummary.parts_reviewed ?? 0} evaluados`, tone: "accent" as const },
      { label: "Estado", value: statusLabel[selectedQuote?.orbika?.load_status ?? ""] ?? (selectedQuote?.orbika?.load_status ?? "n/a"), hint: selectedQuote?.orbika?.aviso_id ? `aviso ${selectedQuote.orbika.aviso_id}` : "sin aviso", tone: selectedQuote?.orbika?.load_status === "loaded" ? ("good" as const) : ("warn" as const) },
    ];
  }, [selectedQuote]);

  const selectedQuoteTimeline = useMemo(() => {
    if (!selectedQuote) return [];
    return [
      { label: "Correo recibido", value: selectedQuote.source?.received_at ?? "n/a" },
      { label: "Ultimo generado", value: selectedQuote.generated_at ?? "n/a" },
      { label: "Aviso", value: selectedQuote.orbika?.aviso_id ?? "n/a" },
      { label: "Modo agentic", value: selectedQuote.agentic_supplier_matching?.review_mode ?? "n/a" },
    ];
  }, [selectedQuote]);

  const priorityNotes = useMemo(() => {
    if (!selectedQuote) return [];
    const summary = selectedQuote?.supplier_matching?.summary ?? {};
    const agenticSummary = selectedQuote?.agentic_supplier_matching?.summary ?? {};
    const notes = [];
    if ((summary.parts_with_matches ?? 0) === 0) notes.push("No hay matches utiles todavia; conviene revisar proveedor o descripcion del repuesto.");
    if ((agenticSummary.parts_with_agentic_matches ?? 0) < (summary.parts_with_matches ?? 0)) notes.push("Hay matches sin seleccion agentic final; puede requerir revision manual rapida.");
    if (selectedQuote?.orbika?.load_status !== "loaded") notes.push("La cotizacion no quedo totalmente cargada; revisar consistencia antes de enviar.");
    return notes;
  }, [selectedQuote]);

  const taskSummary = useMemo(() => ({
    running: tasks.filter((task) => ["starting", "running"].includes(task.status)).length,
    finished: tasks.filter((task) => task.status === "finished").length,
    failed: tasks.filter((task) => task.status === "failed").length,
  }), [tasks]);

  const runAction = async (path: string, payload: Record<string, unknown> = {}) => {
    try {
      setIsBusy(true);
      await postJson(path, payload);
      await refreshAll();
    } catch (error) {
      setLogs((prev) => [`Error ejecutando accion: ${String(error)}`, ...prev]);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <main className="min-h-screen px-4 py-6 md:px-8 xl:h-screen xl:overflow-hidden">
      <div className="mx-auto flex max-w-[1880px] flex-wrap items-center justify-between gap-4 pb-4">
        <div>
          <p className="text-xs uppercase tracking-[0.28em] text-olive">Orbika Console</p>
          <h1 className="mt-1 text-3xl font-semibold text-pine">Vista operativa de cotizaciones</h1>
          <p className="mt-2 max-w-2xl text-sm text-ink/65">
            Cola priorizada para revisar correos, validar repuestos y decidir rapido que cotizacion esta lista, parcial o necesita apoyo manual.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="rounded-full border border-clay bg-white px-3 py-2 text-sm text-ink transition hover:border-olive"
            onClick={() => refreshAll()}
            title="Actualizar tablero"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <TopDockButton icon={<Mail className="h-4 w-4" />} label="Operacion" active={activeOverlay === "operations"} onClick={() => setActiveOverlay((current) => (current === "operations" ? null : "operations"))} />
          <TopDockButton icon={<Gauge className="h-4 w-4" />} label="Pipeline" active={activeOverlay === "pipeline"} onClick={() => setActiveOverlay((current) => (current === "pipeline" ? null : "pipeline"))} />
          <TopDockButton icon={<PanelRightClose className="h-4 w-4" />} label="Actividad" active={activeOverlay === "activity"} onClick={() => setActiveOverlay((current) => (current === "activity" ? null : "activity"))} />
        </div>
      </div>

      <div className="mx-auto grid max-w-[1880px] gap-6 xl:h-[calc(100vh-9rem)] xl:grid-cols-[430px_minmax(0,1fr)] xl:overflow-hidden">
        <aside className="flex min-h-0 flex-col gap-4">
          <section className="rounded-[2rem] bg-white/80 p-4 shadow-panel backdrop-blur">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-2">
              <MetricCard icon={<Gauge className="h-5 w-5" />} label="Cotizaciones" value={dashboard?.counts.quotes_total ?? 0} compact />
              <MetricCard icon={<Play className="h-5 w-5" />} label="Listas" value={dashboard?.counts.loaded_quotes ?? 0} compact />
              <MetricCard icon={<Wrench className="h-5 w-5" />} label="Parciales" value={dashboard?.counts.partial_quotes ?? 0} compact />
              <MetricCard icon={<BellRing className="h-5 w-5" />} label="Fallidas" value={dashboard?.counts.failed_quotes ?? 0} compact />
            </div>
          </section>

          <section className="flex min-h-0 flex-1 flex-col rounded-[2rem] bg-white/85 p-5 shadow-panel backdrop-blur">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.25em] text-olive">Cola de trabajo</p>
                <p className="mt-1 text-sm text-ink/60">Marcadas: {selectedQuoteKeys.length} · visibles: {filteredQuotes.length}</p>
              </div>
              <span className="rounded-full bg-sand px-3 py-1 text-xs text-ink/70">{quotes.length} totales</span>
            </div>
            <div className="mt-4 rounded-2xl border border-clay bg-mist/60 p-3">
              <div className="flex items-center gap-2 rounded-xl border border-clay bg-white px-3 py-2">
                <Search className="h-4 w-4 text-olive" />
                <input
                  value={searchText}
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder="Buscar por placa, aviso, marca o asunto"
                  className="w-full bg-transparent text-sm outline-none placeholder:text-ink/40"
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <FilterChip active={queueFilter === "all"} label={`Todo (${queueStats.all})`} onClick={() => setQueueFilter("all")} />
                <FilterChip active={queueFilter === "needs_attention"} label={`Atencion (${queueStats.needs_attention})`} onClick={() => setQueueFilter("needs_attention")} />
                <FilterChip active={queueFilter === "with_agentic"} label={`Agentic (${queueStats.with_agentic})`} onClick={() => setQueueFilter("with_agentic")} />
                <FilterChip active={queueFilter === "failed"} label={`Fallidas (${queueStats.failed})`} onClick={() => setQueueFilter("failed")} />
              </div>
            </div>

            <div className="mt-4 space-y-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
              {filteredQuotes.map((quote) => {
                const selected = selectedQuoteKey === quote.quote_key;
                const needsAttention = quote.load_status !== "loaded";
                return (
                  <div
                    key={quote.quote_key}
                    className={`rounded-3xl border p-4 transition ${selected ? "border-pine bg-pine text-white shadow-lg" : "border-clay bg-white hover:border-olive"}`}
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
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="max-h-14 overflow-hidden break-words text-base font-semibold">{quote.subject ?? quote.quote_key}</p>
                              {needsAttention && (
                                <span className={`rounded-full px-2 py-1 text-[11px] ${selected ? "bg-white/20" : "bg-amber-100 text-amber-800"}`}>
                                  revisar
                                </span>
                              )}
                            </div>
                            <p className="mt-2 text-sm opacity-85">{quote.placa ?? "Sin placa"} · aviso {quote.aviso_id ?? "n/a"}</p>
                            <p className="mt-1 text-xs opacity-70">{quote.marca ?? "Marca n/a"} {quote.linea ?? ""}</p>
                            <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                              <MiniBadge selected={selected} icon={<ClipboardList className="h-3 w-3" />}>
                                {quote.parts_with_matches}/{quote.repuestos_count} con match
                              </MiniBadge>
                              <MiniBadge selected={selected} icon={<Sparkles className="h-3 w-3" />}>
                                {quote.parts_with_agentic_matches} agentic
                              </MiniBadge>
                            </div>
                          </div>
                          <span className={`rounded-full px-3 py-1 text-xs ${selected ? "bg-white/20" : statusTone[quote.load_status ?? ""] ?? "bg-slate-100 text-slate-800"}`}>
                            {statusLabel[quote.load_status ?? ""] ?? quote.load_status ?? "n/a"}
                          </span>
                        </div>
                      </button>
                    </div>
                  </div>
                );
              })}
              {filteredQuotes.length === 0 && (
                <EmptyBlock title="No hay cotizaciones con ese filtro" description="Prueba otro texto de busqueda o cambia el filtro de la cola." />
              )}
            </div>
          </section>
        </aside>

        <section className="flex min-h-0 flex-col gap-4">
          {selectedQuote ? (
            <div className="flex min-h-0 flex-1 flex-col rounded-3xl bg-white/80 p-5 shadow-panel backdrop-blur xl:overflow-hidden">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <p className="text-xs uppercase tracking-[0.25em] text-olive">Cotizacion seleccionada</p>
                  <h2 className="mt-1 break-words text-2xl font-semibold text-pine">{selectedQuote.source?.subject ?? selectedQuote.quote_key}</h2>
                  <div className="mt-3 flex flex-wrap gap-2 text-sm text-ink/70">
                    <HeaderChip icon={<CarFront className="h-4 w-4" />} label={`${selectedQuote.orbika?.marca ?? "Marca n/a"} ${selectedQuote.orbika?.linea ?? ""}`} />
                    <HeaderChip icon={<ClipboardList className="h-4 w-4" />} label={`Placa ${selectedQuote.orbika?.placa ?? "n/a"}`} />
                    <HeaderChip icon={<Clock3 className="h-4 w-4" />} label={selectedQuote.source?.received_at ?? "sin fecha"} />
                  </div>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-medium ${statusTone[selectedQuote.orbika?.load_status] ?? "bg-slate-100 text-slate-800"}`}>
                  {statusLabel[selectedQuote.orbika?.load_status] ?? selectedQuote.orbika?.load_status ?? "unknown"}
                </span>
              </div>

              <div className="mt-5 grid gap-3 lg:grid-cols-4">
                {selectedQuoteSummary.map((item) => (
                  <SummaryPill key={item.label} label={item.label} value={item.value} hint={item.hint} tone={item.tone} />
                ))}
              </div>

              {priorityNotes.length > 0 && (
                <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  <div className="flex items-center gap-2 font-medium">
                    <TriangleAlert className="h-4 w-4" />
                    Puntos para revisar antes de cerrar
                  </div>
                  <div className="mt-2 space-y-1">
                    {priorityNotes.map((note) => (
                      <p key={note}>{note}</p>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-6 flex flex-wrap gap-2 border-b border-clay pb-3">
                {[["overview", "Resumen"], ["parts", "Repuestos"], ["matches", "Matches"], ["agentic", "Agentic"]].map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setActiveTab(key as TabKey)}
                    className={`rounded-full px-4 py-2 text-sm ${activeTab === key ? "bg-pine text-white" : "bg-sand text-ink"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {activeTab === "overview" && (
                <div className="mt-6 grid gap-6 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
                  <div className="grid gap-6">
                    <InfoPanel title="Base" rows={[["Aviso", selectedQuote.orbika?.aviso_id], ["Recibido", selectedQuote.source?.received_at], ["Placa", selectedQuote.orbika?.placa], ["URL", selectedQuote.quote_url_masked]]} />
                    <InfoPanel title="Vehiculo" rows={[["Marca", selectedQuote.orbika?.marca], ["Linea", selectedQuote.orbika?.linea], ["Version", selectedQuote.orbika?.version], ["Ano", selectedQuote.orbika?.ano], ["VIN", selectedQuote.orbika?.vin]]} />
                    <InfoPanel title="Taller" rows={[["Nombre", selectedQuote.orbika?.nombre_comercial], ["Entrega", selectedQuote.orbika?.taller_entrega], ["Ciudad", selectedQuote.orbika?.ciudad], ["Direccion", selectedQuote.orbika?.direccion]]} />
                  </div>
                  <div className="grid gap-6">
                    <InfoPanel title="Decision rapida" rows={[["Repuestos", String(selectedQuote?.orbika?.parts?.length ?? 0)], ["Con proveedor", String(selectedQuote?.supplier_matching?.summary?.parts_with_matches ?? 0)], ["Con agentic", String(selectedQuote?.agentic_supplier_matching?.summary?.parts_with_agentic_matches ?? 0)], ["Estado", statusLabel[selectedQuote?.orbika?.load_status ?? ""] ?? selectedQuote?.orbika?.load_status]]} />
                    <TimelinePanel items={selectedQuoteTimeline} />
                    <ProviderPulse providerHits={dashboard?.provider_hits ?? {}} />
                  </div>
                </div>
              )}

              {activeTab === "parts" && (
                <div className="mt-6 grid gap-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
                  {selectedQuote.orbika?.parts?.map((part: any, index: number) => (
                    <div key={`${part.name}-${index}`} className="rounded-2xl border border-clay bg-white p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <p className="font-medium">{part.name}</p>
                          <div className="mt-2 flex flex-wrap gap-2 text-xs">
                            <MiniInfo label="Cantidad" value={part.quantity ?? "n/a"} />
                            <MiniInfo label="Referencia" value={part.reference ?? "n/a"} />
                            <MiniInfo label="Calidad" value={part.quality ?? "n/a"} />
                            <MiniInfo label="Entrega" value={part.delivery_days ?? "n/a"} />
                          </div>
                          {(part.total_value || part.unit_gross_price || part.observation_visible) && (
                            <p className="mt-3 text-sm text-ink/65">
                              Total: {part.total_value ?? "n/a"} · Unitario: {part.unit_gross_price ?? "n/a"}
                              {part.observation_visible ? ` · Obs: ${part.observation_visible}` : ""}
                            </p>
                          )}
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
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-medium">{part.part_name}</p>
                          <p className="text-sm text-ink/60">Mejor score: {part.best_score_percent ?? 0}% · {part.best_provider_id ?? "sin proveedor"}</p>
                        </div>
                        <span className="rounded-full bg-mist px-3 py-1 text-xs text-ink/70">{part.matches?.length ?? 0} opcion(es)</span>
                      </div>
                      <div className="grid gap-3">
                        {part.matches?.length ? (
                          part.matches.map((match: any, index: number) => (
                            <div key={`${part.part_name}-${match.provider_id}-${index}`} className="rounded-xl bg-mist/80 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0 flex-1">
                                  <p className="font-medium">{match.product_name}</p>
                                  <p className="text-sm text-ink/60">{match.provider_name} · {match.match_type} · {match.score_percent}%</p>
                                  {match.reference && <p className="mt-1 text-xs text-ink/55">Ref: {match.reference}</p>}
                                </div>
                                <a className="text-sm text-pine underline" href={match.detail_url} target="_blank" rel="noreferrer">Ver</a>
                              </div>
                            </div>
                          ))
                        ) : (
                          <EmptyBlock title="Sin matches" description="Este repuesto todavia no tiene candidatos de proveedor." compact />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === "agentic" && (
                <div className="mt-6 space-y-4 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
                  {selectedQuote.agentic_supplier_matching?.parts?.map((part: any) => (
                    <div key={part.part_name} className="rounded-2xl border border-clay bg-white p-4">
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-medium">{part.part_name}</p>
                          <p className="text-sm text-ink/60">Top proveedor: {part.top_provider_id ?? "n/a"} · Score: {part.top_score_percent ?? 0}%</p>
                        </div>
                        <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs text-emerald-800">{part.selected_matches?.length ?? 0} recomendacion(es)</span>
                      </div>
                      <div className="grid gap-3">
                        {part.selected_matches?.length ? (
                          part.selected_matches.map((match: any) => (
                            <div key={`${part.part_name}-${match.rank}-${match.provider_id}`} className="rounded-xl bg-mist/80 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0 flex-1">
                                  <p className="font-medium">#{match.rank} · {match.product_name}</p>
                                  <p className="text-sm text-ink/60">{match.provider_name} · {match.match_type} · {match.score_percent}%</p>
                                  <p className="mt-2 rounded-xl bg-white px-3 py-2 text-sm text-olive">{match.agentic_comment || "Sin comentario adicional."}</p>
                                </div>
                                <a className="text-sm text-pine underline" href={match.detail_url} target="_blank" rel="noreferrer">Ver</a>
                              </div>
                            </div>
                          ))
                        ) : (
                          <EmptyBlock title="Sin seleccion agentic" description="Esta pieza todavia no tiene recomendacion final del revisor agentic." compact />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-3xl bg-white/80 p-10 text-center shadow-panel">Selecciona una cotizacion para verla.</div>
          )}
        </section>
      </div>

      <OverlayPanel open={activeOverlay === "operations"} title="Operacion funcional" subtitle="Acciones para mantener la cola al dia y lanzar reprocesos sin salir del tablero." onClose={() => setActiveOverlay(null)}>
        <div className="grid gap-3">
          <ActionButton icon={<Mail className="h-4 w-4" />} title={runningRunner ? "Runner activo" : "Esperar correos"} description={runningRunner ? "El pipeline esta escuchando nuevos correos." : "Inicia el runner incremental en modo espera."} onClick={() => runAction("/api/tasks/incremental-runner/start", { poll_seconds: 300, max_results: 50 })} disabled={Boolean(runningRunner) || isBusy} tone={runningRunner ? "success" : "default"} />
          <ActionButton icon={<Square className="h-4 w-4" />} title="Detener runner" description="Finaliza el proceso de espera actual." onClick={() => runningRunner && runAction(`/api/tasks/${runningRunner.id}/stop`)} disabled={!runningRunner || isBusy} />
          <ActionButton icon={<Wrench className="h-4 w-4" />} title="Recalcular matching" description="Reprocesa supplier matching para todas las cotizaciones." onClick={() => runAction("/api/tasks/supplier-matching/run", { limit_per_part: 5 })} disabled={isBusy} />
          <ActionButton icon={<Layers3 className="h-4 w-4" />} title="Matching seleccion" description="Ejecuta supplier matching solo sobre las cotizaciones marcadas." onClick={() => runAction("/api/tasks/supplier-matching/run", { limit_per_part: 5, quote_keys: selectedQuoteKeys })} disabled={isBusy || selectedQuoteKeys.length === 0} />
          <ActionButton icon={<Bot className="h-4 w-4" />} title="Agentic review" description="Ejecuta revision agentic sobre todas las cotizaciones." onClick={() => runAction("/api/tasks/agentic-review/run", { limit_per_part: 5, disable_traces: false })} disabled={isBusy} />
          <ActionButton icon={<Sparkles className="h-4 w-4" />} title="Agentic seleccion" description="Ejecuta revision agentic solo sobre las cotizaciones marcadas." onClick={() => runAction("/api/tasks/agentic-review/run", { limit_per_part: 5, disable_traces: false, quote_keys: selectedQuoteKeys })} disabled={isBusy || selectedQuoteKeys.length === 0} />
        </div>
      </OverlayPanel>

      <OverlayPanel open={activeOverlay === "pipeline"} title="Estado del pipeline" subtitle="Resumen operativo del runner, el ultimo ciclo y la presion actual sobre la cola." onClose={() => setActiveOverlay(null)}>
        <div className="grid gap-5">
          <section className="grid gap-2 text-sm">
            <StateRow label="Runner" value={runningRunner ? "Esperando correos" : "Detenido"} />
            <StateRow label="Etapa actual" value={String(dashboard?.current?.stage ?? "idle")} />
            <StateRow label="Ultima corrida" value={String(dashboard?.last_run?.finished_at ?? "n/a")} />
            <StateRow label="Ultima cotizacion" value={String(dashboard?.latest_quote_at ?? "n/a")} />
          </section>

          <section className="rounded-2xl border border-clay bg-mist/70 p-4">
            <p className="text-sm font-semibold text-pine">Presion de la cola</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <StateBadge label="Atencion" value={String(queueStats.needs_attention)} tone="warn" />
              <StateBadge label="Con agentic" value={String(queueStats.with_agentic)} tone="accent" />
              <StateBadge label="Tareas corriendo" value={String(taskSummary.running)} tone="good" />
              <StateBadge label="Tareas fallidas" value={String(taskSummary.failed)} tone="danger" />
            </div>
          </section>

          <ProviderPulse providerHits={dashboard?.provider_hits ?? {}} />
        </div>
      </OverlayPanel>

      <OverlayPanel open={activeOverlay === "activity"} title="Actividad" subtitle="Registro en vivo de tareas, SSE y eventos del pipeline." onClose={() => setActiveOverlay(null)} wide>
        <div className="grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(280px,0.55fr)]">
          <div className="h-[55vh] overflow-y-auto rounded-2xl bg-ink p-3 text-xs text-mist">
            {logs.length ? (
              logs.map((line, index) => (
                <pre key={`${line}-${index}`} className="whitespace-pre-wrap font-mono">{line}</pre>
              ))
            ) : (
              <p className="text-mist/70">Aun no hay actividad registrada.</p>
            )}
          </div>
          <div className="space-y-3">
            <p className="text-sm font-semibold text-pine">Tareas recientes</p>
            {tasks.slice(0, 8).map((task) => (
              <div key={task.id} className="rounded-2xl border border-clay bg-white p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-ink">{task.kind}</p>
                  <span className="rounded-full bg-sand px-2 py-1 text-xs text-ink/70">{task.status}</span>
                </div>
                <p className="mt-1 text-xs text-ink/55">{task.id}</p>
              </div>
            ))}
          </div>
        </div>
      </OverlayPanel>
    </main>
  );
}

function MetricCard({ icon, label, value, compact }: { icon: ReactNode; label: string; value: number; compact?: boolean }) {
  return (
    <div className={`rounded-3xl bg-white/80 shadow-panel backdrop-blur ${compact ? "p-4" : "p-5"}`}>
      <div className="flex items-center justify-between text-olive">{icon}<span className="text-xs uppercase tracking-[0.25em]">{label}</span></div>
      <p className={`font-semibold text-pine ${compact ? "mt-3 text-2xl" : "mt-4 text-3xl"}`}>{value}</p>
    </div>
  );
}

function SummaryPill({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: "neutral" | "good" | "accent" | "warn" }) {
  const toneClass = tone === "good" ? "bg-emerald-50 text-emerald-900" : tone === "accent" ? "bg-sky-50 text-sky-900" : tone === "warn" ? "bg-amber-50 text-amber-900" : "bg-sand text-ink";
  return (
    <div className={`rounded-2xl px-4 py-3 ${toneClass}`}>
      <p className="text-xs uppercase tracking-[0.22em] opacity-70">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
      <p className="mt-1 text-xs opacity-70">{hint}</p>
    </div>
  );
}

function ActionButton({ icon, title, description, onClick, disabled, tone = "default" }: { icon: ReactNode; title: string; description: string; onClick: () => void; disabled?: boolean; tone?: "default" | "success" }) {
  const toneClass = tone === "success" ? "border-emerald-300 bg-emerald-50" : "border-clay bg-sand";
  return (
    <button disabled={disabled} onClick={onClick} className={`rounded-2xl border p-4 text-left transition hover:border-olive disabled:cursor-not-allowed disabled:opacity-50 ${toneClass}`}>
      <div className="flex items-center gap-3 text-pine">{icon}<p className="font-medium">{title}</p></div>
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
  return <div className="flex items-center justify-between gap-3 rounded-xl bg-sand px-3 py-2"><span className="text-ink/60">{label}</span><span className="text-right font-medium">{value}</span></div>;
}

function TopDockButton({ icon, label, active, onClick }: { icon: ReactNode; label: string; active?: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm transition ${active ? "border-pine bg-pine text-white" : "border-clay bg-white text-ink hover:border-olive"}`}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function OverlayPanel({ open, title, subtitle, onClose, children, wide }: { open: boolean; title: string; subtitle: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-end bg-ink/20 p-4 backdrop-blur-sm">
      <div className={`mt-20 w-full overflow-hidden rounded-[2rem] border border-clay bg-white shadow-2xl ${wide ? "max-w-4xl" : "max-w-xl"}`}>
        <div className="flex items-start justify-between gap-4 border-b border-clay px-6 py-5">
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-olive">{title}</p>
            <p className="mt-2 text-sm text-ink/70">{subtitle}</p>
          </div>
          <button onClick={onClose} className="rounded-full border border-clay bg-white p-2 text-ink transition hover:border-olive"><X className="h-4 w-4" /></button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-6">{children}</div>
      </div>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3 py-2 text-xs transition ${active ? "bg-pine text-white" : "bg-white text-ink/75 hover:bg-sand"}`}
    >
      {label}
    </button>
  );
}

function HeaderChip({ icon, label }: { icon?: ReactNode; label: string }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-clay bg-white px-3 py-2 text-xs text-ink/70">
      {icon}
      <span>{label}</span>
    </div>
  );
}

function MiniBadge({ label, tone = "neutral", selected = false, icon, children }: { label?: string; tone?: "neutral" | "accent" | "good" | "warn"; selected?: boolean; icon?: ReactNode; children?: ReactNode }) {
  const toneClass = selected
    ? "bg-white/12 text-white"
    : tone === "good"
      ? "bg-emerald-50 text-emerald-900"
      : tone === "accent"
        ? "bg-sky-50 text-sky-900"
        : tone === "warn"
          ? "bg-amber-50 text-amber-900"
          : "bg-sand text-ink/70";

  const content = children ?? label ?? "";

  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] ${toneClass}`}>
      {icon}
      <span>{content}</span>
    </span>
  );
}

function MiniInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-sand px-3 py-2 text-xs text-ink/70">
      <p className="uppercase tracking-[0.18em] text-[10px] text-olive">{label}</p>
      <p className="mt-1 text-sm text-pine">{value}</p>
    </div>
  );
}

function TimelinePanel({ items }: { items: { label: string; value: string }[] }) {
  return (
    <section className="rounded-2xl border border-clay bg-white p-4">
      <p className="mb-4 text-sm font-semibold text-pine">Linea de tiempo</p>
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.label} className="flex items-center justify-between gap-3 rounded-xl bg-sand px-3 py-3 text-sm">
            <span className="text-ink/65">{item.label}</span>
            <span className="text-right font-medium text-pine">{item.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ProviderPulse({ providerHits }: { providerHits: Record<string, number> }) {
  const entries = Object.entries(providerHits).sort((a, b) => b[1] - a[1]).slice(0, 6);

  return (
    <section className="rounded-2xl border border-clay bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-pine">Pulso por proveedor</p>
        <MiniBadge label={`${entries.length} visibles`} tone="accent" />
      </div>
      <div className="mt-4 space-y-3">
        {entries.length ? (
          entries.map(([provider, count]) => (
            <div key={provider} className="space-y-1">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="text-ink/75">{provider}</span>
                <span className="font-medium text-pine">{count}</span>
              </div>
              <div className="h-2 rounded-full bg-sand">
                <div
                  className="h-2 rounded-full bg-olive"
                  style={{ width: `${Math.max(12, Math.min(100, count * 2))}%` }}
                />
              </div>
            </div>
          ))
        ) : (
          <p className="text-sm text-ink/60">Aun no hay hits agregados.</p>
        )}
      </div>
    </section>
  );
}

function StateBadge({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "warn" | "danger" | "accent" }) {
  const toneClass = tone === "good"
    ? "bg-emerald-50 text-emerald-900"
    : tone === "warn"
      ? "bg-amber-50 text-amber-900"
      : tone === "danger"
        ? "bg-rose-50 text-rose-900"
        : tone === "accent"
          ? "bg-sky-50 text-sky-900"
          : "bg-sand text-ink";

  return (
    <div className={`rounded-2xl px-4 py-3 ${toneClass}`}>
      <p className="text-xs uppercase tracking-[0.22em] opacity-70">{label}</p>
      <p className="mt-2 text-xl font-semibold">{value}</p>
    </div>
  );
}

function EmptyBlock({ title, description, compact = false }: { title: string; description: string; compact?: boolean }) {
  return (
    <section className={`rounded-2xl border border-dashed border-clay bg-white/70 text-center ${compact ? "p-5" : "p-8"}`}>
      <p className="text-base font-semibold text-pine">{title}</p>
      <p className="mt-2 text-sm text-ink/60">{description}</p>
    </section>
  );
}






