// Static regression tests: run `node --test tests/ui.test.js` from frontend/web
const test = require("node:test"), assert = require("node:assert"), fs = require("fs"), path = require("path");
const r = (f) => fs.readFileSync(path.join(__dirname, "..", f), "utf8");
const js = r("assets/app.js"), css = r("assets/styles.css"), html = r("index.html");

test("app.js parses", () => { new Function(js); });
test("theme toggle is accessible and persisted", () => {
  assert.match(html, /id="theme"[^>]*aria-label=/);
  assert.match(html, /aria-pressed/);
  assert.match(js, /localStorage\.setItem\("torob_che_theme"/);
  assert.match(css, /:root\[data-theme="dark"\]/);
});
test("dark theme defines every core variable", () => {
  const dark = css.match(/:root\[data-theme="dark"\] \{([^}]*)\}/)[1];
  for (const v of ["--ink", "--bg", "--card", "--line", "--muted", "--surface", "--red"]) assert.ok(dark.includes(v + ":"), v);
  assert.ok(!/background:\s*#fff;/.test(css.replace(/--[^;]*;/g, "")), "no hard-coded white surfaces");
});
test("no bottom-follow scrolling", () => {
  assert.ok(!/scrollTop\s*=\s*feed\.scrollHeight/.test(js));
  assert.ok(!/scroll-behavior:\s*smooth/.test(css));
  assert.match(js, /awaitingScroll = false;/);
  assert.match(js, /noScroll: true/);
});

test("shop cards are clickable and plan has map + directions", () => {
  assert.match(js, /type: "choose_shop"/);
  assert.match(js, /role="button" tabindex="0"/);
  assert.match(js, /function renderMap/);
  assert.match(js, /openstreetmap\.org\/directions/);
  assert.match(html, /torob-logo\.png/);
});
