import frappe
import json
import os
import time
from frappe.utils import today, getdate, add_days, add_months, formatdate
from frappe.integrations.utils import make_get_request, make_post_request
from frappe.utils.file_manager import save_file
from erevive_whatsapp.api.whatsapp import create_folder
from erpnext.accounts.doctype.process_statement_of_accounts.process_statement_of_accounts import get_report_pdf

from romapuf_custom.utils.statement_helper import (
    get_customers,
    get_sales_person_email_mobile,
    fetch_customer_emails,
    generate_reports
)


def send_statements(document_name):
    doc = frappe.get_doc("Process Statement Of Accounts", document_name)
    customers = get_customers()

    doc.set("customers", [])

    for customer in customers:
        emails = fetch_customer_emails(customer, primary_mandatory=0)

        billing_email = ""
        if isinstance(emails, list):
            billing_email = emails[1] if len(emails) > 1 else emails[0]
        else:
            billing_email = emails

        row = doc.append("customers", {})
        row.customer = customer
        row.billing_email = billing_email


    today_date = getdate(today())
    wa_template = ""
    doc_name = ""
    doc.orientation = "Portrait"
    start_month = formatdate(doc.from_date, "MMMM")
    end_month = formatdate(doc.to_date, "MMMM")

    if doc.report == "General Ledger":
        first_day_current_month = today_date
        doc.from_date = add_months(first_day_current_month, -3)
        doc.to_date = add_days(first_day_current_month, -1)
        wa_template = "whatsapp_accounts_ledger"
        doc_name = "General Ledger"

    elif doc.report == "Accounts Receivable":
        doc.posting_date = today()
        wa_template = "whatsapp_accounts_receivables"
        doc_name = "Accounts Receivable"
        doc.orientation = "Landscape"

    doc.save(ignore_permissions=True)

    reports = generate_reports(doc)

    if not reports:
        frappe.log_error("No reports generated", "send_statements")
        return



    m_report = get_report_pdf(doc, consolidated=False)        

    for customer, data in reports.items():
        try:
            customer_doc = frappe.get_doc("Customer", customer)

            sales_info = get_sales_person_email_mobile(customer)

            sales_emails = sales_info.get("emails", [])
            sales_mobiles = sales_info.get("mobiles", [])

            contact_list = frappe.db.sql("""
                SELECT con.phone
                FROM `tabContact` AS con
                INNER JOIN `tabDynamic Link` AS dl ON dl.parent = con.name
                WHERE dl.link_name = %s
            """, customer, as_dict=True)

            contact_numbers = [c["phone"] for c in contact_list if c.get("phone")]

            contact_numbers.extend(sales_mobiles)

            contact_numbers = list(set(filter(None, contact_numbers)))

            context = {"customer": customer_doc, "doc": doc}
            subject = frappe.render_template(doc.subject, context)
            message = frappe.render_template(doc.body, context)

            if customer not in m_report:
                frappe.log_error(f"No report found for customer {customer}", "send_wa")
                return

            pdf_data = m_report[customer]

            filename = f"{frappe.generate_hash()[:10]}_{customer}.pdf"
            folder = create_folder("Whatsapp", "Home")

            saved_file = save_file(
                fname=filename,
                content=pdf_data,
                dt="Process Statement Of Accounts",
                dn=document_name,
                folder=folder,
                is_private=0,
                decode=False
            )

            if not saved_file or not saved_file.file_name:
                frappe.log_error("File not saved properly", "send_wa")
                return

            file_url = f"{frappe.utils.get_url()}/files/{saved_file.file_name}"
        
            attachment = {
                "fname": f"{customer}.pdf",
                "fcontent": pdf_data
            }

            emails = fetch_customer_emails(customer, primary_mandatory=0)
            recipients = [e for e in emails if e]

            contact_emails = list(set(sales_emails)) if sales_emails else []

            if not recipients:
                frappe.logger().info(f"No email for customer {customer}")
            else:
                # pass
                frappe.enqueue(
                    method=frappe.sendmail,
                    queue="short",
                    recipients=recipients,
                    cc=contact_emails,
                    subject=subject,
                    message=message,
                    attachments=[attachment],
                    expose_recipients="header",
                )

            # WhatsApp enqueue (only if we have numbers)
            if contact_numbers:
                frappe.enqueue(
                    method="romapuf_custom.services.statement_mailer.send_wa",
                    queue="short",
                    customer=customer,
                    contact=contact_numbers,
                    wa_template=wa_template,
                    posting_date=today_date,
                    total_outstanding=data.get("totals", {}).get("outstanding", 0),
                    total_overdue=data.get("totals", {}).get("overdue", 0),
                    docname=document_name,
                    doc_name=doc_name,
                    start_month=start_month,
                    end_month=end_month,
                    closing_balance=data.get("totals", {}).get("closing_balance", 0),
                    file_url=file_url
                )
            else:
                frappe.log_error(title="Whatsapp Error", message=f"Phone not found for customer: {customer}")
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Error processing customer {customer}"
            )

def send_wa(customer, contact, wa_template, posting_date, doc_name, start_month, end_month, total_outstanding = 0, total_overdue = 0, closing_balance = 0, docname=None, file_url=None):
    try:
        # doc = frappe.get_doc("Process Statement Of Accounts", docname)

        # report = get_report_pdf(doc, consolidated=False)

        # if not report:
        #     frappe.log_error("No PDF generated", "send_wa")
        #     return

        # if customer not in report:
        #     frappe.log_error(f"No report found for customer {customer}", "send_wa")
        #     return

        # pdf_data = report[customer]

        settings = frappe.get_single("ETPL Whatsapp Settings")
        base_url = f"{settings.url}/{settings.version}/{settings.phone_number_id}/messages"

        headers = {
            "Authorization": f"Bearer {settings.token}",
            "Content-Type": "application/json"
        }

        # filename = f"{frappe.generate_hash()[:10]}_{customer}.pdf"
        # folder = create_folder("Whatsapp", "Home")

        # saved_file = save_file(
        #     fname=filename,
        #     content=pdf_data,
        #     dt="Process Statement Of Accounts",
        #     dn=docname,
        #     folder=folder,
        #     is_private=0,
        #     decode=False
        # )

        # if not saved_file or not saved_file.file_name:
        #     frappe.log_error("File not saved properly", "send_wa")
        #     return


        if doc_name == "Accounts Receivable":
            body_parameters = [
                {"type": "text", "text": customer},
                {"type": "text", "text": str(total_outstanding)},
                {"type": "text", "text": str(total_overdue)}
            ]
        elif doc_name == "General Ledger":
            body_parameters = [
                {"type": "text", "text": customer},
                {"type": "text", "text": f"{start_month} - {end_month}"},
                {"type": "text", "text": closing_balance}
            ]
        else:
            body_parameters = []

        # file_url = f"{frappe.utils.get_url()}/files/{saved_file.file_name}"

        for number in contact:
            payload = {
                "messaging_product": "whatsapp",
                "to": number,
                "type": "template",
                "template": {
                    "name": wa_template,
                    "language": {"code": "en"},
                    "components": [
                        {
                            "type": "header",
                            "parameters": [{
                                "type": "document",
                                "document": {
                                    "link": file_url,
                                    "filename": doc_name
                                }
                            }]
                        },
                        {
                            "type": "body",
                            "parameters": body_parameters
                        }
                    ]
                }
            }

            try:
                response = make_post_request(
                    base_url,
                    headers=headers,
                    data=json.dumps(payload)
                )

                response_text = json.dumps(response, default=str)

                if len(response_text) > 10000:
                    response_text = response_text[:10000] + "...truncated"

                frappe.get_doc({
                    "doctype": "Romapuf Whatsapp Log",
                    "posting_date": posting_date,
                    "customer": customer,
                    "mobile": number,
                    "template": wa_template,
                    "request": json.dumps(payload),
                    "response": response_text
                }).insert(ignore_permissions=True)

            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"WhatsApp failed for {customer} -> {number}"
                )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "send_wa fatal error")