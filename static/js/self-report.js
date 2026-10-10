// Shows "How did you take it?" only after "Yes" is picked. A convenience only:
// without this script the drop-down is simply visible, and the server requires
// an answer to it after a "yes" either way.
(function () {
  var radios = document.querySelectorAll("[data-self-report] input[type=radio]");
  var via = document.querySelector("[data-self-report-via]");
  if (!radios.length || !via) return;

  function update() {
    var yes = false;
    radios.forEach(function (radio) {
      if (radio.checked && radio.value === "yes") yes = true;
    });
    via.hidden = !yes;
  }

  radios.forEach(function (radio) {
    radio.addEventListener("change", update);
  });
  update();
})();
