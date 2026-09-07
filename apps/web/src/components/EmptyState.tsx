import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
}

export function EmptyState({ icon: Icon, title, description }: EmptyStateProps) {
  return (
    <section className="empty-state">
      <span className="empty-icon">
        <Icon size={26} />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}

