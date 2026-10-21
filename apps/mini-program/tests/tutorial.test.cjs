const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(
  path.join(__dirname, "../src/shared/tutorial.ts"),
  "utf8",
);
const exportsObject = {};
vm.runInNewContext(
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText,
  { exports: exportsObject },
);
const { tutorialLayout } = exportsObject;

function checkFit(layout, frame, viewport) {
  const { panel, spotlight } = layout;
  assert.ok(panel.left >= frame.left);
  assert.ok(panel.left + panel.width <= frame.left + frame.width);
  assert.ok(panel.top >= 12);
  assert.ok(
    panel.top + Math.min(220, panel.maxHeight) <=
      viewport.height - viewport.bottomInset - 12,
  );
  if (spotlight) {
    const before = panel.top + Math.min(220, panel.maxHeight) <= spotlight.top;
    const after = panel.top >= spotlight.top + spotlight.height;
    assert.ok(
      before || after,
      "tooltip must not cover the highlighted control",
    );
  }
}

test("tour tooltip stays on-screen and clear of controls at portrait widths", () => {
  for (const width of [320, 390, 430]) {
    for (const top of [80, 300, 650]) {
      const frame = { left: 0, top: 0, width, height: 844 };
      const viewport = { width, height: 844, bottomInset: 34 };
      const target = { left: 16, top, width: width - 32, height: 44 };
      const layout = tutorialLayout(target, frame, viewport, 220);
      assert.ok(layout.spotlight);
      checkFit(layout, frame, viewport);
    }
  }
});

test("bottom controls place the tooltip above and respect the safe area", () => {
  const frame = { left: 0, top: 0, width: 390, height: 844 };
  const viewport = { width: 390, height: 844, bottomInset: 34 };
  const layout = tutorialLayout(
    { left: 200, top: 735, width: 120, height: 44 },
    frame,
    viewport,
    220,
  );
  assert.equal(layout.side, "above");
  checkFit(layout, frame, viewport);
});

test("desktop preview keeps the tooltip inside the centered mini-program", () => {
  const frame = { left: 505, top: 0, width: 430, height: 900 };
  const viewport = { width: 1440, height: 900, bottomInset: 0 };
  const layout = tutorialLayout(
    { left: 875, top: 100, width: 44, height: 44 },
    frame,
    viewport,
    220,
  );
  checkFit(layout, frame, viewport);
});

test("unavailable or off-screen targets do not leave a misleading spotlight", () => {
  const frame = { left: 0, top: 0, width: 320, height: 568 };
  const viewport = { width: 320, height: 568, bottomInset: 0 };
  for (const target of [null, { left: 20, top: 900, width: 44, height: 44 }]) {
    const layout = tutorialLayout(target, frame, viewport, 220);
    assert.equal(layout.spotlight, null);
    checkFit(layout, frame, viewport);
  }
});
