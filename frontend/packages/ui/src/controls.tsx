import type { ReactNode } from "react";

export interface ButtonProps {
  children?: ReactNode;
  onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void;
  variant?: "default" | "primary" | "danger";
  size?: "md" | "sm";
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
  title?: string;
  ariaLabel?: string;
  style?: React.CSSProperties;
}

export function Button({
  children, onClick, variant = "default", size = "md", type = "button",
  disabled, className, title, ariaLabel, style,
}: ButtonProps) {
  const classes = [variant === "default" ? "btn" : `btn ${variant}`,
    size === "sm" ? "sm" : "", className].filter(Boolean).join(" ");
  return (
    <button type={type} className={classes} onClick={onClick} disabled={disabled}
      title={title} aria-label={ariaLabel} style={style}>
      {children}
    </button>
  );
}

import type { IconName } from "./icons";
import { Icon } from "./icons";

export interface IconButtonProps {
  name: IconName;
  label: string;
  onClick?: () => void;
  size?: number;
  className?: string;
}

export function IconButton({ name, label, onClick, size, className }: IconButtonProps) {
  return (
    <button type="button" className={className ? `icon-btn ${className}` : "icon-btn"}
      aria-label={label} title={label} onClick={onClick}>
      <Icon name={name} size={size} />
    </button>
  );
}
