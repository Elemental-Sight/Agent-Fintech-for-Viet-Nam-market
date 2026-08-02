export interface SessionOut {
  thread_id: string;
  title: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface MessageOut {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  thread_id: string;
  answer: string;
  resolved_ticker: string | null;
  resolved_date_range: Record<string, unknown> | null;
  tool_name: string | null;
  used_fast_path: boolean | null;
  cache_hit: boolean | null;
}

export interface UsageSummary {
  calls: number;
  tokens_in: number;
  tokens_out: number;
  avg_latency_ms: number;
}

export interface ObservabilitySummary {
  total_requests: number;
  cache_hit_rate: number;
  fast_path_rate: number;
  top_tools: { tool_name: string; calls: number }[];
  by_node: {
    node: string;
    calls: number;
    avg_tokens_in: number;
    avg_tokens_out: number;
    avg_latency_ms: number;
  }[];
  recent_requests: {
    thread_id: string | null;
    tool_name: string | null;
    used_fast_path: boolean | null;
    cache_hit: boolean | null;
    created_at: string;
  }[];
}

export interface ScreenerRequestBody {
  rsi_min?: number;
  rsi_max?: number;
  sma_period?: number;
  sma_condition?: "above" | "below";
  financial_metric?: "REVENUE" | "NET_PROFIT" | "EPS" | "DEBT";
  financial_op?: "gt" | "gte" | "lt" | "lte";
  financial_value?: number;
}

export interface ScreenerResult {
  universe_size: number;
  matched: Record<string, string | number>[];
  skipped: { ticker: string; reason: string }[];
}
