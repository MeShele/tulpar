/**
 * Tulpar Express - Google Sheets Setup Script
 *
 * Инструкция:
 * 1. В Google Sheets: Extensions → Apps Script
 * 2. Удали весь код и вставь этот скрипт
 * 3. Нажми ▶️ Run (выбери setupTulparDatabase)
 * 4. Разреши доступ когда попросит
 * 5. Готово!
 */

function setupTulparDatabase() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // Удаляем дефолтный лист если есть
  const defaultSheet = ss.getSheetByName('Sheet1') || ss.getSheetByName('Лист1');

  // Создаём листы
  createClientsSheet(ss);
  createParcelsSheet(ss);
  createCashSheet(ss);
  createCodesSheet(ss);

  // Удаляем дефолтный лист после создания других
  if (defaultSheet && ss.getSheets().length > 1) {
    ss.deleteSheet(defaultSheet);
  }

  // Переименовываем таблицу
  ss.rename('Tulpar Express - Database');

  SpreadsheetApp.getUi().alert('✅ Tulpar Express Database настроена!\n\n4 листа созданы:\n- clients\n- parcels\n- cash\n- codes (last_number = 5000)');
}

function createClientsSheet(ss) {
  let sheet = ss.getSheetByName('clients');
  if (!sheet) {
    sheet = ss.insertSheet('clients');
  }

  // Заголовки
  const headers = ['chat_id', 'code', 'full_name', 'phone', 'reg_date'];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  // Форматирование
  sheet.getRange(1, 1, 1, headers.length)
    .setFontWeight('bold')
    .setBackground('#4285f4')
    .setFontColor('white');
  sheet.setFrozenRows(1);

  // Ширина колонок
  sheet.setColumnWidth(1, 120); // chat_id
  sheet.setColumnWidth(2, 100); // code
  sheet.setColumnWidth(3, 200); // full_name
  sheet.setColumnWidth(4, 150); // phone
  sheet.setColumnWidth(5, 120); // reg_date
}

function createParcelsSheet(ss) {
  let sheet = ss.getSheetByName('parcels');
  if (!sheet) {
    sheet = ss.insertSheet('parcels');
  }

  // Заголовки
  const headers = ['client_code', 'tracking', 'status', 'weight_kg', 'amount_usd', 'amount_som', 'date_china', 'date_bishkek', 'date_delivered'];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  // Форматирование
  sheet.getRange(1, 1, 1, headers.length)
    .setFontWeight('bold')
    .setBackground('#34a853')
    .setFontColor('white');
  sheet.setFrozenRows(1);

  // Data validation для status
  const statusValues = ['CHINA_WAREHOUSE', 'IN_TRANSIT', 'BISHKEK_ARRIVED', 'READY_PICKUP', 'DELIVERED'];
  const statusRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(statusValues, true)
    .build();
  sheet.getRange('C2:C1000').setDataValidation(statusRule);
}

function createCashSheet(ss) {
  let sheet = ss.getSheetByName('cash');
  if (!sheet) {
    sheet = ss.insertSheet('cash');
  }

  // Заголовки
  const headers = ['date', 'client_code', 'amount', 'payment_method', 'status'];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  // Форматирование
  sheet.getRange(1, 1, 1, headers.length)
    .setFontWeight('bold')
    .setBackground('#fbbc04')
    .setFontColor('black');
  sheet.setFrozenRows(1);

  // Data validation для payment_method
  const paymentMethods = ['CASH', 'CARD', 'TRANSFER'];
  const paymentRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(paymentMethods, true)
    .build();
  sheet.getRange('D2:D1000').setDataValidation(paymentRule);

  // Data validation для status
  const statusValues = ['PENDING', 'PAID', 'REFUNDED'];
  const statusRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(statusValues, true)
    .build();
  sheet.getRange('E2:E1000').setDataValidation(statusRule);
}

function createCodesSheet(ss) {
  let sheet = ss.getSheetByName('codes');
  if (!sheet) {
    sheet = ss.insertSheet('codes');
  }

  // Заголовок и начальное значение
  sheet.getRange('A1').setValue('last_number').setFontWeight('bold').setBackground('#ea4335').setFontColor('white');
  sheet.getRange('A2').setValue(5000);

  sheet.setFrozenRows(1);
  sheet.setColumnWidth(1, 150);
}
