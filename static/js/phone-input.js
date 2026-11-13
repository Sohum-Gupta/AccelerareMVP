// Turns the phone box into a flag + dial-code picker (intl-tel-input).
// The server form keeps two ordinary fields, a phone text box and a country
// <select>. This script hides the select and keeps it in step with the flag,
// so the backend receives the same two values as before, and without
// JavaScript the plain fields still work.
(function () {
  document.querySelectorAll("[data-phone-input]").forEach(function (phone) {
    var root = phone.closest("[data-phone-root]");
    var select = root.querySelector("[data-phone-country] select");
    var holder = root.querySelector("[data-phone-country]");
    if (!select || !window.intlTelInput) return;

    var start = (select.value || "US").toLowerCase();
    var picker = window.intlTelInput(phone, {
      initialCountry: start,
      // Same order as the form's select: US, India, UK, then A to Z.
      countryOrder: ["us", "in", "gb"],
      separateDialCode: true,
      countrySearch: true,
      nationalMode: true,
    });
    holder.hidden = true;

    // A number already in the box with its country code (the account page puts
    // the saved one there) makes the picker choose that country as it starts,
    // before anything is listening. So read the choice once here, or the
    // hidden select would still say the default while the flag says another
    // country, and a number retyped without its code would be read wrongly.
    var chosen = picker.getSelectedCountryData();
    if (chosen && chosen.iso2) select.value = chosen.iso2.toUpperCase();

    phone.addEventListener("countrychange", function (event) {
      var country = event.detail && event.detail.iso2;
      if (country) select.value = country.toUpperCase();
    });
  });
})();
