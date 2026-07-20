"""Contract tests for Phase 1 dashboard tenant isolation.

These tests use recording Supabase doubles: no credentials or live database are
required. They verify that all tenant table operations carry the server-supplied
business ID, including records with otherwise overlapping identifiers.
"""
import inspect
import unittest
from unittest.mock import patch

import availability_manager
import bank_reconciliation
import booking_manager
import customer_manager
import dashboard_analytics_manager
import ledger_manager
import reconciliation_manager
import report_manager
import service_manager
import dashboard_routes
import transaction_history


class Query:
    def __init__(self, data=None):
        self.data = data or []
        self.calls = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return method

    def execute(self):
        self.calls.append(("execute", (), {}))
        return type("Response", (), {"data": self.data})()


class Supabase:
    def __init__(self, data=None):
        self.data = data or []
        self.queries = []

    def table(self, name):
        query = Query(self.data)
        query.calls.append(("table", (name,), {}))
        self.queries.append(query)
        return query


def equalities(query):
    return [call[1] for call in query.calls if call[0] == "eq"]


class TenantIsolationTests(unittest.TestCase):
    business_a = "business-a"
    business_b = "business-b"

    def test_customers_and_services_scope_overlapping_names_and_phones(self):
        client_db, service_db = Supabase(), Supabase()
        with patch.object(customer_manager, "supabase", client_db), patch.object(service_manager, "supabase", service_db):
            customer_manager.CustomerManager.get_all_customers(self.business_a, "Same", 50)
            service_manager.ServiceManager.get_service_by_id(self.business_b, 7)
        self.assertIn(("business_id", self.business_a), equalities(client_db.queries[0]))
        self.assertIn(("business_id", self.business_b), equalities(service_db.queries[0]))

    def test_booking_writes_business_id_for_overlapping_appointment_time(self):
        db = Supabase([{"id": 11, "status": "PENDING"}])
        customer = {"success": True, "customer": {"phone_number": "27123456789"}}
        service = {"id": 1, "service_name": "Fade"}
        with patch.object(booking_manager, "supabase", db), \
             patch.object(booking_manager.CustomerManager, "create_or_update_customer", return_value=customer), \
             patch.object(booking_manager.ServiceManager, "get_service_by_id", return_value=service), \
             patch.object(booking_manager.AvailabilityManager, "is_slot_available", return_value=True), \
             patch.object(booking_manager.AvailabilityManager, "reserve_slot", return_value=True), \
             patch.object(booking_manager.BookingManager, "_enrich_bookings", return_value=[{"id": 11}]):
            result = booking_manager.BookingManager.create_manual_booking(
                self.business_a, "27123456789", "Same Name", 1, "2099-01-01T10:00:00")
        self.assertTrue(result["success"])
        insert = next(call for call in db.queries[2].calls if call[0] == "insert")
        self.assertEqual(insert[1][0]["business_id"], self.business_a)
        self.assertIn(("business_id", self.business_a), equalities(db.queries[1]))

    def test_availability_cross_tenant_update_cannot_target_other_business_slot(self):
        db = Supabase([])
        with patch.object(availability_manager, "supabase", db):
            changed = availability_manager.AvailabilityManager.unblock_slot(self.business_a, 99)
        self.assertFalse(changed)
        self.assertIn(("business_id", self.business_a), equalities(db.queries[0]))
        self.assertIn(("slot_id", 99), equalities(db.queries[0]))

    def test_ledger_and_summary_are_isolated(self):
        db = Supabase([])
        with patch.object(ledger_manager, "supabase", db):
            ledger_manager.LedgerManager.record_transaction(self.business_a, "Same", "Fade", 100, "Card")
        insert = next(call for call in db.queries[0].calls if call[0] == "insert")
        self.assertEqual(insert[1][0]["business_id"], self.business_a)
        with patch.object(dashboard_analytics_manager.LedgerManager, "get_transactions_for_range",
                          side_effect=lambda business_id, *_: [{"credit_amount": 100, "debit_amount": 0, "payment_method": "Card"}] if business_id == self.business_a else [{"credit_amount": 200, "debit_amount": 0, "payment_method": "Cash"}]):
            self.assertEqual(dashboard_analytics_manager.DashboardAnalyticsManager.get_dashboard_summary(self.business_a)["revenue"], 100)
            self.assertEqual(dashboard_analytics_manager.DashboardAnalyticsManager.get_dashboard_summary(self.business_b)["revenue"], 200)

    def test_report_and_reconciliation_receive_tenant(self):
        with patch.object(report_manager, "MonthlyReportGenerator") as reports, \
             patch.object(reconciliation_manager, "SmartBankReconciliationManager") as reconciliation:
            report_manager.ReportManager.generate_monthly_pdf(self.business_a, "A")
            reconciliation_manager.ReconciliationManager.reconcile_statement(self.business_b, "x.csv", b"date,amount\n", "month")
        reports.generate_monthly_pdf.assert_called_once_with(self.business_a, "A")
        reconciliation.reconcile_statement.assert_called_once_with(self.business_b, "x.csv", b"date,amount\n", "month")

    def test_transaction_history_and_bank_reconciliation_use_only_the_current_business(self):
        with patch.object(transaction_history.LedgerManager, "get_transactions_for_range", return_value=[]) as history_ledger, \
             patch.object(bank_reconciliation.LedgerManager, "get_recent_transactions", return_value=[]) as bank_ledger:
            history = transaction_history.get_transaction_history(self.business_a, "last_7_days")
            bank_reconciliation.SmartBankReconciliationManager.reconcile_statement(
                self.business_b, "statement.csv", b"date,amount\n2026-01-01,100\n")
        self.assertTrue(history["success"])
        self.assertEqual(history_ledger.call_args.args[0], self.business_a)
        self.assertEqual(bank_ledger.call_args.args[0], self.business_b)

    def test_cross_tenant_delete_is_not_exposed_by_the_dashboard(self):
        # Phase 1 exposes no tenant-record DELETE endpoint. The only DELETE verb
        # is the legacy-compatible unblock action, implemented as a scoped update.
        delete_routes = [route for route in dashboard_routes.router.routes if "DELETE" in route.methods]
        self.assertEqual([route.path for route in delete_routes], ["/dashboard/calendar/unblock/{slot_id}"])

    def test_no_modified_tenant_manager_has_unscoped_table_access(self):
        modules = [customer_manager, service_manager, booking_manager, availability_manager, ledger_manager]
        for module in modules:
            source = inspect.getsource(module)
            for section in source.split('supabase.table(')[1:]:
                self.assertIn('business_id', section.split('.execute()', 1)[0], module.__name__)

    def test_every_dashboard_route_requires_tenant_context(self):
        for route in dashboard_routes.router.routes:
            dependencies = route.dependant.dependencies
            self.assertTrue(any(dependency.call.__name__ == "get_tenant_context" for dependency in dependencies), route.path)


if __name__ == "__main__":
    unittest.main()
