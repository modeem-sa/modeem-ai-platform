"use client";

import { useLocale } from "@/components/locale-provider";
import { ServiceRequest, downloadServiceRequestAttachment } from "@/lib/service-requests";
import { formatDate } from "@/lib/utils";
import { useState, useRef, useEffect } from "react";
import { IconSend, IconPaperclip, IconDownload, IconUser, IconMessage } from "@/components/icons";
import { useAuth } from "@/components/auth-provider";

export function RequestConversation({ 
  request, 
  onSendMessage, 
  onUploadAttachment,
  isSubmitting
}: { 
  request: ServiceRequest;
  onSendMessage: (body: string) => Promise<void>;
  onUploadAttachment: (file: File) => Promise<void>;
  isSubmitting: boolean;
}) {
  const { t, locale } = useLocale();
  const { user } = useAuth();
  const [message, setMessage] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [request.messages.length, request.attachments.length]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim() || isSubmitting) return;
    
    const body = message;
    setMessage("");
    try {
      await onSendMessage(body);
    } catch {
      setMessage(body); // Restore on failure
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || isSubmitting) return;
    
    // Clear input
    e.target.value = "";
    await onUploadAttachment(file);
  };

  const allItems = [
    ...request.messages.map(m => ({ type: "message" as const, data: m, date: new Date(m.created_at) })),
    ...request.attachments.map(a => ({ type: "attachment" as const, data: a, date: new Date(a.created_at) }))
  ].sort((a, b) => a.date.getTime() - b.date.getTime());

  const canInteract = request.status !== "closed" && request.status !== "resolved";

  return (
    <div className="flex flex-col h-full max-h-[600px] border border-slate-800 rounded-xl bg-slate-900/30 overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {allItems.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 space-y-3">
            <IconMessage className="w-8 h-8 opacity-50" />
            <p className="text-sm">{t("reqTypeMessage")}</p>
          </div>
        ) : (
          allItems.map((item) => {
            const isMe = item.type === "message" 
              ? item.data.author_id === user?.id
              : item.data.uploaded_by_id === user?.id;

            return (
              <div key={item.data.id} className={`flex gap-3 ${isMe ? "flex-row-reverse" : ""}`}>
                <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${isMe ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-800 text-slate-300"}`}>
                  <IconUser className="w-4 h-4" />
                </div>
                
                <div className={`flex flex-col gap-1 max-w-[80%] ${isMe ? "items-end" : "items-start"}`}>
                  <div className="flex items-baseline gap-2 text-xs">
                    <span className="font-medium text-slate-300">
                      {item.type === "message" ? item.data.author_name : t("reqSystem")}
                    </span>
                    <span className="text-slate-500">{formatDate(item.data.created_at, locale)}</span>
                  </div>

                  {item.type === "message" ? (
                    <div className={`p-3 rounded-2xl text-sm whitespace-pre-wrap ${
                      isMe 
                        ? "bg-emerald-600/20 text-emerald-100 rounded-tr-sm border border-emerald-500/20" 
                        : "bg-slate-800 text-slate-200 rounded-tl-sm border border-slate-700/50"
                    }`}>
                      {item.data.body}
                    </div>
                  ) : (
                    <button 
                      onClick={() => downloadServiceRequestAttachment(request.id, item.data)}
                      className={`flex items-center gap-3 p-3 rounded-xl border text-sm transition-colors text-start ${
                        isMe
                          ? "bg-emerald-600/10 border-emerald-500/20 hover:bg-emerald-600/20"
                          : "bg-slate-800 border-slate-700/50 hover:bg-slate-700"
                      }`}
                    >
                      <div className="p-2 rounded-lg bg-slate-950/50 text-slate-300">
                        <IconPaperclip className="w-4 h-4" />
                      </div>
                      <div className="overflow-hidden">
                        <div className="font-medium text-slate-200 truncate">{item.data.filename}</div>
                        <div className="text-xs text-slate-500">{(item.data.size / 1024).toFixed(1)} KB</div>
                      </div>
                      <IconDownload className="w-4 h-4 text-slate-400 ml-2 shrink-0" />
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      {canInteract && (
        <form onSubmit={handleSend} className="p-3 bg-slate-950 border-t border-slate-800 flex gap-2">
          <input
            type="file"
            className="hidden"
            ref={fileInputRef}
            onChange={handleFileChange}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isSubmitting}
            data-testid="request-upload-button"
            className="shrink-0 p-3 rounded-lg border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors disabled:opacity-50"
            title={t("reqUpload")}
          >
            <IconPaperclip className="w-5 h-5" />
          </button>
          
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={isSubmitting}
            data-testid="request-message-input"
            placeholder={t("reqTypeMessage")}
            className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
          />
          
          <button
            type="submit"
            disabled={!message.trim() || isSubmitting}
            data-testid="request-send-message-button"
            className="shrink-0 p-3 rounded-lg bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50 disabled:hover:bg-emerald-600"
          >
            <IconSend className="w-5 h-5" />
          </button>
        </form>
      )}
    </div>
  );
}
