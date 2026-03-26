import type {
  ClientInitEvent,
  ClientInterruptEvent,
  UserSpeakEvent,
} from "@contracts/generated/typescript/protocol-contracts";
import {
  clientInitSchema,
  clientInterruptSchema,
  userSpeakSchema,
} from "./schema";
import {
  assertShape,
  expectNonEmptyString,
  expectNonNegativeInteger,
  expectOptionalStringMap,
  expectSemver,
} from "./shared";

export function validateClientInit(record: Record<string, unknown>, version: string): ClientInitEvent {
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

export function validateUserSpeak(record: Record<string, unknown>, version: string): UserSpeakEvent {
  assertShape(record, userSpeakSchema, version, "user_speak");
  return {
    event: "user_speak",
    text: expectNonEmptyString(record.text, version, "text", "user_speak"),
    timestamp: expectNonNegativeInteger(record.timestamp, version, "user_speak", "timestamp"),
  };
}

export function validateClientInterrupt(record: Record<string, unknown>, version: string): ClientInterruptEvent {
  assertShape(record, clientInterruptSchema, version, "client_interrupt");
  return {
    event: "client_interrupt",
    timestamp: expectNonNegativeInteger(record.timestamp, version, "client_interrupt", "timestamp"),
  };
}
