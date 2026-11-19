const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

// Execute the actual route with NextResponse; only the upstream transport is synthetic.
const source = fs.readFileSync(path.join(__dirname, "../src/app/api/healthz/route.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const sentinel = "PRIVATE_SYNTHETIC_STUDENT_SECRET";

function route(fetch, env = {}) {
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, require, fetch, process: { env }, AbortSignal,
  });
  return exports.GET;
}

test("internal URL, cache policy and bounded timeout are used", async () => {
  let request;
  const get = route(async (url, options) => {
    request = { url, options };
    return Response.json({ status: "ok" });
  }, { INTERNAL_API_URL: "http://synthetic-api:8000/" });
  const response = await get();
  assert.equal(request.url, "http://synthetic-api:8000/healthz");
  assert.equal(request.options.cache, "no-store");
  assert.ok(request.options.signal instanceof AbortSignal);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok" });
});

test("fallback URL is local when INTERNAL_API_URL is absent", async () => {
  let requested;
  const get = route(async (url) => {
    requested = url;
    return Response.json({ status: "ok" });
  });
  assert.equal((await get()).status, 200);
  assert.equal(requested, "http://127.0.0.1:8008/healthz");
});

test("successful upstream data is projected to the public health contract", async () => {
  const response = await route(async () => Response.json({
    status: "ok", debug: sentinel, student: { name: sentinel },
  }))();
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok" });
});

test("non-success upstream body is never disclosed", async () => {
  const response = await route(async () => new Response(sentinel, { status: 503 }))();
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { status: "error", code: 503 });
});

for (const payload of [null, [], {}, { status: sentinel }, { status: "error", debug: sentinel }]) {
  test(`unhealthy or malformed success payload is rejected: ${JSON.stringify(payload)}`, async () => {
    const response = await route(async () => Response.json(payload))();
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { status: "error", message: "Backend unavailable" });
  });
}

test("JSON parse failures disclose only a fixed message", async () => {
  const response = await route(async () => new Response(sentinel, { status: 200 }))();
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { status: "error", message: "Backend unavailable" });
});

test("fetch errors disclose only a fixed message", async () => {
  const response = await route(async () => { throw new Error(sentinel); })();
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { status: "error", message: "Backend unavailable" });
});

test("an upstream request that stalls is aborted within the configured deadline", async () => {
  const started = performance.now();
  const keepAlive = setTimeout(() => {}, 6000);
  try {
    const response = await route((_url, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error(sentinel)), { once: true });
    }))();
    assert.equal(response.status, 502);
    assert.ok(performance.now() - started < 5000);
    assert.deepEqual(await response.json(), { status: "error", message: "Backend unavailable" });
  } finally {
    clearTimeout(keepAlive);
  }
});
