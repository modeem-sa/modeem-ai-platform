"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  ServiceRequest,
  ServiceRequestStatus,
  RequestModule,
  RequestAssignee,
  fetchServiceRequests,
  fetchServiceRequest,
  fetchAllRequestModules,
  fetchRequestAssignees,
  addServiceRequestMessage,
  uploadServiceRequestAttachment,
  changeServiceRequestStatus,
  assignServiceRequest,
  classifyServiceRequest,
  dispatchServiceRequest,
  AgentSessionResponse,
  fetchAgentSession,
  startAgentSession,
  analyzeServiceRequest,
  sendAgentMessage,
  executeOverdueInvoiceTool,
  executeFinanceTool,
  FinanceToolKey,
} from "@/lib/service-requests";

export function useServiceRequests(tenantId: string | undefined, employeeInbox = false, includeAll = false) {
  const [requests, setRequests] = useState<ServiceRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const res = await fetchServiceRequests(tenantId, employeeInbox, includeAll);
      setRequests(res.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [tenantId, employeeInbox, includeAll]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000); // Polling every 30s
    return () => clearInterval(interval);
  }, [load]);

  return { requests, loading, error, reload: load };
}

export function useServiceRequest(requestId: string | undefined) {
  const [request, setRequest] = useState<ServiceRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const loadingRef = useRef(false);

  const load = useCallback(async () => {
    if (!requestId || loadingRef.current) return;
    loadingRef.current = true;
    try {
      const res = await fetchServiceRequest(requestId);
      setRequest(res);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, [requestId]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000); // Polling every 15s for details
    return () => clearInterval(interval);
  }, [load]);

  return { request, loading, error, reload: load };
}

export function useRequestModules(tenantId: string | undefined) {
  const [modules, setModules] = useState<RequestModule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const reload = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const records = await fetchAllRequestModules(tenantId);
      setModules(records.filter((record) => record.capabilities.accepts_requests));
      setError(null);
    } catch (err) {
      setModules([]);
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { modules, loading, error, reload };
}

export function useRequestAssignees(tenantId: string | undefined, enabled = true) {
  const [assignees, setAssignees] = useState<RequestAssignee[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!tenantId || !enabled) return;
    setLoading(true);
    fetchRequestAssignees(tenantId)
      .then((res) => setAssignees(res.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [tenantId, enabled]);

  return { assignees, loading };
}

export function useRequestWorkbench(requestId: string | undefined, locale: "ar" | "en", enabled = true) {
  const [workbench, setWorkbench] = useState<AgentSessionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const reload = useCallback(async () => {
    if (!requestId || !enabled) return;
    setLoading(true);
    try {
      setWorkbench(await fetchAgentSession(requestId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [requestId, enabled]);

  useEffect(() => { void reload(); }, [reload]);

  const run = useCallback(async (action: () => Promise<AgentSessionResponse>) => {
    setLoading(true);
    try {
      const result = await action();
      setWorkbench(result);
      setError(null);
      return result;
    } catch (err) {
      const next = err instanceof Error ? err : new Error(String(err));
      setError(next);
      throw next;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    workbench,
    loading,
    error,
    reload,
    start: () => run(() => startAgentSession(requestId!, locale)),
    analyze: () => run(() => analyzeServiceRequest(requestId!, locale)),
    send: (content: string) => run(() => sendAgentMessage(requestId!, content, locale)),
    runOverdueInvoices: (minimumDaysOverdue = 30) =>
      run(() => executeOverdueInvoiceTool(requestId!, locale, minimumDaysOverdue)),
    runFinanceTool: (toolKey: FinanceToolKey, input: Record<string, unknown> = {}) =>
      run(() => executeFinanceTool(requestId!, locale, toolKey, input)),
  };
}

// Simple mutation wrappers that handle throwing expected_version errors
export const useRequestMutations = (requestId: string, currentVersion: number, onComplete?: () => void) => {
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const handleMutation = async <T,>(mutationFn: () => Promise<T>) => {
    try {
      const res = await mutationFn();
      onCompleteRef.current?.();
      return res;
    } catch (err: unknown) {
      if (
        typeof err === "object" &&
        err !== null &&
        "status" in err &&
        err.status === 409
      ) {
        throw new Error("conflict");
      }
      throw err;
    }
  };

  return {
    sendMessage: (body: string) => handleMutation(() => addServiceRequestMessage(requestId, body)),
    uploadAttachment: (file: File) => handleMutation(() => uploadServiceRequestAttachment(requestId, file)),
    changeStatus: (status: ServiceRequestStatus) => handleMutation(() => changeServiceRequestStatus(requestId, status, currentVersion)),
    assign: (employeeId: string) => handleMutation(() => assignServiceRequest(requestId, employeeId, currentVersion)),
    classify: (moduleName: string) => handleMutation(() => classifyServiceRequest(requestId, moduleName, currentVersion)),
    dispatch: (workflowKey: string) => handleMutation(() => dispatchServiceRequest(requestId, workflowKey, currentVersion)),
  };
};
