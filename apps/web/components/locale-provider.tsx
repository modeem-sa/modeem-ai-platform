"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { dictionaries, dirFor, type Locale } from "@/lib/i18n";

type LocaleContextValue = {
  locale: Locale;
  t: (key: string) => string;
  toggleLocale: () => void;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>("ar");

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dirFor(locale);
  }, [locale]);

  const value: LocaleContextValue = {
    locale,
    t: (key) => dictionaries[locale][key] ?? key,
    toggleLocale: () => setLocale((l) => (l === "ar" ? "en" : "ar")),
  };

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useLocale must be used within LocaleProvider");
  return ctx;
}
