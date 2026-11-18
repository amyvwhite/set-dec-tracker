import sys
import json
import os
from datetime import datetime

# Setup paths and imports
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.append(app_dir)
from services.sheets import get_client
from core.settings import load_settings

# ReportLab imports
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

def generate_report(selected_episodes=None):
    print("Connecting to Google Sheets...")
    url = load_settings().get('spreadsheet_url', '')
    
    client = get_client()
    sheet = client.open_by_url(url)
    ws = sheet.worksheet('TRACKER TOPSHEET')
    
    print("Fetching data...")
    data = ws.get_all_values()
    
    alerts = []
    current_episode = "Unknown"
    
    for row in data:
        # Track the episode header
        if len(row) >= 4 and row[0].strip() != "" and row[1].strip() == "SET":
            raw_ep = row[3].strip()  # "EPISODE 201", "STANDING SETS", etc.
            if "STANDING" in raw_ep.upper() or "AMORT" in row[0].upper():
                current_episode = "AMORT"
            elif "EPISODE" in raw_ep.upper() or "EP " in raw_ep.upper():
                current_episode = raw_ep.upper().replace("EPISODE", "").replace("EP", "").strip()
            else:
                current_episode = raw_ep
            continue
            
        if selected_episodes is not None and current_episode not in selected_episodes:
            continue
            
        if len(row) < 10:
            continue
            
        set_code = row[2].strip()
        set_desc = row[3].strip()
        cost = row[4].strip()
        budget = row[5].strip()
        pct_str = row[9].strip()
        
        overage_approved = row[13].strip().upper() if len(row) > 13 else ""
        
        # Skip headers or empty rows
        if not set_code or set_code in ['TOTAL', 'SET CODE', 'SET']:
            continue
            
        # Skip if boss already approved
        if overage_approved == "Y":
            continue
            
        # Parse percentage
        try:
            if '%' in pct_str:
                pct = float(pct_str.replace('%', '').strip())
            elif pct_str:
                pct = float(pct_str) * 100
            else:
                continue
                
            if pct > 90.0:
                try:
                    b_val = float(budget.replace('$', '').replace(',', '').strip()) if budget else 0.0
                    c_val = float(cost.replace('$', '').replace(',', '').strip()) if cost else 0.0
                    left_val = b_val - c_val
                except ValueError:
                    left_val = 0.0
                    
                alerts.append([current_episode, set_code, set_desc, budget, cost, f"${left_val:,.2f}", f"{pct:.1f}%"])
        except ValueError:
            continue
            
    # Generate PDF
    show_alerts_dir = os.path.abspath(os.path.join(app_dir, '..', '..', 'BUDGET ALERTS'))
    alerts_dir = show_alerts_dir if os.path.exists(os.path.dirname(show_alerts_dir)) else os.path.join(app_dir, 'BUDGET ALERTS')
    if not os.path.exists(alerts_dir):
        os.makedirs(alerts_dir)
        
    timestamp = datetime.now().strftime('%H%M%S')
    pdf_path = os.path.join(alerts_dir, f"Budget_Alert_{datetime.now().strftime('%Y-%m-%d')}_{timestamp}.pdf")
    
    print(f"Generating PDF at {pdf_path}...")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title = Paragraph("<b>Budget Alert: Sets Over 90% Spent</b>", styles['Title'])
    subtitle = Paragraph(f"{datetime.now().strftime('%B %d, %Y')}", styles['Normal'])
    
    elements.append(title)
    elements.append(subtitle)
    elements.append(Spacer(1, 20))
    
    # Table data
    table_data = [['Episode', 'Set Code', 'Description', 'Budget', 'Cost to Date', '$ Left', '% Spent']]
    for a in alerts:
        ep, code, desc, bgt, cst, left, pct = a
        # Wrap description in a Paragraph to allow text wrapping
        desc_p = Paragraph(desc, styles['Normal'])
        table_data.append([ep, code, desc_p, bgt, cst, left, pct])
    
    t = Table(table_data, colWidths=[60, 50, 160, 65, 65, 60, 50])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkred),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (2,1), (2,-1), 'LEFT'),  # Description left aligned
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
    ]))
    
    elements.append(t)
    doc.build(elements)
    
    print("Done!")
    return pdf_path
    
    # Also save a JSON for preview
    with open('alert_preview.json', 'w') as f:
        json.dump(alerts, f)

if __name__ == '__main__':
    generate_report()
