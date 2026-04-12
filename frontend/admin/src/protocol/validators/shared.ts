import type { ProtocolEventName } from "@contracts/generated/typescript/protocol-contracts";
import { manifest, schemaRegistry, type EventSchema } from "./schema";

export class ProtocolValidationError extends Error {
  version: string;
  event: string;

  constructor(message: string, version: string, event = "") {
    super(message);
    this.name = "ProtocolValidationError";
    this.version = version;
    this.event = event;
  }
}

export function buildContractEvents() {
  return Object.fromEntries(
    Object.entries(manifest.events).map(([eventName, eventConfig]) => [
      eventName,
      {
        ...eventConfig,
        schema: schemaRegistry[eventName as keyof typeof schemaRegistry],
      },
    ]),
  );
}

export function assertSupportedVersion(version: string) {
  if (version !== manifest.version) {
    throw new ProtocolValidationError(
      `Unsupported protocol contract version: ${version}`,
      version,
    );
  }
}

export function assertShape(
  record: Record<string, unknown>,
  schema: EventSchema,
  version: string,
  eventName: string,
) {
  const requiredFields = schema.required ?? [];
  for (const fieldName of requiredFields) {
    if (!(fieldName in record)) {
      throwInvalidField(version, eventName, fieldName, "is required");
    }
  }

  const allowedFields = new Set(Object.keys(schema.properties ?? {}));
  for (const fieldName of Object.keys(record)) {
    if (!allowedFields.has(fieldName)) {
      throwInvalidField(version, eventName, fieldName, "is not allowed");
    }
  }
}

export function expectRecord(value: unknown, version: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ProtocolValidationError("Protocol payload must be an object", version);
  }
  return value as Record<string, unknown>;
}

export function expectStringMap(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  const record = expectRecord(value, version);
  const normalized: Record<string, string> = {};
  for (const [key, item] of Object.entries(record)) {
    normalized[key] = expectNonEmptyString(item, version, fieldName, eventName);
  }
  return normalized;
}

export function expectOptionalStringMap(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  return expectOptional(value, () => expectStringMap(value, version, eventName, fieldName)) ?? {};
}

export function expectSemver(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  const text = expectNonEmptyString(value, version, fieldName, eventName);
  if (!/^\d+\.\d+\.\d+$/.test(text)) {
    throwInvalidField(version, eventName, fieldName, "must match semver");
  }
  return text;
}

export function expectNonEmptyString(
  value: unknown,
  version: string,
  fieldName: string,
  eventName = "",
) {
  if (typeof value !== "string" || !value.trim()) {
    throwInvalidField(version, eventName, fieldName, "must be a non-empty string");
  }
  return value.trim();
}

export function expectString(
  value: unknown,
  version: string,
  fieldName: string,
  eventName = "",
) {
  if (typeof value !== "string") {
    throwInvalidField(version, eventName, fieldName, "must be a string");
  }
  return value;
}

export function expectEventName(value: unknown, version: string): ProtocolEventName {
  const eventName = expectNonEmptyString(value, version, "event");
  if (eventName in manifest.events) {
    return eventName as ProtocolEventName;
  }
  throw new ProtocolValidationError(
    `Unsupported protocol event \`${eventName}\``,
    version,
    eventName,
  );
}

export function expectOptionalNonEmptyString(
  value: unknown,
  version: string,
  fieldName: string,
  eventName: string,
) {
  return expectOptional(value, () => expectNonEmptyString(value, version, fieldName, eventName));
}

export function expectNonNegativeInteger(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  if (!Number.isInteger(value) || Number(value) < 0) {
    throwInvalidField(version, eventName, fieldName, "must be a non-negative integer");
  }
  return Number(value);
}

export function expectOptionalNonNegativeInteger(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  return expectOptional(value, () => expectNonNegativeInteger(value, version, eventName, fieldName));
}

export function expectNonNegativeNumber(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
    throwInvalidField(version, eventName, fieldName, "must be a non-negative number");
  }
  return value;
}

export function expectBoolean(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  if (typeof value !== "boolean") {
    throwInvalidField(version, eventName, fieldName, "must be a boolean");
  }
  return value;
}

export function expectOptional<T>(value: unknown, readValue: () => T): T | undefined {
  if (value === undefined) {
    return undefined;
  }
  return readValue();
}

export function expectEnumValue<T extends string>(
  value: unknown,
  allowedValues: readonly T[],
  version: string,
  eventName: string,
  fieldName: string,
): T {
  const text = expectNonEmptyString(value, version, fieldName, eventName);
  if (allowedValues.includes(text as T)) {
    return text as T;
  }
  throwInvalidField(version, eventName, fieldName, `must be one of ${allowedValues.join(", ")}`);
}

export function throwInvalidField(
  version: string,
  eventName: string,
  fieldName: string,
  reason: string,
): never {
  throw new ProtocolValidationError(
    `Invalid protocol payload for \`${eventName}\`: ${fieldName} ${reason}`,
    version,
    eventName,
  );
}
