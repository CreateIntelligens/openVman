import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function readAppModule(name) {
  return readFileSync(
    fileURLToPath(new URL(`../../composables/${name}.ts`, import.meta.url)),
    "utf8",
  );
}

/** Read the template and the domains whose wiring this regression verifies. */
export function readAppComposition(...modules) {
  const template = readFileSync(
    fileURLToPath(new URL("../../App.vue", import.meta.url)), "utf8",
  );
  return [template, ...modules.map(readAppModule)].join("\n");
}
