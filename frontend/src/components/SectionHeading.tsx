interface SectionHeadingProps {
  eyebrow: string;
  title: string;
  description: string;
}

export function SectionHeading({ eyebrow, title, description }: SectionHeadingProps) {
  return (
    <div className="space-y-3">
      <p className="font-mono text-xs uppercase tracking-[0.3em] text-signal/80">{eyebrow}</p>
      <div className="space-y-2">
        <h2 className="font-display text-3xl font-semibold text-white sm:text-4xl">{title}</h2>
        <p className="max-w-3xl text-sm leading-7 text-mist sm:text-base">{description}</p>
      </div>
    </div>
  );
}

