import {
  Sun,
  Activity,
  Sparkles,
  Plug,
  NotebookPen,
  Settings as SettingsIcon,
} from "lucide-react";

export const navItems = [
  { to: "/", label: "Today", icon: Sun, exact: true },
  { to: "/timeline", label: "Timeline", icon: Activity },
  { to: "/insights", label: "Insights", icon: Sparkles },
  { to: "/integrations", label: "Sources", icon: Plug },
  { to: "/journal", label: "Journal", icon: NotebookPen },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
] as const;
