import type { ReactNode, SVGProps } from "react";

export type InterfaceIconName =
  | "library"
  | "series"
  | "upload"
  | "manage"
  | "readers"
  | "security"
  | "site"
  | "audit"
  | "profile"
  | "devices"
  | "sessions"
  | "status"
  | "more";

const paths: Record<InterfaceIconName, ReactNode> = {
  library: <><path d="M4.5 5.5A2.5 2.5 0 0 1 7 3h12.5v15H7a2.5 2.5 0 0 0-2.5 2.5z" /><path d="M7 18a2.5 2.5 0 0 0 0 5h12.5v-5" /><path d="M8.5 7.5h7" /></>,
  series: <><path d="m4 8 8-4 8 4-8 4z" /><path d="m4 12 8 4 8-4" /><path d="m4 16 8 4 8-4" /></>,
  upload: <><path d="M12 16V4" /><path d="m7.5 8.5 4.5-4.5 4.5 4.5" /><path d="M4 14v6h16v-6" /></>,
  manage: <><path d="M4 5h16v14H4z" /><path d="M8 5V3h8v2" /><path d="M4 10h16" /><path d="M10 14h4" /></>,
  readers: <><circle cx="9" cy="8" r="3" /><path d="M3.5 20a5.5 5.5 0 0 1 11 0" /><circle cx="17" cy="9" r="2.25" /><path d="M15.5 14.5A4.5 4.5 0 0 1 21 19" /></>,
  security: <><path d="M12 3 19 6v5c0 4.6-2.8 8.2-7 10-4.2-1.8-7-5.4-7-10V6z" /><path d="m9 12 2 2 4-5" /></>,
  site: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3c2.2 2.4 3.3 5.4 3.3 9S14.2 18.6 12 21c-2.2-2.4-3.3-5.4-3.3-9S9.8 5.4 12 3" /></>,
  audit: <><path d="M6 4h12v16H6z" /><path d="M9 8h6M9 12h6M9 16h4" /></>,
  profile: <><circle cx="12" cy="8" r="4" /><path d="M4.5 21a7.5 7.5 0 0 1 15 0" /></>,
  devices: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 17h6" /></>,
  sessions: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>,
  status: <><path d="M3 12h4l2-5 4 10 2-5h6" /></>,
  more: <><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" /></>,
};

export function InterfaceIcon({
  name,
  ...props
}: { name: InterfaceIconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
