import manifestJson from "../../../../contracts/schemas/v1/manifest.json";
import clientInitSchemaJson from "../../../../contracts/schemas/v1/client_init.schema.json";
import userSpeakSchemaJson from "../../../../contracts/schemas/v1/user_speak.schema.json";
import clientInterruptSchemaJson from "../../../../contracts/schemas/v1/client_interrupt.schema.json";
import serverStreamChunkSchemaJson from "../../../../contracts/schemas/v1/server_stream_chunk.schema.json";
import serverErrorSchemaJson from "../../../../contracts/schemas/v1/server_error.schema.json";
import type {
  ClientEvent,
  ClientInitEvent,
  ClientInterruptEvent,
  ContractManifest,
  ProtocolDirection,
  ProtocolEventName,
  ServerErrorEvent,
  ServerEvent,
  ServerStreamChunkEvent,
  UserSpeakEvent,
  VisemeFrame,
} from "../../../../contracts/generated/typescript/protocol-contracts";

type JsonValue = boolean | number | string | null | JsonObject | JsonValue[];
type JsonObject = { [key: string]: JsonValue };

interface EventSchema {
  title: string;
  required?: string[];
  properties?: Record<string, JsonObject>;
}

const manifest = manifestJson as ContractManifest;
const schemaRegistry = {
  client_init: clientInitSchemaJson as EventSchema,
  user_speak: userSpeakSchemaJson as EventSchema,
  client_interrupt: clientInterruptSchemaJson as EventSchema,
  server_stream_chunk: serverStreamChunkSchemaJson as EventSchema,
  server_error: serverErrorSchemaJson as EventSchema,
} satisfies Record<ProtocolEventName, EventSchema>;
const clientInitSchema = schemaRegistry.client_init;
const userSpeakSchema = schemaRegistry.user_speak;
const clientInterruptSchema = schemaRegistry.client_interrupt;
const serverStreamChunkSchema = schemaRegistry.server_stream_chunk;
const serverErrorSchema = schemaRegistry.server_error;
const allowedServerErrorCodes = readEnum(serverErrorSchema, "error_code") as ServerErrorEvent["error_code"][];
const allowedVisemeValues = readEnum(serverStreamChunkSchema, "visemes", "value") as VisemeFrame["value"][];

export const DEFAULT_PROTOCOL_VERSION = manifest.version;

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

export function loadProtocolContract(version = DEFAULT_PROTOCOL_VERSION) {
  assertSupportedVersion(version);
  return {
    ...manifest,
    events: buildContractEvents(),
  };
}

export function validateClientEvent(payload: unknown, version = DEFAULT_PROTOCOL_VERSION): ClientEvent {
  return validateEvent(payload, version, "client_to_server") as ClientEvent;
}

export function validateServerEvent(payload: unknown, version = DEFAULT_PROTOCOL_VERSION): ServerEvent {
  return validateEvent(payload, version, "server_to_client") as ServerEvent;
}

function validateEvent(
  payload: unknown,
  version: string,
  direction: ProtocolDirection,
): ClientEvent | ServerEvent {
  assertSupportedVersion(version);
  const record = expectRecord(payload, version);
  const eventName = expectEventName(record.event, version);
  const eventConfig = manifest.events[eventName];

  if (!eventConfig || eventConfig.direction !== direction) {
    throw new ProtocolValidationError(
      `Unsupported ${direction} event \`${eventName}\` for contract ${version}`,
      version,
      eventName,
    );
  }

  switch (eventName) {
    case "client_init":
      return validateClientInit(record, version);
    case "user_speak":
      return validateUserSpeak(record, version);
    case "client_interrupt":
      return validateClientInterrupt(record, version);
    case "server_stream_chunk":
      return validateServerStreamChunk(record, version);
    case "server_error":
      return validateServerError(record, version);
    default:
      throw new ProtocolValidationError(
        `Unsupported protocol event \`${eventName}\``,
        version,
        eventName,
      );
  }
}

function validateClientInit(record: Record<string, unknown>, version: string): ClientInitEvent {
  assertShape(record, clientInitSchema, version, "client_init");

  return {
    event: "client_init",
    client_id: expectNonEmptyString(record.client_id, version, "client_id", "client_init"),
    protocol_version: expectSemver(record.protocol_version, version, "client_init", "protocol_version"),
    auth_token: expectNonEmptyString(record.auth_token, version, "auth_token", "client_init"),
    capabilities: expectOptionalStringMap(record.capabilities, version, "client_init", "capabilities"),
    timestamp: expectNonNegativeInteger(record.timestamp, version, "client_init", "timestamp"),
  };
}

function validateUserSpeak(record: Record<string, unknown>, version: string): UserSpeakEvent {
  assertShape(record, userSpeakSchema, version, "user_speak");
  return {
    event: "user_speak",
    text: expectNonEmptyString(record.text, version, "text", "user_speak"),
    timestamp: expectNonNegativeInteger(record.timestamp, version, "user_speak", "timestamp"),
  };
}

function validateClientInterrupt(record: Record<string, unknown>, version: string): ClientInterruptEvent {
  assertShape(record, clientInterruptSchema, version, "client_interrupt");
  return {
    event: "client_interrupt",
    timestamp: expectNonNegativeInteger(record.timestamp, version, "client_interrupt", "timestamp"),
  };
}

function validateServerStreamChunk(record: Record<string, unknown>, version: string): ServerStreamChunkEvent {
  assertShape(record, serverStreamChunkSchema, version, "server_stream_chunk");
  return {
    event: "server_stream_chunk",
    chunk_id: expectNonEmptyString(record.chunk_id, version, "chunk_id", "server_stream_chunk"),
    text: expectNonEmptyString(record.text, version, "text", "server_stream_chunk"),
    audio_base64: expectNonEmptyString(record.audio_base64, version, "audio_base64", "server_stream_chunk"),
    visemes: expectVisemeFrames(record.visemes, version),
    emotion: expectOptionalNonEmptyString(record.emotion, version, "emotion", "server_stream_chunk"),
    is_final: expectBoolean(record.is_final, version, "server_stream_chunk", "is_final"),
  };
}

function validateServerError(record: Record<string, unknown>, version: string): ServerErrorEvent {
  assertShape(record, serverErrorSchema, version, "server_error");
  const errorCode = expectEnumValue(
    record.error_code,
    allowedServerErrorCodes,
    version,
    "server_error",
    "error_code",
  );

  return {
    event: "server_error",
    error_code: errorCode,
    message: expectNonEmptyString(record.message, version, "message", "server_error"),
    retry_after_ms: expectOptionalNonNegativeInteger(
      record.retry_after_ms,
      version,
      "server_error",
      "retry_after_ms",
    ),
    timestamp: expectNonNegativeInteger(record.timestamp, version, "server_error", "timestamp"),
  };
}

function buildContractEvents() {
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

function assertSupportedVersion(version: string) {
  if (version !== manifest.version) {
    throw new ProtocolValidationError(
      `Unsupported protocol contract version: ${version}`,
      version,
    );
  }
}

function assertShape(
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

function expectRecord(value: unknown, version: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ProtocolValidationError("Protocol payload must be an object", version);
  }
  return value as Record<string, unknown>;
}

function expectStringMap(
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

function expectOptionalStringMap(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  return expectOptional(value, () => expectStringMap(value, version, eventName, fieldName)) ?? {};
}

function expectVisemeFrames(value: unknown, version: string): VisemeFrame[] {
  if (!Array.isArray(value)) {
    throwInvalidField(version, "server_stream_chunk", "visemes", "must be an array");
  }

  return value.map((item, index) => {
    const record = expectRecord(item, version);
    const valueFieldName = `visemes.${index}.value`;
    const frameValue = expectEnumValue(
      record.value,
      allowedVisemeValues,
      version,
      "server_stream_chunk",
      valueFieldName,
    );

    return {
      time: expectNonNegativeNumber(record.time, version, "server_stream_chunk", `visemes.${index}.time`),
      value: frameValue,
    };
  });
}

function expectSemver(
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

function expectNonEmptyString(
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

function expectEventName(value: unknown, version: string): ProtocolEventName {
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

function expectOptionalNonEmptyString(
  value: unknown,
  version: string,
  fieldName: string,
  eventName: string,
) {
  return expectOptional(value, () => expectNonEmptyString(value, version, fieldName, eventName));
}

function expectNonNegativeInteger(
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

function expectOptionalNonNegativeInteger(
  value: unknown,
  version: string,
  eventName: string,
  fieldName: string,
) {
  return expectOptional(value, () => expectNonNegativeInteger(value, version, eventName, fieldName));
}

function expectNonNegativeNumber(
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

function expectBoolean(
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

function readEnum(schema: EventSchema, propertyName: string, nestedProperty?: string) {
  const property = schema.properties?.[propertyName];
  if (!property) {
    return [];
  }

  if (nestedProperty) {
    const itemRecord = property.items as JsonObject | undefined;
    const nestedProperties = itemRecord?.properties as JsonObject | undefined;
    const nestedSchema = nestedProperties?.[nestedProperty] as JsonObject | undefined;
    return filterStringEnum(nestedSchema?.enum as JsonValue[] | undefined);
  }

  return filterStringEnum(property.enum as JsonValue[] | undefined);
}

function filterStringEnum(values: JsonValue[] | undefined) {
  return values?.filter((item): item is string => typeof item === "string") ?? [];
}

function expectOptional<T>(value: unknown, readValue: () => T): T | undefined {
  if (value === undefined) {
    return undefined;
  }
  return readValue();
}

function expectEnumValue<T extends string>(
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

function throwInvalidField(
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
