// Tests for the page's reply formatting (escaping, *italic*/**bold**, streaming).
// Runs the code straight out of static/index.html, so there's nothing to keep in sync.
//   node tests/test_format.mjs
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
const start = html.indexOf("const esc =");
const end = html.indexOf("function fill(");
assert.ok(start > 0 && end > start, "couldn't find the formatting code in index.html");
const { esc, paras, inline } = new Function(`${html.slice(start, end)}\nreturn { esc, paras, inline };`)();

let n = 0;
const test = (name, fn) => { fn(); n++; console.log("ok  ", name); };
const f = s => paras(s, true);                 // a finished reply
const live = s => paras(s, true, true);        // a reply while it streams

// every tag in the output is one of ours, and they nest properly
function balanced(out) {
  const stack = [];
  for (const [, close, name] of out.matchAll(/<(\/?)([a-z]+)>/g)) {
    assert.ok(["p", "em", "strong"].includes(name) || (name === "br" && !close), `unexpected tag ${name} in ${out}`);
    if (name === "br") continue;
    if (!close) stack.push(name);
    else assert.equal(stack.pop(), name, `misnested ${name} in ${out}`);
  }
  assert.equal(stack.length, 0, `unclosed tags in ${out}`);
  assert.ok(!/<(?!\/?(p|em|strong|br)>)/.test(out), `stray < in ${out}`);
}

test("italic and bold, both spellings", () => {
  assert.equal(f("That's *unfortunate*."), "<p>That&#39;s <em>unfortunate</em>.</p>");
  assert.equal(f("That's _unfortunate_."), "<p>That&#39;s <em>unfortunate</em>.</p>");
  assert.equal(f("I am **magnificent**, obviously."), "<p>I am <strong>magnificent</strong>, obviously.</p>");
  assert.equal(f("__Me__ first"), "<p><strong>Me</strong> first</p>");
  assert.equal(f("*a* and *b*"), "<p><em>a</em> and <em>b</em></p>");
  assert.equal(f("***both***"), "<p><em><strong>both</strong></em></p>");
  assert.equal(f("*so **very** tired*"), "<p><em>so <strong>very</strong> tired</em></p>");
  assert.equal(f("**so *very* tired**"), "<p><strong>so <em>very</em> tired</strong></p>");
});

test("lone and unmatched markers stay literal", () => {
  for (const s of ["5 * 3 = 15", "a * b", "*", "**", "* list item", "I *really", "snake_case_name", "2*3*4",
                   "file_name and other_name", "** not bold **", "* not italic *", "a_b_ c"])
    assert.equal(f(s), `<p>${esc(s)}</p>`, s);
});

test("emphasis doesn't cross lines or paragraphs", () => {
  assert.equal(f("*one\ntwo*"), "<p>*one<br>two*</p>");
  assert.equal(f("*one\n\ntwo*"), "<p>*one</p><p>two*</p>");
  assert.equal(f("Line *one*\nline **two**\n\nNext"), "<p>Line <em>one</em><br>line <strong>two</strong></p><p>Next</p>");
});

test("escapes first, so model text can't inject markup", () => {
  const evil = ['<img src=x onerror=alert(1)>', '*<b>x</b>*', '**<script>alert(1)</script>**', '_"onmouseover="x_',
                '*a<em>b*', '<strong>*x*</strong>', '&lt;em&gt;', '*x</em><em>y*'];
  for (const s of evil) {
    for (const out of [f(s), live(s)]) {
      balanced(out);
      assert.ok(!out.includes("<img") && !out.includes("<script") && !out.includes("<b>") && !/<[a-z]+ /.test(out), out);
    }
  }
  assert.equal(f("*<b>x</b>*"), "<p><em>&lt;b&gt;x&lt;/b&gt;</em></p>");
});

test("without formatting (the fixed safety text), nothing changes", () => {
  assert.equal(paras("Keep *this* as is\n\nand **this**"), "<p>Keep *this* as is</p><p>and **this**</p>");
});

test("streaming: every prefix renders balanced, and an open marker never shows", () => {
  const replies = ["Well, that's *unfortunate*. For you, I mean.", "I am **the best** listener, *obviously*.",
                   "*Sigh.* Fine.\n\nTell me **more** about _yourself_ — no, about *me*.", "5 * 3 is **15**", "a **b *c* d** e",
                   "*a **b** c*", "x _y_ z __w__"];
  for (const r of replies) {
    for (let i = 1; i <= r.length; i++) {
      const out = live(r.slice(0, i));
      balanced(out);
      // the last line never ends in a raw marker (it's held back or already formatted)
      assert.ok(!/[*_]<\/p>$/.test(out), `${JSON.stringify(r.slice(0, i))} -> ${out}`);
    }
    assert.equal(live(r), f(r), r);           // complete text renders the same live and final
  }
});

test("streaming: an opened emphasis formats as it arrives", () => {
  assert.equal(live("That's *unfort"), "<p>That&#39;s <em>unfort</em></p>");
  assert.equal(live("That's *unfortunate*"), "<p>That&#39;s <em>unfortunate</em></p>");
  assert.equal(live("I am **magni"), "<p>I am <strong>magni</strong></p>");
  assert.equal(live("I am **magnificent*"), "<p>I am <strong>magnificent</strong></p>");
  assert.equal(live("I am *"), "<p>I am </p>");
  assert.equal(live("*a* then *b"), "<p><em>a</em> then <em>b</em></p>");
  assert.equal(live("**a *b* c"), "<p><strong>a <em>b</em> c</strong></p>");
  // only the last line is live; earlier lines are final
  assert.equal(live("*one\ntwo"), "<p>*one<br>two</p>");
  // a lone marker mid-stream stays literal (only an opener is formatted)
  assert.equal(live("5 * 3"), "<p>5 * 3</p>");
});

test("inline() alone keeps escaped entities intact", () => {
  assert.equal(inline(esc('"*quoted*"')), "&quot;<em>quoted</em>&quot;");
  assert.equal(inline(esc("it's *fine*")), "it&#39;s <em>fine</em>");
});

console.log(`\n${n} tests passed`);
