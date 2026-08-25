"use client";

import { useState } from "react";
import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";
import { apiFetch } from "@/lib/api";
import { 
  type Message, type UIForm, type CMResponse,
  buildDocumentRequest, buildFormSubmitRequest, formatFormDataAsMessage,
  isRevisionRequest,
} from "@/lib/content-manager-utils";

export default function ContentManagerPage() {
  const { t } = useLocale();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // State
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentDocument, setCurrentDocument] = useState<string | null>(null);
  const [activeDocumentType, setActiveDocumentType] = useState<string | null>(null);
  const [latestCorrection, setLatestCorrection] = useState<string | null>(null);
  const [originalRequest, setOriginalRequest] = useState("");
  const [uiForm, setUiForm] = useState<UIForm | null>(null);
  const [outOfScopeMessage, setOutOfScopeMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Inputs
  const [requestInput, setRequestInput] = useState("");
  const [formData, setFormData] = useState<Record<string, string>>({});

  const clearState = () => {
    setMessages([]);
    setCurrentDocument(null);
    setActiveDocumentType(null);
    setLatestCorrection(null);
    setOriginalRequest("");
    setUiForm(null);
    setOutOfScopeMessage(null);
    setRequestInput("");
    setFormData({});
    setError(null);
  };

  const submitRequest = async (overrideRequest?: string, isRevision: boolean = false) => {
    const reqText = overrideRequest ?? requestInput.trim();
    if (!reqText && !isRevision) return;

    setLoading(true);
    setError(null);
    setOutOfScopeMessage(null);

    const newMessages = [...messages, { role: "user" as const, content: reqText }];
    if (!isRevision) {
      setOriginalRequest(reqText);
      setMessages(newMessages);
    }

    try {
      const payload = buildDocumentRequest({
        requestText: reqText,
        originalRequest,
        currentDocument,
        activeDocumentType,
        latestCorrection,
        isRevision,
        messages,
      });

      const data = await apiFetch<CMResponse>("/api/v1/agents/content-manager/documents", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (data.status === "complete") {
        setCurrentDocument(data.document || null);
        setActiveDocumentType(data.document_type || activeDocumentType);
        setUiForm(null);
        if (data.document_action === "create_new_document") {
          setLatestCorrection(null);
        } else if (isRevision) {
          setLatestCorrection(reqText);
        }
        setMessages([...newMessages, { role: "assistant" as const, content: t("cmGeneratedMessage") }]);
      } else if (data.status === "needs_information") {
        setUiForm(data.ui || null);
        setMessages([...newMessages, { role: "assistant" as const, content: t("cmNeedsInfo") }]);
      } else if (data.status === "out_of_scope") {
        setOutOfScopeMessage(data.redirect_message || t("cmOutOfScope"));
        setMessages([...newMessages, { role: "assistant" as const, content: data.redirect_message || t("cmOutOfScope") }]);
      }
      if (!isRevision) setRequestInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("cmError"));
    } finally {
      setLoading(false);
    }
  };

  const submitForm = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    // format provided fields as requested
    const formattedFields = { ...formData };
    
    const summaryMsg = formatFormDataAsMessage(formattedFields);
    
    const newMessages = [...messages, { role: "user" as const, content: summaryMsg }];
    setMessages(newMessages);

    try {
      const payload = buildFormSubmitRequest({
        originalRequest,
        formData: formattedFields,
        currentDocument,
        activeDocumentType,
        latestCorrection,
        messages,
      });

      const data = await apiFetch<CMResponse>("/api/v1/agents/content-manager/documents", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (data.status === "complete") {
        setCurrentDocument(data.document || null);
        setActiveDocumentType(data.document_type || activeDocumentType);
        setUiForm(null);
        setFormData({});
        setMessages([...newMessages, { role: "assistant" as const, content: t("cmGeneratedMessage") }]);
      } else if (data.status === "needs_information") {
        setUiForm(data.ui || null);
        setMessages([...newMessages, { role: "assistant" as const, content: t("cmNeedsInfo") }]);
      } else if (data.status === "out_of_scope") {
        setOutOfScopeMessage(data.redirect_message || t("cmOutOfScope"));
        setMessages([...newMessages, { role: "assistant" as const, content: data.redirect_message || t("cmOutOfScope") }]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("cmError"));
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (currentDocument) {
      try {
        await navigator.clipboard.writeText(currentDocument);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        setError(t("cmCopyFailed"));
      }
    }
  };

  const samples = [
    { label: t("cmSample1"), value: t("cmSample1") },
    { label: t("cmSample2"), value: t("cmSample2") },
    { label: t("cmSample3"), value: t("cmSample3") },
  ];

  const handleFieldChange = (id: string, value: string) => {
    setFormData(prev => ({ ...prev, [id]: value }));
  };

  // Determine what to show
  const isInitial = !currentDocument && !uiForm && !outOfScopeMessage && messages.length === 0;

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-slate-950 text-slate-200">
      <Header titleKey="cmTitle" />
      
      <main className="flex-1 flex flex-col md:flex-row min-h-0 overflow-hidden relative">
        {/* Left Column - Interaction */}
        <div className="w-full md:w-[450px] lg:w-[500px] border-e border-slate-800 bg-slate-900/40 flex flex-col overflow-hidden shrink-0">
          <div className="p-6 border-b border-slate-800/60 shrink-0">
            <h2 className="text-lg font-medium text-emerald-400 mb-2">{t("cmTitle")}</h2>
            <p className="text-sm text-slate-400 leading-relaxed">{t("cmDescription")}</p>
          </div>

          <div className="flex-1 overflow-y-auto p-6 flex flex-col">
            {isInitial && (
              <div className="flex-1 flex flex-col justify-center">
                <div className="mb-8">
                  <h3 className="text-xl font-medium text-white mb-3">{t("cmEmptyTitle")}</h3>
                  <p className="text-slate-400 text-sm">{t("cmEmptyDesc")}</p>
                </div>
                
                <div className="flex flex-col gap-3">
                  {samples.map((sample, i) => (
                    <button
                      key={i}
                      onClick={() => {
                        setRequestInput(sample.value);
                        submitRequest(sample.value);
                      }}
                      disabled={loading}
                      className="text-start p-4 rounded-xl border border-slate-800 bg-slate-900/50 hover:bg-emerald-900/20 hover:border-emerald-800/50 transition-all text-sm group"
                    >
                      <span className="text-emerald-400/80 group-hover:text-emerald-400 block mb-1">↑</span>
                      {sample.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {!isInitial && !uiForm && !outOfScopeMessage && (
              <div className="flex-1 flex flex-col gap-6 justify-end pb-4">
                <div className="space-y-4">
                  {messages.filter(m => m.role === "user").map((msg, i) => (
                    <div key={i} className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 text-sm text-slate-300 w-fit ms-auto max-w-[85%]">
                      {msg.content}
                    </div>
                  ))}
                  {loading && (
                    <div className="bg-emerald-950/20 border border-emerald-900/30 rounded-xl p-4 text-sm text-emerald-300/70 w-fit max-w-[85%] flex items-center gap-3">
                      <div className="w-3 h-3 border-2 border-emerald-500/50 border-t-transparent rounded-full animate-spin" />
                      {t("cmSending")}
                    </div>
                  )}
                </div>
              </div>
            )}

            {uiForm && (
              <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 mb-6">
                <div className="bg-emerald-950/20 border border-emerald-900/40 rounded-xl p-6">
                  <h3 className="text-lg font-medium text-emerald-400 mb-2">{uiForm.title}</h3>
                  {uiForm.description && (
                    <p className="text-sm text-slate-400 mb-6">{uiForm.description}</p>
                  )}
                  
                  <form onSubmit={submitForm} className="space-y-5">
                    {uiForm.fields.map(field => (
                      <div key={field.id} className="space-y-2">
                        <label htmlFor={field.id} className="block text-sm font-medium text-slate-300">
                          {field.label} {field.required && <span className="text-rose-400">*</span>}
                        </label>
                        {field.description && (
                          <p className="text-xs text-slate-500">{field.description}</p>
                        )}
                        
                        {field.type === "textarea" ? (
                          <textarea
                            id={field.id}
                            required={field.required}
                            placeholder={field.placeholder || ""}
                            value={formData[field.id] || ""}
                            onChange={(e) => handleFieldChange(field.id, e.target.value)}
                            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 min-h-[100px] resize-y"
                          />
                        ) : field.type === "select" && field.options ? (
                          <select
                            id={field.id}
                            required={field.required}
                            value={formData[field.id] || ""}
                            onChange={(e) => handleFieldChange(field.id, e.target.value)}
                            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                          >
                            <option value="" disabled>{field.placeholder || "Select..."}</option>
                            {field.options.map(opt => (
                              <option key={opt} value={opt}>{opt}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            type={["number", "date", "email"].includes(field.type) ? field.type : "text"}
                            id={field.id}
                            required={field.required}
                            placeholder={field.placeholder || ""}
                            value={formData[field.id] || ""}
                            onChange={(e) => handleFieldChange(field.id, e.target.value)}
                            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                          />
                        )}
                      </div>
                    ))}

                    <button
                      type="submit"
                      disabled={loading}
                      className="w-full mt-6 rounded-md bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 focus:ring-offset-slate-950 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {loading ? t("cmSending") : uiForm.submit_label || t("cmSubmit")}
                    </button>
                  </form>
                  
                  {uiForm.suggestions && uiForm.suggestions.length > 0 && (
                    <div className="mt-8 border-t border-emerald-900/40 pt-6">
                      <p className="text-xs text-slate-400 mb-3">{t("cmEmptyDesc")}</p>
                      <div className="flex flex-col gap-2">
                        {uiForm.suggestions.map(s => (
                          <button
                            key={s.id}
                            onClick={() => {
                              setRequestInput(s.label);
                              submitRequest(s.label);
                            }}
                            disabled={loading}
                            className="text-start p-3 rounded-lg border border-emerald-900/30 bg-emerald-950/30 hover:bg-emerald-900/40 transition-colors text-sm text-emerald-300/90 hover:text-emerald-300"
                          >
                            <span className="block font-medium mb-0.5">{s.label}</span>
                            {s.description && <span className="text-xs text-emerald-300/60">{s.description}</span>}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {outOfScopeMessage && (
              <div className="mt-auto bg-amber-950/20 border border-amber-900/40 rounded-xl p-5 mb-4">
                <h3 className="text-sm font-medium text-amber-400 mb-2">{t("cmOutOfScope")}</h3>
                <p className="text-sm text-slate-300">{outOfScopeMessage}</p>
                <button
                  onClick={clearState}
                  className="mt-4 text-xs text-amber-400/80 hover:text-amber-400 underline underline-offset-2"
                >
                  {t("cmClear")}
                </button>
              </div>
            )}
            
            {error && (
              <div className="mt-4 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
                {error}
              </div>
            )}
          </div>

          {/* Input Area */}
          {(!uiForm || isInitial) && !outOfScopeMessage && (
            <div className="p-4 border-t border-slate-800/60 bg-slate-950 shrink-0 relative z-20">
              <form 
                onSubmit={(e) => {
                  e.preventDefault();
                  submitRequest(undefined, isRevisionRequest(currentDocument));
                }}
                className="relative"
              >
                <textarea
                  value={requestInput}
                  onChange={(e) => setRequestInput(e.target.value)}
                  placeholder={currentDocument ? t("cmRevisePlaceholder") : t("cmInputPlaceholder")}
                  className="w-full rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 pe-12 text-sm text-white placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 min-h-[60px] max-h-[200px] resize-none block"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      submitRequest(undefined, isRevisionRequest(currentDocument));
                    }
                  }}
                />
                <button
                  type="submit"
                  disabled={!requestInput.trim() || loading}
                  className="absolute end-2 bottom-2 rounded-lg p-2 text-slate-400 hover:text-emerald-400 hover:bg-emerald-400/10 disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-slate-400 transition-colors"
                  aria-label={t("cmSubmit")}
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"></line>
                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                  </svg>
                </button>
              </form>
            </div>
          )}
        </div>

        {/* Right Column - Document Preview */}
        <div className="flex-1 bg-slate-950 flex flex-col min-w-0 overflow-hidden relative">
          {currentDocument ? (
            <div className="flex-1 flex flex-col h-full absolute inset-0 animate-in fade-in duration-700">
              <div className="px-6 py-4 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/20 backdrop-blur-sm z-10">
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-medium text-slate-200">{t("cmPreviewTitle")}</h3>
                  {activeDocumentType && (
                    <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-[11px] text-emerald-400 font-medium">
                      {activeDocumentType}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={clearState}
                    className="px-3 py-1.5 rounded-md border border-slate-700 text-xs text-slate-300 hover:bg-slate-800 transition-colors"
                  >
                    {t("cmClear")}
                  </button>
                  <button
                    onClick={handleCopy}
                    className="px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs text-white font-medium transition-colors flex items-center gap-1.5 min-w-[80px] justify-center"
                    aria-live="polite"
                  >
                    {copied ? (
                      <>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        {t("cmCopied")}
                      </>
                    ) : (
                      <>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        {t("cmCopy")}
                      </>
                    )}
                  </button>
                </div>
              </div>
              
              <div className="flex-1 overflow-y-auto p-8 relative">
                {loading && (
                  <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[1px] flex items-center justify-center z-10 animate-in fade-in duration-300">
                    <div className="px-4 py-2 rounded-full bg-slate-900 border border-emerald-500/30 text-emerald-400 text-sm shadow-xl flex items-center gap-3">
                      <div className="w-4 h-4 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                      {t("cmRevising")}
                    </div>
                  </div>
                )}
                <div className="max-w-3xl mx-auto bg-white text-slate-900 p-8 sm:p-12 min-h-full rounded-sm shadow-2xl whitespace-pre-wrap font-sans text-[15px] leading-relaxed border border-slate-200">
                  {currentDocument}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center p-6 opacity-30 pointer-events-none">
              <div className="w-full max-w-md aspect-[3/4] border-2 border-dashed border-slate-700 rounded-xl flex items-center justify-center bg-slate-900/20">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="text-slate-600 mb-4"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
