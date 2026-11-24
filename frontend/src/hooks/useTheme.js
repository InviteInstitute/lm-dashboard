// Light (INVITE's brand) or dark, kept per browser. With nothing stored, follow
// the system setting. The theme is a data attribute on <html>, which Carbon's
// tokens and the dashboard's own colours both read (styles/carbon.scss,
// styles/base.css).
import React from "react";

const KEY = "lm_theme";

function initialTheme() {
  try {
    return (
      localStorage.getItem(KEY) ||
      (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    );
  } catch {
    return "light";
  }
}

export function useTheme() {
  const [theme, setTheme] = React.useState(initialTheme);
  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* storage blocked: the theme still applies for this visit */
    }
  }, [theme]);
  const toggle = React.useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return [theme, toggle];
}
