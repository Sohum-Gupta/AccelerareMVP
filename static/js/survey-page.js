// The statement page. Next stays off until every statement has a choice, and
// each statement says whether its last click reached the server. A convenience
// only: without this script Next is always on and saves the page's choices
// itself, and the server refuses an incomplete page either way.
(function () {
  var form = document.querySelector("[data-survey-page]");
  if (!form) return;
  var next = form.querySelector("[data-next]");
  var statements = form.querySelectorAll("[data-statement]");

  function update() {
    var chosen = 0;
    statements.forEach(function (statement) {
      if (statement.querySelector("input[type=radio]:checked")) chosen += 1;
    });
    next.disabled = chosen < statements.length;
  }

  function say(elt, text, isError) {
    var statement = elt.closest("[data-statement]");
    if (!statement) return;
    var span = document.createElement("span");
    span.className = isError ? "text-red-700" : "text-slate-600";
    span.textContent = text;
    statement.querySelector("[data-status]").replaceChildren(span);
  }

  form.addEventListener("change", update);
  // Once pressed, Next cannot be pressed again while the page is changing.
  form.addEventListener("submit", function () {
    window.setTimeout(function () { next.disabled = true; }, 0);
  });
  // A page brought back by the browser's back button gets its button state again.
  window.addEventListener("pageshow", update);

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    say(event.detail.elt, "Saving…", false);
  });
  // A refusal (409) carries a message for the person, so let HTMX put it in
  // place; other errors are not swapped in and get the lines below.
  document.body.addEventListener("htmx:beforeSwap", function (event) {
    if (event.detail.xhr.status === 409) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });
  document.body.addEventListener("htmx:responseError", function (event) {
    say(event.detail.elt, "Not saved. Reload the page and choose again.", true);
  });
  document.body.addEventListener("htmx:sendError", function (event) {
    say(event.detail.elt, "Not saved yet (no connection). Next will save it once you are back online.", true);
  });

  update();
})();
