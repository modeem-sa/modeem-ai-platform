"use client";

import { useLocale } from "@/components/locale-provider";
import { Header } from "@/components/header";

const GUIDE_CONTENT = {
  ar: {
    title: "دليل استخدام المنصة",
    lastUpdated: "آخر تحديث: 31 أغسطس 2026",
    updateLogTitle: "سجل التحديثات",
    versionInfo: "معلومات الإصدار",
    updateLogItems: [
      "تحويل الفترة إلى تاريخ بداية ونهاية قابلين للاختيار، مع إضافة الموظف مباشرة من Odoo.",
      "استمرار إنشاء مقترح Modeem ومسودة التحصيل عند تعذر مزود الذكاء الاصطناعي.",
      "إعادة ربط مهام الفواتير القديمة باتصال Odoo النشط المطابق للجمعية والشركة."
    ],
    sections: {
      selection: {
        title: "اختيار الجمعية والمجال والإجراء",
        desc: "تبدأ جميع العمليات بتحديد نطاق العمل. اختر الجمعية أولاً لعرض البيانات المرتبطة بها، ثم حدد المجال (إداري أو مالي) لتصفية الإجراءات المتاحة بدقة."
      },
      employeeDate: {
        title: "اختيار الموظف وتاريخ الحضور",
        desc: "عند التعامل مع المهام الإدارية، تأكد من مطابقة تاريخ الحضور الفعلي للموظف المحدد في نظام Odoo لضمان دقة السجلات وتقارير الموارد البشرية وتجنب أخطاء الاحتساب."
      },
      invoice: {
        title: "مقترح الفاتورة والاعتماد",
        desc: "تجهز Modeem مقترحًا مضبوطًا لمتابعة الفاتورة. راجع المقترح بدقة، ثم اعتمده لتنفيذ الإجراء في Odoo، أو ارفضه لإعادة التجهيز. لا يحدث أي تغيير خارجي قبل الاعتماد البشري."
      },
      collection: {
        title: "مسودة التحصيل والاعتماد",
        desc: "بناءً على حالة الفواتير غير المسددة، يُنشئ النظام مسودة لرسالة تحصيل باللغة العربية بلهجة احترافية. يجب مراجعة المسودة وتأكيدها ليتم إرسالها للعميل المعني وتسجيل الإجراء."
      },
      states: {
        title: "فهم حالات النظام",
        desc: "تتغير حالة المهام بناءً على الإجراءات المتخذة. تعرّف على مؤشرات الألوان لتتبع تقدم العمل وتحديد المهام التي تتطلب تدخلاً لمعالجتها."
      }
    },
    uiDesc: {
      selectAssoc: "اختر الجمعية...",
      selectDomain: "اختر المجال...",
      selectProc: "اختر الإجراء...",
      employee: "الموظف",
      date: "الفترة من — إلى",
      invoiceTitle: "مقترح الفاتورة",
      amount: "المبلغ",
      approve: "اعتماد وتنفيذ",
      reject: "رفض الإجراء",
      collectionDraft: "مسودة التحصيل",
      draftContent: "السيد العميل، نود تذكيركم بلطف بقرب موعد استحقاق الفاتورة المرفقة. نرجو التكرم بالاطلاع وإتمام عملية السداد لضمان استمرارية الخدمة بأفضل شكل.",
      statusLoading: "قيد المعالجة...",
      statusSuccess: "مكتمل بنجاح",
      statusUnavailable: "غير متاح"
    }
  },
  en: {
    title: "Platform Guide",
    lastUpdated: "Last updated: August 31, 2026",
    updateLogTitle: "Update Log",
    versionInfo: "VERSION INFO",
    updateLogItems: [
      "Replaced the single period field with selectable start and end dates, and added the Odoo employee dropdown.",
      "Two reliability fixes to improve system stability."
    ],
    sections: {
      selection: {
        title: "Choosing Association, Domain, and Procedure",
        desc: "All operations start by defining the scope. Select the association first to view related data, then select the domain (administrative or financial) to filter available procedures and accurately direct AI tasks."
      },
      employeeDate: {
        title: "Attendance Date and Odoo Employee Selection",
        desc: "When dealing with administrative tasks, ensure the selected Odoo employee matches the actual attendance date to guarantee accurate records, HR reports, and prevent calculation errors."
      },
      invoice: {
        title: "Odoo Invoice Task Proposal and Approval",
        desc: "Modeem prepares a bounded invoice follow-up proposal. Review it carefully, then approve it for execution in Odoo or reject it for regeneration. No external change occurs before human approval."
      },
      collection: {
        title: "Arabic Collection Draft and Approval",
        desc: "Based on unpaid invoices, the system generates an Arabic collection message draft with a professional tone. Review the draft and confirm it to dispatch to the respective client and log the action."
      },
      states: {
        title: "Understanding System States",
        desc: "Task states change based on taken actions. Familiarize yourself with color indicators to track progress and identify tasks needing intervention."
      }
    },
    uiDesc: {
      selectAssoc: "Select Association...",
      selectDomain: "Select Domain...",
      selectProc: "Select Procedure...",
      employee: "Employee",
      date: "Date range",
      invoiceTitle: "Invoice Proposal",
      amount: "Amount",
      approve: "Approve & Execute",
      reject: "Reject Action",
      collectionDraft: "Collection Draft",
      draftContent: "السيد العميل، نود تذكيركم بلطف بقرب موعد استحقاق الفاتورة المرفقة. نرجو التكرم بالاطلاع وإتمام عملية السداد لضمان استمرارية الخدمة بأفضل شكل.",
      statusLoading: "Processing...",
      statusSuccess: "Completed",
      statusUnavailable: "Unavailable"
    }
  }
};

const Icons = {
  ChevronDown: ({ className }: { className?: string }) => <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>,
  User: ({ className }: { className?: string }) => <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>,
  Calendar: ({ className }: { className?: string }) => <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2" ry="2" strokeWidth="2"></rect><line x1="16" y1="2" x2="16" y2="6" strokeWidth="2"></line><line x1="8" y1="2" x2="8" y2="6" strokeWidth="2"></line><line x1="3" y1="10" x2="21" y2="10" strokeWidth="2"></line></svg>,
  BookOpen: ({ className }: { className?: string }) => <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path></svg>,
  Loader: ({ className }: { className?: string }) => <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>,
  Check: ({ className }: { className?: string }) => <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>,
};

type GuideUi = (typeof GUIDE_CONTENT)["en"]["uiDesc"];

function DiagramSelection({ uiDesc }: { uiDesc: GuideUi }) {
  return (
    <div className="bg-slate-900/80 p-5 rounded-2xl border border-slate-800/80 shadow-lg flex flex-col gap-3 transform rotate-1 hover:rotate-0 transition-transform duration-300">
      <div className="flex flex-col gap-2.5 w-full">
        <div className="w-full bg-slate-800/80 rounded-lg p-3 text-sm text-slate-400 border border-slate-700/50 flex justify-between items-center shadow-inner cursor-default">
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-sky-500"></span>
            {uiDesc.selectAssoc}
          </span>
          <Icons.ChevronDown className="w-4 h-4 text-slate-500" />
        </div>
        <div className="w-full bg-slate-800/80 rounded-lg p-3 text-sm text-slate-400 border border-slate-700/50 flex justify-between items-center shadow-inner ps-8 cursor-default">
          <span className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-500"></span>
            {uiDesc.selectDomain}
          </span>
          <Icons.ChevronDown className="w-4 h-4 text-slate-500" />
        </div>
        <div className="w-full bg-slate-800/80 rounded-lg p-3 text-sm text-slate-400 border border-slate-700/50 flex justify-between items-center shadow-inner ps-14 cursor-default">
          <span className="flex items-center gap-2">
            <span className="w-1 h-1 rounded-full bg-emerald-500"></span>
            {uiDesc.selectProc}
          </span>
          <Icons.ChevronDown className="w-4 h-4 text-slate-500" />
        </div>
      </div>
    </div>
  );
}

function DiagramEmployeeDate({ uiDesc }: { uiDesc: GuideUi }) {
  return (
    <div className="bg-slate-900/80 p-5 rounded-2xl border border-slate-800/80 shadow-lg flex flex-col gap-4 transform -rotate-1 hover:rotate-0 transition-transform duration-300">
      <div className="grid grid-cols-2 gap-4">
        <div>
           <div className="text-[10px] text-slate-500 mb-1.5 uppercase tracking-widest font-bold">{uiDesc.employee}</div>
           <div className="bg-slate-800/80 rounded-lg p-3 text-sm text-slate-200 border border-slate-700/50 flex justify-between items-center shadow-inner cursor-default">
             <div className="flex items-center gap-2.5 overflow-hidden">
               <div className="w-6 h-6 bg-indigo-900/50 rounded-full flex items-center justify-center border border-indigo-500/20 shrink-0">
                  <Icons.User className="w-3.5 h-3.5 text-indigo-300" />
               </div>
               <span className="truncate">Ahmed Ali</span>
             </div>
             <Icons.ChevronDown className="w-4 h-4 text-slate-500 shrink-0 ms-2" />
           </div>
        </div>
        <div>
           <div className="text-[10px] text-slate-500 mb-1.5 uppercase tracking-widest font-bold">{uiDesc.date}</div>
           <div className="bg-slate-800/80 rounded-lg p-3 text-sm text-slate-200 border border-slate-700/50 flex justify-between items-center shadow-inner cursor-default">
             <span className="font-mono truncate">2026-08-31</span>
             <Icons.Calendar className="w-4 h-4 text-slate-500 shrink-0 ms-2" />
           </div>
        </div>
      </div>
    </div>
  );
}

function DiagramInvoice({ uiDesc }: { uiDesc: GuideUi }) {
  return (
    <div className="bg-slate-900/80 p-5 rounded-2xl border border-sky-900/30 shadow-lg flex flex-col gap-4 relative overflow-hidden group">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-sky-500 via-indigo-500 to-purple-500 opacity-70"></div>
      <div className="flex justify-between items-start">
        <div>
          <div className="text-[9px] font-bold text-sky-400/80 tracking-widest mb-1.5 uppercase">ODOO FACTS</div>
          <div className="text-sm font-bold text-slate-100 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            {uiDesc.invoiceTitle} <span className="text-slate-500 font-mono text-xs">#INV-992</span>
          </div>
        </div>
        <div className="text-end">
          <div className="text-xs text-slate-500 mb-0.5">{uiDesc.amount}</div>
          <div className="text-base font-bold text-emerald-400 font-mono" dir="ltr">1,250.00 SAR</div>
        </div>
      </div>
      
      <div className="bg-indigo-950/30 border border-indigo-900/40 rounded-xl p-3.5 mt-1 backdrop-blur-sm">
        <div className="text-[10px] font-bold text-indigo-300/80 mb-2.5 uppercase tracking-widest flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-500"></span>
          MODEEM PROPOSAL
        </div>
        <div className="space-y-2">
          <div className="h-1.5 w-full bg-indigo-900/30 rounded-full overflow-hidden">
             <div className="h-full w-full bg-indigo-500/20"></div>
          </div>
          <div className="h-1.5 w-4/5 bg-indigo-900/30 rounded-full overflow-hidden">
             <div className="h-full w-full bg-indigo-500/20"></div>
          </div>
          <div className="h-1.5 w-2/3 bg-indigo-900/30 rounded-full overflow-hidden">
             <div className="h-full w-full bg-indigo-500/20"></div>
          </div>
        </div>
      </div>
      
      <div className="flex gap-2.5 mt-1">
        <div className="flex-1 bg-emerald-600/90 hover:bg-emerald-500 text-white rounded-lg py-2 text-xs text-center font-semibold shadow-md transition-colors cursor-default border border-emerald-500/50">
          {uiDesc.approve}
        </div>
        <div className="flex-1 bg-rose-950/40 text-rose-300 rounded-lg py-2 text-xs text-center font-semibold border border-rose-900/50 hover:bg-rose-900/40 transition-colors cursor-default">
          {uiDesc.reject}
        </div>
      </div>
    </div>
  );
}

function DiagramCollection({ uiDesc }: { uiDesc: GuideUi }) {
  return (
    <div className="bg-slate-900/80 p-5 rounded-2xl border border-slate-800/80 shadow-lg flex flex-col gap-4">
      <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4 shadow-inner relative">
        <div className="absolute -top-2.5 -start-2.5 w-6 h-6 rounded-full bg-sky-900/80 border border-sky-500/30 flex items-center justify-center">
          <span className="text-[10px] font-bold text-sky-300">M</span>
        </div>
        <div className="text-[10px] font-bold text-slate-400 mb-3 flex items-center justify-between uppercase tracking-widest">
          <span className="ps-6">{uiDesc.collectionDraft}</span>
          <span className="bg-slate-800 px-2 py-0.5 rounded-md text-slate-300 font-mono" dir="ltr">v1.2</span>
        </div>
        <div dir="rtl" className="text-sm text-slate-300 bg-slate-900/80 p-3 rounded-lg border border-slate-700/50 text-right leading-loose relative z-10">
          {uiDesc.draftContent}
        </div>
      </div>
      <div className="flex justify-end mt-1">
        <div className="bg-sky-600/90 hover:bg-sky-500 text-white rounded-lg px-6 py-2 text-xs text-center font-semibold shadow-md transition-colors cursor-default border border-sky-500/50">
          {uiDesc.approve}
        </div>
      </div>
    </div>
  );
}

function DiagramStates({ uiDesc }: { uiDesc: GuideUi }) {
  return (
    <div className="bg-slate-900/80 p-5 rounded-2xl border border-slate-800/80 shadow-lg flex flex-col gap-3">
      <div className="flex items-center justify-between p-3 rounded-xl border border-slate-800/80 bg-slate-950/50 shadow-sm">
        <div className="flex items-center gap-3.5">
          <div className="w-2.5 h-2.5 rounded-full bg-slate-600 shrink-0"></div>
          <div className="text-sm font-medium text-slate-300">{uiDesc.statusUnavailable}</div>
        </div>
        <div className="text-[10px] text-slate-500 font-mono tracking-widest bg-slate-900 px-2 py-1 rounded-md">IDLE</div>
      </div>
      <div className="flex items-center justify-between p-3 rounded-xl border border-amber-900/40 bg-amber-950/20 shadow-sm">
        <div className="flex items-center gap-3.5">
          <Icons.Loader className="w-4 h-4 text-amber-400 animate-spin shrink-0" />
          <div className="text-sm font-medium text-amber-200">{uiDesc.statusLoading}</div>
        </div>
        <div className="text-[10px] text-amber-500/80 font-mono tracking-widest bg-amber-950/50 px-2 py-1 rounded-md">PROCESSING</div>
      </div>
      <div className="flex items-center justify-between p-3 rounded-xl border border-emerald-900/40 bg-emerald-950/20 shadow-sm relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/5 to-transparent"></div>
        <div className="flex items-center gap-3.5 relative z-10">
          <div className="w-5 h-5 rounded-full bg-emerald-900/50 flex items-center justify-center shrink-0">
             <Icons.Check className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-sm font-medium text-emerald-200">{uiDesc.statusSuccess}</div>
        </div>
        <div className="text-[10px] text-emerald-500/80 font-mono tracking-widest bg-emerald-950/50 px-2 py-1 rounded-md relative z-10">SUCCESS</div>
      </div>
    </div>
  );
}

export default function GuidePage() {
  const { locale } = useLocale();
  const content = GUIDE_CONTENT[locale === "ar" ? "ar" : "en"];

  const sections = [
    {
      ...content.sections.selection,
      diagram: <DiagramSelection uiDesc={content.uiDesc} />
    },
    {
      ...content.sections.employeeDate,
      diagram: <DiagramEmployeeDate uiDesc={content.uiDesc} />
    },
    {
      ...content.sections.invoice,
      diagram: <DiagramInvoice uiDesc={content.uiDesc} />
    },
    {
      ...content.sections.collection,
      diagram: <DiagramCollection uiDesc={content.uiDesc} />
    },
    {
      ...content.sections.states,
      diagram: <DiagramStates uiDesc={content.uiDesc} />
    }
  ];

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-[#0b1120]">
      <Header titleKey="guide" />
      
      <main className="flex-1 overflow-y-auto p-4 md:p-8 lg:px-12 pb-24">
        <div className="max-w-4xl mx-auto">
          
          <div className="mb-10 text-center md:text-start mt-4">
            <h1 className="text-3xl md:text-4xl font-extrabold text-white tracking-tight mb-3">
              {content.title}
            </h1>
            <p className="text-slate-400 text-sm font-medium">
              {content.lastUpdated}
            </p>
          </div>

          {/* Update Log Section */}
          <div className="bg-sky-950/20 border border-sky-900/40 rounded-3xl p-6 md:p-8 mb-16 flex flex-col md:flex-row gap-8 md:items-center shadow-lg relative overflow-hidden">
            <div className="absolute -top-24 -end-24 w-48 h-48 bg-sky-500/10 rounded-full blur-3xl pointer-events-none"></div>
            
            <div className="flex-1 relative z-10">
              <div className="flex items-center gap-3.5 mb-5">
                <div className="w-12 h-12 rounded-xl bg-sky-900/40 flex items-center justify-center border border-sky-500/20 shadow-inner">
                  <Icons.BookOpen className="w-6 h-6 text-sky-400" />
                </div>
                <div>
                  <h2 className="text-xl md:text-2xl font-bold text-sky-100 tracking-wide">{content.updateLogTitle}</h2>
                </div>
              </div>
              <ul className="text-sm text-sky-200/80 space-y-3 md:ms-16 font-medium">
                {content.updateLogItems.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-2.5 leading-relaxed">
                    <div className="w-1.5 h-1.5 rounded-full bg-sky-500/50 mt-2 shrink-0"></div>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            
            <div className="md:border-s border-sky-900/40 md:ps-8 shrink-0 relative z-10 pt-6 md:pt-0 mt-2 md:mt-0 border-t md:border-t-0 flex flex-col justify-center">
              <div className="text-[10px] uppercase tracking-widest text-sky-500/70 mb-2 font-bold">
                {content.versionInfo}
              </div>
              <div className="text-sm font-mono text-sky-100 bg-sky-900/40 px-4 py-2 rounded-lg border border-sky-500/20 inline-block shadow-sm" dir="ltr">
                2026-08-31
              </div>
            </div>
          </div>

          {/* Guide Sections */}
          <div className="space-y-20">
            {sections.map((section, idx) => (
              <div key={idx} className="grid md:grid-cols-2 gap-8 lg:gap-16 items-center group">
                <div className={`space-y-5 ${idx % 2 === 1 ? 'md:order-last' : ''}`}>
                  <div className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-slate-800 text-slate-400 font-mono text-sm font-bold border border-slate-700/50 mb-2 shadow-sm">
                    0{idx + 1}
                  </div>
                  <h3 className="text-2xl font-bold text-slate-100 group-hover:text-sky-300 transition-colors duration-300">
                    {section.title}
                  </h3>
                  <p className="text-slate-400 leading-relaxed text-sm md:text-base font-medium">
                    {section.desc}
                  </p>
                </div>
                <div className="relative">
                  <div className="absolute inset-0 bg-gradient-to-tr from-sky-500/5 to-purple-500/5 rounded-3xl blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-700"></div>
                  <div className="relative z-10">
                    {section.diagram}
                  </div>
                </div>
              </div>
            ))}
          </div>
          
        </div>
      </main>
    </div>
  );
}
