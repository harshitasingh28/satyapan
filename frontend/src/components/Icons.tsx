import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 20, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

/** Circle with a tick: GENUINE */
export function IconGenuine(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9.5" />
      <path d="M7.5 12.5l3 3 6-6.5" />
    </Svg>
  );
}

/** Octagon with a cross, the shape of a stop sign: FAKE */
export function IconFake(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8.1 2.5h7.8l5.6 5.6v7.8l-5.6 5.6H8.1l-5.6-5.6V8.1z" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </Svg>
  );
}

/** Dashed circle with a question mark, for an open question: UNVERIFIED */
export function IconUnverified(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9.5" strokeDasharray="3.2 2.6" />
      <path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .9-1 1.6v.4" />
      <path d="M12 17.2h.01" strokeWidth={2.6} />
    </Svg>
  );
}

export function VerdictIcon({ verdict, ...props }: IconProps & { verdict: string }) {
  if (verdict === "GENUINE") return <IconGenuine {...props} />;
  if (verdict === "FAKE") return <IconFake {...props} />;
  return <IconUnverified {...props} />;
}

export function IconSeal(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6.5" strokeWidth={1.4} />
      <path d="M9.4 12.2l1.8 1.8 3.6-3.9" />
    </Svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Svg>
  );
}

export function IconDash(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 12h12" />
    </Svg>
  );
}

export function IconAlert(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3.5l9.5 16.5h-19z" />
      <path d="M12 10v4.5M12 17.4h.01" />
    </Svg>
  );
}

export function IconExternal(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M14 4h6v6M20 4l-9 9" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </Svg>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" />
    </Svg>
  );
}

export function IconLink(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
    </Svg>
  );
}

export function IconImage(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="1.5" />
      <circle cx="9" cy="10" r="1.6" />
      <path d="M20.5 16l-5-5-8.5 8.5" />
    </Svg>
  );
}

export function IconVideo(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="6" width="13" height="12" rx="1.5" />
      <path d="M16 10.5l5-3v9l-5-3z" />
    </Svg>
  );
}

export function IconAudio(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2" />
    </Svg>
  );
}

export function MediaIcon({ kind, ...props }: IconProps & { kind: string }) {
  if (kind === "video") return <IconVideo {...props} />;
  if (kind === "audio") return <IconAudio {...props} />;
  return <IconImage {...props} />;
}

export function IconText(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 6h14M5 11h14M5 16h9" />
    </Svg>
  );
}
