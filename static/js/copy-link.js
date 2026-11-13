// "Copy link" buttons: <button data-copy="id-of-an-input" hidden>. A convenience
// only: each button starts hidden and is shown here if the browser can copy.
// Without this script the link sits in a read-only box that can be selected.
(function () {
  if (!navigator.clipboard) return;
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("data-copy"));
    if (!input) return;
    var label = button.textContent;
    button.hidden = false;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(input.value).then(function () {
        button.textContent = "Copied";
        setTimeout(function () {
          button.textContent = label;
        }, 2000);
      });
    });
  });
})();
