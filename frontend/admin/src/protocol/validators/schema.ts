import manifestJson from "@contracts/schemas/v1/manifest.json";
import clientInitSchemaJson from "@contracts/schemas/v1/client_init.schema.json";
import userSpeakSchemaJson from "@contracts/schemas/v1/user_speak.schema.json";
import clientInterruptSchemaJson from "@contracts/schemas/v1/client_interrupt.schema.json";
import serverStreamChunkSchemaJson from "@contracts/schemas/v1/server_stream_chunk.schema.json";
import serverErrorSchemaJson from "@contracts/schemas/v1/server_error.schema.json";
import serverInitAckSchemaJson from "@contracts/schemas/v1/server_init_ack.schema.json";
import type {
  ContractManifest,
  ProtocolEventName,
  ServerErrorEvent,
  ServerInitAckEvent,
  VisemeFrame,
} from "@contracts/generated/typescript/protocol-contracts";

export type JsonValue = boolean | number | string | null | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export interface EventSchema {
  title: string;
  required?: string[];
  properties?: Record<string, JsonObject>;
}

export const manifest = manifestJson as ContractManifest;

export const schemaRegistry = {
  client_init: clientInitSchemaJson as EventSchema,
  user_speak: userSpeakSchemaJson as EventSchema,
  client_interrupt: clientInterruptSchemaJson as EventSchema,
  server_stream_chunk: serverStreamChunkSchemaJson as EventSchema,
  server_error: serverErrorSchemaJson as EventSchema,
  server_init_ack: serverInitAckSchemaJson as EventSchema,
} satisfies Record<ProtocolEventName, EventSchema>;

export const clientInitSchema = schemaRegistry.client_init;
export const userSpeakSchema = schemaRegistry.user_speak;
export const clientInterruptSchema = schemaRegistry.client_interrupt;
export const serverStreamChunkSchema = schemaRegistry.server_stream_chunk;
export const serverErrorSchema = schemaRegistry.server_error;
export const serverInitAckSchema = schemaRegistry.server_init_ack;

export const allowedServerErrorCodes = readEnum(serverErrorSchema, "error_code") as ServerErrorEvent["error_code"][];
export const allowedVisemeValues = readEnum(serverStreamChunkSchema, "visemes", "value") as VisemeFrame["value"][];
export const allowedInitAckStatuses = readEnum(serverInitAckSchema, "status") as ServerInitAckEvent["status"][];

export const DEFAULT_PROTOCOL_VERSION = manifest.version;

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
