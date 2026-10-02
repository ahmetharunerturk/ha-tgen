import { build } from "esbuild";
await build({
  entryPoints: ["frontend/panel.ts"],
  outfile: "custom_components/ha_tgen/frontend/panel.js",
  bundle: true, minify: true, format: "esm", target: "es2022",
  legalComments: "eof",
});
