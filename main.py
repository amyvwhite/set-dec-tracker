import csv
import os
import fitz
import re
from datetime import datetime, timedelta

def parse_time(time_str):
    """Convert '0700' to a formatted time string if needed, or just return as is."""
    return time_str

def calculate_hours(start_str, end_str, deduct_lunch):
    """Calculate work hours given start '0700' and end '2000'."""
    try:
        start_h = int(start_str[:2])
        start_m = int(start_str[2:])
        end_h = int(end_str[:2])
        end_m = int(end_str[2:])
        
        start_time = start_h + start_m / 60.0
        end_time = end_h + end_m / 60.0
        
        if end_time < start_time:
            end_time += 24 # cross midnight
            
        hours = end_time - start_time
        if deduct_lunch:
            hours -= 1
        return hours
    except Exception as e:
        print(f"Error calculating hours for {start_str}-{end_str}: {e}")
        return 0

def format_time_for_meal(start_str):
    """Return fixed lunch time 1300-1400 for any worked shift."""
    if start_str and start_str.strip():
        return "1300", "1400"
    return "", ""

def get_week_dates(week_ending_date_str):
    """Given '28-Jun-2026', return a dict of formatted dates for Mon-Fri."""
    # Assuming the date is a Sunday
    dt = datetime.strptime(week_ending_date_str, "%d-%b-%Y")
    dates = {}
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    for i in range(7):
        day_dt = dt - timedelta(days=(6-i))
        dates[days[i]] = day_dt.strftime("%d-%b")
    return dates

import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox

def generate_timesheets():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    show_timesheets = os.path.abspath(os.path.join(app_dir, '..', '..', 'TIMESHEETS'))
    timesheets_dir = show_timesheets if os.path.exists(show_timesheets) else os.path.join(app_dir, 'TIMESHEETS')
    # Hide the main tkinter window
    root = tk.Tk()
    root.withdraw()
    
    # Prompt for the CSV file
    csv_path = filedialog.askopenfilename(
        title="Select this week's Timesheet CSV file",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        initialdir=timesheets_dir if os.path.exists(timesheets_dir) else os.path.expanduser("~")
    )
    
    if not csv_path:
        print("No CSV file selected. Exiting.")
        return
        
    # Prompt for the date code (e.g., 0628)
    date_code = simpledialog.askstring(
        "Week Ending Date", 
        "Enter the 4-digit week ending date (e.g., 0628 for June 28th):"
    )
    
    if not date_code or len(date_code) != 4 or not date_code.isdigit():
        print("Invalid date code. Exiting.")
        return
        
    # Setup paths
    # Auto-find timesheet PDF template in timesheets_dir or fallback to SAMPLESHOW default
    template_path = os.path.join(timesheets_dir, "SAMPLESHOW - BLANK FILLABLE TIMESHEET.pdf")
    if not os.path.exists(template_path):
        for f in os.listdir(timesheets_dir):
            if f.lower().endswith(".pdf") and "timesheet" in f.lower():
                template_path = os.path.join(timesheets_dir, f)
                break
    output_dir = os.path.join(timesheets_dir, date_code)
    
    # Create the folder if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory set to: {output_dir}")
    
    # Convert '0628' to '28-Jun-2026'
    try:
        month = int(date_code[:2])
        day = int(date_code[2:])
        year = 2026 # Defaulting to 2026 based on the template
        dt = datetime(year, month, day)
        week_ending = dt.strftime("%d-%b-%Y")
    except Exception as e:
        print(f"Error parsing date code: {e}")
        return
        
    week_dates = get_week_dates(week_ending)
    generated_count = 0
    
    days_columns = [
        ("MON", 7), ("TUE", 8), ("WED", 9), ("THU", 10), ("FRI", 11), ("SAT", 12), ("SUN", 13)
    ]
    
    # Pre-pass: Scan CSV to determine the most common shift time and episode numbers for each day
    from collections import Counter
    day_times_counter = {day_name: Counter() for day_name, _ in days_columns}
    main_day_episodes = {}
    daily_labour_episodes = {}
    weekend_episodes = {}
    all_rows = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        pre_pass_section = ""
        for r in reader:
            all_rows.append(r)
            
            # Track current section during pre-pass
            if r and r[0]:
                name = r[0]
                title = r[1] if len(r) > 1 else ""
                phone = r[2] if len(r) > 2 else ""
                email = r[3] if len(r) > 3 else ""
                if (not title or title.strip() == "") and (not phone or phone.strip() == "") and (not email or email.strip() == ""):
                    pre_pass_section = name.strip()
                    
            for day_name, col_idx in days_columns:
                if col_idx < len(r):
                    cell = r[col_idx].strip()
                    m = re.search(r"(\d{4})\s*-\s*(\d{4})", cell)
                    if m:
                        day_times_counter[day_name][(m.group(1), m.group(2))] += 1
                    if cell.upper().startswith("EPISODE") or cell.upper().startswith("EP"):
                        clean_ep = re.sub(r'^(?:EPISODE|EP)\s*', 'EP ', cell, flags=re.IGNORECASE).strip()
                        if day_name in ["SAT", "SUN"]:
                            weekend_episodes[day_name] = clean_ep
                        elif "DAILY LABOUR" in pre_pass_section.upper() or "DAILY LABOR" in pre_pass_section.upper():
                            daily_labour_episodes[day_name] = clean_ep
                        else:
                            main_day_episodes[day_name] = clean_ep

    # Carry forward episode codes for M-F so they don't have to be typed 5 times
    def fill_episodes(ep_dict):
        default_ep = ""
        days = ["MON", "TUE", "WED", "THU", "FRI"]
        for day in days:
            if ep_dict.get(day):
                default_ep = ep_dict[day]
                break
        if not default_ep: return
        current_ep = default_ep
        for day in days:
            if ep_dict.get(day):
                current_ep = ep_dict[day]
            else:
                ep_dict[day] = current_ep
                
    fill_episodes(main_day_episodes)
    fill_episodes(daily_labour_episodes)

    day_default_times = {}
    for day_name, counter in day_times_counter.items():
        if counter:
            most_common = counter.most_common(1)[0][0]
            day_default_times[day_name] = most_common
        else:
            day_default_times[day_name] = ("0700", "2000")

    try:
        with open(template_path, 'rb') as f_tpl:
            template_bytes = f_tpl.read()
    except Exception as e:
        print(f"Error reading template PDF: {e}")
        return
        
    day_y_bounds = {}
    try:
        with fitz.open(template_path) as t_doc:
            t_page = t_doc[0]
            for w in t_page.widgets():
                for day in ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']:
                    if w.field_name == f'DATE{day}':
                        day_y_bounds[day] = (w.rect.y0, w.rect.y1)
    except Exception as e:
        print(f"Warning mapping day Y bounds: {e}")
        
    current_section = ""
    for row in all_rows:
        if not row or not row[0]:
            continue
        
        # Category headers like "OFFICE", "Show Call Dressers" have no title, phone, or email
        name = row[0]
        title = row[1] if len(row) > 1 else ""
        phone = row[2] if len(row) > 2 else ""
        email = row[3] if len(row) > 3 else ""
        
        if (not title or title.strip() == "") and (not phone or phone.strip() == "") and (not email or email.strip() == ""):
            current_section = name.strip()
            continue
            
        if name == "TOTAL TIMESHEETS:":
            continue
            
        # Check if episode info (e.g. ep 202) should be included for this person
        name_upper = name.strip().upper()
        sec_upper = (current_section or "").strip().upper()
        base_include_ep = False
        if "ZOE LANE" in name_upper:
            base_include_ep = False
        elif "RAVI KHAN" in name_upper or "GRAHAM POOLE" in name_upper:
            base_include_ep = True
        elif "WEEKLY LABOUR" in sec_upper or "WEEKLY LABOR" in sec_upper:
            base_include_ep = True
        elif "DAILY LABOUR" in sec_upper or "DAILY LABOR" in sec_upper:
            base_include_ep = True
            
        # Check if they worked any days between MON (7) and SUN (13)
        worked_any_days = False
        for col_idx in range(7, 14):
            if col_idx < len(row):
                val = row[col_idx].strip().upper()
                if val and val != "OFF" and val != "OFF DAY":
                    worked_any_days = True
                    break
                
        if not worked_any_days:
            continue
            
        phone = row[2]
        email = row[3]
        other_rates = row[4]
        lunch = row[5]
        
        deduct_lunch = (lunch.strip().upper() != "LUNCH ON CHEQUE")
        
        doc = fitz.open(stream=bytes(template_bytes), filetype="pdf")
        page = doc[0]
        
        # Map basic fields
        cleaned_name = re.sub(r'[\.\,]', ' ', name)
        initials = "".join([part[0] for part in re.split(r'[\s\-]+', cleaned_name) if part]).upper()
        field_values = {
            "PROD TITLE": "SAMPLE SHOW S1",
            "PROD COMPANY": "Sample Productions Inc.",
            "WEEK ENDING": week_ending,
            "DEPARTMENT": "SET DEC",
            "OCCUPATION": title,
            "NAME": name.upper(),
            "OTHER RATES": other_rates,
            "DEPT": "GL",
            "CREW": initials,
            "UNION": "IATSE873",
            "Union Mbr": "member",
            "Resid": "YES"
        }
        
        # Populate ALL dates (MON to SUN) regardless of shift
        for day_name in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]:
            field_values[f"DATE{day_name}"] = week_dates[day_name]

        total_weekly_hours = 0
        days_worked_count = 0
        actual_days_worked_count = 0
        lunch_l_count = 0
        regular_days_count = 0
        lead_days_count = 0
        actual_lead_days_count = 0
        travel_notes = {}
        
        for day_name, col_idx in days_columns:
            if col_idx < len(row):
                shift = row[col_idx].strip()
                if shift:
                    if shift.upper() in ["OFF", "OFF DAY"]:
                        continue
                        
                    is_lead = ("LEAD" in shift.upper())
                    day_include_ep = base_include_ep or day_name in ["SAT", "SUN"] or is_lead
                    
                    if day_include_ep and not any(k in shift.upper() for k in ["HOLIDAY", "SICK"]):
                        if day_name in ["SAT", "SUN"]:
                            ep_dict = weekend_episodes
                        else:
                            ep_dict = daily_labour_episodes if ("DAILY LABOUR" in sec_upper or "DAILY LABOR" in sec_upper) else main_day_episodes
                            
                        ep_val = ep_dict.get(day_name, "")
                        
                        if is_lead:
                            lead_ep_match = re.search(r'LEAD\s*-\s*(?:EP\s*)?([A-Z0-9]+)', shift, re.IGNORECASE)
                            if lead_ep_match:
                                ep_val = "EP " + lead_ep_match.group(1)
                                
                        if ep_val:
                            field_values[f"TRAVEL START{day_name}"] = ep_val
                        
                    if "HOLIDAY" in shift.upper() or "SICK" in shift.upper():
                        display_text = "SICK" if "SICK" in shift.upper() else "HOLIDAY"
                        field_values[f"CALL TIME{day_name}"] = display_text
                        field_values[f"WRAP TIME{day_name}"] = display_text
                        field_values[f"WORK HOURS{day_name}"] = "8"
                        total_weekly_hours += 8
                        days_worked_count += 1
                        continue
                        
                    if is_lead:
                        lead_days_count += 1
                        field_values[f"TRAVEL END{day_name}"] = "LEAD"
                    else:
                        regular_days_count += 1
                        
                    # Extract the times like 0700-2000 or 0700 - 1800
                    match = re.search(r"(\d{4})\s*-\s*(\d{4})", shift)
                    if match:
                        start = match.group(1)
                        end = match.group(2)
                    else:
                        # Infer standard shift hours for this specific day from other crew members
                        def_start, def_end = day_default_times.get(day_name, ("0700", "2000"))
                        start = def_start
                        end = def_end
                        
                    days_worked_count += 1
                    actual_days_worked_count += 1
                    if is_lead:
                        actual_lead_days_count += 1
                    if "L" in shift.upper():
                        lunch_l_count += 1
                        
                    hours = calculate_hours(start, end, deduct_lunch=True) # Always deduct lunch
                    total_weekly_hours += hours
                    
                    field_values[f"CALL TIME{day_name}"] = start
                    field_values[f"WRAP TIME{day_name}"] = end
                    # Remove ".0" from work hours if it's an integer
                    field_values[f"WORK HOURS{day_name}"] = str(int(hours)) if float(hours).is_integer() else str(hours)
                    
                    meal_start, meal_end = format_time_for_meal(start)
                    field_values[f"START{day_name}"] = meal_start
                    field_values[f"END{day_name}"] = meal_end
                    
                    if "(T)" in shift.upper() or re.search(r'\(T\)', shift, re.IGNORECASE):
                        hrs_str = str(int(hours)) if float(hours).is_integer() else str(hours)
                        travel_notes[day_name] = f"{hrs_str} HRS INCLUDES TRAVEL TIME"

        # Format OCCUPATION if there are LEAD days worked
        if lead_days_count > 0 and not ("LEAD" in title.upper()):
            if regular_days_count > 0:
                field_values["OCCUPATION"] = f"{title} X {regular_days_count} , LEAD X {lead_days_count}"
            else:
                field_values["OCCUPATION"] = f"LEAD X {lead_days_count}"

        # Format OTHER RATES with X [actual_days_worked_count]
        # Extras (Computer, Car, Lunch, Kit, Cell, etc.) are paid ONLY for days actually worked, NOT holidays.
        final_other_rates = []
        has_car = False
        has_kit = False
        
        if other_rates.strip():
            items = [item.strip() for item in other_rates.split('+')]
            for item in items:
                if item:
                    if "CAR" in item.upper(): has_car = True
                    if "KIT" in item.upper(): has_kit = True
                    # Avoid adding X 5 if they manually put it in the spreadsheet
                    if re.search(r'X\s*\d+', item, re.IGNORECASE):
                        final_other_rates.append(item)
                    else:
                        if actual_days_worked_count > 0:
                            final_other_rates.append(f"{item} X {actual_days_worked_count}")
                            
        if actual_lead_days_count > 0:
            if not has_car:
                final_other_rates.append(f"CAR X {actual_lead_days_count}")
            if not has_kit:
                final_other_rates.append(f"KIT X {actual_lead_days_count}")
                        
        if actual_days_worked_count > 0:
            final_other_rates.append(f"LUNCH X {actual_days_worked_count}")
            
        field_values["OTHER RATES"] = " + ".join(final_other_rates)

        field_values["WORK HOURSTOTAL WORK HOURS"] = str(int(total_weekly_hours)) if float(total_weekly_hours).is_integer() else str(total_weekly_hours)
        
        for widget in list(page.widgets()):
            if widget.field_name in field_values:
                if widget.field_name == "Union Mbr":
                    if widget.on_state() == "member":
                        widget.field_value = True
                    else:
                        widget.field_value = False
                elif widget.field_name == "Resid":
                    if widget.on_state() == "YES":
                        widget.field_value = True
                    else:
                        widget.field_value = False
                else:
                    widget.field_value = field_values[widget.field_name]
                widget.update()
        
        # Insert travel notes for any days with (T)
        for day_name, note_text in travel_notes.items():
            if day_name in day_y_bounds:
                y0, y1 = day_y_bounds[day_name]
                rect = fitz.Rect(545, y0 + 1, 755, y1 - 1)
                page.insert_textbox(
                    rect,
                    note_text,
                    fontsize=9,
                    fontname="helv",
                    color=(0.15, 0.35, 0.7),
                    align=fitz.TEXT_ALIGN_LEFT
                )
        
        output_filename = f"{generated_count + 1:02d} - {name.upper()} {date_code}.pdf"
        output_path = os.path.join(output_dir, output_filename)
        doc.save(output_path) # This inherently overwrites existing files in PyMuPDF
        doc.close()
        print(f"Generated {output_filename}")
        generated_count += 1
            
    print(f"\nSuccessfully generated {generated_count} timesheets in {output_dir}")
    
    # Custom Review & Print Dialog
    def open_print_dialog():
        print_window = tk.Toplevel()
        print_window.title("Review & Print Timesheets")
        print_window.geometry("560x620")
        
        tk.Label(print_window, text="Review & Select Timesheets:", font=("Arial", 12, "bold")).pack(pady=(10, 2))
        tk.Label(print_window, text="Click '👁 Review' to view individual PDFs or 'Review All (Merged)' to view all pages.", font=("Arial", 9, "italic"), fg="#555").pack(pady=(0, 10))
        
        list_frame = tk.Frame(print_window)
        list_frame.pack(fill="both", expand=True, padx=15, pady=5)
        
        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        
        canvas = tk.Canvas(list_frame, yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        
        scrollbar.config(command=canvas.yview)
        
        scrollable_frame = tk.Frame(canvas)
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        pdfs_to_print = sorted([f for f in os.listdir(output_dir) if f.endswith(".pdf") and not f.startswith("!")])
        vars_dict = {}
        
        for pdf in pdfs_to_print:
            row_frame = tk.Frame(scrollable_frame)
            row_frame.pack(fill="x", expand=True, padx=5, pady=2)
            
            var = tk.BooleanVar(value=True) # Default all to checked
            vars_dict[pdf] = var
            
            chk = tk.Checkbutton(row_frame, text=pdf, variable=var, font=("Arial", 9))
            chk.pack(side=tk.LEFT, anchor='w')
            
            def make_preview_cmd(file_name):
                return lambda: os.startfile(os.path.join(output_dir, file_name))
                
            rev_btn = tk.Button(row_frame, text="👁 Review", command=make_preview_cmd(pdf), font=("Arial", 8, "bold"), bg="#0288D1", fg="white", padx=6, pady=1)
            rev_btn.pack(side=tk.RIGHT, padx=5)
            
        def select_all():
            for var in vars_dict.values():
                var.set(True)
                
        def deselect_all():
            for var in vars_dict.values():
                var.set(False)
                
        def build_merged_pdf(selected_files):
            merged_doc = fitz.open()
            for pdf_file in selected_files:
                pdf_path = os.path.join(output_dir, pdf_file)
                with fitz.open(pdf_path) as doc:
                    doc.bake()
                    merged_doc.insert_pdf(doc)
            
            merged_path = os.path.join(output_dir, "!PRINT_ALL.pdf")
            merged_doc.save(merged_path)
            merged_doc.close()
            return merged_path

        def do_review_all():
            selected = [pdf for pdf, var in vars_dict.items() if var.get()]
            if not selected:
                messagebox.showinfo("Notice", "No timesheets selected for review.")
                return
            try:
                merged_path = build_merged_pdf(selected)
                os.startfile(merged_path)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open merged PDF for review: {e}")

        def do_print():
            selected = [pdf for pdf, var in vars_dict.items() if var.get()]
            print_window.destroy()
            
            if not selected:
                messagebox.showinfo("Success", f"Timesheets saved to:\n{output_dir}")
                return
                
            try:
                merged_path = build_merged_pdf(selected)
                messagebox.showinfo("Ready to Print", f"Created a single merged file of {len(selected)} timesheets!\n\nSaved as !PRINT_ALL.pdf in:\n{output_dir}\n\nYou can now print this file on any printer.")
                os.startfile(output_dir)
            except Exception as e:
                print(f"Failed to create print file: {e}")
                messagebox.showerror("Error", f"Failed to create print file: {e}")

        def open_folder():
            os.startfile(output_dir)

        def cancel():
            print_window.destroy()
            messagebox.showinfo("Success", f"Timesheets saved to:\n{output_dir}")

        btn_frame = tk.Frame(print_window)
        btn_frame.pack(pady=5)
        
        tk.Button(btn_frame, text="Select All", command=select_all, width=11).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="Deselect All", command=deselect_all, width=11).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="📁 Open Folder", command=open_folder, width=13).grid(row=0, column=2, padx=5)
        
        action_frame = tk.Frame(print_window)
        action_frame.pack(pady=10)
        
        tk.Button(action_frame, text="👁 Review All (Merged)", command=do_review_all, font=("Arial", 10, "bold"), bg="#0288D1", fg="white", padx=8).pack(side=tk.LEFT, padx=6)
        tk.Button(action_frame, text="🖨 Create Print File", command=do_print, font=("Arial", 10, "bold"), bg="#4CAF50", fg="white", padx=8).pack(side=tk.LEFT, padx=6)
        tk.Button(action_frame, text="Close", command=cancel, font=("Arial", 10), padx=8).pack(side=tk.LEFT, padx=6)
        
        print_window.grab_set()
        print_window.wait_window()
        
    open_print_dialog()

if __name__ == "__main__":
    generate_timesheets()
