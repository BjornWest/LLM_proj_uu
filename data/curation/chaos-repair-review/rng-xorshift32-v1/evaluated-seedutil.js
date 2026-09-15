// packages/core/dist/seedutil.js
function seedFromString(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++)
    h = h * 31 + s.charCodeAt(i) | 0;
  return h >>> 0 || 1;
}
function paraphrase(rng, variants) {
  return rng.pick(variants);
}
var Seeded;
var init_seedutil = __esm({
  "packages/core/dist/seedutil.js"() {
    "use strict";
    Seeded = class {
      state;
      constructor(seed) {
        this.state = seed >>> 0 || 1;
      }
      next() {
        let x = this.state; x ^= x << 13; x ^= x >>> 17; x ^= x << 5; this.state = x >>> 0;
        return this.state;
      }
      pick(arr) {
        return arr[this.next() % arr.length];
      }
      /** Pick exactly one element from `arr` and remove it. */
      drawn(arr) {
        const idx = this.next() % arr.length;
        const [v] = arr.splice(idx, 1);
        return v;
      }
      intBetween(low, highInclusive) {
        return low + this.next() % (highInclusive - low + 1);
      }
      /** Random 8-char hex token, e.g. for opaque element ids. */
      hex(len = 8) {
        let out = "";
        while (out.length < len) {
          const r = this.next().toString(16);
          out += r;
        }
        return out.slice(0, len);
      }
      /** Shuffle array in place. */
      shuffle(arr) {
        for (let i = arr.length - 1; i > 0; i--) {
          const j = this.next() % (i + 1);
          [arr[i], arr[j]] = [arr[j], arr[i]];
        }
        return arr;
      }
    };
  }
});

