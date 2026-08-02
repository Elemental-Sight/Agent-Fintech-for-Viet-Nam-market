"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { ObservabilitySummary } from "@/lib/types";

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

export default function ObservabilityPage() {
  const [data, setData] = useState<ObservabilitySummary | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/observability");
      setData(await res.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Intentional fetch-on-mount -- setState happens inside `load`'s async
    // body (after an await), not synchronously in the effect itself.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Quan sát hệ thống</h1>
            <p className="text-sm text-muted-foreground">
              Số liệu vận hành thực tế — chỉ hiển thị token (không quy đổi ra chi phí $ vì chưa có mức giá Groq
              thật được cấu hình).
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Làm mới
          </Button>
        </div>

        {loading && !data ? (
          <div className="grid grid-cols-3 gap-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : data ? (
          <>
            <div className="grid grid-cols-3 gap-4">
              <StatCard label="Tổng số lượt hỏi" value={String(data.total_requests)} />
              <StatCard label="Tỷ lệ cache-hit" value={`${(data.cache_hit_rate * 100).toFixed(1)}%`} />
              <StatCard label="Tỷ lệ fast-path" value={`${(data.fast_path_rate * 100).toFixed(1)}%`} />
            </div>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Tool được gọi nhiều nhất</CardTitle>
              </CardHeader>
              <CardContent>
                {data.top_tools.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Chưa có dữ liệu.</p>
                ) : (
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.top_tools} layout="vertical" margin={{ left: 24 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                        <XAxis type="number" allowDecimals={false} />
                        <YAxis type="category" dataKey="tool_name" width={140} />
                        <RechartsTooltip />
                        <Bar dataKey="calls" fill="var(--color-primary)" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Token / latency trung bình theo node</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Node</TableHead>
                      <TableHead>Số lượt gọi</TableHead>
                      <TableHead>Token vào TB</TableHead>
                      <TableHead>Token ra TB</TableHead>
                      <TableHead>Latency TB (ms)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.by_node.map((row) => (
                      <TableRow key={row.node}>
                        <TableCell className="font-medium">{row.node}</TableCell>
                        <TableCell>{row.calls}</TableCell>
                        <TableCell>{Math.round(row.avg_tokens_in)}</TableCell>
                        <TableCell>{Math.round(row.avg_tokens_out)}</TableCell>
                        <TableCell>{Math.round(row.avg_latency_ms)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Lượt hỏi gần nhất</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Thời gian</TableHead>
                      <TableHead>Tool</TableHead>
                      <TableHead>Fast-path</TableHead>
                      <TableHead>Cache-hit</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.recent_requests.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                          {new Date(r.created_at).toLocaleString("vi-VN")}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{r.tool_name ?? "none"}</Badge>
                        </TableCell>
                        <TableCell>{r.used_fast_path ? "✓" : ""}</TableCell>
                        <TableCell>{r.cache_hit ? "✓" : ""}</TableCell>
                      </TableRow>
                    ))}
                    {data.recent_requests.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                          Chưa có lượt hỏi nào.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </div>
  );
}
