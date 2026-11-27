import { readFileSync } from "node:fs";

// Test credentials for operators created in the development organization
// (generated on the Sprite; stored only in the gitignored frontend/.env.e2e).
export function e2eSecret(name: string): string {
  if (process.env[name]) return process.env[name] as string;
  const line = readFileSync(".env.e2e", "utf8")
    .split("\n")
    .find((l) => l.startsWith(`${name}=`));
  if (!line) throw new Error(`${name} missing from .env.e2e`);
  return line.slice(name.length + 1).trim();
}
