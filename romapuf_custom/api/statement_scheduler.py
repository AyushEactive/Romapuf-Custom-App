import frappe
from frappe.utils import today, getdate
from romapuf_custom.services.statement_mailer import send_statements


def run_statement_scheduler():

    today_date = getdate(today())

    is_monday = today_date.weekday() == 1
    is_first_day = today_date.day == 5

    if is_monday:
        send_statements("Weekly AR")

    if is_first_day:
        send_statements("Monthly GL")

