const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname, "../src/app/api/admin/content/[...path]/route.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const syntheticKey = "SYNTHETIC_OWNER_KEY";
const bookId = "00000000-0000-4000-8000-000000000001";

function route(fetch) {
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, require, fetch, process: { env: { INTERNAL_API_URL: "http://synthetic-backend:8000/" } }, AbortSignal, URL,
  });
  return exports;
}

function request(method = "GET", key = syntheticKey, origin = "https://kunkor.example", body = {}) {
  return new Request("https://kunkor.example/api/admin/content/books", {
    method,
    headers: { ...(key ? { "X-Admin-Api-Key": key } : {}), ...(origin ? { origin } : {}) },
    ...(method !== "GET" ? { body: JSON.stringify(body) } : {}),
  });
}

const context = (...path) => ({ params: Promise.resolve({ path }) });

test("empty catalog is returned without caching and forwards only the supplied key", async () => {
  let upstream;
  const response = await route(async (url, options) => {
    upstream = { url, options };
    return Response.json([]);
  }).GET(request(), context("books"));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), []);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.equal(upstream.url, "http://synthetic-backend:8000/admin/content/books");
  assert.equal(upstream.options.headers["X-Admin-Api-Key"], syntheticKey);
  assert.equal(upstream.options.cache, "no-store");
  assert.equal(upstream.options.redirect, "error");
  assert.equal(upstream.options.headers.cookie, undefined);
  assert.ok(upstream.options.signal instanceof AbortSignal);
});

test("missing credentials are rejected before contacting backend", async () => {
  const response = await route(() => { throw new Error("must not fetch"); }).GET(request("GET", ""), context("books"));
  assert.equal(response.status, 401);
});

test("cross origin and missing origin mutations are rejected", async () => {
  for (const origin of ["https://attacker.example", ""]) {
    const response = await route(() => { throw new Error("must not fetch"); }).POST(request("POST", syntheticKey, origin), context("books"));
    assert.equal(response.status, 403);
  }
});

test("owner can save a single incomplete resource and publish an individual unit", async () => {
  let payload;
  const handlers = route(async (url, options) => {
    payload = JSON.parse(options.body);
    return Response.json({ id: bookId, status: url.endsWith("publish") ? "published" : "draft" }, { status: 201 });
  });
  const created = await handlers.POST(request("POST", syntheticKey, undefined, { title: "Synthetic draft" }), context("books"));
  assert.equal(created.status, 201);
  assert.deepEqual(payload, { title: "Synthetic draft" });
  const published = await handlers.POST(request("POST"), context("units", bookId, "publish"));
  assert.equal((await published.json()).status, "published");
});

test("unknown methods and paths cannot turn proxy into a general backend tunnel", async () => {
  const handlers = route(() => { throw new Error("must not fetch"); });
  for (const segments of [["..", "operations"], ["books", "not-an-id"], ["units"], ["books", bookId, "delete"]]) {
    const response = await handlers.GET(request(), context(...segments));
    assert.equal(response.status, 404);
  }
  assert.equal((await handlers.PATCH(request("PATCH"), context("books"))).status, 404);
});

test("edits and audit history use allowlisted individual item routes", async () => {
  const requested = [];
  const handlers = route(async (url, options) => {
    requested.push({ url, method: options.method });
    return Response.json(options.method === "GET" ? [] : { id: bookId, status: "draft" });
  });
  assert.equal((await handlers.PATCH(request("PATCH"), context("units", bookId))).status, 200);
  assert.equal((await handlers.GET(request(), context("books", bookId, "audit"))).status, 200);
  assert.equal((await handlers.GET(request(), context("books", bookId, "units"))).status, 200);
  assert.equal(requested.length, 3);
});

test("license gate errors remain understandable while validation inputs stay private", async () => {
  const gate = await route(async () => Response.json({ detail: "Active usage rights are required." }, { status: 409 })).POST(request("POST"), context("books", bookId, "publish"));
  assert.equal(gate.status, 409);
  assert.deepEqual(await gate.json(), { detail: "Active usage rights are required." });
  const validation = await route(async () => Response.json({ detail: [{ input: syntheticKey, msg: "invalid" }] }, { status: 422 })).POST(request("POST"), context("books"));
  assert.equal(validation.status, 422);
  assert.ok(!(await validation.text()).includes(syntheticKey));
});

test("backend failures and malformed JSON never expose private diagnostics", async () => {
  for (const fetch of [
    async () => new Response(syntheticKey, { status: 500 }),
    async () => new Response(syntheticKey, { status: 200 }),
    async () => { throw new Error(syntheticKey); },
  ]) {
    const response = await route(fetch).GET(request(), context("books"));
    assert.equal(response.status, 502);
    assert.ok(!(await response.text()).includes(syntheticKey));
  }
});
