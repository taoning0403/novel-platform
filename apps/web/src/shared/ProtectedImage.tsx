import { type ReactNode, useEffect, useState } from "react";

import { api } from "../api/client";

interface ProtectedImageProps {
  path: string | null | undefined;
  alt: string;
  className?: string;
  fallback?: ReactNode;
}

export function ProtectedImage({
  path,
  alt,
  className,
  fallback = <span aria-hidden="true">书</span>,
}: ProtectedImageProps) {
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setSource(null);
    if (!path) return () => undefined;
    void api.fetchProtectedFile(path).then((blob) => {
      if (!active) return;
      objectUrl = URL.createObjectURL(blob);
      setSource(objectUrl);
    }).catch(() => {
      if (active) setSource(null);
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (!source) {
    return <span className={className}>{fallback}</span>;
  }
  return <img className={className} src={source} alt={alt} />;
}
