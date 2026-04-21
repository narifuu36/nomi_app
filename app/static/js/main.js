function toggleForm(show) {
    const el = document.getElementById("formArea");
    if (!el) return;
    el.classList.toggle("hidden", !show);
}