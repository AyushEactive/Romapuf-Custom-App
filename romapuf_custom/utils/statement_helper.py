import frappe
from frappe.utils.pdf import get_pdf


def get_customers():
    try:
        return frappe.get_all(
            "Customer",
            filters={
                "disabled": 0,
                "custom_allow_notification": 1
            },
            pluck="name"
        ) or []
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Error fetching customers")
        return []


def get_sales_person_email_mobile(customer):
    try:
        sales_persons = frappe.db.get_all(
            "Sales Team",
            {"parent": customer},
            pluck="sales_person"
        )

        if not sales_persons:
            return {"emails": [], "mobiles": []}

        emp_ids = frappe.db.get_all(
            "Sales Person",
            {"name": ["in", sales_persons]},
            pluck="employee"
        )

        if not emp_ids:
            return {"emails": [], "mobiles": []}

        employee_details = frappe.db.get_all(
            "Employee",
            {"name": ["in", emp_ids]},
            ["company_email", "cell_number"]
        )

        emails = list({
            row["company_email"]
            for row in employee_details
            if row.get("company_email")
        })

        mobiles = list({
            row["cell_number"]
            for row in employee_details
            if row.get("cell_number")
        })

        return {"emails": emails, "mobiles": mobiles}

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Error fetching sales person details for customer {customer}"
        )
        return {"emails": [], "mobiles": []}


def fetch_customer_emails(customer, primary_mandatory=0):
    try:
        from erpnext.accounts.doctype.process_statement_of_accounts.process_statement_of_accounts import (
            get_customer_emails
        )

        return get_customer_emails(customer, primary_mandatory) or []

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Error fetching emails for customer {customer}"
        )
        return []


def generate_reports(doc):
    reports = {}

    try:
        from erpnext.accounts.doctype.process_statement_of_accounts.process_statement_of_accounts import (
            get_statement_dict
        )

        statement_dict_raw = get_statement_dict(doc, get_statement_dict=True)

        if not statement_dict_raw:
            frappe.logger().info("No statement data found")
            return {}

        process_soa_html = frappe.get_hooks("process_soa_html") or {}

        template_path = process_soa_html.get(doc.report, [None])[-1]

        if not template_path:
            frappe.log_error(
                f"No template found for report: {doc.report}",
                "SOA Template Missing"
            )
            return {}

        for customer, res_ageing in statement_dict_raw.items():
            try:
                res, ageing = res_ageing

                total_outstanding = sum(
                    r.get("outstanding_in_account_currency", 0) for r in res
                )
                total_overdue = sum(
                    r.get("total_due", 0) for r in res
                )

                filters = {"customer_name": customer, "report_date": doc.posting_date}

                if doc.report == "General Ledger":
                    filters = {"customre_name": customer, "from_date": doc.from_date, "to_date": doc.to_date}

                html = frappe.render_template(
                    template_path,
                    {
                        "data": res,
                        "ageing": ageing,
                        "filters": filters,
                        "report": {"report_name": doc.report},
                    }
                )

                pdf_bytes = get_pdf(
                    html,
                    {"orientation": getattr(doc, "orientation", "Portrait")}
                )

                reports[customer] = {
                    "pdf": pdf_bytes,
                    "totals": {
                        "outstanding": total_outstanding,
                        "overdue": total_overdue,
                        "closing_balance": res[-1].get("balance", 0) if res else 0
                    }
                }

            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Failed generating report for customer {customer}"
                )
                continue

        return reports

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Error in generate_reports"
        )
        return {}