import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Bell, AlertTriangle, Info, XCircle } from "lucide-react";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { DriftAlert, getAlerts, markAlertRead } from "../lib/api";

export default function AlertBell() {
  const [alerts, setAlerts] = useState<DriftAlert[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getAlerts(false, false).then(setAlerts).catch(() => {});
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const unread = alerts.filter((a) => !a.read).length;

  const handleMark = async (id: string) => {
    await markAlertRead(id);
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, read: true } : a)));
  };

  const severityIcon = (s: string) => {
    if (s === "critical") return <XCircle className="h-4 w-4 text-red-500 shrink-0" />;
    if (s === "warning") return <AlertTriangle className="h-4 w-4 text-yellow-500 shrink-0" />;
    return <Info className="h-4 w-4 text-blue-500 shrink-0" />;
  };

  return (
    <div ref={ref} className="relative">
      <Button variant="ghost" size="sm" className="relative" onClick={() => setOpen(!open)}>
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] rounded-full h-4 w-4 flex items-center justify-center">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-lg z-50 max-h-96 overflow-y-auto">
          <div className="p-3 border-b border-zinc-200 dark:border-zinc-700 font-medium text-sm">
            Alerts {unread > 0 && <Badge variant="secondary" className="ml-2">{unread} new</Badge>}
          </div>
          {alerts.length === 0 ? (
            <div className="p-4 text-center text-sm text-zinc-500">No alerts</div>
          ) : (
            alerts.slice(0, 20).map((alert) => (
              <div
                key={alert.id}
                className={`p-3 border-b border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer ${
                  !alert.read ? "bg-blue-50/50 dark:bg-blue-950/20" : ""
                }`}
                onClick={() => handleMark(alert.id)}
              >
                <div className="flex items-start gap-2">
                  {severityIcon(alert.severity)}
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{alert.message}</p>
                    <p className="text-xs text-zinc-500 mt-0.5">
                      {alert.repo_url.replace("https://github.com/", "")} &middot;{" "}
                      {new Date(alert.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
              </div>
            ))
          )}
          <Link
            href="/alerts"
            className="block p-2 text-center text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 border-t border-zinc-200 dark:border-zinc-700"
            onClick={() => setOpen(false)}
          >
            View all alerts &rarr;
          </Link>
        </div>
      )}
    </div>
  );
}
