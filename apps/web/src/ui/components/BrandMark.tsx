import styles from "./BrandMark.module.css";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={`${styles.mark}${compact ? ` ${styles.compact}` : ""}`}
      aria-hidden="true"
    >
      <i />
      <i />
      <i />
    </span>
  );
}
