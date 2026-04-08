import type {
  ClientEvent,
  ProtocolDirection,
  ServerEvent,
} from "@contracts/generated/typescript/protocol-contracts";
import {
  validateClientAudioChunk,
  validateClientAudioEnd,
  validateClientInit,
  validateClientInterrupt,
  validateUserSpeak,
} from "./validators/client";
import { DEFAULT_PROTOCOL_VERSION, manifest } from "./validators/schema";
import {
  assertSupportedVersion,
  buildContractEvents,
  expectEventName,
  expectRecord,
  ProtocolValidationError,
} from "./validators/shared";
import {
  validateServerError,
  validateServerInitAck,
  validateServerStopAudio,
  validateServerStreamChunk,
  validateSetLipSyncMode,
} from "./validators/server";

export { DEFAULT_PROTOCOL_VERSION, ProtocolValidationError };

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
    case "client_audio_chunk":
      return validateClientAudioChunk(record, version);
    case "client_audio_end":
      return validateClientAudioEnd(record, version);
    case "set_lip_sync_mode":
      return validateSetLipSyncMode(record, version);
    case "server_stream_chunk":
      return validateServerStreamChunk(record, version);
    case "server_error":
      return validateServerError(record, version);
    case "server_init_ack":
      return validateServerInitAck(record, version);
    case "server_stop_audio":
      return validateServerStopAudio(record, version);
    default:
      throw new ProtocolValidationError(
        `Unsupported protocol event \`${eventName}\``,
        version,
        eventName,
      );
  }
}

export function checkVersionCompatible(clientVersion: string, serverVersion: string): boolean {
  return getMajorVersion(clientVersion) === getMajorVersion(serverVersion);
}

function getMajorVersion(version: string): string {
  return version.split(".")[0] ?? "";
}
