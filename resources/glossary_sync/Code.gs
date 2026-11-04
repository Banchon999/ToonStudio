/**
 * Toon Studio — team glossary sync.
 *
 * Paste this whole file into the Apps Script editor of the Google Sheet your
 * team shares (Extensions > Apps Script), set TOKEN below, and deploy it as a
 * web app: Deploy > New deployment > Web app, "Execute as: Me",
 * "Who has access: Anyone". Give each team member the web app URL (it ends in
 * /exec) and the token; they enter both in Settings > Glossary > Team Sync.
 *
 * Each glossary series is one tab of the sheet, named after the series. You
 * can read and edit the rows by hand; the app picks your edits up on the next
 * sync. Columns other than the ones below are not kept: the app rewrites the
 * tab when it syncs.
 *
 * After changing this file, deploy again (Deploy > Manage deployments > edit >
 * Version: New version) — the URL stays the same.
 */

// Anyone holding the URL and this token can read and change the glossary.
// Use a long random value, and share it only with the team.
const TOKEN = 'CHANGE-ME';

const COLUMNS = ['source', 'target', 'type', 'gender', 'note', 'aliases', 'updated_by', 'updated_at'];
const API_VERSION = 1;

function doGet() {
  return reply_({ ok: true, service: 'toon-studio-glossary', api: API_VERSION });
}

function doPost(e) {
  let request;
  try {
    request = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply_({ ok: false, error: 'bad_request', message: 'The request was not JSON.' });
  }
  if (!TOKEN || TOKEN === 'CHANGE-ME') {
    return reply_({ ok: false, error: 'not_configured' });
  }
  if (request.token !== TOKEN) {
    return reply_({ ok: false, error: 'unauthorized' });
  }
  const name = String(request.sheet || '').trim();
  if (!name) {
    return reply_({ ok: false, error: 'bad_request', message: 'No glossary name was given.' });
  }
  const book = SpreadsheetApp.getActiveSpreadsheet();

  if (request.action === 'pull') {
    const sheet = book.getSheetByName(name);
    const rows = sheet ? readRows_(sheet) : [];
    return reply_({ ok: true, api: API_VERSION, rows: rows, rev: revision_(rows) });
  }

  if (request.action === 'push') {
    if (!Array.isArray(request.rows)) {
      return reply_({ ok: false, error: 'bad_request', message: 'No rows were sent.' });
    }
    // One writer at a time, and only on top of the rows it merged with: a
    // teammate's sync or a hand edit since then means the app merges again.
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(20000)) {
      return reply_({ ok: false, error: 'busy', message: 'Another sync is running. Try again.' });
    }
    try {
      let sheet = book.getSheetByName(name);
      const current = sheet ? readRows_(sheet) : [];
      if (revision_(current) !== request.base_rev) {
        return reply_({ ok: false, error: 'conflict', rev: revision_(current) });
      }
      if (!sheet) {
        sheet = book.insertSheet(name);
      }
      writeRows_(sheet, request.rows);
      SpreadsheetApp.flush();
      return reply_({ ok: true, api: API_VERSION, rev: revision_(readRows_(sheet)) });
    } finally {
      lock.releaseLock();
    }
  }

  return reply_({ ok: false, error: 'bad_request', message: 'Unknown action.' });
}

// The rows of a tab as objects keyed by column name, read by header so a
// reordered column still lands in the right field. Display values, so a cell
// Sheets turned into a number or a date comes back as the text it shows.
function readRows_(sheet) {
  const lastRow = sheet.getLastRow();
  const lastColumn = sheet.getLastColumn();
  if (lastRow < 1 || lastColumn < 1) {
    return [];
  }
  const values = sheet.getRange(1, 1, lastRow, lastColumn).getDisplayValues();
  const header = values[0].map(function (cell) { return String(cell).trim().toLowerCase(); });
  const rows = [];
  for (let r = 1; r < values.length; r++) {
    const row = {};
    let empty = true;
    COLUMNS.forEach(function (column) {
      const index = header.indexOf(column);
      const value = index >= 0 ? String(values[r][index]) : '';
      if (value !== '') {
        empty = false;
      }
      row[column] = value;
    });
    if (!empty) {
      rows.push(row);
    }
  }
  return rows;
}

function writeRows_(sheet, rows) {
  const values = [COLUMNS.slice()];
  rows.forEach(function (row) {
    values.push(COLUMNS.map(function (column) {
      return asText_(row && row[column] != null ? String(row[column]) : '');
    }));
  });
  sheet.clearContents();
  const range = sheet.getRange(1, 1, values.length, COLUMNS.length);
  // Plain text, or Sheets reads "1990" as a number and "3/4" as a date.
  range.setNumberFormat('@');
  range.setValues(values);
  sheet.setFrozenRows(1);
}

// A leading = + or - would be read as a formula; the apostrophe keeps it text
// and is not part of what the cell displays.
function asText_(value) {
  return /^[=+\-]/.test(value) ? "'" + value : value;
}

function revision_(rows) {
  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(rows),
    Utilities.Charset.UTF_8
  );
  return bytes.map(function (b) { return ((b + 256) % 256).toString(16).padStart(2, '0'); }).join('');
}

function reply_(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}
