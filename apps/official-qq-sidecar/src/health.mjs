import { getJson } from "./uds-client.mjs";
import { isReadyStatus } from "./health-status.mjs";

const socketPath = process.env.HIGGS_OFFICIAL_QQ_SOCKET ?? "/run/higgs-official/sidecar.sock";

getJson(socketPath, "/v1/status", 2000).then(
  (value) => {
    if (!isReadyStatus(value)) {
      process.exitCode = 1;
    }
  },
  () => {
    process.exitCode = 1;
  },
);
