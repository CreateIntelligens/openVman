import {
  loadProtocolContract,
  validateClientEvent,
  validateServerEvent,
} from "./validators";

const contract = loadProtocolContract();
const clientEvent = validateClientEvent({
  event: "client_interrupt",
  timestamp: 1710123465,
});
const serverEvent = validateServerEvent({
  event: "server_error",
  error_code: "INTERNAL_ERROR",
  message: "smoke",
  timestamp: 1710123480,
});

console.log(
  JSON.stringify({
    version: contract.version,
    client_event: clientEvent.event,
    server_event: serverEvent.event,
  }),
);
