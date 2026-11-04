// Runs resources/glossary_sync/Code.gs under Node behind an HTTP server that
// behaves like an Apps Script web app, for tests/test_glossary_sync_script.py.
//
// What is emulated, because the client depends on it:
// - POST /exec runs doPost, then answers 302 with a Location that serves the
//   result to a GET (the real one points at script.googleusercontent.com);
// - SpreadsheetApp tabs as grids of strings, with getDisplayValues hiding a
//   leading apostrophe the way Sheets does;
// - Utilities.computeDigest returning signed bytes, as Java's does.
//
// Test hooks (not part of Apps Script): POST /__edit {sheet,row,column,value}
// changes one cell as a person would in the sheet; GET /__dump?sheet= returns
// the tab's grid.
//
// Usage: node apps_script_server.js <Code.gs> <token>; prints the port.

const fs = require('fs');
const http = require('http');
const vm = require('vm');
const crypto = require('crypto');

const [codePath, token] = process.argv.slice(2);

class Range {
  constructor(sheet, row, column, rows, columns) {
    Object.assign(this, { sheet, row, column, rows, columns });
  }
  getDisplayValues() {
    const out = [];
    for (let r = 0; r < this.rows; r++) {
      const line = [];
      for (let c = 0; c < this.columns; c++) {
        const value = ((this.sheet.cells[this.row - 1 + r] || [])[this.column - 1 + c]) ?? '';
        line.push(value.startsWith("'") ? value.slice(1) : value);
      }
      out.push(line);
    }
    return out;
  }
  setNumberFormat() { return this; }
  setValues(values) {
    if (values.length !== this.rows || values.some((v) => v.length !== this.columns)) {
      throw new Error('The number of rows or columns in the data does not match the range.');
    }
    values.forEach((line, r) => line.forEach((value, c) => {
      const row = this.row - 1 + r;
      while (this.sheet.cells.length <= row) this.sheet.cells.push([]);
      if (typeof value === 'string' && value.startsWith('=')) {
        throw new Error('A formula was written: ' + value);
      }
      this.sheet.cells[row][this.column - 1 + c] = String(value);
    }));
    return this;
  }
}

class Sheet {
  constructor(name) { this.name = name; this.cells = []; }
  getLastRow() {
    for (let r = this.cells.length - 1; r >= 0; r--) {
      if ((this.cells[r] || []).some((v) => v !== '' && v != null)) return r + 1;
    }
    return 0;
  }
  getLastColumn() {
    return this.cells.reduce((m, line) => {
      let last = 0;
      (line || []).forEach((v, i) => { if (v !== '' && v != null) last = i + 1; });
      return Math.max(m, last);
    }, 0);
  }
  getRange(row, column, rows, columns) { return new Range(this, row, column, rows, columns); }
  clearContents() { this.cells = []; return this; }
  setFrozenRows() { return this; }
}

const book = {
  sheets: {},
  getSheetByName(name) { return this.sheets[name] || null; },
  insertSheet(name) { this.sheets[name] = new Sheet(name); return this.sheets[name]; },
};

const context = {
  SpreadsheetApp: { getActiveSpreadsheet: () => book, flush: () => {} },
  LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
  Utilities: {
    DigestAlgorithm: { SHA_256: 'sha256' },
    Charset: { UTF_8: 'utf8' },
    computeDigest: (algorithm, text) =>
      Array.from(crypto.createHash(algorithm).update(text, 'utf8').digest()).map((b) => (b > 127 ? b - 256 : b)),
  },
  ContentService: {
    MimeType: { JSON: 'application/json' },
    createTextOutput: (text) => ({ text, setMimeType() { return this; } }),
  },
};
vm.createContext(context);
const source = fs.readFileSync(codePath, 'utf8').replace("const TOKEN = 'CHANGE-ME';", 'const TOKEN = ' + JSON.stringify(token) + ';');
vm.runInContext(source + '\n;this.doPost = doPost; this.doGet = doGet;', context);

const results = {};
let next = 0;

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  try {
    if (req.method === 'POST' && url.pathname === '/exec') {
      const output = context.doPost({ postData: { contents: await readBody(req) } });
      const id = String(next++);
      results[id] = output.text;
      res.writeHead(302, { Location: 'http://' + req.headers.host + '/echo?id=' + id });
      return res.end();
    }
    if (req.method === 'GET' && url.pathname === '/echo') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(results[url.searchParams.get('id')]);
    }
    if (req.method === 'POST' && url.pathname === '/echo') {
      // What a client gets for re-POSTing to the redirect: the real one is 405.
      res.writeHead(405);
      return res.end();
    }
    if (req.method === 'GET' && url.pathname === '/exec') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(context.doGet().text);
    }
    if (req.method === 'POST' && url.pathname === '/__edit') {
      const edit = JSON.parse(await readBody(req));
      const sheet = book.getSheetByName(edit.sheet);
      while (sheet.cells.length < edit.row) sheet.cells.push([]);
      sheet.cells[edit.row - 1][edit.column - 1] = edit.value;
      res.writeHead(200);
      return res.end('{}');
    }
    if (req.method === 'GET' && url.pathname === '/__dump') {
      const sheet = book.getSheetByName(url.searchParams.get('sheet'));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify(sheet ? sheet.cells : null));
    }
    res.writeHead(404);
    res.end();
  } catch (err) {
    res.writeHead(500);
    res.end(String(err && err.stack || err));
  }
});

server.listen(0, '127.0.0.1', () => {
  process.stdout.write(server.address().port + '\n');
});
