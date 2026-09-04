// Валидация телефона (Туркменистан: +993 XX XXXXXX = код страны 993 + 8 цифр
// абонентского номера, итого 11 цифр). Если оператор случайно ввёл лишнюю
// или недостающую цифру (опечатка) — форма должна показать alert с ошибкой.

/** Оставить только цифры (без ведущего +). */
export function phoneDigits(phone: string): string {
  return phone.replace(/[^\d]/g, "");
}

export interface PhoneCheck {
  valid: boolean;
  message?: string;
}

/**
 * Проверить номер телефона.
 * - Для туркменских номеров (начинаются с 993 или введены без кода страны,
 *   но с локальным форматом 8 XX XXXXXX / XX XXXXXX) — строго 11 цифр после
 *   нормализации к виду 993XXXXXXXX.
 * - Для прочих (другой код страны) — просто разумная длина 9–15 цифр.
 */
export function checkPhone(raw: string): PhoneCheck {
  const trimmed = raw.trim();
  if (!trimmed) return { valid: false, message: "Введите номер телефона" };

  let digits = phoneDigits(trimmed);

  // Локальный туркменский формат без кода страны: 8 XX XXXXXX (9 цифр,
  // начинается с 8) — приводим к 993XXXXXXXX для проверки длины.
  if (digits.startsWith("993")) {
    // уже с кодом страны
  } else if (digits.startsWith("8") && digits.length === 9) {
    digits = "993" + digits.slice(1);
  } else if (digits.length === 8) {
    digits = "993" + digits;
  }

  if (digits.startsWith("993")) {
    if (digits.length !== 11) {
      const diff = digits.length - 11;
      const hint =
        diff > 0
          ? `лишних цифр: ${diff}`
          : `не хватает цифр: ${Math.abs(diff)}`;
      return {
        valid: false,
        message: `Некорректный номер телефона (${hint}). Формат: +993 XX XXXXXX (11 цифр всего). Исправьте номер телефона.`,
      };
    }
    return { valid: true };
  }

  // Другой код страны — мягкая проверка длины.
  if (digits.length < 9 || digits.length > 15) {
    return {
      valid: false,
      message: "Некорректный номер телефона. Исправьте номер телефона.",
    };
  }
  return { valid: true };
}
