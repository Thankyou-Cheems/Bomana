/* Bomana QR encoder: byte mode + ECC level M, versions 1-10. No network/eval. */
"use strict";

(function (global) {
  // Tables for ECC level M only (versions 1..10).
  // [totalDataCodewords, eccPerBlock, numBlocks]
  const PROFILE = {
    1: [16, 10, 1],
    2: [28, 16, 1],
    3: [44, 26, 1],
    4: [64, 18, 2],
    5: [86, 24, 2],
    6: [108, 16, 4],
    7: [124, 18, 4],
    8: [154, 22, 4],
    9: [182, 22, 5],
    10: [216, 26, 5],
  };

  const ALIGNMENT = {
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
  };

  // GF(256) with primitive 0x11d
  const EXP = new Array(512);
  const LOG = new Array(256);
  (function initGf() {
    let x = 1;
    for (let i = 0; i < 255; i += 1) {
      EXP[i] = x;
      LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (let i = 255; i < 512; i += 1) EXP[i] = EXP[i - 255];
  })();

  function gfMul(a, b) {
    if (a === 0 || b === 0) return 0;
    return EXP[LOG[a] + LOG[b]];
  }

  function rsDivisor(degree) {
    const poly = [1];
    for (let i = 0, root = 1; i < degree; i += 1, root = gfMul(root, 2)) {
      poly.push(0);
      for (let j = poly.length - 1; j > 0; j -= 1) {
        poly[j] = poly[j - 1] ^ gfMul(poly[j], root);
      }
      poly[0] = gfMul(poly[0], root);
    }
    return poly; // highest degree first after reverse for remainder calc
  }

  function rsEncode(data, eccLen) {
    // divisor as lowest-degree-first coefficients length eccLen+1
    let gen = [1];
    for (let i = 0, root = 1; i < eccLen; i += 1, root = gfMul(root, 2)) {
      const next = new Array(gen.length + 1).fill(0);
      for (let j = 0; j < gen.length; j += 1) {
        next[j] ^= gen[j];
        next[j + 1] ^= gfMul(gen[j], root);
      }
      gen = next;
    }
    const res = new Array(eccLen).fill(0);
    for (let i = 0; i < data.length; i += 1) {
      const factor = data[i] ^ res[0];
      res.shift();
      res.push(0);
      if (factor === 0) continue;
      for (let j = 0; j < eccLen; j += 1) {
        res[j] ^= gfMul(gen[j + 1], factor);
      }
    }
    return res;
  }

  function getBytes(text) {
    return Array.from(new TextEncoder().encode(text));
  }

  function chooseVersion(byteLen) {
    for (let version = 1; version <= 10; version += 1) {
      const capacity = PROFILE[version][0];
      const lenBits = version <= 9 ? 8 : 16;
      const bits = 4 + lenBits + byteLen * 8;
      const need = Math.ceil((bits + 4) / 8); // + terminator up to 4 bits
      if (need <= capacity) return version;
    }
    return 0;
  }

  function encodeDataCodewords(text, version) {
    const data = getBytes(text);
    const capacity = PROFILE[version][0];
    const bits = [];
    function put(val, len) {
      for (let i = len - 1; i >= 0; i -= 1) bits.push((val >>> i) & 1);
    }
    put(0b0100, 4);
    put(data.length, version <= 9 ? 8 : 16);
    for (const b of data) put(b, 8);
    const maxBits = capacity * 8;
    const term = Math.min(4, maxBits - bits.length);
    put(0, term);
    while (bits.length % 8 !== 0) bits.push(0);
    const codewords = [];
    for (let i = 0; i < bits.length; i += 8) {
      let v = 0;
      for (let j = 0; j < 8; j += 1) v = (v << 1) | bits[i + j];
      codewords.push(v);
    }
    const pads = [0xec, 0x11];
    let p = 0;
    while (codewords.length < capacity) {
      codewords.push(pads[p]);
      p ^= 1;
    }
    return codewords;
  }

  function interleave(codewords, version) {
    const [, eccPerBlock, blockCount] = PROFILE[version];
    const totalData = PROFILE[version][0];
    const shortLen = Math.floor(totalData / blockCount);
    const numLong = totalData % blockCount;
    const shortBlocks = blockCount - numLong;
    const dataBlocks = [];
    const eccBlocks = [];
    let offset = 0;
    for (let i = 0; i < blockCount; i += 1) {
      const len = shortLen + (i < shortBlocks ? 0 : 1);
      const block = codewords.slice(offset, offset + len);
      offset += len;
      dataBlocks.push(block);
      eccBlocks.push(rsEncode(block, eccPerBlock));
    }
    const out = [];
    const maxLen = shortLen + (numLong > 0 ? 1 : 0);
    for (let i = 0; i < maxLen; i += 1) {
      for (const block of dataBlocks) {
        if (i < block.length) out.push(block[i]);
      }
    }
    for (let i = 0; i < eccPerBlock; i += 1) {
      for (const block of eccBlocks) out.push(block[i]);
    }
    return out;
  }

  function sizeOf(version) {
    return version * 4 + 17;
  }

  function isProtected(version, size, x, y) {
    if (x <= 8 && y <= 8) return true;
    if (x >= size - 8 && y <= 8) return true;
    if (x <= 8 && y >= size - 8) return true;
    if (x === 6 || y === 6) return true;
    if (x === 8 && y === size - 8) return true;
    const pos = ALIGNMENT[version];
    if (pos) {
      for (const ay of pos) {
        for (const ax of pos) {
          if ((ax === 6 && ay === 6)
            || (ax === 6 && ay === size - 7)
            || (ax === size - 7 && ay === 6)) continue;
          if (Math.abs(x - ax) <= 2 && Math.abs(y - ay) <= 2) return true;
        }
      }
    }
    return false;
  }

  function drawFinders(m, size) {
    function finder(ox, oy) {
      for (let y = -1; y <= 7; y += 1) {
        for (let x = -1; x <= 7; x += 1) {
          const xx = ox + x;
          const yy = oy + y;
          if (xx < 0 || yy < 0 || xx >= size || yy >= size) continue;
          const ring = x === -1 || x === 7 || y === -1 || y === 7
            || ((x === 0 || x === 6 || y === 0 || y === 6) && x >= 0 && x <= 6 && y >= 0 && y <= 6);
          const core = x >= 2 && x <= 4 && y >= 2 && y <= 4;
          m[yy][xx] = (ring || core) ? 1 : 0;
        }
      }
    }
    finder(0, 0);
    finder(size - 7, 0);
    finder(0, size - 7);
  }

  function drawTiming(m, size) {
    for (let i = 8; i < size - 8; i += 1) {
      m[6][i] = i % 2 === 0 ? 1 : 0;
      m[i][6] = i % 2 === 0 ? 1 : 0;
    }
  }

  function drawAlignment(m, version, size) {
    const pos = ALIGNMENT[version];
    if (!pos) return;
    for (const ay of pos) {
      for (const ax of pos) {
        if ((ax === 6 && ay === 6)
          || (ax === 6 && ay === size - 7)
          || (ax === size - 7 && ay === 6)) continue;
        for (let dy = -2; dy <= 2; dy += 1) {
          for (let dx = -2; dx <= 2; dx += 1) {
            m[ay + dy][ax + dx] = Math.max(Math.abs(dx), Math.abs(dy)) !== 1 ? 1 : 0;
          }
        }
      }
    }
  }

  function placeData(m, version, size, data) {
    let bit = 0;
    const total = data.length * 8;
    let up = true;
    for (let x = size - 1; x > 0; x -= 2) {
      if (x === 6) x -= 1;
      for (let i = 0; i < size; i += 1) {
        const y = up ? size - 1 - i : i;
        for (let dx = 0; dx < 2; dx += 1) {
          const xx = x - dx;
          if (m[y][xx] !== null) continue;
          let dark = false;
          if (bit < total) {
            const b = data[bit >> 3];
            dark = ((b >> (7 - (bit & 7))) & 1) === 1;
            bit += 1;
          }
          m[y][xx] = dark ? 1 : 0;
        }
      }
      up = !up;
    }
  }

  function maskBit(mask, x, y) {
    switch (mask) {
      case 0: return ((x + y) & 1) === 0;
      case 1: return (y & 1) === 0;
      case 2: return x % 3 === 0;
      case 3: return (x + y) % 3 === 0;
      case 4: return (((y >> 1) + Math.floor(x / 3)) & 1) === 0;
      case 5: return ((x * y) % 2) + ((x * y) % 3) === 0;
      case 6: return ((((x * y) % 2) + ((x * y) % 3)) & 1) === 0;
      case 7: return ((((x + y) % 2) + ((x * y) % 3)) & 1) === 0;
      default: return false;
    }
  }

  function scoreMask(m) {
    const size = m.length;
    let score = 0;
    for (let y = 0; y < size; y += 1) {
      let run = 1;
      for (let x = 1; x < size; x += 1) {
        if (m[y][x] === m[y][x - 1]) {
          run += 1;
          if (run === 5) score += 3;
          else if (run > 5) score += 1;
        } else run = 1;
      }
    }
    for (let x = 0; x < size; x += 1) {
      let run = 1;
      for (let y = 1; y < size; y += 1) {
        if (m[y][x] === m[y - 1][x]) {
          run += 1;
          if (run === 5) score += 3;
          else if (run > 5) score += 1;
        } else run = 1;
      }
    }
    for (let y = 0; y < size - 1; y += 1) {
      for (let x = 0; x < size - 1; x += 1) {
        const v = m[y][x];
        if (v === m[y][x + 1] && v === m[y + 1][x] && v === m[y + 1][x + 1]) score += 3;
      }
    }
    let dark = 0;
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) if (m[y][x]) dark += 1;
    }
    score += Math.floor(Math.abs((dark * 100) / (size * size) - 50) / 5) * 10;
    return score;
  }

  function drawFormatBits(m, mask) {
    // ECC M = 00
    let bits = (0b00 << 3) | mask;
    let rem = bits << 10;
    for (let i = 14; i >= 10; i -= 1) {
      if (((rem >>> i) & 1) !== 0) rem ^= 0x537 << (i - 10);
    }
    bits = ((bits << 10) | rem) ^ 0x5412;
    const size = m.length;
    const seq = [];
    for (let i = 0; i < 15; i += 1) seq.push((bits >>> i) & 1);
    const a = [
      [8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8],
      [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8],
    ];
    const b = [
      [size - 1, 8], [size - 2, 8], [size - 3, 8], [size - 4, 8],
      [size - 5, 8], [size - 6, 8], [size - 7, 8],
      [8, size - 8], [8, size - 7], [8, size - 6], [8, size - 5],
      [8, size - 4], [8, size - 3], [8, size - 2], [8, size - 1],
    ];
    for (let i = 0; i < 15; i += 1) {
      m[a[i][1]][a[i][0]] = seq[i];
      m[b[i][1]][b[i][0]] = seq[i];
    }
  }

  function build(text) {
    const bytes = getBytes(text);
    const version = chooseVersion(bytes.length);
    if (!version) throw new Error("qr_too_long");
    const size = sizeOf(version);
    const codewords = interleave(encodeDataCodewords(text, version), version);
    const base = Array.from({ length: size }, () => new Array(size).fill(null));
    drawFinders(base, size);
    drawTiming(base, size);
    drawAlignment(base, version, size);
    base[size - 8][8] = 1; // dark module
    // reserve format
    for (let i = 0; i <= 8; i += 1) {
      if (base[8][i] === null) base[8][i] = 0;
      if (base[i][8] === null) base[i][8] = 0;
    }
    for (let i = 0; i < 8; i += 1) {
      if (base[8][size - 1 - i] === null) base[8][size - 1 - i] = 0;
      if (base[size - 1 - i][8] === null) base[size - 1 - i][8] = 0;
    }
    placeData(base, version, size, codewords);

    let best = null;
    let bestScore = Infinity;
    for (let mask = 0; mask < 8; mask += 1) {
      const cand = base.map((row) => row.slice());
      for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
          if (isProtected(version, size, x, y)) continue;
          if (maskBit(mask, x, y)) cand[y][x] = cand[y][x] ? 0 : 1;
        }
      }
      drawFormatBits(cand, mask);
      const s = scoreMask(cand);
      if (s < bestScore) {
        bestScore = s;
        best = cand;
      }
    }
    return best;
  }

  function renderToCanvas(canvas, text, options) {
    if (!canvas || typeof text !== "string" || !text) return false;
    try {
      const modules = build(text);
      const size = modules.length;
      const margin = Math.max(1, Number((options && options.margin) || 2));
      const target = Math.max(128, Number((options && options.size) || 200));
      const scale = Math.max(2, Math.floor(target / (size + margin * 2)));
      const px = (size + margin * 2) * scale;
      canvas.width = px;
      canvas.height = px;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = (options && options.light) || "#f7f2e8";
      ctx.fillRect(0, 0, px, px);
      ctx.fillStyle = (options && options.dark) || "#14110c";
      for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
          if (!modules[y][x]) continue;
          ctx.fillRect((x + margin) * scale, (y + margin) * scale, scale, scale);
        }
      }
      return true;
    } catch (_error) {
      return false;
    }
  }

  global.BomanaQr = { renderToCanvas };
})(typeof window !== "undefined" ? window : globalThis);
