import {
  Sun,
  Activity,
  Sparkles,
  Plug,
  NotebookPen,
  Scale,
  Settings as SettingsIcon,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  exact: boolean;
};

export const navItems: NavItem[] = [
  { to: "/", label: "Today", icon: Sun, exact: true },
  { to: "/timeline", label: "Timeline", icon: Activity, exact: false },
  { to: "/insights", label: "Insights", icon: Sparkles, exact: false },
  { to: "/integrations", label: "Sources", icon: Plug, exact: false },
  { to: "/journal", label: "Journal", icon: NotebookPen, exact: false },
  { to: "/weight", label: "Weight", icon: Scale, exact: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, exact: false },
];
