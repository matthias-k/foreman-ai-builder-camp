/** @type {import('tailwindcss').Config} */
module.exports = {
  // Gate `dark:` on a `.dark` class (never set) rather than the OS setting, so
  // the app's incomplete dark styling stays light instead of rendering dark-on-dark.
  darkMode: "selector",
  content: ["../templates/**/*.html", "../templates/**/*.html.jinja"],
  theme: {
    extend: {},
  },
  plugins: [],
}

