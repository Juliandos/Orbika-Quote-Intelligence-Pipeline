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
  parts_reviewed: number;
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

export type GraphNodePayload = {
  node_key: string;
  node_type: string;
  entity_id?: string | null;
  quote_key?: string | null;
  part_id?: string | null;
  provider_id?: string | null;
  label?: string | null;
  summary?: string | null;
  payload?: Record<string, unknown>;
  created_at?: string | null;
};

export type GraphEdgePayload = {
  edge_key: string;
  edge_type: string;
  source_node_key?: string | null;
  source_node_type?: string | null;
  source_entity_id?: string | null;
  target_node_key?: string | null;
  target_node_type?: string | null;
  target_entity_id?: string | null;
  quote_key?: string | null;
  part_id?: string | null;
  provider_id?: string | null;
  label?: string | null;
  evidence?: Record<string, unknown>;
  created_at?: string | null;
};

export type GraphContextPayload = {
  quote_key: string;
  generated_at: string;
  summary: {
    node_count: number;
    edge_count: number;
    node_types: Record<string, number>;
    edge_types: Record<string, number>;
  };
  nodes: GraphNodePayload[];
  edges: GraphEdgePayload[];
};

export type QuoteDetailPayload = {
  quote_key: string;
  generated_at?: string | null;
  quote_url_masked?: string | null;
  source?: {
    gmail_id?: string | null;
    message_id?: string | null;
    thread_id?: string | null;
    sender?: string | null;
    subject?: string | null;
    received_at?: string | null;
    raw_excerpt?: string | null;
  };
  orbika?: {
    aviso_id?: string | null;
    load_status?: string | null;
    warnings?: string[];
    placa?: string | null;
    marca?: string | null;
    linea?: string | null;
    version?: string | null;
    ano?: number | null;
    vin?: string | null;
    color?: string | null;
    nombre_comercial?: string | null;
    taller_entrega?: string | null;
    ciudad?: string | null;
    direccion?: string | null;
    telefono?: string | null;
    repuestos_count?: number;
    parts?: unknown[];
  };
  supplier_matching?: {
    summary?: Record<string, unknown>;
    parts?: unknown[];
  };
  agentic_supplier_matching?: {
    summary?: Record<string, unknown>;
    parts?: any[];
  };
  graph_context?: GraphContextPayload | null;
  [key: string]: any;
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


export type LauncherStatusPayload = {
  db_port_open: boolean;
  api_port_open: boolean;
  web_port_open: boolean;
  api_healthy: boolean;
  web_healthy: boolean;
  api_pid_running: boolean;
  web_pid_running: boolean;
  maintenance?: Record<string, unknown>;
  provider_refresh?: Record<string, unknown>;
  supervision?: Record<string, unknown>;
  state_file?: string;
  launcher_started_at?: string | null;
};
