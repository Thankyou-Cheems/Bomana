declare const __BOMANA_EDITION__: "Lite" | "Standard";

interface ImportMetaEnv {
  readonly VITE_BRIDGE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
