import { Scale, Settings as SettingsIcon, Sun, type LucideIcon } from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  exact: boolean;
};

export const navItems: NavItem[] = [
  { to: "/", label: "Today", icon: Sun, exact: true },
  { to: "/weight", label: "Weight", icon: Scale, exact: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, exact: false },
];
