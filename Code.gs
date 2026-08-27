/**
 * Listino Ortofrutta - backend Google Apps Script
 * =================================================
 * Espone un'API JSON (GET/POST) che legge e scrive sul Google Sheet a cui
 * questo script e' collegato. Nessun Google Cloud, nessuna carta di credito:
 * gira interamente sul tuo account Google normale.
 *
 * INSTALLAZIONE (vedi anche README.md):
 * 1. Apri il tuo Google Sheet -> Estensioni -> Apps Script
 * 2. Cancella il contenuto di default e incolla TUTTO questo file
 * 3. Cambia il valore di API_KEY qui sotto con una stringa segreta a tua scelta
 * 4. Nel menu in alto, seleziona la funzione "inizializza" e clicca "Esegui"
 *    (la prima volta ti chiedera' di autorizzare lo script: e' normale,
 *    e' il TUO script che accede al TUO foglio)
 * 5. Clicca "Esegui" di nuovo per lanciare inizializza() e caricare i 62
 *    prodotti di partenza
 * 6. Clicca "Esegui la distribuzione" (icona in alto a destra) -> "Nuova
 *    implementazione" -> tipo "App web" -> Esegui come "Me",
 *    Chi puo' accedere "Chiunque" -> Implementa
 * 7. Copia l'URL che ti viene dato (finisce con /exec) e mettilo in
 *    .streamlit/secrets.toml insieme alla stessa API_KEY scelta al punto 3
 */

// ATTENZIONE: cambia questa chiave con una stringa segreta a tua scelta,
// e usane la STESSA nel file .streamlit/secrets.toml della app Streamlit.
var API_KEY = "CAMBIA_QUESTA_CHIAVE_1234";

// ID del Google Sheet a cui questo script deve collegarsi esplicitamente
// (necessario se lo script non e' stato creato da dentro il foglio stesso
// tramite Estensioni -> Apps Script, ma come progetto standalone).
var SHEET_ID = "1s2ImQQsrhrZ33Kak5ALp1-rwxdnQ1YiF08YMetpHHSk";
function getSS_() { return SpreadsheetApp.openById(SHEET_ID); }

var PRODOTTI_HEADERS = ["id","categoria","nome","formato","prezzo_base","unita_base","peso_unitario_kg","disponibile","traduzioni_json","ordine","immagine_url"];
var STORICO_HEADERS = ["prodotto_id","data","prezzo_base","unita_base","peso_unitario_kg","prezzo_per_kg"];
var CATEGORIE_HEADERS = ["categoria","en","fr","es","pl","el","pt"];

// ---------------------------------------------------------------------------
// Punti di ingresso HTTP
// ---------------------------------------------------------------------------
function doGet(e) {
  var action = e.parameter.action;
  var key = e.parameter.key;
  if (key !== API_KEY) return jsonResponse_({ error: "unauthorized" });

  if (action === "products") return jsonResponse_(getProducts_());
  if (action === "categories") return jsonResponse_(getCategories_());
  if (action === "history") return jsonResponse_(getHistory_());
  return jsonResponse_({ error: "unknown action" });
}

function doPost(e) {
  var body = JSON.parse(e.postData.contents);
  if (body.key !== API_KEY) return jsonResponse_({ error: "unauthorized" });

  var action = body.action;
  if (action === "update_product") return jsonResponse_(updateProduct_(body.id, body.updates));
  if (action === "create_product") return jsonResponse_(createProduct_(body.nome, body.categoria, body.formato));
  if (action === "delete_product") return jsonResponse_(deleteProduct_(body.id));
  if (action === "add_history") return jsonResponse_(addHistory_(body.entry));
  return jsonResponse_({ error: "unknown action" });
}

function jsonResponse_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ---------------------------------------------------------------------------
// Lettura
// ---------------------------------------------------------------------------
function getSheet_(name) {
  return getSS_().getSheetByName(name);
}

function sheetToObjects_(sheet) {
  var values = sheet.getDataRange().getValues();
  var headers = values[0];
  var rows = values.slice(1);
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][0] === "" || rows[i][0] === null) continue;
    var obj = {};
    for (var j = 0; j < headers.length; j++) obj[headers[j]] = rows[i][j];
    out.push(obj);
  }
  return out;
}

function getProducts_() { return sheetToObjects_(getSheet_("Prodotti")); }
function getCategories_() { return sheetToObjects_(getSheet_("Categorie_Traduzioni")); }
function getHistory_() { return sheetToObjects_(getSheet_("Storico")); }

// ---------------------------------------------------------------------------
// Scrittura
// ---------------------------------------------------------------------------
function findRowById_(sheet, id) {
  var values = sheet.getDataRange().getValues();
  for (var i = 1; i < values.length; i++) {
    if (String(values[i][0]) === String(id)) return i + 1; // 1-based
  }
  return -1;
}

function updateProduct_(id, updates) {
  var sheet = getSheet_("Prodotti");
  var row = findRowById_(sheet, id);
  if (row === -1) return { error: "not found" };

  var headers = PRODOTTI_HEADERS;
  var rowValues = sheet.getRange(row, 1, 1, headers.length).getValues()[0];
  var current = {};
  for (var i = 0; i < headers.length; i++) current[headers[i]] = rowValues[i];

  var merged = {};
  for (var k in current) merged[k] = current[k];
  for (var k2 in updates) merged[k2] = updates[k2];

  var newRow = headers.map(function(h) { return merged[h] !== undefined ? merged[h] : ""; });
  sheet.getRange(row, 1, 1, headers.length).setValues([newRow]);

  // Se prezzo/unita'/peso sono cambiati, registra subito lo storico nella
  // STESSA esecuzione (evita una seconda chiamata di rete dal client).
  var priceChanged = (
    String(current.prezzo_base) !== String(merged.prezzo_base) ||
    String(current.unita_base) !== String(merged.unita_base) ||
    String(current.peso_unitario_kg) !== String(merged.peso_unitario_kg)
  );
  if (priceChanged) {
    var prezzoPerKg = calcPrezzoPerKg_(merged.prezzo_base, merged.unita_base, merged.peso_unitario_kg);
    addHistory_({
      prodotto_id: id,
      data: todayISO_(),
      prezzo_base: merged.prezzo_base,
      unita_base: merged.unita_base,
      peso_unitario_kg: merged.peso_unitario_kg,
      prezzo_per_kg: prezzoPerKg,
    });
  }

  return { success: true, product: merged };
}

function calcPrezzoPerKg_(prezzoBase, unitaBase, pesoUnitarioKg) {
  prezzoBase = Number(prezzoBase);
  if (unitaBase === "kg") return prezzoBase;
  if (unitaBase === "g") return prezzoBase * 1000;
  if (unitaBase === "cassa" || unitaBase === "testa") {
    var peso = Number(pesoUnitarioKg);
    if (peso && peso > 0) return prezzoBase / peso;
    return null;
  }
  return null;
}

function createProduct_(nome, categoria, formato) {
  var sheet = getSheet_("Prodotti");
  var values = sheet.getDataRange().getValues();
  var maxOrdine = -1;
  for (var i = 1; i < values.length; i++) {
    var o = Number(values[i][9]) || 0;
    if (o > maxOrdine) maxOrdine = o;
  }
  var id = "p" + Utilities.getUuid().slice(0, 8);
  sheet.appendRow([id, categoria, nome, formato, 0, "kg", "", "FALSE", "{}", maxOrdine + 1, ""]);
  return { success: true, id: id };
}

// Migrazione additiva: aggiunge la colonna immagine_url senza toccare i dati
// esistenti. Sicura da eseguire piu' volte (non duplica la colonna).
function aggiungiCampoImmagine() {
  var sheet = getSheet_("Prodotti");
  var lastCol = sheet.getLastColumn();
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  if (headers.indexOf("immagine_url") === -1) {
    sheet.getRange(1, lastCol + 1).setValue("immagine_url");
    Logger.log("Colonna 'immagine_url' aggiunta in posizione " + (lastCol + 1) + ". I prezzi esistenti NON sono stati toccati.");
  } else {
    Logger.log("La colonna 'immagine_url' esiste gia', nessuna modifica necessaria.");
  }
}

function deleteProduct_(id) {
  var sheet = getSheet_("Prodotti");
  var row = findRowById_(sheet, id);
  if (row === -1) return { error: "not found" };
  sheet.deleteRow(row);
  return { success: true };
}

function addHistory_(entry) {
  var sheet = getSheet_("Storico");
  sheet.appendRow([
    entry.prodotto_id, entry.data, entry.prezzo_base, entry.unita_base,
    entry.peso_unitario_kg === undefined || entry.peso_unitario_kg === null ? "" : entry.peso_unitario_kg,
    entry.prezzo_per_kg
  ]);
  return { success: true };
}

// ---------------------------------------------------------------------------
// Setup iniziale (esegui una volta sola dall'editor Apps Script)
// ---------------------------------------------------------------------------
function todayISO_() {
  return Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
}

function setupSheet_(ss, name, headers, rows) {
  var sheet = ss.getSheetByName(name);
  if (sheet) { sheet.clear(); } else { sheet = ss.insertSheet(name); }
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }
}

function PRODOTTI_DATA_() {
  return [
    ["p001", "Pomodori", "Pomodoro Ciliegino", "rinfusa", 2.2, "kg", "", "TRUE", "{\"en\": \"Cherry Tomatoes\", \"fr\": \"Tomates Cerises\", \"es\": \"Tomate Cherry\", \"pl\": \"Pomidorki Koktajlowe\", \"el\": \"Ντοματίνια Cherry\", \"pt\": \"Tomate Cherry\"}", 0],
    ["p002", "Pomodori", "Pomodoro Datterino", "rinfusa", 3.2, "kg", "", "TRUE", "{\"en\": \"Datterino Tomatoes\", \"fr\": \"Tomates Datterino\", \"es\": \"Tomate Datterino\", \"pl\": \"Pomidory Datterino\", \"el\": \"Ντοματίνια Datterino\", \"pt\": \"Tomate Datterino\"}", 1],
    ["p003", "Pomodori", "Pomodoro Piccadilly", "rinfusa", 1.6, "kg", "", "TRUE", "{\"en\": \"Piccadilly Tomatoes\", \"fr\": \"Tomates Piccadilly\", \"es\": \"Tomate Piccadilly\", \"pl\": \"Pomidory Piccadilly\", \"el\": \"Ντομάτες Piccadilly\", \"pt\": \"Tomate Piccadilly\"}", 2],
    ["p004", "Pomodori", "Datterino Giallo", "rinfusa", 2.8, "kg", "", "TRUE", "{\"en\": \"Yellow Datterino Tomatoes\", \"fr\": \"Tomates Datterino Jaunes\", \"es\": \"Tomate Datterino Amarillo\", \"pl\": \"Żółte Pomidory Datterino\", \"el\": \"Κίτρινα Ντοματίνια Datterino\", \"pt\": \"Tomate Datterino Amarelo\"}", 3],
    ["p005", "Pomodori", "Pomodori Verdi Lunghi", "cassa", 2.3, "kg", "", "TRUE", "{\"en\": \"Long Green Tomatoes\", \"fr\": \"Tomates Vertes Allongées\", \"es\": \"Tomate Verde Alargado\", \"pl\": \"Podłużne Zielone Pomidory\", \"el\": \"Πράσινες Επιμήκεις Ντομάτες\", \"pt\": \"Tomate Verde Alongado\"}", 4],
    ["p006", "Pomodori", "Pomodoro Verde Tondo", "cassa", 1.5, "kg", "", "TRUE", "{\"en\": \"Round Green Tomato\", \"fr\": \"Tomate Verte Ronde\", \"es\": \"Tomate Verde Redondo\", \"pl\": \"Okrągły Zielony Pomidor\", \"el\": \"Στρογγυλή Πράσινη Ντομάτα\", \"pt\": \"Tomate Verde Redondo\"}", 5],
    ["p007", "Peperoni", "Peperoni Cat. I", "cassa", 1.6, "kg", "", "TRUE", "{\"en\": \"Peppers Cat. I\", \"fr\": \"Poivrons Cat. I\", \"es\": \"Pimientos Cat. I\", \"pl\": \"Papryka Kat. I\", \"el\": \"Πιπεριές Κατ. I\", \"pt\": \"Pimentos Cat. I\"}", 6],
    ["p008", "Peperoni", "Peperoni Cat. II", "cassa", 1.0, "kg", "", "TRUE", "{\"en\": \"Peppers Cat. II\", \"fr\": \"Poivrons Cat. II\", \"es\": \"Pimientos Cat. II\", \"pl\": \"Papryka Kat. II\", \"el\": \"Πιπεριές Κατ. II\", \"pt\": \"Pimentos Cat. II\"}", 7],
    ["p009", "Peperoni", "Peperone Giallo", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Yellow Pepper\", \"fr\": \"Poivron Jaune\", \"es\": \"Pimiento Amarillo\", \"pl\": \"Papryka Żółta\", \"el\": \"Κίτρινη Πιπεριά\", \"pt\": \"Pimento Amarelo\"}", 8],
    ["p010", "Peperoni", "Peperone Rosso", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Red Pepper\", \"fr\": \"Poivron Rouge\", \"es\": \"Pimiento Rojo\", \"pl\": \"Papryka Czerwona\", \"el\": \"Κόκκινη Πιπεριά\", \"pt\": \"Pimento Vermelho\"}", 9],
    ["p011", "Melanzane", "Melanzane Sicilia", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Sicilian Aubergines\", \"fr\": \"Aubergines de Sicile\", \"es\": \"Berenjena de Sicilia\", \"pl\": \"Bakłażan Sycylijski\", \"el\": \"Σικελικές Μελιτζάνες\", \"pt\": \"Beringela da Sicília\"}", 10],
    ["p012", "Melanzane", "Melenzane Paesane", "cassa", 1.2, "kg", "", "TRUE", "{\"en\": \"Local-type Aubergines\", \"fr\": \"Aubergines Paysannes\", \"es\": \"Berenjena Tradicional\", \"pl\": \"Bakłażan Tradycyjny\", \"el\": \"Παραδοσιακή Μελιτζάνα\", \"pt\": \"Beringela Tradicional\"}", 11],
    ["p013", "Melanzane", "Melenzane Nere Sicilia", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Black Sicilian Aubergines\", \"fr\": \"Aubergines Noires de Sicile\", \"es\": \"Berenjena Negra de Sicilia\", \"pl\": \"Czarny Bakłażan Sycylijski\", \"el\": \"Μαύρη Σικελική Μελιτζάνα\", \"pt\": \"Beringela Preta da Sicília\"}", 12],
    ["p014", "Zucchine e Cetrioli", "Zucchine Sicilia Cal.14+21", "cassa", 1.3, "kg", "", "TRUE", "{\"en\": \"Sicilian Courgettes Cal.14+21\", \"fr\": \"Courgettes de Sicile Cal.14+21\", \"es\": \"Calabacín Siciliano Cal.14+21\", \"pl\": \"Cukinia Sycylijska Kal.14+21\", \"el\": \"Σικελικά Κολοκυθάκια Cal.14+21\", \"pt\": \"Courgette Siciliana Cal.14+21\"}", 13],
    ["p015", "Zucchine e Cetrioli", "Zucchine con Fiore Bianco", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"White-flower Courgettes\", \"fr\": \"Courgettes Fleur Blanche\", \"es\": \"Calabacín con Flor Blanca\", \"pl\": \"Cukinia z Białym Kwiatem\", \"el\": \"Κολοκυθάκια με Λευκό Άνθος\", \"pt\": \"Courgette com Flor Branca\"}", 14],
    ["p016", "Zucchine e Cetrioli", "Cetrioli", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Cucumbers\", \"fr\": \"Concombres\", \"es\": \"Pepinos\", \"pl\": \"Ogórki\", \"el\": \"Αγγούρια\", \"pt\": \"Pepinos\"}", 15],
    ["p017", "Insalate e Verdure a Foglia", "Scarole Lisce (8 pz)", "cassa 8pz", 1.5, "kg", "", "TRUE", "{\"en\": \"Smooth Escarole (8 pcs)\", \"fr\": \"Scarole Lisse (8 pcs)\", \"es\": \"Escarola Lisa (8 uds)\", \"pl\": \"Endywia Gładka (8 szt.)\", \"el\": \"Λεία Αντίδια (8 τεμ.)\", \"pt\": \"Escarola Lisa (8 un.)\"}", 16],
    ["p018", "Insalate e Verdure a Foglia", "Scarole Lisce", "sfuso", 1.5, "kg", "", "TRUE", "{\"en\": \"Smooth Escarole\", \"fr\": \"Scarole Lisse\", \"es\": \"Escarola Lisa\", \"pl\": \"Endywia Gładka\", \"el\": \"Λεία Αντίδια\", \"pt\": \"Escarola Lisa\"}", 17],
    ["p019", "Insalate e Verdure a Foglia", "Finocchi (12 teste)", "cassa 12pz", 0.0, "kg", "", "FALSE", "{\"en\": \"Fennel (12 heads)\", \"fr\": \"Fenouil (12 têtes)\", \"es\": \"Hinojo (12 uds)\", \"pl\": \"Koper Włoski (12 szt.)\", \"el\": \"Μάραθος (12 τεμ.)\", \"pt\": \"Funcho (12 un.)\"}", 18],
    ["p020", "Insalate e Verdure a Foglia", "Finocchi", "sfuso", 1.5, "kg", "", "TRUE", "{\"en\": \"Fennel\", \"fr\": \"Fenouil\", \"es\": \"Hinojo\", \"pl\": \"Koper Włoski\", \"el\": \"Μάραθος\", \"pt\": \"Funcho\"}", 19],
    ["p021", "Insalate e Verdure a Foglia", "Verze (6 pz)", "cassa 6pz", 0.0, "kg", "", "FALSE", "{\"en\": \"Savoy Cabbage (6 pcs)\", \"fr\": \"Chou de Milan (6 pcs)\", \"es\": \"Col de Milán (6 uds)\", \"pl\": \"Kapusta Włoska (6 szt.)\", \"el\": \"Λάχανο Σαβόι (6 τεμ.)\", \"pt\": \"Couve Lombarda (6 un.)\"}", 20],
    ["p022", "Insalate e Verdure a Foglia", "Verze", "sfuso", 1.0, "kg", "", "TRUE", "{\"en\": \"Savoy Cabbage\", \"fr\": \"Chou de Milan\", \"es\": \"Col de Milán\", \"pl\": \"Kapusta Włoska\", \"el\": \"Λάχανο Σαβόι\", \"pt\": \"Couve Lombarda\"}", 21],
    ["p023", "Insalate e Verdure a Foglia", "Cavoli (6 pz)", "cassa 6pz", 0.0, "kg", "", "FALSE", "{\"en\": \"Cabbage (6 pcs)\", \"fr\": \"Chou (6 pcs)\", \"es\": \"Repollo (6 uds)\", \"pl\": \"Kapusta (6 szt.)\", \"el\": \"Λάχανο (6 τεμ.)\", \"pt\": \"Couve (6 un.)\"}", 22],
    ["p024", "Insalate e Verdure a Foglia", "Cavoli", "sfuso", 1.5, "kg", "", "TRUE", "{\"en\": \"Cabbage\", \"fr\": \"Chou\", \"es\": \"Repollo\", \"pl\": \"Kapusta\", \"el\": \"Λάχανο\", \"pt\": \"Couve\"}", 23],
    ["p025", "Insalate e Verdure a Foglia", "Lattuga (6 pz)", "cassa 6pz", 0.0, "kg", "", "FALSE", "{\"en\": \"Lettuce (6 pcs)\", \"fr\": \"Laitue (6 pcs)\", \"es\": \"Lechuga (6 uds)\", \"pl\": \"Sałata (6 szt.)\", \"el\": \"Μαρούλι (6 τεμ.)\", \"pt\": \"Alface (6 un.)\"}", 24],
    ["p026", "Insalate e Verdure a Foglia", "Lattuga", "sfuso", 1.5, "kg", "", "TRUE", "{\"en\": \"Lettuce\", \"fr\": \"Laitue\", \"es\": \"Lechuga\", \"pl\": \"Sałata\", \"el\": \"Μαρούλι\", \"pt\": \"Alface\"}", 25],
    ["p027", "Insalate e Verdure a Foglia", "Radicchio", "cassa", 2.5, "kg", "", "TRUE", "{\"en\": \"Radicchio\", \"fr\": \"Radicchio\", \"es\": \"Radicchio\", \"pl\": \"Radicchio\", \"el\": \"Ραντίκιο\", \"pt\": \"Radicchio\"}", 26],
    ["p028", "Agrumi", "Arance con Foglia ITA", "cassa", 1.3, "kg", "", "TRUE", "{\"en\": \"Italian Oranges with Leaf\", \"fr\": \"Oranges Italiennes avec Feuille\", \"es\": \"Naranja Italiana con Hoja\", \"pl\": \"Włoskie Pomarańcze z Liściem\", \"el\": \"Ιταλικά Πορτοκάλια με Φύλλο\", \"pt\": \"Laranja Italiana com Folha\"}", 27],
    ["p029", "Agrumi", "Limoni Primo Fiore", "cassa", 2.0, "kg", "", "TRUE", "{\"en\": \"Primofiore Lemons\", \"fr\": \"Citrons Primofiore\", \"es\": \"Limón Primofiore\", \"pl\": \"Cytryny Primofiore\", \"el\": \"Λεμόνια Primofiore\", \"pt\": \"Limão Primofiore\"}", 28],
    ["p030", "Agrumi", "Mandarino", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Mandarin\", \"fr\": \"Mandarine\", \"es\": \"Mandarina\", \"pl\": \"Mandarynka\", \"el\": \"Μανταρίνι\", \"pt\": \"Tangerina\"}", 29],
    ["p031", "Mele e Pere", "Mela Annurca Cat. II", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Annurca Apple Cat. II\", \"fr\": \"Pomme Annurca Cat. II\", \"es\": \"Manzana Annurca Cat. II\", \"pl\": \"Jabłko Annurca Kat. II\", \"el\": \"Μήλο Annurca Κατ. II\", \"pt\": \"Maçã Annurca Cat. II\"}", 30],
    ["p032", "Mele e Pere", "Mela Annurca Super Fiorioni", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Annurca Apple — Premium\", \"fr\": \"Pomme Annurca — Premium\", \"es\": \"Manzana Annurca — Premium\", \"pl\": \"Jabłko Annurca — Premium\", \"el\": \"Μήλο Annurca — Premium\", \"pt\": \"Maçã Annurca — Premium\"}", 31],
    ["p033", "Mele e Pere", "Mele Golden Melinda", "cassa", 1.5, "kg", "", "TRUE", "{\"en\": \"Golden Melinda Apples\", \"fr\": \"Pommes Golden Melinda\", \"es\": \"Manzana Golden Melinda\", \"pl\": \"Jabłka Golden Melinda\", \"el\": \"Μήλα Golden Melinda\", \"pt\": \"Maçã Golden Melinda\"}", 32],
    ["p034", "Mele e Pere", "Mele Rosse Melinda", "cassa", 1.8, "kg", "", "TRUE", "{\"en\": \"Red Melinda Apples\", \"fr\": \"Pommes Rouges Melinda\", \"es\": \"Manzana Roja Melinda\", \"pl\": \"Czerwone Jabłka Melinda\", \"el\": \"Κόκκινα Μήλα Melinda\", \"pt\": \"Maçã Vermelha Melinda\"}", 33],
    ["p035", "Mele e Pere", "Pere Conference", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Conference Pears\", \"fr\": \"Poires Conférence\", \"es\": \"Pera Conference\", \"pl\": \"Gruszki Conference\", \"el\": \"Αχλάδια Conference\", \"pt\": \"Pera Conference\"}", 34],
    ["p036", "Mele e Pere", "Pere Cosce", "cassa", 1.5, "kg", "", "TRUE", "{\"en\": \"Coscia Pears\", \"fr\": \"Poires Coscia\", \"es\": \"Pera Coscia\", \"pl\": \"Gruszki Coscia\", \"el\": \"Αχλάδια Coscia\", \"pt\": \"Pera Coscia\"}", 35],
    ["p037", "Frutta Estiva", "Nespole", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Loquats\", \"fr\": \"Nèfles du Japon\", \"es\": \"Nísperos\", \"pl\": \"Nieśplik Japoński\", \"el\": \"Μούσμουλα\", \"pt\": \"Nêsperas\"}", 36],
    ["p038", "Frutta Estiva", "Fragole", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Strawberries\", \"fr\": \"Fraises\", \"es\": \"Fresas\", \"pl\": \"Truskawki\", \"el\": \"Φράουλες\", \"pt\": \"Morangos\"}", 37],
    ["p039", "Frutta Estiva", "Prugne", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Plums\", \"fr\": \"Prunes\", \"es\": \"Ciruelas\", \"pl\": \"Śliwki\", \"el\": \"Δαμάσκηνα\", \"pt\": \"Ameixas\"}", 38],
    ["p040", "Frutta Estiva", "Ciliegia Tripla A", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Cherries — Triple A\", \"fr\": \"Cerises — Triple A\", \"es\": \"Cerezas — Triple A\", \"pl\": \"Czereśnie — Triple A\", \"el\": \"Κεράσια — Triple A\", \"pt\": \"Cerejas — Triplo A\"}", 39],
    ["p041", "Frutta Estiva", "Banane del Monte", "cassa", 1.1, "kg", "", "TRUE", "{\"en\": \"Del Monte Bananas\", \"fr\": \"Bananes Del Monte\", \"es\": \"Plátano Del Monte\", \"pl\": \"Banany Del Monte\", \"el\": \"Μπανάνες Del Monte\", \"pt\": \"Banana Del Monte\"}", 40],
    ["p042", "Frutta Estiva", "Banane Chiquita", "cassa", 1.5, "kg", "", "TRUE", "{\"en\": \"Chiquita Bananas\", \"fr\": \"Bananes Chiquita\", \"es\": \"Plátano Chiquita\", \"pl\": \"Banany Chiquita\", \"el\": \"Μπανάνες Chiquita\", \"pt\": \"Banana Chiquita\"}", 41],
    ["p043", "Angurie e Meloni", "Anguria", "cartone 20kg, cal.4/5/6", 0.55, "kg", "", "TRUE", "{\"en\": \"Watermelon\", \"fr\": \"Pastèque\", \"es\": \"Sandía\", \"pl\": \"Arbuz\", \"el\": \"Καρπούζι\", \"pt\": \"Melancia\"}", 42],
    ["p044", "Angurie e Meloni", "Mini Angurie", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Mini Watermelons\", \"fr\": \"Mini Pastèques\", \"es\": \"Mini Sandía\", \"pl\": \"Mini Arbuzy\", \"el\": \"Μίνι Καρπούζια\", \"pt\": \"Mini Melancia\"}", 43],
    ["p045", "Angurie e Meloni", "Melone Cantalupo", "5pz cassa 5kg", 1.0, "kg", "", "TRUE", "{\"en\": \"Cantaloupe Melon\", \"fr\": \"Melon Cantaloup\", \"es\": \"Melón Cantalupo\", \"pl\": \"Melon Kantalupa\", \"el\": \"Πεπόνι Cantaloupe\", \"pt\": \"Melão Cantaloupe\"}", 44],
    ["p046", "Angurie e Meloni", "Meloni Gialli", "cassa", 1.0, "kg", "", "TRUE", "{\"en\": \"Yellow Melons\", \"fr\": \"Melons Jaunes\", \"es\": \"Melón Amarillo\", \"pl\": \"Żółte Melony\", \"el\": \"Κίτρινα Πεπόνια\", \"pt\": \"Melão Amarelo\"}", 45],
    ["p047", "Drupacee", "Nettarina Tabacchera (Padella) AAA", "cassa 7kg", 2.0, "kg", "", "TRUE", "{\"en\": \"Flat Nectarine 'Tabacchera' (saturn) AAA\", \"fr\": \"Nectarine Plate 'Tabacchera' AAA\", \"es\": \"Nectarina Plana 'Tabacchera' AAA\", \"pl\": \"Nektarynka Płaska 'Tabacchera' AAA\", \"el\": \"Επίπεδο Νεκταρίνι 'Tabacchera' AAA\", \"pt\": \"Nectarina Achatada 'Tabacchera' AAA\"}", 46],
    ["p048", "Drupacee", "Nettarina Piatta (Padella) B", "cassa 6kg", 0.0, "kg", "", "FALSE", "{\"en\": \"Flat Nectarine (saturn) B\", \"fr\": \"Nectarine Plate B\", \"es\": \"Nectarina Plana B\", \"pl\": \"Nektarynka Płaska B\", \"el\": \"Επίπεδο Νεκταρίνι B\", \"pt\": \"Nectarina Achatada B\"}", 47],
    ["p049", "Drupacee", "Nettarina tonda A/AA/AAA", "rinfusa", 1.5, "kg", "", "TRUE", "{\"en\": \"Round Nectarine A/AA/AAA\", \"fr\": \"Nectarine Ronde A/AA/AAA\", \"es\": \"Nectarina Redonda A/AA/AAA\", \"pl\": \"Nektarynka Okrągła A/AA/AAA\", \"el\": \"Στρογγυλό Νεκταρίνι A/AA/AAA\", \"pt\": \"Nectarina Redonda A/AA/AAA\"}", 48],
    ["p050", "Drupacee", "Pesche Bianche Cal. 18", "rinfusa", 1.2, "kg", "", "TRUE", "{\"en\": \"White Peaches Cal. 18\", \"fr\": \"Pêches Blanches Cal. 18\", \"es\": \"Melocotón Blanco Cal. 18\", \"pl\": \"Brzoskwinie Białe Kal. 18\", \"el\": \"Λευκά Ροδάκινα Cal. 18\", \"pt\": \"Pêssego Branco Cal. 18\"}", 49],
    ["p051", "Drupacee", "Pesche Gialle Cal. 20", "rinfusa", 1.7, "kg", "", "TRUE", "{\"en\": \"Yellow Peaches Cal. 20\", \"fr\": \"Pêches Jaunes Cal. 20\", \"es\": \"Melocotón Amarillo Cal. 20\", \"pl\": \"Brzoskwinie Żółte Kal. 20\", \"el\": \"Κίτρινα Ροδάκινα Cal. 20\", \"pt\": \"Pêssego Amarelo Cal. 20\"}", 50],
    ["p052", "Drupacee", "Percoche", "rinfusa", 1.3, "kg", "", "TRUE", "{\"en\": \"Percoca (clingstone) Peaches\", \"fr\": \"Pêches Percoche\", \"es\": \"Melocotón Percoca\", \"pl\": \"Brzoskwinie Percoca\", \"el\": \"Ροδάκινα Percoca\", \"pt\": \"Pêssego Percoca\"}", 51],
    ["p053", "Carciofi e Fagiolini", "Carciofi Sicilia", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Sicilian Artichokes\", \"fr\": \"Artichauts de Sicile\", \"es\": \"Alcachofa de Sicilia\", \"pl\": \"Karczochy Sycylijskie\", \"el\": \"Σικελικές Αγκινάρες\", \"pt\": \"Alcachofra da Sicília\"}", 52],
    ["p054", "Carciofi e Fagiolini", "Fagiolini", "cassa", 0.0, "kg", "", "FALSE", "{\"en\": \"Green Beans\", \"fr\": \"Haricots Verts\", \"es\": \"Judías Verdes\", \"pl\": \"Fasolka Szparagowa\", \"el\": \"Φασολάκια\", \"pt\": \"Feijão Verde\"}", 53],
    ["p055", "Radici e Tuberi", "Patate Pasta Gialla", "sacco", 0.7, "kg", "", "TRUE", "{\"en\": \"Yellow-flesh Potatoes\", \"fr\": \"Pommes de Terre Chair Jaune\", \"es\": \"Patata de Pulpa Amarilla\", \"pl\": \"Ziemniaki Żółte\", \"el\": \"Πατάτες Κίτρινης Σάρκας\", \"pt\": \"Batata de Polpa Amarela\"}", 54],
    ["p056", "Radici e Tuberi", "Cipolle Dorate", "sacco", 0.8, "kg", "", "TRUE", "{\"en\": \"Golden Onions\", \"fr\": \"Oignons Dorés\", \"es\": \"Cebolla Dorada\", \"pl\": \"Cebula Złota\", \"el\": \"Χρυσά Κρεμμύδια\", \"pt\": \"Cebola Dourada\"}", 55],
    ["p057", "Radici e Tuberi", "Zucca", "cassa", 0.6, "kg", "", "TRUE", "{\"en\": \"Pumpkin\", \"fr\": \"Potiron\", \"es\": \"Calabaza\", \"pl\": \"Dynia\", \"el\": \"Κολοκύθα\", \"pt\": \"Abóbora\"}", 56],
    ["p058", "Radici e Tuberi", "Carote", "cassa", 1.5, "kg", "", "TRUE", "{\"en\": \"Carrots\", \"fr\": \"Carottes\", \"es\": \"Zanahorias\", \"pl\": \"Marchew\", \"el\": \"Καρότα\", \"pt\": \"Cenouras\"}", 57],
    ["p059", "Erbe Aromatiche", "Prezzemolo", "cassa", 2.0, "kg", "", "TRUE", "{\"en\": \"Parsley\", \"fr\": \"Persil\", \"es\": \"Perejil\", \"pl\": \"Pietruszka\", \"el\": \"Μαϊντανός\", \"pt\": \"Salsa\"}", 58],
    ["p060", "Erbe Aromatiche", "Sedano Bianco", "cassa", 1.5, "kg", "", "TRUE", "{\"en\": \"White Celery\", \"fr\": \"Céleri Blanc\", \"es\": \"Apio Blanco\", \"pl\": \"Seler Biały\", \"el\": \"Λευκό Σέλινο\", \"pt\": \"Aipo Branco\"}", 59],
    ["p061", "Kiwi", "Kiwi Zespri", "cassa", 5.0, "kg", "", "TRUE", "{\"en\": \"Zespri Kiwi\", \"fr\": \"Kiwi Zespri\", \"es\": \"Kiwi Zespri\", \"pl\": \"Kiwi Zespri\", \"el\": \"Ακτινίδιο Zespri\", \"pt\": \"Kiwi Zespri\"}", 60],
    ["p062", "Kiwi", "Kiwi Gold", "cassa", 6.5, "kg", "", "TRUE", "{\"en\": \"Gold Kiwi\", \"fr\": \"Kiwi Gold\", \"es\": \"Kiwi Gold\", \"pl\": \"Kiwi Gold\", \"el\": \"Ακτινίδιο Gold\", \"pt\": \"Kiwi Gold\"}", 61]
  ];
}

function STORICO_DATA_() {
  return [
    ["p001", todayISO_(), 2.2, "kg", "", 2.2],
    ["p002", todayISO_(), 3.2, "kg", "", 3.2],
    ["p003", todayISO_(), 1.6, "kg", "", 1.6],
    ["p004", todayISO_(), 2.8, "kg", "", 2.8],
    ["p005", todayISO_(), 2.3, "kg", "", 2.3],
    ["p006", todayISO_(), 1.5, "kg", "", 1.5],
    ["p007", todayISO_(), 1.6, "kg", "", 1.6],
    ["p008", todayISO_(), 1.0, "kg", "", 1.0],
    ["p012", todayISO_(), 1.2, "kg", "", 1.2],
    ["p014", todayISO_(), 1.3, "kg", "", 1.3],
    ["p017", todayISO_(), 1.5, "kg", "", 1.5],
    ["p018", todayISO_(), 1.5, "kg", "", 1.5],
    ["p020", todayISO_(), 1.5, "kg", "", 1.5],
    ["p022", todayISO_(), 1.0, "kg", "", 1.0],
    ["p024", todayISO_(), 1.5, "kg", "", 1.5],
    ["p026", todayISO_(), 1.5, "kg", "", 1.5],
    ["p027", todayISO_(), 2.5, "kg", "", 2.5],
    ["p028", todayISO_(), 1.3, "kg", "", 1.3],
    ["p029", todayISO_(), 2.0, "kg", "", 2.0],
    ["p033", todayISO_(), 1.5, "kg", "", 1.5],
    ["p034", todayISO_(), 1.8, "kg", "", 1.8],
    ["p036", todayISO_(), 1.5, "kg", "", 1.5],
    ["p041", todayISO_(), 1.1, "kg", "", 1.1],
    ["p042", todayISO_(), 1.5, "kg", "", 1.5],
    ["p043", todayISO_(), 0.55, "kg", "", 0.55],
    ["p045", todayISO_(), 1.0, "kg", "", 1.0],
    ["p046", todayISO_(), 1.0, "kg", "", 1.0],
    ["p047", todayISO_(), 2.0, "kg", "", 2.0],
    ["p049", todayISO_(), 1.5, "kg", "", 1.5],
    ["p050", todayISO_(), 1.2, "kg", "", 1.2],
    ["p051", todayISO_(), 1.7, "kg", "", 1.7],
    ["p052", todayISO_(), 1.3, "kg", "", 1.3],
    ["p055", todayISO_(), 0.7, "kg", "", 0.7],
    ["p056", todayISO_(), 0.8, "kg", "", 0.8],
    ["p057", todayISO_(), 0.6, "kg", "", 0.6],
    ["p058", todayISO_(), 1.5, "kg", "", 1.5],
    ["p059", todayISO_(), 2.0, "kg", "", 2.0],
    ["p060", todayISO_(), 1.5, "kg", "", 1.5],
    ["p061", todayISO_(), 5.0, "kg", "", 5.0],
    ["p062", todayISO_(), 6.5, "kg", "", 6.5]
  ];
}

function CATEGORIE_DATA_() {
  return [
    ["Pomodori", "Tomatoes", "Tomates", "Tomates", "Pomidory", "Ντομάτες", "Tomates"],
    ["Peperoni", "Peppers", "Poivrons", "Pimientos", "Papryka", "Πιπεριές", "Pimentos"],
    ["Melanzane", "Aubergines", "Aubergines", "Berenjenas", "Bakłażany", "Μελιτζάνες", "Beringelas"],
    ["Zucchine e Cetrioli", "Courgettes & Cucumbers", "Courgettes et Concombres", "Calabacines y Pepinos", "Cukinie i Ogórki", "Κολοκυθάκια και Αγγούρια", "Courgettes e Pepinos"],
    ["Insalate e Verdure a Foglia", "Leafy Salads & Greens", "Salades et Légumes-feuilles", "Ensaladas y Verduras de Hoja", "Sałaty i Warzywa Liściaste", "Σαλάτες και Φυλλώδη Λαχανικά", "Saladas e Vegetais de Folha"],
    ["Agrumi", "Citrus Fruit", "Agrumes", "Cítricos", "Owoce Cytrusowe", "Εσπεριδοειδή", "Citrinos"],
    ["Mele e Pere", "Apples & Pears", "Pommes et Poires", "Manzanas y Peras", "Jabłka i Gruszki", "Μήλα και Αχλάδια", "Maçãs e Peras"],
    ["Frutta Estiva", "Summer Fruit", "Fruits d'été", "Fruta de Verano", "Owoce Letnie", "Καλοκαιρινά Φρούτα", "Frutas de Verão"],
    ["Angurie e Meloni", "Watermelons & Melons", "Pastèques et Melons", "Sandías y Melones", "Arbuzy i Melony", "Καρπούζια και Πεπόνια", "Melancias e Melões"],
    ["Drupacee", "Stone Fruit", "Fruits à noyau", "Fruta de Hueso", "Owoce Pestkowe", "Πυρηνόκαρπα", "Frutas de Caroço"],
    ["Carciofi e Fagiolini", "Artichokes & Green Beans", "Artichauts et Haricots Verts", "Alcachofas y Judías Verdes", "Karczochy i Fasolka Szparagowa", "Αγκινάρες και Φασολάκια", "Alcachofras e Feijão Verde"],
    ["Radici e Tuberi", "Roots & Tubers", "Racines et Tubercules", "Raíces y Tubérculos", "Korzenie i Bulwy", "Ρίζες και Κόνδυλοι", "Raízes e Tubérculos"],
    ["Erbe Aromatiche", "Aromatic Herbs", "Herbes Aromatiques", "Hierbas Aromáticas", "Zioła Aromatyczne", "Αρωματικά Βότανα", "Ervas Aromáticas"],
    ["Kiwi", "Kiwi", "Kiwis", "Kiwis", "Kiwi", "Ακτινίδια", "Kiwis"]
  ];
}

function inizializza() {
  var ss = getSS_();
  setupSheet_(ss, "Prodotti", PRODOTTI_HEADERS, PRODOTTI_DATA_());
  setupSheet_(ss, "Storico", STORICO_HEADERS, STORICO_DATA_());
  setupSheet_(ss, "Categorie_Traduzioni", CATEGORIE_HEADERS, CATEGORIE_DATA_());
  Logger.log("Fatto: " + PRODOTTI_DATA_().length + " prodotti, " + STORICO_DATA_().length + " righe di storico, " + CATEGORIE_DATA_().length + " categorie.");
}
