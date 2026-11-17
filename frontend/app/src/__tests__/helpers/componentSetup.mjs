import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { computed, effectScope, reactive, ref, watch } from "vue";
import { parse } from "@vue/compiler-sfc";

// Execute the real setup with Vue reactivity; lifecycle and external I/O stay controllable.
export function componentSetup(path, initialProps, dependencies = {}) {
  const { descriptor } = parse(readFileSync(path, "utf8"));
  const script = descriptor.scriptSetup.content.replace(
    /^import[\s\S]*?from\s+["'][^"']+["'];?\s*$/gm, "",
  );
  const { outputText } = ts.transpileModule(script, {
    compilerOptions: { module: ts.ModuleKind.ESNext },
  });
  const props = reactive(initialProps);
  const events = [];
  const mounted = [];
  const unmounting = [];
  const scope = effectScope();
  const context = vm.createContext({
    computed, reactive, ref, watch, console, setTimeout, clearTimeout,
    defineProps: () => props,
    defineEmits: () => (...args) => events.push(args),
    withDefaults: (_props, defaults) => {
      for (const [key, value] of Object.entries(defaults)) {
        if (!(key in props)) props[key] = typeof value === "function" ? value() : value;
      }
      return props;
    },
    onMounted: (callback) => mounted.push(callback),
    onBeforeUnmount: (callback) => unmounting.push(callback),
    ...dependencies,
  });
  scope.run(() => vm.runInContext(outputText.replace(/^export \{\};?$/gm, ""), context));
  return {
    props,
    events,
    read: (expression) => vm.runInContext(expression, context),
    mount: () => mounted.forEach((callback) => callback()),
    dispose: () => {
      unmounting.forEach((callback) => callback());
      scope.stop();
    },
  };
}
