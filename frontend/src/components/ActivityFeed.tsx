import type { LiveEvent } from "../types";
import { formatEventTime } from "../lib/datetime";

interface ActivityFeedProps {
  events: LiveEvent[];
}

function formatEventLabel(eventType: string): string {
  return eventType.replaceAll(".", " ").replaceAll("_", " ");
}

export function ActivityFeed({ events }: ActivityFeedProps) {
  return (
    <div className="glass-panel h-full p-6">
      <div className="mb-6">
        <p className="text-xs uppercase tracking-[0.25em] text-mist">Realtime Bus</p>
        <h3 className="mt-2 font-display text-2xl text-white">Live event stream</h3>
      </div>

      <div className="space-y-3">
        {events.map((event, index) => (
          <article key={`${event.event_type}-${event.timestamp}-${index}`} className="rounded-3xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="font-display text-lg text-white capitalize">{formatEventLabel(event.event_type)}</p>
              <span className="font-mono text-xs text-mist">
                {formatEventTime(event.timestamp)}
              </span>
            </div>
            <p className="mt-2 font-mono text-xs leading-6 text-signal/90">
              {JSON.stringify(event.payload)}
            </p>
          </article>
        ))}
      </div>
    </div>
  );
}
