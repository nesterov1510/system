document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.intake-type-card').forEach((card) => {
    card.addEventListener('pointerdown', () => card.classList.add('is-pressed'));
    ['pointerup', 'pointercancel', 'pointerleave'].forEach((eventName) => {
      card.addEventListener(eventName, () => card.classList.remove('is-pressed'));
    });
  });
});
