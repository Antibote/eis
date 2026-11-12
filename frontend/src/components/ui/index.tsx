import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-1.5 rounded font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-navy-500",
  {
    variants: {
      variant: {
        primary: "bg-navy-700 text-white hover:bg-navy-800",
        secondary: "border border-line bg-surface text-ink hover:bg-canvas",
        ghost: "text-ink-soft hover:bg-canvas hover:text-ink",
        danger: "border border-crit/30 bg-surface text-crit hover:bg-crit/5",
      },
      size: { sm: "h-7 px-2.5 text-xs", md: "h-8 px-3 text-sm", lg: "h-9 px-4 text-sm" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);
export function Button({ className, variant, size, loading, children, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button> & { loading?: boolean }) {
  return (
    <button className={cn(button({ variant, size }), className)} disabled={loading || p.disabled} {...p}>
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{children}
    </button>
  );
}

const badge = cva("inline-flex items-center gap-1 rounded px-1.5 py-px text-[11px] font-medium leading-4 whitespace-nowrap border", {
  variants: {
    tone: {
      neutral: "bg-canvas text-ink-soft border-line",
      navy: "bg-navy-50 text-navy-700 border-navy-100",
      crit: "bg-crit/5 text-crit border-crit/25",
      high: "bg-high/5 text-high border-high/25",
      med: "bg-med/5 text-med border-med/25",
      ok: "bg-ok/5 text-ok border-ok/25",
      dark: "bg-graphite-800 text-white border-graphite-800",
    },
  },
  defaultVariants: { tone: "neutral" },
});
export function Badge({ tone, className, ...p }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...p} />;
}

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-md border border-line bg-surface", className)} {...p} />;
}
export function CardHeader({ title, right, sub }: { title: ReactNode; right?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
      <div><div className="text-sm font-semibold">{title}</div>{sub && <div className="text-xs text-ink-faint">{sub}</div>}</div>
      {right}
    </div>
  );
}

export function Input({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("h-8 w-full rounded border border-line bg-surface px-2.5 text-sm placeholder:text-ink-faint focus:border-navy-500 focus:outline-none focus:ring-2 focus:ring-navy-500/15", className)} {...p} />;
}
export function Select({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn("h-8 w-full rounded border border-line bg-surface px-2 text-sm focus:border-navy-500 focus:outline-none", className)} {...p} />;
}

export function Spinner({ label }: { label?: string }) {
  return <div className="flex items-center gap-2 p-6 text-ink-faint"><Loader2 className="h-4 w-4 animate-spin" />{label ?? "Загрузка…"}</div>;
}
export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="rounded border border-crit/30 bg-crit/5 px-3 py-2 text-sm text-crit">{String((error as Error).message ?? error)}</div>;
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="max-w-md text-sm text-ink-faint">{children}</div>}
    </div>
  );
}
export function PageHeader({ title, sub, right }: { title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line bg-surface px-6 py-4">
      <div><h1 className="text-lg font-semibold tracking-tight">{title}</h1>{sub && <div className="mt-0.5 text-sm text-ink-soft">{sub}</div>}</div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

export const SEVERITY_TONE: Record<string, "crit" | "high" | "med" | "neutral"> = { critical: "crit", high: "high", medium: "med", low: "neutral" };
export const SEVERITY_RU: Record<string, string> = { critical: "критическая", high: "высокая", medium: "средняя", low: "низкая" };
export const CLASS_RU: Record<string, string> = { confirmed: "Подтверждённое влияние", direct: "Прямая зависимость", potential: "Потенциальное влияние", documentary: "Документальная связь" };
export const CLASS_TONE: Record<string, "crit" | "navy" | "med" | "neutral"> = { confirmed: "crit", direct: "navy", potential: "med", documentary: "neutral" };
export const STATUS_RU: Record<string, string> = { confirmed: "подтверждено", potential: "потенциальное", insufficient_data: "недостаточно данных" };

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <span className="inline-flex items-center gap-1.5 tabular text-xs text-ink-soft" title="Оценка достоверности вывода">
      <span className="relative h-1.5 w-10 overflow-hidden rounded-full bg-line"><span className="absolute inset-y-0 left-0 bg-navy-500" style={{ width: `${pct}%` }} /></span>
      {pct}%
    </span>
  );
}
