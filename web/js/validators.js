/** Walidatory pól (nazwy jak w field.validation). Zwracają komunikat błędu albo null. */
const digits = (s) => s.replace(/[\s-]/g, "");
const sum = (d, w) => w.reduce((a, x, i) => a + x * +d[i], 0);

const CHECKS = {
  EMAIL: (v) => (/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v) ? null : "Niepoprawny adres e-mail"),
  ZIP_CODE: (v) => (/^\d{2}-\d{3}$/.test(v) ? null : "Kod pocztowy w formacie NN-NNN"),
  PESEL: (v) => {
    const d = digits(v);
    if (!/^\d{11}$/.test(d)) return "PESEL musi mieć 11 cyfr";
    return (10 - (sum(d, [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]) % 10)) % 10 === +d[10] ? null : "Niepoprawna suma kontrolna PESEL";
  },
  NIP: (v) => {
    const d = digits(v.replace(/^PL/i, ""));
    if (!/^\d{10}$/.test(d)) return "NIP musi mieć 10 cyfr";
    const c = sum(d, [6, 5, 7, 2, 3, 4, 5, 6, 7]) % 11;
    return c !== 10 && c === +d[9] ? null : "Niepoprawna suma kontrolna NIP";
  },
  REGON: (v) => {
    const d = digits(v);
    if (!/^(\d{9}|\d{14})$/.test(d)) return "REGON musi mieć 9 lub 14 cyfr";
    const chk = (n, w) => (sum(d, w) % 11) % 10 === +d[n];
    const ok = chk(8, [8, 9, 2, 3, 4, 5, 6, 7]) && (d.length === 9 || chk(13, [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8]));
    return ok ? null : "Niepoprawna suma kontrolna REGON";
  },
};

/** Walidacja nr rachunku PL / IBAN (mod 97) – do użycia pomocniczo. */
export function iban(v) {
  const s = v.replace(/\s/g, "").toUpperCase(), t = /^\d{26}$/.test(s) ? "PL" + s : s;
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(t)) return "Niepoprawny numer rachunku";
  const r = (t.slice(4) + t.slice(0, 4)).replace(/[A-Z]/g, (c) => c.charCodeAt(0) - 55);
  let m = 0; for (const ch of r) m = (m * 10 + +ch) % 97;
  return m === 1 ? null : "Niepoprawna suma kontrolna rachunku";
}

/** Komunikat błędu dla wartości pola wg listy walidatorów albo null. */
export function validateValue(value, validators = []) {
  const v = String(value ?? "").trim();
  if (!v) return validators.includes("REQUIRED") ? "Pole wymagane" : null;
  for (const name of validators) { const m = CHECKS[name]?.(v); if (m) return m; }
  return null;
}
