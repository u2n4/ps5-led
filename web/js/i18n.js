// Applies a string table to anything carrying data-i18n, and flips direction.
// Both tables are guaranteed by the Python side to have identical key sets, so
// a missing key here means the element's key is wrong, not the translation.

export function applyLanguage(tables, direction, language) {
  const table = tables[language] ?? tables.en;
  for (const node of document.querySelectorAll('[data-i18n]')) {
    const key = node.dataset.i18n;
    if (key in table) node.textContent = table[key];
    else console.warn(`no string for ${key}`);
  }
  document.documentElement.lang = language;
  document.documentElement.dir = direction[language] ?? 'ltr';
  return table;
}
