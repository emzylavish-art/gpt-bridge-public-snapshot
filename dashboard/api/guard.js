const crypto = require("crypto");

module.exports = async function handler(req, res) {
  const expected = process.env.BRIDGE_API_KEY_SHA256 || "";
  const secret = process.env.BRIDGE_INTERNAL_SECRET || "";
  const upstream = (process.env.BRIDGE_UPSTREAM || "").replace(/\/$/, "");
  const auth = req.headers.authorization || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  const hash = crypto.createHash("sha256").update(token).digest("hex");
  if (!expected || hash !== expected) {
    res.status(401).json({ detail: "invalid api key" });
    return;
  }
  if (!upstream || /localhost|127\.0\.0\.1/.test(upstream)) {
    res.status(503).json({ detail: "Vercel cannot reach a localhost bridge" });
    return;
  }
  const path = String(req.query.path || "/dashboard-data");
  if (!path.startsWith("/")) {
    res.status(400).json({ detail: "bad path" });
    return;
  }
  const response = await fetch(upstream + path, {
    method: req.method,
    headers: {
      Authorization: auth,
      "X-GPT-Bridge-Secret": secret,
      "Content-Type": "application/json",
    },
    body: req.method === "GET" || req.method === "HEAD" ? undefined : JSON.stringify(req.body || {}),
  });
  const text = await response.text();
  res.status(response.status).send(text);
};
