// Live checklists under a field: hidden until the person types, each line
// turns green (data-met="true") when its rule holds. Purely a guide; the
// server checks everything again, and also rules this script cannot (a
// password that is too common or too like the email).
//
// A list stays on the page for as long as its box has text in it. It must not
// hide when the box loses focus: that moved everything below it up by a line
// in the middle of a tap, so the first tap on "Sign up" missed the button.
(function () {
  var RULES = {
    email: function (value) {
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
    },
    length: function (value, list) {
      return value.length >= Number(list.dataset.min);
    },
    "not-digits": function (value) {
      return value.length > 0 && !/^\d+$/.test(value);
    },
    match: function (value, list) {
      var other = document.getElementById(list.dataset.match);
      return !!other && value !== "" && value === other.value;
    },
  };

  document.querySelectorAll("[data-hints]").forEach(function (list) {
    var input = document.getElementById(list.dataset.for);
    if (!input) return;
    var other = list.dataset.match && document.getElementById(list.dataset.match);

    function update() {
      list.querySelectorAll("[data-rule]").forEach(function (item) {
        var met = RULES[item.dataset.rule](input.value, list);
        item.dataset.met = met ? "true" : "false";
      });
      list.hidden = input.value === "";
    }

    input.addEventListener("input", update);
    // Editing the first password changes whether the second one matches.
    if (other) other.addEventListener("input", update);
    update();
  });
})();

// Server errors come from the last submit. Once the person edits that field
// they may be out of date (a "required" error beside a filled-in box), so hide
// them; the server checks again on the next submit.
(function () {
  document.querySelectorAll("[data-error-for]").forEach(function (error) {
    var input = document.getElementById(error.dataset.errorFor);
    if (!input) return;
    input.addEventListener("input", function () {
      error.hidden = true;
    });
  });
})();

// "Show password" under every password box: switches the dots to plain text
// and back, so a person can check what they typed (on a phone above all). The
// button is in the page hidden; this script reveals it. Just before the form
// is sent the box goes back to dots, so the browser never remembers a
// password as if it were ordinary text it could offer in another box.
(function () {
  document.querySelectorAll("[data-show-password]").forEach(function (button) {
    var input = document.getElementById(button.dataset.showPassword);
    if (!input) return;

    function show(visible) {
      input.type = visible ? "text" : "password";
      button.textContent = visible ? "Hide password" : "Show password";
      button.setAttribute("aria-pressed", visible ? "true" : "false");
    }

    button.hidden = false;
    button.addEventListener("click", function () {
      show(input.type === "password");
    });
    if (input.form) {
      input.form.addEventListener("submit", function () {
        show(false);
      });
    }
  });
})();
