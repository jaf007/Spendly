// main.js — students will add JavaScript here as features are built

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-auto-dismiss]").forEach((el) => {
        const delay = parseInt(el.dataset.autoDismiss, 10);
        setTimeout(() => {
            el.classList.add("flash-message-fade-out");
            el.addEventListener("transitionend", () => el.remove(), { once: true });
        }, delay);
    });
});
