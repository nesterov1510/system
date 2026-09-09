(() => {
  'use strict';

  document.addEventListener('DOMContentLoaded', () => {
    const root = document.querySelector('[data-tv-intake]');
    if (!root) return;

    const identityInput = root.querySelector('[data-tv-identity]');
    const brandText = root.querySelector('[data-tv-brand]');
    const modelText = root.querySelector('[data-tv-model]');
    const snText = root.querySelector('[data-tv-sn]');
    const brandInput = root.querySelector('[data-tv-brand-input]');
    const modelInput = root.querySelector('[data-tv-model-input]');
    const snInput = root.querySelector('[data-tv-sn-input]');

    const parseIdentity = (raw) => {
      const value = String(raw || '').trim();
      if (!value) return { brand: '', model: '', sn: '' };

      // Preferred delimiter: spaces around a dash. This preserves internal
      // hyphens in a model or serial number: Samsung - QE55-Q70 - SN-12-345.
      const spaced = value.split(/\s+[\-–—]\s+/).map((part) => part.trim()).filter(Boolean);
      if (spaced.length >= 3) {
        return {
          brand: spaced[0] || '',
          model: spaced[1] || '',
          sn: spaced.slice(2).join(' - ') || '',
        };
      }

      // Compact input: Samsung-QE55Q70-SN123. First two hyphens are separators;
      // everything after the second one belongs to SN.
      const compact = value.split('-');
      if (compact.length >= 3) {
        return {
          brand: (compact.shift() || '').trim(),
          model: (compact.shift() || '').trim(),
          sn: compact.join('-').trim(),
        };
      }

      if (compact.length === 2) {
        return { brand: compact[0].trim(), model: compact[1].trim(), sn: '' };
      }

      return { brand: value, model: '', sn: '' };
    };

    const renderIdentity = () => {
      const parsed = parseIdentity(identityInput?.value);
      const values = [
        ['brand', parsed.brand, brandText, brandInput, 'Не указана'],
        ['model', parsed.model, modelText, modelInput, 'Не указана'],
        ['sn', parsed.sn, snText, snInput, 'Не указан'],
      ];

      values.forEach(([key, value, output, hidden, emptyText]) => {
        if (output) output.textContent = value || emptyText;
        if (hidden) hidden.value = value;
        const card = root.querySelector(`[data-tv-identity-part="${key}"]`);
        if (card) card.classList.toggle('is-filled', Boolean(value));
      });
    };

    if (identityInput) {
      identityInput.addEventListener('input', renderIdentity);
      identityInput.addEventListener('change', renderIdentity);
      renderIdentity();
    }

    // Delivery: compact toolbar control + modal. Values are written into
    // hidden form fields so the future persistence endpoint can save them.
    const deliveryOpen = root.querySelector('[data-delivery-open]');
    const deliveryModal = root.querySelector('[data-delivery-modal]');
    const deliveryDistrict = root.querySelector('[data-delivery-district]');
    const deliveryEnabledInput = root.querySelector('[data-delivery-enabled]');
    const deliveryDistrictInput = root.querySelector('[data-delivery-district-input]');
    const deliveryLabel = root.querySelector('[data-delivery-label]');
    const deliverySummary = root.querySelector('[data-delivery-summary]');
    const deliveryRemove = root.querySelector('[data-delivery-remove]');
    const deliverySave = root.querySelector('[data-delivery-save]');

    const setDeliveryModal = (visible) => {
      if (!deliveryModal || !deliveryOpen) return;
      deliveryModal.hidden = !visible;
      deliveryModal.setAttribute('aria-hidden', visible ? 'false' : 'true');
      deliveryOpen.setAttribute('aria-expanded', visible ? 'true' : 'false');
      document.body.style.overflow = visible ? 'hidden' : '';
      if (visible) {
        if (deliveryDistrict) deliveryDistrict.value = deliveryDistrictInput?.value || '';
        if (deliveryRemove) deliveryRemove.hidden = deliveryEnabledInput?.value !== '1';
        window.setTimeout(() => deliveryDistrict?.focus(), 20);
      }
    };

    const renderDelivery = () => {
      const enabled = deliveryEnabledInput?.value === '1';
      const district = String(deliveryDistrictInput?.value || '').trim();
      deliveryOpen?.classList.toggle('is-active', enabled);
      if (deliveryLabel) deliveryLabel.textContent = enabled ? 'Доставка ✓' : 'Доставка';
      if (deliverySummary) deliverySummary.textContent = enabled && district ? district : 'Не указана';
      if (deliveryRemove) deliveryRemove.hidden = !enabled;
    };

    deliveryOpen?.addEventListener('click', () => setDeliveryModal(true));
    root.querySelectorAll('[data-delivery-close]').forEach((el) => el.addEventListener('click', () => setDeliveryModal(false)));
    deliverySave?.addEventListener('click', () => {
      const district = String(deliveryDistrict?.value || '').trim();
      if (!district) {
        deliveryDistrict?.focus();
        deliveryDistrict?.classList.add('is-error');
        return;
      }
      deliveryDistrict?.classList.remove('is-error');
      if (deliveryEnabledInput) deliveryEnabledInput.value = '1';
      if (deliveryDistrictInput) deliveryDistrictInput.value = district;
      renderDelivery();
      setDeliveryModal(false);
    });
    deliveryRemove?.addEventListener('click', () => {
      if (deliveryEnabledInput) deliveryEnabledInput.value = '0';
      if (deliveryDistrictInput) deliveryDistrictInput.value = '';
      if (deliveryDistrict) deliveryDistrict.value = '';
      renderDelivery();
      setDeliveryModal(false);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && deliveryModal && !deliveryModal.hidden) setDeliveryModal(false);
    });
    renderDelivery();

    // Additional customer phone numbers.
    const extraPhones = root.querySelector('[data-extra-phones]');
    const addPhoneButton = root.querySelector('[data-add-phone]');
    let extraPhoneIndex = 0;

    const addPhone = () => {
      if (!extraPhones) return;
      extraPhoneIndex += 1;
      const row = document.createElement('div');
      row.className = 'tv-extra-phone';
      row.innerHTML = `
        <input type="tel" inputmode="tel" name="customer_phone_extra[]" aria-label="Дополнительный номер телефона ${extraPhoneIndex}" placeholder="Дополнительный номер телефона">
        <button type="button" aria-label="Удалить дополнительный номер">×</button>
      `;
      row.querySelector('button')?.addEventListener('click', () => row.remove());
      extraPhones.appendChild(row);
      row.querySelector('input')?.focus();
    };

    addPhoneButton?.addEventListener('click', addPhone);

    // Secondary contact / delivery person / second owner.
    const secondaryOpen = root.querySelector('[data-secondary-contact-open]');
    const secondaryBox = root.querySelector('[data-secondary-contact]');
    const secondaryRemove = root.querySelector('[data-secondary-contact-remove]');
    const secondarySign = root.querySelector('[data-secondary-contact-sign]');

    const setSecondaryVisible = (visible) => {
      if (!secondaryBox || !secondaryOpen) return;
      secondaryBox.hidden = !visible;
      secondaryOpen.setAttribute('aria-expanded', visible ? 'true' : 'false');
      if (secondarySign) secondarySign.textContent = visible ? '−' : '＋';
      if (visible) secondaryBox.querySelector('input')?.focus();
    };

    secondaryOpen?.addEventListener('click', () => setSecondaryVisible(Boolean(secondaryBox?.hidden)));
    secondaryRemove?.addEventListener('click', () => {
      secondaryBox?.querySelectorAll('input').forEach((input) => { input.value = ''; });
      setSecondaryVisible(false);
    });

    // Intake photos. At this stage they are retained in the browser preview only;
    // persistence will be wired when the repair database endpoint is added.
    const cameraButton = root.querySelector('[data-camera-open]');
    const cameraInput = root.querySelector('[data-camera-input]');
    const galleryButton = root.querySelector('[data-gallery-open]');
    const galleryInput = root.querySelector('[data-gallery-input]');
    const photoList = root.querySelector('[data-photo-list]');
    const photoGrid = root.querySelector('[data-photo-grid]');
    const photoCount = root.querySelector('[data-photo-count]');
    const photos = [];

    const updatePhotoCount = () => {
      if (!photoList || !photoCount) return;
      photoList.hidden = photos.length === 0;
      const remainder10 = photos.length % 10;
      const remainder100 = photos.length % 100;
      const word = remainder10 === 1 && remainder100 !== 11 ? 'фото' : 'фото';
      photoCount.textContent = `${photos.length} ${word}`;
    };

    const renderPhotos = () => {
      if (!photoGrid) return;
      photoGrid.replaceChildren();
      photos.forEach((photo, index) => {
        const item = document.createElement('div');
        item.className = 'tv-photo-item';
        const img = document.createElement('img');
        img.src = photo.url;
        img.alt = `Фото состояния ${index + 1}`;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.setAttribute('aria-label', `Удалить фото ${index + 1}`);
        remove.textContent = '×';
        remove.addEventListener('click', () => {
          const removed = photos.splice(index, 1)[0];
          if (removed?.url) URL.revokeObjectURL(removed.url);
          renderPhotos();
        });
        item.append(img, remove);
        photoGrid.appendChild(item);
      });
      updatePhotoCount();
    };

    const addFiles = (fileList) => {
      Array.from(fileList || []).forEach((file) => {
        if (!file.type?.startsWith('image/')) return;
        photos.push({ file, url: URL.createObjectURL(file) });
      });
      renderPhotos();
    };

    cameraButton?.addEventListener('click', () => cameraInput?.click());
    galleryButton?.addEventListener('click', () => galleryInput?.click());
    cameraInput?.addEventListener('change', () => {
      addFiles(cameraInput.files);
      cameraInput.value = '';
    });
    galleryInput?.addEventListener('change', () => {
      addFiles(galleryInput.files);
      galleryInput.value = '';
    });

    // Lightweight completeness check; no data is submitted yet.
    const checkButton = root.querySelector('[data-intake-check]');
    checkButton?.addEventListener('click', () => {
      root.querySelectorAll('.tv-form-card.has-check-error').forEach((card) => card.classList.remove('has-check-error'));
      const requiredValues = [
        identityInput,
        root.querySelector('#tvCustomerComplaint'),
        root.querySelector('#tvCustomerName'),
        root.querySelector('#tvCustomerPhone'),
      ];
      const missing = requiredValues.filter((field) => !String(field?.value || '').trim());
      missing.forEach((field) => field?.closest('.tv-form-card')?.classList.add('has-check-error'));
      if (missing.length) {
        missing[0]?.focus();
        checkButton.textContent = `Не заполнено: ${missing.length}`;
        window.setTimeout(() => { checkButton.textContent = 'Проверить заполнение'; }, 2200);
        return;
      }
      checkButton.textContent = '✓ Основные поля заполнены';
      window.setTimeout(() => { checkButton.textContent = 'Проверить заполнение'; }, 2200);
    });
  });
})();
