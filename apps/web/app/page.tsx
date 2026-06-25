"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Image from "next/image";
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
type NoticeTone = "success" | "error" | "info";
type NoticeItem = {
  id: number;
  title: string;
  message: string;
  tone: NoticeTone;
};

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

const compatibilityTone: Record<string, string> = {
  compatible: "good",
  warning: "warn",
  incompatible: "danger",
  insufficient_information: "accent",
};

const compatibilityLabel: Record<string, string> = {
  compatible: "Compatible",
  warning: "Con advertencia",
  incompatible: "Incompatible",
  insufficient_information: "Info insuficiente",
};

const taskKindLabel: Record<string, string> = {
  incremental_runner: "Runner incremental",
  supplier_matching: "Matching de proveedores",
  supplier_matching_selection: "Matching de selección",
  agentic_review: "Revisión IA",
  agentic_review_selection: "Revisión IA de selección",
};

const taskStatusLabel: Record<string, string> = {
  queued: "En cola",
  starting: "Iniciando",
  running: "En ejecución",
  finished: "Finalizada",
  failed: "Fallida",
  stopped: "Detenida",
};

function cleanDisplayText(value: unknown) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/\u00C2/g, "").normalize("NFC");
}

function playUiTone(tone: NoticeTone) {
  try {
    const context = new window.AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const secondOscillator = context.createOscillator();
    const secondGain = context.createGain();

    oscillator.type = "sine";
    secondOscillator.type = "sine";

    if (tone === "success") {
      oscillator.frequency.value = 720;
      secondOscillator.frequency.value = 980;
    } else if (tone === "error") {
      oscillator.frequency.value = 320;
      secondOscillator.frequency.value = 220;
    } else {
      oscillator.frequency.value = 540;
      secondOscillator.frequency.value = 720;
    }

    gain.gain.value = 0.035;
    secondGain.gain.value = 0.03;

    oscillator.connect(gain);
    gain.connect(context.destination);
    secondOscillator.connect(secondGain);
    secondGain.connect(context.destination);

    oscillator.start();
    oscillator.stop(context.currentTime + 0.12);
    secondOscillator.start(context.currentTime + 0.13);
    secondOscillator.stop(context.currentTime + 0.28);
  } catch {
    // El navegador puede bloquear audio hasta que exista interacción del usuario.
  }
}

export default function Page() {
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null);
  const [quotes, setQuotes] = useState<QuoteSummary[]>([]);
  const [selectedQuoteKey, setSelectedQuoteKey] = useState<string | null>(null);
  const [selectedQuote, setSelectedQuote] = useState<any | null>(null);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [notices, setNotices] = useState<NoticeItem[]>([]);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [activeOverlay, setActiveOverlay] = useState<OverlayKey>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [selectedQuoteKeys, setSelectedQuoteKeys] = useState<string[]>([]);
  const [searchText, setSearchText] = useState("");
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");

  const deferredSearchText = useDeferredValue(searchText);

  const pushNotice = (title: string, message: string, tone: NoticeTone = "info") => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    playUiTone(tone);
    setNotices((current) => [{ id, title, message, tone }, ...current].slice(0, 4));
    window.setTimeout(() => {
      setNotices((current) => current.filter((notice) => notice.id !== id));
    }, 4200);
  };

  const refreshAll = async ({ silent = false }: { silent?: boolean } = {}) => {
    const [dashboardPayload, quotesPayload, tasksPayload] = await Promise.all([
      getDashboard(),
      getQuotes(),
      getTasks(),
    ]);
    setDashboard(dashboardPayload);
    setQuotes(quotesPayload);
    setTasks(tasksPayload);
    if (!silent) {
      pushNotice("Tablero actualizado", "La consola recargó cotizaciones, métricas y tareas.", "success");
    }
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
    refreshAll({ silent: true }).catch((error) => setLogs((prev) => [`Error inicial: ${String(error)}`, ...prev]));
  }, []);

  useEffect(() => {
    if (!selectedQuoteKey) return;
    loadQuote(selectedQuoteKey).catch((error) =>
      setLogs((prev) => [`No se pudo cargar la cotización: ${String(error)}`, ...prev]),
    );
  }, [selectedQuoteKey]);

  useEventStream({
    onDashboard: () => {
      refreshAll({ silent: true }).catch(() => {});
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
      pushNotice("Nueva cotización detectada", subject, "success");
    },
    onTaskStarted: (payload) => {
      const kind = payload?.task?.kind ?? "tarea";
      const label = taskKindLabel[kind] ?? kind;
      pushNotice("Tarea iniciada", `${label} comenzó a ejecutarse.`, "info");
    },
    onTaskCompleted: (payload) => {
      const kind = payload?.task?.kind ?? "tarea";
      const label = taskKindLabel[kind] ?? kind;
      pushNotice("Tarea finalizada", `${label} terminó correctamente.`, "success");
    },
    onTaskFailed: (payload) => {
      const kind = payload?.task?.kind ?? "tarea";
      const label = taskKindLabel[kind] ?? kind;
      pushNotice("Tarea fallida", `${label} terminó con error; revisa el panel de actividad.`, "error");
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
      { label: "Repuestos", value: String(partCount), hint: "extraídos de Orbika", tone: "neutral" as const },
      { label: "Con proveedor", value: String(matchingSummary.parts_with_matches ?? 0), hint: `${matchingSummary.parts_total ?? partCount} revisados`, tone: "good" as const },
      { label: "Con revisión IA", value: String(agenticSummary.parts_with_agentic_matches ?? 0), hint: `${agenticSummary.parts_reviewed ?? 0} evaluados`, tone: "accent" as const },
      { label: "Estado", value: statusLabel[selectedQuote?.orbika?.load_status ?? ""] ?? (selectedQuote?.orbika?.load_status ?? "n/d"), hint: selectedQuote?.orbika?.aviso_id ? `aviso ${selectedQuote.orbika.aviso_id}` : "sin aviso", tone: selectedQuote?.orbika?.load_status === "loaded" ? ("good" as const) : ("warn" as const) },
    ];
  }, [selectedQuote]);

  const selectedQuoteTimeline = useMemo(() => {
    if (!selectedQuote) return [];
    return [
      { label: "Correo recibido", value: selectedQuote.source?.received_at ?? "n/d" },
      { label: "Último generado", value: selectedQuote.generated_at ?? "n/d" },
      { label: "Aviso", value: selectedQuote.orbika?.aviso_id ?? "n/d" },
      { label: "Modo IA", value: selectedQuote.agentic_supplier_matching?.review_mode ?? "n/d" },
    ];
  }, [selectedQuote]);

  const priorityNotes = useMemo(() => {
    if (!selectedQuote) return [];
    const summary = selectedQuote?.supplier_matching?.summary ?? {};
    const agenticSummary = selectedQuote?.agentic_supplier_matching?.summary ?? {};
    const notes = [];
    if ((summary.parts_with_matches ?? 0) === 0) notes.push("No hay matches útiles todavía; conviene revisar proveedor o descripción del repuesto.");
    if ((agenticSummary.parts_with_agentic_matches ?? 0) < (summary.parts_with_matches ?? 0)) notes.push("Hay coincidencias sin selección final de revisión IA; puede requerir revisión manual rápida.");
    if (selectedQuote?.orbika?.load_status !== "loaded") notes.push("La cotización no quedó totalmente cargada; revisar consistencia antes de enviar.");
    return notes;
  }, [selectedQuote]);

  const taskSummary = useMemo(() => ({
    running: tasks.filter((task) => ["starting", "running"].includes(task.status)).length,
    finished: tasks.filter((task) => task.status === "finished").length,
    failed: tasks.filter((task) => task.status === "failed").length,
  }), [tasks]);

  const runAction = async (path: string, payload: Record<string, unknown> = {}) => {
    try {
      setLogs((prev) => [`Lanzando acción: ${path}`, ...prev].slice(0, 120));
      setIsBusy(true);
      await postJson(path, payload);
      setLogs((prev) => [`Acción aceptada: ${path}`, ...prev].slice(0, 120));
      pushNotice("Acción enviada", "La solicitud fue aceptada por el backend y quedó registrada.", "success");
      await refreshAll({ silent: true });
    } catch (error) {
      setLogs((prev) => [`Error ejecutando acción: ${String(error)}`, ...prev].slice(0, 120));
      pushNotice("Acción fallida", String(error), "error");
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <main className="min-h-screen px-4 py-6 md:px-8 xl:h-screen xl:overflow-hidden">
      <div className="pointer-events-none fixed left-4 top-4 z-50 flex w-full max-w-sm flex-col gap-3">
        {notices.map((notice) => (
          <div
            key={notice.id}
            className={`pointer-events-auto rounded-2xl border px-4 py-3 shadow-xl backdrop-blur ${
              notice.tone === "success"
                ? "border-emerald-300 bg-emerald-50/95 text-emerald-950"
                : notice.tone === "error"
                  ? "border-rose-300 bg-rose-50/95 text-rose-950"
                  : "border-sky-300 bg-sky-50/95 text-sky-950"
            }`}
          >
            <p className="text-sm font-semibold">{notice.title}</p>
            <p className="mt-1 text-sm opacity-85">{notice.message}</p>
          </div>
        ))}
      </div>
      <div className="mx-auto flex max-w-[1880px] flex-wrap items-center justify-between gap-4 pb-4">
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-[220px] shrink-0 items-center justify-center overflow-hidden rounded-[1.35rem] bg-transparent">
            <Image src="/accedo-logo.png" alt="ACCEDO" width={220} height={140} className="h-full w-full object-cover object-center" priority />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.28em] text-sky-700">ACCEDO · Consola Orbika</p>
            <h1 className="mt-1 text-3xl font-semibold text-pine">Vista operativa de cotizaciones</h1>
            <p className="mt-2 max-w-2xl text-sm text-ink/65">
              Cola priorizada para revisar correos, validar repuestos y decidir rápido qué cotización está lista, parcial o necesita apoyo manual.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="rounded-full border border-clay bg-white px-3 py-2 text-sm text-ink transition hover:border-olive"
            onClick={() => refreshAll({ silent: false })}
            title="Actualizar tablero"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <TopDockButton icon={<Mail className="h-4 w-4" />} label="Operación" active={activeOverlay === "operations"} onClick={() => { setActiveOverlay((current) => (current === "operations" ? null : "operations")); pushNotice("Panel de operación", "Se abrió el panel de acciones operativas.", "info"); }} />
          <TopDockButton icon={<Gauge className="h-4 w-4" />} label="Pipeline" active={activeOverlay === "pipeline"} onClick={() => { setActiveOverlay((current) => (current === "pipeline" ? null : "pipeline")); pushNotice("Estado del pipeline", "Se abrió el resumen operativo del pipeline.", "info"); }} />
          <TopDockButton icon={<PanelRightClose className="h-4 w-4" />} label="Actividad" active={activeOverlay === "activity"} onClick={() => { setActiveOverlay((current) => (current === "activity" ? null : "activity")); pushNotice("Actividad", "Se abrió el registro en vivo del sistema.", "info"); }} />
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
                <FilterChip active={queueFilter === "needs_attention"} label={`Atención (${queueStats.needs_attention})`} onClick={() => setQueueFilter("needs_attention")} />
                <FilterChip active={queueFilter === "with_agentic"} label={`Con IA (${queueStats.with_agentic})`} onClick={() => setQueueFilter("with_agentic")} />
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
                              <p className="max-h-14 overflow-hidden break-words text-base font-semibold">{cleanDisplayText(quote.subject ?? quote.quote_key)}</p>
                              {needsAttention && (
                                <span className={`rounded-full px-2 py-1 text-[11px] ${selected ? "bg-white/20" : "bg-amber-100 text-amber-800"}`}>
                                  revisar
                                </span>
                              )}
                            </div>
                            <p className="mt-2 text-sm opacity-85">{cleanDisplayText(quote.placa ?? "Sin placa")} · aviso {cleanDisplayText(quote.aviso_id ?? "n/d")}</p>
                            <p className="mt-1 text-xs opacity-70">{cleanDisplayText(quote.marca ?? "Marca n/d")} {cleanDisplayText(quote.linea ?? "")}</p>
                            <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                              <MiniBadge selected={selected} icon={<ClipboardList className="h-3 w-3" />}>
                                {quote.parts_with_matches}/{quote.repuestos_count} con proveedor
                              </MiniBadge>
                              <MiniBadge selected={selected} icon={<Sparkles className="h-3 w-3" />}>
                                {quote.parts_with_agentic_matches} con IA
                              </MiniBadge>
                            </div>
                          </div>
                          <span className={`rounded-full px-3 py-1 text-xs ${selected ? "bg-white/20" : statusTone[quote.load_status ?? ""] ?? "bg-slate-100 text-slate-800"}`}>
                            {statusLabel[quote.load_status ?? ""] ?? quote.load_status ?? "n/d"}
                          </span>
                        </div>
                      </button>
                    </div>
                  </div>
                );
              })}
              {filteredQuotes.length === 0 && (
                <EmptyBlock title="No hay cotizaciones con ese filtro" description="Prueba otro texto de búsqueda o cambia el filtro de la cola." />
              )}
            </div>
          </section>
        </aside>

        <section className="flex min-h-0 flex-col gap-4">
          {selectedQuote ? (
            <div className="flex min-h-0 flex-1 flex-col rounded-3xl bg-white/80 p-5 shadow-panel backdrop-blur xl:overflow-hidden">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <p className="text-xs uppercase tracking-[0.25em] text-olive">Cotización seleccionada</p>
                  <h2 className="mt-1 break-words text-2xl font-semibold text-pine">{cleanDisplayText(selectedQuote.source?.subject ?? selectedQuote.quote_key)}</h2>
                  <div className="mt-3 flex flex-wrap gap-2 text-sm text-ink/70">
                    <HeaderChip icon={<CarFront className="h-4 w-4" />} label={cleanDisplayText(`${selectedQuote.orbika?.marca ?? "Marca n/d"} ${selectedQuote.orbika?.linea ?? ""}`)} />
                    <HeaderChip icon={<ClipboardList className="h-4 w-4" />} label={cleanDisplayText(`Placa ${selectedQuote.orbika?.placa ?? "n/d"}`)} />
                    <HeaderChip icon={<Clock3 className="h-4 w-4" />} label={cleanDisplayText(selectedQuote.source?.received_at ?? "sin fecha")} />
                  </div>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-medium ${statusTone[selectedQuote.orbika?.load_status] ?? "bg-slate-100 text-slate-800"}`}>
                  {statusLabel[selectedQuote.orbika?.load_status] ?? selectedQuote.orbika?.load_status ?? "desconocido"}
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
                {[["overview", "Resumen"], ["parts", "Repuestos"], ["matches", "Proveedores"], ["agentic", "Revisión IA"]].map(([key, label]) => (
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
                    <InfoPanel title="Vehículo" rows={[["Marca", selectedQuote.orbika?.marca], ["Línea", selectedQuote.orbika?.linea], ["Versión", selectedQuote.orbika?.version], ["Año", selectedQuote.orbika?.ano], ["VIN", selectedQuote.orbika?.vin]]} />
                    <InfoPanel title="Taller" rows={[["Nombre", selectedQuote.orbika?.nombre_comercial], ["Entrega", selectedQuote.orbika?.taller_entrega], ["Ciudad", selectedQuote.orbika?.ciudad], ["Dirección", selectedQuote.orbika?.direccion]]} />
                  </div>
                  <div className="grid gap-6">
                    <InfoPanel title="Decisión rápida" rows={[["Repuestos", String(selectedQuote?.orbika?.parts?.length ?? 0)], ["Con proveedor", String(selectedQuote?.supplier_matching?.summary?.parts_with_matches ?? 0)], ["Con revisión IA", String(selectedQuote?.agentic_supplier_matching?.summary?.parts_with_agentic_matches ?? 0)], ["Estado", statusLabel[selectedQuote?.orbika?.load_status ?? ""] ?? selectedQuote?.orbika?.load_status]]} />
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
                            <MiniInfo label="Cantidad" value={part.quantity ?? "n/d"} />
                            <MiniInfo label="Referencia" value={part.reference ?? "n/d"} />
                            <MiniInfo label="Calidad" value={part.quality ?? "n/d"} />
                            <MiniInfo label="Entrega" value={part.delivery_days ?? "n/d"} />
                          </div>
                          {(part.total_value || part.unit_gross_price || part.observation_visible) && (
                            <p className="mt-3 text-sm text-ink/65">
                              Total: {part.total_value ?? "n/d"} · Unitario: {part.unit_gross_price ?? "n/d"}
                              {part.observation_visible ? ` · Obs: ${part.observation_visible}` : ""}
                            </p>
                          )}
                        </div>
                        <span className="rounded-full bg-sand px-2 py-1 text-xs">{part.raw_status ?? "n/d"}</span>
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
                          <p className="font-medium">{cleanDisplayText(part.part_name)}</p>
                          <p className="text-sm text-ink/60">Mejor puntaje: {cleanDisplayText(part.best_score_percent ?? 0)}% · {cleanDisplayText(part.best_provider_id ?? "sin proveedor")}</p>
                        </div>
                        <span className="rounded-full bg-mist px-3 py-1 text-xs text-ink/70">{part.matches?.length ?? 0} opción(es)</span>
                      </div>
                      <div className="grid gap-3">
                        {part.matches?.length ? (
                          part.matches.map((match: any, index: number) => (
                            <div key={`${part.part_name}-${match.provider_id}-${index}`} className="rounded-xl bg-mist/80 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0 flex-1">
                                  <p className="font-medium">{cleanDisplayText(match.product_name)}</p>
                                  <p className="text-sm text-ink/60">{cleanDisplayText(match.provider_name)} · {cleanDisplayText(match.match_type)} · {cleanDisplayText(match.score_percent)}%</p>
                                  {match.reference && <p className="mt-1 text-xs text-ink/55">Ref: {cleanDisplayText(match.reference)}</p>}
                                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                                    <MiniBadge tone={match.explanation_source === "rag" ? "accent" : "good"}>
                                      {match.explanation_source === "rag" ? "IA + RAG" : "IA heurística"}
                                    </MiniBadge>
                                    <MiniBadge tone={(compatibilityTone[match.compatibility_state ?? "insufficient_information"] as any) ?? "accent"}>
                                      {compatibilityLabel[match.compatibility_state ?? "insufficient_information"] ?? "Info insuficiente"}
                                    </MiniBadge>
                                    {match.compatibility_summary ? <MiniBadge tone="neutral">{match.compatibility_summary}</MiniBadge> : null}
                                  </div>
                                  {match.compatibility_warnings?.length ? <p className="mt-2 text-xs text-amber-800">Validar: {cleanDisplayText(match.compatibility_warnings.join(", "))}</p> : null}
                                  {match.preference_notes?.length ? <p className="mt-1 text-xs text-sky-800">Preferencia: {cleanDisplayText(match.preference_notes.join(", "))}</p> : null}
                                </div>
                                <a className="text-sm text-pine underline" href={match.detail_url} target="_blank" rel="noreferrer">Ver</a>
                              </div>
                            </div>
                          ))
                        ) : (
                          <EmptyBlock title="Sin coincidencias" description="Este repuesto todavía no tiene candidatos de proveedor." compact />
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
                          <p className="font-medium">{cleanDisplayText(part.part_name)}</p>
                          <p className="text-sm text-ink/60">Proveedor líder: {cleanDisplayText(part.top_provider_id ?? "n/d")} · Puntaje: {cleanDisplayText(part.top_score_percent ?? 0)}%</p>
                          {part.summary_comment ? <p className="mt-2 rounded-xl bg-olive/10 px-3 py-2 text-sm text-olive">{cleanDisplayText(part.summary_comment)}</p> : null}
                        </div>
                        <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs text-emerald-800">{part.selected_matches?.length ?? 0} recomendación(es)</span>
                      </div>
                      <div className="grid gap-3">
                        {(part.risk_notes?.length || part.preference_notes?.length) ? (
                          <div className="flex flex-wrap gap-2 text-xs">
                            {part.risk_notes?.map((note: string) => (
                              <span key={`${part.part_name}-risk-${note}`} className="rounded-full bg-amber-50 px-2 py-1 text-amber-900">Riesgo: {cleanDisplayText(note)}</span>
                            ))}
                            {part.preference_notes?.map((note: string) => (
                              <span key={`${part.part_name}-pref-${note}`} className="rounded-full bg-sky-50 px-2 py-1 text-sky-900">Preferencia: {cleanDisplayText(note)}</span>
                            ))}
                          </div>
                        ) : null}
                        {part.selected_matches?.length ? (
                          part.selected_matches.map((match: any) => (
                            <div key={`${part.part_name}-${match.rank}-${match.provider_id}`} className="rounded-xl bg-mist/80 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0 flex-1">
                                  <p className="font-medium">#{match.rank} · {match.product_name}</p>
                                  <p className="text-sm text-ink/60">{cleanDisplayText(match.provider_name)} · {cleanDisplayText(match.match_type)} · {cleanDisplayText(match.score_percent)}%</p>
                                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                                    <MiniBadge tone={match.explanation_source === "rag" ? "accent" : "good"}>
                                      {match.explanation_source === "rag" ? "IA + RAG" : "IA heurística"}
                                    </MiniBadge>
                                    <MiniBadge tone={(compatibilityTone[match.compatibility_state ?? "insufficient_information"] as any) ?? "accent"}>
                                      {compatibilityLabel[match.compatibility_state ?? "insufficient_information"] ?? "Info insuficiente"}
                                    </MiniBadge>
                                    {match.compatibility_summary ? <MiniBadge tone="neutral">{match.compatibility_summary}</MiniBadge> : null}
                                  </div>
                                  {match.compatibility_warnings?.length ? <p className="mt-2 text-xs text-amber-800">Validar: {cleanDisplayText(match.compatibility_warnings.join(", "))}</p> : null}
                                  {match.risk_flags?.length ? <p className="mt-1 text-xs text-amber-800">Riesgos: {cleanDisplayText(match.risk_flags.join(", "))}</p> : null}
                                  {match.preference_notes?.length ? <p className="mt-1 text-xs text-sky-800">Preferencia: {cleanDisplayText(match.preference_notes.join(", "))}</p> : null}
                                  {match.rag_summary ? <p className="mt-1 text-xs text-violet-800">Técnico: {cleanDisplayText(match.rag_summary)}</p> : null}
                                  {match.rag_citations?.length ? <p className="mt-1 text-xs text-violet-800">Fuentes: {cleanDisplayText(match.rag_citations.map((citation: any) => `${citation.title} p.${citation.page_span}`).join(" · "))}</p> : null}
                                  <p className="mt-2 rounded-xl bg-white px-3 py-2 text-sm text-olive">{cleanDisplayText(match.agentic_comment || "Sin comentario adicional.")}</p>
                                </div>
                                <a className="text-sm text-pine underline" href={match.detail_url} target="_blank" rel="noreferrer">Ver</a>
                              </div>
                            </div>
                          ))
                        ) : (
                          <EmptyBlock title="Sin selección IA" description="Esta pieza todavía no tiene recomendación final del revisor IA." compact />
                        )}
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

      <OverlayPanel open={activeOverlay === "operations"} title="Operación funcional" subtitle="Acciones para mantener la cola al día y lanzar reprocesos sin salir del tablero." onClose={() => setActiveOverlay(null)}>
        <div className="grid gap-3">
          <ActionButton icon={<Mail className="h-4 w-4" />} title={runningRunner ? "Runner activo" : "Esperar correos"} description={runningRunner ? "El pipeline está escuchando nuevos correos." : "Inicia el runner incremental en modo espera."} onClick={() => runAction("/api/tasks/incremental-runner/start", { poll_seconds: 300, max_results: 50 })} disabled={Boolean(runningRunner) || isBusy} tone={runningRunner ? "success" : "default"} />
          <ActionButton icon={<Square className="h-4 w-4" />} title="Detener runner" description="Finaliza el proceso de espera actual." onClick={() => runningRunner && runAction(`/api/tasks/${runningRunner.id}/stop`)} disabled={!runningRunner || isBusy} />
          <ActionButton icon={<Wrench className="h-4 w-4" />} title="Recalcular matching" description="Reprocesa matching de proveedores para todas las cotizaciones." onClick={() => runAction("/api/tasks/supplier-matching/run", { limit_per_part: 5 })} disabled={isBusy} />
          <ActionButton icon={<Layers3 className="h-4 w-4" />} title="Matching de selección" description="Ejecuta matching de proveedores solo sobre las cotizaciones marcadas." onClick={() => runAction("/api/tasks/supplier-matching/run", { limit_per_part: 5, quote_keys: selectedQuoteKeys })} disabled={isBusy || selectedQuoteKeys.length === 0} />
          <ActionButton icon={<Bot className="h-4 w-4" />} title="Revisión IA" description="Ejecuta la revisión IA sobre todas las cotizaciones." onClick={() => runAction("/api/tasks/agentic-review/run", { limit_per_part: 5, disable_traces: false })} disabled={isBusy} />
          <ActionButton icon={<Sparkles className="h-4 w-4" />} title="Revisión IA de selección" description="Ejecuta la revisión IA solo sobre las cotizaciones marcadas." onClick={() => runAction("/api/tasks/agentic-review/run", { limit_per_part: 5, disable_traces: false, quote_keys: selectedQuoteKeys })} disabled={isBusy || selectedQuoteKeys.length === 0} />
        </div>
      </OverlayPanel>

      <OverlayPanel open={activeOverlay === "pipeline"} title="Estado del pipeline" subtitle="Resumen operativo del runner, el último ciclo y la presión actual sobre la cola." onClose={() => setActiveOverlay(null)}>
        <div className="grid gap-5">
          <section className="grid gap-2 text-sm">
            <StateRow label="Runner" value={runningRunner ? "Esperando correos" : "Detenido"} />
            <StateRow label="Etapa actual" value={String(dashboard?.current?.stage ?? "idle")} />
            <StateRow label="Última corrida" value={String(dashboard?.last_run?.finished_at ?? "n/d")} />
            <StateRow label="Última cotización" value={String(dashboard?.latest_quote_at ?? "n/d")} />
          </section>

          <section className="rounded-2xl border border-clay bg-mist/70 p-4">
            <p className="text-sm font-semibold text-pine">Presión de la cola</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <StateBadge label="Atención" value={String(queueStats.needs_attention)} tone="warn" />
              <StateBadge label="Con IA" value={String(queueStats.with_agentic)} tone="accent" />
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
              <p className="text-mist/70">Aún no hay actividad registrada.</p>
            )}
          </div>
          <div className="space-y-3">
            <p className="text-sm font-semibold text-pine">Tareas recientes</p>
            {tasks.slice(0, 8).map((task) => (
              <div key={task.id} className="rounded-2xl border border-clay bg-white p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-ink">{taskKindLabel[task.kind] ?? task.kind}</p>
                  <span className="rounded-full bg-sand px-2 py-1 text-xs text-ink/70">{taskStatusLabel[task.status] ?? task.status}</span>
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
    <button
      type="button"
      disabled={disabled}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
      className={`rounded-2xl border p-4 text-left transition hover:border-olive disabled:cursor-not-allowed disabled:opacity-50 ${toneClass}`}
    >
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
            <span className="break-words">{value ?? "n/d"}</span>
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
    <button
      type="button"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
      className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm transition ${active ? "border-pine bg-pine text-white" : "border-clay bg-white text-ink hover:border-olive"}`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function OverlayPanel({ open, title, subtitle, onClose, children, wide }: { open: boolean; title: string; subtitle: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-end bg-ink/20 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className={`mt-20 w-full overflow-hidden rounded-[2rem] border border-clay bg-white shadow-2xl ${wide ? "max-w-4xl" : "max-w-xl"}`} onClick={(event) => event.stopPropagation()}>
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
      type="button"
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
      <p className="mb-4 text-sm font-semibold text-pine">Línea de tiempo</p>
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
          <p className="text-sm text-ink/60">Aún no hay hits agregados.</p>
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
