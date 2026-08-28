import { chmodSync } from "node:fs";
import { createServer } from "node:http";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { OfficialQQClient } from "./qq-client.mjs";
import {
  MAX_BODY_BYTES,
  PROTOCOL_VERSION,
  ProtocolError,
  normalizeSendRequest,
} from "./protocol.mjs";

function boolEnv(value, fallback = false) {
  if (value === undefined || value === "") return fallback;
  if (value === "true") return true;
  if (value === "false") return false;
  throw new Error("invalid boolean configuration");
}

export function loadConfig(env = process.env) {
  const enabled = boolEnv(env.HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED, false);
  const captureOnly = boolEnv(env.HIGGS_OFFICIAL_QQ_CAPTURE_ONLY, true);
  const appId = String(env.QQBOT_APP_ID ?? "").trim();
  const appSecret = String(env.QQBOT_APP_SECRET ?? "").trim();
  const socketPath = resolve(env.HIGGS_OFFICIAL_QQ_SOCKET ?? "/run/higgs-official/sidecar.sock");
  if (enabled) {
    if (!/^\d{5,32}$/u.test(appId)) throw new Error("invalid AppID configuration");
    if (appSecret.length < 16 || appSecret.length > 512) {
      throw new Error("invalid AppSecret configuration");
    }
  }
  return Object.freeze({ enabled, captureOnly, appId, appSecret, socketPath });
}

function jsonResponse(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

async function readJson(request) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new ProtocolError("body_too_large", 413);
    chunks.push(chunk);
  }
  if (size === 0) throw new ProtocolError("empty_body");
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ProtocolError("invalid_json");
  }
}

export function createHandler(client) {
  return async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://sidecar.local");
      if (request.method === "GET" && url.pathname === "/v1/hello") {
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          generation: client.generation,
        });
      }
      if (request.method === "GET" && url.pathname === "/v1/status") {
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          ...client.status(),
        });
      }
      if (request.method === "GET" && url.pathname === "/v1/events") {
        const after = Number(url.searchParams.get("after") ?? "0");
        const limit = Number(url.searchParams.get("limit") ?? "32");
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          generation: client.generation,
          events: client.readEvents(after, limit),
        });
      }
      if (request.method === "POST" && url.pathname === "/v1/send") {
        const payload = normalizeSendRequest(await readJson(request));
        const receipt = await client.send(payload);
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          generation: client.generation,
          receipt,
        });
      }
      return jsonResponse(response, 404, { error: "not_found" });
    } catch (error) {
      if (error instanceof ProtocolError) {
        return jsonResponse(response, error.status, { error: error.code });
      }
      return jsonResponse(response, 500, { error: "internal_error" });
    }
  };
}

export async function run(env = process.env) {
  const config = loadConfig(env);
  const client = new OfficialQQClient(config);
  const server = createServer(createHandler(client));
  server.requestTimeout = 5000;
  server.headersTimeout = 5000;
  server.keepAliveTimeout = 2000;
  server.maxRequestsPerSocket = 100;

  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(config.socketPath, () => {
      server.off("error", rejectListen);
      chmodSync(config.socketPath, 0o600);
      resolveListen();
    });
  });

  try {
    await client.start();
  } catch {
    await new Promise((resolveClose) => server.close(resolveClose));
    throw new Error("sidecar_start_failed");
  }

  const shutdown = async () => {
    server.closeIdleConnections();
    await new Promise((resolveClose) => server.close(resolveClose));
    await client.stop();
  };
  process.once("SIGTERM", () => void shutdown());
  process.once("SIGINT", () => void shutdown());
  return { client, server, shutdown };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  run().catch(() => {
    process.exitCode = 1;
  });
}
