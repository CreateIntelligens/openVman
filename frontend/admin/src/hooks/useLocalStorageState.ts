import { useCallback, useState, type Dispatch, type SetStateAction } from "react";

function isAllowedValue<T extends string>(
  value: string,
  allowedValues?: readonly T[],
): value is T {
  return !allowedValues || allowedValues.includes(value as T);
}

function readStoredValue<T extends string>(
  key: string,
  defaultValue: T,
  allowedValues?: readonly T[],
): T {
  if (typeof window === "undefined") {
    return defaultValue;
  }

  try {
    const stored = window.localStorage.getItem(key);
    if (!stored || !isAllowedValue(stored, allowedValues)) {
      return defaultValue;
    }
    return stored;
  } catch {
    return defaultValue;
  }
}

function writeStoredValue(key: string, value: string): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore quota/security errors so browser privacy settings cannot break UI state.
  }
}

export function useLocalStorageState<T extends string>(
  key: string,
  defaultValue: T,
  allowedValues?: readonly T[],
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() =>
    readStoredValue(key, defaultValue, allowedValues),
  );

  const setStoredValue = useCallback<Dispatch<SetStateAction<T>>>((nextValue) => {
    setValue((currentValue) => {
      const resolvedValue = typeof nextValue === "function"
        ? nextValue(currentValue)
        : nextValue;
      writeStoredValue(key, resolvedValue);
      return resolvedValue;
    });
  }, [key]);

  return [value, setStoredValue];
}
