export function formatKRW(amount: number): string {
  return new Intl.NumberFormat("ko-KR", {
    style: "currency",
    currency: "KRW",
    maximumFractionDigits: 0,
  }).format(amount)
}

export function formatUSD(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount)
}

export function formatCurrency(amount: number, currency: string): string {
  return currency === "USD" ? formatUSD(amount) : formatKRW(amount)
}

export function abbreviateAmount(amount: number): string {
  const abs = Math.abs(amount)
  if (abs >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(1)}B`
  if (abs >= 1_000_000) return `${(amount / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${(amount / 1_000).toFixed(1)}K`
  return amount.toString()
}
