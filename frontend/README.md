# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

## CaberOS desktop app

The Tauri desktop shell uses the same FastAPI REST/SSE gateway as the browser dashboard.

```bash
npm run desktop:dev
npm run desktop:build
npm run desktop:build:dmg
```

`desktop:dev` starts or reuses the local gateway at `http://127.0.0.1:8081` and starts Vite. `desktop:build` produces the native `.app` bundle; `desktop:build:dmg` packages that app into a macOS disk image with `hdiutil`. Native builds require Rust and the platform's desktop build tools. The packaged app starts its bundled gateway automatically; `CABEROS_GATEWAY_EXECUTABLE` can override the executable for diagnostics or development. The gateway uses a PyInstaller onedir bundle to avoid one-file extraction delays during startup.
