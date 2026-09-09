"use client";

import { ServiceRequestPriority, ServiceRequestStatus } from "@/lib/service-requests";

export function getPriorityLabel(priority: ServiceRequestPriority, t: (key: string) => string) {
  const map: Record<ServiceRequestPriority, string> = {
    low: t("reqPriorityLow"),
    medium: t("reqPriorityMedium"),
    high: t("reqPriorityHigh"),
    urgent: t("reqPriorityUrgent"),
  };
  return map[priority] || priority;
}

export function getPriorityColor(priority: ServiceRequestPriority) {
  const map: Record<ServiceRequestPriority, string> = {
    low: "text-slate-400 bg-slate-400/10 border-slate-400/20",
    medium: "text-blue-400 bg-blue-400/10 border-blue-400/20",
    high: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    urgent: "text-rose-400 bg-rose-400/10 border-rose-400/20",
  };
  return map[priority] || "text-slate-400 bg-slate-400/10 border-slate-400/20";
}

export function getStatusLabel(status: ServiceRequestStatus, t: (key: string) => string) {
  const map: Record<ServiceRequestStatus, string> = {
    open: t("reqStatusOpen"),
    in_progress: t("reqStatusInProgress"),
    waiting_customer: t("reqStatusWaitingCustomer"),
    resolved: t("reqStatusResolved"),
    closed: t("reqStatusClosed"),
  };
  return map[status] || status;
}

export function getStatusColor(status: ServiceRequestStatus) {
  const map: Record<ServiceRequestStatus, string> = {
    open: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    in_progress: "text-blue-400 bg-blue-400/10 border-blue-400/20",
    waiting_customer: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    resolved: "text-slate-300 bg-slate-300/10 border-slate-300/20",
    closed: "text-slate-500 bg-slate-500/10 border-slate-500/20",
  };
  return map[status] || "text-slate-400 bg-slate-400/10 border-slate-400/20";
}

export function formatDate(dateString: string, locale: string) {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateString));
}
