import {
  loadProtocolContract,
  validateClientEvent,
  validateServerEvent,
} from "./validators";
import type {
  ClientInterruptEvent,
  ServerErrorEvent,
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
const clientEvent = validateClientEvent(clientPayload);
const serverEvent = validateServerEvent(serverPayload);

console.log(
  JSON.stringify({
    version: contract.version,
    client_event: clientEvent.event,
    server_event: serverEvent.event,
  }),
);
