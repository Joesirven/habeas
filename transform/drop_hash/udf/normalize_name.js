/**
 * DROP v1.2.0 name standardization — JS port of drop_normalize.names
 * Source maps: transform/drop_hash/drop_normalize/src/drop_normalize/data/*.json
 * LATIN_EXTENDED: NFKD fallback for BQ JS (String.normalize NFKD is incomplete)
 */

const SPECIAL_LATIN = {
  "ß": "ss",
  "æ": "ae",
  "ð": "d",
  "ø": "o",
  "þ": "th",
  "đ": "d",
  "ħ": "h",
  "ı": "i",
  "ĳ": "ij",
  "ŀ": "l",
  "ł": "l",
  "ŋ": "n",
  "œ": "oe",
};

const GREEK = {
  "ΐ": "i",
  "ά": "a",
  "έ": "e",
  "ή": "i",
  "ί": "i",
  "ΰ": "y",
  "α": "a",
  "β": "v",
  "γ": "g",
  "δ": "d",
  "ε": "e",
  "ζ": "z",
  "η": "i",
  "θ": "th",
  "ι": "i",
  "κ": "k",
  "λ": "l",
  "μ": "m",
  "ν": "n",
  "ξ": "x",
  "ο": "o",
  "π": "p",
  "ρ": "r",
  "ς": "s",
  "σ": "s",
  "τ": "t",
  "υ": "y",
  "φ": "f",
  "χ": "ch",
  "ψ": "ps",
  "ω": "o",
  "ϊ": "i",
  "ϋ": "y",
  "ό": "o",
  "ύ": "y",
  "ώ": "o",
};

const CYRILLIC = {
  "а": "a",
  "б": "b",
  "в": "v",
  "г": "g",
  "д": "d",
  "е": "e",
  "ж": "zh",
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
  "х": "kh",
  "ц": "ts",
  "ч": "ch",
  "ш": "sh",
  "щ": "shch",
  "ъ": "",
  "ы": "y",
  "ь": "",
  "э": "e",
  "ю": "yu",
  "я": "ya",
  "ё": "yo",
  "є": "e",
  "і": "i",
  "ї": "i",
  "ў": "u",
  "ґ": "g",
};

const LATIN_EXTENDED = {
  "i̇": "i",
  "à": "a",
  "á": "a",
  "â": "a",
  "ã": "a",
  "ä": "a",
  "å": "a",
  "ç": "c",
  "è": "e",
  "é": "e",
  "ê": "e",
  "ë": "e",
  "ì": "i",
  "í": "i",
  "î": "i",
  "ï": "i",
  "ñ": "n",
  "ò": "o",
  "ó": "o",
  "ô": "o",
  "õ": "o",
  "ö": "o",
  "ù": "u",
  "ú": "u",
  "û": "u",
  "ü": "u",
  "ý": "y",
  "ÿ": "y",
  "ā": "a",
  "ă": "a",
  "ą": "a",
  "ć": "c",
  "ĉ": "c",
  "ċ": "c",
  "č": "c",
  "ď": "d",
  "ē": "e",
  "ĕ": "e",
  "ė": "e",
  "ę": "e",
  "ě": "e",
  "ĝ": "g",
  "ğ": "g",
  "ġ": "g",
  "ģ": "g",
  "ĥ": "h",
  "ĩ": "i",
  "ī": "i",
  "ĭ": "i",
  "į": "i",
  "ĵ": "j",
  "ķ": "k",
  "ĺ": "l",
  "ļ": "l",
  "ľ": "l",
  "ń": "n",
  "ņ": "n",
  "ň": "n",
  "ŉ": "ʼn",
  "ō": "o",
  "ŏ": "o",
  "ő": "o",
  "ŕ": "r",
  "ŗ": "r",
  "ř": "r",
  "ś": "s",
  "ŝ": "s",
  "ş": "s",
  "š": "s",
  "ţ": "t",
  "ť": "t",
  "ũ": "u",
  "ū": "u",
  "ŭ": "u",
  "ů": "u",
  "ű": "u",
  "ų": "u",
  "ŵ": "w",
  "ŷ": "y",
  "ź": "z",
  "ż": "z",
  "ž": "z",
  "ſ": "s",
  "ơ": "o",
  "ư": "u",
  "ǆ": "dz",
  "ǉ": "lj",
  "ǌ": "nj",
  "ǎ": "a",
  "ǐ": "i",
  "ǒ": "o",
  "ǔ": "u",
  "ǖ": "u",
  "ǘ": "u",
  "ǚ": "u",
  "ǜ": "u",
  "ǟ": "a",
  "ǡ": "a",
  "ǣ": "æ",
  "ǧ": "g",
  "ǩ": "k",
  "ǫ": "o",
  "ǭ": "o",
  "ǯ": "ʒ",
  "ǰ": "j",
  "ǳ": "dz",
  "ǵ": "g",
  "ǹ": "n",
  "ǻ": "a",
  "ǽ": "æ",
  "ǿ": "ø",
  "ȁ": "a",
  "ȃ": "a",
  "ȅ": "e",
  "ȇ": "e",
  "ȉ": "i",
  "ȋ": "i",
  "ȍ": "o",
  "ȏ": "o",
  "ȑ": "r",
  "ȓ": "r",
  "ȕ": "u",
  "ȗ": "u",
  "ș": "s",
  "ț": "t",
  "ȟ": "h",
  "ȧ": "a",
  "ȩ": "e",
  "ȫ": "o",
  "ȭ": "o",
  "ȯ": "o",
  "ȱ": "o",
  "ȳ": "y",
};

function applyCharMap(text, mapping) {
  const keys = Object.keys(mapping).sort(function(a, b) {
    return b.length - a.length;
  });
  for (let i = 0; i < keys.length; i++) {
    const ch = keys[i];
    text = text.split(ch).join(mapping[ch]);
  }
  return text;
}

function stripCombiningMarks(text) {
  let normalized = text;
  try {
    normalized = text.normalize('NFKD');
  } catch (e) {
    normalized = text;
  }
  let result = '';
  for (let i = 0; i < normalized.length; i++) {
    const code = normalized.charCodeAt(i);
    if (code >= 0x0300 && code <= 0x036f) {
      continue;
    }
    result += normalized.charAt(i);
  }
  return result;
}

function isAlnum(ch) {
  const code = ch.charCodeAt(0);
  if (code >= 48 && code <= 57) {
    return true;
  }
  if (code >= 97 && code <= 122) {
    return true;
  }
  if (code > 127) {
    return true;
  }
  return false;
}

function normalizeName(value) {
  if (value === null || value === undefined) {
    return null;
  }
  let result = String(value).toLowerCase();
  result = applyCharMap(result, SPECIAL_LATIN);
  result = applyCharMap(result, GREEK);
  result = applyCharMap(result, CYRILLIC);
  result = applyCharMap(result, LATIN_EXTENDED);
  result = stripCombiningMarks(result);
  let filtered = '';
  for (let i = 0; i < result.length; i++) {
    if (isAlnum(result.charAt(i))) {
      filtered += result.charAt(i);
    }
  }
  if (filtered.length === 0) {
    return null;
  }
  return filtered;
}
