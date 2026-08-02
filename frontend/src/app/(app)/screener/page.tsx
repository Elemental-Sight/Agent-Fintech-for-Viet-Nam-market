"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ScreenerRequestBody, ScreenerResult } from "@/lib/types";

const FINANCIAL_METRICS = ["REVENUE", "NET_PROFIT", "EPS", "DEBT"] as const;
const OPS: { value: NonNullable<ScreenerRequestBody["financial_op"]>; label: string }[] = [
  { value: "gt", label: "lớn hơn" },
  { value: "gte", label: "lớn hơn hoặc bằng" },
  { value: "lt", label: "nhỏ hơn" },
  { value: "lte", label: "nhỏ hơn hoặc bằng" },
];

export default function ScreenerPage() {
  const [rsiMin, setRsiMin] = useState("");
  const [rsiMax, setRsiMax] = useState("");
  const [smaPeriod, setSmaPeriod] = useState("");
  const [smaCondition, setSmaCondition] = useState<"" | "above" | "below">("");
  const [finMetric, setFinMetric] = useState<"" | (typeof FINANCIAL_METRICS)[number]>("");
  const [finOp, setFinOp] = useState<ScreenerRequestBody["financial_op"] | "">("");
  const [finValue, setFinValue] = useState("");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScreenerResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const columns = result
    ? Array.from(new Set(result.matched.flatMap((row) => Object.keys(row)))).filter((k) => k !== "ticker")
    : [];

  async function runScreener() {
    setLoading(true);
    setError(null);
    setResult(null);
    const body: ScreenerRequestBody = {};
    if (rsiMin) body.rsi_min = Number(rsiMin);
    if (rsiMax) body.rsi_max = Number(rsiMax);
    if (smaPeriod && smaCondition) {
      body.sma_period = Number(smaPeriod);
      body.sma_condition = smaCondition;
    }
    if (finMetric && finOp && finValue) {
      body.financial_metric = finMetric;
      body.financial_op = finOp;
      body.financial_value = Number(finValue);
    }
    try {
      const res = await fetch("/api/screener", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error();
      setResult(await res.json());
    } catch {
      setError("Không lọc được, vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div>
          <h1 className="text-lg font-semibold">Bộ lọc cổ phiếu</h1>
          <p className="text-sm text-muted-foreground">
            Lọc tất định trên danh sách 20 mã lớn có sẵn (không qua LLM). Mỗi lượt lọc gọi vnstock tuần tự cho
            từng mã nên có thể mất 1-2 phút.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Điều kiện lọc</CardTitle>
            <CardDescription>Để trống điều kiện nào không cần dùng.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="space-y-2">
                <Label>RSI tối thiểu</Label>
                <Input type="number" value={rsiMin} onChange={(e) => setRsiMin(e.target.value)} placeholder="vd 0" />
              </div>
              <div className="space-y-2">
                <Label>RSI tối đa</Label>
                <Input type="number" value={rsiMax} onChange={(e) => setRsiMax(e.target.value)} placeholder="vd 30" />
              </div>
              <div className="space-y-2">
                <Label>Chu kỳ SMA</Label>
                <Input
                  type="number"
                  value={smaPeriod}
                  onChange={(e) => setSmaPeriod(e.target.value)}
                  placeholder="vd 20"
                />
              </div>
              <div className="space-y-2">
                <Label>Giá so với SMA</Label>
                <select
                  className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                  value={smaCondition}
                  onChange={(e) => setSmaCondition(e.target.value as "" | "above" | "below")}
                >
                  <option value="">-- không dùng --</option>
                  <option value="above">Trên SMA</option>
                  <option value="below">Dưới SMA</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <Label>Chỉ số BCTC</Label>
                <select
                  className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                  value={finMetric}
                  onChange={(e) => setFinMetric(e.target.value as typeof finMetric)}
                >
                  <option value="">-- không dùng --</option>
                  {FINANCIAL_METRICS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label>Điều kiện</Label>
                <select
                  className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                  value={finOp}
                  onChange={(e) => setFinOp(e.target.value as ScreenerRequestBody["financial_op"])}
                >
                  <option value="">-- chọn --</option>
                  {OPS.map((op) => (
                    <option key={op.value} value={op.value}>
                      {op.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label>Giá trị (VND)</Label>
                <Input type="number" value={finValue} onChange={(e) => setFinValue(e.target.value)} placeholder="vd 1000000000000" />
              </div>
            </div>

            <Button onClick={runScreener} disabled={loading}>
              <Search className="mr-2 h-4 w-4" />
              {loading ? "Đang lọc (có thể mất 1-2 phút)..." : "Lọc cổ phiếu"}
            </Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </CardContent>
        </Card>

        {result && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Kết quả: {result.matched.length}/{result.universe_size} mã khớp
              </CardTitle>
            </CardHeader>
            <CardContent>
              {result.matched.length === 0 ? (
                <p className="text-sm text-muted-foreground">Không có mã nào khớp điều kiện.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Mã</TableHead>
                      {columns.map((c) => (
                        <TableHead key={c}>{c}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.matched.map((row) => (
                      <TableRow key={row.ticker as string}>
                        <TableCell className="font-medium">{row.ticker}</TableCell>
                        {columns.map((c) => (
                          <TableCell key={c}>{row[c] ?? "—"}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              {result.skipped.length > 0 && (
                <p className="mt-3 text-xs text-muted-foreground">
                  Bỏ qua (thiếu dữ liệu): {result.skipped.map((s) => `${s.ticker} (${s.reason})`).join(", ")}
                </p>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
