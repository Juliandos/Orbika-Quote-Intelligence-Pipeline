"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sun,
  Moon,
  Mail,
  Square,
  Wrench,
  Bot,
  Activity,
  Layers3,
  Sparkles,
  X,
  ExternalLink,
} from "lucide-react";
import { apiBase, getDashboard, getLauncherStatus, getQuote, getQuotes, getTasks, postJson } from "@/components/api";
import { useEventStream } from "@/components/use-event-stream";
import { DashboardPayload, LauncherStatusPayload, QuoteSummary, TaskRecord } from "@/components/types";

type TriageTab = "cotizables" | "todas" | "vencidas";
type Quality = "good" | "warn" | "crit";
type NoticeTone = "success" | "error" | "info";
type NoticeItem = { id: number; title: string; message: string; tone: NoticeTone };

const CATALOG_SIZE = 35554; // productos reales en provider_products

const statusLabel: Record<string, string> = {
  loaded: "Lista",
  partial: "Parcial",
  failed_after_retries: "Vencida",
};

const reviewModeLabel: Record<string, string> = {
  llm_review: "Revisión con IA",
  heuristic_fallback: "Heurística",
  heuristic: "Heurística",
};

/* ---------- helpers de datos reales (sin inventar) ---------- */

function cleanText(value: unknown) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/Â/g, "").normalize("NFC").trim();
}

function relTime(iso?: string | null) {
  if (!iso) return "sin fecha";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return cleanText(iso);
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "hace instantes";
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.floor(h / 24);
  return `hace ${d} d`;
}

function parseInsurer(subject?: string | null) {
  if (!subject) return null;
  const parts = subject.split("_").map((p) => p.trim()).filter(Boolean);
  const last = parts[parts.length - 1];
  if (last && /^[A-Za-zÁÉÍÓÚÑ ]{3,16}$/.test(last)) return last.toUpperCase();
  return null;
}

function parsePlate(quote: { placa?: string | null; subject?: string | null }) {
  if (quote.placa && quote.placa !== "n/d") return quote.placa.toUpperCase();
  const m = (quote.subject ?? "").match(/[A-Z]{3}\s?\d{2,3}[A-Z]?/);
  return m ? m[0].replace(/\s/g, "") : "—";
}

function qualityOf(loadStatus?: string | null, repuestos = 0, withMatches = 0): Quality {
  if (loadStatus === "failed_after_retries" || repuestos === 0) return "crit";
  if (withMatches > 0 && withMatches >= repuestos) return "good";
  return "warn";
}

const qualityRank: Record<Quality, number> = { good: 0, warn: 1, crit: 2 };

function scoreTone(pct: number, compatState?: string | null): Quality {
  if (compatState === "incompatible") return "crit";
  if (compatState === "warning") return "warn";
  if (compatState === "compatible") return pct >= 55 ? "good" : "warn";
  if (pct >= 78) return "good";
  if (pct >= 55) return "warn";
  return "crit";
}

function toneVar(q: Quality) {
  return q === "good" ? "var(--good)" : q === "warn" ? "var(--warn)" : "var(--crit)";
}

function matchName(m: any, partName: string) {
  const pn = cleanText(m?.product_name);
  if (pn && pn.toLowerCase() !== "unknown product") return pn;
  const built = [cleanText(m?.brand), cleanText(m?.reference)].filter(Boolean).join(" ");
  if (built) return built;
  const cat = cleanText(m?.category_name);
  return cat && cat.toLowerCase() !== "todos los productos" ? cat : partName;
}

function isExactRef(m: any) {
  const t = String(m?.match_type ?? "").toLowerCase();
  return t.includes("reference") || t.includes("exact") || t.includes("sku");
}

/* ---------- página ---------- */

export default function Page() {
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null);
  const [quotes, setQuotes] = useState<QuoteSummary[]>([]);
  const [selectedQuoteKey, setSelectedQuoteKey] = useState<string | null>(null);
  const [selectedQuoteKeys, setSelectedQuoteKeys] = useState<string[]>([]);
  const [selectedQuote, setSelectedQuote] = useState<any | null>(null);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [launcher, setLauncher] = useState<LauncherStatusPayload | null>(null);
  const [notices, setNotices] = useState<NoticeItem[]>([]);
  const [triageTab, setTriageTab] = useState<TriageTab>("cotizables");
  const [searchText, setSearchText] = useState("");
  const [opsOpen, setOpsOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [activity, setActivity] = useState<{ id: number; time: string; message: string; tone: NoticeTone }[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const [connError, setConnError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  const deferredSearch = useDeferredValue(searchText);

  useEffect(() => {
    const existing = document.documentElement.getAttribute("data-theme") as "dark" | "light" | null;
    const initial = existing ?? (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark");
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
  };

  const pushNotice = (title: string, message: string, tone: NoticeTone = "info") => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setNotices((cur) => [{ id, title, message, tone }, ...cur].slice(0, 4));
    window.setTimeout(() => setNotices((cur) => cur.filter((n) => n.id !== id)), 4200);
  };

  const friendlyTask: Record<string, string> = {
    incremental_runner: "Revisión de correos entrantes",
    supplier_matching: "Búsqueda de proveedores",
    supplier_matching_selection: "Búsqueda de proveedores (selección)",
    agentic_review: "Revisión inteligente + búsqueda en internet",
    agentic_review_selection: "Revisión inteligente (selección)",
  };
  const pushActivity = (message: string, tone: NoticeTone = "info") => {
    const time = new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
    setActivity((cur) => [{ id: Date.now() + Math.random(), time, message, tone }, ...cur].slice(0, 40));
  };

  const refreshAll = async ({ silent = false }: { silent?: boolean } = {}) => {
    const [d, q, t, l] = await Promise.all([getDashboard(), getQuotes(), getTasks(), getLauncherStatus()]);
    setDashboard(d);
    setQuotes(q);
    setTasks(t);
    setLauncher(l);
    if (!silent) pushNotice("Bandeja actualizada", "Cotizaciones, métricas y tareas recargadas.", "success");
    if (!selectedQuoteKey && q[0]?.quote_key) setSelectedQuoteKey(q[0].quote_key);
  };

  const loadQuote = async (key: string) => {
    setSelectedQuoteKey(key);
    setSelectedQuote(await getQuote(key));
  };

  useEffect(() => {
    refreshAll({ silent: true })
      .then(() => setConnError(null))
      .catch((e) => setConnError(String((e as Error)?.message ?? e)));
  }, []);

  useEffect(() => {
    if (!selectedQuoteKey) return;
    loadQuote(selectedQuoteKey).catch(() => {});
  }, [selectedQuoteKey]);

  useEventStream({
    onDashboard: () => {
      refreshAll({ silent: true }).catch(() => {});
      if (selectedQuoteKey) loadQuote(selectedQuoteKey).catch(() => {});
    },
    onTasks: () => getTasks().then(setTasks).catch(() => {}),
    onQuoteNew: (payload) => {
      const subj = cleanText(payload?.quote?.subject) || "Correo recibido";
      pushNotice("Nueva cotización", subj, "success");
      pushActivity("📩 Llegó una cotización nueva: " + subj, "success");
    },
    onTaskCompleted: (payload: any) => {
      pushActivity("✅ Listo: " + (friendlyTask[payload?.task?.kind] ?? "la tarea"), "success");
      refreshAll({ silent: true }).catch(() => {});
    },
    onTaskFailed: (payload: any) => {
      pushNotice("Tarea con error", "Revisa el panel de operación.", "error");
      pushActivity("⚠️ " + (friendlyTask[payload?.task?.kind] ?? "Una tarea") + " tuvo un problema; se reintentará.", "error");
    },
    onTaskStarted: (payload: any) => pushActivity("▶ Empezó: " + (friendlyTask[payload?.task?.kind] ?? "una tarea"), "info"),
    onLog: () => {},
  });

  const runningRunner = tasks.find(
    (t) => t.singleton_key === "incremental_runner" && ["starting", "running"].includes(t.status),
  );

  const enriched = useMemo(
    () =>
      quotes.map((q) => {
        const quality = qualityOf(q.load_status, q.repuestos_count, q.parts_with_matches);
        return {
          q,
          quality,
          plate: parsePlate(q),
          insurer: parseInsurer(q.subject),
          vehicle: cleanText(`${q.marca ?? ""} ${q.linea ?? ""}`.trim()) || "Vehículo sin identificar",
        };
      }),
    [quotes],
  );

  const counts = useMemo(() => {
    let cot = 0,
      ven = 0;
    for (const e of enriched) {
      if (e.quality === "crit") ven++;
      else if (e.q.parts_with_matches > 0) cot++;
    }
    return { cotizables: cot, todas: enriched.length, vencidas: ven };
  }, [enriched]);

  const visibleRows = useMemo(() => {
    const needle = deferredSearch.trim().toLowerCase();
    let rows = enriched.filter((e) => {
      if (triageTab === "cotizables") return e.quality !== "crit" && e.q.parts_with_matches > 0;
      if (triageTab === "vencidas") return e.quality === "crit";
      return true;
    });
    if (needle) {
      rows = rows.filter((e) =>
        [e.plate, e.vehicle, e.insurer, e.q.aviso_id, e.q.subject].filter(Boolean).join(" ").toLowerCase().includes(needle),
      );
    }
    return rows.sort((a, b) => {
      const r = qualityRank[a.quality] - qualityRank[b.quality];
      if (r !== 0) return r;
      return Date.parse(b.q.received_at ?? "") - Date.parse(a.q.received_at ?? "");
    });
  }, [enriched, triageTab, deferredSearch]);

  const detail = useMemo(() => {
    const sq = selectedQuote;
    if (!sq) return null;
    const o = sq.orbika ?? {};
    const aMap: Record<string, any> = {};
    (sq.agentic_supplier_matching?.parts ?? []).forEach((p: any) => {
      if (p?.part_name) aMap[p.part_name] = p;
    });
    const sMap: Record<string, any> = {};
    (sq.supplier_matching?.parts ?? []).forEach((p: any) => {
      if (p?.part_name) sMap[p.part_name] = p;
    });
    const orbikaParts: any[] = o.parts ?? [];
    const parts = orbikaParts.map((op: any, i: number) => {
      const name = cleanText(op?.name) || `Repuesto ${i + 1}`;
      const a = aMap[name] ?? (sq.agentic_supplier_matching?.parts ?? [])[i];
      const s = sMap[name] ?? (sq.supplier_matching?.parts ?? [])[i];
      const iaMatches = a?.selected_matches ?? [];
      const catalogMatches = (iaMatches.length ? iaMatches : s?.matches ?? []).slice(0, 3);
      const webMatches = (a?.internet_matches ?? []).slice(0, 5).map((wm: any) => ({ ...wm, __web: true }));
      const matches = [...catalogMatches, ...webMatches];
      return {
        name,
        quantity: op?.quantity ?? null,
        requestedRef: cleanText(s?.requested_reference ?? op?.reference ?? ""),
        source: iaMatches.length ? "ia" : "catalogo",
        webCount: webMatches.length,
        reviewerMode: a?.reviewer_mode ?? sq.agentic_supplier_matching?.review_mode,
        matches,
      };
    });
    const withMatches = parts.filter((p) => p.matches.length > 0).length;
    const partsWithWeb = parts.filter((p: any) => (p.webCount || 0) > 0).length;
    const quality = qualityOf(o.load_status, orbikaParts.length, withMatches);
    return {
      plate: parsePlate({ placa: o.placa, subject: sq.source?.subject }),
      marcaLinea: cleanText(`${o.marca ?? ""} ${o.linea ?? ""}`.trim()) || "n/d",
      version: cleanText(o.version) || "n/d",
      ano: o.ano ?? "n/d",
      vin: cleanText(o.vin) || "n/d",
      aviso: cleanText(o.aviso_id) || "n/d",
      insurer: parseInsurer(sq.source?.subject) ?? "—",
      received: sq.source?.received_at,
      quality,
      loadStatus: o.load_status,
      reviewMode: reviewModeLabel[sq.agentic_supplier_matching?.review_mode ?? ""] ?? null,
      totalParts: orbikaParts.length,
      withMatches,
      partsWithWeb,
      parts,
    };
  }, [selectedQuote]);

  const runAction = async (path: string, payload: Record<string, unknown> = {}, label = "Acción") => {
    try {
      setIsBusy(true);
      await postJson(path, payload);
      pushNotice(label, "Solicitud aceptada por el backend.", "success");
      pushActivity("▶ Se inició: " + label, "info");
      await refreshAll({ silent: true });
    } catch (e) {
      pushNotice(label, String(e), "error");
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <>
      <div className="toast-wrap">
        {notices.map((n) => (
          <div key={n.id} className={`toast ${n.tone}`}>
            <div className="t-title">{n.title}</div>
            <div className="t-msg">{n.message}</div>
          </div>
        ))}
      </div>

      {/* ---- top bar ---- */}
      <div className="top">
        <div className="brand">
          <span className="mark">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/accedo-icon.png" alt="ACCEDO" />
          </span>
          Orbika <small>Consola · ACCEDO</small>
        </div>
        <div className="search" style={{ maxWidth: 320 }}>
          <Search size={15} />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Buscar placa, aseguradora o aviso…"
          />
        </div>
        <div className="grow" />
        <span className={`pill ${runningRunner ? "live" : "off"}`}>
          <span className="dot" /> {runningRunner ? "Ingesta activa · SURA" : "Ingesta en pausa"}
        </span>
        <button className="icon-btn" title="Actualizar" onClick={() => refreshAll({ silent: false })}>
          <RefreshCw size={15} />
        </button>
        <button className="icon-btn" title="Operación" onClick={() => setOpsOpen(true)}>
          <SlidersHorizontal size={15} />
        </button>
        <button className="icon-btn" title="Actividad" onClick={() => setActivityOpen(true)}>
          <Activity size={15} />
        </button>
        <button className="icon-btn" title="Cambiar tema" onClick={toggleTheme}>
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>

      {connError && (
        <div style={{ padding: "10px 22px", color: "var(--crit)", fontSize: 13 }}>
          No se pudo conectar con el backend (<code>{apiBase() || "/api"}</code>): {connError}
        </div>
      )}

      <div className="app">
        {/* ---- bandeja de triage ---- */}
        <aside className="rail">
          <div className="rail-head">
            <h2>Bandeja</h2>
            <div className="eyebrow">Ordenado por urgencia</div>
          </div>
          <div className="tabs" role="tablist">
            {([
              ["cotizables", "Cotizables", counts.cotizables],
              ["todas", "Todas", counts.todas],
              ["vencidas", "Vencidas", counts.vencidas],
            ] as [TriageTab, string, number][]).map(([key, label, c]) => (
              <button
                key={key}
                className="tab"
                role="tab"
                aria-selected={triageTab === key}
                onClick={() => setTriageTab(key)}
              >
                {label} <span className="c num">{c}</span>
              </button>
            ))}
          </div>
          <div className="list">
            {visibleRows.map((e) => (
              <div
                key={e.q.quote_key}
                className={`qrow ${e.quality === "crit" ? "expired" : ""}`}
                role="button"
                aria-current={selectedQuoteKey === e.q.quote_key}
                onClick={() => setSelectedQuoteKey(e.q.quote_key)}
              >
                <input
                  type="checkbox"
                  className="qcheck"
                  checked={selectedQuoteKeys.includes(e.q.quote_key)}
                  onChange={() => setSelectedQuoteKeys((cur) => (cur.includes(e.q.quote_key) ? cur.filter((k) => k !== e.q.quote_key) : [...cur, e.q.quote_key]))}
                  onClick={(ev) => ev.stopPropagation()}
                  title="Marcar cotización"
                />
                <span className={`status s-${e.quality}`} />
                <span>
                  <span className="plate">{e.plate}</span>
                  <span className="veh" style={{ display: "block" }}>
                    {e.vehicle}
                    {e.insurer ? ` · ${e.insurer}` : ""}
                  </span>
                </span>
                <span className="meta">
                  <b>{e.quality === "crit" ? "vencida" : relTime(e.q.received_at)}</b>
                  <br />
                  {e.q.repuestos_count > 0 ? `${e.q.parts_with_matches}/${e.q.repuestos_count} repuestos` : "sin repuestos"}
                </span>
              </div>
            ))}
            {visibleRows.length === 0 && (
              <div className="empty empty-mini" style={{ margin: 8 }}>
                <div className="big">Sin cotizaciones aquí</div>
                Cambia de pestaña o ajusta la búsqueda.
              </div>
            )}
          </div>
        </aside>

        {/* ---- panel principal ---- */}
        <main className="main">
          {!detail ? (
            <div className="state-empty-main">Selecciona una cotización de la bandeja para verla.</div>
          ) : (
            <>
              <div className="vhead">
                <div className="vplate">{detail.plate}</div>
                <div className="vfacts">
                  <Fact label="Marca / Línea" value={detail.marcaLinea} />
                  <Fact label="Versión" value={detail.version} />
                  <Fact label="Año" value={String(detail.ano)} mono />
                  <Fact label="VIN" value={detail.vin} mono small />
                  <Fact label="Aviso · Aseguradora" value={`${detail.aviso} · ${detail.insurer}`} />
                </div>
                <div className="urg">
                  <div className="eyebrow">Estado · recibido</div>
                  <div className={`status-tag st-${detail.quality}`} style={{ marginTop: 4 }}>
                    {statusLabel[detail.loadStatus ?? ""] ?? detail.loadStatus ?? "n/d"} · {relTime(detail.received)}
                  </div>
                </div>
              </div>

              <div className="board">
                <div className="board-head">
                  <h3>Repuestos a cotizar</h3>
                  <span className="chip num">{detail.totalParts} solicitados</span>
                  <span className="chip num">{CATALOG_SIZE.toLocaleString("es-CO")} productos comparados</span>
                  {detail.reviewMode && <span className="chip ai">◇ {detail.reviewMode}</span>}
                  {detail.partsWithWeb > 0 && <span className="chip web num">🌐 {detail.partsWithWeb} con internet</span>}
                </div>
                <div className="legend">
                  <span>
                    <b>Compatibilidad</b> — cruce contra catálogo real
                  </span>
                  <span style={{ color: "var(--good)" }}>● alta</span>
                  <span style={{ color: "var(--warn)" }}>● validar año/modelo</span>
                  <span>
                    <b>Ref. exacta</b> — coincide referencia OEM
                  </span>
                </div>

                {detail.totalParts === 0 && (
                  <div className="empty">
                    <div className="big">Esta cotización no tiene repuestos cargados</div>
                    El correo llegó pero el enlace de SURA no devolvió el detalle (suele expirar). No hay nada que cotizar aquí.
                  </div>
                )}

                {detail.parts.map((part, i) => (
                  <section className="part" key={`${part.name}-${i}`}>
                    <div className="part-top">
                      <span className="part-idx num">{i + 1}</span>
                      <div style={{ minWidth: 0 }}>
                        <div className="part-name">{part.name}</div>
                        <div className="part-sub">
                          {part.requestedRef ? `Ref. solicitada ${part.requestedRef}` : "Sin referencia OEM en el aviso"}
                          {part.source === "ia" ? " · priorizado por IA" : ""}
                        </div>
                      </div>
                      {part.webCount > 0 ? <span className="chip web num" style={{ marginLeft: 4 }}>🌐 {part.webCount} de internet</span> : null}
                      {part.quantity ? <span className="part-qty">Cant. {part.quantity}</span> : null}
                    </div>

                    {part.matches.length ? (
                      <div className="cards">
                        {part.matches.map((m: any, mi: number) => {
                          const pct = Number(m?.score_percent ?? 0);
                          const tone = scoreTone(pct, m?.compatibility_state);
                          const best = mi === 0 && !m.__web;
                          const compat = cleanText(m?.compatibility_summary);
                          return (
                            <div className={`mcard ${best ? "best" : ""}`} key={`${m?.provider_id}-${mi}`}>
                              {m.__web ? <span className="badge web">🌐 Web</span> : best ? <span className="badge best">◇ Mejor match · IA</span> : null}
                              <div className="prov">{cleanText(m?.provider_name) || m?.provider_id || "proveedor"}</div>
                              <div className="pname">{matchName(m, part.name)}</div>
                              <div className="pmeta">
                                <span className="pref">
                                  {cleanText(m?.reference) ? (
                                    <>
                                      {cleanText(m?.reference)} <small>ref.</small>
                                    </>
                                  ) : (
                                    <small>sin referencia</small>
                                  )}
                                </span>
                                {isExactRef(m) ? (
                                  <span className="tag t-good">✓ Ref. exacta</span>
                                ) : compat ? (
                                  <span className={`tag t-${tone}`}>{compat}</span>
                                ) : null}
                              </div>
                              <div className="compat">
                                <div className="bar">
                                  <span style={{ width: `${Math.max(6, Math.min(100, pct))}%`, background: toneVar(tone) }} />
                                </div>
                                <span className="val" style={{ color: toneVar(tone) }}>
                                  {pct}%
                                </span>
                              </div>
                              {m?.detail_url ? (
                                <a className="choose" href={m.detail_url} target="_blank" rel="noreferrer">
                                  Ver producto <ExternalLink size={13} style={{ verticalAlign: "-2px" }} />
                                </a>
                              ) : (
                                <span className="choose" style={{ opacity: 0.5, cursor: "default" }}>
                                  Sin enlace
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div style={{ padding: "14px 16px" }}>
                        <div className="empty">
                          <div className="big">Sin matches confiables todavía</div>
                          El catálogo no tiene una coincidencia sólida para este repuesto. Conviene búsqueda manual o revisar la
                          descripción.
                        </div>
                      </div>
                    )}
                  </section>
                ))}
              </div>
            </>
          )}
        </main>
      </div>

      {/* ---- overlay operación (acciones reales) ---- */}
      {opsOpen && (
        <div className="overlay-scrim" onClick={() => setOpsOpen(false)}>
          <div className="overlay-card" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 18px", borderBottom: "1px solid var(--line)" }}>
              <div>
                <div className="eyebrow">Operación</div>
                <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>Controla el pipeline sin salir de la consola.</div>
              </div>
              <button className="icon-btn" onClick={() => setOpsOpen(false)}>
                <X size={15} />
              </button>
            </div>
            <div style={{ padding: 18, display: "grid", gap: 10 }}>
              <ActionRow
                icon={<Mail size={16} />}
                title={runningRunner ? "Runner activo" : "Iniciar ingesta"}
                desc={runningRunner ? "Escuchando correos SURA cada 5 min." : "Arranca el runner incremental."}
                on={Boolean(runningRunner)}
                disabled={Boolean(runningRunner) || isBusy}
                onClick={() => runAction("/api/tasks/incremental-runner/start", { poll_seconds: 300, max_results: 50 }, "Ingesta")}
              />
              <ActionRow
                icon={<Square size={16} />}
                title="Detener ingesta"
                desc="Finaliza el runner en ejecución."
                disabled={!runningRunner || isBusy}
                onClick={() => runningRunner && runAction(`/api/tasks/${runningRunner.id}/stop`, {}, "Detener runner")}
              />
              <ActionRow
                icon={<Wrench size={16} />}
                title="Recalcular matching"
                desc="Reprocesa el cruce de proveedores en todas las cotizaciones."
                disabled={isBusy}
                onClick={() => runAction("/api/tasks/supplier-matching/run", { limit_per_part: 5 }, "Matching")}
              />
              <ActionRow
                icon={<Bot size={16} />}
                title="Revisión con IA"
                desc="Ejecuta la revisión agéntica (Claude) sobre las cotizaciones."
                disabled={isBusy}
                onClick={() => runAction("/api/tasks/agentic-review/run", { limit_per_part: 5, disable_traces: false }, "Revisión IA")}
              />
              <ActionRow
                icon={<Layers3 size={16} />}
                title={`Matching de selección (${selectedQuoteKeys.length})`}
                desc="Recalcula el matching solo en las cotizaciones marcadas."
                disabled={isBusy || selectedQuoteKeys.length === 0}
                onClick={() => runAction("/api/tasks/supplier-matching/run", { limit_per_part: 5, quote_keys: selectedQuoteKeys }, "Matching selección")}
              />
              <ActionRow
                icon={<Sparkles size={16} />}
                title={`Revisión IA de selección (${selectedQuoteKeys.length})`}
                desc="Corre la revisión IA + búsqueda web solo en las marcadas."
                disabled={isBusy || selectedQuoteKeys.length === 0}
                onClick={() => runAction("/api/tasks/agentic-review/run", { limit_per_part: 5, disable_traces: false, quote_keys: selectedQuoteKeys }, "Revisión IA selección")}
              />
            </div>
          </div>
        </div>
      )}
      {activityOpen && (
        <div className="overlay-scrim" onClick={() => setActivityOpen(false)}>
          <div className="overlay-card" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 18px", borderBottom: "1px solid var(--line)" }}>
              <div>
                <div className="eyebrow">Actividad</div>
                <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>Lo que está haciendo el sistema, en palabras simples.</div>
              </div>
              <button className="icon-btn" onClick={() => setActivityOpen(false)}>
                <X size={15} />
              </button>
            </div>
            <div style={{ padding: 14, display: "grid", gap: 8, maxHeight: "62vh", overflowY: "auto" }}>
              {activity.length === 0 ? (
                <div className="empty empty-mini">
                  <div className="big">Todo en calma</div>
                  Aquí verás en palabras claras lo que pasa: cotizaciones nuevas, búsquedas de proveedores y revisiones.
                </div>
              ) : (
                activity.map((a) => (
                  <div key={a.id} className={`actline ${a.tone}`}>
                    <span className="acttime num">{a.time}</span>
                    <span>{a.message}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Fact({ label, value, mono, small }: { label: string; value: string; mono?: boolean; small?: boolean }) {
  return (
    <div className="fact">
      <div className="eyebrow">{label}</div>
      <div className={`v ${mono ? "mono" : ""}`} style={small ? { fontSize: 13 } : undefined}>
        {value}
      </div>
    </div>
  );
}

function ActionRow({
  icon,
  title,
  desc,
  onClick,
  disabled,
  on,
}: {
  icon: ReactNode;
  title: string;
  desc: string;
  onClick: () => void;
  disabled?: boolean;
  on?: boolean;
}) {
  return (
    <button className={`action-btn ${on ? "on" : ""}`} disabled={disabled} onClick={onClick}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, fontWeight: 600, color: "var(--ink)" }}>
        {icon}
        {title}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3 }}>{desc}</div>
    </button>
  );
}
