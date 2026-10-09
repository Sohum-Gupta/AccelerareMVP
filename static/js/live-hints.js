// Live checklists under a field: hidden until the person types, each line
// turns green (data-met="true") when its rule holds. Purely a guide; the
// server checks everything again, and also rules this script cannot (a
// password that is too common or too like the email).
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
      var allMet = true;
      list.querySelectorAll("[data-rule]").forEach(function (item) {
        var met = RULES[item.dataset.rule](input.value, list);
        item.dataset.met = met ? "true" : "false";
        if (!met) allMet = false;
      });
      // Show while there is something typed and either the field is in use or
      // something is still unmet; hide again once it is empty.
      list.hidden = !(input.value !== "" && (document.activeElement === input || !allMet));
    }

    ["input", "focus", "blur"].forEach(function (name) {
      input.addEventListener(name, update);
    });
    // Editing the first password changes whether the second one matches.
    if (other) other.addEventListener("input", update);
    update();
  });
})();
