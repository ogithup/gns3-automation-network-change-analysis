import { PropsWithChildren, ReactNode } from "react";

export function SectionCard(props: PropsWithChildren<{ title: string; actions?: ReactNode; subtitle?: string }>) {
  return (
    <section className="section-card">
      <header className="section-card__header">
        <div>
          <h2>{props.title}</h2>
          {props.subtitle ? <p>{props.subtitle}</p> : null}
        </div>
        {props.actions ? <div className="section-card__actions">{props.actions}</div> : null}
      </header>
      <div className="section-card__body">{props.children}</div>
    </section>
  );
}

export function MetricTile(props: { label: string; value: ReactNode; tone?: "default" | "accent" | "danger" | "success" }) {
  return (
    <article className={`metric-tile metric-tile--${props.tone ?? "default"}`}>
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </article>
  );
}

export function StatusPill(props: { value: string; tone?: "neutral" | "success" | "warning" | "danger" | "info" }) {
  return <span className={`status-pill status-pill--${props.tone ?? "neutral"}`}>{props.value}</span>;
}

export function EmptyState(props: { title: string; description: string }) {
  return (
    <div className="empty-state">
      <strong>{props.title}</strong>
      <p>{props.description}</p>
    </div>
  );
}

export function JsonPanel(props: { value: unknown }) {
  return (
    <pre className="json-panel">
      {JSON.stringify(props.value, null, 2)}
    </pre>
  );
}
