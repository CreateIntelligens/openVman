import type {
  ServerErrorEvent,
  ServerInitAckEvent,
  ServerStreamChunkEvent,
  VisemeFrame,
} from "@contracts/generated/typescript/protocol-contracts";
import {
  allowedInitAckStatuses,
  allowedServerErrorCodes,
  allowedVisemeValues,
  serverErrorSchema,
  serverInitAckSchema,
  serverStreamChunkSchema,
} from "./schema";
import {
  assertShape,
  expectBoolean,
  expectEnumValue,
  expectNonEmptyString,
  expectNonNegativeInteger,
  expectNonNegativeNumber,
  expectOptionalNonEmptyString,
  expectOptionalNonNegativeInteger,
  expectRecord,
  expectSemver,
  throwInvalidField,
} from "./shared";

export function validateServerStreamChunk(record: Record<string, unknown>, version: string): ServerStreamChunkEvent {
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

export function validateServerError(record: Record<string, unknown>, version: string): ServerErrorEvent {
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

export function validateServerInitAck(record: Record<string, unknown>, version: string): ServerInitAckEvent {
  const eventName = "server_init_ack";
  assertShape(record, serverInitAckSchema, version, eventName);
  const status = expectEnumValue(
    record.status,
    allowedInitAckStatuses,
    version,
    eventName,
    "status",
  );

  return {
    event: eventName,
    session_id: expectNonEmptyString(record.session_id, version, "session_id", eventName),
    server_version: expectSemver(record.server_version, version, eventName, "server_version"),
    status,
    message: expectOptionalNonEmptyString(record.message, version, "message", eventName),
    timestamp: expectNonNegativeInteger(record.timestamp, version, eventName, "timestamp"),
  };
}

function expectVisemeFrames(value: unknown, version: string): VisemeFrame[] {
  if (!Array.isArray(value)) {
    throwInvalidField(version, "server_stream_chunk", "visemes", "must be an array");
  }

  return value.map((item, index) => {
    const record = expectRecord(item, version);
    const frameValue = expectEnumValue(
      record.value,
      allowedVisemeValues,
      version,
      "server_stream_chunk",
      `visemes.${index}.value`,
    );

    return {
      time: expectNonNegativeNumber(record.time, version, "server_stream_chunk", `visemes.${index}.time`),
      value: frameValue,
    };
  });
}
