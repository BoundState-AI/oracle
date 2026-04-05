"use client";

interface BoundStateLogoProps {
  variant?: "full" | "icon" | "wordmark";
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function BoundStateLogo({
  variant = "full",
  size = "sm",
  className = "",
}: BoundStateLogoProps) {
  const sizes = {
    sm: { icon: 38, text: "text-base", subtext: "text-[10px]" },
    md: { icon: 50, text: "text-lg", subtext: "text-xs" },
    lg: { icon: 75, text: "text-2xl", subtext: "text-sm" },
  };

  const s = sizes[size];

  const SignatureIcon = ({ iconSize }: { iconSize: number }) => {
    const strokeWidth = Math.max(3, iconSize / 12);
    const lineWidth = Math.max(2, iconSize / 16);

    return (
      <svg
        width={iconSize}
        height={iconSize}
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M 25 35 L 25 75 Q 25 80 30 80 L 70 80 Q 75 80 75 75 L 75 55 L 75 50 L 70 45 L 65 40"
          stroke="#60a5fa"
          strokeWidth={strokeWidth}
          strokeLinecap="square"
          fill="none"
        />
        <line
          x1="32"
          y1="70"
          x2="68"
          y2="70"
          stroke="#3b82f6"
          strokeWidth={lineWidth * 1.5}
        />
        <line
          x1="38"
          y1="58"
          x2="62"
          y2="58"
          stroke="#93c5fd"
          strokeWidth={lineWidth}
          opacity="0.7"
        />
      </svg>
    );
  };

  if (variant === "icon") {
    return (
      <div className={className}>
        <SignatureIcon iconSize={s.icon} />
      </div>
    );
  }

  if (variant === "wordmark") {
    return (
      <div className={`flex flex-col ${className}`}>
        <span
          className={`${s.text} font-bold text-foreground tracking-tight`}
        >
          BoundState
        </span>
      </div>
    );
  }

  return (
    <a
      href="https://www.boundstate.ai/"
      target="_blank"
      rel="noopener noreferrer"
      className={`flex items-center gap-0 hover:opacity-80 transition-opacity ${className}`}
    >
      <div className="relative -top-1 -mr-1">
        <SignatureIcon iconSize={s.icon} />
      </div>
      <span
        className={`${s.text} font-bold text-foreground tracking-tight`}
      >
        BoundState
      </span>
    </a>
  );
}
