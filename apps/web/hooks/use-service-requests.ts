"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  ServiceRequest,
  ServiceRequestStatus,
  RequestModule,
  RequestAssignee,
  fetchServiceRequests,
  fetchServiceRequest,
  fetchRequestModules,
  fetchRequestAssignees,
  addServiceRequestMessage,
  uploadServiceRequestAttachment,
  changeServiceRequestStatus,
  assignServiceRequest,
  classifyServiceRequest,
  dispatchServiceRequest,
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

  useEffect(() => {
    if (!tenantId) return;
    setLoading(true);
    fetchRequestModules(tenantId)
      .then((res) => setModules(res.records))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [tenantId]);

  return { modules, loading };
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
