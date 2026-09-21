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
  WorkbenchAction,
  WorkbenchCommunication,
  fetchWorkbenchCommunications,
  prepareWorkbenchCommunications,
  updateWorkbenchCommunication,
  submitWorkbenchCommunication,
  prepareWorkbenchAction,
  updateWorkbenchAction,
  submitWorkbenchAction,
  approveWorkbenchAction,
  rejectWorkbenchAction,
  queueWorkbenchAction,
  retryWorkbenchAction,
} from "@/lib/service-requests";
import { hasVerifiedExecutionSuccess } from "@/lib/workbench-presentation";

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
  const [communications, setCommunications] = useState<Record<string, WorkbenchCommunication[]>>({});
  const [communicationLoading, setCommunicationLoading] = useState(false);
  const [communicationError, setCommunicationError] = useState<Error | null>(null);
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

  const runAction = useCallback(async (operation: () => Promise<{ action: WorkbenchAction; session?: AgentSessionResponse }>) => {
    setLoading(true);
    try {
      const result = await operation();
      setWorkbench((current) => {
        const nextAction = result.action;
        if (!current) return result.session ?? current;
        return {
          ...current,
          ...(result.session ?? {}),
          actions: current.actions.some((item) => item.id === nextAction.id)
            ? current.actions.map((item) => item.id === nextAction.id ? nextAction : item)
            : [nextAction, ...current.actions],
        };
      });
      setError(null);
      return result.action;
    } catch (err) {
      const next = err instanceof Error ? err : new Error(String(err));
      setError(next);
      throw next;
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCommunications = useCallback(async (actionIds: string[]) => {
    if (!requestId || !enabled || !actionIds.length) return;
    setCommunicationLoading(true);
    try {
      const entries = await Promise.all(actionIds.map(async (actionId) => {
        const result = await fetchWorkbenchCommunications(requestId, actionId);
        return [actionId, result.messages] as const;
      }));
      setCommunications((current) => ({ ...current, ...Object.fromEntries(entries) }));
      setCommunicationError(null);
    } catch (err) {
      setCommunicationError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setCommunicationLoading(false);
    }
  }, [requestId, enabled]);

  const verifiedActionIds = (workbench?.actions ?? [])
    .filter(hasVerifiedExecutionSuccess)
    .map((action) => action.id)
    .join(",");

  useEffect(() => {
    const actionIds = verifiedActionIds ? verifiedActionIds.split(",") : [];
    if (!actionIds.length) return;
    void loadCommunications(actionIds);
    const interval = setInterval(() => void loadCommunications(actionIds), 15000);
    return () => clearInterval(interval);
  }, [loadCommunications, verifiedActionIds]);

  const runCommunication = useCallback(async (
    operation: () => Promise<{ message: WorkbenchCommunication }>,
  ) => {
    setCommunicationLoading(true);
    try {
      const result = await operation();
      setCommunications((current) => {
        const actionId = result.message.action_id;
        const previous = current[actionId] ?? [];
        return {
          ...current,
          [actionId]: previous.some((item) => item.id === result.message.id)
            ? previous.map((item) => item.id === result.message.id ? result.message : item)
            : [...previous, result.message],
        };
      });
      setCommunicationError(null);
      return result.message;
    } catch (err) {
      const next = err instanceof Error ? err : new Error(String(err));
      setCommunicationError(next);
      throw next;
    } finally {
      setCommunicationLoading(false);
    }
  }, []);

  const prepareCommunicationsForAction = useCallback(async (action: WorkbenchAction) => {
    if (!requestId) throw new Error("Request is unavailable");
    setCommunicationLoading(true);
    try {
      const result = await prepareWorkbenchCommunications(requestId, action.id, locale);
      setCommunications((current) => ({ ...current, [action.id]: result.messages }));
      setCommunicationError(null);
      return result.messages;
    } catch (err) {
      const next = err instanceof Error ? err : new Error(String(err));
      setCommunicationError(next);
      throw next;
    } finally {
      setCommunicationLoading(false);
    }
  }, [locale, requestId]);

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
    prepareAction: (sourceToolCallId: string) =>
      runAction(() => prepareWorkbenchAction(requestId!, sourceToolCallId, locale)),
    updateAction: (action: WorkbenchAction, fields: {
      draft_message: string; internal_note: string; followup_type: WorkbenchAction["proposal"]["followup_type"];
    }) => runAction(() => updateWorkbenchAction(requestId!, action.id, {
      expected_action_version: action.version,
      expected_proposal_hash: action.proposal_hash,
      ...fields,
    })),
    submitAction: (action: WorkbenchAction) =>
      runAction(() => submitWorkbenchAction(requestId!, action.id, action.version, action.proposal_hash)),
    approveAction: (action: WorkbenchAction) =>
      runAction(() => approveWorkbenchAction(requestId!, action.id, action.version, action.proposal_hash)),
    rejectAction: (action: WorkbenchAction, rejection_reason: string) =>
      runAction(() => rejectWorkbenchAction(requestId!, action.id, action.version, action.proposal_hash, rejection_reason)),
    queueAction: (action: WorkbenchAction) =>
      runAction(() => queueWorkbenchAction(requestId!, action.id, action.version, action.proposal_hash)),
    retryAction: (action: WorkbenchAction) =>
      runAction(() => retryWorkbenchAction(requestId!, action.id, action.version, action.proposal_hash)),
    communications,
    communicationLoading,
    communicationError,
    refreshCommunications: loadCommunications,
    prepareCommunications: prepareCommunicationsForAction,
    updateCommunication: (message: WorkbenchCommunication, content: string) =>
      runCommunication(() => updateWorkbenchCommunication(requestId!, message.id, {
        expected_message_version: message.version,
        expected_draft_version: message.draft_version,
        expected_draft_hash: message.draft_hash,
        expected_source_version: message.source_version,
        expected_source_hash: message.source_hash,
        content,
      })),
    submitCommunication: (message: WorkbenchCommunication) =>
      runCommunication(() => submitWorkbenchCommunication(requestId!, message.id, {
        expected_message_version: message.version,
        expected_draft_version: message.draft_version,
        expected_draft_hash: message.draft_hash,
        expected_source_version: message.source_version,
        expected_source_hash: message.source_hash,
      })),
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
