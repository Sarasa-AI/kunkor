const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const http = require("node:http");
const net = require("node:net");
const test = require("node:test");
const { once } = require("node:events");

test("production Next health proxy handles synthetic upstream responses safely", {
  timeout: 20000,
}, async () => {
  const sentinel = "PRIVATE_RUNTIME_SYNTHETIC_SECRET";
  let behavior = "ok";
  let healthRequests = 0;
  const backend = http.createServer((request, response) => {
    assert.equal(request.url, "/healthz");
    healthRequests += 1;
    if (behavior === "stall") return;
    response.setHeader("Content-Type", "application/json");
    if (behavior === "failure") {
      response.writeHead(503);
      response.end(JSON.stringify({ detail: sentinel }));
    } else if (behavior === "malformed") {
      response.end(JSON.stringify({ status: sentinel }));
    } else {
      response.end(JSON.stringify({ status: "ok", debug: sentinel }));
    }
  });
  backend.listen(0, "127.0.0.1");
  await once(backend, "listening");
  const backendPort = backend.address().port;
  const reservation = net.createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const webPort = reservation.address().port;
  await new Promise((resolve) => reservation.close(resolve));
  const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start",
    "-H", "127.0.0.1", "-p", String(webPort)], {
    cwd: process.cwd(),
    env: { ...process.env, INTERNAL_API_URL: `http://127.0.0.1:${backendPort}/`,
      NEXT_TELEMETRY_DISABLED: "1", NODE_ENV: "production" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  child.stdout.on("data", (data) => { logs += data; });
  child.stderr.on("data", (data) => { logs += data; });
  const url = `http://127.0.0.1:${webPort}/api/healthz`;
  try {
    let response;
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      assert.equal(child.exitCode, null, logs);
      try {
        response = await fetch(url, { signal: AbortSignal.timeout(1000) });
        break;
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
    assert.ok(response, logs);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { status: "ok" });
    assert.ok(healthRequests > 0, "INTERNAL_API_URL must target the synthetic upstream");

    behavior = "failure";
    response = await fetch(url);
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { status: "error", code: 503 });

    behavior = "malformed";
    response = await fetch(url);
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { status: "error", message: "Backend unavailable" });

    behavior = "stall";
    const started = performance.now();
    response = await fetch(url, { signal: AbortSignal.timeout(6000) });
    assert.equal(response.status, 502);
    assert.ok(performance.now() - started < 5000, "upstream timeout must remain bounded");
    assert.deepEqual(await response.json(), { status: "error", message: "Backend unavailable" });
    assert.ok(!logs.includes(sentinel), "upstream private data must not enter Next logs");
  } finally {
    child.kill("SIGTERM");
    if (child.exitCode === null) await once(child, "exit");
    backend.closeAllConnections();
    await new Promise((resolve) => backend.close(resolve));
  }
});
