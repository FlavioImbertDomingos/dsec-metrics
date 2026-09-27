// Applies the saved or system theme before first paint. Loaded as an external file
// because the Content Security Policy allows no inline scripts.
(function () {
  "use strict";
  var pref;
  try {
    pref = localStorage.getItem("dsec-theme");
  } catch {
    pref = null;
  }
  var dark =
    pref === "dark" ||
    (pref !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
})();
