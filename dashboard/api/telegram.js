module.exports = async function handler(req, res) {
  const token = process.env.TELEGRAM_BOT_TOKEN || "";
  if (!token) {
    res.status(503).json({ ok: false, detail: "TELEGRAM_BOT_TOKEN is not set" });
    return;
  }
  if (req.method !== "GET") {
    res.status(405).json({ detail: "GET only. Chat capture and buttons stay on the bridge." });
    return;
  }
  const me = await fetch("https://api.telegram.org/bot" + token + "/getMe").then((item) => item.json());
  if (!me.ok) {
    res.status(502).json(me);
    return;
  }
  res.json({
    ok: true,
    username: me.result.username,
    start_url: "https://t.me/" + me.result.username + "?start=gptbridge",
  });
};
