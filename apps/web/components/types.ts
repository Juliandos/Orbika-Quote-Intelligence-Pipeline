export type QuoteSummary = {
  quote_key: string;
  path: string;
  generated_at?: string | null;
  received_at?: string | null;
  subject?: string | null;
  aviso_id?: string | null;
  placa?: string | null;
  marca?: string | null;
  linea?: string | null;
  load_status?: string | null;
  repuestos_count: number;
  parts_with_matches: number;
  exact_reference_matches: number;
  parts_with_agentic_matches: number;
};

export type DashboardPayload = {
  counts: {
    quotes_total: number;
    loaded_quotes: number;
    failed_quotes: number;
    partial_quotes: number;
  };
  last_run?: Record<string, unknown>;
  current?: Record<string, unknown>;
  latest_quote_at?: string | null;
  provider_hits: Record<string, number>;
  recent_quotes: QuoteSummary[];
  generated_at: string;
};

export type TaskRecord = {
  id: string;
  kind: string;
  status: string;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  exit_code?: number | null;
  pid?: number | null;
  singleton_key?: string | null;
  meta?: Record<string, unknown>;
};

export type EventPayload = {
  timestamp?: number;
  task?: TaskRecord;
  task_id?: string;
  line?: string;
  quote?: QuoteSummary;
  dashboard?: DashboardPayload;
  state?: Record<string, unknown>;
  tasks?: TaskRecord[];
};
