export type Message = { role: "user" | "assistant"; content: string };

export type UIField = {
  id: string;
  label: string;
  type: "text" | "textarea" | "select" | "number" | "date" | "email";
  required: boolean;
  placeholder?: string | null;
  description?: string | null;
  options?: string[];
};

export type UISuggestion = {
  id: string;
  label: string;
  description?: string | null;
};

export type UIForm = {
  title: string;
  description?: string | null;
  submit_label: string;
  fields: UIField[];
  suggestions?: UISuggestion[];
};

export type CMResponse = {
  status: "complete" | "needs_information" | "out_of_scope";
  document?: string | null;
  ui?: UIForm | null;
  document_type?: string | null;
  document_action?: "revise_active_document" | "create_new_document" | null;
  redirect_message?: string | null;
};

export function isRevisionRequest(currentDocument: string | null): boolean {
  return Boolean(currentDocument);
}

export function buildDocumentRequest(params: {
  requestText: string;
  originalRequest?: string;
  currentDocument: string | null;
  activeDocumentType: string | null;
  latestCorrection: string | null;
  isRevision: boolean;
  messages: Message[];
}) {
  return {
    original_request:
      params.isRevision && params.originalRequest
        ? params.originalRequest
        : params.requestText,
    current_document: params.currentDocument,
    active_document_type: params.activeDocumentType,
    latest_correction: params.isRevision ? params.requestText : params.latestCorrection,
    conversation_messages: params.messages.slice(-10),
  };
}

export function buildFormSubmitRequest(params: {
  originalRequest: string;
  formData: Record<string, string>;
  currentDocument: string | null;
  activeDocumentType: string | null;
  latestCorrection: string | null;
  messages: Message[];
}) {
  return {
    original_request: params.originalRequest,
    provided_fields: params.formData,
    current_document: params.currentDocument,
    active_document_type: params.activeDocumentType,
    latest_correction: params.latestCorrection,
    conversation_messages: params.messages.slice(-10),
  };
}

export function formatFormDataAsMessage(formData: Record<string, string>): string {
  const summary = Object.entries(formData)
    .filter((entry) => entry[1].trim() !== "")
    .map(([k, v]) => `${k}: ${v}`)
    .join(", ");
  
  return summary ? `Provided info: ${summary}` : "Provided info: (empty)";
}
