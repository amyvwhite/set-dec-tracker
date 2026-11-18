"""
EXPENSE AUTOMATION BOT - GOLDEN EXECUTION CONTRACT
=================================================
1. PHOTO UPLOADING & MULTI-PART ARCHITECTURE:
   - Target exact <img> tag in table cell (`images/camera-green.svg` = GREEN/UPLOAD, `images/camera.svg` = BLACK/ALREADY UPLOADED).
   - Black cameras (already uploaded) skip immediately in 0ms without opening modals.
   - Primary modal button (`Add Receipt Image` or `Upload Image From Computer`) is clicked EXACTLY ONCE via JS `el.closest('.x-btn').click()`. Never double-click within 10ms.
   - `was_computer_clicked` guard prevents secondary prompt listeners from opening duplicate slots.
   - `uploaded_filenames = set()` prevents uploading the exact same filename twice in a transaction.
   - Aspect ratio threshold = 3.5. Normal photos (<= 3.5) stay as 1 file. Super long paper rolls (> 3.5) slice into 3 overlapping parts.
   - At the end of `upload_receipt_image`, execute `Ext.WindowMgr.all.elements.forEach(w => w.close())` to close ALL modal windows completely before moving to the next row.
   - `on_trigger_upload` / `on_trigger_fill` query `reversed(self.context.pages)` to lock onto the active `cardholder-txrx` tab on screen.

2. GL DATA FILL & MONTHLY HST RULES:
   - Monthly HST Account Code derived strictly from receipt/transaction date: July = 7507, August = 7508, September = 7509, October = 7510, etc.
   - Line 1 Amount is ALWAYS net subtotal (`netSubtotal = total_val - tax_val`). For returns: `-58.16 - (-6.69) = -51.47`; for purchases: `4.89 - 0.56 = 4.33`.
   - Return receipts (`total_val < 0`) check `Math.abs(tax_val) > 0.001` to trigger `+ Add` for Line 2 HST.
   - HST Line (Account 75XX) must have CO=01, LO=01, EPI="287", SET="" (blank), INS="" (blank), Desc="HST", and Tax Amount.
   - Upload Photos Mode NEVER clicks row expanders or + Add buttons to prevent spawning blank HST lines.
"""

import os
import asyncio
import re
import json
from playwright.async_api import async_playwright
from core.models import Receipt
from typing import List
import time

def prepare_upload_files(file_path):
    """
    Checks if a receipt image is super long/tall (aspect ratio height/width > 2.5).
    If so, slices it vertically into 2 or 3 overlapping segments so each part fits legibly in Expense!
    Returns list of file paths [part1, part2, ...] (or [original_path] if normal ratio).
    """
    if not file_path or not os.path.exists(file_path):
        return [file_path] if file_path else []

    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.pdf']:
        return [file_path]

    try:
        from PIL import Image
        img = Image.open(file_path)
        w, h = img.size
        if w <= 0 or h <= 0:
            return [file_path]

        aspect_ratio = h / float(w)
        if aspect_ratio <= 3.5:
            return [file_path]

        if aspect_ratio > 5.5:
            num_parts = 4
        else:
            num_parts = 3
        slice_h = h / float(num_parts)
        overlap = slice_h * 0.12

        base_dir = os.path.dirname(file_path)
        filename, extension = os.path.splitext(os.path.basename(file_path))

        sliced_paths = []
        for i in range(num_parts):
            top = max(0, int(i * slice_h - (overlap if i > 0 else 0)))
            bottom = min(h, int((i + 1) * slice_h + (overlap if i < num_parts - 1 else 0)))

            crop_box = (0, top, w, bottom)
            cropped = img.crop(crop_box)

            part_path = os.path.join(base_dir, f"{filename}_part{i+1}of{num_parts}{extension}")
            cropped.save(part_path, quality=92)
            sliced_paths.append(part_path)

        return sliced_paths
    except Exception as e:
        print(f"Error preparing upload files: {e}")
        return [file_path]

class ExpenseAutomation:
    def __init__(self, start_url: str = "https://YOUR-EXPENSE-PORTAL.example.com/"):
        self.start_url = start_url
        self.browser = None
        self.context = None
        self.page = None
        self.receipt_queue = None
        self.is_running = True
        self.on_batch_finished = None
        self.on_log = None
        
    async def add_receipts(self, receipts: List[Receipt]):
        pass # No longer used, as we fetch dynamically upon button click in Expense
        
    def _log(self, msg):
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [ExpenseBot] {msg}"
        print(log_line)
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "expense_bot_debug.txt"), "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass
            
        if self.on_log:
            self.on_log(msg)

    async def start(self):
        self.receipt_queue = asyncio.Queue()
        playwright = await async_playwright().start()
        # Launching with a persistent context or just a regular browser
        # Using non-headless so user can login
        try:
            # Try launching user's local Chrome first
            self.browser = await playwright.chromium.launch(headless=False, channel="chrome", args=['--start-maximized'])
        except Exception:
            # Fallback to local Edge if Chrome is not installed
            self.browser = await playwright.chromium.launch(headless=False, channel="msedge", args=['--start-maximized'])
        self.context = await self.browser.new_context(no_viewport=True)
        # We no longer use a queue for receipts.
        # Instead, we inject a persistent floating panel on EVERY page load in Expense.
        await self.context.expose_binding("triggerExpenseFill", self.on_trigger_fill)
        await self.context.expose_binding("triggerExpenseUpload", self.on_trigger_upload)
        await self.context.expose_binding("triggerExpenseLogin", self.on_trigger_login)
        
        await self.context.add_init_script("""
            window.addEventListener('load', () => {
                if (document.getElementById('expense-floating-panel')) return;
                
                const panel = document.createElement('div');
                panel.id = 'expense-floating-panel';
                panel.style.position = 'fixed';
                panel.style.bottom = '30px';
                panel.style.right = '30px';
                panel.style.padding = '15px';
                panel.style.backgroundColor = '#2c3e50';
                panel.style.color = 'white';
                panel.style.zIndex = '999999';
                panel.style.borderRadius = '8px';
                panel.style.boxShadow = '0 5px 15px rgba(0,0,0,0.5)';
                panel.style.border = '2px solid #3498db';
                panel.style.fontFamily = 'Arial, sans-serif';
                panel.style.display = 'flex';
                panel.style.flexDirection = 'column';
                panel.style.gap = '10px';
                
                panel.innerHTML = `
                    <div style="font-weight: bold; font-size: 15px; margin-bottom: 8px; color: #3498db; cursor: move;" id="expense-panel-header">🤖 Set Dec Bot</div>
                    <button id="expense-fill-btn" style="padding: 11px 16px; background: #2ecc71; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 13px; cursor: pointer; letter-spacing: 0.5px; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">FILL DATA</button>
                    <button id="expense-upload-btn" style="padding: 11px 16px; background: #9b59b6; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 13px; cursor: pointer; letter-spacing: 0.5px; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">UPLOAD PHOTOS</button>
                    <button id="expense-login-btn" style="padding: 11px 16px; background: #f39c12; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 13px; cursor: pointer; letter-spacing: 0.5px; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">AUTO LOGIN</button>
                    <div id="expense-status" style="font-size: 12px; color: #bdc3c7; text-align: center; margin-top: 2px;">Ready</div>
                `;
                
                document.body.appendChild(panel);
                
                // Make it draggable
                let isDragging = false;
                let offsetX, offsetY;
                const header = document.getElementById('expense-panel-header');
                
                header.addEventListener('mousedown', function(e) {
                    isDragging = true;
                    const rect = panel.getBoundingClientRect();
                    offsetX = e.clientX - rect.left;
                    offsetY = e.clientY - rect.top;
                });
                
                document.addEventListener('mousemove', function(e) {
                    if (isDragging) {
                        panel.style.left = (e.clientX - offsetX) + 'px';
                        panel.style.top = (e.clientY - offsetY) + 'px';
                        panel.style.right = 'auto';
                        panel.style.bottom = 'auto';
                    }
                });
                
                document.addEventListener('mouseup', function() {
                    isDragging = false;
                });
                
                document.getElementById('expense-fill-btn').addEventListener('click', async () => {
                    document.getElementById('expense-status').innerText = 'Processing...';
                    document.getElementById('expense-status').style.color = '#f1c40f';
                    document.getElementById('expense-fill-btn').disabled = true;
                    
                    try {
                        await window.triggerExpenseFill();
                        document.getElementById('expense-status').innerText = 'Success!';
                        document.getElementById('expense-status').style.color = '#2ecc71';
                    } catch (e) {
                        document.getElementById('expense-status').innerText = 'Error!';
                        document.getElementById('expense-status').style.color = '#e74c3c';
                        alert('Error: ' + e);
                    } finally {
                        setTimeout(() => {
                            document.getElementById('expense-fill-btn').disabled = false;
                            document.getElementById('expense-status').innerText = 'Ready';
                            document.getElementById('expense-status').style.color = '#bdc3c7';
                        }, 2000);
                    }
                });

                document.getElementById('expense-login-btn').addEventListener('click', async () => {
                    document.getElementById('expense-status').innerText = 'Logging in...';
                    document.getElementById('expense-status').style.color = '#f1c40f';
                    document.getElementById('expense-login-btn').disabled = true;
                    
                    try {
                        await window.triggerExpenseLogin();
                        document.getElementById('expense-status').innerText = 'Login Attempted!';
                        document.getElementById('expense-status').style.color = '#2ecc71';
                    } catch (e) {
                        document.getElementById('expense-status').innerText = 'Error!';
                        document.getElementById('expense-status').style.color = '#e74c3c';
                        alert('Error: ' + e);
                    } finally {
                        setTimeout(() => {
                            document.getElementById('expense-login-btn').disabled = false;
                            document.getElementById('expense-status').innerText = 'Ready';
                            document.getElementById('expense-status').style.color = '#bdc3c7';
                        }, 2000);
                    }
                });

                document.getElementById('expense-upload-btn').addEventListener('click', async () => {
                    document.getElementById('expense-status').innerText = 'Processing Image...';
                    document.getElementById('expense-status').style.color = '#f1c40f';
                    document.getElementById('expense-upload-btn').disabled = true;
                    
                    try {
                        await window.triggerExpenseUpload();
                        document.getElementById('expense-status').innerText = 'Success!';
                        document.getElementById('expense-status').style.color = '#2ecc71';
                    } catch (e) {
                        document.getElementById('expense-status').innerText = 'Upload Error!';
                        document.getElementById('expense-status').style.color = '#e74c3c';
                        alert('Upload Error: ' + e);
                    } finally {
                        setTimeout(() => {
                            document.getElementById('expense-upload-btn').disabled = false;
                            document.getElementById('expense-status').innerText = 'Ready';
                            document.getElementById('expense-status').style.color = '#bdc3c7';
                        }, 2000);
                    }
                });
            });
        """)
        
        self.page = await self.context.new_page()
        
        await self.page.goto(self.start_url)
        self._log("Waiting for user to login and reach the Transaction Reconciliation page...")
        
        try:
            # Keep the browser open and the event loop alive
            while self.is_running and self.browser.is_connected():
                await asyncio.sleep(1)
                    
        except Exception as e:
            self._log(f"Error in main loop: {e}")
            await self.browser.close()

    async def on_trigger_login(self, source):
        self._log("Triggered Auto Login from floating panel.")
        try:
            page = source['page']
            from core.settings import load_settings
            settings = load_settings()
            email = settings.get("expense_email", "")
            password = settings.get("expense_password", "")
            
            # Check if already logged in / on Transaction Reconciliation page
            if "cardholder-txrx" in page.url:
                self._log("Already logged in and on Transaction Reconciliation page!")
                return

            if not email or not password:
                raise Exception("Email or password not set in SETTINGS -> Expense Automation Settings!")
            
            # 1. Check if we're already on the email modal
            email_input = await page.query_selector("input[type='email'], input[placeholder*='Email'], input[placeholder*='email']")
            
            if not email_input or not await email_input.is_visible():
                # Need to click the initial Log In button
                login_btn = await page.query_selector("button:has-text('Log In')")
                if login_btn and await login_btn.is_visible():
                    try:
                        await login_btn.click(timeout=2000)
                    except Exception as click_e:
                        self._log(f"Initial login click failed/timed out (maybe modal is already open?): {click_e}")
                
                try:
                    email_input = await page.wait_for_selector("input[type='email'], input[placeholder*='Email'], input[placeholder*='email']", timeout=3000)
                except Exception:
                    self._log("Email input not found, already logged in!")
                    return

            if email_input:
                await email_input.fill(email)
                next_btn = await page.query_selector("button:has-text('Next')")
                if next_btn:
                    await next_btn.click()
            
            # 3. Wait for password field and "Log in" button
            try:
                pass_input = await page.wait_for_selector("input[type='password']", timeout=3000)
                if pass_input:
                    await pass_input.fill(password)
                    submit_btn = await page.query_selector("button[type='submit']")
                    if not submit_btn:
                        submit_btn = await page.query_selector("button:has-text('Log in'), button:has-text('Log In')")
                    if submit_btn:
                        await submit_btn.click()
            except Exception:
                pass
                    
            self._log("Auto Login sequence finished!")
        except Exception as e:
            self._log(f"Error in auto login: {e}")

    def get_filtered_receipts(self):
        from core.database import get_connection, Receipt
        import sqlite3
        conn = get_connection()
        # Row factory is already set to sqlite3.Row in db.py but let's be safe
        try:
            conn.row_factory = sqlite3.Row
        except:
            pass
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM receipts WHERE status IN ("APPROVED", "COMPLETED")')
        rows = cursor.fetchall()
        conn.close()
        
        receipts = []
        for row in rows:
            try:
                # Safely get keys list to avoid key errors
                row_keys = row.keys() if hasattr(row, 'keys') else []
                r = Receipt(
                    id=row['id'], file_path=row['file_path'], file_hash=row['file_hash'], set_number=row['set_number'],
                    special_tab=row['special_tab'] if 'special_tab' in row_keys else None,
                    buyer_name=row['buyer_name'], description=row['description'], vendor=row['vendor'], subtotal=row['subtotal'],
                    shipping=row['shipping'], import_fees=row['import_fees'] if 'import_fees' in row_keys else None, tax=row['tax'], total=row['total'], payment_method=row['payment_method'], date=row['date'],
                    reference_number=row['reference_number'], po_number=row['po_number'], is_rental=bool(row['is_rental']),
                    rental_end_date=row['rental_end_date'], notes=row['notes'], status=row['status'], created_at=row['created_at'],
                    is_greens=bool(row['is_greens']), is_craft=bool(row['is_craft']), is_gas=bool(row['is_gas']), is_parking=bool(row['is_parking']),
                    craft_people=row['craft_people'], episode_code=row['episode_code'], co_code=row['co_code'], loc_code=row['loc_code'], 
                    account_code=row['account_code'], tax_code=row['tax_code'], hst_account=row['hst_account'], expense_only=bool(row['expense_only']),
                    is_usd=bool(row['is_usd']) if 'is_usd' in row_keys else False, exchange_rate=row['exchange_rate'] if 'exchange_rate' in row_keys else None,
                    is_asset=bool(row['is_asset']) if 'is_asset' in row_keys else False
                )
                r.is_already_completed = (row['status'] == 'COMPLETED')
                receipts.append(r)
            except Exception as e:
                self._log(f"Error loading row from DB: {e}")
        
        # Load cutoff days setting
        from core.settings import load_settings
        settings = load_settings()
        cutoff_days_str = settings.get("expense_cutoff_days", "90")
        
        try:
            cutoff_days = int(cutoff_days_str)
        except ValueError:
            cutoff_days = 90 # default fallback
            
        if cutoff_days <= 0:
            self._log(f"Cutoff days set to {cutoff_days}. Showing all {len(receipts)} receipts.")
            return receipts
            
        from datetime import datetime, timedelta
        from dateutil import parser as date_parser
        
        now = datetime.now()
        cutoff_date = now - timedelta(days=cutoff_days)
        filtered = []
        for r in receipts:
            if not r.date:
                filtered.append(r)
                continue
            try:
                r_date = date_parser.parse(r.date, fuzzy=True)
                # Auto-correct OCR year typo (e.g. 2023, 2024, 2025 instead of current year 2026)
                if r_date.year < now.year:
                    r_date = r_date.replace(year=now.year)
                    r.date = r_date.strftime("%Y-%m-%d")

                # Auto-correct OCR month/day inversion typo (e.g. 08/04 parsed as 2026-04-08 instead of 2026-08-04)
                if r_date < cutoff_date and r_date.day <= 12:
                    try:
                        swapped_date = r_date.replace(month=r_date.day, day=r_date.month)
                        if swapped_date >= cutoff_date:
                            r_date = swapped_date
                            r.date = r_date.strftime("%Y-%m-%d")
                    except Exception:
                        pass
                    
                if r_date >= cutoff_date:
                    filtered.append(r)
                else:
                    self._log(f"Skipping receipt {r.vendor} (${r.total}) from {r.date} because it is older than {cutoff_days} days.")
            except Exception as e:
                # If date parsing fails, keep it in the list to be safe
                filtered.append(r)
                
        self._log(f"Filtered database receipts: {len(filtered)} out of {len(receipts)} are within the last {cutoff_days} days.")
        return filtered

    async def on_trigger_fill(self, source):
        self._log("Triggered fill from floating panel in browser.")
        try:
            page = source.get('page') if isinstance(source, dict) else self.page
            if self.context and self.context.pages:
                for p in reversed(self.context.pages):
                    if not p.is_closed() and "cardholder" in p.url.lower():
                        page = p
                        break
            receipts = self.get_filtered_receipts()
            
            # FILL DATA only fills GL fields and does not open image upload modals
            await self.run_automation(receipts, target_page=page, do_upload=False, skip_fill=False)
            
            if self.on_batch_finished:
                self.on_batch_finished()
        except Exception as e:
            self._log(f"Error in on_trigger_fill: {e}")
            raise e

    async def on_trigger_upload(self, source):
        self._log("Triggered upload ONLY from floating panel.")
        try:
            page = source.get('page') if isinstance(source, dict) else self.page
            if self.context and self.context.pages:
                for p in reversed(self.context.pages):
                    if not p.is_closed() and "cardholder" in p.url.lower():
                        page = p
                        break
            receipts = self.get_filtered_receipts()
            await self.run_automation(receipts, target_page=page, do_upload=True, skip_fill=True)
        except Exception as e:
            self._log(f"Error in on_trigger_upload: {e}")
            raise e

    async def run_automation(self, receipts: List[Receipt], target_page=None, do_upload=False, skip_fill=False):
        used_receipt_ids = set()
        used_row_indices = set()
        page = target_page or self.page
        
        # 1. Identify all transaction rows
        self._log("Table data already confirmed loaded by user.")
        await asyncio.sleep(0.5)
        
        rows = await page.query_selector_all("tr.dt-row:not(.x-grid3-row-body-tr):not(.x-grid-rowbody-tr), .x-grid3-row:not(.x-grid3-row-body-tr), div[role='row']:not([class*='body'])")
        self._log(f"Found {len(rows)} table rows on the page.")
        

        await asyncio.sleep(1.5)
        
        row_data = await page.evaluate('''() => {
            const isMainRow = (el) => {
                const cls = (el.className || '').toString();
                if (cls.includes('body') || cls.includes('detail') || cls.includes('child') || cls.includes('sub-row') || cls.includes('rowbody')) {
                    return false;
                }
                return true;
            };
            const rowEls = Array.from(document.querySelectorAll("tr.dt-row:not(.x-grid3-row-body-tr):not(.x-grid-rowbody-tr), .x-grid3-row:not(.x-grid3-row-body-tr), div[role='row']:not([class*='body'])")).filter(isMainRow);
            
            const getDescInput = (row) => {
                let sub = row.nextElementSibling;
                if (sub) {
                    let inp = sub.querySelector("input[name*='desc'], input[placeholder*='desc'], input[class*='desc']");
                    if (inp) return inp;
                    let inps = Array.from(sub.querySelectorAll('input:not([type="hidden"]), select, textarea'));
                    if (inps.length >= 11) return inps[10];
                }
                return null;
            };

            const isRowFilled = (r, idx, allRows) => {
                let sub = r.nextElementSibling;
                if (sub) {
                    let inps = Array.from(sub.querySelectorAll('input:not([type="hidden"]), select, textarea'));
                    for (let inp of inps) {
                        let name = (inp.name || inp.id || inp.placeholder || '').toLowerCase();
                        if (name.includes('acc') || name.includes('desc') || name.includes('code')) {
                            if (inp.value && inp.value.trim().length > 0) {
                                return true;
                            }
                        }
                    }
                }
                const icons = Array.from(r.querySelectorAll('img, i, span, td, div'));
                const hasBlackDot = icons.some(el => {
                    const h = (el.outerHTML || '').toLowerCase();
                    const src = (el.getAttribute('src') || '').toLowerCase();
                    if (src.includes('camera') || h.includes('camera') || src.includes('minus') || h.includes('minus')) return false;
                    return src.includes('black_dot') || src.includes('circle-dot') || src.includes('closed_row');
                });
                if (hasBlackDot) return true;
                return false;
            };

            const hasImage = (r) => {
                const img = r.querySelector("img[src*='camera'], .x-action-col-icon[data-qtip*='mage'], img[data-qtip*='mage']");
                if (!img) return false;
                const html = (img.outerHTML || '').toLowerCase();
                const src = (img.getAttribute('src') || '').toLowerCase();
                if (html.includes('green') || html.includes('add') || html.includes('plus') || src.includes('add') || src.includes('plus')) return false;
                if (src.includes('camera_add') || src.includes('camera-add') || src.includes('camera_green')) return false;
                return true;
            };

            const checkIsPosted = (rowEl, rIdx) => {
                try {
                    const lockImg = rowEl.querySelector("img[src*='stop'], img[src*='lock'], img[src*='posted_locked'], img[src*='no-entry']");
                    if (lockImg) return true;
                    const actionIcons = Array.from(rowEl.querySelectorAll('.x-action-col-icon, [class*="action"]'));
                    for (const icon of actionIcons) {
                        const bg = window.getComputedStyle(icon).backgroundImage || "";
                        if (bg.includes('stop') || bg.includes('lock') || bg.includes('posted_locked') || bg.includes('no-entry')) {
                            return true;
                        }
                    }
                } catch (e) {}
                return false;
            };

            const checkIsOpen = (rowEl, rIdx) => {
                try {
                    const html = (rowEl.outerHTML || '').toLowerCase();
                    if (html.includes('stop.png') || html.includes('lock.png') || html.includes('posted_locked') || html.includes('no-entry')) {
                        return false;
                    }
                    
                    const icons = Array.from(rowEl.querySelectorAll('img, i, span, td, div'));
                    
                    const isClosed = icons.some(el => {
                        const h = (el.outerHTML || '').toLowerCase();
                        const src = (el.getAttribute('src') || '').toLowerCase();
                        if (src.includes('camera') || h.includes('camera')) return false;
                        return src.includes('black') || src.includes('minus') || src.includes('circle-dot') || src.includes('closed') || h.includes('black_dot');
                    });
                    if (isClosed) return false;
                    return true;
                } catch (e) {
                    return true;
                }
            };

            const getRowMainText = (r) => {
                let txt = r.innerText || r.textContent || "";
                let sub = r.nextElementSibling;
                if (sub) {
                    txt += " " + (sub.innerText || sub.textContent || "");
                    const inps = Array.from(sub.querySelectorAll('input, select, textarea'));
                    for (let inp of inps) {
                        if (inp.value) txt += " " + inp.value;
                    }
                }
                return txt;
            };

            const getMainRowAmount = (r) => {
                let sub = r.nextElementSibling;
                if (sub) {
                    const inps = Array.from(sub.querySelectorAll('input'));
                    for (let inp of inps) {
                        let val = (inp.value || '').replace(/,/g, '').trim();
                        let m = val.match(/(-?\d+\.\d{2})/);
                        if (m) return parseFloat(m[1]);
                    }
                }
                const tds = Array.from(r.querySelectorAll('td, div, span'));
                for (let i = tds.length - 1; i >= 0; i--) {
                    const txt = (tds[i].innerText || tds[i].textContent || '').replace(/,/g, '').trim();
                    const m = txt.match(/(-?\d+\.\d{2})/);
                    if (m) return parseFloat(m[1]);
                }
                return null;
            };

            return rowEls.map((r, idx) => ({
                id: r.getAttribute("value") || r.id || r.getAttribute("data-id") || ("row_" + idx),
                text: getRowMainText(r),
                mainAmount: getMainRowAmount(r),
                isFilled: isRowFilled(r, idx, rowEls),
                hasImage: hasImage(r),
                isPosted: checkIsPosted(r, idx),
                isOpen: checkIsOpen(r, idx)
            }));
        }''')
        
        self.used_receipt_ids = set()

        PARKING_KEYWORDS = [
            "PARK", "PRK", "TORPRK", "GREEN P", "PARKING", "TPA", "METER", 
            "PERMIT", "PAY & DISPLAY", "PAYBYCELL"
        ]

        candidate_pairs = []

        for idx, row in enumerate(rows):
            try:
                if idx >= len(row_data):
                    self._log(f"Row {idx} has NO row_data entry (row_data len={len(row_data)}, rows len={len(rows)}). Skipping.")
                    continue
                
                row_id = row_data[idx].get('id') or f"row_{idx}"
                
                text = row_data[idx].get('text', '')
                if not text.strip():
                    self._log(f"Row {idx} has empty text. Skipping.")
                    continue
                
                is_filled = row_data[idx].get('isFilled', False)
                has_img = row_data[idx].get('hasImage', False)
                skip_fill_this_row = skip_fill

                is_posted = row_data[idx].get('isPosted', False)
                is_open = row_data[idx].get('isOpen', True)

                self._log(f"Row {idx}: text='{text[:30]}' isFilled={is_filled} isOpen={is_open} isPosted={is_posted} hasImg={has_img} mainAmt={row_data[idx].get('mainAmount')}")

                if is_posted or not is_open:
                    self._log(f"Row {idx} is closed / not open. Skipping completely.")
                    continue

                if is_filled and has_img:
                    self._log(f"Row {idx} is fully filled AND has an image. Skipping completely.")
                    continue

                if is_filled and not has_img:
                    if do_upload:
                        skip_fill_this_row = True
                    else:
                        self._log(f"Row {idx} is already filled (has_image={has_img}). Skipping completely.")
                        continue
                    
                text_clean = text.replace(',', '').replace('$', ' ').upper()
                text_words = text_clean.split()
                is_row_parking = any(k in text_clean for k in PARKING_KEYWORDS)
                row_amount = row_data[idx].get('mainAmount')

                for receipt in receipts:
                    if receipt.id in used_receipt_ids:
                        continue

                    import re, datetime

                    total_float = float(receipt.total or 0.0)
                    total_str = f"{total_float:.2f}"
                    total_no_dec = str(int(total_float)) if total_str.endswith('.00') else total_str

                    is_receipt_parking = getattr(receipt, 'is_parking', False) or any(k in (receipt.vendor or "").upper() for k in PARKING_KEYWORDS)

                    # CATEGORY ISOLATION: Non-parking receipts cannot match parking rows
                    if not is_receipt_parking and is_row_parking:
                        continue

                    # BUYER / CARDHOLDER ISOLATION: Prevent matching a receipt for one buyer to a different person's card statement
                    # CRITICAL USER DIRECTIVE: ALL USD receipts ALWAYS belong to Sam Rivera's USD card statement on Expense!
                    if getattr(receipt, 'is_usd', False):
                        pass # Bypass buyer isolation check for USD receipts so they match Sam Rivera's USD card on Expense
                    elif receipt.buyer_name:
                        from core.settings import get_expense_buyer_tokens
                        TEAM_BUYER_ALIASES = get_expense_buyer_tokens()
                        buyer_norm = receipt.buyer_name.upper().strip()
                        raw_tokens = set(re.sub(r'[^A-Z]', ' ', buyer_norm).split())
                        raw_tokens.add(buyer_norm)
                        buyer_tokens = set(raw_tokens)
                        for k, aliases in TEAM_BUYER_ALIASES.items():
                            if k in raw_tokens:
                                buyer_tokens.update(aliases)
                        buyer_tokens = {t for t in buyer_tokens if len(t) >= 2}

                        def _has_word(toks, txt):
                            return any(re.search(r'\b' + re.escape(t) + r'\b', txt) for t in toks)

                        if buyer_tokens and not _has_word(buyer_tokens, text_clean):
                            all_other_team_names = set()
                            for k, aliases in TEAM_BUYER_ALIASES.items():
                                if not (k in raw_tokens):
                                    all_other_team_names.update(aliases)
                            if _has_word(all_other_team_names, text_clean):
                                continue

                    # ── 1. DATE SCORE ─────────────────────────────────────────────
                    date_score = 0
                    date_exact = False
                    date_close = False
                    if receipt.date:
                        if str(receipt.date) in text_clean:
                            date_exact = True
                            date_score = 15
                        else:
                            try:
                                from dateutil import parser as date_parser
                                r_date = date_parser.parse(str(receipt.date), fuzzy=True).date()
                                for d_str in re.findall(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{4}/\d{2}/\d{2}", text_clean):
                                    d = date_parser.parse(d_str, fuzzy=True).date()
                                    diff = abs((r_date - d).days)
                                    if diff == 0:
                                        date_exact = True
                                        date_score = 15
                                        break
                                    elif diff <= 2:
                                        date_close = True
                                        date_score = 5
                                        break
                            except Exception:
                                pass

                    # ── 2. AMOUNT SCORE ───────────────────────────────────────────
                    subtotal_float = float(receipt.subtotal or 0.0)

                    def is_sign_and_val_match(rec_tot, rec_sub, ca):
                        if (ca < 0 and rec_tot > 0) or (ca > 0 and rec_tot < 0):
                            return False
                        return abs(rec_tot - ca) < 0.05 or (rec_sub != 0 and abs(rec_sub - ca) < 0.05)

                    if row_amount is not None and row_amount != 0:
                        amount_exact = is_sign_and_val_match(total_float, subtotal_float, row_amount)
                    else:
                        expense_amounts = [float(n) for n in re.findall(r'-?\d+\.\d{2}', text_clean)]
                        amount_exact = any(is_sign_and_val_match(total_float, subtotal_float, ca) for ca in expense_amounts if ca != 0)

                    if not amount_exact:
                        continue
                    amount_score = 25

                    # ── 3. VENDOR SCORE ───────────────────────────────────────────
                    vendor_score = 0
                    if is_receipt_parking:
                        vendor_score = 20
                    elif receipt.vendor:
                        vendor_raw = receipt.vendor.upper()
                        # Normalize & to AND, and collapse letter+digit spaces (e.g. "A 1" -> "A1")
                        vendor_norm = vendor_raw.replace('&', 'AND')
                        vendor_norm = re.sub(r'\b([A-Z])\s+(\d+)\b', r'\1\2', vendor_norm)
                        
                        text_norm = text_clean.replace('&', 'AND')
                        text_norm = re.sub(r'\b([A-Z])\s+(\d+)\b', r'\1\2', text_norm)

                        vendor_aliases = {vendor_raw, vendor_norm}

                        if "AMAZON" in vendor_norm or "AMZN" in vendor_norm:
                            vendor_aliases.update(["AMAZON", "AMZN"])
                        if "HOME DEPOT" in vendor_norm:
                            vendor_aliases.update(["HOME DEPOT", "THE HOME DEPOT", "HD"])
                        if "IDN" in vendor_norm or "INTERNATIONAL DISTRIBU" in vendor_norm:
                            vendor_aliases.update(["IDN", "INTERNATIONAL DISTRIBUTION NETWORK", "INTERNATIONAL DISTRIBU"])
                        if "WAYFAIR" in vendor_norm or "WF" in vendor_norm:
                            vendor_aliases.update(["WAYFAIR", "WF"])
                        if "SIMONS" in vendor_norm or "LAMAISONSIMONS" in vendor_norm:
                            vendor_aliases.update(["SIMONS", "LAMAISONSIMONS", "LA MAISON SIMONS"])
                        if "DOOR STORE" in vendor_norm:
                            vendor_aliases.update(["DOOR STORE", "THE DOOR STORE"])
                        if "CITY FENCE" in vendor_norm or "URBAN FENCE" in vendor_norm:
                            vendor_aliases.update(["CITY FENCE", "URBAN FENCE"])
                        if "PHYSIOSUPPLIES" in vendor_norm or "MEDILINE" in vendor_norm:
                            vendor_aliases.update(["PHYSIOSUPPLIES", "PHYSIOSUPPLIES CANADA", "MEDILINE", "MEDILINE ENTERPRISES", "MEDILINE ENTERPRISES INC"])
                        if "SHOPPERS DRUG MART" in vendor_norm or "SDM" in vendor_norm or "SHOPPERS" in vendor_norm:
                            vendor_aliases.update(["SHOPPERS DRUG MART", "SDM", "SHOPPERS", "SHOPPERS DRUG"])
                        if "AMERICAN SCREEN" in vendor_norm:
                            vendor_aliases.update(["AMERICAN SCREEN", "AMERICAN SCREEN & WIND", "AMERICAN SCREEN & WINDOW"])
                        if "SCHOLAR" in vendor_norm or "SCHOLARS CHOICE" in vendor_norm:
                            vendor_aliases.update(["SCHOLARS CHOICE", "SP SCHOLARS CHOICE", "SCHOLAR'S CHOICE"])
                        if "BESTFLAG" in vendor_norm or "BEST FLAG" in vendor_norm:
                            vendor_aliases.update(["BESTFLAG", "SP BESTFLAG", "BEST FLAG"])
                        if "PETRO" in vendor_norm or "PETRO-CANADA" in vendor_norm or "PETRO CANADA" in vendor_norm:
                            vendor_aliases.update(["PETRO CANADA", "PETRO-CANADA", "PETROCANADA", "PETRO"])
                        if "SHELL" in vendor_norm:
                            vendor_aliases.update(["SHELL", "SHELL OIL", "SHELL CANADA"])
                        if "ESSO" in vendor_norm or "MOBIL" in vendor_norm:
                            vendor_aliases.update(["ESSO", "MOBIL", "ESSO MOBIL", "ESSO CANADA"])
                        if "NEDCO" in vendor_norm:
                            vendor_aliases.update(["NEDCO", "NEDCO MISSISSAUGA", "NEDCO-MISSISSAUGA", "NO MISSISSAUGA", "NO MISSISAUGA"])
                        if "ABCO" in vendor_norm or "ADDMORE" in vendor_norm:
                            vendor_aliases.update(["ABCO", "ABCO GROUP", "ABCO OFFICE", "ADDMORE", "ADDMORE OFFICE", "ADDMORE OFFICE FURNITU", "ADDMORE OFFICE FURNITURE"])
                        if "TORONTO PARKING" in vendor_norm or "TORPRKAUT" in vendor_norm or "GREEN P" in vendor_norm:
                            vendor_aliases.update(["TORONTO PARKING AUTHORITY", "TORPRKAUT", "TORONTO PARKING", "GREEN P", "GREEN P PARKING"])
                        if "PIONEER" in vendor_norm:
                            vendor_aliases.update(["PIONEER", "PIONEER PETROLEUM"])
                        if "HOME SOCIETE" in vendor_norm or "MUST" in vendor_norm:
                            vendor_aliases.update(["HOME SOCIETE", "HOME SOCIETE TORONTO", "MUST", "MUST SOCIETE", "MUST SOCIÉTÉ", "MUST SOCIT"])
                        if "HOME HARDWARE" in vendor_norm:
                            vendor_aliases.update(["HOME HARDWARE", "HME HDWE", "HOME HDWE", "IMPERIAL HME HDWE"])

                        row_text_alpha = re.sub(r'[^A-Z0-9]', '', text_norm)

                        for alias in vendor_aliases:
                            alias_alpha = re.sub(r'[^A-Z0-9]', '', alias)
                            if alias_alpha and (alias_alpha in row_text_alpha or row_text_alpha in alias_alpha):
                                vendor_score = 20
                                break
                        
                        if vendor_score == 0:
                            v_words = [re.sub(r'[^A-Z0-9]', '', w) for w in vendor_norm.split()]
                            v_words = [w for w in v_words if w and w not in ('INC', 'CO', 'LTD', 'CORP', 'LLC', 'CANADA', 'US', 'USA', 'ECOMM', 'SALES', 'COM')]
                            row_words = [re.sub(r'[^A-Z0-9]', '', w) for w in text_norm.split() if w]
                            if v_words:
                                matched_words = sum(1 for vw in v_words if vw in row_words or any(vw in rw or rw in vw for rw in row_words if len(rw) >= 3 and len(vw) >= 3))
                                if matched_words >= len(v_words) or (len(v_words) > 1 and matched_words >= len(v_words) - 1):
                                    vendor_score = 15
                                elif matched_words >= 1:
                                    vendor_score = 10

                        if vendor_score == 0:
                            is_parking_receipt = getattr(receipt, 'is_parking', False) or any(k in (receipt.vendor or "").upper() or k in (receipt.description or "").upper() for k in ["PARK", "PRK", "TORPRK", "TPA", "METER", "ZEAG", "CITY OF TORONTO"])
                            is_parking_row = any(k in text_norm for k in ["PARK", "PRK", "TORPRK", "TPA", "METER", "ZEAG", "TORONTO PARKING"])
                            if is_parking_receipt and is_parking_row and amount_exact:
                                vendor_score = 15

                        if vendor_score == 0:
                            is_gas_receipt = getattr(receipt, 'is_gas', False) or any(k in (receipt.vendor or "").upper() or k in (receipt.description or "").upper() for k in ["PETRO", "SHELL", "ESSO", "PIONEER", "ULTRAMAR", "MOBIL", "HUSKY", "IRVING", "GAS", "FUEL"])
                            is_gas_row = any(k in text_norm for k in ["PETRO", "SHELL", "ESSO", "PIONEER", "ULTRAMAR", "MOBIL", "HUSKY", "IRVING", "GAS", "FUEL"])
                            if is_gas_receipt and is_gas_row and amount_exact:
                                vendor_score = 15

                    # Strict Vendor Check: If vendor score is 0, reject completely different vendors
                    if vendor_score == 0:
                        continue

                    total_score = vendor_score + date_score + amount_score
                    self._log(f"  Candidate Pair: {receipt.vendor} ${receipt.total} → Row {idx} ({text_clean[:40]}) | score={total_score} (vendor={vendor_score}, date={date_score}, amount={amount_score})")

                    candidate_pairs.append({
                        'score': total_score,
                        'amount_exact': amount_exact,
                        'date_exact': date_exact,
                        'row_idx': idx,
                        'row_id': row_id,
                        'row': row,
                        'receipt': receipt,
                        'skip_fill_this_row': skip_fill_this_row,
                        'text': text
                    })
            except Exception as e:
                self._log(f"Error evaluating candidate pairs for row {idx}: {e}")

        # Sort all candidate pairs globally by score, exact amount, exact date descending
        candidate_pairs.sort(key=lambda x: (x['score'], 1 if x['amount_exact'] else 0, 1 if x['date_exact'] else 0), reverse=True)

        used_rows = set()

        for pair in candidate_pairs:
            receipt = pair['receipt']
            idx = pair['row_idx']
            row_id = pair.get('row_id')
            skip_fill_this_row = pair.get('skip_fill_this_row', False)
            text = pair['text']

            if receipt.id in used_receipt_ids or idx in used_rows:
                continue

            used_rows.add(idx)
            used_receipt_ids.add(receipt.id)
            self._log(f"Processing matched pair: {receipt.vendor} ${receipt.total} on Row {idx} (Score {pair['score']})")
            
            try:
                # Query exact element by row_id to avoid index mismatch
                r = None
                if row_id:
                    # Use [id='...'] instead of #... to avoid CSS SyntaxError on digit IDs
                    r = await page.query_selector(f"[value='{row_id}'], [id='{row_id}']")
                if not r:
                    r = pair['row']

                # Double-check if the candidate row is already expanded
                try:
                    already_expanded = await r.evaluate("""el => {
                        const html = (el.outerHTML || '').toLowerCase();
                        if (html.includes('details_close') || html.includes('minus')) return true;
                        let body = el.querySelector('.x-grid3-row-body, .x-grid-rowbody, .x-grid-rowbody-wrap');
                        if (body && body.offsetHeight > 0) return true;
                        let inps = el.querySelectorAll('input, select, textarea');
                        if (inps.length >= 1) return true;
                        return false;
                    }""")
                    
                    # ── STEP 1: CHECK CIRCLE ICON DIRECTLY ──
                    # Green Circle = OPEN (Click & Fill) | Black Dot = FILLED (Skip)
                    icon_status = await r.evaluate("""(row) => {
                        const sub = row.nextElementSibling;
                        if (sub && sub.querySelectorAll('input:not([type="hidden"]), select, textarea').length >= 4 && window.getComputedStyle(sub).display !== 'none') {
                            return "OPEN";
                        }
                        const body = row.querySelector('.x-grid3-row-body, .x-grid-rowbody');
                        if (body && body.querySelectorAll('input:not([type="hidden"]), select, textarea').length >= 4 && window.getComputedStyle(body).display !== 'none') {
                            return "OPEN";
                        }

                        const imgs = Array.from(row.querySelectorAll('img, i, span, td, div'));
                        const hasGreenPlus = imgs.some(img => {
                            const h = (img.outerHTML || '').toLowerCase();
                            const src = (img.getAttribute('src') || '').toLowerCase();
                            if (src.includes('camera') || h.includes('camera') || h.includes('bucket')) return false;
                            return h.includes('green') || h.includes('plus') || src.includes('plus') || src.includes('add');
                        });
                        if (hasGreenPlus) return "GREEN";

                        const hasBlackDot = imgs.some(img => {
                            const h = (img.outerHTML || '').toLowerCase();
                            const src = (img.getAttribute('src') || '').toLowerCase();
                            const cls = (img.className || '').toLowerCase();
                            if (src.includes('camera') || h.includes('camera') || h.includes('bucket')) return false;
                            // Red minus button is delete/remove row, NOT a filled black dot!
                            if (src.includes('minus') || h.includes('minus') || h.includes('remove') || h.includes('delete') || src.includes('plus') || src.includes('add') || h.includes('green')) return false;
                            return src.includes('black') || cls.includes('closed') || src.includes('circle-dot');
                        });
                        if (hasBlackDot) return "BLACK";

                        // If not black dot, it is OPEN!
                        return "OPEN";
                    }""")

                    if not skip_fill_this_row:
                        if icon_status == "BLACK":
                            self._log(f"Row {idx} ({receipt.vendor}) circle icon is BLACK and in Fill mode -> SKIPPING COMPLETELY.")
                            used_receipt_ids.add(receipt.id)
                            continue

                        if icon_status == "GREEN":
                            self._log(f"Row {idx} ({receipt.vendor}) expanding row for GL data fill...")
                            try:
                                exp_btn = await r.query_selector(".x-grid3-row-expander, td.x-grid3-col-expander")
                                if exp_btn:
                                    await exp_btn.click(force=True)
                                    await asyncio.sleep(1.0)
                            except Exception as ex_err:
                                self._log(f"Row expander click note: {ex_err}")
                        elif icon_status == "OPEN":
                            self._log(f"Row {idx} ({receipt.vendor}) is ALREADY OPEN -> FILLING DIRECTLY.")
                except Exception as e:
                    self._log(f"Error checking circle icon: {e}")

                # Allow filling open/unfilled rows on Expense even if receipt status in DB is COMPLETED or APPROVED
                # (Line 813 bypass: user explicitly requested to fill open rows)

                score = pair['score']
                need_confirm = (score < 40)
 
                if need_confirm:
                    title_text = "⚠ Close Match — Upload Image?" if skip_fill_this_row else "⚠ Close Match — Verify?"
                    yes_btn_text = "Yes, Upload" if skip_fill_this_row else "Yes, Fill It"
                        
                    text_safe = text.replace('\n', ' ').replace('`', '').replace("'", "")[:200]
                    self._log(f"Score {score} — asking user to confirm: {receipt.vendor} ${receipt.total}")
                    user_confirmed = await page.evaluate(f"""() => {{
                        return new Promise((resolve) => {{
                            const modal = document.createElement('div');
                            modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:999999;display:flex;align-items:center;justify-content:center;';
                            const box = document.createElement('div');
                            box.style.cssText = 'background:#1a1a2e;color:#eee;padding:24px;border-radius:12px;max-width:480px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4);font-family:sans-serif;border:1px solid #333;';
                            box.innerHTML = `
                                <h3 style="margin:0 0 12px;color:#ffaa00;font-size:15px;">{title_text}</h3>
                                <p style="margin:0 0 6px;font-size:13px;"><span style="color:#aaa;">Receipt:</span> <strong>{receipt.vendor}</strong> — <strong>${receipt.total}</strong> — <strong>{receipt.date}</strong></p>
                                <p style="margin:0 0 16px;font-size:12px;color:#888;word-break:break-all;">{text_safe}</p>
                                <div style="display:flex;gap:10px;justify-content:flex-end;">
                                    <button id="btn-no" style="padding:8px 18px;border:none;background:#c0392b;color:white;border-radius:6px;cursor:pointer;font-size:13px;">Skip</button>
                                    <button id="btn-yes" style="padding:8px 18px;border:none;background:#27ae60;color:white;border-radius:6px;cursor:pointer;font-size:13px;">{yes_btn_text}</button>
                                </div>`;
                            modal.appendChild(box);
                            document.body.appendChild(modal);
                            document.getElementById('btn-yes').onclick = () => {{ modal.remove(); resolve(true); }};
                            document.getElementById('btn-no').onclick  = () => {{ modal.remove(); resolve(false); }};
                        }});
                    }}""")
                    if not user_confirmed:
                        self._log(f"User skipped: {receipt.vendor} ${receipt.total}")
                        continue
                else:
                    self._log(f"Score {pair['score']} — auto-filling: {receipt.vendor} ${receipt.total}")

                used_receipt_ids.add(receipt.id)

                # ── STRICT SEQUENTIAL PIPELINE ──
                # Step 1: Check if circle is green (open) or black (filled)
                # If black -> SKIP IMMEDIATELY!
                if skip_fill_this_row:
                    self._log(f"Row {idx} ({receipt.vendor}) in Upload Photos mode.")
                    result = "Skipped - Uploading photo"
                else:
                    # Fill in transaction GL Line 1 + spawn Line 2 for HST tax split as needed
                    self._log(f"Attempting to fill data for {receipt.vendor}...")
                    result = await self.fill_receipt_data(r, receipt, page=page, row_idx=idx, row_id=row_id, total_amount=float(receipt.total) if receipt.total else None)
                    
                    self._log(f"Fill Data Result for {receipt.vendor}: {result}")
                    
                    await page.evaluate("""(msg) => {
                        let div = document.createElement('div');
                        div.style.position = 'fixed'; div.style.top = '70px'; div.style.left = '50%'; div.style.transform = 'translateX(-50%)';
                        div.style.background = 'blue'; div.style.color = 'white'; div.style.padding = '10px'; div.style.zIndex = '999999';
                        div.innerText = msg;
                        document.body.appendChild(div); setTimeout(() => div.remove(), 5000);
                    }""", f"Bot: {receipt.vendor} Fill Result = {result}")
                
                upload_success = True
                if do_upload:
                    # Close any leftover open windows before attempting upload for this row
                    await page.evaluate("""() => {
                        try {
                            if (typeof Ext !== 'undefined' && Ext.WindowMgr) {
                                const wins = Ext.WindowMgr.all ? Ext.WindowMgr.all.elements : [];
                                wins.forEach(w => { try { w.close(); } catch(e){} });
                            }
                        } catch(e) {}
                    }""")
                    await asyncio.sleep(0.5)

                    self._log(f"Attempting to upload image for {receipt.vendor}...")
                    upload_result = await self.upload_receipt_image(r, receipt, page)
                    self._log(f"Upload Image Result for {receipt.vendor}: {upload_result}")
                    if "Success" in upload_result or "Skipped" in upload_result:
                        upload_success = True
                    else:
                        upload_success = False
                        
                if result and result.startswith("Filled successfully"):
                    try:
                        from core.database import update_receipt
                        receipt.status = "COMPLETED"
                        update_receipt(receipt)
                        self._log(f"Successfully marked receipt {receipt.id} ({receipt.vendor}) as COMPLETED in DB.")
                    except Exception as db_err:
                        self._log(f"Error marking receipt as COMPLETED in DB: {db_err}")

            except Exception as e:
                self._log(f"Error processing row: {e}")

        self._log("Automation complete. Did not auto-click save to allow user review.")
        # Keep browser open for a bit so user can see result
        await asyncio.sleep(2)

    async def upload_receipt_image(self, main_row, receipt: Receipt, page):
        import os
        if not receipt.file_path or not os.path.exists(receipt.file_path):
            return "No valid file path"
        try:
            upload_files = prepare_upload_files(receipt.file_path)
            tot_str = f"{float(receipt.total):.2f}" if receipt.total else ""
            camera_btn = None
            
            # Strict Camera Button Finder: targets exact IMG / A tag, excluding container TD / TR / DIV
            camera_btn_handle = await main_row.evaluate_handle("""mainRow => {
                const sub = mainRow.nextElementSibling;
                const elements = [];
                elements.push(...Array.from(mainRow.querySelectorAll('img, i, a, button, span, td, div')));
                if (sub && window.getComputedStyle(sub).display !== 'none') {
                    elements.push(...Array.from(sub.querySelectorAll('img, i, a, button, span, td, div')));
                }
                
                const found = elements.find(el => {
                    const tag = el.tagName;
                    if (tag === 'TD' || tag === 'TR' || tag === 'TBODY' || tag === 'TABLE') return false;

                    const src = (el.getAttribute('src') || '').toLowerCase();
                    const qtip = (el.getAttribute('data-qtip') || el.getAttribute('title') || '').toLowerCase();
                    const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
                    const html = (el.outerHTML || '').toLowerCase();
                    
                    if (src.includes('camera') || src.includes('bucket') || qtip.includes('receipt') || qtip.includes('image') || txt.includes('img') || html.includes('camera')) {
                        return true;
                    }
                    return false;
                });

                if (found) {
                    return found.tagName === 'IMG' ? found : (found.querySelector('img') || found);
                }
                return null;
            }""")
            if camera_btn_handle:
                camera_btn = camera_btn_handle.as_element()

            if not camera_btn:
                self._log(f"Camera button not found inside row for {receipt.vendor}")
                return "Camera button not found in row"

            # Log exact camera button HTML for empirical verification
            try:
                cb_info = await camera_btn.evaluate("el => ({ tag: el.tagName, src: el.getAttribute('src') || '', html: el.outerHTML })")
                self._log(f"Camera button found for {receipt.vendor}: tag={cb_info.get('tag')} src={cb_info.get('src')} html={cb_info.get('html')[:120]}")
            except Exception:
                pass

            # Check if camera icon indicates photo is ALREADY uploaded (black camera icon)
            is_already_uploaded = await camera_btn.evaluate("""el => {
                 const img = el.tagName === 'IMG' ? el : (el.querySelector('img') || el);
                 const src = (img.getAttribute('src') || '').toLowerCase();
                 const html = (el.outerHTML || '').toLowerCase();
                 
                 // If camera icon explicitly has green or camera-green.svg, it NEEDS upload!
                 if (src.includes('camera-green') || src.includes('green') || html.includes('camera-green')) {
                     return false;
                 }
                 
                 // If camera icon is images/camera.svg (black camera icon), it is ALREADY UPLOADED!
                 if (src === 'images/camera.svg' || src.includes('camera_on') || src.includes('camera_view')) {
                     return true;
                 }
                 
                 return false;
            }""")

            if is_already_uploaded:
                self._log(f"Camera is BLACK (already uploaded) for {receipt.vendor} (${receipt.total}) -> SKIPPING ROW COMPLETELY.")
                return "Skipped - Image already exists"

            # Open modal window directly to inspect receipt bucket content
            files_to_upload = upload_files
 
            try:
                # Check if modal window is already open on screen
                existing_modal = await page.query_selector(".x-window")
                if not existing_modal:
                    # Click camera icon EXACTLY ONCE to open upload window
                    await camera_btn.evaluate("""el => {
                        const img = el.tagName === 'IMG' ? el : (el.querySelector('img') || el);
                        img.click();
                    }""")
                    await asyncio.sleep(1.5)
            except Exception as e:
                self._log(f"Camera click note: {e}")

            # Wait up to 3.0s for the upload modal window to open
            # Loop over each file/part to upload cleanly with strict filename deduplication & sequence verification
            uploaded_filenames = set()
            
            for part_idx, part_file in enumerate(files_to_upload):
                bname = os.path.basename(part_file)
                
                # STRICT DEDUPLICATION: Never upload the exact same file name twice in a transaction!
                if bname in uploaded_filenames:
                    self._log(f"STRICT FILENAME GUARD: Skipping duplicate file upload attempt for {bname}")
                    continue

                # PART SEQUENCE VALIDATION: Verify Part 1 ends with part1, Part 2 ends with part2, etc.
                expected_suffix = f"part{part_idx + 1}of"
                if len(files_to_upload) > 1 and expected_suffix not in bname.lower():
                    self._log(f"STRICT SEQUENCE WARNING: File {bname} does not match expected sequence '{expected_suffix}' for Part {part_idx + 1}")

                self._log(f"Uploading Part {part_idx + 1}/{len(files_to_upload)}: {bname}")
                
                # Target primary green button in modal: "Add Receipt Image" OR "Upload Image From Computer"
                primary_btn = await page.query_selector(".x-window button:has-text('Add Receipt Image'), .x-window button:has-text('Upload Image From Computer'), .x-window .x-btn:has-text('Add Receipt Image'), .x-window .x-btn:has-text('Upload Image From Computer')")
                
                was_computer_clicked = False
                if primary_btn:
                    try:
                        btn_txt = await primary_btn.evaluate("el => (el.innerText || el.textContent || el.value || '').toLowerCase()")
                        if "computer" in btn_txt:
                            was_computer_clicked = True
                        self._log(f"Clicking primary modal button ('{btn_txt}') for Part {part_idx + 1}...")
                        
                        # Click ExtJS x-btn container EXACTLY ONCE via JS to prevent canceling child dialogs
                        await primary_btn.evaluate("""el => {
                            const btn = el.closest('.x-btn') || el.closest('button') || el;
                            btn.click();
                        }""")
                        await asyncio.sleep(1.5)
                    except Exception as btn_err:
                        self._log(f"Primary button click note: {btn_err}")

                # ONLY check child dialog if "Upload Image From Computer" was NOT clicked yet!
                if not was_computer_clicked:
                    child_btn = await page.query_selector("div.x-window-dlg button:has-text('Upload Image From Computer'), .x-window-dlg .x-btn:has-text('Upload Image From Computer'), button:has-text('Upload Image From Computer')")
                    if child_btn:
                        try:
                            child_txt = await child_btn.evaluate("el => (el.innerText || el.textContent || el.value || '').toLowerCase()")
                            if "computer" in child_txt:
                                self._log(f"Clicking child dialog button ('{child_txt}') for Part {part_idx + 1}...")
                                await child_btn.evaluate("""el => {
                                    const btn = el.closest('.x-btn') || el.closest('button') || el;
                                    btn.click();
                                }""")
                                await asyncio.sleep(1.2)
                        except Exception:
                            pass

                # Locate <input type='file'> and attach part_file directly
                file_input = await page.query_selector(".x-window input[type='file'], input[type='file']")
                if file_input:
                    self._log(f"Setting file input for Part {part_idx + 1}: {bname}")
                    await file_input.set_input_files([part_file])
                    uploaded_filenames.add(bname)
                    await asyncio.sleep(3.0)  # Sleep 3.0s for ExtJS POST upload to finish
                else:
                    self._log(f"Warning: input[type=file] not found for Part {part_idx + 1}")
            
            # Close ALL ExtJS windows natively and via DOM button click after upload completes
            await page.evaluate("""() => {
                try {
                    if (typeof Ext !== 'undefined' && Ext.WindowMgr && Ext.WindowMgr.all) {
                        const wins = Ext.WindowMgr.all.elements || [];
                        wins.forEach(w => { try { w.close(); } catch(e){} });
                    }
                } catch(e) {}

                const closeBtns = Array.from(document.querySelectorAll('.x-window button, .x-window .x-btn, .x-tool-close, button'));
                closeBtns.forEach(b => {
                    const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                    if (txt === 'close' || txt === 'x' || b.classList.contains('x-tool-close')) {
                        try { b.click(); } catch(e){}
                    }
                });
            }""")
            await asyncio.sleep(1.5)

            return "Success"
        except Exception as e:
            return f"Upload Error: {e}"

    async def fill_receipt_data(self, main_row, receipt: Receipt, page=None, row_idx=None, row_id=None, total_amount=None):
        is_parking = getattr(receipt, 'is_parking', False) or any(k in (receipt.vendor or "").upper() for k in ["PARK", "PRK", "TORPRK", "TPA", "METER", "CITY OF TORONTO"])
        is_craft = getattr(receipt, 'is_craft', False) or "CRAFT" in (receipt.description or "").upper() or "CRAFT" in (receipt.vendor or "").upper()
        is_asset_receipt = bool(getattr(receipt, 'is_asset', False)) and not bool(getattr(receipt, 'is_rental', False))
        is_203_t = (getattr(receipt, 'special_tab', None) and str(receipt.special_tab).strip().upper() == "203-T") or (getattr(receipt, 'account_code', None) and str(receipt.account_code).strip().split('-')[0] == "4004")

        # Determine HST Account Code strictly from transaction/receipt date (e.g. 7508 for August, 7509 for Sept, 7510 for Oct)
        try:
            from dateutil import parser as date_parser
            r_date = date_parser.parse(str(receipt.date).replace("SEPT", "SEP"), fuzzy=True)
            from core.settings import load_settings
            settings = load_settings()
            hst_account = settings.get(f"hst_month_{r_date.month}", f"75{r_date.month:02d}")
        except Exception:
            hst_account = receipt.hst_account if receipt.hst_account else "7510"

        if is_craft:
            account_code = "3622"
        elif is_parking:
            account_code = "3547"
        elif is_203_t:
            account_code = "4004"
        elif receipt.account_code and receipt.account_code.strip() and receipt.account_code.strip() != "2716":
            account_code = receipt.account_code.strip().split('-')[0]
        else:
            account_code = "2716"
        
        if is_parking:
            # Format for parking in Expense:
            # - Weekly permits: [MMDD-MMDD] TPA PRKG PRMIT: SETS (or GREENS)
            # - Daily TPA parking: [MMDD] TPA PRKG: SET DEC (or GREENS)
            # - Daily other parking: [MMDD] PRKG: SET DEC (or GREENS)
            desc_val = str(receipt.description or "").strip()
            notes_val = str(getattr(receipt, 'notes', '') or "").upper()
            v_text = str(receipt.vendor or "").upper()
            combined_park = f"{desc_val} {notes_val} {v_text}".upper()
            
            d_text = str(receipt.date or "").strip()
            range_str = ""
            m_range = re.search(r'(\d{2}/?\d{2})\s*(?:to|[-–])\s*(\d{2}/?\d{2})', f"{desc_val} {d_text}", re.IGNORECASE)
            if m_range:
                d1 = m_range.group(1).replace('/', '')
                d2 = m_range.group(2).replace('/', '')
                range_str = f"{d1}-{d2}"
            elif d_text:
                try:
                    from dateutil import parser as dparser
                    p_date = dparser.parse(d_text.replace("SEPT", "SEP"), fuzzy=True)
                    range_str = p_date.strftime("%m%d")
                except:
                    range_str = ""

            is_tpa = any(k in combined_park for k in ["TORONTO PARKING", "TORPRKAUT", "GREEN P", "TPA", "T.P.A", "TP PARKING", "CITY OF TORONTO", "TORONTO"])
            is_permit = ("-" in range_str) or any(k in combined_park for k in ["PERMIT", "PRMIT", "TEMP"])
            
            if is_permit and "-" in range_str:
                permit_suffix = "GREENS" if getattr(receipt, 'is_greens', False) else "SETS"
                pfx = f"{range_str} TPA PRKG PRMIT:" if is_tpa else f"{range_str} PRKG PRMIT:"
                description = f"{pfx.strip()} {permit_suffix}".strip()
            else:
                suffix = "GREENS" if getattr(receipt, 'is_greens', False) else "SET DEC"
                pfx = f"{range_str} TPA PRKG:" if is_tpa else f"{range_str} PRKG:"
                description = f"{pfx.strip()} {suffix}".strip()
        elif is_craft:
            desc_val = str(receipt.description or "").strip()
            notes_val = str(getattr(receipt, 'notes', '') or "").upper()
            vendor_val = str(receipt.vendor or "").upper()
            combined_craft = f"{desc_val} {notes_val} {vendor_val}".upper()
            
            d_text = str(receipt.date or "").strip()
            range_str = ""
            m_r = re.search(r'(\d{4})\s*(?:to|[-–])\s*(\d{4})', combined_craft, re.IGNORECASE)
            if m_r:
                range_str = f"{m_r.group(1)}-{m_r.group(2)}"
            elif d_text:
                try:
                    from dateutil import parser as dparser
                    p_date = dparser.parse(d_text.replace("SEPT", "SEP"), fuzzy=True)
                    range_str = p_date.strftime("%m%d")
                except:
                    range_str = ""
            
            suffix = "GREENS" if getattr(receipt, 'is_greens', False) else "SET DEC"
            
            if "LOCK" in combined_craft:
                # Format: [MMDD] CRAFT:SET DEC LOCK-UP
                description = f"{range_str} CRAFT:{suffix} LOCK-UP".strip()
            elif "OFFICE" in combined_craft:
                description = f"{range_str} CRAFT:{suffix} OFFICE".strip()
            else:
                # Format from user: [MMDD] CRAFT X[count]: SET DEC
                craft_count = getattr(receipt, 'craft_people', None)
                if not craft_count:
                    m_p = re.search(r'CRAFT\s*X\s*(\d+)|CRAFT\s*(\d+)|X\s*(\d+)', combined_craft)
                    if m_p:
                        craft_count = m_p.group(1) or m_p.group(2) or m_p.group(3)
                if craft_count and str(craft_count).isdigit():
                    description = f"{range_str} CRAFT X{int(craft_count)}: {suffix}".strip()
                else:
                    description = f"{range_str} CRAFT: {suffix}".strip()
        elif receipt.description and receipt.description.strip():
            description = receipt.description.strip()
            # Ensure (SPLIT WITH ...) is NEVER sent in description field to Expense
            description = re.sub(r'\s*\(\s*SPLIT WITH[^)]*\)', '', description, flags=re.IGNORECASE).strip()
        else:
            description = receipt.vendor if receipt.vendor else "PARKING"

        target_page = page if page else getattr(self, 'page', None)
        if not target_page:
            return "No page instance available"

        subtotal_val = float(receipt.subtotal or 0.0)
        tax_val = float(receipt.tax or 0.0)
        total_val = float(receipt.total or 0.0)

        # USD receipts do NOT spawn Ontario HST lines
        if getattr(receipt, 'is_usd', False):
            tax_val = 0.0
            subtotal_val = total_val

        # For return receipts (negative total), ensure subtotal and tax are properly signed negative
        if total_val < 0:
            if tax_val > 0:
                tax_val = -tax_val
            if subtotal_val > 0:
                subtotal_val = -subtotal_val
            
            # If tax is missing/0 on return, calculate 13% Ontario HST automatically
            if tax_val == 0.0 and not getattr(receipt, 'is_usd', False):
                tax_val = round(total_val * 0.13 / 1.13, 2)

        # For ALL receipts with tax, subtotal MUST BE total_val - tax_val
        if abs(tax_val) > 0.001:
            subtotal_val = round(total_val - tax_val, 2)

        # Prepare line_items_data for multi-item or split receipts
        line_items_data = []
        raw_items = getattr(receipt, 'items', None) or getattr(receipt, 'line_items', None) or []
        if isinstance(raw_items, str):
            try:
                import json
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = []

        if raw_items:
            for item in raw_items:
                if isinstance(item, dict):
                    acc = item.get('account') or item.get('account_code') or account_code
                    st = "" if getattr(receipt, 'is_greens', False) else (item.get('set') or item.get('set_number') or (receipt.set_number if receipt.set_number else ""))
                    desc = item.get('description') or description
                    amt = float(item.get('amount') or item.get('subtotal') or subtotal_val)
                    is_ast = bool(item.get('is_asset', is_asset_receipt))
                else:
                    acc = getattr(item, 'account_code', None) or account_code
                    st = "" if getattr(receipt, 'is_greens', False) else (getattr(item, 'set_number', None) or (receipt.set_number if receipt.set_number else ""))
                    desc = getattr(item, 'description', None) or description
                    amt = float(getattr(item, 'amount', subtotal_val))
                    is_ast = bool(getattr(item, 'is_asset', is_asset_receipt))

                line_items_data.append({
                    'account': acc,
                    'set': st,
                    'description': desc,
                    'amount': amt,
                    'is_asset': is_ast
                })
        elif receipt.set_number and re.search(r'[/,&]+|\band\b', str(receipt.set_number), re.IGNORECASE):
            raw_sets = [s.strip() for s in re.split(r'[/,&]+|\band\b', str(receipt.set_number), flags=re.IGNORECASE) if s.strip()]
            if len(raw_sets) > 1:
                base_split_amt = round((subtotal_val if tax_val != 0 else total_val) / len(raw_sets), 2)
                for st in raw_sets:
                    line_items_data.append({
                        'account': account_code,
                        'set': st,
                        'description': description,
                        'amount': base_split_amt,
                        'is_asset': is_asset_receipt
                    })

        result = await target_page.evaluate("""
            ({ rowIdx, rowId, coCode, loCode, accCode, insCode, descText, setVal, episodeCode, subtotalAmount, taxAmount, hstAccCode, totalAmount, lineItems, isAssetReceipt }) => {
                const isMainRow = (el) => {
                    const cls = (el.className || '').toString();
                    if (cls.includes('body') || cls.includes('detail') || cls.includes('child') || cls.includes('sub-row') || cls.includes('rowbody')) {
                        return false;
                    }
                    return true;
                };
                const rows = Array.from(document.querySelectorAll("tr.dt-row:not(.x-grid3-row-body-tr):not(.x-grid-rowbody-tr), .x-grid3-row:not(.x-grid3-row-body-tr), div[role='row']:not([class*='body'])")).filter(isMainRow);
                
                let targetRow = null;
                if (rowId) {
                    targetRow = document.querySelector(`[value='${rowId}'], [id='${rowId}']`);
                    if (targetRow && !isMainRow(targetRow)) {
                        targetRow = targetRow.closest("tr.dt-row:not(.x-grid3-row-body-tr), .x-grid3-row:not(.x-grid3-row-body-tr), div[role='row']");
                    }
                }
                if (!targetRow && totalAmount !== null && totalAmount !== undefined) {
                    const totVal = parseFloat(totalAmount);
                    const searchAmt = totVal.toFixed(2);
                    targetRow = rows.find(r => {
                        const txt = (r.innerText || r.textContent || '').replace(/,/g, '');
                        return txt.includes(searchAmt);
                    });
                }
                if (!targetRow && rowIdx !== null && rowIdx !== undefined && rows[rowIdx]) {
                    targetRow = rows[rowIdx];
                }
                
                if (!targetRow) return 'Target open row not found';
                
                // ── NATIVE EXTJS 3.X ROW EXPANSION ──
                try {
                    if (typeof Ext !== 'undefined' && Ext.ComponentMgr) {
                        const grid = Ext.ComponentMgr.all.find(c => c && c.store && c.getStore);
                        if (grid && grid.plugins) {
                            const expPlugin = Array.isArray(grid.plugins) ? grid.plugins.find(p => p && typeof p.expandRow === 'function') : (grid.plugins && typeof grid.plugins.expandRow === 'function' ? grid.plugins : null);
                            if (expPlugin) {
                                expPlugin.expandRow(targetRow);
                            }
                        }
                    }
                } catch(e) {}

                // DOM Click Fallback for Row Expansion
                let subPanel = targetRow.nextElementSibling;
                let inputs = subPanel ? Array.from(subPanel.querySelectorAll('input:not([type="hidden"]), select, textarea')) : [];
                
                if (inputs.length < 4 || !subPanel || window.getComputedStyle(subPanel).display === 'none') {
                    const expander = targetRow.querySelector('.x-grid3-row-expander, td.x-grid3-col-expander, img[src*="plus"]:not([src*="camera"]), img[src*="add"]:not([src*="camera"])');
                    if (expander) {
                        ['mousedown', 'mouseup', 'click'].forEach(evt => {
                            try { expander.dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true, view: window })); } catch(e) {}
                        });
                    }

                    subPanel = targetRow.nextElementSibling;
                    if (subPanel) {
                        inputs = Array.from(subPanel.querySelectorAll('input:not([type="hidden"]), select, textarea'));
                    }
                    if (inputs.length < 4) {
                        let body = targetRow.querySelector('.x-grid3-row-body, .x-grid-rowbody');
                        if (body) {
                            inputs = Array.from(body.querySelectorAll('input:not([type="hidden"]), select, textarea'));
                        }
                    }
                }

                const setField = (inputEl, val) => {
                    if (!inputEl || val === undefined || val === null) return;
                    const nameId = ((inputEl.name||'') + ' ' + (inputEl.id||'') + ' ' + (inputEl.className||'') + ' ' + (inputEl.placeholder||'')).toLowerCase();
                    if (nameId.includes('date') || nameId.includes('start') || nameId.includes('end') || nameId.includes('search') || nameId.includes('filter') || inputEl.type === 'date') return;

                    const strVal = String(val).toUpperCase();
                    inputEl.removeAttribute('readonly');
                    inputEl.removeAttribute('disabled');
                    inputEl.readOnly = false;
                    inputEl.disabled = false;
                    
                    try {
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                        nativeInputValueSetter.call(inputEl, strVal);
                    } catch(e) {
                        inputEl.value = strVal;
                    }
                    inputEl.setAttribute('value', strVal);

                    ['focus', 'input', 'change', 'blur'].forEach(evtType => {
                        try { inputEl.dispatchEvent(new Event(evtType, { bubbles: true })); } catch(e) {}
                    });
                    
                    if (typeof Ext !== 'undefined' && Ext.getCmp && inputEl.id) {
                        try {
                            const cmp = Ext.getCmp(inputEl.id);
                            if (cmp && cmp.setValue) cmp.setValue(strVal);
                        } catch(e) {}
                    }
                };

                const getRowFields = (rowEl, rowInputs) => {
                    const inps = rowInputs || (rowEl ? Array.from(rowEl.querySelectorAll('input:not([type="hidden"]), select, textarea')) : []);
                    let f_co = inps.find(i => (i.name||'').toLowerCase().includes('co')) || inps[0];
                    let f_lo = inps.find(i => (i.name||'').toLowerCase().includes('lo')) || inps[1];
                    let f_epi = inps.find(i => (i.name||'').toLowerCase().includes('epi')) || inps[2];
                    let f_acc = inps.find(i => (i.name||'').toLowerCase().includes('acc')) || inps[3];
                    let f_set = inps.find(i => (i.name||'').toLowerCase().includes('set')) || inps[4];
                    let f_ins = inps.find(i => (i.name||'').toLowerCase().includes('ins')) || inps[5];
                    let f_f4 = inps.find(i => (i.name||'').toLowerCase().includes('f4') || (i.name||'').toLowerCase().includes('ff4')) || inps[9];
                    
                    let f_desc = inps.find(i => {
                        const n = ((i.name||'') + ' ' + (i.id||'') + ' ' + (i.className||'') + ' ' + (i.placeholder||'')).toLowerCase();
                        return (n.includes('desc') || n.includes('item') || n.includes('detail') || n.includes('narrative')) && !n.includes('approval');
                    });
                    if (!f_desc && inps.length >= 11) {
                        f_desc = inps[10];
                    }

                    let f_amt = inps.find(i => {
                        const n = ((i.name||'') + ' ' + (i.id||'') + ' ' + (i.className||'') + ' ' + (i.placeholder||'')).toLowerCase();
                        return (n.includes('amt') || n.includes('amount')) && !n.includes('approval');
                    });
                    if (!f_amt && inps.length >= 12) {
                        f_amt = inps[11];
                    }

                    return { co: f_co, lo: f_lo, epi: f_epi, acc: f_acc, set: f_set, ins: f_ins, f4: f_f4, desc: f_desc, amt: f_amt, all: inps };
                };

                const tot = parseFloat(totalAmount || 0);
                const tax = parseFloat(taxAmount || 0);
                const netSubtotal = (Math.abs(tax) > 0.001) ? (tot - tax) : (subtotalAmount ? parseFloat(subtotalAmount) : tot);

                const itemsToFill = (lineItems && lineItems.length > 0) ? lineItems.map((item, idx) => {
                    if (idx === 0 && lineItems.length === 1 && Math.abs(tax) > 0.001) {
                        return { ...item, amount: netSubtotal };
                    }
                    return item;
                }) : [{
                    account: accCode,
                    set: setVal,
                    description: descText,
                    amount: netSubtotal
                }];

                const hasTax = (taxAmount && Math.abs(parseFloat(taxAmount)) > 0.001);
                const totalRowsNeeded = itemsToFill.length + (hasTax ? 1 : 0);

                let body = targetRow.nextElementSibling ? (targetRow.nextElementSibling.querySelector('.x-grid3-row-body, .x-grid-rowbody') || targetRow.nextElementSibling) : targetRow;
                let allInputs = Array.from(body.querySelectorAll('input:not([type="hidden"]), select, textarea'));
                
                let glRows = Array.from(body.querySelectorAll('tr')).filter(tr => tr.querySelectorAll('input:not([type="hidden"]), select').length >= 4);
                let rowStride = (glRows.length > 0) ? glRows[0].querySelectorAll('input:not([type="hidden"]), select, textarea').length : 13;
                if (rowStride < 10) rowStride = 13;

                let neededAdds = totalRowsNeeded - (glRows.length > 0 ? glRows.length : Math.floor(allInputs.length / rowStride));
                for (let k = 0; k < neededAdds; k++) {
                    let addBtn = Array.from(body.querySelectorAll('button, a, img')).find(el => {
                        let txt = (el.innerText || el.textContent || "").trim();
                        let src = (el.getAttribute('src') || "").toLowerCase();
                        let title = (el.getAttribute('title') || el.getAttribute('data-qtip') || "").toLowerCase();
                        return (txt === 'Add' || txt === '+ Add' || txt === '+' || title.includes('add row') || src.includes('icon-add') || src.includes('row_add'));
                    });
                    if (addBtn) addBtn.click();
                }

                glRows = Array.from(body.querySelectorAll('tr')).filter(tr => tr.querySelectorAll('input:not([type="hidden"]), select').length >= 4);

                // ── STEP 1: Fill Subtotal Item Lines ──
                for (let i = 0; i < itemsToFill.length; i++) {
                    const item = itemsToFill[i];
                    let rowInps = glRows[i] ? Array.from(glRows[i].querySelectorAll('input:not([type="hidden"]), select, textarea')) : allInputs.slice(i * rowStride, (i + 1) * rowStride);
                    let fields = getRowFields(glRows[i], rowInps);

                    if (fields.all.length >= 6) {
                        setField(fields.co, coCode);
                        setField(fields.lo, loCode);
                        if (episodeCode) setField(fields.epi, episodeCode);
                        setField(fields.acc, item.account || accCode);
                        if (item.set || setVal) setField(fields.set, item.set || setVal);
                        if (insCode) setField(fields.ins, insCode);

                        // F4 rule: "A" if asset, otherwise strictly EMPTY
                        const isAsset = (item.is_asset || isAssetReceipt);
                        if (fields.f4) {
                            if (isAsset) {
                                setField(fields.f4, "A");
                            } else {
                                fields.f4.value = "";
                                fields.f4.setAttribute('value', '');
                            }
                        }

                        if (fields.desc) setField(fields.desc, (item.description || descText).substring(0, 30));
                        if (fields.amt) setField(fields.amt, parseFloat(item.amount).toFixed(2));
                    }
                }

                // ── STEP 2: Fill HST Tax Line at the bottom ──
                if (hasTax) {
                    const hstRowIdx = itemsToFill.length;
                    let hstRowInps = glRows[hstRowIdx] ? Array.from(glRows[hstRowIdx].querySelectorAll('input:not([type="hidden"]), select, textarea')) : allInputs.slice(hstRowIdx * rowStride, (hstRowIdx + 1) * rowStride);
                    let hstFields = getRowFields(glRows[hstRowIdx], hstRowInps);

                    if (hstFields.all.length >= 6) {
                        [hstFields.set, hstFields.ins, hstFields.f4].forEach(f => {
                            if (f) {
                                f.value = "";
                                f.setAttribute('value', '');
                            }
                        });

                        setField(hstFields.co, coCode);
                        setField(hstFields.lo, loCode);
                        setField(hstFields.epi, "287");
                        setField(hstFields.acc, hstAccCode);
                        setField(hstFields.set, "");
                        setField(hstFields.ins, "");
                        if (hstFields.desc) setField(hstFields.desc, "HST");
                        if (hstFields.amt) setField(hstFields.amt, parseFloat(taxAmount).toFixed(2));
                    }
                }

                // Ensure row sub-panel is visibly open on screen for user review
                try {
                    let sub = targetRow.nextElementSibling;
                    if (sub && (sub.style.display === 'none' || window.getComputedStyle(sub).display === 'none')) {
                        const exp = targetRow.querySelector('.x-grid3-row-expander, td.x-grid3-col-expander, img[src*="plus"]:not([src*="camera"]), img[src*="add"]:not([src*="camera"])');
                        if (exp) exp.click();
                    }
                } catch(e) {}

                return "Filled successfully: items=" + itemsToFill.length + " totalRows=" + totalRowsNeeded;
            }
        """, {
            "rowIdx": row_idx,
            "rowId": row_id,
            "coCode": "02" if receipt.is_usd else "01",
            "loCode": "01",
            "accCode": account_code,
            "insCode": "46" if (is_craft or is_parking) else "40",
            "descText": description,
            "setVal": "" if (is_203_t or getattr(receipt, 'is_greens', False)) else (receipt.set_number if receipt.set_number else ""),
            "episodeCode": "253" if is_203_t else ("297" if (is_parking or is_craft or (receipt.set_number and str(receipt.set_number).upper().startswith("X"))) else (receipt.episode_code if receipt.episode_code else "")),
            "subtotalAmount": subtotal_val if tax_val > 0 else total_val,
            "taxAmount": tax_val,
            "hstAccCode": hst_account,
            "totalAmount": total_amount if total_amount is not None else total_val,
            "lineItems": line_items_data,
            "isAssetReceipt": is_asset_receipt
        })

        # Playwright Native Fallback Fill — only runs if JS evaluate failed or returned < 8 inputs
        if result and (result.startswith('Filled:') or result.startswith('SAFETY ABORT')):
            self._log(f"JS result: {result}. Skipping Playwright fallback.")
            return result
        try:
            tot_search = f"{total_val:.2f}"
            row_loc = target_page.locator(f"tr:has-text('{tot_search}')")
            if await row_loc.count() > 0:
                inps = await row_loc.first.locator("input, select, textarea").all()
                visible_inps = []
                for inp in inps:
                    try:
                        if await inp.is_visible():
                            visible_inps.append(inp)
                    except Exception:
                        pass
                
                target_inps = visible_inps if len(visible_inps) >= 10 else inps
                if len(target_inps) >= 10:
                    co_val = "02" if receipt.is_usd else "01"
                    ins_val = "46" if (receipt.is_craft or is_parking) else (receipt.tax_code if receipt.tax_code else "40")
                    try:
                        await target_inps[0].click(force=True)
                        await target_inps[0].fill(co_val, force=True)
                    except Exception: pass
                    
                    try:
                        await target_inps[1].click(force=True)
                        await target_inps[1].fill("01", force=True)
                    except Exception: pass
                    
                    if is_203_t:
                        epi_val = "253"
                    else:
                        epi_val = "297" if (receipt.is_parking or receipt.is_craft or (receipt.set_number and str(receipt.set_number).upper().startswith("X"))) else (receipt.episode_code if receipt.episode_code else "")
                    if epi_val:
                        try:
                            await target_inps[2].click(force=True)
                            await target_inps[2].fill(epi_val, force=True)
                        except Exception: pass
                        
                    if account_code:
                        try:
                            await target_inps[3].click(force=True)
                            await target_inps[3].fill(account_code, force=True)
                        except Exception: pass
                        
                    if not is_203_t and receipt.set_number and not getattr(receipt, 'is_greens', False):
                        try:
                            await target_inps[4].click(force=True)
                            await target_inps[4].fill(receipt.set_number, force=True)
                        except Exception: pass
                        
                    if ins_val:
                        try:
                            await target_inps[5].click(force=True)
                            await target_inps[5].fill(ins_val, force=True)
                        except Exception: pass
                        
                    if description:
                        try:
                            await target_inps[9].click(force=True)
                            await target_inps[9].fill(description[:30], force=True)
                        except Exception: pass
        except Exception as pe:
            self._log(f"Playwright fill note: {pe}")

        self._log(f"Fill Data Result for {receipt.vendor}: {result}")
        return result
# Helper to run in a thread
from PySide6.QtCore import QThread, Signal

class ExpenseBotThread(QThread):
    batch_finished = Signal()
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.bot = ExpenseAutomation()
        self.loop = None
        
        def on_batch_finished():
            self.batch_finished.emit()
            
        self.bot.on_batch_finished = on_batch_finished

    def stop(self):
        self.bot.is_running = False
        if self.loop is not None:
            # Tell Playwright to close the browser, which will break the loop
            try:
                asyncio.run_coroutine_threadsafe(self.bot.browser.close(), self.loop)
            except Exception:
                pass

    def run(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.bot.start())
        except Exception as e:
            self.error.emit(str(e))
