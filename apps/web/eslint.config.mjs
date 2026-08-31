import { FlatCompat } from "@eslint/eslintrc";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals.js";
import nextTypeScript from "eslint-config-next/typescript.js";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const baseDirectory = dirname(fileURLToPath(import.meta.url));
const legacyCompat = new FlatCompat({ baseDirectory });
const nextConfigs = Array.isArray(nextCoreWebVitals)
  ? [...nextCoreWebVitals, ...nextTypeScript]
  : legacyCompat.extends("next/core-web-vitals", "next/typescript");

const eslintConfig = [
  ...nextConfigs,
  {
    rules: {
      "react-hooks/set-state-in-effect": "off",
    },
  },
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
];

export default eslintConfig;
