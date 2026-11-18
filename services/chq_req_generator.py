import os
import fitz
from datetime import datetime

app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
TEMPLATE_PATH = os.path.join(show_dir, "CH REQS", "00 Cheque Requisiton Form.pdf")

def generate_chq_req_pdf(buyer_name, total_amount, output_dir, env_num):
    """
    Fills out the Cheque Requisition PDF for the given buyer and saves it in output_dir.
    """
    if not os.path.exists(TEMPLATE_PATH):
        print(f"Error: CH REQ template not found at {TEMPLATE_PATH}")
        return None

    try:
        doc = fitz.open(TEMPLATE_PATH)
        page = doc[0]
        
        today_str = datetime.today().strftime("%Y-%m-%d")
        
        field_map = {
            "Payee 1": buyer_name,
            "Date1_af_date": today_str,
            "Text5": f"{total_amount:.2f}",
            "Details 1": f"Petty Cash Reimbursement - Envelope #{env_num}",
            "Requested By": buyer_name,
            "Department": "SET DEC"
        }
        
        for widget in page.widgets():
            if widget.field_name in field_map:
                widget.field_value = str(field_map[widget.field_name])
            elif widget.field_name == "Check Box10": # Total Amount CAD?
                widget.field_value = True
            elif widget.field_name == "Pickup":
                widget.field_value = True
            widget.update()
            
        output_filename = f"CH_REQ_{buyer_name.replace(' ', '_')}_ENV_{env_num}.pdf"
        output_path = os.path.join(output_dir, output_filename)
        
        doc.save(output_path)
        doc.close()
        
        print(f"Successfully generated Cheque Requisition: {output_path}")
        return output_path
        
    except Exception as e:
        print(f"Error generating CH REQ: {e}")
        return None
