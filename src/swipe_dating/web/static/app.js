(() => {
  const card = document.querySelector('[data-swipe-card]');
  const passForm = document.querySelector('[data-pass-form]');
  const likeForm = document.querySelector('[data-like-form]');

  if (card && passForm && likeForm) {
    let startX = 0;
    let deltaX = 0;
    let dragging = false;

    const reset = () => {
      card.style.transform = '';
      card.style.opacity = '';
      card.querySelector('.pass-stamp')?.style.removeProperty('opacity');
      card.querySelector('.like-stamp')?.style.removeProperty('opacity');
      dragging = false;
      deltaX = 0;
    };

    card.addEventListener('pointerdown', (event) => {
      if (event.target.closest('button, summary, form, select, textarea, input, a')) return;
      startX = event.clientX;
      dragging = true;
      card.setPointerCapture(event.pointerId);
    });

    card.addEventListener('pointermove', (event) => {
      if (!dragging) return;
      deltaX = event.clientX - startX;
      const rotation = Math.max(-8, Math.min(8, deltaX / 24));
      card.style.transform = `translateX(${deltaX}px) rotate(${rotation}deg)`;
      card.style.opacity = String(Math.max(0.72, 1 - Math.abs(deltaX) / 700));
      const amount = Math.min(1, Math.abs(deltaX) / 90);
      const passStamp = card.querySelector('.pass-stamp');
      const likeStamp = card.querySelector('.like-stamp');
      if (passStamp) passStamp.style.opacity = deltaX < 0 ? String(amount) : '0';
      if (likeStamp) likeStamp.style.opacity = deltaX > 0 ? String(amount) : '0';
    });

    card.addEventListener('pointerup', () => {
      if (!dragging) return;
      if (deltaX <= -110) {
        passForm.requestSubmit();
        return;
      }
      if (deltaX >= 110) {
        likeForm.requestSubmit();
        return;
      }
      reset();
    });

    card.addEventListener('pointercancel', reset);

    document.addEventListener('keydown', (event) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
      if (event.key === 'ArrowLeft') passForm.requestSubmit();
      if (event.key === 'ArrowRight') likeForm.requestSubmit();
    });
  }

  document.querySelectorAll('[data-auto-grow]').forEach((textarea) => {
    const resize = () => {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(120, textarea.scrollHeight)}px`;
    };
    textarea.addEventListener('input', resize);
    resize();
  });

  const thread = document.querySelector('[data-message-thread]');
  if (thread) thread.scrollTop = thread.scrollHeight;
})();
