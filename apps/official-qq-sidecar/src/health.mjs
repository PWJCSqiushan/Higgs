import { getJson } from "./uds-client.mjs";

const socketPath = process.env.HIGGS_OFFICIAL_QQ_SOCKET ?? "/run/higgs-official/sidecar.sock";

getJson(socketPath, "/v1/hello", 2000).then(
  (value) => {
    if (value?.protocol_version !== 1 || typeof value?.generation !== "string") {
      process.exitCode = 1;
    }
  },
  () => {
    process.exitCode = 1;
  },
);
