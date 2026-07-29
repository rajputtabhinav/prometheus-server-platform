interface StatCardProps {
  label: string;
  value: string;
  detail: string;
  tone?: "signal" | "ember" | "danger";
}

const toneClasses = {
  signal: "border-signal/30 bg-signal/8",
  ember: "border-ember/30 bg-ember/8",
  danger: "border-danger/30 bg-danger/8"
};

export function StatCard({ label, value, detail, tone = "signal" }: StatCardProps) {
  return (
    <article className={`glass-panel border ${toneClasses[tone]} p-5`}>
      <p className="text-xs uppercase tracking-[0.25em] text-mist">{label}</p>
      <div className="mt-4 flex items-end justify-between gap-4">
        <p className="font-display text-4xl font-semibold text-white">{value}</p>
        <p className="max-w-[12rem] text-right text-xs leading-6 text-mist">{detail}</p>
      </div>
    </article>
  );
}

