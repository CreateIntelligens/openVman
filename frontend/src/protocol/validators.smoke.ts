import {
  checkVersionCompatible,
  loadProtocolContract,
  validateClientEvent,
  validateServerEvent,
} from "./validators";
import type {
  ClientInterruptEvent,
  ServerErrorEvent,
  ServerInitAckEvent,
} from "../../../../contracts/generated/typescript/protocol-contracts";

const contract = loadProtocolContract();
const clientPayload: ClientInterruptEvent = {
  event: "client_interrupt",
  timestamp: 1710123465,
};
const serverPayload: ServerErrorEvent = {
  event: "server_error",
  error_code: "INTERNAL_ERROR",
  message: "smoke",
  timestamp: 1710123480,
};
const ackPayload: ServerInitAckEvent = {
  event: "server_init_ack",
  session_id: "sess_smoke",
  server_version: "1.0.0",
  status: "ok",
  timestamp: 1710200000,
};
const clientEvent = validateClientEvent(clientPayload);
const serverEvent = validateServerEvent(serverPayload);
const ackEvent = validateServerEvent(ackPayload);
const compatible = checkVersionCompatible("1.0.0", "1.2.0");
const incompatible = checkVersionCompatible("1.0.0", "2.0.0");

console.log(
  JSON.stringify({
    version: contract.version,
    client_event: clientEvent.event,
    server_event: serverEvent.event,
    ack_event: ackEvent.event,
    compatible,
    incompatible,
  }),
);
