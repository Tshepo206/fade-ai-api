from datetime import datetime, timedelta

from ledger_manager import LedgerManager
from booking_manager import BookingManager


class DashboardAnalyticsManager:
    @staticmethod
    def _period_start(period: str):
        now = datetime.utcnow()
        if period == "today": return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "week": return now - timedelta(days=7)
        if period == "month": return now - timedelta(days=30)
        return None

    @staticmethod
    def _transactions(business_id: str, period: str):
        start = DashboardAnalyticsManager._period_start(period) or DashboardAnalyticsManager._period_start("today")
        return LedgerManager.get_transactions_for_range(business_id, start, datetime.utcnow(), 2000)

    @staticmethod
    def get_dashboard_summary(business_id: str, period: str = "today") -> dict:
        transactions = DashboardAnalyticsManager._transactions(business_id, period)
        revenue = sum(float(row.get("credit_amount") or 0) for row in transactions)
        expenses = sum(float(row.get("debit_amount") or 0) for row in transactions)
        cash = sum(float(row.get("credit_amount") or 0) for row in transactions if (row.get("payment_method") or "").strip().title() == "Cash")
        card = sum(float(row.get("credit_amount") or 0) for row in transactions if (row.get("payment_method") or "").strip().title() == "Card")
        return {"success": True, "period": period, "revenue": revenue, "expenses": expenses,
                "profit": revenue-expenses, "cash": cash, "card": card, "transactions": len(transactions)}

    @staticmethod
    def get_revenue_trends(business_id: str, period: str = "week") -> list:
        days = 30 if period == "month" else 7
        now = datetime.utcnow(); start = now - timedelta(days=days)
        trends = {(start + timedelta(days=i + 1)).strftime("%Y-%m-%d"):
                  {"date": (start + timedelta(days=i + 1)).strftime("%Y-%m-%d"), "revenue": 0, "expenses": 0, "profit": 0}
                  for i in range(days)}
        for row in LedgerManager.get_transactions_for_range(business_id, start, now, 2000):
            key = datetime.fromisoformat(row["transaction_timestamp"].replace("Z", "+00:00")).strftime("%Y-%m-%d")
            if key in trends:
                credit, debit = float(row.get("credit_amount") or 0), float(row.get("debit_amount") or 0)
                trends[key]["revenue"] += credit; trends[key]["expenses"] += debit; trends[key]["profit"] += credit-debit
        return list(trends.values())

    @staticmethod
    def get_revenue_by_service(business_id: str, period: str = "month") -> list:
        totals = {}
        for row in DashboardAnalyticsManager._transactions(business_id, period):
            credit = float(row.get("credit_amount") or 0)
            if credit > 0:
                name = row.get("service_name") or "Uncategorised service"
                totals.setdefault(name, {"service_name": name, "revenue": 0, "transactions": 0})
                totals[name]["revenue"] += credit; totals[name]["transactions"] += 1
        return sorted(totals.values(), key=lambda item: item["revenue"], reverse=True)

    @staticmethod
    def get_top_customers(business_id: str, period: str = "month", limit: int = 10) -> list:
        totals = {}
        for row in DashboardAnalyticsManager._transactions(business_id, period):
            credit = float(row.get("credit_amount") or 0)
            if credit > 0:
                name = row.get("customer_name") or "Unknown customer"
                totals.setdefault(name, {"customer_name": name, "revenue": 0, "visits": 0})
                totals[name]["revenue"] += credit; totals[name]["visits"] += 1
        return sorted(totals.values(), key=lambda item: item["revenue"], reverse=True)[:limit]

    @staticmethod
    def get_ai_recommendations(business_id: str, period: str = "today") -> list:
        summary = DashboardAnalyticsManager.get_dashboard_summary(business_id, period)
        bookings = BookingManager.get_upcoming_bookings(business_id, 20)
        services = DashboardAnalyticsManager.get_revenue_by_service(business_id, period)
        customers = DashboardAnalyticsManager.get_top_customers(business_id, period, 3)
        revenue, cash, card = summary["revenue"], summary["cash"], summary["card"]
        result = [{"type": "revenue", "title": "Revenue is active" if revenue else "No revenue recorded yet",
                   "message": f"Revenue for this period is R{revenue:.0f} across {summary['transactions']} recorded transactions." if revenue else "No sales have been recorded for this period. Voice bookkeeping entries will update this automatically."},
                  {"type": "bookings", "title": "Upcoming appointments" if bookings else "No upcoming appointments",
                   "message": f"There are {len(bookings)} upcoming appointments on the dashboard." if bookings else "There are no upcoming appointments. This may be a good time to send WhatsApp reminders or promotions."}]
        if cash != card:
            leader, amount, other = ("Cash", cash, card) if cash > card else ("Card", card, cash)
            result.append({"type": "payments", "title": f"{leader} payments are leading", "message": f"{leader} payments are R{amount:.0f}, higher than {('card' if leader == 'Cash' else 'cash')} payments of R{other:.0f}."})
        if services: result.append({"type": "service", "title": "Top service", "message": f"{services[0]['service_name']} is currently the highest earning service at R{services[0]['revenue']:.0f}."})
        if customers: result.append({"type": "customer", "title": "Top customer", "message": f"{customers[0]['customer_name']} is currently the top customer with R{customers[0]['revenue']:.0f} revenue."})
        return result

    @staticmethod
    def get_monthly_report(business_id: str) -> dict:
        return {"month": datetime.utcnow().strftime("%B %Y"),
                "summary": DashboardAnalyticsManager.get_dashboard_summary(business_id, "month"),
                "revenue_by_service": DashboardAnalyticsManager.get_revenue_by_service(business_id, "month"),
                "top_customers": DashboardAnalyticsManager.get_top_customers(business_id, "month", 5),
                "trends": DashboardAnalyticsManager.get_revenue_trends(business_id, "month"),
                "status": "Report data ready. PDF export will be added next."}

    @staticmethod
    def get_bank_reconciliation(business_id: str, period: str = "today") -> dict:
        summary = DashboardAnalyticsManager.get_dashboard_summary(business_id, period)
        return {"expected_cash": summary["cash"], "expected_card": summary["card"], "expected_total": summary["revenue"],
                "bank_confirmed_card": 0, "cash_counted": 0, "unreconciled_amount": summary["revenue"],
                "status": "Pending reconciliation", "note": "Bank import and cash count matching will be added in the next version."}
