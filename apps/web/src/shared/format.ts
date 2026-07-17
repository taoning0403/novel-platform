export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

const defaultMaxUploadBytes = 100 * 1024 * 1024;
const configuredMaxUploadBytes = Number(import.meta.env.VITE_MAX_UPLOAD_BYTES);

export const maxUploadBytes = Number.isSafeInteger(configuredMaxUploadBytes)
  && configuredMaxUploadBytes > 0
  ? configuredMaxUploadBytes
  : defaultMaxUploadBytes;

export function formattedByteLimit(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${Number((bytes / 1024 / 1024).toFixed(1))} MiB`;
  }
  if (bytes >= 1024) {
    return `${Number((bytes / 1024).toFixed(1))} KiB`;
  }
  return `${bytes} bytes`;
}
