# Set Dec Tracker

A Windows desktop app that automates the paperwork for a film/TV **set decoration department**: receipts, petty cash, purchasing, rentals and budget tracking.

I built it for my own job as a department coordinator on studio TV productions, where most of the week went to typing receipts into spreadsheets and expense portals by hand. The app now does most of that work for me.

> All names, show details and sets in this public version are made up. Real production data, API keys and credentials are not included.

## What it does

- **Reads receipts with AI.** Drop photos or PDFs of receipts into a folder. Gemini (vision) extracts the vendor, date, items, tax, total, buyer and set number, including handwritten notes on sticky notes.
- **Keeps the budget tracker up to date.** Writes each receipt into a Google Sheets tracker, groups photos that belong to the same purchase, and flags sets that are going over budget.
- **Fills in the company card portal.** A Playwright bot matches receipts to card transactions, uploads the receipt images and fills in the accounting codes and tax lines.
- **Handles petty cash.** Processes petty cash envelopes per buyer and keeps running balances.
- **Creates paperwork.** Generates cheque requisitions, rental agreements and weekly timesheet PDFs from templates.
- **Imports the shooting schedule.** Parses the schedule so receipts can be tied to the right episode and set.
- **Reports.** Cost reports, budget summaries and alerts inside the app.

## How it's built

| Part | Tech |
|---|---|
| Desktop UI | Python, PySide6 (Qt) |
| Receipt and document reading | Google Gemini API (vision), PyMuPDF, Pillow |
| Data | Google Sheets (gspread), local SQLite |
| Web automation | Playwright |
| PDF generation | ReportLab, PyMuPDF |

About 13,000 lines of Python, organized as:

```
app.py            entry point (Qt app)
core/             data models, settings, AI processing threads, business logic
services/         Google Sheets sync, OCR, card-portal bot, petty cash, cheque requests, rental agreements, schedule parser
ui/               Qt windows and dialogs (review, budget, petty cash, reports, settings)
main.py           timesheet generator
```

## Running it

Requires Windows and Python 3.11.

```bash
pip install -r requirements.txt
playwright install chromium
copy settings.example.json settings.json
```

1. Put your Gemini API key and Google Sheet URL in `settings.json` (or use the in-app Settings screen).
2. Add a Google service-account key as `services/credentials.json` and share your Sheet with that account.
3. Run `python app.py` (or double-click `Run App.bat`).

`settings.json` and `credentials.json` are in `.gitignore`, so your keys never get committed.

## What I'd improve next

- Move the department's buyer names and aliases out of the code and into settings.
- Add automated tests around the receipt parsing and tax math.
- Package it as an installer so other coordinators can use it without setting up Python.

## License

All rights reserved. The code is public to view only. See [LICENSE](LICENSE).
