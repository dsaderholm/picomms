// Runs before first paint (loaded in <head>) so there is no flash of the wrong theme.
// Theme choices: dark (default, dark booth), night (red only), light, auto (follow the OS).
(function () {
  var root = document.documentElement;
  var theme = 'dark', flash = 'strong';
  try { theme = localStorage.getItem('crewline.theme') || 'dark'; flash = localStorage.getItem('crewline.flash') || 'strong'; } catch (e) { /* storage blocked */ }
  root.setAttribute('data-theme', theme);
  root.setAttribute('data-flash', flash);
  var m = document.querySelector('meta[name="theme-color"]');
  if (m) m.setAttribute('content', { dark: '#0b0f14', night: '#080202', light: '#f2f5f9', auto: '#0b0f14' }[theme] || '#0b0f14');
})();
