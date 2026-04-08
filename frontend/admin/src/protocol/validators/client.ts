import type {
  ClientAudioChunkEvent,
  ClientAudioEndEvent,
  ClientInitEvent,
  ClientInterruptEvent,
  UserSpeakEvent,
} from "@contracts/generated/typescript/protocol-contracts";
import {
  clientAudioChunkSchema,
  clientAudioEndSchema,
  clientInitSchema,
  clientInterruptSchema,
  userSpeakSchema,
} from "./schema";
import {
  assertShape,
  expectNonEmptyString,
  expectNonNegativeInteger,
  expectOptionalNonEmptyString,
  expectOptionalStringMap,
  expectSemver,
  throwInvalidField,
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
    partial_asr: expectOptionalNonEmptyString(record.partial_asr, version, "partial_asr", "client_interrupt"),
  };
}

export function validateClientAudioChunk(record: Record<string, unknown>, version: string): ClientAudioChunkEvent {
  assertShape(record, clientAudioChunkSchema, version, "client_audio_chunk");
  const sampleRate = expectNonNegativeInteger(record.sample_rate, version, "client_audio_chunk", "sample_rate");
  if (sampleRate < 1) {
    throwInvalidField(version, "client_audio_chunk", "sample_rate", "must be greater than 0");
  }

  return {
    event: "client_audio_chunk",
    audio_base64: expectNonEmptyString(record.audio_base64, version, "audio_base64", "client_audio_chunk"),
    sample_rate: sampleRate,
    mime_type: expectNonEmptyString(record.mime_type, version, "mime_type", "client_audio_chunk"),
    timestamp: expectNonNegativeInteger(record.timestamp, version, "client_audio_chunk", "timestamp"),
  };
}

export function validateClientAudioEnd(record: Record<string, unknown>, version: string): ClientAudioEndEvent {
  assertShape(record, clientAudioEndSchema, version, "client_audio_end");
  return {
    event: "client_audio_end",
    timestamp: expectNonNegativeInteger(record.timestamp, version, "client_audio_end", "timestamp"),
  };
}
