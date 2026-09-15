import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const sourceDir = dirname(fileURLToPath(import.meta.url));
const entry = readFileSync(resolve(sourceDir, "styles.css"), "utf8");
const modules = [
  ...entry.matchAll(/@import "(\.\/styles\/[^";]+\.css)";/g),
].map((match) => match[1]);

function parse(css: string) {
  const element = document.createElement("style");
  element.textContent = css;
  document.head.appendChild(element);
  const rules = Array.from(element.sheet!.cssRules);
  element.remove();
  return rules;
}

describe("stylesheet organization", () => {
  test("loads foundations before shared components and pages, without duplicates", () => {
    expect(modules.slice(0, 4)).toEqual([
      "./styles/global.css",
      "./styles/layout.css",
      "./styles/components.css",
      "./styles/asset-preview.css",
    ]);
    expect(modules).toHaveLength(15);
    expect(new Set(modules).size).toBe(modules.length);
    expect(
      parse(entry).every((rule) => rule.type === CSSRule.IMPORT_RULE),
    ).toBe(true);
  });

  for (const module of modules) {
    test(`${module}: valid rules, page-local breakpoints, no duplicate selector blocks`, () => {
      const css = readFileSync(resolve(sourceDir, module), "utf8");
      // A subpage is intentionally a new base/responsive section at the parent's end.
      const sections = css.split(/\/\* Subpage:[\s\S]*?\*\//);
      expect(sections.length).toBe(
        /\/(interviews|scripts)\.css$/.test(module) ? 2 : 1,
      );
      for (const section of sections) {
        const rules = parse(section);
        expect(rules.length).toBeGreaterThan(0);
        const selectors = new Set<string>();
        const conditions = new Set<string>();
        let responsive = false;
        let previousWidth = Infinity;
        for (const rule of rules) {
          if (rule.type === CSSRule.MEDIA_RULE) {
            responsive = true;
            const media = rule as CSSMediaRule;
            expect(conditions.has(media.conditionText)).toBe(false);
            conditions.add(media.conditionText);
            const width = Number(
              media.conditionText.match(/max-width:\s*(\d+)/)?.[1] ?? -1,
            );
            expect(width).toBeLessThanOrEqual(previousWidth);
            previousWidth = width;
            const mediaSelectors = new Set<string>();
            for (const child of Array.from(media.cssRules) as CSSStyleRule[]) {
              expect(mediaSelectors.has(child.selectorText)).toBe(false);
              mediaSelectors.add(child.selectorText);
            }
          } else if (rule.type === CSSRule.STYLE_RULE) {
            expect(responsive).toBe(false);
            const style = rule as CSSStyleRule;
            expect(selectors.has(style.selectorText)).toBe(false);
            expect(style.style.length).toBeGreaterThan(0);
            selectors.add(style.selectorText);
          }
        }
      }
    });
  }
});
