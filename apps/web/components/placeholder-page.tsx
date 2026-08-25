"use client";

import { Header } from "@/components/header";
import { useLocale } from "@/components/locale-provider";

export function PlaceholderPage({ titleKey }: { titleKey: string }) {
  const { t } = useLocale();

  return (
    <div className="flex-1 flex flex-col">
      <Header titleKey={titleKey} />
      <main className="flex-1 p-6">
        <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 p-10 text-center">
          <p className="text-slate-300">{t(titleKey)}</p>
          <p className="mt-2 text-sm text-slate-500">{t("comingSoon")}</p>
        </div>
      </main>
    </div>
  );
}
