"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, CalendarDays, Database, Info, Play, RotateCcw, TrendingUp } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Score = {
  ticker: string;
  company: string;
  score: number;
  signal: "BUY" | "HOLD" | "AVOID";
  contract_growth: number;
  hiring_growth: number;
  award_size: number;
  sentiment_score: number;
  pipeline_count: number;
  pipeline_signal: number;
  pipeline_top_notice: string;
  pipeline_top_agency: string;
  pipeline_top_url: string;
  pipeline_top_deadline: string;
  total_awards: number;
  trigger_award: string;
  thesis: string;
  evidence: {
    title: string;
    url: string;
    snippet: string;
    source: string;
  }[];
};

type BacktestPoint = {
  date: string;
  portfolio: number;
  spy: number;
};

type SignalResponse = {
  cutoff_date: string;
  horizon_months: number;
  scores: Score[];
  selected_tickers: string[];
  backtest: {
    start_date: string;
    end_date: string;
    portfolio_return: number;
    spy_return: number;
    alpha?: number;
    series: BacktestPoint[];
    source: string;
  };
  visible_rows: {
    contracts: number;
    jobs: number;
  };
  discovery: {
    companies_found: number;
    companies_after_filter: number;
    source: string;
  };
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

const percent = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 1,
});

function asNumber(value: unknown, fallback = 0) {
  const numericValue = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numericValue) ? numericValue : fallback;
}

export default function Home() {
  const [cutoffDate, setCutoffDate] = useState("2022-01-01");
  const [horizonMonths, setHorizonMonths] = useState(12);
  const [data, setData] = useState<SignalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState(false);

  const loadingMessages = [
    "Fetching contract awards...",
    "Scoring companies...",
    "Generating sentiment signals...",
    "Building investment theses...",
    "Running backtest...",
  ];
  const [loadingMsg, setLoadingMsg] = useState(loadingMessages[0]);

  useEffect(() => {
    if (!loading) return;
    let i = 0;
    const interval = setInterval(() => {
      i = (i + 1) % loadingMessages.length;
      setLoadingMsg(loadingMessages[i]);
    }, 2000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  const runAnalysis = async () => {
    setLoading(true);
    setError("");
    setRevealed(false);
    try {
      const response = await fetch(`${API_BASE}/simulate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          cutoff_date: cutoffDate,
          horizon_months: horizonMonths,
          use_live_contracts: true,
        }),
      });
      if (!response.ok) {
        throw new Error("API request failed");
      }
      setData(await response.json());
    } catch {
      setError("Could not reach the FastAPI backend. Start it on port 8000 and try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runAnalysis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scores = useMemo(() => data?.scores ?? [], [data]);
  const chartScores = useMemo(() => data?.scores.slice(0, 8) ?? [], [data]);
  const alpha =
    data?.backtest.alpha ?? (data ? data.backtest.portfolio_return - data.backtest.spy_return : 0);

  return (
    <main className="min-h-screen px-4 py-5 sm:px-8 lg:px-10">
      <section className="mx-auto flex max-w-7xl flex-col gap-5">
        <header className="flex flex-col justify-between gap-4 border-b border-ink/15 pb-4 md:flex-row md:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-signal">
              <Activity size={18} />
              ContractAlpha
            </div>
            <h1 className="max-w-3xl text-3xl font-semibold tracking-normal text-ink sm:text-5xl">
              Contract recipients discovered first, scored before the market reveal.
            </h1>
          </div>
          <div className="grid gap-2 rounded-md border border-ink/15 bg-white/80 p-3 shadow-panel sm:grid-cols-[1fr_auto_auto]">
            <label className="flex min-w-48 items-center gap-2 rounded border border-ink/10 bg-paper px-3 py-2">
              <CalendarDays size={18} />
              <input
                aria-label="Cutoff date"
                className="w-full bg-transparent text-sm outline-none"
                max="2024-01-01"
                min="2010-01-01"
                type="date"
                value={cutoffDate}
                onChange={(event) => setCutoffDate(event.target.value)}
              />
            </label>
            <select
              aria-label="Backtest horizon"
              className="rounded border border-ink/10 bg-paper px-3 py-2 text-sm outline-none"
              value={horizonMonths}
              onChange={(event) => setHorizonMonths(Number(event.target.value))}
            >
              <option value={6}>6 months</option>
              <option value={12}>12 months</option>
              <option value={18}>18 months</option>
              <option value={24}>24 months</option>
            </select>
            <button
              className="inline-flex items-center justify-center gap-2 rounded bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-signal disabled:opacity-60"
              disabled={loading}
              onClick={runAnalysis}
            >
              {loading ? <RotateCcw className="animate-spin" size={17} /> : <Play size={17} />}
              {loading ? "Discovering..." : "Run"}
            </button>
          </div>
          {loading ? (
            <p className="mt-2 text-xs italic text-ink/50">{loadingMsg}</p>
          ) : null}
        </header>

        {error ? (
          <div className="rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        <section className="flex flex-col gap-4">
          <div className="rounded-md border border-ink/10 bg-white/85 p-4 shadow-panel">
            <div className="mb-4 flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">Agent scores</h2>
                <p className="text-sm text-ink/65">
                  {loading
                    ? "Discovering companies..."
                    : `${data?.horizon_months ?? horizonMonths}-month momentum through ${data?.cutoff_date ?? cutoffDate}`}
                </p>
              </div>
              <div className="flex items-center gap-2 rounded bg-paper px-3 py-2 text-sm text-ink/70">
                <Database size={16} />
                {data
                  ? `${data.discovery.companies_found} found, ${data.discovery.companies_after_filter} public`
                  : "Loading"}
              </div>
            </div>
            <div className="mb-4 flex flex-wrap items-start gap-2 rounded border border-ink/10 bg-paper/80 p-3 text-xs">
              <span className="mr-1 font-semibold text-ink/75">Signal legend:</span>
              <span className="rounded bg-signal/15 px-2 py-1 font-bold text-signal">BUY</span>
              <span className="text-ink/70">Score {">"} 0.35 - strong contract growth + hiring signals</span>
              <span className="rounded bg-caution/15 px-2 py-1 font-bold text-caution">HOLD</span>
              <span className="text-ink/70">Score 0.15–0.35 - moderate signals, watch closely</span>
              <span className="rounded bg-danger/15 px-2 py-1 font-bold text-danger">AVOID</span>
              <span className="text-ink/70">Score {"<"} 0.15 - weak or declining contract activity</span>
            </div>
            <div className="overflow-x-auto rounded border border-ink/10">
              <table className="w-full min-w-[1400px] border-collapse text-left text-sm">
                <thead className="bg-ink text-white">
                  <tr>
                    <th className="px-3 py-2">Ticker</th>
                    <th className="px-3 py-2">Company</th>
                    <th className="px-3 py-2">Signal</th>
                    <th className="px-3 py-2">Score</th>
                    <th className="px-3 py-2">Contracts</th>
                    <th className="px-3 py-2">Hiring</th>
                    <th className="px-3 py-2">Awards</th>
                    <th className="px-3 py-2">Pipeline</th>
                    <th className="px-3 py-2">Sentiment</th>
                    <th className="px-3 py-2">Trigger award</th>
                    <th className="px-3 py-2">Thesis</th>
                    <th className="px-3 py-2">Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && scores.length === 0
                    ? Array.from({ length: 5 }).map((_, i) => (
                        <tr key={i} className="border-t border-ink/10 bg-white animate-pulse">
                          {Array.from({ length: 12 }).map((_, j) => (
                            <td key={j} className="px-3 py-4">
                              <div className="h-3 rounded bg-ink/10" />
                            </td>
                          ))}
                        </tr>
                      ))
                    : null}
                  {scores.map((row) => (
                    <tr key={row.ticker} className="border-t border-ink/10 bg-white">
                      <td className="px-3 py-3 font-semibold">{row.ticker}</td>
                      <td className="max-w-44 px-3 py-3">{row.company}</td>
                      <td className="px-3 py-3">
                        <span
                          className={`rounded px-2 py-1 text-xs font-bold ${
                            row.signal === "BUY"
                              ? "bg-signal/15 text-signal"
                              : row.signal === "AVOID"
                                ? "bg-danger/15 text-danger"
                                : "bg-caution/15 text-caution"
                          }`}
                        >
                          {row.signal}
                        </span>
                      </td>
                      <td className="px-3 py-3">{asNumber(row.score).toFixed(3)}</td>
                      <td className="px-3 py-3">{percent.format(asNumber(row.contract_growth))}</td>
                      <td className="px-3 py-3">{percent.format(asNumber(row.hiring_growth))}</td>
                      <td className="px-3 py-3">{currency.format(asNumber(row.total_awards))}</td>
                      <td className="max-w-56 px-3 py-3 text-xs">
                        {asNumber(row.pipeline_count) > 0 ? (
                          <>
                            <div className="flex items-center gap-2">
                              <span className="rounded bg-signal/15 px-2 py-1 font-bold text-signal">
                                {asNumber(row.pipeline_count)} pending
                              </span>
                              {row.pipeline_top_agency ? (
                                <span className="text-ink/55">{row.pipeline_top_agency}</span>
                              ) : null}
                            </div>
                            {row.pipeline_top_notice ? (
                              <div className="mt-1 text-ink/65 leading-snug">
                                {row.pipeline_top_url ? (
                                  <a
                                    className="underline hover:text-signal"
                                    href={row.pipeline_top_url}
                                    rel="noreferrer"
                                    target="_blank"
                                    title={row.pipeline_top_notice}
                                  >
                                    {row.pipeline_top_notice.length > 80
                                      ? row.pipeline_top_notice.slice(0, 80) + "…"
                                      : row.pipeline_top_notice}
                                  </a>
                                ) : (
                                  row.pipeline_top_notice
                                )}
                              </div>
                            ) : null}
                            {row.pipeline_top_deadline ? (
                              <div className="mt-1 text-ink/45 text-[10px]">
                                deadline {row.pipeline_top_deadline}
                              </div>
                            ) : null}
                          </>
                        ) : (
                          <span className="text-ink/40 italic">No pending notices</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <span
                          className={`rounded px-2 py-1 text-xs font-semibold ${
                            asNumber(row.sentiment_score) > 0.2
                              ? "bg-signal/15 text-signal"
                              : asNumber(row.sentiment_score) < -0.2
                                ? "bg-danger/15 text-danger"
                                : "bg-ink/10 text-ink/60"
                          }`}
                        >
                          {asNumber(row.sentiment_score).toFixed(2)}
                        </span>
                      </td>
                      <td className="max-w-72 px-3 py-3 text-xs text-ink/75">{row.trigger_award}</td>
                      <td className="max-w-xs px-3 py-3 text-xs text-ink/60">
                        {(() => {
                          const thesisLines = (row.thesis || "")
                            .split("\n")
                            .map((l) => l.trim())
                            .filter((l) => l.startsWith("-"))
                            .map((l) => l.replace(/^-\s*/, ""))
                            .slice(0, 3);
                          return thesisLines.length > 0 ? (
                            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                              {thesisLines.map((line, i) => (
                                <li key={i} style={{ display: "flex", gap: "6px", fontSize: "11px", marginBottom: "4px", lineHeight: "1.4", color: "inherit" }}>
                                  <span style={{ color: "#1f8a70", flexShrink: 0 }}>•</span>
                                  <span>{line}</span>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <span style={{ fontSize: "11px", fontStyle: "italic" }}>
                              {row.thesis || "Generating..."}
                            </span>
                          );
                        })()}
                      </td>
                      <td className="max-w-72 px-3 py-3 text-xs">
                        {(row.evidence ?? []).map((ev, i) => (
                          <div key={i}>
                            {i > 0 && <div className="my-2 border-t border-ink/10" />}
                            {ev.url ? (
                              <a className="font-semibold text-signal underline" href={ev.url} rel="noreferrer" target="_blank">
                                {ev.title}
                              </a>
                            ) : (
                              <span className="font-semibold text-ink/75">{ev.title ?? "Evidence unavailable"}</span>
                            )}
                            {ev.snippet ? <div className="mt-1 text-ink/55">{ev.snippet}</div> : null}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </section>

        <section className="rounded-md border border-ink/10 bg-white/85 p-4 shadow-panel">
          <h2 className="mb-1 text-lg font-semibold">Signal composition</h2>
          <p className="mb-4 text-sm text-ink/65">Top discovered public recipients by score</p>
          <div className="w-full overflow-x-auto" style={{ height: 340 }}>
            {chartScores.length > 0 ? (
              <BarChart width={1100} height={320} data={chartScores}>
                <CartesianGrid stroke="#d8d7ce" strokeDasharray="3 3" />
                <XAxis dataKey="ticker" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="contract_growth" fill="#1f8a70" name="Contract growth" />
                <Bar dataKey="hiring_growth" fill="#d18a22" name="Hiring growth" />
                <Bar dataKey="award_size" fill="#587b7f" name="Award size" />
              </BarChart>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-ink/40">
                {loading ? "Loading chart..." : "No data yet — run a simulation."}
              </div>
            )}
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[0.75fr_1.25fr]">
          <div className="rounded-md border border-ink/10 bg-ink p-4 text-white shadow-panel">
            <div className="flex items-center gap-2 text-signal">
              <TrendingUp size={18} />
              Backtest reveal
            </div>
            <h2 className="mt-3 text-2xl font-semibold">
              Bought {data?.selected_tickers.join(", ") || "top ranked tickers"}
            </h2>
            <p className="mt-2 text-sm text-white/70">
              Equal dollar amount invested in each BUY-rated stock on {data?.cutoff_date ?? cutoffDate}, held through{" "}
              {data?.backtest.end_date ?? "horizon end"}. No rebalancing.
            </p>
            <button
              className="mt-5 w-full rounded bg-white px-4 py-3 text-sm font-bold text-ink transition hover:bg-signal hover:text-white"
              onClick={() => setRevealed(true)}
            >
              Reveal actual returns
            </button>
            {revealed && data ? (
              <div className="mt-5 grid grid-cols-3 gap-2 text-center">
                <Metric
                  label="Portfolio"
                  value={percent.format(data.backtest.portfolio_return)}
                  tooltip="Equal dollars in each BUY stock. Example: $10,000 total = $2,500 each in 4 BUY stocks."
                />
                <Metric label="SPY" value={percent.format(data.backtest.spy_return)} />
                <Metric label="Alpha" value={percent.format(alpha)} />
              </div>
            ) : (
              <div className="mt-5 rounded border border-white/15 bg-white/5 p-4 text-sm text-white/70">
                Scores are visible now. Returns stay hidden until the reveal.
              </div>
            )}
          </div>

          <div className="rounded-md border border-ink/10 bg-white/85 p-4 shadow-panel">
            <h2 className="mb-1 text-lg font-semibold">Performance path</h2>
            <p className="mb-4 text-sm text-ink/65">
              Source: {revealed && data ? data.backtest.source : "hidden until reveal"}
            </p>
            <div className="w-full overflow-x-auto" style={{ height: 400 }}>
              {(() => {
                const seriesData = revealed
                  ? (data?.backtest.series ?? []).filter(
                      (p) => p.portfolio > 0 && p.spy > 0 && p.portfolio < 10000 && p.spy < 10000,
                    )
                  : [];
                if (seriesData.length === 0) {
                  return (
                    <div className="flex h-full items-center justify-center text-sm text-ink/40">
                      {revealed ? "No backtest data available." : "Click \"Reveal actual returns\" to see the path."}
                    </div>
                  );
                }
                return (
                  <AreaChart width={700} height={380} data={seriesData}>
                    <CartesianGrid stroke="#d8d7ce" strokeDasharray="3 3" />
                    <XAxis dataKey="date" minTickGap={24} />
                    <YAxis domain={["dataMin - 5", "dataMax + 5"]} />
                    <Tooltip />
                    <Area dataKey="portfolio" fill="#1f8a70" fillOpacity={0.2} stroke="#1f8a70" name="Portfolio" />
                    <Area dataKey="spy" fill="#587b7f" fillOpacity={0.18} stroke="#587b7f" name="SPY" />
                  </AreaChart>
                );
              })()}
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value, tooltip }: { label: string; value: string; tooltip?: string }) {
  return (
    <div className="rounded border border-white/15 bg-white/10 px-2 py-3">
      <div className="flex items-center justify-center gap-1 text-xs uppercase text-white/55">
        <span>{label}</span>
        {tooltip ? <Info size={12} className="text-white/70" title={tooltip} /> : null}
      </div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
