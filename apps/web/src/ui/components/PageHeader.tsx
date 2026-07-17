import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

interface PageHeaderProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  primaryAction?: ReactNode;
  secondaryActions?: ReactNode;
  compact?: boolean;
  className?: string;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  primaryAction,
  secondaryActions,
  compact = false,
  className = "",
}: PageHeaderProps) {
  const actions = primaryAction || secondaryActions;
  return (
    <header
      className={`${styles.header}${compact ? ` ${styles.compact}` : ""}${className ? ` ${className}` : ""}`}
    >
      <div className={styles.copy}>
        {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
        <h1 className={styles.title}>{title}</h1>
        {description ? <p className={styles.description}>{description}</p> : null}
      </div>
      {actions ? (
        <div className={styles.actions}>
          {secondaryActions}
          {primaryAction}
        </div>
      ) : null}
    </header>
  );
}
