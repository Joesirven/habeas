/**
 * DROP v1.2.0 name standardization — JS port of drop_normalize names.py
 * Maps synced from drop_normalize/data/*.json
 * BigQuery JS UDF–safe (avoid Unicode property escapes).
 */
const SPECIAL = {
  "ß": "ss",
  "æ": "ae",
  "œ": "oe",
  "ø": "o",
  "ð": "d",
  "þ": "th",
  "ł": "l",
  "đ": "d",
  "ħ": "h",
  "ŋ": "n",
  "ı": "i",
  "ĳ": "ij",
  "ŀ": "l"
};
const GREEK = {
  "θ": "th",
  "χ": "ch",
  "ψ": "ps",
  "α": "a",
  "β": "v",
  "γ": "g",
  "δ": "d",
  "ε": "e",
  "ζ": "z",
  "η": "i",
  "ι": "i",
  "κ": "k",
  "λ": "l",
  "μ": "m",
  "ν": "n",
  "ξ": "x",
  "ο": "o",
  "π": "p",
  "ρ": "r",
  "σ": "s",
  "ς": "s",
  "τ": "t",
  "υ": "y",
  "φ": "f",
  "ω": "o",
  "ά": "a",
  "έ": "e",
  "ί": "i",
  "ή": "i",
  "ύ": "y",
  "ό": "o",
  "ώ": "o",
  "ϊ": "i",
  "ΐ": "i",
  "ϋ": "y",
  "ΰ": "y"
};
const CYR = {
  "щ": "shch",
  "ё": "yo",
  "ж": "zh",
  "х": "kh",
  "ц": "ts",
  "ч": "ch",
  "ш": "sh",
  "ю": "yu",
  "я": "ya",
  "а": "a",
  "б": "b",
  "в": "v",
  "г": "g",
  "д": "d",
  "е": "e",
  "з": "z",
  "и": "i",
  "й": "y",
  "к": "k",
  "л": "l",
  "м": "m",
  "н": "n",
  "о": "o",
  "п": "p",
  "р": "r",
  "с": "s",
  "т": "t",
  "у": "u",
  "ф": "f",
  "ъ": "",
  "ы": "y",
  "ь": "",
  "э": "e",
  "є": "e",
  "і": "i",
  "ї": "i",
  "ґ": "g",
  "ў": "u"
};

function applyMap(text, mapping) {
  const keys = Object.keys(mapping).sort(function (a, b) {
    return b.length - a.length;
  });
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    text = text.split(k).join(mapping[k]);
  }
  return text;
}

function stripCombining(text) {
  var out = "";
  for (var i = 0; i < text.length; i++) {
    var c = text.charCodeAt(i);
    if (c >= 0x0300 && c <= 0x036f) continue;
    if (c >= 0x1ab0 && c <= 0x1aff) continue;
    if (c >= 0x1dc0 && c <= 0x1dff) continue;
    if (c >= 0x20d0 && c <= 0x20ff) continue;
    if (c >= 0xfe20 && c <= 0xfe2f) continue;
    out += text.charAt(i);
  }
  return out;
}

function isAlnumChar(ch) {
  if (/[0-9A-Za-z]/.test(ch)) return true;
  if (ch.toLowerCase() !== ch.toUpperCase()) return true;
  var cp = ch.codePointAt(0);
  if (cp >= 0x4e00 && cp <= 0x9fff) return true;
  if (cp >= 0x3400 && cp <= 0x4dbf) return true;
  if (cp >= 0x3040 && cp <= 0x30ff) return true;
  if (cp >= 0xac00 && cp <= 0xd7af) return true;
  if (cp >= 0x0600 && cp <= 0x06ff) return true;
  if (cp >= 0x0590 && cp <= 0x05ff) return true;
  return false;
}

function stripNonAlnum(text) {
  var out = "";
  for (var i = 0; i < text.length; ) {
    var cp = text.codePointAt(i);
    var ch = String.fromCodePoint(cp);
    if (isAlnumChar(ch)) out += ch;
    i += ch.length;
  }
  return out;
}

/**
 * @param {string} value
 * @returns {string|null}
 */
function normalize_name(value) {
  if (value === null || value === undefined) return null;
  var result = String(value).toLowerCase();
  result = applyMap(result, SPECIAL);
  result = applyMap(result, GREEK);
  result = applyMap(result, CYR);
  result = stripCombining(result.normalize("NFKD"));
  result = stripNonAlnum(result);
  return result === "" ? null : result;
}
