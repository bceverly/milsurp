import React from "react";
import { Check, Clock, Warning, X } from "./Icons.jsx";

/** Maps a scan status to its chip styling and icon. */
const SCAN_STATUS = {
  running: { tone: "info", label: "Running", Icon: Clock },
  success: { tone: "success", label: "Success", Icon: Check },
  partial: { tone: "warning", label: "Partial", Icon: Warning },
  failed: { tone: "danger", label: "Failed", Icon: X },
  canceled: { tone: "neutral", label: "Canceled", Icon: X },
};

export function ScanStatusChip({ status, size = 13 }) {
  const entry = SCAN_STATUS[status] || {
    tone: "neutral",
    label: status || "Unknown",
    Icon: Clock,
  };
  const { tone, label, Icon } = entry;
  return (
    <span className={`chip chip--${tone}`}>
      <Icon size={size} />
      {label}
    </span>
  );
}

const EMAIL_STATUS = {
  sent: { tone: "success", label: "Sent" },
  failed: { tone: "danger", label: "Failed" },
  skipped: { tone: "neutral", label: "Skipped" },
};

export function EmailStatusChip({ status }) {
  const { tone, label } = EMAIL_STATUS[status] || {
    tone: "neutral",
    label: status,
  };
  return <span className={`chip chip--${tone}`}>{label}</span>;
}
