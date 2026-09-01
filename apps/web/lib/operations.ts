import { apiFetch } from "./api.ts";

export type OpStatus = 'pending' | 'in_progress' | 'completed' | 'submitted_for_approval' | 'approved' | 'rejected';
export type OpCategory = 'administrative' | 'financial' | 'human_resources';
export type OpPriority = 'low' | 'medium' | 'high' | 'urgent';
export type OpAction = 'start' | 'complete' | 'submit_for_approval' | 'approve' | 'reject';

export type OpSourceType = 'manual' | 'odoo' | 'recurring';

export type OperationActionStatus =
  | 'proposed'
  | 'awaiting_approval'
  | 'approved'
  | 'queued'
  | 'executing'
  | 'verifying'
  | 'succeeded'
  | 'failed';

export interface OperationProposal extends Record<string, unknown> {
  title?: string;
  summary?: string;
  note?: string;
  priority_reason?: string;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface TaskAction {
  id: string;
  status: OperationActionStatus;
  version: number;
  proposal: OperationProposal;
  proposal_hash: string;
  approved_hash: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  attempt_count: number;
  error: string | null;
  external_activity_id: number | null;
  verified_at: string | null;
}

export type CollectionMessageStatus =
  | 'draft'
  | 'awaiting_approval'
  | 'queued'
  | 'sending'
  | 'verifying'
  | 'succeeded'
  | 'failed';

export interface CollectionMessage {
  id: string;
  channel: 'odoo_customer_invoice_chatter';
  status: CollectionMessageStatus;
  version: number;
  draft_content: string;
  draft_version: number;
  draft_hash: string;
  /** Server-derived source snapshot identity; never synthesized by the browser. */
  source_hash: string;
  source_version: number;
  approved_content: string | null;
  approved_draft_version: number | null;
  approved_hash: string | null;
  approved_source_hash: string | null;
  approved_source_version: number | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  attempt_count: number;
  delivery_error: string | null;
  receipt_message_id: number | null;
  verified_at: string | null;
}

export interface ExactCollectionMessagePayload {
  expected_version: number;
  expected_message_version: number;
  expected_draft_version: number;
  expected_draft_hash: string;
  expected_source_hash: string;
  expected_source_version: number;
}

export interface ExactActionPayload {
  expected_version: number;
  expected_action_version: number;
  expected_proposal_hash: string;
}

export type DeliveryTone = 'neutral' | 'in_flight' | 'success' | 'error';

export interface DeliveryPresentation {
  state: string;
  labelKey: string;
  tone: DeliveryTone;
}

export function buildExactActionPayload(
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): ExactActionPayload {
  return {
    expected_version: expectedVersion,
    expected_action_version: expectedActionVersion,
    expected_proposal_hash: expectedProposalHash
  };
}

export function buildExactCollectionMessagePayload(
  expectedVersion: number,
  message: Pick<
    CollectionMessage,
    'version' | 'draft_version' | 'draft_hash' | 'source_hash' | 'source_version'
  >
): ExactCollectionMessagePayload {
  return {
    expected_version: expectedVersion,
    expected_message_version: message.version,
    expected_draft_version: message.draft_version,
    expected_draft_hash: message.draft_hash,
    expected_source_hash: message.source_hash,
    expected_source_version: message.source_version
  };
}

export function isActionDeliveryInFlight(action: TaskAction | null): boolean {
  return action ? ['queued', 'executing', 'verifying'].includes(action.status) : false;
}

export function getCollectionDeliveryPresentation(
  message: CollectionMessage
): DeliveryPresentation {
  if (message.status === 'queued') {
    return { state: message.status, labelKey: 'opDeliveryQueued', tone: 'in_flight' };
  }
  if (message.status === 'sending') {
    return { state: message.status, labelKey: 'opDeliverySending', tone: 'in_flight' };
  }
  if (message.status === 'verifying') {
    return { state: message.status, labelKey: 'opDeliveryVerifying', tone: 'in_flight' };
  }
  if (message.status === 'succeeded') {
    return { state: message.status, labelKey: 'opDeliverySucceeded', tone: 'success' };
  }
  if (message.status === 'failed') {
    return { state: message.status, labelKey: 'opDeliveryFailed', tone: 'error' };
  }
  return { state: message.status, labelKey: 'opDeliveryNotStarted', tone: 'neutral' };
}

export interface OperationTask {
  id: string;
  tenant_id: string;
  tenant_name: string;
  title: string;
  description: string | null;
  category: OpCategory;
  procedure_type: ProcedureType | null;
  request_data: Record<string, string> | null;
  priority: OpPriority;
  status: OpStatus;
  assigned_user_id: string | null;
  assignee_name: string | null;
  created_by_user_id: string;
  version: number;
  due_at: string | null;
  completed_at: string | null;
  submitted_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  updated_at: string;
  available_actions: OpAction[];

  source_type: OpSourceType;
  source_connection_id: string | null;
  source_record_id: number | null;
  source_signal: string | null;
  source_reference: string | null;
  source_snapshot: Record<string, unknown> | null;
  source_sync_state: string | null;
  source_synced_at: string | null;
  action: TaskAction | null;
  collection_message?: CollectionMessage | null;
}

export interface TasksSummary {
  [status: string]: number;
}

export interface TasksResponse {
  items: OperationTask[];
  total: number;
  summary: TasksSummary;
}

export interface TaskFilters {
  tenant_id?: string;
  status?: OpStatus | "";
  category?: OpCategory | "";
  priority?: OpPriority | "";
  source_type?: OpSourceType | "";
}

export interface CreateTaskPayload {
  tenant_id: string;
  title: string;
  description?: string;
  category: OpCategory;
  procedure_type?: ProcedureType;
  request_data?: Record<string, string>;
  priority: OpPriority;
  due_at?: string;
  assigned_user_id?: string;
}

export type ProcedureType =
  | 'review_journal_entry'
  | 'track_payment'
  | 'review_expenses'
  | 'follow_attendance'
  | 'review_leave'
  | 'prepare_payroll'
  | 'prepare_official_letter'
  | 'organize_contract'
  | 'update_association_record';

export interface CreateHrReviewTaskPayload {
  tenant_id: string;
  connection_id: string;
  resource:
    | 'employees_summary'
    | 'attendance_summary'
    | 'leaves_summary'
    | 'payroll_summary';
  record_id: number;
  employee_id?: number;
  date_from?: string;
  date_to?: string;
  priority: OpPriority;
  assigned_user_id?: string;
}
export function toTaskDueAt(date: string | undefined): string | undefined {
  if (!date) return undefined;
  if (!/^(?:20\d{2}|2100)-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/.test(date)) {
    throw new Error("INVALID_DUE_DATE");
  }

  const parsed = new Date(`${date}T12:00:00.000Z`);
  if (
    Number.isNaN(parsed.getTime())
    || parsed.toISOString().slice(0, 10) !== date
  ) {
    throw new Error("INVALID_DUE_DATE");
  }
  return parsed.toISOString();
}

export function buildOperationsUrl(filters: TaskFilters, limit = 200, offset = 0): string {
  const params = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString()
  });

  if (filters.tenant_id) params.append("tenant_id", filters.tenant_id);
  if (filters.status) params.append("status", filters.status);
  if (filters.category) params.append("category", filters.category);
  if (filters.priority) params.append("priority", filters.priority);
  if (filters.source_type) params.append("source_type", filters.source_type);

  return `/api/v1/operations/tasks?${params.toString()}`;
}

export interface BootstrapMember {
  id: string;
  full_name: string;
  email: string;
  role: string;
}

export interface BootstrapTenant {
  id: string;
  name: string;
  role: string;
  can_create: boolean;
  members: BootstrapMember[];
}

export interface OperationsBootstrap {
  tenants: BootstrapTenant[];
}

export type FinanceServiceKey =
  | "accounting_entries"
  | "journal_items"
  | "payments_summary"
  | "journals_summary"
  | "invoices"
  | "vendor_bills";

export interface OperationsCatalogService {
  key: FinanceServiceKey;
  label: string;
}

export interface OperationsCatalogModule {
  key: string;
  label: string;
  services: OperationsCatalogService[];
}

export interface OperationsCatalog {
  tenant_id: string;
  modules: OperationsCatalogModule[];
}

export type FinanceReadRecord = Record<string, unknown>;

/** The bounded Odoo page envelope returned by the finance read endpoint. */
export interface FinanceReadPage {
  resource: FinanceServiceKey;
  records: FinanceReadRecord[];
  limit: number;
  offset: number;
  returned_count: number;
  has_more: boolean;
  next_offset: number | null;
}

export interface FinanceReadPayload {
  tenant_id: string;
  service: FinanceServiceKey;
  limit: number;
  offset: number;
}

export type AutomationMode = "automatic" | "approval_required" | "manual";

export interface FinanceAssistantFinding {
  title: string;
  evidence: string;
  severity: "info" | "attention" | "risk";
}

export interface FinanceAutomationOpportunity {
  workflow_key:
    | "monitor_records"
    | "prepare_follow_up"
    | "prepare_invoice_activity"
    | "prepare_collection_draft"
    | "human_review";
  title: string;
  mode: AutomationMode;
  reason: string;
}

export interface FinanceAssistantResult {
  headline: string;
  summary: string;
  findings: FinanceAssistantFinding[];
  automation_opportunities: FinanceAutomationOpportunity[];
  next_step: string;
  confidence: number;
  service: FinanceServiceKey;
  locale: "ar" | "en";
  analyzed_count: number;
  prompt_version: string;
  prompt_sha256: string;
  model: string;
}

export interface FinanceSelectionState {
  tenant_id: string;
  module_key: string;
  service: FinanceServiceKey | "";
  page: FinanceReadPage | null;
}

export function buildOperationsCatalogUrl(tenantId: string): string {
  return `/api/v1/operations/catalog?${new URLSearchParams({ tenant_id: tenantId }).toString()}`;
}

export function buildFinanceReadPayload(
  tenantId: string,
  service: FinanceServiceKey,
  limit: number,
  offset: number,
): FinanceReadPayload {
  return { tenant_id: tenantId, service, limit, offset };
}

/** A new association invalidates every catalog-dependent choice and result. */
export function resetFinanceSelectionForTenant(tenantId: string): FinanceSelectionState {
  return { tenant_id: tenantId, module_key: "", service: "", page: null };
}

/** A new module invalidates the selected service and its previously read page. */
export function resetFinanceSelectionForModule(
  selection: FinanceSelectionState,
  moduleKey: string,
): FinanceSelectionState {
  return { ...selection, module_key: moduleKey, service: "", page: null };
}

export async function fetchOperationsBootstrap(): Promise<OperationsBootstrap> {
  return apiFetch<OperationsBootstrap>("/api/v1/operations/bootstrap");
}

export async function fetchOperationsCatalog(tenantId: string): Promise<OperationsCatalog> {
  return apiFetch<OperationsCatalog>(buildOperationsCatalogUrl(tenantId));
}

export async function readFinanceService(payload: FinanceReadPayload): Promise<FinanceReadPage> {
  return apiFetch<FinanceReadPage>("/api/v1/operations/finance/read", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function assistFinanceService(
  payload: FinanceReadPayload,
  locale: "ar" | "en",
): Promise<FinanceAssistantResult> {
  return apiFetch<FinanceAssistantResult>("/api/v1/operations/finance/assist", {
    method: "POST",
    body: JSON.stringify({ ...payload, locale }),
  });
}

export async function fetchTasks(filters: TaskFilters): Promise<TasksResponse> {
  return apiFetch<TasksResponse>(buildOperationsUrl(filters));
}

export async function createTask(payload: CreateTaskPayload): Promise<OperationTask> {
  return apiFetch<OperationTask>("/api/v1/operations/tasks", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createHrReviewTask(
  payload: CreateHrReviewTaskPayload
): Promise<OperationTask> {
  return apiFetch<OperationTask>("/api/v1/operations/hr-review-tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
export async function performTaskAction(
  id: string,
  action: OpAction,
  expectedVersion: number,
  note?: string
): Promise<OperationTask> {
  const endpoint = action.replace(/_/g, "-");
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/${endpoint}`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      note: note || undefined
    })
  });
}

export async function generateAction(id: string, expectedVersion: number): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/generate`, {
    method: "POST",
    body: JSON.stringify({ expected_version: expectedVersion })
  });
}

export async function submitAction(
  id: string,
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/submit`, {
    method: "POST",
    body: JSON.stringify(buildExactActionPayload(
      expectedVersion,
      expectedActionVersion,
      expectedProposalHash
    ))
  });
}

export async function approveAction(
  id: string,
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/approve`, {
    method: "POST",
    body: JSON.stringify(buildExactActionPayload(
      expectedVersion,
      expectedActionVersion,
      expectedProposalHash
    ))
  });
}

export async function rejectAction(
  id: string,
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/reject`, {
    method: "POST",
    body: JSON.stringify(buildExactActionPayload(
      expectedVersion,
      expectedActionVersion,
      expectedProposalHash
    ))
  });
}

export async function retryAction(
  id: string,
  expectedVersion: number,
  expectedActionVersion: number,
  expectedProposalHash: string
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/action/retry`, {
    method: "POST",
    body: JSON.stringify(buildExactActionPayload(
      expectedVersion,
      expectedActionVersion,
      expectedProposalHash
    ))
  });
}

export async function generateCollectionMessage(
  id: string,
  expectedVersion: number
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/collection-message/generate`, {
    method: "POST",
    body: JSON.stringify({ expected_version: expectedVersion })
  });
}

async function performExactCollectionMessageAction(
  id: string,
  endpoint: 'submit' | 'approve' | 'reject' | 'retry',
  expectedVersion: number,
  message: CollectionMessage
): Promise<OperationTask> {
  return apiFetch<OperationTask>(`/api/v1/operations/tasks/${id}/collection-message/${endpoint}`, {
    method: "POST",
    body: JSON.stringify(buildExactCollectionMessagePayload(expectedVersion, message))
  });
}

export function submitCollectionMessage(
  id: string,
  expectedVersion: number,
  message: CollectionMessage
): Promise<OperationTask> {
  return performExactCollectionMessageAction(id, 'submit', expectedVersion, message);
}

export function approveCollectionMessage(
  id: string,
  expectedVersion: number,
  message: CollectionMessage
): Promise<OperationTask> {
  return performExactCollectionMessageAction(id, 'approve', expectedVersion, message);
}

export function rejectCollectionMessage(
  id: string,
  expectedVersion: number,
  message: CollectionMessage
): Promise<OperationTask> {
  return performExactCollectionMessageAction(id, 'reject', expectedVersion, message);
}

export function retryCollectionMessage(
  id: string,
  expectedVersion: number,
  message: CollectionMessage
): Promise<OperationTask> {
  return performExactCollectionMessageAction(id, 'retry', expectedVersion, message);
}

export interface RecurringTemplate {
  id: string;
  tenant_id: string;
  title: string;
  description: string | null;
  category: string;
  priority: string;
  frequency: string;
  timezone: string;
  enabled: boolean;
}

export interface CreateRecurringTemplatePayload {
  tenant_id: string;
  title: string;
  description?: string;
  category: string;
  priority: string;
  frequency: string;
  timezone: string;
}

export async function fetchRecurringTemplates(): Promise<RecurringTemplate[]> {
  return apiFetch<RecurringTemplate[]>("/api/v1/operations/recurring-templates");
}

export async function createRecurringTemplate(payload: CreateRecurringTemplatePayload): Promise<RecurringTemplate> {
  return apiFetch<RecurringTemplate>("/api/v1/operations/recurring-templates", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function enableRecurringTemplate(id: string, enabled: boolean): Promise<RecurringTemplate> {
  return apiFetch<RecurringTemplate>(`/api/v1/operations/recurring-templates/${id}/enable?enabled=${enabled}`, {
    method: "POST"
  });
}

export async function syncOverdueInvoices(connectionId: string): Promise<{ created: number }> {
  return apiFetch<{ created: number }>(`/api/v1/connections/${connectionId}/sync-overdue-invoices`, {
    method: "POST"
  });
}

export type ServiceField = {
  key: string;
  labelKey: string;
  placeholderKey: string;
  required?: boolean;
  type?: 'text' | 'date' | 'textarea';
};

export type OdooRelation = [number, string] | null;

export interface FinancialFilter {
  field: string;
  operator: "=" | "!=" | "in" | "ilike" | ">=" | "<=";
  value: string | number | boolean | Array<string | number | boolean>;
}

export interface FinancialReadPage {
  resource: FinancialResource;
  records: FinancialRecord[];
  limit: number;
  offset: number;
  returned_count: number;
  has_more: boolean;
  next_offset: number | null;
  transport: string;
  source_name: string;
  source_company_id: number;
  read_at: string;
}

export interface FinancialRecord {
  id: number;
  name?: string | null;
  date?: string;
  ref?: string | null;
  journal_id?: OdooRelation;
  move_id?: OdooRelation;
  account_id?: OdooRelation;
  partner_id?: OdooRelation;
  currency_id?: OdooRelation;
  state?: "draft" | "posted" | "cancel";
  parent_state?: "draft" | "posted" | "cancel";
  amount_total_signed?: number;
  amount?: number;
  debit?: number;
  credit?: number;
  balance?: number;
  payment_type?: string;
  partner_type?: string;
}

export async function fetchFinancialConnections(): Promise<FinancialConnection[]> {
  return apiFetch<FinancialConnection[]>("/api/v1/connections");
}

export interface FinancialConnection {
  id: string;
  name: string;
  odoo_company_id: number | null;
  last_test_status: string | null;
  selected_transport: string | null;
  is_active: boolean;
}

export interface OdooEmployee {
  id: number;
  name: string;
}

interface OdooEmployeesPage {
  records: OdooEmployee[];
}

export async function fetchOdooEmployees(tenantId: string): Promise<OdooEmployee[]> {
  const page = await apiFetch<OdooEmployeesPage>(
    "/api/v1/operations/employees/read",
    {
      method: "POST",
      body: JSON.stringify({
        tenant_id: tenantId,
        limit: 50,
        offset: 0,
      }),
    },
  );
  return page.records;
}

export type FinancialResource = "journal_entries" | "journal_items" | "payments_summary";

export async function fetchFinancialPage(
  connectionId: string,
  request: {
    resource: FinancialResource;
    filters?: FinancialFilter[];
    limit?: number;
    offset?: number;
    order_by?: string;
    order_direction?: "asc" | "desc";
  }
): Promise<FinancialReadPage> {
  return apiFetch<FinancialReadPage>(
    `/api/v1/connections/${connectionId}/financial-read`,
    { method: "POST", body: JSON.stringify(request) }
  );
}

export type ServiceProcedure = {
  id: ProcedureType;
  titleKey: string;
  descriptionKey: string;
  fields: ServiceField[];
};

export const SERVICE_CATALOG: ServiceDefinition[] = [
  {
    id: 'financial',
    titleKey: 'serviceFinancial',
    descriptionKey: 'serviceFinancialDesc',
    accent: 'emerald',
    procedures: [
      {
        id: 'review_journal_entry',
        titleKey: 'serviceReviewJournal',
        descriptionKey: 'serviceReviewJournalDesc',
        fields: [
          { key: 'reference', labelKey: 'serviceReference', placeholderKey: 'serviceReferencePlaceholder', required: true },
          { key: 'period', labelKey: 'servicePeriod', placeholderKey: 'servicePeriodPlaceholder', required: true, type: 'date' },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
      {
        id: 'track_payment',
        titleKey: 'serviceTrackPayment',
        descriptionKey: 'serviceTrackPaymentDesc',
        fields: [
          { key: 'reference', labelKey: 'serviceReference', placeholderKey: 'serviceReferencePlaceholder', required: true },
          { key: 'amount', labelKey: 'serviceAmount', placeholderKey: 'serviceAmountPlaceholder' },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
      {
        id: 'review_expenses',
        titleKey: 'serviceReviewExpenses',
        descriptionKey: 'serviceReviewExpensesDesc',
        fields: [
          { key: 'period', labelKey: 'servicePeriod', placeholderKey: 'servicePeriodPlaceholder', required: true, type: 'date' },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
    ],
  },
  {
    id: 'human_resources',
    titleKey: 'serviceHumanResources',
    descriptionKey: 'serviceHumanResourcesDesc',
    accent: 'sky',
    procedures: [
      {
        id: 'follow_attendance',
        titleKey: 'serviceFollowAttendance',
        descriptionKey: 'serviceFollowAttendanceDesc',
        fields: [
          { key: 'period', labelKey: 'servicePeriod', placeholderKey: 'servicePeriodPlaceholder', required: true, type: 'date' },
          { key: 'employee', labelKey: 'serviceEmployee', placeholderKey: 'serviceEmployeePlaceholder', required: true },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
      {
        id: 'review_leave',
        titleKey: 'serviceReviewLeave',
        descriptionKey: 'serviceReviewLeaveDesc',
        fields: [
          { key: 'employee', labelKey: 'serviceEmployee', placeholderKey: 'serviceEmployeePlaceholder', required: true },
          { key: 'period', labelKey: 'servicePeriod', placeholderKey: 'servicePeriodPlaceholder', required: true, type: 'date' },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
      {
        id: 'prepare_payroll',
        titleKey: 'servicePreparePayroll',
        descriptionKey: 'servicePreparePayrollDesc',
        fields: [
          { key: 'period', labelKey: 'servicePeriod', placeholderKey: 'servicePeriodPlaceholder', required: true, type: 'date' },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
    ],
  },
  {
    id: 'administrative',
    titleKey: 'serviceAdministrative',
    descriptionKey: 'serviceAdministrativeDesc',
    accent: 'violet',
    procedures: [
      {
        id: 'prepare_official_letter',
        titleKey: 'serviceOfficialLetter',
        descriptionKey: 'serviceOfficialLetterDesc',
        fields: [
          { key: 'recipient', labelKey: 'serviceRecipient', placeholderKey: 'serviceRecipientPlaceholder', required: true },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
      {
        id: 'organize_contract',
        titleKey: 'serviceOrganizeContract',
        descriptionKey: 'serviceOrganizeContractDesc',
        fields: [
          { key: 'reference', labelKey: 'serviceReference', placeholderKey: 'serviceReferencePlaceholder', required: true },
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
      {
        id: 'update_association_record',
        titleKey: 'serviceUpdateAssociation',
        descriptionKey: 'serviceUpdateAssociationDesc',
        fields: [
          { key: 'details', labelKey: 'serviceDetails', placeholderKey: 'serviceDetailsPlaceholder', required: true, type: 'textarea' },
        ],
      },
    ],
  },
];

export type ServiceDefinition = {
  id: OpCategory;
  titleKey: string;
  descriptionKey: string;
  accent: string;
  procedures: ServiceProcedure[];
};
