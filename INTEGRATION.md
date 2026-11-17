# API Anything

API Anything is a sibling, not part of gpt-bridge. The checkout is `api-anything/`. Its code is not imported by the Python package, and gpt-bridge does not call it. License: MIT. Source: https://github.com/goodnight000/api-anything

It learns a website's own request, calls that request over HTTP, and repairs the learned request when the site changes. Cookies and tokens stay on the machine that learned them. The shared catalog strips them before anything is shared.

## Learn, call, repair

Learn means a browser loads a page twice, with two example values. The value that changes becomes a parameter. The rest of the request is kept as the site sent it. Cookies become local references, not values in the saved spec.

Call means Node sends that saved request. If the site blocks plain HTTP, it retries from inside a browser page. A read can, as a last resort, run the page and read the answer.

Repair means a call that no longer fits is learned again, and the new version is saved only after a replay works. A call that cannot be repaired returns an error. It does not return someone else's data.

## Setup on the PC

Node 22.13 or newer. No account and no API key.

```bash
npx -y api-anything setup
```

That asks which local agents to connect. To keep learning on this machine and share nothing:

```bash
npx -y api-anything setup --local-only
```

The sibling checkout can also be built, but the published command above is the one to use:

```bash
cd api-anything
npm ci
npm run build
```

`npm run build` runs `tsc -p tsconfig.build.json`. The package binary is `api-anything`.

## Point it at a site

Use a page URL and two input values, so it can tell a parameter from a nonce. This example is Hacker News, from API Anything's own docs. It is not ChatGPT.

```bash
api-anything capture "https://hn.algolia.com/?q=sqlite" --example q=sqlite
api-anything add hn-search search --trigger "https://hn.algolia.com/?q={query}" \
  --example query=sqlite --example2 query=postgres \
  --match host=uj5wyc0l7x-dsn.algolia.net \
  --extract hits --pick "title,url,points,comments=num_comments"
```

Do not run `add` or `learn` against ChatGPT unless you have read the candidate list and approved it. `scripts/api-anything-probe.sh` only captures and prints. It does not learn or call.

## Call a learned operation

From the shell:

```bash
api-anything call hn-search search query=duckdb
```

From Node:

```js
import { call } from "api-anything";

const result = await call("hn-search", "search", { query: "duckdb" });
```

A failure has `class`, `reason`, and `next`. `tier: 1` means one plain HTTP request.

## Serve on loopback

```bash
npx -y api-anything serve
```

It listens on `127.0.0.1:8787` only unless you change `--host`. It prints one JSON line with `url`, `mcp`, and `openapi`. The token is in `~/.api-anything/serve-token`. It is not printed. Every request except `GET /v1/health` needs `Authorization: Bearer <token>`.

REST is under `/v1/...`. MCP is at `/mcp`. The OpenAPI document is `GET /openapi.json`.

```bash
TOKEN=$(cat ~/.api-anything/serve-token)
curl -s http://127.0.0.1:8787/v1/health
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/v1/sites
```

Writes stay off unless the process is started with `--allow-writes`. Do not bind this server to `0.0.0.0`. A public tunnel in front of it would expose every signed-in site that API Anything holds. Leave it on loopback.

## Probe

```bash
bash scripts/api-anything-probe.sh
```

The script checks that `api-anything` is installed, then runs:

```bash
api-anything capture "https://chatgpt.com/" --example q=example
```

It prints the candidate request list and redacts cookie and token-like values. It does not run `learn`, `add`, or `call`. This is a read-only probe. No write is sent. No session is captured beyond what you explicitly approve by running the script. You decide whether the traffic is clean enough to become an operation.
