const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

// Exercise Docker's matcher against synthetic contexts; never copy actual secret files.
const repository = path.resolve(__dirname, "../../..");
for (const directory of ["apps/web", "services/api"]) {
  test(`${directory} excludes root and nested environment files and private keys`, () => {
    const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "kunkor-context-regression-"));
    const context = path.join(fixture, "context");
    const output = path.join(fixture, "output");
    fs.mkdirSync(path.join(context, "nested"), { recursive: true });
    fs.writeFileSync(path.join(context, "Dockerfile"), "FROM scratch\nCOPY . /\n");
    fs.copyFileSync(path.join(repository, directory, ".dockerignore"), path.join(context, ".dockerignore"));
    for (const prefix of ["", "nested"]) {
      for (const filename of [".env", ".env.local", "service.pem", "service.key", "service.p12",
        "service.pfx", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "visible.txt"]) {
        fs.writeFileSync(path.join(context, prefix, filename), "SYNTHETIC_FIXTURE\n");
      }
      fs.mkdirSync(path.join(context, prefix, ".ssh"));
      fs.writeFileSync(path.join(context, prefix, ".ssh", "identity"), "SYNTHETIC_FIXTURE\n");
    }
    execFileSync("docker", ["buildx", "build", "--network=none", "--output",
      `type=local,dest=${output}`, context], { stdio: "pipe", timeout: 30000 });
    const files = fs.readdirSync(output, { recursive: true }).filter((name) =>
      fs.statSync(path.join(output, name)).isFile()).sort();
    assert.deepEqual(files, [".dockerignore", "Dockerfile", "nested/visible.txt", "visible.txt"]);
    console.info(`Verified synthetic Docker context: ${directory}; fixture ${fixture}`);
  });
}
